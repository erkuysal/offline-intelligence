from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cache.redis import get_redis_client
from app.config import Settings, get_settings
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.document import Document, DocumentChunk, DocumentVersion
from app.models.user import User
from app.schemas.documents import (
    DocumentChunkRead,
    DocumentRead,
    DocumentSearchRequest,
    DocumentSearchResult,
    DocumentVersionRead,
)
from app.services.document_ingestion import process_document_ingestion
from app.services.document_ingestion_queue import enqueue_document_ingestion
from app.services.document_storage import delete_stored_file, store_upload
from app.services.embeddings import get_embedding_provider, search_document_chunks

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    file: UploadFile = File(...),
) -> Document:
    stored_document = await store_upload(
        file=file,
        storage_dir=settings.document_storage_dir,
        max_size_bytes=settings.max_upload_size_bytes,
    )
    document = db.scalar(
        select(Document).where(
            Document.owner_id == current_user.id,
            Document.original_filename == stored_document.original_filename,
        )
    )

    if document is not None and document.checksum_sha256 == stored_document.checksum_sha256:
        delete_stored_file(stored_document.storage_path)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate document upload",
        )

    if document is None:
        document = Document(
            owner_id=current_user.id,
            original_filename=stored_document.original_filename,
            content_type=stored_document.content_type,
            size_bytes=stored_document.size_bytes,
            storage_path=stored_document.storage_path,
            checksum_sha256=stored_document.checksum_sha256,
            version_number=1,
        )
        db.add(document)
    else:
        document.content_type = stored_document.content_type
        document.size_bytes = stored_document.size_bytes
        document.storage_path = stored_document.storage_path
        document.checksum_sha256 = stored_document.checksum_sha256
        document.version_number += 1
        document.status = "pending"
        document.ingestion_error = None
        document.chunk_count = 0

    db.commit()
    db.refresh(document)
    db.add(
        DocumentVersion(
            document_id=document.id,
            version_number=document.version_number,
            original_filename=stored_document.original_filename,
            content_type=stored_document.content_type,
            size_bytes=stored_document.size_bytes,
            storage_path=stored_document.storage_path,
            checksum_sha256=stored_document.checksum_sha256,
        )
    )
    db.commit()
    db.refresh(document)

    ingestion_mode = settings.document_ingestion_mode.strip().lower()
    if ingestion_mode == "redis":
        try:
            enqueue_document_ingestion(
                get_redis_client(),
                queue_name=settings.document_ingestion_queue_name,
                document_id=document.id,
            )
        except RedisError as exc:
            document.status = "failed"
            document.ingestion_error = "Ingestion queue is unavailable"
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Ingestion queue is unavailable",
            ) from exc
        return document

    if ingestion_mode != "sync":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unsupported document ingestion mode",
        )

    processed_document = process_document_ingestion(db, document.id, settings=settings)
    if processed_document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    return processed_document


@router.get("", response_model=list[DocumentRead])
def list_documents(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[Document]:
    statement = (
        select(Document)
        .where(Document.owner_id == current_user.id)
        .order_by(Document.created_at.desc())
    )
    return list(db.scalars(statement))


@router.get("/{document_id}", response_model=DocumentRead)
def get_document(
    document_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Document:
    document = db.get(Document, document_id)
    if document is None or document.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    return document


@router.get("/{document_id}/chunks", response_model=list[DocumentChunkRead])
def list_document_chunks(
    document_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[DocumentChunk]:
    document = db.get(Document, document_id)
    if document is None or document.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    return list(document.chunks)


@router.get("/{document_id}/versions", response_model=list[DocumentVersionRead])
def list_document_versions(
    document_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[DocumentVersion]:
    document = db.get(Document, document_id)
    if document is None or document.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    return list(document.versions)


@router.post("/search", response_model=list[DocumentSearchResult])
def search_documents(
    request: DocumentSearchRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[DocumentSearchResult]:
    results = search_document_chunks(
        db,
        owner_id=current_user.id,
        query=request.query,
        limit=request.limit,
        provider=get_embedding_provider(),
    )
    return [
        DocumentSearchResult(
            document_id=chunk.document_id,
            document_filename=chunk.document.original_filename,
            chunk_id=chunk.id,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            source_page=chunk.source_page,
            source_label=chunk.source_label,
            score=score,
        )
        for chunk, score in results
    ]


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    document = db.get(Document, document_id)
    if document is None or document.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    storage_paths = {version.storage_path for version in document.versions}
    storage_paths.add(document.storage_path)
    db.delete(document)
    db.commit()
    for storage_path in storage_paths:
        delete_stored_file(storage_path)

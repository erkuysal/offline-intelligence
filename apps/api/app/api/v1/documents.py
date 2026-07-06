from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.document import Document
from app.models.user import User
from app.schemas.documents import DocumentRead
from app.services.document_storage import delete_stored_file, store_upload

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
    document = Document(
        owner_id=current_user.id,
        original_filename=stored_document.original_filename,
        content_type=stored_document.content_type,
        size_bytes=stored_document.size_bytes,
        storage_path=stored_document.storage_path,
        checksum_sha256=stored_document.checksum_sha256,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    return document


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

    storage_path = document.storage_path
    db.delete(document)
    db.commit()
    delete_stored_file(storage_path)

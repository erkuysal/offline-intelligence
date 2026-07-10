from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.document import Document, DocumentChunk
from app.services.embeddings import EmbeddingError, embed_document_chunks, get_embedding_provider

DOCUMENT_STATUS_PENDING = "pending"
DOCUMENT_STATUS_PROCESSING = "processing"
DOCUMENT_STATUS_READY = "ready"
DOCUMENT_STATUS_FAILED = "failed"


class DocumentIngestionError(Exception):
    pass


@dataclass(frozen=True)
class TextChunk:
    content: str
    char_start: int
    char_end: int
    token_start: int
    token_end: int


def extract_text(document: Document) -> str:
    path = Path(document.storage_path)
    if document.content_type == "text/plain":
        return path.read_text(encoding="utf-8")

    if document.content_type == "application/pdf":
        return extract_pdf_text(path)

    raise DocumentIngestionError(f"Unsupported content type: {document.content_type}")


def extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]
    except ImportError as exc:
        raise DocumentIngestionError("PDF extraction requires pypdf") from exc

    try:
        reader = PdfReader(str(path))
        page_text = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise DocumentIngestionError("PDF text extraction failed") from exc

    return "\n\n".join(page_text)


def chunk_text(
    text: str,
    chunk_size_chars: int,
    overlap_chars: int,
) -> list[TextChunk]:
    normalized_text = text.strip()
    if not normalized_text:
        raise DocumentIngestionError("No extractable text found")

    if chunk_size_chars <= 0:
        raise ValueError("chunk_size_chars must be greater than zero")
    if overlap_chars < 0:
        raise ValueError("overlap_chars cannot be negative")
    if overlap_chars >= chunk_size_chars:
        raise ValueError("overlap_chars must be smaller than chunk_size_chars")

    chunks: list[TextChunk] = []
    text_length = len(normalized_text)
    start = 0

    while start < text_length:
        end = min(start + chunk_size_chars, text_length)
        if end < text_length:
            split_at = normalized_text.rfind("\n", start, end)
            if split_at <= start:
                split_at = normalized_text.rfind(" ", start, end)
            if split_at > start:
                end = split_at

        content = normalized_text[start:end].strip()
        if content:
            token_start = estimate_token_count(normalized_text[:start])
            token_end = token_start + estimate_token_count(content)
            chunks.append(
                TextChunk(
                    content=content,
                    char_start=start,
                    char_end=end,
                    token_start=token_start,
                    token_end=token_end,
                )
            )

        if end >= text_length:
            break

        start = max(end - overlap_chars, start + 1)
        while start < text_length and normalized_text[start].isspace():
            start += 1

    if not chunks:
        raise DocumentIngestionError("No extractable text found")

    return chunks


def estimate_token_count(text: str) -> int:
    # This is a rough boundary for storage and retrieval planning until tokenizer-aware chunking lands.
    return max(1, (len(text) + 3) // 4) if text else 0


def ingest_document(
    db: Session,
    document: Document,
    *,
    chunk_size_chars: int,
    overlap_chars: int,
) -> Document:
    document.status = DOCUMENT_STATUS_PROCESSING
    document.ingestion_error = None
    document.chunk_count = 0
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
    db.commit()
    db.refresh(document)

    try:
        text = extract_text(document)
        chunks = chunk_text(
            text,
            chunk_size_chars=chunk_size_chars,
            overlap_chars=overlap_chars,
        )
    except Exception as exc:
        document.status = DOCUMENT_STATUS_FAILED
        document.ingestion_error = str(exc)
        document.chunk_count = 0
        db.commit()
        db.refresh(document)
        return document

    for index, chunk in enumerate(chunks):
        db.add(
            DocumentChunk(
                document_id=document.id,
                chunk_index=index,
                content=chunk.content,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                token_start=chunk.token_start,
                token_end=chunk.token_end,
            )
        )

    document.status = DOCUMENT_STATUS_READY
    document.ingestion_error = None
    document.chunk_count = len(chunks)
    db.commit()
    db.refresh(document)
    return document


def process_document_ingestion(
    db: Session,
    document_id: int,
    *,
    settings: Settings,
) -> Document | None:
    document = db.get(Document, document_id)
    if document is None:
        return None

    document = ingest_document(
        db,
        document,
        chunk_size_chars=settings.document_chunk_size_chars,
        overlap_chars=settings.document_chunk_overlap_chars,
    )
    if document.status != DOCUMENT_STATUS_READY:
        return document

    try:
        embed_document_chunks(db, document, get_embedding_provider())
    except EmbeddingError as exc:
        document.status = DOCUMENT_STATUS_FAILED
        document.ingestion_error = str(exc)
        db.commit()

    db.refresh(document)
    return document

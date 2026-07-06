from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

ALLOWED_CONTENT_TYPES = {
    "application/pdf": ".pdf",
    "text/plain": ".txt",
}
CHUNK_SIZE_BYTES = 1024 * 1024


@dataclass(frozen=True)
class StoredDocument:
    original_filename: str
    content_type: str
    size_bytes: int
    storage_path: str
    checksum_sha256: str


async def store_upload(
    file: UploadFile,
    storage_dir: str,
    max_size_bytes: int,
) -> StoredDocument:
    content_type = file.content_type or ""
    expected_suffix = ALLOWED_CONTENT_TYPES.get(content_type)
    if expected_suffix is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF and TXT files are supported",
        )

    original_filename = Path(file.filename or "").name
    if not original_filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required",
        )

    original_suffix = Path(original_filename).suffix.lower()
    if original_suffix != expected_suffix:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File extension does not match content type",
        )

    target_dir = Path(storage_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{uuid4().hex}{expected_suffix}"

    digest = sha256()
    size_bytes = 0

    try:
        with target_path.open("wb") as output:
            while chunk := await file.read(CHUNK_SIZE_BYTES):
                size_bytes += len(chunk)
                if size_bytes > max_size_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail="File exceeds maximum allowed size",
                    )
                digest.update(chunk)
                output.write(chunk)
    except Exception:
        target_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    if size_bytes == 0:
        target_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File is empty",
        )

    return StoredDocument(
        original_filename=original_filename,
        content_type=content_type,
        size_bytes=size_bytes,
        storage_path=str(target_path),
        checksum_sha256=digest.hexdigest(),
    )


def delete_stored_file(storage_path: str) -> None:
    Path(storage_path).unlink(missing_ok=True)

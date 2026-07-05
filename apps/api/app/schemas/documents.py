from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    original_filename: str
    content_type: str
    size_bytes: int
    checksum_sha256: str
    status: str
    created_at: datetime
    updated_at: datetime


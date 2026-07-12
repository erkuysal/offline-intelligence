from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ServiceStatus = Literal["healthy", "degraded", "unavailable", "disabled"]
MetadataValue = str | int | float | bool | None


class ServiceHealthResponse(BaseModel):
    service: str
    status: ServiceStatus
    detail: str
    code: str | None = None
    checked_at: datetime
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class RetrievalRun(TimestampMixin, Base):
    __tablename__ = "retrieval_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    request_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    strategy: Mapped[str] = mapped_column(String(50), nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    query_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    query_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    filters: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, nullable=False)
    model_versions: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, nullable=False)
    candidates: Mapped[list[dict[str, object]]] = mapped_column(JSONB, default=list, nullable=False)
    selected_context: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
    )
    timings_ms: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, nullable=False)
    selection_metrics: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    candidate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    selected_context_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)

    owner: Mapped["User"] = relationship(back_populates="retrieval_runs")

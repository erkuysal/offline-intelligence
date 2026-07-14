from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    text: str
    user_id: int
    limit: int
    document_ids: tuple[int, ...] | None = None


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    document_id: int
    document_filename: str
    chunk_id: int
    chunk_index: int
    content: str
    source_page: int | None
    source_label: str | None
    char_start: int
    char_end: int
    raw_score: float
    normalized_score: float
    rank: int
    strategy: str
    strategy_ranks: dict[str, int] = field(default_factory=dict)
    strategy_scores: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    candidates: list[RetrievalCandidate]
    timings_ms: dict[str, float]
    diagnostics: dict[str, object] = field(default_factory=dict)


class RetrievalStrategy(Protocol):
    name: str

    def retrieve(self, db: Session, query: RetrievalQuery) -> RetrievalResult: ...

from typing import Literal

from app.config import Settings, get_settings
from app.retrieval.contracts import RetrievalStrategy
from app.retrieval.dense import DenseRetrievalStrategy
from app.retrieval.hybrid import HybridRetrievalStrategy
from app.retrieval.lexical import LexicalRetrievalStrategy
from app.retrieval.reranked import RerankedRetrievalStrategy
from app.services.embeddings import EmbeddingProvider
from app.services.rerankers import get_reranker_provider

RetrievalStrategyName = Literal["dense", "lexical", "hybrid", "reranked"]


def build_retrieval_strategy(
    name: RetrievalStrategyName,
    *,
    provider: EmbeddingProvider,
    settings: Settings,
) -> RetrievalStrategy:
    dense = DenseRetrievalStrategy(provider)
    if name == "dense":
        return dense

    lexical = LexicalRetrievalStrategy()
    if name == "lexical":
        return lexical

    hybrid = HybridRetrievalStrategy(
        dense,
        lexical,
        overfetch_multiplier=settings.hybrid_overfetch_multiplier,
        max_candidates_per_strategy=settings.hybrid_max_candidates_per_strategy,
        rrf_k=settings.hybrid_rrf_k,
    )
    if name == "hybrid":
        return hybrid
    return RerankedRetrievalStrategy(
        hybrid,
        get_reranker_provider(),
        candidate_limit=settings.reranker_candidate_limit,
    )


def retrieval_model_versions(
    strategy: RetrievalStrategyName,
    embedding_model: str,
    settings: Settings | None = None,
) -> dict[str, object]:
    versions: dict[str, object] = {}
    if strategy in {"dense", "hybrid", "reranked"}:
        versions["embedding"] = embedding_model
    if strategy in {"lexical", "hybrid", "reranked"}:
        versions["lexical"] = "postgresql-simple"
    if strategy == "reranked":
        resolved_settings = settings or get_settings()
        versions["reranker"] = (
            f"{resolved_settings.reranker_model}@{resolved_settings.reranker_model_revision}"
        )
    return versions

from typing import Literal

from app.config import Settings, get_settings
from app.retrieval.contracts import RetrievalStrategy
from app.retrieval.dense import DenseRetrievalStrategy
from app.retrieval.hybrid import HybridRetrievalStrategy
from app.retrieval.lexical import LexicalRetrievalStrategy
from app.retrieval.multi_query import MultiQueryRetrievalStrategy
from app.retrieval.reranked import RerankedRetrievalStrategy
from app.services.embeddings import EmbeddingProvider
from app.services.rerankers import get_reranker_provider
from app.services.query_rewriters import get_query_rewriter

RetrievalStrategyName = Literal["dense", "lexical", "hybrid", "reranked", "multi_query"]


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
    if name == "reranked":
        return RerankedRetrievalStrategy(
            hybrid,
            get_reranker_provider(),
            candidate_limit=settings.reranker_candidate_limit,
        )
    return MultiQueryRetrievalStrategy(
        hybrid,
        get_query_rewriter(),
        max_generated_variants=settings.multi_query_max_generated_variants,
        max_query_chars=settings.multi_query_max_query_chars,
        candidates_per_variant=settings.multi_query_candidates_per_variant,
        max_candidate_observations=settings.multi_query_max_candidate_observations,
        max_pipeline_ms=settings.multi_query_max_pipeline_ms,
        rrf_k=settings.multi_query_rrf_k,
    )


def retrieval_model_versions(
    strategy: RetrievalStrategyName,
    embedding_model: str,
    settings: Settings | None = None,
) -> dict[str, object]:
    versions: dict[str, object] = {}
    if strategy in {"dense", "hybrid", "reranked", "multi_query"}:
        versions["embedding"] = embedding_model
    if strategy in {"lexical", "hybrid", "reranked", "multi_query"}:
        versions["lexical"] = "postgresql-simple"
    if strategy == "reranked":
        resolved_settings = settings or get_settings()
        versions["reranker"] = (
            f"{resolved_settings.reranker_model}@{resolved_settings.reranker_model_revision}"
        )
    if strategy == "multi_query":
        resolved_settings = settings or get_settings()
        versions["query_rewriter"] = (
            f"{resolved_settings.query_rewrite_model}@"
            f"{resolved_settings.query_rewrite_model_revision}"
        )
    return versions

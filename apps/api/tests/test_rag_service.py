from app.retrieval import RetrievalCandidate, RetrievalResult
from app.schemas.chat import ChatCompletionRequest, ChatMessage
from app.services.rag import augment_chat_request, build_context


def make_candidate(content: str, chunk_index: int = 0) -> RetrievalCandidate:
    char_start = chunk_index * 100
    return RetrievalCandidate(
        document_id=1,
        document_filename="notes.txt",
        chunk_id=chunk_index + 1,
        chunk_index=chunk_index,
        content=content,
        source_page=None,
        source_label=None,
        char_start=char_start,
        char_end=char_start + len(content),
        raw_score=0.9,
        normalized_score=0.9,
        rank=chunk_index + 1,
        strategy="dense",
    )


def test_build_context_respects_character_budget() -> None:
    candidate = make_candidate("abcdefghijklmnopqrstuvwxyz")

    context, included = build_context([candidate], max_chars=45)

    assert len(context) == 45
    assert context.startswith("[Source 1: notes.txt, chunk 0]\n")
    assert len(included) == 1


def test_build_context_stops_when_next_heading_does_not_fit() -> None:
    first = make_candidate("short", chunk_index=0)
    second = make_candidate("another", chunk_index=1)

    context, included = build_context(
        [first, second],
        max_chars=len("[Source 1: notes.txt, chunk 0]\nshort"),
    )

    assert context.endswith("short")
    assert included == [first]


def test_augment_chat_request_preserves_candidate_order_filters_and_source_score(
    monkeypatch,
) -> None:
    candidates = [
        make_candidate("first passage", chunk_index=0),
        make_candidate("second passage", chunk_index=1),
    ]
    captured_queries = []

    class FakeStrategy:
        name = "dense"

        def retrieve(self, _db, query):
            captured_queries.append(query)
            return RetrievalResult(candidates=candidates, timings_ms={"strategy_total": 1.0})

    def build_strategy(_name, *, provider, settings):
        return FakeStrategy()

    monkeypatch.setattr("app.services.rag.build_retrieval_strategy", build_strategy)
    request = ChatCompletionRequest(
        messages=[ChatMessage(role="user", content="What is the policy?")],
        use_documents=True,
        document_ids=[7, 9],
        retrieval_limit=2,
    )
    settings = SimpleSettings(rag_retrieval_limit=5, rag_max_context_chars=1_000)

    result = augment_chat_request(
        object(),  # type: ignore[arg-type]
        owner_id=42,
        request=request,
        settings=settings,  # type: ignore[arg-type]
    )

    assert captured_queries[0].user_id == 42
    assert captured_queries[0].document_ids == (7, 9)
    assert [source.chunk_index for source in result.sources] == [0, 1]
    assert [source.score for source in result.sources] == [0.9, 0.9]
    assert result.request.messages[0].content.index("first passage") < (
        result.request.messages[0].content.index("second passage")
    )


class SimpleSettings:
    def __init__(self, *, rag_retrieval_limit: int, rag_max_context_chars: int) -> None:
        self.rag_retrieval_limit = rag_retrieval_limit
        self.rag_max_context_chars = rag_max_context_chars
        self.rag_max_context_chars_per_document = rag_max_context_chars
        self.rag_retrieval_strategy = "dense"
        self.retrieval_run_persistence_enabled = False

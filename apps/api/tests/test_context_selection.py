from app.retrieval import (
    RetrievalCandidate,
    relevant_context_retention,
    select_context,
)


def make_candidate(
    chunk_id: int,
    content: str,
    *,
    document_id: int = 1,
    chunk_index: int = 0,
    char_start: int = 0,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        document_id=document_id,
        document_filename=f"document-{document_id}.txt",
        chunk_id=chunk_id,
        chunk_index=chunk_index,
        content=content,
        source_page=None,
        source_label=f"passage-{chunk_id}",
        char_start=char_start,
        char_end=char_start + len(content),
        raw_score=1.0,
        normalized_score=1.0,
        rank=chunk_id,
        strategy="dense",
    )


def test_context_selection_removes_exact_duplicates_and_renumbers_sources() -> None:
    first = make_candidate(1, "same passage", document_id=1)
    duplicate = make_candidate(2, "same passage", document_id=2)
    unique = make_candidate(3, "unique passage", document_id=3)

    selection = select_context(
        [first, duplicate, unique],
        max_chars=1_000,
        max_chars_per_document=1_000,
    )

    assert [candidate.chunk_id for candidate in selection.candidates] == [1, 3]
    assert selection.metrics.exact_duplicates_removed == 1
    assert selection.context.count("[Source ") == 2
    assert "[Source 1:" in selection.context
    assert "[Source 2:" in selection.context
    assert "[Source 3:" not in selection.context


def test_context_selection_trims_overlapping_adjacent_chunks() -> None:
    first = make_candidate(1, "abcdefghij", chunk_index=0, char_start=0)
    adjacent = make_candidate(2, "ijklmno", chunk_index=1, char_start=8)

    selection = select_context(
        [first, adjacent],
        max_chars=1_000,
        max_chars_per_document=1_000,
    )

    assert [candidate.chunk_id for candidate in selection.candidates] == [1, 2]
    assert selection.metrics.overlap_chars_removed == 2
    assert selection.metrics.unique_chars == 15
    assert selection.metrics.considered_chars == 17
    assert selection.metrics.unique_context_ratio == round(15 / 17, 6)
    assert "abcdefghij" in selection.context
    assert "\nklmno" in selection.context
    assert "\nijklmno" not in selection.context


def test_context_selection_enforces_per_document_budget_without_starving_others() -> None:
    first = make_candidate(1, "abcdefghij", document_id=1, char_start=0)
    same_document = make_candidate(2, "klmnopqrst", document_id=1, char_start=10)
    other_document = make_candidate(3, "uvwxyz", document_id=2, char_start=0)

    selection = select_context(
        [first, same_document, other_document],
        max_chars=1_000,
        max_chars_per_document=5,
    )

    assert [candidate.chunk_id for candidate in selection.candidates] == [1, 3]
    assert "abcde" in selection.context
    assert "uvwxy" in selection.context
    assert "klmnopqrst" not in selection.context


def test_relevant_context_retention_measures_selected_relevant_chunks() -> None:
    selected = [make_candidate(1, "first"), make_candidate(3, "third")]

    assert relevant_context_retention(selected, {1, 2}) == 0.5
    assert relevant_context_retention(selected, set()) == 1.0

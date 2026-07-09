from types import SimpleNamespace

from app.services.rag import build_context


def make_chunk(content: str, chunk_index: int = 0):
    return SimpleNamespace(
        content=content,
        chunk_index=chunk_index,
        document=SimpleNamespace(original_filename="notes.txt"),
    )


def test_build_context_respects_character_budget() -> None:
    chunk = make_chunk("abcdefghijklmnopqrstuvwxyz")

    context, included = build_context([(chunk, 0.9)], max_chars=45)

    assert len(context) == 45
    assert context.startswith("[Source 1: notes.txt, chunk 0]\n")
    assert len(included) == 1


def test_build_context_stops_when_next_heading_does_not_fit() -> None:
    first = make_chunk("short", chunk_index=0)
    second = make_chunk("another", chunk_index=1)

    context, included = build_context([(first, 0.9), (second, 0.8)], max_chars=len(
        "[Source 1: notes.txt, chunk 0]\nshort"
    ))

    assert context.endswith("short")
    assert included == [(first, 0.9)]

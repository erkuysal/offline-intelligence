from dataclasses import asdict, dataclass

from app.retrieval.contracts import RetrievalCandidate


@dataclass(frozen=True, slots=True)
class ContextSelectionMetrics:
    input_candidate_count: int
    selected_candidate_count: int
    exact_duplicates_removed: int
    overlap_chars_removed: int
    considered_chars: int
    unique_chars: int
    selected_chars: int
    unique_context_ratio: float

    def as_dict(self) -> dict[str, int | float]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ContextSelection:
    context: str
    candidates: list[RetrievalCandidate]
    metrics: ContextSelectionMetrics


def select_context(
    candidates: list[RetrievalCandidate],
    *,
    max_chars: int,
    max_chars_per_document: int,
) -> ContextSelection:
    sections: list[str] = []
    selected: list[RetrievalCandidate] = []
    document_chars: dict[int, int] = {}
    covered_intervals: dict[int, list[tuple[int, int]]] = {}
    selected_contents: set[str] = set()
    used_chars = 0
    exact_duplicates_removed = 0
    overlap_chars_removed = 0
    considered_chars = 0
    unique_chars = 0
    selected_chars = 0

    for candidate in candidates:
        separator_chars = 2 if sections else 0
        source_number = len(selected) + 1
        heading = (
            f"[Source {source_number}: {candidate.document_filename}, "
            f"chunk {candidate.chunk_index}]"
        )
        available_total = max_chars - used_chars - len(heading) - 1 - separator_chars
        if available_total <= 0:
            break

        content_key = candidate.content.strip()
        considered_chars += len(candidate.content)
        if content_key in selected_contents:
            exact_duplicates_removed += 1
            continue

        segments = candidate_segments(candidate, covered_intervals.get(candidate.document_id, []))
        segment_chars = sum(end - start for start, end in segments)
        removed_overlap = max(0, len(candidate.content) - segment_chars)
        overlap_chars_removed += removed_overlap
        unique_chars += segment_chars
        if not segments:
            continue

        available_document = max_chars_per_document - document_chars.get(candidate.document_id, 0)
        content_budget = min(available_total, available_document)
        if content_budget <= 0:
            continue

        content, selected_intervals = render_segments(candidate, segments, content_budget)
        if not content:
            continue

        section = f"{heading}\n{content}"
        sections.append(section)
        selected.append(candidate)
        selected_contents.add(content_key)
        used_chars += len(section) + separator_chars
        selected_chars += len(content)
        document_chars[candidate.document_id] = (
            document_chars.get(candidate.document_id, 0) + len(content)
        )
        covered_intervals[candidate.document_id] = merge_intervals(
            [*covered_intervals.get(candidate.document_id, []), *selected_intervals]
        )

    unique_context_ratio = unique_chars / considered_chars if considered_chars else 1.0
    return ContextSelection(
        context="\n\n".join(sections),
        candidates=selected,
        metrics=ContextSelectionMetrics(
            input_candidate_count=len(candidates),
            selected_candidate_count=len(selected),
            exact_duplicates_removed=exact_duplicates_removed,
            overlap_chars_removed=overlap_chars_removed,
            considered_chars=considered_chars,
            unique_chars=unique_chars,
            selected_chars=selected_chars,
            unique_context_ratio=round(unique_context_ratio, 6),
        ),
    )


def candidate_segments(
    candidate: RetrievalCandidate,
    covered: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    if candidate.char_end <= candidate.char_start:
        return [(0, len(candidate.content))]
    source_length = candidate.char_end - candidate.char_start
    if source_length != len(candidate.content):
        return [(0, len(candidate.content))]
    return subtract_intervals((candidate.char_start, candidate.char_end), covered)


def render_segments(
    candidate: RetrievalCandidate,
    segments: list[tuple[int, int]],
    budget: int,
) -> tuple[str, list[tuple[int, int]]]:
    parts: list[str] = []
    selected_intervals: list[tuple[int, int]] = []
    remaining = budget
    uses_source_offsets = candidate.char_end - candidate.char_start == len(candidate.content)

    for start, end in segments:
        separator = "\n" if parts else ""
        if remaining <= len(separator):
            break
        take = min(end - start, remaining - len(separator))
        if take <= 0:
            break
        content_start = start - candidate.char_start if uses_source_offsets else start
        fragment = candidate.content[content_start : content_start + take]
        if not fragment:
            continue
        parts.append(f"{separator}{fragment}")
        selected_intervals.append((start, start + len(fragment)))
        remaining -= len(separator) + len(fragment)
        if len(fragment) < end - start:
            break
    return "".join(parts), selected_intervals


def subtract_intervals(
    interval: tuple[int, int],
    covered: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    remaining = [interval]
    for covered_start, covered_end in covered:
        next_remaining: list[tuple[int, int]] = []
        for start, end in remaining:
            if covered_end <= start or covered_start >= end:
                next_remaining.append((start, end))
                continue
            if covered_start > start:
                next_remaining.append((start, covered_start))
            if covered_end < end:
                next_remaining.append((covered_end, end))
        remaining = next_remaining
    return remaining


def merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def relevant_context_retention(
    selected: list[RetrievalCandidate],
    relevant_chunk_ids: set[int],
) -> float:
    if not relevant_chunk_ids:
        return 1.0
    selected_ids = {candidate.chunk_id for candidate in selected}
    return len(selected_ids & relevant_chunk_ids) / len(relevant_chunk_ids)

from __future__ import annotations

from array import array
import ctypes
from dataclasses import dataclass
from enum import IntEnum
from functools import lru_cache
import math
import os
from pathlib import Path
import sys
from typing import Protocol, Sequence, cast


EXPECTED_ABI_VERSION = 1
LIBRARY_ENVIRONMENT_VARIABLE = "OIH_VECTOR_LIBRARY"


class VectorStatus(IntEnum):
    OK = 0
    NULL_POINTER = 1
    ZERO_LENGTH = 2
    SIZE_OVERFLOW = 3
    ZERO_NORM = 4
    NON_FINITE = 5


class VectorSimilarityError(ValueError):
    def __init__(self, status: VectorStatus, operation: str) -> None:
        self.status = status
        self.operation = operation
        super().__init__(f"{operation} failed with native status {status.name.lower()}")


@dataclass(frozen=True)
class NativeCapabilities:
    backend: str
    abi_version: int | None
    build_info: str
    library_path: str | None
    fallback_reason: str | None


class NativeFunction(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(self, *args: object) -> int: ...


class NativeLibrary(Protocol):
    oih_vector_abi_version: NativeFunction
    oih_vector_build_info: NativeFunction
    oih_cosine_similarity_f32: NativeFunction
    oih_cosine_batch_f32: NativeFunction


def cosine_similarity_fallback(query: Sequence[float], row: Sequence[float]) -> float:
    if not query or len(query) != len(row):
        raise ValueError("cosine inputs must be non-empty and have equal dimensions")
    query_norm_squared = sum(value * value for value in query)
    row_norm_squared = sum(value * value for value in row)
    if query_norm_squared == 0 or row_norm_squared == 0:
        raise ValueError("cosine inputs must have non-zero norms")
    if not math.isfinite(query_norm_squared) or not math.isfinite(row_norm_squared):
        raise ValueError("cosine inputs must contain only finite values")
    dot = sum(left * right for left, right in zip(query, row, strict=True))
    if not math.isfinite(dot):
        raise ValueError("cosine result is non-finite")
    return dot / math.sqrt(query_norm_squared * row_norm_squared)


def cosine_batch_fallback(
    query: Sequence[float],
    rows: Sequence[Sequence[float]],
) -> list[float]:
    if not rows:
        raise ValueError("cosine batch must contain at least one row")
    if not query:
        raise ValueError("cosine query must be non-empty")
    query_norm_squared = sum(value * value for value in query)
    if query_norm_squared == 0:
        raise ValueError("cosine query must have a non-zero norm")
    if not math.isfinite(query_norm_squared):
        raise ValueError("cosine query must contain only finite values")
    query_norm = math.sqrt(query_norm_squared)
    scores: list[float] = []
    for row in rows:
        if len(row) != len(query):
            raise ValueError("cosine rows must match query dimensions")
        row_norm_squared = sum(value * value for value in row)
        if row_norm_squared == 0:
            raise ValueError("cosine rows must have non-zero norms")
        if not math.isfinite(row_norm_squared):
            raise ValueError("cosine rows must contain only finite values")
        dot = sum(left * right for left, right in zip(query, row, strict=True))
        if not math.isfinite(dot):
            raise ValueError("cosine result is non-finite")
        scores.append(dot / (query_norm * math.sqrt(row_norm_squared)))
    return scores


def default_library_path() -> Path:
    extension = ".dll" if sys.platform == "win32" else ".dylib" if sys.platform == "darwin" else ".so"
    return Path(__file__).with_name(f"liboih_vector_similarity{extension}")


def configured_library_path(library_path: Path | None = None) -> Path:
    if library_path is not None:
        return library_path.expanduser().absolute()
    configured = os.environ.get(LIBRARY_ENVIRONMENT_VARIABLE)
    if configured:
        return Path(configured).expanduser().absolute()
    return default_library_path()


@lru_cache(maxsize=8)
def load_native_library(library_path: Path) -> NativeLibrary:
    library = ctypes.CDLL(str(library_path))
    library.oih_vector_abi_version.argtypes = []
    library.oih_vector_abi_version.restype = ctypes.c_int
    library.oih_vector_build_info.argtypes = []
    library.oih_vector_build_info.restype = ctypes.c_char_p
    pointer = ctypes.POINTER(ctypes.c_float)
    library.oih_cosine_similarity_f32.argtypes = [pointer, pointer, ctypes.c_size_t, pointer]
    library.oih_cosine_similarity_f32.restype = ctypes.c_int
    library.oih_cosine_batch_f32.argtypes = [
        pointer,
        pointer,
        ctypes.c_size_t,
        ctypes.c_size_t,
        pointer,
    ]
    library.oih_cosine_batch_f32.restype = ctypes.c_int
    abi_version = int(library.oih_vector_abi_version())
    if abi_version != EXPECTED_ABI_VERSION:
        raise OSError(
            f"unsupported vector library ABI: expected {EXPECTED_ABI_VERSION}, found {abi_version}"
        )
    return cast(NativeLibrary, library)


def native_capabilities(library_path: Path | None = None) -> NativeCapabilities:
    path = configured_library_path(library_path)
    try:
        library = load_native_library(path)
    except OSError as exc:
        return NativeCapabilities(
            backend="python",
            abi_version=None,
            build_info="python_scalar",
            library_path=None,
            fallback_reason=str(exc),
        )
    raw_build_info = library.oih_vector_build_info()
    build_info = raw_build_info.decode("utf-8") if isinstance(raw_build_info, bytes) else "unknown"
    return NativeCapabilities(
        backend="native",
        abi_version=int(library.oih_vector_abi_version()),
        build_info=build_info,
        library_path=str(path),
        fallback_reason=None,
    )


def contiguous_f32(values: Sequence[float], *, label: str) -> array[float]:
    if not values:
        raise ValueError(f"{label} must be non-empty")
    converted = array("f")
    try:
        for value in values:
            converted.append(float(value))
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain float32-compatible values") from exc
    if any(not math.isfinite(value) for value in converted):
        raise ValueError(f"{label} must contain only finite values")
    return converted


def raise_for_status(status_value: int, operation: str) -> None:
    try:
        status = VectorStatus(status_value)
    except ValueError as exc:
        raise RuntimeError(f"{operation} returned unknown native status {status_value}") from exc
    if status is not VectorStatus.OK:
        raise VectorSimilarityError(status, operation)


def native_cosine_similarity(
    library: NativeLibrary,
    query: Sequence[float],
    row: Sequence[float],
) -> float:
    if len(query) != len(row):
        raise ValueError("cosine inputs must have equal dimensions")
    query_buffer = contiguous_f32(query, label="query")
    row_buffer = contiguous_f32(row, label="row")
    query_view = (ctypes.c_float * len(query_buffer)).from_buffer(query_buffer)
    row_view = (ctypes.c_float * len(row_buffer)).from_buffer(row_buffer)
    output = ctypes.c_float()
    status = library.oih_cosine_similarity_f32(
        query_view,
        row_view,
        len(query_buffer),
        ctypes.byref(output),
    )
    raise_for_status(status, "cosine_similarity")
    return float(output.value)


def native_cosine_batch(
    library: NativeLibrary,
    query: Sequence[float],
    rows: Sequence[Sequence[float]],
) -> list[float]:
    query_buffer, rows_buffer = prepare_contiguous_batch(query, rows)
    return invoke_native_cosine_batch_buffers(
        library,
        query_buffer,
        rows_buffer,
        row_count=len(rows),
    )


def prepare_contiguous_batch(
    query: Sequence[float],
    rows: Sequence[Sequence[float]],
) -> tuple[array[float], array[float]]:
    if not rows:
        raise ValueError("cosine batch must contain at least one row")
    query_buffer = contiguous_f32(query, label="query")
    flat_rows = array("f")
    for index, row in enumerate(rows):
        if len(row) != len(query_buffer):
            raise ValueError("cosine rows must match query dimensions")
        flat_rows.extend(contiguous_f32(row, label=f"row {index}"))
    return query_buffer, flat_rows


def invoke_native_cosine_batch_buffers(
    library: NativeLibrary,
    query_buffer: array[float],
    rows_buffer: array[float],
    *,
    row_count: int,
) -> list[float]:
    if query_buffer.typecode != "f" or rows_buffer.typecode != "f":
        raise ValueError("native cosine buffers must use float32 array typecode 'f'")
    if not query_buffer or row_count <= 0:
        raise ValueError("native cosine buffers must be non-empty")
    if len(rows_buffer) != row_count * len(query_buffer):
        raise ValueError("native cosine row buffer shape does not match dimensions")
    output = array("f", [0.0]) * row_count
    query_view = (ctypes.c_float * len(query_buffer)).from_buffer(query_buffer)
    rows_view = (ctypes.c_float * len(rows_buffer)).from_buffer(rows_buffer)
    output_view = (ctypes.c_float * len(output)).from_buffer(output)
    status = library.oih_cosine_batch_f32(
        query_view,
        rows_view,
        row_count,
        len(query_buffer),
        output_view,
    )
    raise_for_status(status, "cosine_batch")
    return output.tolist()


def cosine_batch_contiguous_fallback(
    query_buffer: array[float],
    rows_buffer: array[float],
    *,
    row_count: int,
) -> list[float]:
    if query_buffer.typecode != "f" or rows_buffer.typecode != "f":
        raise ValueError("contiguous cosine buffers must use float32 array typecode 'f'")
    if not query_buffer or row_count <= 0:
        raise ValueError("contiguous cosine buffers must be non-empty")
    dimensions = len(query_buffer)
    if len(rows_buffer) != row_count * dimensions:
        raise ValueError("contiguous cosine row buffer shape does not match dimensions")
    query_norm_squared = sum(value * value for value in query_buffer)
    if query_norm_squared == 0 or not math.isfinite(query_norm_squared):
        raise ValueError("contiguous cosine query must have a finite non-zero norm")
    query_norm = math.sqrt(query_norm_squared)
    scores: list[float] = []
    for row_index in range(row_count):
        offset = row_index * dimensions
        dot = 0.0
        row_norm_squared = 0.0
        for dimension_index in range(dimensions):
            query_value = query_buffer[dimension_index]
            row_value = rows_buffer[offset + dimension_index]
            dot += query_value * row_value
            row_norm_squared += row_value * row_value
        if row_norm_squared == 0 or not math.isfinite(row_norm_squared):
            raise ValueError("contiguous cosine rows must have finite non-zero norms")
        scores.append(dot / (query_norm * math.sqrt(row_norm_squared)))
    return scores


def cosine_batch_contiguous(
    query_buffer: array[float],
    rows_buffer: array[float],
    *,
    row_count: int,
    library_path: Path | None = None,
) -> list[float]:
    try:
        library = load_native_library(configured_library_path(library_path))
    except OSError:
        return cosine_batch_contiguous_fallback(
            query_buffer,
            rows_buffer,
            row_count=row_count,
        )
    return invoke_native_cosine_batch_buffers(
        library,
        query_buffer,
        rows_buffer,
        row_count=row_count,
    )


def cosine_similarity(
    query: Sequence[float],
    row: Sequence[float],
    *,
    library_path: Path | None = None,
) -> float:
    try:
        library = load_native_library(configured_library_path(library_path))
    except OSError:
        return cosine_similarity_fallback(query, row)
    return native_cosine_similarity(library, query, row)


def cosine_batch(
    query: Sequence[float],
    rows: Sequence[Sequence[float]],
    *,
    library_path: Path | None = None,
) -> list[float]:
    try:
        library = load_native_library(configured_library_path(library_path))
    except OSError:
        return cosine_batch_fallback(query, rows)
    return native_cosine_batch(library, query, rows)

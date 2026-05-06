"""Типы данных: сообщения очередей, состояние перетаскивания, результат валидации."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Any, Literal, Optional, Union

ErrorCode = Literal["not_file", "bad_ext", "not_readable"]


@dataclass(frozen=True)
class SeismicPreview:
    """Уменьшенная сетка амплитуд float32 (трассы × отсчёты) для отображения на «Главная»."""

    n_traces: int
    n_samples: int
    data: bytes


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    name: Optional[str] = None
    error: Optional[ErrorCode] = None
    path: Optional[str] = None
    preview: Optional[SeismicPreview] = None
    tracecount: Optional[int] = None
    samples_count: Optional[int] = None


@dataclass(frozen=True)
class LogicTaskValidateSeismic:
    path: str
    request_id: int


@dataclass(frozen=True)
class LogicTaskReadDataRange:
    path: str
    request_id: int
    start: int
    end: int
    step: int
    chunk_size: int
    max_full_matrix_bytes: int
    preview_target: int
    cancel_event: Event


@dataclass(frozen=True)
class LogicTaskProcessRange:
    path: str
    request_id: int
    start: int
    end: int
    step: int
    method_ids: tuple[str, ...]
    chunk_size: int
    preview_target: int
    cancel_event: Event


@dataclass(frozen=True)
class UiMessageValidateResult:
    request_id: int
    result: ValidationResult


@dataclass(frozen=True)
class UiMessageReadDataProgress:
    request_id: int
    processed: int
    total: int


@dataclass(frozen=True)
class UiMessageReadDataResult:
    request_id: int
    start: int
    end: int
    step: int
    selected_traces: int
    n_samples: int
    max_abs: float
    full_matrix: Optional[Any]
    preview_matrix: Any
    preview_matrix_norm: Any
    keep_full_matrix: bool


@dataclass(frozen=True)
class UiMessageProcessProgress:
    request_id: int
    processed: int
    total: int
    from_trace: int
    to_trace: int


@dataclass(frozen=True)
class UiMessageProcessResult:
    request_id: int
    start: int
    end: int
    step: int
    method_ids: tuple[str, ...]
    max_abs: float
    before_preview: Any
    after_preview: Any
    before_preview_norm: Any
    after_preview_norm: Any


@dataclass(frozen=True)
class UiMessageWorkerError:
    request_id: int
    message: str


UiMessage = Union[
    UiMessageValidateResult,
    UiMessageReadDataProgress,
    UiMessageReadDataResult,
    UiMessageProcessProgress,
    UiMessageProcessResult,
    UiMessageWorkerError,
]


@dataclass
class PipeDragState:
    idx: int
    mid: str
    x0: int
    y0: int
    moved: bool
    row: Any
    title_lbl: Any
    visual_on: bool
    hl_row: Optional[Any]
    ghost: Optional[Any]
    goffs: tuple[int, int]
    ghost_w: int

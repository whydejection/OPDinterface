"""Фоновый поток: задачи без доступа к виджетам Tk."""

from __future__ import annotations

import logging
import queue
from typing import Any

from models import (
    LogicTaskProcessRange,
    LogicTaskReadDataRange,
    LogicTaskValidateSeismic,
    UiMessageProcessProgress,
    UiMessageProcessResult,
    UiMessageReadDataProgress,
    UiMessageReadDataResult,
    UiMessageValidateResult,
    UiMessageWorkerError,
    ValidationResult,
)

from .seismic import (
    load_segy_preview,
    process_range_streaming,
    read_data_range_streaming,
    read_segy_meta,
    validate_seismic_file,
)

LOG = logging.getLogger(__name__)

LOGIC_STOP = object()


def logic_worker_main(task_queue: queue.Queue, ui_queue: queue.Queue) -> None:
    while True:
        task: Any = task_queue.get()
        if task is LOGIC_STOP:
            break
        if isinstance(task, LogicTaskValidateSeismic):
            try:
                result = validate_seismic_file(task.path)
                if result.ok and result.path:
                    preview = load_segy_preview(result.path)
                    meta = read_segy_meta(result.path)
                    tc = meta[0] if meta else None
                    sc = meta[1] if meta else None
                    result = ValidationResult(
                        ok=True,
                        name=result.name,
                        path=result.path,
                        preview=preview,
                        tracecount=tc,
                        samples_count=sc,
                    )
                ui_queue.put(UiMessageValidateResult(request_id=task.request_id, result=result))
            except Exception:
                LOG.exception("Ошибка в задаче validate_seismic")
                ui_queue.put(
                    UiMessageWorkerError(
                        request_id=task.request_id,
                        message="Внутренняя ошибка при проверке файла",
                    )
                )
        elif isinstance(task, LogicTaskReadDataRange):
            try:
                def on_progress(done: int, total: int) -> None:
                    ui_queue.put(
                        UiMessageReadDataProgress(
                            request_id=task.request_id,
                            processed=done,
                            total=total,
                        )
                    )

                res = read_data_range_streaming(
                    task.path,
                    task.start,
                    task.end,
                    task.step,
                    chunk_size=task.chunk_size,
                    max_full_matrix_bytes=task.max_full_matrix_bytes,
                    preview_target=task.preview_target,
                    progress_cb=on_progress,
                    cancel_event=task.cancel_event,
                )
                ui_queue.put(
                    UiMessageReadDataResult(
                        request_id=task.request_id,
                        start=task.start,
                        end=task.end,
                        step=task.step,
                        selected_traces=int(res["selected_traces"]),
                        n_samples=int(res["n_samples"]),
                        max_abs=float(res["max_abs"]),
                        full_matrix=res["full_matrix"],
                        preview_matrix=res["preview_matrix"],
                        keep_full_matrix=bool(res["keep_full_matrix"]),
                    )
                )
            except RuntimeError as ex:
                if str(ex) == "cancelled":
                    ui_queue.put(
                        UiMessageWorkerError(
                            request_id=task.request_id,
                            message="Операция отменена",
                        )
                    )
                else:
                    ui_queue.put(
                        UiMessageWorkerError(
                            request_id=task.request_id,
                            message=f"Ошибка чтения диапазона: {ex}",
                        )
                    )
            except Exception:
                LOG.exception("Ошибка в задаче read_data_range")
                ui_queue.put(
                    UiMessageWorkerError(
                        request_id=task.request_id,
                        message="Внутренняя ошибка при чтении диапазона",
                    )
                )
        elif isinstance(task, LogicTaskProcessRange):
            try:
                def on_progress(done: int, total: int, from_trace: int, to_trace: int) -> None:
                    ui_queue.put(
                        UiMessageProcessProgress(
                            request_id=task.request_id,
                            processed=done,
                            total=total,
                            from_trace=from_trace,
                            to_trace=to_trace,
                        )
                    )

                res = process_range_streaming(
                    task.path,
                    task.start,
                    task.end,
                    task.step,
                    task.method_ids,
                    chunk_size=task.chunk_size,
                    preview_target=task.preview_target,
                    progress_cb=on_progress,
                    cancel_event=task.cancel_event,
                )
                ui_queue.put(
                    UiMessageProcessResult(
                        request_id=task.request_id,
                        start=task.start,
                        end=task.end,
                        step=task.step,
                        method_ids=task.method_ids,
                        max_abs=float(res["max_abs"]),
                        before_preview=res["before_preview"],
                        after_preview=res["after_preview"],
                    )
                )
            except RuntimeError as ex:
                if str(ex) == "cancelled":
                    ui_queue.put(
                        UiMessageWorkerError(
                            request_id=task.request_id,
                            message="Операция обработки отменена",
                        )
                    )
                else:
                    ui_queue.put(
                        UiMessageWorkerError(
                            request_id=task.request_id,
                            message=f"Ошибка обработки: {ex}",
                        )
                    )
            except Exception:
                LOG.exception("Ошибка в задаче process_range")
                ui_queue.put(
                    UiMessageWorkerError(
                        request_id=task.request_id,
                        message="Внутренняя ошибка при обработке диапазона",
                    )
                )

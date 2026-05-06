"""Чистая логика проверки сейсмического файла (без GUI)."""

from __future__ import annotations

import logging
import os
from threading import Event
from typing import Optional

from models import SeismicPreview, ValidationResult

LOG = logging.getLogger(__name__)
_INTERP_SESSION = None
_INTERP_IO_NAMES: Optional[tuple[str, str]] = None
_INTERP_UNAVAILABLE = False


def _segyio_path(path: str) -> str:
    """Путь для segyio на Windows: пробуем короткий 8.3, если есть кириллица."""
    if os.name != "nt":
        return path
    if all(ord(ch) < 128 for ch in path):
        return path
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(32768)
        n = ctypes.windll.kernel32.GetShortPathNameW(path, buf, len(buf))
        if n > 0:
            return str(buf.value)
    except Exception:
        pass
    return path


def _ensure_interp_session():
    """Ленивая инициализация ONNX-модели интерполяции."""
    global _INTERP_SESSION, _INTERP_IO_NAMES, _INTERP_UNAVAILABLE
    if _INTERP_UNAVAILABLE:
        return None
    if _INTERP_SESSION is not None:
        return _INTERP_SESSION
    try:
        import onnxruntime as ort
    except Exception:
        LOG.warning("onnxruntime недоступен — метод interp работает как passthrough")
        _INTERP_UNAVAILABLE = True
        return None

    # Поиск модели без привязки к конкретному ПК/пользователю.
    env_model = (os.environ.get("OPD_INTERP_MODEL") or "").strip()
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    candidates = []
    if env_model:
        candidates.append(env_model)
    candidates.extend(
        [
            os.path.join(base_dir, "models", "swin_transformer.onnx"),
            os.path.join(base_dir, "Методы", "swin_transformer.onnx"),
            os.path.join(base_dir, "methods", "swin_transformer.onnx"),
            os.path.join(os.getcwd(), "models", "swin_transformer.onnx"),
            os.path.join(os.getcwd(), "Методы", "swin_transformer.onnx"),
            os.path.join(os.getcwd(), "methods", "swin_transformer.onnx"),
        ]
    )
    model_path = ""
    for cand in candidates:
        p = os.path.abspath(os.path.normpath(cand))
        if os.path.isfile(p):
            model_path = p
            break
    model_path = _segyio_path(model_path) if model_path else ""
    if not os.path.isfile(model_path):
        LOG.warning(
            "Файл модели интерполяции не найден. Ищем через OPD_INTERP_MODEL "
            "или в ./project/models|Методы|methods."
        )
        _INTERP_UNAVAILABLE = True
        return None
    try:
        sess = ort.InferenceSession(model_path)
        in_name = sess.get_inputs()[0].name
        out_name = sess.get_outputs()[0].name
        _INTERP_SESSION = sess
        _INTERP_IO_NAMES = (in_name, out_name)
        LOG.info("ONNX интерполяция активирована: %s", model_path)
        return _INTERP_SESSION
    except Exception:
        LOG.exception("Не удалось загрузить ONNX-модель интерполяции: %s", model_path)
        _INTERP_UNAVAILABLE = True
        return None


def _apply_interp_onnx(arr):
    import numpy as np

    sess = _ensure_interp_session()
    if sess is None or _INTERP_IO_NAMES is None:
        return arr

    if arr.ndim != 2 or arr.size == 0:
        return arr

    in_name, out_name = _INTERP_IO_NAMES
    h, w = int(arr.shape[0]), int(arr.shape[1])
    patch = 128
    out = np.empty((h, w), dtype=np.float32)

    for y0 in range(0, h, patch):
        for x0 in range(0, w, patch):
            y1 = min(y0 + patch, h)
            x1 = min(x0 + patch, w)
            tile = arr[y0:y1, x0:x1].astype(np.float32, copy=False)
            if tile.shape != (patch, patch):
                padded = np.zeros((patch, patch), dtype=np.float32)
                padded[: tile.shape[0], : tile.shape[1]] = tile
                tile = padded
            inp = tile[np.newaxis, np.newaxis, :, :]
            try:
                pred = sess.run([out_name], {in_name: inp})[0]
                rec = np.asarray(pred, dtype=np.float32)[0, 0]
                out[y0:y1, x0:x1] = rec[: y1 - y0, : x1 - x0]
            except Exception:
                LOG.exception("Ошибка ONNX-интерполяции патча [%s:%s, %s:%s]", y0, y1, x0, x1)
                out[y0:y1, x0:x1] = arr[y0:y1, x0:x1]
    return out


def validate_seismic_file(path: str) -> ValidationResult:
    path = os.path.abspath(os.path.normpath(path))
    if not os.path.isfile(path):
        return ValidationResult(ok=False, error="not_file")
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".sgy", ".segy"):
        return ValidationResult(ok=False, error="bad_ext")
    return ValidationResult(ok=True, name=os.path.basename(path), path=path)


def read_segy_meta(path: str) -> Optional[tuple[int, int]]:
    """Число трасс и отсчётов на трассу (как в testtrass: tracecount, len(samples))."""
    try:
        import segyio

        with segyio.open(_segyio_path(path), "r", ignore_geometry=True, strict=False) as f:
            return int(f.tracecount), int(len(f.samples))
    except Exception:
        LOG.exception("read_segy_meta: %s", path)
        return None


def load_segy_preview(
    path: str,
    max_traces: int = 512,
    max_samples: int = 1024,
) -> Optional[SeismicPreview]:
    """Читает SEG-Y и строит компактную сетку амплитуд для imshow (фоновый поток)."""
    try:
        import numpy as np
        import segyio
    except ImportError:
        LOG.warning("segyio/numpy недоступны — превью сейсмики отключено")
        return None

    try:
        with segyio.open(_segyio_path(path), "r", strict=False, ignore_geometry=True) as f:
            n_tr = int(f.tracecount)
            if n_tr <= 0:
                return None
            ns_hdr = int(len(f.samples))
            if ns_hdr <= 0:
                return None

            block = None
            try:
                raw = np.asarray(f.trace.raw, dtype=np.float32)
                if raw.ndim == 2 and raw.shape[0] > 0 and raw.shape[1] > 0:
                    n_rows = min(n_tr, raw.shape[0])
                    n_cols = min(ns_hdr, raw.shape[1])
                    mtx = raw[:n_rows, :n_cols]
                    nt = min(max_traces, mtx.shape[0])
                    ns_out = min(max_samples, mtx.shape[1])
                    t_idx = np.linspace(0, mtx.shape[0] - 1, num=nt, dtype=np.intp)
                    s_idx = np.linspace(0, mtx.shape[1] - 1, num=ns_out, dtype=np.intp)
                    block = mtx[t_idx][:, s_idx].astype(np.float32, copy=True)
            except Exception:
                LOG.debug("trace.raw для превью недоступен, пробуем по трассам", exc_info=True)

            if block is None:
                probe = min(n_tr, 32)
                ns = min(int(len(f.trace[i])) for i in range(probe))
                if ns <= 0:
                    return None
                nt = min(max_traces, n_tr)
                ns_out = min(max_samples, ns)
                t_idx = np.linspace(0, n_tr - 1, num=nt, dtype=np.int64)
                s_idx = np.linspace(0, ns - 1, num=ns_out, dtype=np.int64)
                block = np.empty((nt, ns_out), dtype=np.float32)
                for ir, ti in enumerate(t_idx):
                    tr = np.asarray(f.trace[int(ti)], dtype=np.float32)[:ns]
                    block[ir, :] = tr[s_idx.astype(int)]

            flat = np.abs(block).ravel()
            p98 = float(np.percentile(flat, 98.0)) if flat.size else 1.0
            if p98 <= 0.0:
                p98 = 1.0
            block = np.clip(block / p98, -1.0, 1.0)

            return SeismicPreview(
                n_traces=int(block.shape[0]),
                n_samples=int(block.shape[1]),
                data=block.tobytes(),
            )
    except Exception:
        LOG.exception("Не удалось прочитать SEG-Y для превью: %s", path)
        return None


def reorder_pipeline(seq: list[str], from_i: int, to_i: int) -> None:
    """Переставить элемент списка на место to_i (на месте, как insert после pop)."""
    if not (0 <= from_i < len(seq) and 0 <= to_i < len(seq)):
        return
    item = seq.pop(from_i)
    seq.insert(to_i, item)


def read_data_range_streaming(
    path: str,
    start: int,
    end: int,
    step: int,
    *,
    chunk_size: int = 5000,
    max_full_matrix_bytes: int = 512 * 1024 * 1024,
    preview_target: int = 512,
    progress_cb=None,
    cancel_event: Optional[Event] = None,
):
    """Потоковое чтение диапазона трасс: full matrix (если влезает) + preview matrix."""
    import numpy as np
    import segyio

    selected_traces = len(range(start, end, step))
    if selected_traces <= 0:
        raise ValueError("Выбран пустой диапазон данных.")

    with segyio.open(_segyio_path(path), "r", ignore_geometry=True, strict=False) as f:
        n_samples = int(len(f.samples))
        est_bytes = selected_traces * n_samples * 4
        keep_full_matrix = est_bytes <= max_full_matrix_bytes

        full_chunks: list[np.ndarray] = []
        max_abs = 0.0

        preview_target = max(1, min(preview_target, selected_traces))
        preview_idx = np.linspace(0, selected_traces - 1, num=preview_target, dtype=np.int64)
        preview_cursor = 0
        preview_rows: list[np.ndarray] = []

        processed = 0
        for offset in range(0, selected_traces, chunk_size):
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("cancelled")

            part_end = min(offset + chunk_size, selected_traces)
            from_trace = start + offset * step
            to_trace = start + part_end * step
            chunk_matrix = np.asarray(f.trace.raw[from_trace:to_trace:step], dtype=np.float32)
            if chunk_matrix.ndim != 2 or chunk_matrix.size == 0:
                processed += (part_end - offset)
                if progress_cb is not None:
                    progress_cb(processed, selected_traces)
                continue

            chunk_max = float(np.max(np.abs(chunk_matrix)))
            if chunk_max > max_abs:
                max_abs = chunk_max

            if keep_full_matrix:
                full_chunks.append(chunk_matrix)

            while preview_cursor < len(preview_idx) and int(preview_idx[preview_cursor]) < part_end:
                local_row = int(preview_idx[preview_cursor]) - offset
                if 0 <= local_row < chunk_matrix.shape[0]:
                    preview_rows.append(chunk_matrix[local_row : local_row + 1, :])
                preview_cursor += 1

            processed += (part_end - offset)
            if progress_cb is not None:
                progress_cb(processed, selected_traces)

        full_matrix = (
            np.concatenate(full_chunks, axis=0) if keep_full_matrix and full_chunks else None
        )
        preview_matrix = (
            np.concatenate(preview_rows, axis=0) if preview_rows else np.empty((0, 0), dtype=np.float32)
        )

        return {
            "selected_traces": selected_traces,
            "n_samples": n_samples,
            "max_abs": max_abs,
            "full_matrix": full_matrix,
            "preview_matrix": preview_matrix,
            "keep_full_matrix": keep_full_matrix,
        }


def _apply_pipeline_method(chunk, method_id: str):
    import numpy as np

    arr = np.asarray(chunk, dtype=np.float32)
    if method_id == "interp":
        return _apply_interp_onnx(arr)
    if method_id == "denoise":
        if arr.ndim != 2 or arr.shape[1] < 3:
            return arr
        out = arr.copy()
        out[:, 1:-1] = (arr[:, :-2] + arr[:, 1:-1] + arr[:, 2:]) / 3.0
        return out
    if method_id == "spectrum":
        return np.clip(arr * 1.1, -1.0e9, 1.0e9)
    if method_id == "resolution":
        if arr.ndim != 2 or arr.shape[1] < 3:
            return arr
        out = arr.copy()
        mid = arr[:, 1:-1]
        out[:, 1:-1] = mid + 0.25 * (mid - (arr[:, :-2] + arr[:, 2:]) * 0.5)
        return out
    return arr


def process_range_streaming(
    path: str,
    start: int,
    end: int,
    step: int,
    method_ids: tuple[str, ...],
    *,
    chunk_size: int = 1000,
    preview_target: int = 512,
    progress_cb=None,
    cancel_event: Optional[Event] = None,
):
    import numpy as np
    import segyio

    selected_traces = len(range(start, end, step))
    if selected_traces <= 0:
        raise ValueError("Выбран пустой диапазон данных.")

    preview_target = max(1, min(preview_target, selected_traces))
    preview_idx = np.linspace(0, selected_traces - 1, num=preview_target, dtype=np.int64)
    preview_cursor = 0
    preview_before_rows: list[np.ndarray] = []
    preview_after_rows: list[np.ndarray] = []
    processed = 0
    max_abs = 0.0

    with segyio.open(_segyio_path(path), "r", ignore_geometry=True, strict=False) as f:
        total_traces_in_file = int(f.tracecount)
        if total_traces_in_file <= 0:
            raise ValueError("В файле нет трасс для обработки.")

        for offset in range(0, selected_traces, chunk_size):
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("cancelled")

            part_end = min(offset + chunk_size, selected_traces)
            from_trace = start + offset * step
            to_trace = start + part_end * step
            current_chunk = np.asarray(f.trace.raw[from_trace:to_trace:step], dtype=np.float32)
            source_chunk = current_chunk.copy()

            for method_id in method_ids:
                current_chunk = _apply_pipeline_method(current_chunk, method_id)

            if current_chunk.size > 0:
                max_abs = max(max_abs, float(np.max(np.abs(current_chunk))))

            while preview_cursor < len(preview_idx) and int(preview_idx[preview_cursor]) < part_end:
                local_row = int(preview_idx[preview_cursor]) - offset
                if 0 <= local_row < current_chunk.shape[0]:
                    preview_before_rows.append(source_chunk[local_row : local_row + 1, :])
                    preview_after_rows.append(current_chunk[local_row : local_row + 1, :])
                preview_cursor += 1

            processed += (part_end - offset)
            if progress_cb is not None:
                progress_cb(processed, selected_traces, from_trace, to_trace)

    before_plot = (
        np.concatenate(preview_before_rows, axis=0) if preview_before_rows else np.empty((0, 0), dtype=np.float32)
    )
    after_plot = (
        np.concatenate(preview_after_rows, axis=0) if preview_after_rows else np.empty((0, 0), dtype=np.float32)
    )
    return {
        "max_abs": max_abs,
        "before_preview": before_plot,
        "after_preview": after_plot,
    }

"""Главное окно: только главный поток трогает виджеты Tk."""

from __future__ import annotations

import queue
import locale
import threading
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Optional

import customtkinter as ctk

import constants as C
from ui.settings import load_settings, save_settings
from dnd_utils import iter_ctk_drop_surfaces, parse_dropped_file_paths
from logic import LOGIC_STOP, logic_worker_main
from logic.seismic import reorder_pipeline
from models import (
    LogicTaskProcessRange,
    LogicTaskReadDataRange,
    LogicTaskValidateSeismic,
    PipeDragState,
    SeismicPreview,
    UiMessageProcessProgress,
    UiMessageProcessResult,
    UiMessageReadDataProgress,
    UiMessageReadDataResult,
    UiMessageValidateResult,
    UiMessageWorkerError,
)

try:
    from tkinterdnd2 import COPY, DND_FILES, TkinterDnD
except ImportError:
    COPY = None
    DND_FILES = None
    TkinterDnD = None


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        if TkinterDnD is not None:
            try:
                TkinterDnD._require(self)
            except Exception:
                pass
            self._diagnose_dnd_windows()

        self.title("Seismic Data Suite")
        self.minsize(640, 480)
        self.configure(fg_color=C.WINDOW_BG)
        self._apply_fullscreen_geometry()

        self.current_state: dict[str, str] = {
            "tab": "Файл",
            "theme": "System",
            "scale": "100%",
            "scheme": C.SCHEME_CLASSIC,
            "plot_mode": C.PLOT_MODE_IMAGE,
        }
        self.history_tabs: list[str] = ["Файл"]
        self.history_index = 0
        self.is_navigating = False
        self._dnd_leave_timer: Optional[str] = None
        self.analysis_pipeline: list[str] = []
        self._pipe_drag: Optional[PipeDragState] = None
        self._is_resizing: bool = False

        self.current_file_path: Optional[str] = None
        self._load_request_id = 0
        self._applied_theme: Optional[str] = None
        self._applied_scale: Optional[str] = None
        self._applied_scheme: Optional[str] = None
        self._file_loading: bool = False
        self._suspend_checkbox_cmd: bool = False

        self.total_traces: int = 0
        self.samples_count: int = 0
        self.matrix_data: Any = None
        self._home_selection_patch: Any = None
        self._home_selection_patches: list[Any] = []
        self._home_selected_ranges: list[tuple[int, int]] = []
        self._home_drag_anchor: Optional[int] = None
        self._home_ctrl_down: bool = False
        self._home_view_start: int = 0
        self._home_view_end: int = 0
        self._home_view_step: int = 1
        self._home_window_size: int = 500
        self._home_window_request_id: int = 0
        self._home_window_cancel: Optional[threading.Event] = None
        self._home_window_after: Optional[str] = None
        self._home_window_start: int = 0
        self._home_window_target: int = 0
        self._home_window_last: Optional[tuple[int, int]] = None
        self._home_locked_by_selection: bool = False
        self._home_btn_clear_selection: Any = None
        self.home_slider_status: Any = None
        self._home_amp_gain: float = 1.0
        self._home_amp_var: Optional[tk.StringVar] = None
        self._home_scroll_widget: Any = None
        self._plot_popups: dict[str, Any] = {}
        self._analysis_export_source: Any = None
        self._data_read_request_id: int = 0
        self._data_read_cancel: Optional[threading.Event] = None
        self._data_range_cache: dict[tuple[str, int, int, int, int], dict[str, Any]] = {}
        self._process_request_id: int = 0
        self._process_cancel: Optional[threading.Event] = None

        self._shutdown = False
        self._ui_poll_id: Optional[str] = None
        self._logic_queue: queue.Queue = queue.Queue()
        self._ui_queue: queue.Queue = queue.Queue()
        self._logic_thread = threading.Thread(
            target=logic_worker_main,
            args=(self._logic_queue, self._ui_queue),
            name="AppLogic",
            daemon=True,
        )
        self._logic_thread.start()

        self.top_container = ctk.CTkFrame(self, fg_color=C.TOPBAR_BG, corner_radius=0)
        self.top_container.pack(fill="x", padx=12, pady=(8, 4))

        self.logo_wave = ctk.CTkLabel(
            self.top_container,
            text="≋",
            font=(C.FONT_LOGO[0], 26, "bold"),
            text_color=C.ACCENT,
            width=28,
        )
        self.logo_wave.pack(side="left", padx=(4, 2))
        self.logo_label = ctk.CTkLabel(
            self.top_container,
            text="SEIS",
            font=C.FONT_LOGO,
            text_color=C.ACCENT,
        )
        self.logo_label.pack(side="left", padx=(0, 12))

        self.nav_frame = ctk.CTkFrame(self.top_container, fg_color="transparent")
        self.nav_frame.pack(side="left")

        self.btn_back = ctk.CTkButton(
            self.nav_frame,
            text="←",
            width=34,
            height=32,
            corner_radius=6,
            fg_color=C.NAV_BTN_FG,
            hover_color=C.NAV_BTN_HOVER,
            text_color=C.NAV_BTN_TEXT,
            command=self.go_back,
        )
        self.btn_back.pack(side="left", padx=2)
        self.btn_forward = ctk.CTkButton(
            self.nav_frame,
            text="→",
            width=34,
            height=32,
            corner_radius=6,
            fg_color=C.NAV_BTN_FG,
            hover_color=C.NAV_BTN_HOVER,
            text_color=C.NAV_BTN_TEXT,
            command=self.go_forward,
        )
        self.btn_forward.pack(side="left", padx=2)

        self.tab_buttons: dict[str, ctk.CTkButton] = {}
        self.tabs_list = ["Файл", "Главная", "Анализ", "Вид"]
        for name in self.tabs_list:
            btn = ctk.CTkButton(
                self.top_container,
                text=name,
                width=88,
                height=32,
                corner_radius=C.TAB_CORNER_RADIUS,
                border_width=0,
                fg_color=C.TAB_INACTIVE_FG,
                text_color=C.TAB_INACTIVE_TEXT,
                hover_color=C.TAB_HOVER,
                command=lambda n=name: self.save_state(n),
            )
            btn.pack(side="left", padx=3, pady=2)
            self.tab_buttons[name] = btn

        self.ribbon = ctk.CTkFrame(
            self,
            height=C.RIBBON_HEIGHT_DEFAULT,
            corner_radius=0,
            border_width=0,
            fg_color="transparent",
        )
        self.ribbon.pack(fill="x", padx=C.RIBBON_OUTER_PADX, pady=(2, 0))
        self.ribbon.pack_propagate(False)
        self._ribbon_stack = ctk.CTkFrame(self.ribbon, fg_color="transparent")
        self._ribbon_stack.pack(fill="both", expand=True)

        self._resize_after_id: Optional[str] = None
        self.bind("<Configure>", self._on_root_configure, add="+")

        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=C.RIBBON_OUTER_PADX, pady=(8, 10))
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

        self.frames: dict[str, ctk.CTkFrame] = {}
        for name in self.tabs_list:
            frame = ctk.CTkFrame(self.container, fg_color="transparent")
            self.frames[name] = frame
            frame.grid(row=0, column=0, sticky="nsew")

        self.setup_file_page()
        self.setup_ribbon_tools()
        self.setup_analysis_page()
        self.setup_view_settings()
        self.setup_home_page()

        self._setup_status_bar()
        self._load_persisted_settings()
        self.apply_state(self.current_state)
        self.update_idletasks()
        self._bind_global_shortcuts()
        self._bind_upload_double_click()
        self._bind_ctrl_for_multiselect()

        self.protocol("WM_DELETE_WINDOW", self._on_close_request)
        self._schedule_ui_drain()
        self._undo_stack: list[dict[str, Any]] = []

    def _diagnose_dnd_windows(self) -> None:
        """Показать причину, если DnD заведомо не заработает (Windows)."""
        if sys.platform != "win32":
            return
        try:
            import ctypes

            is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            is_admin = False
        if is_admin:
            try:
                messagebox.showwarning(
                    "Drag&Drop",
                    "Drag&Drop в Windows не работает, если приложение запущено от администратора.\n"
                    "Закройте программу и запустите её обычным пользователем (и IDE/терминал тоже без admin).",
                    parent=self,
                )
            except Exception:
                pass
            return
        try:
            self.tk.call("package", "require", "tkdnd")
        except Exception:
            try:
                messagebox.showwarning(
                    "Drag&Drop",
                    "Модуль drag&drop не активирован (tkdnd недоступен).\n"
                    "Установите зависимость:  py -m pip install tkinterdnd2",
                    parent=self,
                )
            except Exception:
                pass

    def _schedule_ui_drain(self) -> None:
        self._ui_poll_id = self.after(16, self._drain_ui_queue)

    def _drain_ui_queue(self) -> None:
        if self._shutdown:
            return
        try:
            while True:
                msg = self._ui_queue.get_nowait()
                self._handle_logic_message(msg)
        except queue.Empty:
            pass
        if not self._shutdown:
            self._schedule_ui_drain()

    def _handle_logic_message(self, msg: Any) -> None:
        if isinstance(msg, UiMessageValidateResult):
            if msg.request_id != self._load_request_id:
                return
            self._set_file_ui_busy(False)
            r = msg.result
            if r.ok and r.name:
                self.current_file_path = r.path
                self.file_status.configure(
                    text=f"Успешно загружен: {r.name}",
                    text_color=C.STATUS_OK,
                )
                self.total_traces = int(r.tracecount or 0)
                self.samples_count = int(r.samples_count or 0)
                self.matrix_data = None
                self._sync_data_tab_after_load()
                self._sync_home_slider_after_load()
                self._request_home_window_read(0, force=True)
            elif r.error == "bad_ext":
                self.current_file_path = None
                self.file_status.configure(
                    text="Перетащите файл .sgy или .segy",
                    text_color=C.STATUS_WARN,
                )
                self._reset_data_tab_state()
                self._reset_home_plots_empty()
            elif r.error == "not_file":
                self.current_file_path = None
                self.file_status.configure(
                    text="Файл не найден",
                    text_color=C.STATUS_WARN,
                )
                self._reset_data_tab_state()
                self._reset_home_plots_empty()
            elif r.error == "not_readable":
                self.current_file_path = None
                self.file_status.configure(
                    text="Файл не читается как SEG-Y",
                    text_color=C.STATUS_WARN,
                )
                self._reset_data_tab_state()
                self._reset_home_plots_empty()
        elif isinstance(msg, UiMessageReadDataProgress):
            if msg.request_id == self._home_window_request_id:
                pct = int(100 * msg.processed / max(1, msg.total))
                try:
                    if self.home_slider_status is not None:
                        self.home_slider_status.configure(text=f"Чтение окна: {pct}%")
                except Exception:
                    pass
                return
            if msg.request_id != self._data_read_request_id:
                return
            pct = int(100 * msg.processed / max(1, msg.total))
            self.label_data_result.configure(text=f"Чтение данных: {pct}%", text_color=C.STATUS_PENDING)
        elif isinstance(msg, UiMessageReadDataResult):
            if msg.request_id == self._data_read_request_id:
                self._set_data_read_busy(False)
                self._data_read_cancel = None
                self._apply_data_read_result(msg)
                return
            if msg.request_id == self._home_window_request_id:
                self._home_window_cancel = None
                self._apply_home_window_read_result(msg)
                return
            return
        elif isinstance(msg, UiMessageProcessProgress):
            if msg.request_id != self._process_request_id:
                return
            pct = int(100 * msg.processed / max(1, msg.total))
            self.analysis_progress.set(msg.processed / max(1, msg.total))
            self.analysis_status_label.configure(
                text=(
                    f"Обработаны выбранные трассы {msg.from_trace}-{msg.to_trace} "
                    f"({pct}%)."
                ),
                text_color=C.GRAY_TEXT,
            )
        elif isinstance(msg, UiMessageProcessResult):
            if msg.request_id != self._process_request_id:
                return
            self.btn_processing_cancel.configure(state="disabled")
            self.btn_processing.configure(state="normal")
            self._process_cancel = None
            self._analysis_export_source = msg.after_preview
            self.analysis_status_label.configure(
                text=(
                    "Готово. Порядок методов: "
                    f"{' -> '.join(self._analysis_label(m) for m in msg.method_ids)}. "
                    f"max|A|={msg.max_abs:.3g}"
                ),
                text_color=C.STATUS_OK,
            )
            self.analysis_progress.set(1.0)
            self._open_plot_popup(
                key="before",
                title="График До",
                matrix=msg.before_preview,
                trace_start=msg.start,
                trace_step=msg.step,
            )
            self._open_plot_popup(
                key="after",
                title="График После",
                matrix=msg.after_preview,
                trace_start=msg.start,
                trace_step=msg.step,
            )
        elif isinstance(msg, UiMessageWorkerError):
            if msg.request_id == self._load_request_id:
                self._set_file_ui_busy(False)
                self.current_file_path = None
                self.file_status.configure(text=msg.message, text_color=C.STATUS_WARN)
                self._reset_data_tab_state()
                self._reset_home_plots_empty()
                return
            if msg.request_id == self._data_read_request_id:
                self._set_data_read_busy(False)
                self._data_read_cancel = None
                self.matrix_data = None
                self.label_data_result.configure(text=msg.message, text_color=C.STATUS_WARN)
                return
            if msg.request_id == self._home_window_request_id:
                self._home_window_cancel = None
                if getattr(self, "_home_matplotlib_ok", False) and self._home_ax_before is not None:
                    self._home_apply_placeholder(self._home_ax_before, msg.message)
                    try:
                        self._home_canvas_before.draw()
                    except Exception:
                        pass
                return
            if msg.request_id == self._process_request_id:
                self.btn_processing_cancel.configure(state="disabled")
                self.btn_processing.configure(state="normal")
                self._process_cancel = None
                self.analysis_status_label.configure(text=msg.message, text_color=C.STATUS_WARN)
                self.analysis_progress.set(0.0)

    def _on_close_request(self) -> None:
        self._shutdown = True
        if self._data_read_cancel is not None:
            self._data_read_cancel.set()
        if self._process_cancel is not None:
            self._process_cancel.set()
        if self._ui_poll_id is not None:
            try:
                self.after_cancel(self._ui_poll_id)
            except tk.TclError:
                pass
        if self._resize_after_id is not None:
            try:
                self.after_cancel(self._resize_after_id)
            except tk.TclError:
                pass
        self._resize_after_id = None
        self._logic_queue.put(LOGIC_STOP)
        self._logic_thread.join(timeout=2.0)
        self.destroy()

    def submit_load_seismic(self, path: str) -> None:
        path = str(path).strip().strip("{}").strip().strip('"').strip("'")
        if path.lower().startswith("file:///"):
            path = path[8:]
        self._load_request_id += 1
        self._set_file_ui_busy(True)
        self._logic_queue.put(LogicTaskValidateSeismic(path=path, request_id=self._load_request_id))

    def _apply_fullscreen_geometry(self) -> None:
        try:
            self.state("zoomed")
        except tk.TclError:
            self.update_idletasks()
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            self.geometry(f"{sw}x{sh}+0+0")

    def _setup_status_bar(self) -> None:
        self.status_bar = ctk.CTkFrame(
            self,
            height=40,
            corner_radius=0,
            fg_color=C.STATUS_BAR_BG,
            border_width=1,
            border_color=C.STATUS_BAR_BORDER,
        )
        self.status_bar.pack(side="bottom", fill="x", padx=0, pady=0)
        self.status_bar.pack_propagate(False)
        self.status_hint_label = ctk.CTkLabel(
            self.status_bar,
            text="",
            anchor="w",
            font=C.FONT_BODY,
            text_color=C.STATUS_BAR_TEXT,
            justify="left",
        )
        self.status_hint_label.pack(side="left", padx=14, pady=8, fill="x", expand=True)
        self.status_keys_label = ctk.CTkLabel(
            self.status_bar,
            text=C.STATUS_KEYS_DEFAULT,
            anchor="e",
            font=C.FONT_SMALL,
            text_color=C.STATUS_BAR_TEXT,
        )
        self.status_keys_label.pack(side="right", padx=14, pady=8)
        self._bind_nav_status_hints()

    def _bind_nav_status_hints(self) -> None:
        def hover(widget, tip: str):
            def on_enter(_e):
                self.status_hint_label.configure(text=tip)

            def on_leave(_e):
                self._refresh_status_bar()

            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)

        hover(self.btn_back, "Назад по истории вкладок")
        hover(self.btn_forward, "Вперёд по истории вкладок")

    def _refresh_status_bar(self) -> None:
        tab = self.current_state["tab"]
        self.status_hint_label.configure(text=C.TAB_STATUS_HINTS.get(tab, ""))
        keys = C.STATUS_KEYS_ANALYSIS if tab == "Анализ" else C.STATUS_KEYS_DEFAULT
        self.status_keys_label.configure(text=keys)

    def _set_file_ui_busy(self, busy: bool) -> None:
        self._file_loading = busy
        try:
            self.btn_select.configure(state="disabled" if busy else "normal")
        except (tk.TclError, AttributeError):
            pass
        if busy:
            self.file_status.configure(text="Проверка файла…", text_color=C.STATUS_PENDING)

    def _bind_global_shortcuts(self) -> None:
        def go_tab(event, idx: int) -> str:
            if 0 <= idx < len(self.tabs_list):
                self.save_state(self.tabs_list[idx])
            return "break"

        for i, _name in enumerate(self.tabs_list):
            self.bind_all(f"<Control-Key-{i + 1}>", lambda e, ix=i: go_tab(e, ix))

        self.bind_all("<Control-o>", lambda e: self._shortcut_open_file())
        self.bind_all("<Control-O>", lambda e: self._shortcut_open_file())
        self.bind_all("<Control-z>", self._undo)
        self.bind_all("<Control-Z>", self._undo)
        self.bind_all("<MouseWheel>", self._on_global_wheel, add="+")
        self.bind_all("<Button-4>", self._on_global_wheel, add="+")
        self.bind_all("<Button-5>", self._on_global_wheel, add="+")

    def _shortcut_open_file(self, event=None) -> Optional[str]:
        if self.current_state["tab"] != "Файл":
            self.save_state("Файл")
        self.open_file_dialog()
        return "break"

    def _bind_ctrl_for_multiselect(self) -> None:
        def down(_e=None):
            self._home_ctrl_down = True

        def up(_e=None):
            self._home_ctrl_down = False

        self.bind_all("<KeyPress-Control_L>", down, add="+")
        self.bind_all("<KeyRelease-Control_L>", up, add="+")
        self.bind_all("<KeyPress-Control_R>", down, add="+")
        self.bind_all("<KeyRelease-Control_R>", up, add="+")

    def _bind_upload_double_click(self) -> None:
        def on_double(event) -> str:
            self.open_file_dialog()
            return "break"

        widgets = (
            self.frames["Файл"],
            self.upload_box,
            self.upload_glyph,
            self.upload_title,
            self.upload_formats,
            self.upload_dnd_hint,
            self.file_status,
        )
        for w in widgets:
            for surf in iter_ctk_drop_surfaces(w):
                surf.bind("<Double-Button-1>", on_double)

    def _on_root_configure(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        if self._shutdown:
            return
        self._is_resizing = True
        if self._resize_after_id is not None:
            try:
                self.after_cancel(self._resize_after_id)
            except tk.TclError:
                pass
        self._resize_after_id = self.after(250, self._on_resize_idle)

    def _on_resize_idle(self) -> None:
        self._resize_after_id = None
        if self._shutdown:
            return
        self._is_resizing = False
        if self.current_state.get("tab") == "Главная":
            try:
                self._home_refresh_matplotlib_geometry()
            except Exception:
                pass
        try:
            self.update_idletasks()
        except tk.TclError:
            pass

    def setup_ribbon_tools(self) -> None:
        self._ribbon_placeholder = ctk.CTkFrame(self._ribbon_stack, fg_color="transparent")
        self._ribbon_placeholder.place(x=0, y=0, relwidth=1, relheight=1)

        self.home_tools = ctk.CTkFrame(self._ribbon_stack, fg_color="transparent")

        ctk.CTkLabel(
            self.home_tools,
            text="Цветовая схема",
            font=C.FONT_SMALL,
            text_color=C.GRAY_LABEL,
        ).pack(side="left", padx=(8, 4), pady=10)
        self.scheme_menu = ctk.CTkOptionMenu(
            self.home_tools,
            values=list(C.AVAILABLE_COLOR_SCHEMES),
            width=170,
            command=lambda v: self.update_view_settings(scheme=v),
        )
        self.scheme_menu.pack(side="left", padx=(0, 10), pady=10)

        ctk.CTkLabel(
            self.home_tools,
            text="Вид графика",
            font=C.FONT_SMALL,
            text_color=C.GRAY_LABEL,
        ).pack(side="left", padx=(0, 4), pady=10)
        self.plot_mode_menu = ctk.CTkOptionMenu(
            self.home_tools,
            values=list(C.AVAILABLE_PLOT_MODES),
            width=170,
            command=lambda v: self.update_view_settings(plot_mode=v),
        )
        self.plot_mode_menu.pack(side="left", padx=(0, 12), pady=10)

        self.btn_home_fourier = ctk.CTkButton(
            self.home_tools,
            text="Спектр Фурье",
            width=140,
            height=34,
            corner_radius=8,
            font=C.FONT_RIBBON,
            fg_color=C.ACCENT,
            hover_color=C.ACCENT_DARK,
            text_color="white",
            command=self._open_fourier_spectrum_popup,
        )
        self.btn_home_fourier.pack(side="left", padx=(0, 8), pady=10)

        self.btn_home_clear = ctk.CTkButton(
            self.home_tools,
            text="Очистить данные",
            width=150,
            height=34,
            corner_radius=8,
            font=C.FONT_RIBBON,
            fg_color=C.TOOL_FG,
            text_color=C.TOOL_TEXT,
            hover_color=C.TOOL_HOVER,
            border_width=1,
            border_color=C.TOOL_BORDER,
            command=self.clear_all_data,
        )
        self.btn_home_clear.pack(side="left", padx=(0, 8), pady=10)
        self.home_tools.place(x=0, y=0, relwidth=1, relheight=1)

        self.analysis_tools = ctk.CTkFrame(self._ribbon_stack, fg_color="transparent")
        title_row = ctk.CTkFrame(self.analysis_tools, fg_color="transparent")
        title_row.pack(fill="x", pady=(1, 0))
        ctk.CTkLabel(
            title_row,
            text="Методы обработки",
            font=C.FONT_RIBBON_SECTION,
            text_color=C.GRAY_LABEL,
            anchor="center",
        ).pack(fill="x", padx=16, pady=0)

        body = ctk.CTkFrame(self.analysis_tools, fg_color="transparent")
        body.pack(fill="x", expand=False, padx=12, pady=(0, 6))

        left_col = ctk.CTkFrame(body, fg_color="transparent")
        left_col.pack(side="left", fill="x", padx=(8, 8), anchor="nw")

        self.analysis_method_checkboxes: dict[str, ctk.CTkCheckBox] = {}
        for mid, full, _ in C.ANALYSIS_METHODS:
            lbl = full
            cb = ctk.CTkCheckBox(
                left_col,
                text=lbl,
                font=C.FONT_SMALL,
                height=20,
                checkbox_width=14,
                checkbox_height=14,
                fg_color=C.ACCENT,
                hover_color=C.ACCENT_DARK,
                border_width=2,
                border_color=C.GRAY_BORDER_IDLE,
                text_color=C.GRAY_TEXT,
                command=lambda m=mid: self._on_ribbon_method_checkbox(m),
            )
            cb.pack(anchor="w", pady=0, ipady=0, fill="x")
            self.analysis_method_checkboxes[mid] = cb

        self.btn_processing = ctk.CTkButton(
            left_col,
            text="Обработка",
            width=140,
            height=28,
            corner_radius=8,
            font=C.FONT_RIBBON,
            fg_color=C.ACCENT,
            hover_color=C.ACCENT_DARK,
            text_color="white",
            command=self._on_processing_click,
        )
        self.btn_processing.pack(anchor="w", pady=(2, 0))

        self.analysis_tools.place(x=0, y=0, relwidth=1, relheight=1)
        self._ribbon_placeholder.tkraise()

    def setup_analysis_page(self) -> None:
        f = self.frames["Анализ"]
        self.analysis_body = ctk.CTkFrame(f, fg_color="transparent")
        self.analysis_body.pack(fill="both", expand=True)

        self.analysis_body.grid_rowconfigure(0, weight=1)
        self.analysis_body.grid_columnconfigure(0, weight=4)
        self.analysis_body.grid_columnconfigure(1, weight=6)

        left_col = ctk.CTkFrame(self.analysis_body, fg_color="transparent", width=C.LEFT_COL_W)
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 12), pady=0)
        left_col.grid_propagate(False)
        left_col.grid_rowconfigure(0, weight=3)
        left_col.grid_rowconfigure(1, weight=5)
        left_col.grid_columnconfigure(0, weight=1)
        self._analysis_left_col = left_col

        self.analysis_pipeline_outer = ctk.CTkFrame(
            left_col,
            fg_color=C.PIPELINE_CARD_FG,
            corner_radius=C.RIBBON_CORNER_RADIUS,
            border_width=2,
            border_color=C.ACCENT_ON_BORDER,
            width=C.PIPELINE_OUTER_W,
        )
        self.analysis_pipeline_outer.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        self.analysis_pipeline_outer.pack_propagate(False)

        ctk.CTkLabel(
            self.analysis_pipeline_outer,
            text="Цепочка обработки",
            font=C.FONT_HEAD,
            text_color=C.GRAY_TEXT,
            anchor="w",
        ).pack(anchor="w", fill="x", padx=14, pady=(14, 6))
        _sep1 = ctk.CTkFrame(
            self.analysis_pipeline_outer,
            height=2,
            corner_radius=0,
            fg_color=C.SEPARATOR_LINE,
        )
        _sep1.pack(fill="x", padx=12, pady=(0, 8))
        _sep1.pack_propagate(False)
        ctk.CTkLabel(
            self.analysis_pipeline_outer,
            text="Перетащите строки для порядка · клик по строке — убрать метод",
            font=C.FONT_SMALL,
            text_color=C.GRAY_TEXT_MUTED,
            justify="left",
            anchor="w",
        ).pack(anchor="w", padx=14, pady=(0, 6))

        self.analysis_pipeline_scroll = ctk.CTkScrollableFrame(
            self.analysis_pipeline_outer,
            fg_color="transparent",
        )
        self.analysis_pipeline_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 12))

        self._setup_data_range_panel(left_col)

        self.analysis_workspace = ctk.CTkFrame(
            self.analysis_body,
            fg_color=C.ANALYSIS_WORKSPACE_BG,
            corner_radius=C.RIBBON_CORNER_RADIUS,
            border_width=2,
            border_color=C.ACCENT_ON_BORDER,
        )
        self.analysis_workspace.grid(row=0, column=1, sticky="nsew", padx=(0, 0), pady=0)

        ws_head = ctk.CTkFrame(self.analysis_workspace, fg_color="transparent")
        ws_head.pack(fill="x", padx=14, pady=(14, 6))
        ctk.CTkLabel(
            ws_head,
            text="Рабочая область анализа",
            font=C.FONT_HEAD,
            text_color=C.GRAY_TEXT,
            anchor="w",
        ).pack(side="left", anchor="w")
        _sep2 = ctk.CTkFrame(
            self.analysis_workspace,
            height=2,
            corner_radius=0,
            fg_color=C.SEPARATOR_LINE,
        )
        _sep2.pack(fill="x", padx=12, pady=(0, 10))
        _sep2.pack_propagate(False)

        self.analysis_workspace_canvas = ctk.CTkFrame(
            self.analysis_workspace,
            fg_color=C.ANALYSIS_WORKSPACE_INNER,
            corner_radius=8,
            border_width=1,
            border_color=C.ANALYSIS_WORKSPACE_BORDER,
        )
        self.analysis_workspace_canvas.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # Используем grid для точного управления расположением
        self.analysis_workspace_canvas.grid_rowconfigure(0, weight=0)  # статус
        self.analysis_workspace_canvas.grid_rowconfigure(1, weight=0)  # панель задач
        self.analysis_workspace_canvas.grid_rowconfigure(2, weight=0)  # кнопка отмены
        self.analysis_workspace_canvas.grid_rowconfigure(3, weight=0)  # таблица (не растягивается)
        self.analysis_workspace_canvas.grid_columnconfigure(0, weight=1)

        self.analysis_status_label = ctk.CTkLabel(
            self.analysis_workspace_canvas,
            text="Выберите порядок методов и нажмите «Обработка».",
            font=C.FONT_BODY,
            text_color=C.GRAY_TEXT,
            justify="left",
            anchor="w",
        )
        self.analysis_status_label.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))

        self.analysis_taskbar = ctk.CTkFrame(
            self.analysis_workspace_canvas,
            fg_color=("gray92", "#2f2f2f"),
            corner_radius=8,
            border_width=1,
            border_color=C.ANALYSIS_WORKSPACE_BORDER,
        )
        self.analysis_taskbar.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.analysis_taskbar.grid_columnconfigure(0, weight=1)
        self.analysis_taskbar.grid_columnconfigure(1, weight=0)

        self.analysis_progress = ctk.CTkProgressBar(self.analysis_taskbar)
        self.analysis_progress.grid(row=0, column=0, sticky="ew", padx=(10, 8), pady=8)
        self.analysis_progress.set(0.0)

        self.btn_analysis_export = ctk.CTkButton(
            self.analysis_taskbar,
            text="Выгрузить данные",
            width=150,
            height=28,
            font=C.FONT_SMALL,
            fg_color=C.ACCENT,
            hover_color=C.ACCENT_DARK,
            text_color="white",
            command=self._export_analysis_table,
        )
        self.btn_analysis_export.grid(row=0, column=1, sticky="e", padx=(0, 10), pady=6)

        self.btn_processing_cancel = ctk.CTkButton(
            self.analysis_workspace_canvas,
            text="Отмена обработки",
            width=180,
            height=30,
            font=C.FONT_BODY,
            fg_color=C.NAV_BTN_FG,
            hover_color=C.NAV_BTN_HOVER,
            text_color=C.NAV_BTN_TEXT,
            state="disabled",
            command=self._cancel_processing,
        )
        self.btn_processing_cancel.grid(row=2, column=0, sticky="w", padx=12, pady=(0, 12))


        # Таблица для выгрузки обработанных данных
        table_frame = ctk.CTkFrame(self.analysis_workspace_canvas, fg_color="transparent")
        table_frame.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 12))
        table_frame.configure(height=300)  # фиксированная высота в пикселях
        # Создаём таблицу с фиксированной высотой (количество видимых строк)
        self.analysis_table = ttk.Treeview(table_frame, columns=("Время",), show="headings", height=12)
        self.analysis_table.heading("Время", text="Время")

        # Скроллы
        v_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.analysis_table.yview)
        h_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.analysis_table.xview)
        self.analysis_table.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        # Настройка растяжения внутри table_frame
        table_frame.grid_rowconfigure(0, weight=0)   # не растягиваем по вертикали
        table_frame.grid_columnconfigure(0, weight=1)  # растягиваем по горизонтали

        self.analysis_table.grid(row=0, column=0, sticky="nsew")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")

        self._refresh_analysis_ui()

    def _setup_data_range_panel(self, parent: ctk.CTkFrame) -> None:
        """Панель выбора диапазона трасс (перенесено из бывшей вкладки «Данные»)."""
        card = ctk.CTkFrame(
            parent,
            fg_color=C.PIPELINE_CARD_FG,
            corner_radius=C.RIBBON_CORNER_RADIUS,
            border_width=1,
            border_color=C.PIPELINE_CARD_BORDER,
            width=C.PIPELINE_OUTER_W,
        )
        card.grid(row=1, column=0, sticky="nsew", padx=0, pady=(12, 0))
        card.pack_propagate(False)

        ctk.CTkLabel(
            card,
            text="Выбор данных",
            font=C.FONT_HEAD,
            text_color=C.GRAY_TEXT,
            anchor="w",
        ).pack(anchor="w", fill="x", padx=14, pady=(14, 6))

        _sep = ctk.CTkFrame(card, height=2, corner_radius=0, fg_color=C.SEPARATOR_LINE)
        _sep.pack(fill="x", padx=12, pady=(0, 10))
        _sep.pack_propagate(False)

        self.label_data_meta = ctk.CTkLabel(
            card,
            text="Файл не загружен — сначала откройте SEG-Y на вкладке «Файл».",
            font=C.FONT_BODY,
            text_color=C.GRAY_TEXT_MUTED,
            justify="left",
            anchor="w",
        )
        self.label_data_meta.pack(anchor="w", padx=14, pady=(0, 10), fill="x")

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(anchor="w", padx=14, pady=(0, 10))

        ctk.CTkLabel(row, text="От:", font=C.FONT_BODY, text_color=C.GRAY_TEXT).grid(row=0, column=0, padx=(0, 6))
        self.entry_data_start = ctk.CTkEntry(row, placeholder_text="0", width=88, state="disabled")
        self.entry_data_start.grid(row=0, column=1, padx=(0, 16))

        ctk.CTkLabel(row, text="До:", font=C.FONT_BODY, text_color=C.GRAY_TEXT).grid(row=0, column=2, padx=(0, 6))
        self.entry_data_end = ctk.CTkEntry(row, placeholder_text="—", width=88, state="disabled")
        self.entry_data_end.grid(row=0, column=3, padx=(0, 16))

        ctk.CTkLabel(row, text="Шаг:", font=C.FONT_BODY, text_color=C.GRAY_TEXT).grid(row=0, column=4, padx=(0, 6))
        self.entry_data_step = ctk.CTkEntry(row, placeholder_text="1", width=64, state="disabled")
        self.entry_data_step.grid(row=0, column=5, padx=(0, 0))

        for e in (self.entry_data_start, self.entry_data_end, self.entry_data_step):
            e.bind("<FocusOut>", self._on_data_entries_focus_out)

        self.btn_data_read = ctk.CTkButton(
            card,
            text="Выбрать данные",
            width=200,
            height=36,
            font=C.FONT_RIBBON,
            fg_color=C.STATUS_OK,
            hover_color="#27ae60",
            text_color="white",
            state="disabled",
            command=self._on_data_read_to_memory,
        )
        self.btn_data_read.pack(anchor="w", padx=14, pady=(2, 10))

        self.btn_data_cancel = ctk.CTkButton(
            card,
            text="Отмена",
            width=120,
            height=36,
            font=C.FONT_RIBBON,
            fg_color=C.NAV_BTN_FG,
            hover_color=C.NAV_BTN_HOVER,
            text_color=C.NAV_BTN_TEXT,
            state="disabled",
            command=self._cancel_data_read,
        )
        self.btn_data_cancel.pack(anchor="w", padx=14, pady=(0, 10))

        self.label_data_result = ctk.CTkLabel(
            card,
            text="",
            font=C.FONT_BODY,
            text_color=C.GRAY_TEXT,
            justify="left",
            anchor="w",
        )
        self.label_data_result.pack(anchor="w", padx=14, pady=(0, 14), fill="x")

    def _on_ribbon_method_checkbox(self, mid: str) -> None:
        if self._suspend_checkbox_cmd:
            return
        cb = self.analysis_method_checkboxes[mid]
        if cb.get():
            self._save_undo_state()
            self.analysis_pipeline.append(mid)
            cb.deselect()
            self._rebuild_pipeline_list()

    def _on_processing_click(self) -> None:
        if not self.analysis_pipeline:
            messagebox.showinfo(
                "Обработка",
                "Сначала отметьте один или несколько методов на ленте «Методы обработки».",
                parent=self,
            )
            return
        if not self.current_file_path:
            messagebox.showinfo(
                "Обработка",
                "Сначала загрузите SEG-Y файл на вкладке «Файл».",
                parent=self,
            )
            return

        ordered_methods = [m for m in self.analysis_pipeline if m in {"interp", "denoise", "spectrum", "resolution"}]
        if not ordered_methods:
            messagebox.showwarning(
                "Обработка",
                "В цепочке нет поддерживаемых методов обработки.",
                parent=self,
            )
            return

        try:
            start = int(self.entry_data_start.get()) if self.entry_data_start.get().strip() else 0
            end = int(self.entry_data_end.get()) if self.entry_data_end.get().strip() else self.total_traces
            step = int(self.entry_data_step.get()) if self.entry_data_step.get().strip() else 1
            if step <= 0:
                raise ValueError("Шаг должен быть больше 0.")
            if start < 0 or end > self.total_traces or start >= end:
                raise ValueError(f"Диапазон должен быть в пределах 0..{self.total_traces}, и От < До.")
            selected_traces = len(range(start, end, step))
            if selected_traces <= 0:
                raise ValueError("Выбран пустой диапазон данных.")
            self._process_request_id += 1
            req_id = self._process_request_id
            cancel_event = threading.Event()
            self._process_cancel = cancel_event
            self.btn_processing_cancel.configure(state="normal")
            self.btn_processing.configure(state="disabled")
            self.analysis_progress.set(0.0)
            self.analysis_status_label.configure(
                text=(
                    f"Запуск: {', '.join(self._analysis_label(m) for m in ordered_methods)} "
                    f"(трассы {start}:{end}:{step})"
                ),
                text_color=C.STATUS_PENDING,
            )
            self._logic_queue.put(
                LogicTaskProcessRange(
                    path=self.current_file_path,
                    request_id=req_id,
                    start=start,
                    end=end,
                    step=step,
                    method_ids=tuple(ordered_methods),
                    chunk_size=1000,
                    preview_target=512,
                    cancel_event=cancel_event,
                )
            )
        except Exception as ex:
            self.analysis_status_label.configure(text=f"Ошибка конвейера: {ex}", text_color=C.STATUS_WARN)
            self.analysis_progress.set(0.0)

    def _cancel_processing(self) -> None:
        ev = self._process_cancel
        if ev is not None:
            ev.set()
        self.analysis_status_label.configure(text="Отмена обработки...", text_color=C.STATUS_PENDING)
        self.btn_processing_cancel.configure(state="disabled")

    def _fill_analysis_table(self, matrix: Any, trace_start: int, trace_step: int, source: str = "") -> None:
        """
        Заполнить таблицу в транспонированном виде: строки — отсчёты, столбцы — трассы.
        source: "read" или "process" для разных сообщений.
        """
        # Очистим таблицу
        for row in self.analysis_table.get_children():
            self.analysis_table.delete(row)

        # Полностью удалим все колонки кроме первой (пересоздадим)
        existing = list(self.analysis_table["columns"])
        for col in existing:
            self.analysis_table["columns"] = tuple([c for c in existing if c != col])
        # Теперь колонок нет, установим заново

        if matrix is None:
            self.analysis_table["columns"] = ("Время",)
            self.analysis_table.heading("#0", text="")
            self.analysis_table.heading("Время", text="Время")
            return

        import numpy as np
        arr = np.asarray(matrix, dtype=np.float32)
        if arr.ndim != 2 or arr.size == 0:
            self.analysis_table["columns"] = ("Время",)
            self.analysis_table.heading("#0", text="")
            self.analysis_table.heading("Время", text="Время")
            return

        n_traces = arr.shape[0]
        n_samples = arr.shape[1]
        # Ограничим количество отображаемых трасс (например, 50)
        max_traces = 50
        if n_traces > max_traces:
            self.analysis_status_label.configure(
                text=f"Внимание: выбрано {n_traces} трасс, показаны первые {max_traces}.",
                text_color=C.STATUS_WARN
            )
            n_traces = max_traces

        # Создадим колонки: первая "Время", затем для каждой трассы
        columns = ["Время"]
        trace_columns = []  # для хранения реальных номеров
        for i in range(n_traces):
            real_trace_num = trace_start + i * trace_step
            col_name = f"Трасса {real_trace_num}"
            columns.append(col_name)
            trace_columns.append(col_name)

        self.analysis_table["columns"] = tuple(columns)
        # Настроим заголовки
        self.analysis_table.heading("Время", text="Время")
        for col in trace_columns:
            self.analysis_table.heading(col, text=col)
        # Настроим ширину и выравнивание
        self.analysis_table.column("Время", width=60, anchor="center")
        for col in trace_columns:
            self.analysis_table.column(col, width=70, anchor="center")

        # Заполняем строки по отсчётам (время)
        for sample_idx in range(n_samples):
            row_values = [str(sample_idx)]  # первая колонка - номер отсчёта
            for tr_idx in range(n_traces):
                amp = arr[tr_idx, sample_idx]
                row_values.append(f"{amp:.4f}")
            self.analysis_table.insert("", "end", values=row_values)

        # Обновим статусную строку
        if source == "read":
            self.analysis_status_label.configure(
                text=f"Выбрано {n_traces} трасс, {n_samples} отсчётов. Таблица показывает амплитуды по отсчётам.",
                text_color=C.STATUS_OK
            )
        else:
            self.analysis_status_label.configure(
                text=f"Обработано {n_traces} трасс, {n_samples} отсчётов. Таблица показывает амплитуды по отсчётам.",
                text_color=C.STATUS_OK
            )

    def _method_interp(self, chunk: Any) -> Any:
        return chunk * 1.0

    def _method_denoise(self, chunk: Any) -> Any:
        import numpy as np

        arr = np.asarray(chunk, dtype=np.float32)
        if arr.ndim != 2 or arr.shape[1] < 3:
            return arr
        out = arr.copy()
        out[:, 1:-1] = (arr[:, :-2] + arr[:, 1:-1] + arr[:, 2:]) / 3.0
        return out

    def _method_spectrum(self, chunk: Any) -> Any:
        import numpy as np

        arr = np.asarray(chunk, dtype=np.float32)
        return np.clip(arr * 1.1, -1.0e9, 1.0e9)

    def _method_resolution(self, chunk: Any) -> Any:
        import numpy as np

        arr = np.asarray(chunk, dtype=np.float32)
        if arr.ndim != 2 or arr.shape[1] < 3:
            return arr
        out = arr.copy()
        mid = arr[:, 1:-1]
        out[:, 1:-1] = mid + 0.25 * (mid - (arr[:, :-2] + arr[:, 2:]) * 0.5)
        return out

    def _analysis_label(self, mid: str) -> str:
        return C.ANALYSIS_LABELS.get(mid, mid)

    def toggle_analysis_method(self, mid: str) -> None:
        self._save_undo_state()
        if mid in self.analysis_pipeline:
            self.analysis_pipeline.remove(mid)
        else:
            self.analysis_pipeline.append(mid)
        self._refresh_analysis_ui()

    def _sync_method_indicators(self) -> None:
        self._suspend_checkbox_cmd = True
        try:
            for _mid, cb in self.analysis_method_checkboxes.items():
                cb.deselect()
        finally:
            self._suspend_checkbox_cmd = False

    def _refresh_analysis_ui(self) -> None:
        self._sync_method_indicators()
        self._rebuild_pipeline_list()

    def _pipeline_scroll_rows(self):
        return [
            c
            for c in self.analysis_pipeline_scroll.winfo_children()
            if isinstance(c, ctk.CTkFrame)
        ]

    def _pipeline_row_idle_style(self, row) -> None:
        if not row.winfo_exists():
            return
        row.configure(fg_color=C.GRAY_ROW, border_width=0, cursor="hand2")

    def _pipeline_row_slot_style(self, row, title_lbl) -> None:
        if row.winfo_exists():
            row.configure(
                fg_color=C.GRAY_ROW_ALT,
                border_width=1,
                border_color=("gray80", "#555"),
                cursor="none",
            )
        if title_lbl.winfo_exists():
            title_lbl.configure(text="")

    def _make_drag_ghost(self, mid: str, width_px: int):
        g = ctk.CTkToplevel(self)
        g.overrideredirect(True)
        try:
            g.attributes("-topmost", True)
        except tk.TclError:
            pass
        try:
            g.attributes("-alpha", 0.9)
        except tk.TclError:
            pass
        fr = ctk.CTkFrame(
            g,
            fg_color=("gray90", "#3a3a3a"),
            border_width=2,
            border_color=C.GHOST_BORDER,
            corner_radius=5,
            height=C.PIPELINE_ROW_HEIGHT,
        )
        fr.pack(fill="both", expand=True)
        ctk.CTkLabel(
            fr,
            text="☰",
            width=28,
            font=C.FONT_GRIP,
            text_color=("gray40", "gray65"),
        ).pack(side="left", padx=(4, 2))
        ctk.CTkLabel(
            fr,
            text=self._analysis_label(mid),
            font=C.FONT_SMALL,
            anchor="w",
        ).pack(side="left", fill="x", expand=True, padx=(4, 8))
        w = max(160, int(width_px))
        g.geometry(f"{w}x32+{-1000}+{-1000}")
        return g

    def _rebuild_pipeline_list(self) -> None:
        for w in self.analysis_pipeline_scroll.winfo_children():
            w.destroy()
        if not self.analysis_pipeline:
            ctk.CTkLabel(
                self.analysis_pipeline_scroll,
                text="Методы не выбраны",
                font=("Arial", 13),
                text_color="gray55",
            ).pack(pady=24)
            self._update_pipeline_card_minsize()
            return
        _h = C.PIPELINE_ROW_HEIGHT
        for i, mid in enumerate(self.analysis_pipeline):
            row = ctk.CTkFrame(
                self.analysis_pipeline_scroll,
                fg_color=C.GRAY_ROW,
                height=_h,
                corner_radius=8,
                cursor="hand2",
            )
            row.pack(fill="x", pady=3, padx=2)
            row.pack_propagate(False)
            grip = ctk.CTkLabel(
                row,
                text="☰",
                width=28,
                font=C.FONT_GRIP,
                text_color=("gray40", "gray65"),
            )
            grip.pack(side="left", padx=(6, 2))
            title = ctk.CTkLabel(row, text=self._analysis_label(mid), font=C.FONT_SMALL, anchor="w")
            title.pack(side="left", fill="x", expand=True, padx=(4, 8))
            for w in (row, grip, title):
                w.bind(
                    "<Button-1>",
                    lambda e, idx=i, r=row, t=title, m=mid: self._pipeline_press(e, idx, r, t, m),
                )
        self._update_pipeline_card_minsize()

    def _update_pipeline_card_minsize(self) -> None:
        """Гарантировать, что в цепочке видны все выбранные методы (их максимум 4)."""
        try:
            host = getattr(self, "_analysis_left_col", None)
            if host is None:
                return
            n = max(1, int(len(self.analysis_pipeline)))
            rows_h = n * (C.PIPELINE_ROW_HEIGHT + 6) + 18
            min_h = 110 + rows_h
            min_h = int(max(220, min(520, min_h)))
            host.grid_rowconfigure(0, minsize=min_h)
        except Exception:
            pass

    def _pipeline_press(self, event, idx: int, row, title_lbl, mid: str) -> None:
        gx = event.x_root - row.winfo_rootx()
        gy = event.y_root - row.winfo_rooty()
        self._pipe_drag = PipeDragState(
            idx=idx,
            mid=mid,
            x0=event.x_root,
            y0=event.y_root,
            moved=False,
            row=row,
            title_lbl=title_lbl,
            visual_on=False,
            hl_row=None,
            ghost=None,
            goffs=(gx, gy),
            ghost_w=180,
        )
        self.bind_all("<B1-Motion>", self._pipeline_motion_all)
        self.bind_all("<ButtonRelease-1>", self._pipeline_release_all)

    def _pipeline_motion_all(self, event) -> None:
        self._pipeline_motion_core(event.x_root, event.y_root)

    def _pipeline_motion_core(self, x_root: int, y_root: int) -> None:
        d = self._pipe_drag
        if not d:
            return
        if abs(x_root - d.x0) + abs(y_root - d.y0) > 6:
            if not d.visual_on:
                d.visual_on = True
                self.update_idletasks()
                row = d.row
                rw = max(150, row.winfo_width())
                d.ghost_w = rw
                d.ghost = self._make_drag_ghost(d.mid, rw)
                gx = x_root - d.goffs[0]
                gy = y_root - d.goffs[1]
                d.ghost.geometry(f"{rw}x32+{gx}+{gy}")
                self._pipeline_row_slot_style(row, d.title_lbl)
                try:
                    self.configure(cursor="fleur")
                except tk.TclError:
                    pass
            d.moved = True
            gh = d.ghost
            if gh is not None:
                try:
                    rw = d.ghost_w
                    ox, oy = d.goffs
                    gh.geometry(f"{rw}x32+{x_root - ox}+{y_root - oy}")
                except tk.TclError:
                    pass
            self._pipeline_update_drop_preview(y_root)

    def _pipeline_update_drop_preview(self, y_root: int) -> None:
        d = self._pipe_drag
        if not d or not d.visual_on:
            return
        drag_row = d.row
        rows = self._pipeline_scroll_rows()
        target_idx = self._pipeline_row_index_at_y(y_root)
        prev = d.hl_row
        if prev is not None and prev.winfo_exists() and prev is not drag_row:
            self._pipeline_row_idle_style(prev)
        d.hl_row = None
        if target_idx is None or not (0 <= target_idx < len(rows)):
            return
        target = rows[target_idx]
        if target is drag_row:
            return
        target.configure(
            fg_color=C.GRAY_ROW,
            border_width=2,
            border_color=C.DROP_PREVIEW_BORDER,
            cursor="hand2",
        )
        d.hl_row = target

    def _pipeline_release_all(self, event) -> None:
        d = self._pipe_drag
        if d is None:
            return
        self.unbind_all("<B1-Motion>")
        self.unbind_all("<ButtonRelease-1>")
        idx0 = d.idx
        mid = d.mid
        title_lbl = d.title_lbl
        drag_row = d.row
        moved = d.moved
        hl = d.hl_row
        ghost = d.ghost
        self._pipe_drag = None
        try:
            self.configure(cursor="")
        except tk.TclError:
            pass
        if ghost is not None:
            try:
                ghost.destroy()
            except tk.TclError:
                pass
        if moved:
            to = self._pipeline_row_index_at_y(event.y_root)
            if to is not None and to != idx0:
                self._save_undo_state()
                reorder_pipeline(self.analysis_pipeline, idx0, to)
                self._refresh_analysis_ui()
            else:
                if drag_row and drag_row.winfo_exists():
                    self._pipeline_row_idle_style(drag_row)
                    if title_lbl.winfo_exists():
                        title_lbl.configure(text=self._analysis_label(mid))
                if hl and hl.winfo_exists() and hl is not drag_row:
                    self._pipeline_row_idle_style(hl)
        else:
            if 0 <= idx0 < len(self.analysis_pipeline):
                self._save_undo_state()
                self.analysis_pipeline.pop(idx0)
                self._refresh_analysis_ui()

    def _pipeline_row_index_at_y(self, y_root: int):
        rows = self._pipeline_scroll_rows()
        for i, c in enumerate(rows):
            try:
                top = c.winfo_rooty()
                bot = top + c.winfo_height()
                if top <= y_root < bot:
                    return i
            except tk.TclError:
                continue
        return None

    def setup_file_page(self) -> None:
        self._upload_border_idle = C.UPLOAD_BORDER_IDLE
        self._upload_fg_idle = C.UPLOAD_FG_IDLE
        self._upload_dnd_hint_idle = (
            "Перетащите файл из проводника, дважды щёлкните по области\nили нажмите кнопку ниже (Ctrl+O)",
            ("gray40", "gray60"),
        )

        self.upload_box = ctk.CTkFrame(
            self.frames["Файл"],
            border_width=2,
            border_color=self._upload_border_idle,
            fg_color=self._upload_fg_idle,
            corner_radius=14,
            width=C.UPLOAD_BOX_W,
            height=C.UPLOAD_BOX_H,
        )
        self.upload_box.place(relx=0.5, rely=0.5, anchor="center")
        self.upload_box.pack_propagate(False)

        self.upload_glyph = ctk.CTkLabel(
            self.upload_box,
            text="⬇",
            font=C.FONT_ICON_LARGE,
            text_color=(C.ACCENT, C.ACCENT_LIGHT),
        )
        self.upload_glyph.pack(pady=(36, 0))

        self.upload_title = ctk.CTkLabel(self.upload_box, text="Область загрузки", font=C.FONT_TITLE)
        self.upload_title.pack(pady=(4, 6))
        self.upload_formats = ctk.CTkLabel(
            self.upload_box,
            text="Доступные форматы: .sgy, .segy",
            font=C.FONT_SUB,
            text_color=C.ACCENT,
        )
        self.upload_formats.pack(pady=(0, 8))

        self.upload_dnd_hint = ctk.CTkLabel(
            self.upload_box,
            text=self._upload_dnd_hint_idle[0],
            font=("Arial", 15),
            text_color=self._upload_dnd_hint_idle[1],
            justify="center",
        )
        self.upload_dnd_hint.pack(pady=(0, 14))

        self.btn_select = ctk.CTkButton(
            self.upload_box,
            text="Выбрать файл  (Ctrl+O)",
            width=240,
            height=50,
            font=("Arial", 16),
            command=self.open_file_dialog,
        )
        self.btn_select.pack(pady=10)

        self.file_status = ctk.CTkLabel(
            self.upload_box,
            text="Файл не выбран",
            font=C.FONT_SUB,
            text_color="gray",
        )
        self.file_status.pack(pady=(10, 36))

        self._register_file_drop_targets()

    def _register_file_drop_targets(self) -> None:
        if DND_FILES is None:
            return
        widgets = (
            self.frames["Файл"],
            self.upload_box,
            self.upload_glyph,
            self.upload_title,
            self.upload_formats,
            self.upload_dnd_hint,
            self.btn_select,
            self.file_status,
        )
        for w in widgets:
            for surf in iter_ctk_drop_surfaces(w):
                if not hasattr(surf, "drop_target_register") or not hasattr(surf, "dnd_bind"):
                    continue
                try:
                    surf.drop_target_register(DND_FILES)
                    surf.dnd_bind("<<Drop>>", self._on_file_drop)
                    surf.dnd_bind("<<DropEnter>>", self._on_drop_enter)
                    surf.dnd_bind("<<DropLeave>>", self._on_drop_leave)
                except (tk.TclError, AttributeError):
                    continue

    def _cancel_scheduled_drop_unhighlight(self) -> None:
        if self._dnd_leave_timer is not None:
            self.after_cancel(self._dnd_leave_timer)
            self._dnd_leave_timer = None

    def _on_drop_enter(self, event):
        if DND_FILES is None:
            return
        self._cancel_scheduled_drop_unhighlight()
        self._set_drop_zone_highlight(True)
        return COPY

    def _on_drop_leave(self, event) -> None:
        if DND_FILES is None:
            return

        def _unhighlight():
            self._dnd_leave_timer = None
            self._set_drop_zone_highlight(False)

        self._cancel_scheduled_drop_unhighlight()
        self._dnd_leave_timer = self.after(45, _unhighlight)

    def _set_drop_zone_highlight(self, active: bool) -> None:
        if active:
            self.upload_box.configure(
                border_width=3,
                border_color=C.UPLOAD_ACTIVE_BORDER,
                fg_color=C.UPLOAD_ACTIVE_FG,
            )
            self.upload_dnd_hint.configure(
                text="Отпустите файл здесь — он будет загружен",
                text_color=C.ACCENT,
            )
            self.upload_glyph.configure(text="📥", text_color=(C.ACCENT_DARK, C.ACCENT_HOVER))
        else:
            self.upload_box.configure(
                border_width=2,
                border_color=self._upload_border_idle,
                fg_color=self._upload_fg_idle,
            )
            self.upload_dnd_hint.configure(
                text=self._upload_dnd_hint_idle[0],
                text_color=self._upload_dnd_hint_idle[1],
            )
            self.upload_glyph.configure(
                text="⬇",
                text_color=(C.ACCENT, C.ACCENT_LIGHT),
            )

    def _on_file_drop(self, event) -> None:
        if DND_FILES is None:
            return
        self._cancel_scheduled_drop_unhighlight()
        self._set_drop_zone_highlight(False)
        raw = getattr(event, "data", "") or ""
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8")
            except UnicodeDecodeError:
                raw = raw.decode(locale.getpreferredencoding(False), errors="replace")
        else:
            raw = str(raw)
        paths = parse_dropped_file_paths(self, raw)
        if not paths:
            self.file_status.configure(text="Не удалось разобрать путь из Drag&Drop", text_color=C.STATUS_WARN)
            return COPY
        for path in paths:
            self.submit_load_seismic(path)
            break
        return COPY

    def open_file_dialog(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Seismic data", "*.sgy *.segy")])
        if path:
            self.submit_load_seismic(path)

    def setup_view_settings(self) -> None:
        f = self.frames["Вид"]
        ctk.CTkLabel(f, text="Настройки интерфейса", font=("Arial", 24, "bold")).pack(pady=40)
        container = ctk.CTkFrame(f, fg_color="transparent")
        container.pack()
        for lbl, vals, opt in [
            ("Тема приложения:", ["System", "Dark", "Light"], "theme"),
            ("Масштаб:", ["80%", "100%", "120%"], "scale"),
        ]:
            r = ctk.CTkFrame(container, fg_color="transparent")
            r.pack(pady=10)
            ctk.CTkLabel(r, text=lbl, width=150, anchor="w", font=C.FONT_SUB).pack(side="left")
            menu = ctk.CTkOptionMenu(
                r,
                values=vals,
                command=lambda v, o=opt: self.update_view_settings(**{o: v}),
            )
            menu.pack(side="left")
            if opt == "theme":
                self.theme_menu = menu
            else:
                self.scale_menu = menu

    def _set_data_entries_enabled(self, enabled: bool) -> None:
        st: str = "normal" if enabled else "disabled"
        self.entry_data_start.configure(state=st)
        self.entry_data_end.configure(state=st)
        self.entry_data_step.configure(state=st)
        self.btn_data_read.configure(state=st)

    def _set_data_read_busy(self, busy: bool) -> None:
        self.btn_data_cancel.configure(state="normal" if busy else "disabled")
        if busy:
            self._set_data_entries_enabled(False)
        else:
            self._set_data_entries_enabled(self.total_traces > 0 and bool(self.current_file_path))

    def _set_entry_int(self, entry: Any, value: int) -> None:
        entry.delete(0, "end")
        entry.insert(0, str(int(value)))

    def _sync_data_entries_from_inputs(self) -> None:
        if self.total_traces <= 0:
            return
        try:
            start = int(self.entry_data_start.get()) if self.entry_data_start.get().strip() else 0
            end = int(self.entry_data_end.get()) if self.entry_data_end.get().strip() else self.total_traces
            step = int(self.entry_data_step.get()) if self.entry_data_step.get().strip() else 1
        except ValueError:
            return
        start = max(0, min(start, self.total_traces - 1))
        end = max(start + 1, min(end, self.total_traces))
        max_step = max(1, min(1000, max(1, self.total_traces // 10)))
        step = max(1, min(step, max_step))
        self._set_entry_int(self.entry_data_start, start)
        self._set_entry_int(self.entry_data_end, end)
        self._set_entry_int(self.entry_data_step, step)
        # Ручной ввод диапазона (вкладка «Анализ») не должен менять график «Главная».

    def _on_data_entries_focus_out(self, _event=None) -> None:
        self._sync_data_entries_from_inputs()

    def _home_trace_from_x(self, x_value: Any) -> Optional[int]:
        if x_value is None:
            return None
        try:
            x = float(x_value)
            if self._home_view_end <= self._home_view_start:
                return None
            step = max(1, int(self._home_view_step or 1))
            # Ось X выровнена так, что центр каждой трассы находится в целой координате.
            idx = int(round((x - float(self._home_view_start)) / float(step)))
            trace = int(self._home_view_start + idx * step)
        except Exception:
            return None
        left = int(self._home_view_start)
        right = int(self._home_view_end) - 1
        if right < left:
            return None
        trace = max(left, min(right, trace))
        return max(0, min(self.total_traces - 1, trace))

    def _draw_home_selection_overlay(self, start: int, end: int) -> None:
        if not getattr(self, "_home_matplotlib_ok", False) or self.total_traces <= 0:
            return
        ax = self._home_ax_before
        for p in list(self._home_selection_patches):
            try:
                p.remove()
            except Exception:
                pass
        self._home_selection_patches.clear()
        if self._home_selection_patch is not None:
            try:
                self._home_selection_patch.remove()
            except Exception:
                pass
        if self._home_view_end <= self._home_view_start:
            return
        step = max(1, int(self._home_view_step or 1))
        ranges = self._home_selected_ranges[:] if self._home_selected_ranges else [(int(start), int(end))]
        for rs, re in ranges:
            left_trace = max(int(self._home_view_start), int(rs))
            right_trace_excl = min(int(self._home_view_end), int(re))
            if right_trace_excl <= left_trace:
                right_trace_excl = left_trace + step
            left = float(left_trace) - 0.5 * float(step)
            right = float(right_trace_excl) - 0.5 * float(step)
            self._home_selection_patches.append(
                ax.axvspan(min(left, right), max(left, right), color=str(C.ACCENT), alpha=0.25)
            )
        if self._home_selection_patches:
            self._home_selection_patch = self._home_selection_patches[-1]
        self._home_canvas_before.draw_idle()

    def _on_home_before_press(self, event) -> None:
        if not getattr(self, "_home_matplotlib_ok", False) or event.inaxes is not self._home_ax_before:
            return
        tr = self._home_trace_from_x(event.xdata)
        if tr is None:
            return
        self._home_drag_anchor = tr
        self._apply_home_plot_selection(tr, tr)

    def _on_home_before_motion(self, event) -> None:
        if self._home_drag_anchor is None or event.inaxes is not self._home_ax_before:
            return
        tr = self._home_trace_from_x(event.xdata)
        if tr is None:
            return
        self._apply_home_plot_selection(self._home_drag_anchor, tr)

    def _on_home_before_release(self, event) -> None:
        if self._home_drag_anchor is None:
            return
        tr = self._home_trace_from_x(event.xdata)
        if tr is None:
            tr = self._home_drag_anchor
        self._apply_home_plot_selection(self._home_drag_anchor, tr)
        self._home_drag_anchor = None

    def _apply_home_plot_selection(self, trace_a: int, trace_b: int) -> None:
        left = min(trace_a, trace_b)
        right = max(trace_a, trace_b)
        left = max(self._home_view_start, left)
        right = min(self._home_view_end - 1, right)
        if right < left:
            right = left
        rng = (int(left), int(min(self.total_traces, right + 1)))
        if self._home_ctrl_down:
            self._home_selected_ranges.append(rng)
            self._home_selected_ranges.sort(key=lambda x: x[0])
            merged: list[tuple[int, int]] = []
            for s, e in self._home_selected_ranges:
                if not merged:
                    merged.append((s, e))
                    continue
                ps, pe = merged[-1]
                if s <= pe:
                    merged[-1] = (ps, max(pe, e))
                else:
                    merged.append((s, e))
            self._home_selected_ranges = merged
        else:
            self._home_selected_ranges = [rng]
        self._set_entry_int(self.entry_data_start, rng[0])
        self._set_entry_int(self.entry_data_end, rng[1])
        self._draw_home_selection_overlay(rng[0], rng[1])

    def _sync_data_tab_after_load(self) -> None:
        for e in (self.entry_data_start, self.entry_data_end, self.entry_data_step):
            e.configure(state="normal")
            e.delete(0, "end")
        self.label_data_result.configure(text="")
        if self.total_traces <= 0 or not self.current_file_path:
            self.label_data_meta.configure(
                text="Метаданные SEG-Y недоступны (проверьте файл и segyio).",
                text_color=C.STATUS_WARN,
            )
            self._set_data_entries_enabled(False)
            return
        self.label_data_meta.configure(
            text=f"Всего трасс: {self.total_traces}\nОтсчётов на трассу: {self.samples_count}",
            text_color=C.GRAY_TEXT,
        )
        self._set_data_entries_enabled(True)
        self.btn_data_cancel.configure(state="disabled")
        self.entry_data_end.configure(placeholder_text=str(self.total_traces))
        self._set_entry_int(self.entry_data_start, 0)
        self._set_entry_int(self.entry_data_end, self.total_traces)
        self._set_entry_int(self.entry_data_step, 1)
        self._home_view_start = 0
        self._home_view_end = self.total_traces
        self._home_view_step = 1
        self._sync_data_entries_from_inputs()

    def _reset_data_tab_state(self) -> None:
        if self._process_cancel is not None:
            self._process_cancel.set()
        self._process_cancel = None
        try:
            self.btn_processing_cancel.configure(state="disabled")
            self.btn_processing.configure(state="normal")
        except Exception:
            pass
        if self._data_read_cancel is not None:
            self._data_read_cancel.set()
        self._data_read_cancel = None
        self.total_traces = 0
        self.samples_count = 0
        self.matrix_data = None
        for e in (self.entry_data_start, self.entry_data_end, self.entry_data_step):
            e.configure(state="normal")
            e.delete(0, "end")
        self.label_data_meta.configure(
            text="Файл не загружен — сначала откройте SEG-Y на вкладке «Файл».",
            text_color=C.GRAY_TEXT_MUTED,
        )
        self.label_data_result.configure(text="")
        self._set_data_entries_enabled(False)
        self.btn_data_cancel.configure(state="disabled")
        self.entry_data_end.configure(placeholder_text="—")
        self._home_view_start = 0
        self._home_view_end = 0
        self._home_view_step = 1
        self._home_locked_by_selection = False
        self._home_selected_ranges = []
        self._home_selection_patches = []
        if self._home_window_cancel is not None:
            try:
                self._home_window_cancel.set()
            except Exception:
                pass
        self._home_window_cancel = None
        self._home_window_last = None
        if self._home_window_after is not None:
            try:
                self.after_cancel(self._home_window_after)
            except Exception:
                pass
        self._home_window_after = None
        try:
            if self.home_slider_status is not None:
                self.home_slider_status.configure(text="")
        except Exception:
            pass

    def _sync_home_slider_after_load(self) -> None:
        self._home_window_start = 0
        self._home_window_last = None
        try:
            if self.home_slider_status is not None:
                self.home_slider_status.configure(text="")
        except Exception:
            pass

    def _on_home_scroll(self, event) -> None:
        if event is None or event.inaxes is not getattr(self, "_home_ax_before", None):
            return
        if not self.current_file_path or self.total_traces <= 0:
            return
        direction = 0
        try:
            if hasattr(event, "step") and event.step:
                direction = 1 if float(event.step) > 0 else -1
            elif getattr(event, "button", None) == "up":
                direction = 1
            elif getattr(event, "button", None) == "down":
                direction = -1
        except Exception:
            direction = 0
        self._scroll_home_window(direction)

    def _on_home_scroll_tk(self, event) -> str:
        """Прокрутка по тачпаду/колесу на Tk-виджете Matplotlib."""
        if not self._is_pointer_over_home_plot():
            return "break"
        if not self.current_file_path or self.total_traces <= 0:
            return "break"
        direction = 0
        try:
            # Windows/macOS обычно дают event.delta, Linux может давать num=4/5.
            delta = int(getattr(event, "delta", 0) or 0)
            if delta > 0:
                direction = 1
            elif delta < 0:
                direction = -1
            else:
                num = int(getattr(event, "num", 0) or 0)
                if num == 4:
                    direction = 1
                elif num == 5:
                    direction = -1
        except Exception:
            direction = 0
        self._scroll_home_window(direction)
        return "break"

    def _on_global_wheel(self, event) -> Optional[str]:
        # Глобальный fallback: часть тачпадов шлёт wheel-события не в canvas.
        if not self._is_pointer_over_home_plot():
            return None
        return self._on_home_scroll_tk(event)

    def _is_pointer_over_home_plot(self) -> bool:
        if self.current_state.get("tab") != "Главная":
            return False
        w = self._home_scroll_widget
        if w is None:
            return False
        try:
            px = int(self.winfo_pointerx())
            py = int(self.winfo_pointery())
            under = self.winfo_containing(px, py)
        except Exception:
            return False
        if under is None:
            return False
        cur = under
        while cur is not None:
            if cur is w:
                return True
            try:
                cur = cur.master
            except Exception:
                break
        return False

    def _scroll_home_window(self, direction: int) -> None:
        if direction == 0:
            return
        if not self.current_file_path or self.total_traces <= 0:
            return
        if self._home_locked_by_selection:
            try:
                if self.home_slider_status is not None:
                    self.home_slider_status.configure(text="Снимите выбор, чтобы снова прокручивать график.")
            except Exception:
                pass
            return
        step = 10
        max_start = max(0, int(self.total_traces) - int(self._home_window_size))
        base = int(self._home_window_target if self._home_window_target is not None else self._home_window_start)
        start = int(max(0, min(max_start, base - direction * step)))
        self._home_window_target = start
        if self._home_window_after is not None:
            try:
                self.after_cancel(self._home_window_after)
            except Exception:
                pass
            self._home_window_after = None
        self._home_window_after = self.after(20, lambda: self._request_home_window_read(start))

    def _clear_home_selection_lock(self) -> None:
        """Снять выбор диапазона и вернуть прокрутку окна 500 трасс."""
        self._home_locked_by_selection = False
        self._home_selected_ranges = []
        self._home_selection_patches = []
        if self.current_file_path and self.total_traces > 0:
            self._request_home_window_read(int(self._home_window_start), force=True)
        try:
            if self.home_slider_status is not None:
                self.home_slider_status.configure(text="")
        except Exception:
            pass

    def _request_home_window_read(self, start: int, *, force: bool = False) -> None:
        if not self.current_file_path or self.total_traces <= 0:
            return
        window = int(self._home_window_size)
        if window <= 0:
            return

        # Если трасс >= 500 — всегда показываем ровно 500 и не "сжимаем" окно у конца файла.
        if int(self.total_traces) >= window:
            max_start = int(self.total_traces) - window
            start = int(max(0, min(int(start), max_start)))
            end = int(start + window)
        else:
            # Иначе показываем всё, что есть (меньше 500 физически не получить).
            start = 0
            end = int(self.total_traces)
            if end <= 0:
                return
        if not force and self._home_window_last == (start, end):
            return
        self._home_window_last = (start, end)
        self._home_window_start = int(start)
        self._home_window_target = int(start)

        ev = self._home_window_cancel
        if ev is not None:
            try:
                ev.set()
            except Exception:
                pass
        cancel_event = threading.Event()
        self._home_window_cancel = cancel_event

        self._home_window_request_id += 1
        req_id = self._home_window_request_id

        # Область видимости для выбора мышью — только текущее окно.
        self._home_view_start = start
        self._home_view_end = end
        self._home_view_step = 1

        try:
            self._set_entry_int(self.entry_data_start, start)
            self._set_entry_int(self.entry_data_end, end)
            self._set_entry_int(self.entry_data_step, 1)
        except Exception:
            pass

        try:
            if self.home_slider_status is not None:
                self.home_slider_status.configure(text="Чтение окна: 0%")
        except Exception:
            pass

        self._logic_queue.put(
            LogicTaskReadDataRange(
                path=self.current_file_path,
                request_id=req_id,
                start=start,
                end=end,
                step=1,
                chunk_size=2000,
                max_full_matrix_bytes=256 * 1024 * 1024,
                preview_target=int(self._home_window_size),
                cancel_event=cancel_event,
            )
        )

    def _apply_home_window_read_result(self, msg: UiMessageReadDataResult) -> None:
        try:
            if self.home_slider_status is not None:
                self.home_slider_status.configure(text="")
        except Exception:
            pass
        self._home_view_start = int(msg.start)
        self._home_view_end = int(msg.end)
        self._home_view_step = int(max(1, msg.step))
        self._home_window_start = int(msg.start)
        self._home_window_target = int(msg.start)

        plot_matrix = msg.full_matrix if msg.keep_full_matrix and msg.full_matrix is not None else msg.preview_matrix
        if plot_matrix is None:
            return
        self._update_home_before_from_matrix(plot_matrix)
        try:
            self._draw_home_selection_overlay(int(msg.start), int(msg.end))
        except Exception:
            pass

    def _on_data_read_to_memory(self) -> None:
        if not self.current_file_path or self.total_traces <= 0:
            return
        try:
            start = int(self.entry_data_start.get()) if self.entry_data_start.get().strip() else 0
            end = int(self.entry_data_end.get()) if self.entry_data_end.get().strip() else self.total_traces
            step = int(self.entry_data_step.get()) if self.entry_data_step.get().strip() else 1
        except ValueError:
            self.label_data_result.configure(text="Ошибка: введите целые числа в поля От / До / Шаг.", text_color=C.STATUS_WARN)
            return

        if step <= 0:
            self.label_data_result.configure(text="Ошибка: шаг должен быть больше 0.", text_color=C.STATUS_WARN)
            return
        if start < 0 or end > self.total_traces or start >= end:
            self.label_data_result.configure(
                text=f"Ошибка: диапазон трасс 0 … {self.total_traces}, нужно От < До.",
                text_color=C.STATUS_WARN,
            )
            return

        self._start_data_read_request(start, end, step)

    def _cancel_data_read(self) -> None:
        ev = self._data_read_cancel
        if ev is not None:
            ev.set()
        self.label_data_result.configure(text="Отмена чтения...", text_color=C.STATUS_PENDING)
        self._set_data_read_busy(False)

    def _start_data_read_request(self, start: int, end: int, step: int) -> None:
        if not self.current_file_path:
            return
        cache_key = (
            self.current_file_path,
            int(os.path.getmtime(self.current_file_path)),
            start,
            end,
            step,
        )
        cached = self._data_range_cache.get(cache_key)
        if cached is not None:
            self.matrix_data = cached["full_matrix"]
            self.label_data_result.configure(
                text=cached["message"] + " (из кэша)",
                text_color=C.STATUS_OK,
            )
            # При "Выбрать данные" обновляем график на вкладке "Главная", без всплывающего окна.
            self._home_view_start = int(start)
            self._home_view_end = int(end)
            self._home_view_step = int(max(1, step))
            self._home_locked_by_selection = True
            self._update_home_before_from_matrix(cached["plot_matrix"])
            self._draw_home_selection_overlay(start, end)
            try:
                if self.home_slider_status is not None:
                    self.home_slider_status.configure(text="Выбор зафиксирован. Нажмите «Снять выбор».")
            except Exception:
                pass
            return

        self._data_read_request_id += 1
        req_id = self._data_read_request_id
        cancel_event = threading.Event()
        self._data_read_cancel = cancel_event
        self._set_data_read_busy(True)
        self.label_data_result.configure(text="Чтение данных: 0%", text_color=C.STATUS_PENDING)
        self._logic_queue.put(
            LogicTaskReadDataRange(
                path=self.current_file_path,
                request_id=req_id,
                start=start,
                end=end,
                step=step,
                chunk_size=5000,
                max_full_matrix_bytes=512 * 1024 * 1024,
                preview_target=512,
                cancel_event=cancel_event,
            )
        )

    def _store_data_range_cache(self, key: tuple[str, int, int, int, int], value: dict[str, Any]) -> None:
        self._data_range_cache[key] = value
        if len(self._data_range_cache) > 8:
            oldest = next(iter(self._data_range_cache))
            self._data_range_cache.pop(oldest, None)

    def _apply_data_read_result(self, msg: UiMessageReadDataResult) -> None:
        mode_msg = "Данные в памяти" if msg.keep_full_matrix else "Потоковый режим (без полной загрузки в RAM)"
        text = (
            f"{mode_msg}: матрица {msg.selected_traces}×{msg.n_samples} "
            f"(трассы {msg.start}:{msg.end}:{msg.step}), max|A|={msg.max_abs:.3g}."
        )
        self.matrix_data = msg.full_matrix
        plot_matrix = msg.full_matrix if msg.keep_full_matrix and msg.full_matrix is not None else msg.preview_matrix
        self._analysis_export_source = plot_matrix
        self.label_data_result.configure(text=text, text_color=C.STATUS_OK)
        # При "Выбрать данные" обновляем график на "Главная" и фиксируем диапазон до снятия выбора.
        self._home_view_start = int(msg.start)
        self._home_view_end = int(msg.end)
        self._home_view_step = int(max(1, msg.step))
        self._home_locked_by_selection = True
        self._update_home_before_from_matrix(plot_matrix)
        self._draw_home_selection_overlay(int(msg.start), int(msg.end))
        try:
            if self.home_slider_status is not None:
                self.home_slider_status.configure(text="Выбор зафиксирован. Нажмите «Снять выбор».")
        except Exception:
            pass
        try:
            cache_key = (
                self.current_file_path or "",
                int(os.path.getmtime(self.current_file_path or "")),
                msg.start,
                msg.end,
                msg.step,
            )
            self._store_data_range_cache(
                cache_key,
                {
                    "full_matrix": msg.full_matrix,
                    "plot_matrix": plot_matrix,
                    "message": text,
                },
            )
        except Exception:
            pass


    def _update_home_before_from_matrix(self, matrix: Any) -> None:
        """Обновить график «До» по полной матрице (после «Выбрать данные»)."""
        if not getattr(self, "_home_matplotlib_ok", False):
            self.label_data_result.configure(
                text="Данные считаны, но Matplotlib недоступен для отрисовки.",
                text_color=C.STATUS_WARN,
            )
            return

        axb = self._home_ax_before
        axb.clear()
        axb.axis("on")
        self._plot_matrix_on_ax(
            axb,
            matrix,
            int(self._home_view_start),
            int(max(1, self._home_view_step)),
            key="before",
        )
        axb.set_xlabel("Номер трассы")
        axb.set_ylabel("Время / отсчёт")
        axb.tick_params(labelsize=8)
        self._home_fig_before.subplots_adjust(left=0.08, right=0.96, top=0.95, bottom=0.13)
        self._home_canvas_before.draw()
        self.update_idletasks()

        self.after(10, self._home_refresh_matplotlib_geometry)
        self.after(200, self._home_refresh_matplotlib_geometry)

    def _plot_matrix_on_ax(self, ax: Any, matrix: Any, trace_start: int, trace_step: int, *, key: str) -> None:
        """Единый рендер матрицы для 'До/После': image или wiggle."""
        import numpy as np

        arr = np.asarray(matrix, dtype=np.float32)
        if arr.ndim != 2 or arr.size == 0:
            return
        flat = np.abs(arr).ravel()
        p98 = float(np.percentile(flat, 98.0)) if flat.size else 1.0
        if p98 <= 0.0:
            p98 = 1.0
        gain = float(getattr(self, "_home_amp_gain", 1.0) or 1.0)
        gain = max(0.1, min(10.0, gain))
        norm = np.clip((arr / p98) * gain, -1.0, 1.0)

        mode = str(self.current_state.get("plot_mode", C.PLOT_MODE_IMAGE) or C.PLOT_MODE_IMAGE)
        # Выравниваем геометрию оси X: центры трасс на целых значениях.
        x0 = float(trace_start) - 0.5 * float(trace_step)
        x1 = float(trace_start + trace_step * norm.shape[0]) - 0.5 * float(trace_step)

        if mode == C.PLOT_MODE_IMAGE:
            cmap = "gray"
            try:
                if C.active_color_scheme() == C.SCHEME_RED_BLUE:
                    cmap = "seismic"
            except Exception:
                pass
            ax.imshow(
                norm.T,
                aspect="auto",
                cmap=cmap,
                vmin=-1.0,
                vmax=1.0,
                interpolation="bilinear",
                origin="upper",
                extent=(x0, x1, float(norm.shape[1]), 0.0),
            )
            return

        max_traces = 500
        ntr = int(norm.shape[0])
        step_idx = max(1, int(ntr // max_traces))
        tr_idx = np.arange(0, ntr, step_idx, dtype=int)
        view = norm[tr_idx, :]

        y = np.arange(view.shape[1], dtype=np.float32)
        amp_scale = 0.45 * float(step_idx) * float(trace_step)
        base_x = trace_start + tr_idx * trace_step

        line_color = "#e6e6e6" if ctk.get_appearance_mode() == "Dark" else "#222222"
        fill_pos = mode == C.PLOT_MODE_WIGGLE_FILL
        fill_color = C.ACCENT_DARK if key == "after" and C.active_color_scheme() == C.SCHEME_RED_BLUE else C.ACCENT

        for i, bx in enumerate(base_x):
            tr = view[i, :]
            x = bx + tr * amp_scale
            ax.plot(x, y, lw=0.6, color=line_color, alpha=0.9)
            if fill_pos:
                ax.fill_betweenx(y, bx, x, where=(x >= bx), color=fill_color, alpha=0.22, linewidth=0)

        ax.set_xlim(x0, x1)
        ax.set_ylim(float(view.shape[1]), 0.0)

    def _open_plot_popup(self, key: str, title: str, matrix: Any, trace_start: int, trace_step: int) -> None:
        """Отдельное всплывающее окно с графиком (до/после)."""
        try:
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from matplotlib.figure import Figure
        except Exception:
            return

        old = self._plot_popups.get(key)
        if old is not None:
            try:
                old.destroy()
            except Exception:
                pass

        top = ctk.CTkToplevel(self)
        top.title(title)
        top.geometry("1120x680")
        top.minsize(700, 420)
        host = tk.Frame(top, bg="#ececec")
        host.pack(fill="both", expand=True)

        fig = Figure(figsize=(8.5, 4.6), dpi=100)
        ax = fig.add_subplot(111)
        self._plot_matrix_on_ax(ax, matrix, trace_start, trace_step, key=key)
        ax.set_xlabel("Номер трассы")
        ax.set_ylabel("Время / отсчёт")
        ax.tick_params(labelsize=9)
        fig.subplots_adjust(left=0.09, right=0.99, top=0.95, bottom=0.12)

        canvas = FigureCanvasTkAgg(fig, master=host)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        canvas.draw()
        self._plot_popups[key] = top

    def _on_home_amp_slider(self, value: float) -> None:
        self._home_amp_gain = float(value)
        if self._home_amp_var is not None:
            self._home_amp_var.set(f"{self._home_amp_gain:.2f}")
        self._redraw_home_if_ready()

    def _on_home_amp_entry_commit(self, _event=None) -> None:
        raw = self._home_amp_var.get().strip() if self._home_amp_var is not None else ""
        try:
            val = float(raw)
        except Exception:
            val = float(self._home_amp_gain)
        val = max(0.1, min(10.0, val))
        self._home_amp_gain = val
        if self._home_amp_var is not None:
            self._home_amp_var.set(f"{val:.2f}")
        try:
            self._home_amp_slider.set(val)
        except Exception:
            pass
        self._redraw_home_if_ready()

    def _redraw_home_if_ready(self) -> None:
        if not self.current_file_path or self.total_traces <= 0:
            return
        if self._home_locked_by_selection and self._analysis_export_source is not None:
            self._update_home_before_from_matrix(self._analysis_export_source)
        else:
            self._request_home_window_read(int(self._home_window_start), force=True)

    def _open_fourier_spectrum_popup(self) -> None:
        import numpy as np

        matrix = self._analysis_export_source if self._analysis_export_source is not None else self.matrix_data
        if matrix is None:
            messagebox.showinfo(
                "Спектр Фурье",
                "Сначала выберите данные на вкладке «Анализ» кнопкой «Выбрать данные».",
                parent=self,
            )
            return
        arr = np.asarray(matrix, dtype=np.float32)
        if arr.ndim != 2 or arr.size == 0:
            messagebox.showwarning("Спектр Фурье", "Недостаточно данных для построения спектра.", parent=self)
            return

        spec = np.abs(np.fft.rfft(arr, axis=1)).mean(axis=0)
        freq = np.fft.rfftfreq(arr.shape[1], d=1.0)

        try:
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from matplotlib.figure import Figure
        except Exception:
            messagebox.showwarning("Спектр Фурье", "Matplotlib недоступен.", parent=self)
            return

        old = self._plot_popups.get("fourier")
        if old is not None:
            try:
                old.destroy()
            except Exception:
                pass

        top = ctk.CTkToplevel(self)
        top.title("Спектр Фурье")
        top.geometry("900x560")
        top.minsize(700, 420)
        top.transient(self)

        host = ctk.CTkFrame(top, fg_color="transparent")
        host.pack(fill="both", expand=True, padx=8, pady=8)
        fig = Figure(figsize=(8.0, 5.0), dpi=100)
        ax = fig.add_subplot(111)
        ax.plot(freq, spec, color=str(C.ACCENT), lw=1.2)
        ax.set_title("Амплитудный спектр (FFT)")
        ax.set_xlabel("Нормированная частота")
        ax.set_ylabel("Амплитуда")
        ax.grid(True, alpha=0.25)
        fig.subplots_adjust(left=0.1, right=0.97, top=0.93, bottom=0.12)
        canvas = FigureCanvasTkAgg(fig, master=host)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        canvas.draw()
        self._plot_popups["fourier"] = top

    def _export_analysis_table(self) -> None:
        rows = self.analysis_table.get_children()
        if not rows:
            messagebox.showinfo("Выгрузка", "Таблица пуста: сначала выберите данные или запустите обработку.", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Выгрузить таблицу анализа",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            import csv

            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f, delimiter=";")
                cols = list(self.analysis_table["columns"])
                writer.writerow(cols)
                for item_id in rows:
                    writer.writerow(self.analysis_table.item(item_id, "values"))
            self.analysis_status_label.configure(text=f"Выгрузка завершена: {path}", text_color=C.STATUS_OK)
        except Exception as ex:
            self.analysis_status_label.configure(text=f"Ошибка выгрузки: {ex}", text_color=C.STATUS_WARN)

    def _home_matplotlib_host_bg(self) -> str:
        try:
            if ctk.get_appearance_mode() == "Dark":
                return str(C.ANALYSIS_WORKSPACE_INNER[1])
            return str(C.ANALYSIS_WORKSPACE_INNER[0])
        except Exception:
            return "#d8d8d8"

    def _home_refresh_matplotlib_geometry(self) -> None:
        """Matplotlib + CustomTkinter: canvas часто 0×0, пока не подогнать fig под виджет и не draw()."""
        if not getattr(self, "_home_matplotlib_ok", False):
            return
        if getattr(self, "_is_resizing", False):
            return
        pairs = ((self._home_canvas_before, self._home_fig_before),)
        for canvas, fig in pairs:
            if canvas is None or fig is None:
                continue
            tw = canvas.get_tk_widget()
            try:
                w = int(tw.winfo_width())
                h = int(tw.winfo_height())
            except tk.TclError:
                continue
            if w > 24 and h > 24:
                w = min(w, 3200)
                h = min(h, 2400)
                fig.set_size_inches(w / fig.get_dpi(), h / fig.get_dpi(), forward=False)
            try:
                canvas.draw()
            except Exception:
                pass

    def setup_home_page(self) -> None:
        """Вкладка «Главная»: один большой график исходных данных."""
        f = self.frames["Главная"]
        outer = ctk.CTkFrame(f, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=6, pady=6)
        outer.grid_columnconfigure(0, weight=1, uniform="home")
        outer.grid_rowconfigure(0, weight=0)
        outer.grid_rowconfigure(1, weight=1)

        top_controls = ctk.CTkFrame(outer, fg_color="transparent")
        top_controls.grid(row=0, column=0, sticky="ew", padx=2, pady=(0, 6))
        ctk.CTkLabel(top_controls, text="Амплитуда", font=C.FONT_SMALL, text_color=C.GRAY_TEXT).pack(
            side="left", padx=(4, 4)
        )
        self._home_amp_slider = ctk.CTkSlider(
            top_controls,
            from_=0.1,
            to=3.0,
            number_of_steps=58,
            width=180,
            command=self._on_home_amp_slider,
        )
        self._home_amp_slider.set(1.0)
        self._home_amp_slider.pack(side="left", padx=(0, 6))
        self._home_amp_var = tk.StringVar(value="1.00")
        self._home_amp_entry = ctk.CTkEntry(top_controls, width=64, textvariable=self._home_amp_var)
        self._home_amp_entry.pack(side="left", padx=(0, 10))
        self._home_amp_entry.bind("<Return>", self._on_home_amp_entry_commit)
        self._home_amp_entry.bind("<FocusOut>", self._on_home_amp_entry_commit)
        self._home_btn_clear_selection = ctk.CTkButton(
            top_controls,
            text="Снять выбор",
            width=130,
            height=30,
            font=C.FONT_SMALL,
            command=self._clear_home_selection_lock,
        )
        self._home_btn_clear_selection.pack(side="right", padx=(8, 4))

        def pane(row: int, col: int, title: str, pad_l: int, pad_r: int) -> ctk.CTkFrame:
            box = ctk.CTkFrame(
                outer,
                fg_color=C.PIPELINE_CARD_FG,
                corner_radius=C.RIBBON_CORNER_RADIUS,
                border_width=2,
                border_color=C.ACCENT_ON_BORDER,
            )
            box.grid(row=row, column=col, sticky="nsew", padx=(pad_l, pad_r), pady=(0, 2))
            box.grid_rowconfigure(1, weight=1)
            box.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                box,
                text=title,
                font=C.FONT_HEAD,
                text_color=C.GRAY_TEXT,
                anchor="w",
            ).grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 6))
            host = ctk.CTkFrame(
                box,
                fg_color=C.ANALYSIS_WORKSPACE_INNER,
                corner_radius=8,
                border_width=1,
                border_color=C.ANALYSIS_WORKSPACE_BORDER,
            )
            host.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
            return host

        self._home_plot_host_before = pane(1, 0, "Исходные данные", 0, 0)
        self._home_matplotlib_ok = False
        self._home_fig_before = None
        self._home_ax_before = None
        self._home_canvas_before = None

        try:
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from matplotlib.figure import Figure

            def mount(host: ctk.CTkFrame, placeholder: str) -> tuple[Any, Any, Any]:
                inner = tk.Frame(host, bg=self._home_matplotlib_host_bg(), highlightthickness=0, bd=0)
                inner.pack(fill="both", expand=True)
                fig = Figure(figsize=(5.0, 4.0), dpi=100)
                fig.patch.set_facecolor("#ececec")
                ax = fig.add_subplot(111)
                ax.set_facecolor("#e4e4e4")
                ax.axis("off")
                ax.text(
                    0.5,
                    0.5,
                    placeholder,
                    ha="center",
                    va="center",
                    transform=ax.transAxes,
                    fontsize=11,
                    color="#555555",
                )
                canvas = FigureCanvasTkAgg(fig, master=inner)
                canvas.get_tk_widget().pack(fill="both", expand=True)
                return fig, ax, canvas

            self._home_fig_before, self._home_ax_before, self._home_canvas_before = mount(
                self._home_plot_host_before,
                "Загрузите файл на вкладке «Файл».",
            )
            self._home_canvas_before.mpl_connect("button_press_event", self._on_home_before_press)
            self._home_canvas_before.mpl_connect("motion_notify_event", self._on_home_before_motion)
            self._home_canvas_before.mpl_connect("button_release_event", self._on_home_before_release)
            self._home_canvas_before.mpl_connect("scroll_event", self._on_home_scroll)
            try:
                tk_canvas = self._home_canvas_before.get_tk_widget()
                self._home_scroll_widget = tk_canvas
                tk_canvas.bind("<MouseWheel>", self._on_home_scroll_tk, add="+")
                tk_canvas.bind("<Button-4>", self._on_home_scroll_tk, add="+")
                tk_canvas.bind("<Button-5>", self._on_home_scroll_tk, add="+")
            except Exception:
                pass
            self._home_matplotlib_ok = True
        except Exception:
            ctk.CTkLabel(
                self._home_plot_host_before,
                text="Для графиков: pip install matplotlib numpy segyio",
                font=C.FONT_SMALL,
                text_color=C.GRAY_TEXT_MUTED,
                wraplength=220,
            ).pack(expand=True, padx=12, pady=24)

    def _home_apply_placeholder(self, ax: Any, text: str) -> None:
        ax.clear()
        ax.set_facecolor("#e4e4e4")
        ax.axis("off")
        ax.text(
            0.5,
            0.5,
            text,
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontsize=11,
            color="#555555",
        )

    def _reset_home_plots_empty(self) -> None:
        if not getattr(self, "_home_matplotlib_ok", False):
            return
        self._home_apply_placeholder(self._home_ax_before, "Загрузите файл на вкладке «Файл».")
        self._home_selection_patch = None
        self._home_locked_by_selection = False
        self._home_selected_ranges = []
        self._home_selection_patches = []
        self._home_canvas_before.draw()
        self.after(50, self._home_refresh_matplotlib_geometry)

    def _update_home_plots_after_load(self, preview: Optional[SeismicPreview]) -> None:
        if not getattr(self, "_home_matplotlib_ok", False):
            return
        axb = self._home_ax_before
        axb.clear()
        axb.axis("on")
        if preview is None:
            self._home_apply_placeholder(
                axb,
                "Файл подключён. Прокручивайте колесом мыши/тачпадом,\nчтобы подгружать и отображать окно из 500 трасс.",
            )
        else:
            import numpy as np

            try:
                arr = np.frombuffer(preview.data, dtype=np.float32).reshape(
                    preview.n_traces, preview.n_samples
                )
            except ValueError:
                self._home_apply_placeholder(
                    axb,
                    "Превью повреждено (размер буфера не совпадает с формой).",
                )
            else:
                self._plot_matrix_on_ax(axb, arr, 0, 1, key="before")
                axb.set_xlabel("Номер трассы")
                axb.set_ylabel("Время / отсчёт")
                axb.tick_params(labelsize=8)

        self._home_fig_before.subplots_adjust(left=0.08, right=0.96, top=0.95, bottom=0.13)
        if self.total_traces > 0:
            s = int(self.entry_data_start.get()) if self.entry_data_start.get().strip() else 0
            e = int(self.entry_data_end.get()) if self.entry_data_end.get().strip() else self.total_traces
            self._draw_home_selection_overlay(s, e)
        self._home_canvas_before.draw()
        self.update_idletasks()
        self.after(10, self._home_refresh_matplotlib_geometry)
        self.after(200, self._home_refresh_matplotlib_geometry)
    def _save_undo_state(self) -> None:
        """Сохраняем текущее состояние (файл + методы) в историю."""
        state_snapshot = {
            "pipeline": self.analysis_pipeline[:],
            "file_path": self.current_file_path,
        }
        self._undo_stack.append(state_snapshot)
        if len(self._undo_stack) > 30:
            self._undo_stack.pop(0)

    def _undo(self, event=None) -> None:
        
        if not self._undo_stack:
            self.status_hint_label.configure(text="История правок пуста")
            return
        
        last_state = self._undo_stack.pop()
        
        
        self.current_file_path = last_state["file_path"]
        if self.current_file_path:
            name = os.path.basename(self.current_file_path)
            self.file_status.configure(text=f"Восстановлен: {name}", text_color=C.STATUS_OK)
        else:
            self.file_status.configure(text="Файл не выбран", text_color="gray")
            
      
        self.analysis_pipeline = last_state["pipeline"]
        self._refresh_analysis_ui()
        self.status_hint_label.configure(text="Действие отменено (Ctrl+Z)")

    def clear_all_data(self) -> None:
        
        if not self.current_file_path and not self.analysis_pipeline:
            return

        if messagebox.askyesno("Очистка", "Удалить выбранный файл и цепочку обработки?", parent=self):
            self._save_undo_state()
            self.current_file_path = None
            self.file_status.configure(text="Файл не выбран", text_color="gray")
            self._reset_data_tab_state()
            self._reset_home_plots_empty()
            self.analysis_pipeline = []
            self._refresh_analysis_ui()
            for child in self.analysis_workspace_canvas.winfo_children():
                child.destroy()
    def save_state(self, tab: str) -> None:
        
        if self.is_navigating:
            return
        if self.current_state["tab"] == tab:
            return
        self.history_tabs = self.history_tabs[: self.history_index + 1]
        self.history_tabs.append(tab)
        self.history_index = len(self.history_tabs) - 1
        self.current_state["tab"] = tab
        self.apply_state(self.current_state)

    def update_view_settings(self, theme=None, scheme=None, plot_mode=None, scale=None) -> None:
        if self.is_navigating:
            return
        if theme:
            self.current_state["theme"] = theme
        if scheme:
            self.current_state["scheme"] = scheme
        if plot_mode:
            self.current_state["plot_mode"] = plot_mode
        if scale:
            self.current_state["scale"] = scale
        self.apply_state(self.current_state)
        self._persist_settings()

    def _apply_tab_ribbon(self, name: str) -> None:
        self.frames[name].tkraise()

        prev_tab = getattr(self, "_ribbon_style_tab", None)
        if prev_tab is None:
            for t_name, btn in self.tab_buttons.items():
                if t_name == name:
                    btn.configure(
                        fg_color=C.ACCENT,
                        text_color="white",
                        hover_color=C.ACCENT_DARK,
                    )
                else:
                    btn.configure(
                        fg_color=C.TAB_INACTIVE_FG,
                        text_color=C.TAB_INACTIVE_TEXT,
                        hover_color=C.TAB_HOVER,
                    )
        elif prev_tab != name:
            self.tab_buttons[prev_tab].configure(
                fg_color=C.TAB_INACTIVE_FG,
                text_color=C.TAB_INACTIVE_TEXT,
                hover_color=C.TAB_HOVER,
            )
            self.tab_buttons[name].configure(
                fg_color=C.ACCENT,
                text_color="white",
                hover_color=C.ACCENT_DARK,
            )
        self._ribbon_style_tab = name

        bucket = "home" if name == "Главная" else ("analysis" if name == "Анализ" else "none")
        if getattr(self, "_ribbon_bucket", None) == bucket:
            return
        self._ribbon_bucket = bucket

        if bucket == "home":
            self.home_tools.tkraise()
            self.ribbon.configure(
                height=C.RIBBON_HEIGHT_DEFAULT,
                fg_color=C.RIBBON_PANEL_BG,
                border_width=1,
                border_color=C.RIBBON_PANEL_BORDER,
                corner_radius=C.RIBBON_CORNER_RADIUS,
            )
        elif bucket == "analysis":
            self.analysis_tools.tkraise()
            self.ribbon.configure(
                height=C.RIBBON_HEIGHT_ANALYSIS,
                fg_color=C.RIBBON_PANEL_BG,
                border_width=1,
                border_color=C.RIBBON_PANEL_BORDER,
                corner_radius=C.RIBBON_CORNER_RADIUS,
            )
        else:
            self._ribbon_placeholder.tkraise()
            self.ribbon.configure(
                height=8,
                fg_color="transparent",
                border_width=0,
                corner_radius=0,
            )

    def _sync_theme_and_scale(self, state: dict[str, str]) -> None:
        ctk.set_appearance_mode(state["theme"])
        self.theme_menu.set(state["theme"])
        ctk.set_widget_scaling(int(state["scale"].replace("%", "")) / 100)
        self.scale_menu.set(state["scale"])
        try:
            self.scheme_menu.set(state.get("scheme", C.SCHEME_CLASSIC))
        except Exception:
            pass
        try:
            self.plot_mode_menu.set(state.get("plot_mode", C.PLOT_MODE_IMAGE))
        except Exception:
            pass

    def _sync_color_scheme(self, state: dict[str, str]) -> None:
        scheme = state.get("scheme") or C.SCHEME_CLASSIC
        applied = C.apply_color_scheme(scheme)
        state["scheme"] = applied
        self._apply_colors_to_widgets()

    def _apply_colors_to_widgets(self) -> None:
        """Перекрасить уже созданные виджеты после смены палитры."""
        try:
            self.configure(fg_color=C.WINDOW_BG)
        except Exception:
            pass
        try:
            self.top_container.configure(fg_color=C.TOPBAR_BG)
        except Exception:
            pass
        for w in (getattr(self, "logo_wave", None), getattr(self, "logo_label", None)):
            if w is not None:
                try:
                    w.configure(text_color=C.ACCENT)
                except Exception:
                    pass
        try:
            self._apply_tab_ribbon(self.current_state.get("tab", "Файл"))
        except Exception:
            pass
        for cb in getattr(self, "analysis_method_checkboxes", {}).values():
            try:
                cb.configure(fg_color=C.ACCENT, hover_color=C.ACCENT_DARK)
            except Exception:
                pass
        for btn_name in ("btn_processing",):
            btn = getattr(self, btn_name, None)
            if btn is not None:
                try:
                    btn.configure(fg_color=C.ACCENT, hover_color=C.ACCENT_DARK)
                except Exception:
                    pass
        w = getattr(self, "upload_formats", None)
        if w is not None:
            try:
                w.configure(text_color=C.ACCENT)
            except Exception:
                pass
        g = getattr(self, "upload_glyph", None)
        if g is not None:
            try:
                g.configure(text_color=(C.ACCENT, C.ACCENT_LIGHT))
            except Exception:
                pass
        if getattr(self, "_file_loading", False):
            pass
        try:
            if self.total_traces > 0:
                s = int(self.entry_data_start.get()) if self.entry_data_start.get().strip() else 0
                e = int(self.entry_data_end.get()) if self.entry_data_end.get().strip() else self.total_traces
                self._draw_home_selection_overlay(s, e)
        except Exception:
            pass

    def _load_persisted_settings(self) -> None:
        data = load_settings()
        theme = data.get("theme")
        scale = data.get("scale")
        scheme = data.get("scheme")
        plot_mode = data.get("plot_mode")
        if isinstance(theme, str) and theme in {"System", "Dark", "Light"}:
            self.current_state["theme"] = theme
        if isinstance(scale, str) and scale in {"80%", "100%", "120%"}:
            self.current_state["scale"] = scale
        if isinstance(scheme, str):
            self.current_state["scheme"] = scheme
        if isinstance(plot_mode, str):
            self.current_state["plot_mode"] = plot_mode

    def _persist_settings(self) -> None:
        try:
            save_settings(
                {
                    "theme": self.current_state.get("theme", "System"),
                    "scale": self.current_state.get("scale", "100%"),
                    "scheme": self.current_state.get("scheme", C.SCHEME_CLASSIC),
                    "plot_mode": self.current_state.get("plot_mode", C.PLOT_MODE_IMAGE),
                }
            )
        except Exception:
            pass

    def _sync_nav_buttons(self) -> None:
        can_back = self.history_index > 0
        can_fwd = self.history_index < len(self.history_tabs) - 1
        self.btn_back.configure(
            state="normal" if can_back else "disabled",
            fg_color=C.NAV_BTN_FG if can_back else C.NAV_BTN_DISABLED,
            text_color=C.NAV_BTN_TEXT if can_back else ("gray55", "gray50"),
            hover_color=C.NAV_BTN_HOVER if can_back else C.NAV_BTN_DISABLED,
        )
        self.btn_forward.configure(
            state="normal" if can_fwd else "disabled",
            fg_color=C.NAV_BTN_FG if can_fwd else C.NAV_BTN_DISABLED,
            text_color=C.NAV_BTN_TEXT if can_fwd else ("gray55", "gray50"),
            hover_color=C.NAV_BTN_HOVER if can_fwd else C.NAV_BTN_DISABLED,
        )

    def apply_state(self, state: dict[str, str]) -> None:
        self.is_navigating = True
        name = state["tab"]
        self._apply_tab_ribbon(name)
        need_view = (
            self._applied_theme is None
            or self._applied_scale is None
            or state["theme"] != self._applied_theme
            or state["scale"] != self._applied_scale
        )
        if need_view:
            self._sync_theme_and_scale(state)
            self._applied_theme = state["theme"]
            self._applied_scale = state["scale"]
        need_scheme = self._applied_scheme is None or state.get("scheme") != self._applied_scheme
        if need_scheme:
            self._sync_color_scheme(state)
            self._applied_scheme = state.get("scheme")
        self._sync_nav_buttons()
        self._refresh_status_bar()
        self.is_navigating = False
        if name == "Главная":
            self.after(80, self._home_refresh_matplotlib_geometry)

    def go_back(self) -> None:
        if self.history_index > 0:
            self.history_index -= 1
            self.current_state["tab"] = self.history_tabs[self.history_index]
            self.apply_state(self.current_state)

    def go_forward(self) -> None:
        if self.history_index < len(self.history_tabs) - 1:
            self.history_index += 1
            self.current_state["tab"] = self.history_tabs[self.history_index]
            self.apply_state(self.current_state)


def main() -> None:
    app = App()
    app.mainloop()

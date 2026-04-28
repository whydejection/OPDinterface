"""Цвета, шрифты и размеры — в т.ч. под эталонный макет окна «Анализ»."""

import sys

SCHEME_CLASSIC = "Classic"
SCHEME_RED_BLUE = "Red-Blue"

AVAILABLE_COLOR_SCHEMES = (SCHEME_CLASSIC, SCHEME_RED_BLUE)

PLOT_MODE_IMAGE = "Image"
PLOT_MODE_WIGGLE_FILL = "Wiggle (fill)"
PLOT_MODE_WIGGLE_LINE = "Wiggle (line)"

AVAILABLE_PLOT_MODES = (PLOT_MODE_IMAGE, PLOT_MODE_WIGGLE_FILL, PLOT_MODE_WIGGLE_LINE)

_PALETTES: dict[str, dict[str, object]] = {
    SCHEME_CLASSIC: {
        "ACCENT": "#3a8dcc",
        "ACCENT_LIGHT": "#5dade2",
        "ACCENT_DARK": "#2e7aaf",
        "ACCENT_HOVER": "#4a9fd4",
        "ACCENT_ON_BORDER": ("#2e7aaf", "#5dade2"),
        "DROP_PREVIEW_BORDER": "#5dade2",
    },
    SCHEME_RED_BLUE: {
        "ACCENT": "#2f80ed",
        "ACCENT_LIGHT": "#56a3ff",
        "ACCENT_DARK": "#eb5757",
        "ACCENT_HOVER": "#3b8ef2",
        "ACCENT_ON_BORDER": ("#1f6fd6", "#56a3ff"),
        "DROP_PREVIEW_BORDER": "#56a3ff",
    },
}

_active_color_scheme: str = SCHEME_CLASSIC


def apply_color_scheme(name: str) -> str:
    """Применить палитру (акцентные цвета) на уровне модуля constants.

    Возвращает фактически применённое имя схемы (если пришло неизвестное — откат на Classic).
    """
    global _active_color_scheme
    palette = _PALETTES.get(name) or _PALETTES[SCHEME_CLASSIC]
    applied = name if name in _PALETTES else SCHEME_CLASSIC
    _active_color_scheme = applied
    for k, v in palette.items():
        globals()[k] = v
    globals()["GHOST_BORDER"] = globals()["ACCENT"]
    return applied


def active_color_scheme() -> str:
    return _active_color_scheme

WINDOW_BG = ("#f2f2f2", "#1e1e1e")
TOPBAR_BG = ("#f2f2f2", "#1e1e1e")

ACCENT = "#3a8dcc"
ACCENT_LIGHT = "#5dade2"
ACCENT_DARK = "#2e7aaf"
ACCENT_HOVER = "#4a9fd4"
ACCENT_ON_BORDER = ("#2e7aaf", "#5dade2")

TAB_CORNER_RADIUS = 8
TAB_INACTIVE_FG = ("#e4e4e4", "#383838")
TAB_INACTIVE_TEXT = ("#1f1f1f", "#e8e8e8")
TAB_HOVER = ("#d8d8d8", "#454545")

NAV_BTN_FG = ("#e4e4e4", "#404040")
NAV_BTN_HOVER = ("#d4d4d4", "#505050")
NAV_BTN_TEXT = ("#333333", "#e0e0e0")
NAV_BTN_DISABLED = ("#c8c8c8", "#353535")

RIBBON_PANEL_BG = ("#e8e8e8", "#2c2c2c")
RIBBON_PANEL_BORDER = ("#c4c4c4", "#454545")
RIBBON_CORNER_RADIUS = 10
RIBBON_OUTER_PADX = 14
RIBBON_HEIGHT_DEFAULT = 118
RIBBON_HEIGHT_ANALYSIS = 168

RIBBON_BORDER = RIBBON_PANEL_BORDER
RIBBON_FG_MAIN = RIBBON_PANEL_BG

GRAY_BORDER_IDLE = ("#8a9aaa", "#6b6b6b")
GRAY_ROW = ("#e0e0e0", "#3d3d3d")
GRAY_ROW_ALT = ("#ececec", "#2a2a2a")
GRAY_TEXT_MUTED = ("#5a5a5a", "#a8a8a8")
GRAY_TEXT = ("#1a1a1a", "#e4e4e4")
GRAY_LABEL = ("#2a2a2a", "#d0d0d0")

UPLOAD_BORDER_IDLE = ("gray62", "gray36")
UPLOAD_FG_IDLE = ("#f4f7fb", "#2c2c2c")
UPLOAD_ACTIVE_BORDER = ACCENT
UPLOAD_ACTIVE_FG = ("#ddeefb", "#1f3344")

STATUS_OK = "#2ecc71"
STATUS_WARN = "#e67e22"
STATUS_PENDING = ("gray40", "gray60")

STATUS_BAR_BG = ("#ebebeb", "#252525")
STATUS_BAR_BORDER = ("#d4d4d4", "#383838")
STATUS_BAR_TEXT = ("#303030", "#c8c8c8")

TOOL_FG = ("#eeeeee", "#333333")
TOOL_TEXT = ("#1a1a1a", "#ffffff")
TOOL_HOVER = ("#dddddd", "#444444")
TOOL_BORDER = ("#cccccc", "#444444")

PIPELINE_CARD_FG = ("#ffffff", "#2c2c2c")
PIPELINE_CARD_BORDER = ("#c8c8c8", "#454545")
SEPARATOR_LINE = ("#d0d0d0", "#505050")

ANALYSIS_WORKSPACE_BG = ("#e0e0e0", "#333333")
ANALYSIS_WORKSPACE_BORDER = ("#c0c0c0", "#404040")
ANALYSIS_WORKSPACE_INNER = ("#d8d8d8", "#383838")

DROP_PREVIEW_BORDER = "#5dade2"
GHOST_BORDER = ACCENT

if sys.platform == "win32":
    _F = "Segoe UI"
else:
    _F = "Arial"

FONT_TITLE = (_F, 26, "bold")
FONT_HEAD = (_F, 15, "bold")
FONT_SUB = (_F, 14)
FONT_BODY = (_F, 11)
FONT_SMALL = (_F, 10)
FONT_RIBBON = (_F, 12, "bold")
FONT_RIBBON_SECTION = (_F, 13, "bold")
FONT_LOGO = (_F, 22, "bold")
FONT_GRIP = ("Segoe UI", 14) if sys.platform == "win32" else ("Arial", 14)
FONT_ICON_LARGE = ("Segoe UI Symbol", 44)

PIPELINE_SCROLL_HEIGHT = 420
PIPELINE_ROW_HEIGHT = 30
UPLOAD_BOX_W = 700
UPLOAD_BOX_H = 450
LEFT_COL_W = 360
PIPELINE_OUTER_W = 340

ANALYSIS_METHODS = (
    ("interp", "Интерполяция данных", "Интерполяция\nданных"),
    ("denoise", "Подавление шумов", "Подавление\nшумов"),
    ("spectrum", "Расширение амплитудного спектра", "Расширение\nамплитудного\nспектра"),
    ("resolution", "Повышение разрешающей способности", "Повышение\nразрешающей\nспособности"),
)
ANALYSIS_LABELS = {mid: full for mid, full, _ in ANALYSIS_METHODS}

TAB_STATUS_HINTS = {
    "Файл": "Перетащите .sgy / .segy или двойной клик по области.",
    "Главная": "Слева — исходные данные после загрузки; справа — после обработки (в разработке).",
    "Анализ": "Выберите диапазон трасс (От / До / Шаг), нажмите «Выбрать данные», затем запустите «Обработка».",
    "Вид": "Тема и масштаб применяются ко всему окну.",
}

STATUS_KEYS_DEFAULT = "Ctrl+1…4 — вкладки  ·  Ctrl+O — файл"
STATUS_KEYS_ANALYSIS = "Ctrl+1...4"

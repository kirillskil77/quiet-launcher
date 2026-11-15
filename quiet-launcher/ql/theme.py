"""Тёмная сдержанная тема для ttk (встроенная тема clam, без внешних картинок)."""
import os
import sys
import tkinter.font as tkfont
from tkinter import ttk

THEMES = {
    "black":    ("Чёрная",       dict(BG="#17191c", PANEL="#1f2226", FIELD="#121417", LINE="#2d3136", BTN="#2a2e33", BTN_HOVER="#343a40")),
    "graphite": ("Графит",       dict(BG="#222428", PANEL="#2b2e33", FIELD="#1b1d20", LINE="#3a3e44", BTN="#363a40", BTN_HOVER="#41464d")),
    "navy":     ("Тёмно-синяя",  dict(BG="#10151f", PANEL="#171e2b", FIELD="#0c1018", LINE="#253047", BTN="#212b3d", BTN_HOVER="#2a364c")),
    "purple":   ("Тёмно-фиолетовая", dict(BG="#171320", PANEL="#1f1a2c", FIELD="#110e19", LINE="#322a47", BTN="#2b2440", BTN_HOVER="#362d4f")),
}
ACCENTS = (("#4f8f6a", "Зелёный"), ("#4f86c6", "Синий"), ("#8a6cc9", "Фиолетовый"),
           ("#c9704f", "Оранжевый"), ("#c95f7f", "Розовый"), ("#c9a74f", "Золотой"), ("#4fb0b8", "Бирюзовый"))
DEFAULT_THEME, DEFAULT_ACCENT = "black", "#4f8f6a"

BG = PANEL = FIELD = LINE = BTN = BTN_HOVER = ""
FG = "#d9dce0"
MUTED = "#868c93"
ACCENT = ACCENT_HOVER = SELECT = ACCENT_DISABLED = ""
THEME_NAME = ACCENT_BASE = ""


def _rgb(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def mix_hex(a, b, t):
    ra, rb = _rgb(a), _rgb(b)
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(ra, rb))


def valid_color(c):
    return isinstance(c, str) and len(c) == 7 and c[0] == "#" and all(ch in "0123456789abcdefABCDEF" for ch in c[1:])


def configure(theme=DEFAULT_THEME, accent=DEFAULT_ACCENT):
    """Задаёт палитру. Вызывать до импорта ql.widgets / ql.ui — они берут цвета при загрузке."""
    global BG, PANEL, FIELD, LINE, BTN, BTN_HOVER, ACCENT, ACCENT_HOVER, SELECT, ACCENT_DISABLED
    global THEME_NAME, ACCENT_BASE
    if theme not in THEMES:
        theme = DEFAULT_THEME
    if not valid_color(accent):
        accent = DEFAULT_ACCENT
    g = globals()
    g.update(THEMES[theme][1])
    THEME_NAME, ACCENT_BASE = theme, accent.lower()
    ACCENT = ACCENT_BASE
    ACCENT_HOVER = mix_hex(ACCENT, "#ffffff", 0.14)
    SELECT = mix_hex(PANEL, ACCENT, 0.28)
    ACCENT_DISABLED = mix_hex(PANEL, ACCENT, 0.2)


configure()

def _default_font():
    if sys.platform == "darwin":
        return "Helvetica Neue"
    if sys.platform.startswith("linux"):
        return "DejaVu Sans"
    return "Segoe UI"


FONT = os.environ.get("QL_FONT") or _default_font()
MONO = "Consolas"


def apply_theme(root, scale=1.0):
    s = ttk.Style(root)
    s.theme_use("clam")
    root.configure(bg=BG)
    for name, size in (("TkDefaultFont", 10), ("TkTextFont", 10), ("TkMenuFont", 10), ("TkHeadingFont", 10)):
        tkfont.nametofont(name).configure(family=FONT, size=size)
    tkfont.nametofont("TkFixedFont").configure(family=MONO, size=9)

    s.configure(".", background=BG, foreground=FG, fieldbackground=FIELD, bordercolor=LINE,
                lightcolor=LINE, darkcolor=LINE, troughcolor=FIELD, focuscolor=BG,
                insertcolor=FG, selectbackground=SELECT, selectforeground=FG)

    s.configure("TFrame", background=BG)
    s.configure("Panel.TFrame", background=PANEL)
    s.configure("TLabel", background=BG, foreground=FG)
    s.configure("Muted.TLabel", foreground=MUTED)
    s.configure("Panel.TLabel", background=PANEL)
    s.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED, font=(FONT, 8, "bold"))
    s.configure("Title.TLabel", font=(FONT, 12, "bold"))
    s.configure("Head.TLabel", font=(FONT, 18, "bold"))
    s.configure("PanelTitle.TLabel", background=PANEL, font=(FONT, 12, "bold"))
    s.configure("PanelAccent.TLabel", background=PANEL, foreground=ACCENT_HOVER, font=(FONT, 12))
    s.configure("PanelNote.TLabel", background=PANEL, foreground=MUTED)
    s.configure("Field.TFrame", background=FIELD)
    s.configure("Code.TLabel", font=(MONO, 20, "bold"), foreground=ACCENT_HOVER)

    s.configure("TButton", background=BTN, foreground=FG, borderwidth=0, padding=(14, 6),
                focusthickness=0, relief="flat")
    s.map("TButton", background=[("disabled", PANEL), ("active", BTN_HOVER)],
          foreground=[("disabled", "#555a60")])
    s.configure("Accent.TButton", background=ACCENT, foreground="#ffffff", padding=(26, 8),
                font=(FONT, 11, "bold"))
    s.map("Accent.TButton", background=[("disabled", ACCENT_DISABLED), ("active", ACCENT_HOVER)],
          foreground=[("disabled", MUTED)])

    for w in ("TEntry", "TCombobox", "TSpinbox"):
        s.configure(w, fieldbackground=FIELD, foreground=FG, bordercolor=LINE, lightcolor=LINE,
                    darkcolor=LINE, insertcolor=FG, padding=5, arrowcolor=MUTED)
    s.configure("Flat.TEntry", fieldbackground=FIELD, foreground=FG, borderwidth=0, padding=(2, 3),
                bordercolor=FIELD, lightcolor=FIELD, darkcolor=FIELD, insertcolor=FG)
    s.map("Flat.TEntry", bordercolor=[("focus", FIELD)], lightcolor=[("focus", FIELD)],
          darkcolor=[("focus", FIELD)], fieldbackground=[("readonly", FIELD), ("disabled", FIELD)],
          foreground=[("disabled", MUTED)])
    s.configure("Flat.TCombobox", fieldbackground=FIELD, background=FIELD, foreground=FG, borderwidth=0,
                bordercolor=FIELD, lightcolor=FIELD, darkcolor=FIELD, arrowcolor=MUTED, padding=(6, 4),
                arrowsize=int(14 * scale))
    s.map("Flat.TCombobox", fieldbackground=[("readonly", FIELD), ("disabled", FIELD)],
          background=[("active", FIELD), ("readonly", FIELD)], foreground=[("readonly", FG)],
          bordercolor=[("focus", FIELD)], lightcolor=[("focus", FIELD)], darkcolor=[("focus", FIELD)],
          selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", FG)],
          arrowcolor=[("active", ACCENT_HOVER)])
    s.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", FG)],
          selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", FG)],
          bordercolor=[("focus", ACCENT)])
    s.map("TEntry", bordercolor=[("focus", ACCENT)])
    s.map("TSpinbox", bordercolor=[("focus", ACCENT)])
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", SELECT)
    root.option_add("*TCombobox*Listbox.selectForeground", FG)
    root.option_add("*TCombobox*Listbox.borderWidth", 0)

    s.configure("TCheckbutton", background=BG, foreground=FG)
    s.map("TCheckbutton", background=[("active", BG)],
          indicatorcolor=[("selected", ACCENT), ("!selected", FIELD)])

    s.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
    s.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(16, 7), borderwidth=0)
    s.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", FG)])

    s.configure("Treeview", background=FIELD, fieldbackground=FIELD, foreground=FG, borderwidth=0,
                rowheight=int(26 * scale))
    s.map("Treeview", background=[("selected", SELECT)], foreground=[("selected", FG)])
    s.configure("Treeview.Heading", background=PANEL, foreground=MUTED, relief="flat", padding=(8, 5),
                font=(FONT, 9))
    s.map("Treeview.Heading", background=[("active", PANEL)])
    s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    s.configure("List.Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG, borderwidth=0,
                rowheight=int(34 * scale), font=(FONT, 11))
    s.map("List.Treeview", background=[("selected", SELECT)], foreground=[("selected", "#ffffff")])
    s.layout("List.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    s.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=FIELD, borderwidth=0,
                lightcolor=ACCENT, darkcolor=ACCENT, thickness=6)
    for o in ("Vertical", "Horizontal"):
        s.configure(o + ".TScrollbar", background=BTN, troughcolor=FIELD, bordercolor=FIELD, arrowcolor=MUTED,
                    lightcolor=BTN, darkcolor=BTN, relief="flat", arrowsize=int(10 * scale))
        s.map(o + ".TScrollbar", background=[("active", BTN_HOVER)])
    s.layout("Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
        ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
    s.configure("Horizontal.TScale", background=BG, troughcolor=FIELD, bordercolor=BG,
                lightcolor=ACCENT, darkcolor=ACCENT)

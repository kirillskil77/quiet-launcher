"""Скруглённые виджеты и анимированный фон. Только tkinter (без Pillow), Python 3.8+.

Скругления рисуются на Canvas: прямоугольники плюс четыре угловых спрайта PNG с альфа-каналом
(сглаженные края). Спрайты создаются на лету и кэшируются, поэтому внешних картинок нет.
"""
import base64
import math
import random
import struct
import time
import tkinter as tk
import tkinter.font as tkfont
import zlib
from tkinter import ttk

from .theme import (BG, PANEL, FIELD, LINE, BTN, BTN_HOVER, FG, MUTED, ACCENT, ACCENT_HOVER, SELECT, FONT,
                    ACCENT_DISABLED, _rgb)

ANIMATIONS = True            # выключается в настройках: тогда всё меняется мгновенно, фон не движется
DISABLED_ACCENT = ACCENT_DISABLED


QUIET_UNTIL = 0.0


def quiet(sec):
    """Фон на это время замирает, чтобы не отнимать кадры у переходов и перетаскивания окна."""
    global QUIET_UNTIL
    QUIET_UNTIL = max(QUIET_UNTIL, time.perf_counter() + sec)


def set_animations(on):
    global ANIMATIONS
    ANIMATIONS = bool(on)


# ------------------------------------------------------------------ цвета и PNG

def hex_rgb(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def rgb_hex(t):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in t)


def mix(a, b, t):
    ra, rb = hex_rgb(a), hex_rgb(b)
    return rgb_hex([ra[i] + (rb[i] - ra[i]) * t for i in range(3)])


DISABLED_BTN = mix(BTN, BG, 0.45)


def scale_of(w):
    return getattr(w._root(), "scale", 1.0)


def bg_of(w):
    """Цвет фона родителя (у ttk-виджетов берём из стиля)."""
    try:
        return w.cget("bg")
    except Exception:
        pass
    try:
        name = w.cget("style") or w.winfo_class()
        c = ttk.Style(w).lookup(name, "background")
        if c:
            return c
    except Exception:
        pass
    return BG


def _png(w, h, rgba):
    stride = w * 4
    raw = b"".join(b"\x00" + bytes(rgba[y * stride:(y + 1) * stride]) for y in range(h))

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b""))


def _photo(master, w, h, rgba):
    return tk.PhotoImage(master=master, data=base64.b64encode(_png(w, h, rgba)).decode("ascii"))


def chevron(master, size, color):
    """Маленькая стрелка-треугольник «вправо» с плавными краями (шрифты на Windows 7 такого знака не гарантируют)."""
    r, g, b = hex_rgb(color)
    ss = 4
    px = bytearray(size * size * 4)
    x0, x1, y0, y1 = size * 0.30, size * 0.74, size * 0.18, size * 0.82
    for y in range(size):
        for x in range(size):
            hit = 0
            for sy in range(ss):
                for sx in range(ss):
                    fx, fy = x + (sx + 0.5) / ss, y + (sy + 0.5) / ss
                    if x0 <= fx <= x1:
                        half = (y1 - y0) / 2.0 * (1 - (fx - x0) / (x1 - x0))
                        if abs(fy - (y0 + y1) / 2.0) <= half:
                            hit += 1
            i = (y * size + x) * 4
            px[i], px[i + 1], px[i + 2], px[i + 3] = r, g, b, int(255 * hit / (ss * ss))
    return _photo(master, size, size, bytes(px))


# ------------------------------------------------------------------ скруглённый прямоугольник

_quadrants = {}
_corner_cache = {}


def _quadrant(r):
    q = _quadrants.get(r)
    if q is None:
        q, n = [], 4
        for py in range(r):
            row = []
            for px in range(r):
                c = 0
                for sy in range(n):
                    for sx in range(n):
                        x, y = px + (sx + .5) / n, py + (sy + .5) / n
                        if (x - r) ** 2 + (y - r) ** 2 <= r * r:
                            c += 1
                row.append(int(255 * c / float(n * n)))
            q.append(row)
        _quadrants[r] = q
    return q


def corner_images(master, r, color):
    """Четыре угла (лв, пв, лн, пн) со сглаженным краем."""
    key = (id(master), r, color)
    v = _corner_cache.get(key)
    if v is None:
        q = _quadrant(r)
        cr, cg, cb = hex_rgb(color)

        def build(flip_x, flip_y):
            buf = bytearray()
            for y in (range(r - 1, -1, -1) if flip_y else range(r)):
                row = q[y][::-1] if flip_x else q[y]
                for a in row:
                    buf += bytes((cr, cg, cb, a))
            return _photo(master, r, r, buf)

        v = (build(0, 0), build(1, 0), build(0, 1), build(1, 1))
        _corner_cache[key] = v
    return v


class RR(object):
    """Скруглённый прямоугольник из элементов Canvas."""

    def __init__(self, cv, x1, y1, x2, y2, r, color, tags=()):
        self.cv, self.r, self.color = cv, max(1, int(r)), color
        self.a = cv.create_rectangle(0, 0, 0, 0, fill=color, outline="", tags=tags)
        self.b = cv.create_rectangle(0, 0, 0, 0, fill=color, outline="", tags=tags)
        self.c = [cv.create_image(0, 0, image=im, anchor="nw", tags=tags)
                  for im in corner_images(cv._root(), self.r, color)]
        self.place(x1, y1, x2, y2)

    def place(self, x1, y1, x2, y2):
        cv, r = self.cv, self.r
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
        cv.coords(self.a, x1 + r, y1, x2 - r, y2)
        cv.coords(self.b, x1, y1 + r, x2, y2 - r)
        for item, (x, y) in zip(self.c, ((x1, y1), (x2 - r, y1), (x1, y2 - r), (x2 - r, y2 - r))):
            cv.coords(item, x, y)

    def recolor(self, color):
        if color == self.color:
            return
        self.color = color
        self.cv.itemconfigure(self.a, fill=color)
        self.cv.itemconfigure(self.b, fill=color)
        for item, im in zip(self.c, corner_images(self.cv._root(), self.r, color)):
            self.cv.itemconfigure(item, image=im)

    def items(self):
        return [self.a, self.b] + self.c

    def delete(self):
        for i in self.items():
            self.cv.delete(i)


class Card(object):
    """Панель со скруглёнными углами и тонкой рамкой."""

    def __init__(self, cv, r, fill=PANEL, border=LINE, tags=("card",)):
        self.outer = RR(cv, 0, 0, 2 * r, 2 * r, r, border, tags)
        self.inner = RR(cv, 0, 0, 2 * r, 2 * r, max(1, r - 1), fill, tags)

    def place(self, x1, y1, x2, y2):
        self.outer.place(x1, y1, x2, y2)
        self.inner.place(x1 + 1, y1 + 1, x2 - 1, y2 - 1)


# ------------------------------------------------------------------ кнопка

class ButtonArt(object):
    """Кнопка-таблетка, нарисованная на Canvas (на любом, в том числе на общем фоне).
    Плавно меняет цвет при наведении."""

    def __init__(self, cv, text, command=None, accent=False, x=0, y=0):
        self.cv, self.command, self.accent, self.text = cv, command, accent, text
        self.state, self.hv, self.target, self.pressed, self.over = "normal", 0.0, 0, False, False
        self.s = scale_of(cv)
        self.font = tkfont.Font(root=cv._root(), family=FONT, size=11 if accent else 10,
                                weight="bold" if accent else "normal")
        self.tag = "btn%d" % id(self)
        self.after_id = None
        self.x, self.y = int(x), int(y)
        self._size()
        self.rr = RR(cv, self.x, self.y, self.x + self.w, self.y + self.h, self.h // 2, self._color(), (self.tag,))
        self.txt = cv.create_text(self.x + self.w // 2, self.y + self.h // 2, text=text, font=self.font,
                                  fill=self._fg(), tags=(self.tag,))
        cv.tag_bind(self.tag, "<Enter>", self._enter)
        cv.tag_bind(self.tag, "<Leave>", self._leave)
        cv.tag_bind(self.tag, "<ButtonPress-1>", self._press)
        cv.tag_bind(self.tag, "<ButtonRelease-1>", self._release)

    def _size(self):
        s = self.s
        self.w = self.font.measure(self.text) + int((56 if self.accent else 32) * s)
        self.h = int((42 if self.accent else 32) * s)

    # --- цвета
    def _base(self):
        return ACCENT if self.accent else BTN

    def _hover(self):
        return ACCENT_HOVER if self.accent else BTN_HOVER

    def _color(self):
        if self.state == "disabled":
            return DISABLED_ACCENT if self.accent else DISABLED_BTN
        if self.pressed:
            return mix(self._hover(), "#000000", 0.22)
        return mix(self._base(), self._hover(), round(self.hv * 5) / 5.0)

    def _fg(self):
        if self.state == "disabled":
            return mix(ACCENT_DISABLED, FG, 0.35) if self.accent else mix(MUTED, BG, 0.45)
        return "#ffffff" if self.accent else FG

    def _paint(self):
        self.rr.recolor(self._color())
        self.cv.itemconfigure(self.txt, fill=self._fg())

    # --- анимация наведения
    def _tween(self):
        self.after_id = None
        d = self.target - self.hv
        if not ANIMATIONS or abs(d) < 0.08:
            self.hv = float(self.target)
            self._paint()
            return
        self.hv += d * 0.4
        self._paint()
        self.after_id = self.cv.after(16, self._tween)

    def _kick(self):
        if self.after_id is None:
            self._tween()

    def _cursor(self, c):
        try:
            self.cv.configure(cursor=c)
        except tk.TclError:
            pass

    def _enter(self, _=None):
        self.over = True
        if self.state == "disabled":
            return
        self.target = 1
        self._cursor("hand2")
        self._kick()

    def _leave(self, _=None):
        self.over, self.target, self.pressed = False, 0, False
        self._cursor("")
        self._kick()
        self._paint()

    def _press(self, _=None):
        if self.state == "disabled":
            return
        self.pressed = True
        self._paint()

    def _release(self, _=None):
        was = self.pressed
        self.pressed = False
        self._paint()
        if was and self.over and self.state != "disabled" and self.command:
            self.command()

    # --- API
    def move_to(self, x, y):
        x, y = int(x), int(y)
        self.cv.move(self.tag, x - self.x, y - self.y)
        self.x, self.y = x, y

    def configure(self, **kw):
        if "command" in kw:
            self.command = kw.pop("command")
        if "text" in kw:
            self.text = kw.pop("text")
            self.cv.itemconfigure(self.txt, text=self.text)
            self._size()
            self.rr.place(self.x, self.y, self.x + self.w, self.y + self.h)
            self.cv.coords(self.txt, self.x + self.w // 2, self.y + self.h // 2)
        if "state" in kw:
            self.state = "disabled" if str(kw.pop("state")) == "disabled" else "normal"
            if self.state == "disabled":
                self.target, self.hv, self.pressed = 0, 0.0, False
            elif self.over:
                self.target = 1
                self._kick()
            self._paint()

    config = configure

    def cget(self, key):
        return {"text": self.text, "state": self.state}.get(key)

    def invoke(self):
        if self.state != "disabled" and self.command:
            self.command()


class RoundButton(tk.Canvas):
    """Замена ttk.Button: те же text/command/state/pack, но скруглённая и с анимацией."""

    def __init__(self, parent, text="", command=None, style=None, accent=None, bg=None, **_ignored):
        if accent is None:
            accent = str(style or "").startswith("Accent")
        tk.Canvas.__init__(self, parent, bg=bg or bg_of(parent), highlightthickness=0, bd=0)
        self.art = ButtonArt(self, text, command, accent)
        tk.Canvas.configure(self, width=self.art.w, height=self.art.h)
        self.bind("<Return>", lambda e: self.art.invoke())
        self.bind("<space>", lambda e: self.art.invoke())

    def configure(self, cnf=None, **kw):
        own = dict((k, kw.pop(k)) for k in ("text", "state", "command") if k in kw)
        if own:
            self.art.configure(**own)
            if "text" in own:
                tk.Canvas.configure(self, width=self.art.w, height=self.art.h)
        if cnf or kw:
            return tk.Canvas.configure(self, cnf, **kw)

    config = configure

    def cget(self, key):
        if key in ("text", "state"):
            return self.art.cget(key)
        return tk.Canvas.cget(self, key)

    def invoke(self):
        self.art.invoke()


# ------------------------------------------------------------------ поля

class Well(tk.Canvas):
    """Скруглённая «лунка» для вставки обычного виджета (таблица, журнал)."""

    def __init__(self, parent, color=FIELD, bg=None, radius=10, pad=6):
        s = scale_of(parent)
        tk.Canvas.__init__(self, parent, bg=bg or bg_of(parent), highlightthickness=0, bd=0)
        self.pad, self.win = int(pad * s), None
        self.rr = RR(self, 0, 0, int(2 * radius * s), int(2 * radius * s), int(radius * s), color)
        tk.Canvas.bind(self, "<Configure>", self._cfg)

    def set_child(self, child):
        self.win = self.create_window(self.pad, self.pad, anchor="nw", window=child)
        child.update_idletasks()
        tk.Canvas.configure(self, width=child.winfo_reqwidth() + 2 * self.pad,
                            height=child.winfo_reqheight() + 2 * self.pad)

    def _cfg(self, e):
        self.rr.place(0, 0, e.width, e.height)
        if self.win is not None:
            self.itemconfigure(self.win, width=max(1, e.width - 2 * self.pad), height=max(1, e.height - 2 * self.pad))


class RoundEntry(tk.Canvas):
    """Замена ttk.Entry со скруглёнными краями и акцентной рамкой в фокусе."""

    def __init__(self, parent, textvariable=None, width=20, show="", bg=None, **kw):
        s = scale_of(parent)
        tk.Canvas.__init__(self, parent, bg=bg or bg_of(parent), highlightthickness=0, bd=0)
        self.s, self.pad = s, int(10 * s)
        self.entry = ttk.Entry(self, textvariable=textvariable, width=width, show=show, style="Flat.TEntry", **kw)
        font = tkfont.nametofont("TkTextFont")
        self.h = int(34 * s)
        self.w0 = width * font.measure("0") + 2 * self.pad
        tk.Canvas.configure(self, width=self.w0, height=self.h)
        r = int(10 * s)
        self.outer = RR(self, 0, 0, 2 * r, 2 * r, r, LINE)
        self.inner = RR(self, 0, 0, 2 * r, 2 * r, r - 1, FIELD)
        self.win = self.create_window(self.pad, self.h // 2, anchor="w", window=self.entry)
        self.entry.bind("<FocusIn>", lambda e: self.outer.recolor(ACCENT))
        self.entry.bind("<FocusOut>", lambda e: self.outer.recolor(LINE))
        tk.Canvas.bind(self, "<Configure>", self._cfg)
        tk.Canvas.bind(self, "<Button-1>", lambda e: self.entry.focus_set())

    def _cfg(self, e):
        self.outer.place(0, 0, e.width, e.height)
        self.inner.place(1, 1, e.width - 1, e.height - 1)
        self.itemconfigure(self.win, width=max(10, e.width - 2 * self.pad), height=e.height - 2)
        self.coords(self.win, self.pad, e.height // 2)

    # методы, которые вызывают снаружи как у обычного Entry
    def focus_set(self):
        self.entry.focus_set()

    focus = focus_set

    def bind(self, seq=None, func=None, add=None):
        return self.entry.bind(seq, func, add)

    def get(self):
        return self.entry.get()

    def insert(self, index, string):
        self.entry.insert(index, string)

    def delete(self, first, last=None):
        self.entry.delete(first, last)

    def select_range(self, a, b):
        self.entry.select_range(a, b)

    def icursor(self, i):
        self.entry.icursor(i)

    def configure(self, cnf=None, **kw):
        own = dict((k, kw.pop(k)) for k in ("state", "show", "textvariable") if k in kw)
        if own:
            self.entry.configure(**own)
        if cnf or kw:
            return tk.Canvas.configure(self, cnf, **kw)

    config = configure


class RoundCombo(Well):
    """Замена ttk.Combobox в скруглённой рамке (список при раскрытии рисует система)."""

    def __init__(self, parent, textvariable=None, values=(), state="normal", width=20, bg=None):
        Well.__init__(self, parent, color=FIELD, bg=bg, radius=10, pad=3)
        self.combo = ttk.Combobox(self, textvariable=textvariable, values=list(values), state=state,
                                  width=width, style="Flat.TCombobox")
        self.set_child(self.combo)

    def configure(self, cnf=None, **kw):
        own = dict((k, kw.pop(k)) for k in ("values", "state", "textvariable") if k in kw)
        if own:
            self.combo.configure(**own)
        if cnf or kw:
            return tk.Canvas.configure(self, cnf, **kw)

    config = configure

    def current(self, i=None):
        return self.combo.current() if i is None else self.combo.current(i)

    def bind(self, seq=None, func=None, add=None):
        return self.combo.bind(seq, func, add)

    def get(self):
        return self.combo.get()

    def set(self, v):
        self.combo.set(v)

    def focus_set(self):
        self.combo.focus_set()


class Switch(tk.Frame):
    """Замена ttk.Checkbutton: переключатель с плавно ездящим кружком и подписью."""

    def __init__(self, parent, text="", variable=None, command=None, bg=None, wraplength=460, **_ignored):
        bg = bg or bg_of(parent)
        tk.Frame.__init__(self, parent, bg=bg)
        s = scale_of(parent)
        self.var = variable if variable is not None else tk.BooleanVar(value=False)
        self.command, self.t, self.goal, self.job = command, 0.0, 0.0, None
        self.w, self.h = int(40 * s), int(22 * s)
        self.d = self.h - int(6 * s)
        self.cv = tk.Canvas(self, width=self.w, height=self.h, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.cv.pack(side="left", padx=(0, 10))
        self.track = RR(self.cv, 0, 0, self.w, self.h, self.h // 2, self._track())
        m = (self.h - self.d) // 2
        self.knob = RR(self.cv, m, m, m + self.d, m + self.d, self.d // 2, "#f1f4f2")
        self.label = tk.Label(self, text=text, bg=bg, fg=FG, anchor="w", justify="left", cursor="hand2",
                              wraplength=int(wraplength * s), font=tkfont.nametofont("TkDefaultFont"))
        self.label.pack(side="left", fill="x", expand=True)
        for w in (self.cv, self.label):
            w.bind("<ButtonRelease-1>", lambda e: self.toggle())
        self.t = self.goal = 1.0 if self.var.get() else 0.0
        self._paint()
        self.var.trace_add("write", lambda *a: self._sync())

    def _track(self):
        return mix(mix(BTN_HOVER, FG, 0.12), ACCENT, round(self.t * 5) / 5.0)

    def _paint(self):
        self.track.recolor(self._track())
        m = (self.h - self.d) // 2
        x = m + (self.w - self.d - 2 * m) * self.t
        self.knob.place(x, m, x + self.d, m + self.d)

    def _sync(self):
        self.goal = 1.0 if self.var.get() else 0.0
        if self.job is not None:
            self.after_cancel(self.job)
            self.job = None
        self._step()

    def _step(self):
        self.job = None
        if not ANIMATIONS:
            self.t = self.goal
            self._paint()
            return
        quiet(0.4)
        start, t0 = self.t, time.perf_counter()
        goal = self.goal

        def frame():
            if goal != self.goal:          # переключили снова — едем в новую сторону
                return self._step()
            k = min(1.0, (time.perf_counter() - t0) / 0.15)
            self.t = start + (goal - start) * (1 - (1 - k) ** 3)
            self._paint()
            self.job = self.after(10, frame) if k < 1.0 else None

        frame()

    def toggle(self):
        self.var.set(not self.var.get())
        if self.command:
            self.command()


class RoundSlider(tk.Canvas):
    """Замена ttk.Scale: тонкая скруглённая дорожка и круглый бегунок."""

    def __init__(self, parent, from_=0, to=100, variable=None, command=None, bg=None, **_ignored):
        s = scale_of(parent)
        tk.Canvas.__init__(self, parent, bg=bg or bg_of(parent), highlightthickness=0, bd=0,
                           height=int(24 * s), cursor="hand2")
        self.lo, self.hi, self.command = float(from_), float(to), command
        self.var = variable if variable is not None else tk.DoubleVar(value=from_)
        self.pad, self.th, self.d = int(10 * s), max(4, int(6 * s)), int(18 * s)
        self.W = 100
        self.track = RR(self, 0, 0, 20, self.th, self.th // 2, FIELD)
        self.fill = RR(self, 0, 0, 20, self.th, self.th // 2, ACCENT)
        self.knob = RR(self, 0, 0, self.d, self.d, self.d // 2, "#f1f4f2")
        self.bind("<Configure>", self._cfg)
        self.bind("<Button-1>", self._drag)
        self.bind("<B1-Motion>", self._drag)
        self.var.trace_add("write", lambda *a: self._paint())

    def _cfg(self, e):
        self.W = e.width
        self._paint()

    def _paint(self):
        h = int(self["height"])
        y = (h - self.th) // 2
        span = max(1, self.W - 2 * self.pad)
        frac = (float(self.var.get()) - self.lo) / max(1e-9, self.hi - self.lo)
        x = self.pad + span * max(0.0, min(1.0, frac))
        self.track.place(self.pad, y, self.W - self.pad, y + self.th)
        self.fill.place(self.pad, y, max(x, self.pad + self.th), y + self.th)
        ky = (h - self.d) // 2
        self.knob.place(x - self.d / 2, ky, x + self.d / 2, ky + self.d)

    def _drag(self, e):
        span = max(1, self.W - 2 * self.pad)
        frac = max(0.0, min(1.0, (e.x - self.pad) / float(span)))
        v = self.lo + frac * (self.hi - self.lo)
        try:
            self.var.set(int(round(v)) if isinstance(self.var, tk.IntVar) else v)
        except tk.TclError:
            return
        if self.command:
            self.command(v)


# ------------------------------------------------------------------ полоса прогресса

class RoundProgress(tk.Canvas):
    """Тонкая скруглённая полоса. Совместима с ttk.Progressbar: mode/maximum/value/start/stop."""

    def __init__(self, parent, length=240, mode="determinate", bg=None, **_ignored):
        s = scale_of(parent)
        tk.Canvas.__init__(self, parent, bg=bg or bg_of(parent), highlightthickness=0, bd=0)
        self.h, self.length = max(6, int(8 * s)), int(length)
        tk.Canvas.configure(self, width=self.length, height=self.h)
        self.mode, self.maximum, self.value = mode, 100.0, 0.0
        self.shown, self.job, self.pos = 0.0, None, 0.0
        self.trough = RR(self, 0, 0, self.length, self.h, self.h // 2, FIELD)
        self.fill = None
        self.bind("<Configure>", self._cfg)

    def _cfg(self, e):
        self.length = e.width
        self.trough.place(0, 0, e.width, self.h)
        self._draw(self.shown)

    def _draw(self, frac, offset=None):
        if self.fill is not None:
            self.fill.delete()
            self.fill = None
        w = self.length
        if offset is None:          # определённый прогресс
            if frac <= 0:
                return
            x1, x2 = 0, max(self.h, int(w * min(1.0, frac)))
        else:                        # бегущая «таблетка»
            seg = max(self.h, int(w * 0.3))
            x1 = int(offset * (w + seg)) - seg
            x1, x2 = max(0, x1), min(w, x1 + seg)
            if x2 - x1 < 2:
                return
        self.fill = RR(self, x1, 0, x2, self.h, min(self.h // 2, (x2 - x1) // 2), ACCENT)

    def configure(self, cnf=None, **kw):
        if "mode" in kw:
            self.mode = kw.pop("mode")
        if "maximum" in kw:
            self.maximum = float(kw.pop("maximum")) or 1.0
        if "value" in kw:
            self.value = float(kw.pop("value"))
            self._ensure_job()
        if cnf or kw:
            return tk.Canvas.configure(self, cnf, **kw)

    config = configure

    def _ensure_job(self):
        if self.job is None and self.mode == "determinate":
            self._tick()

    def _tick(self):
        self.job = None
        target = self.value / self.maximum if self.maximum else 0
        d = target - self.shown
        if not ANIMATIONS or abs(d) < 0.004:
            self.shown = target
            self._draw(self.shown)
            return
        self.shown += d * 0.25
        self._draw(self.shown)
        self.job = self.after(20, self._tick)

    def start(self, interval=14):
        self.stop()
        self.mode, self.pos = "indeterminate", 0.0
        self._run()

    def _run(self):
        self.pos = (self.pos + 0.018) % 1.0
        self._draw(0, self.pos)
        self.job = self.after(25, self._run)

    def stop(self):
        if self.job is not None:
            self.after_cancel(self.job)
            self.job = None
        self.mode, self.shown, self.value = "determinate", 0.0, 0.0
        self._draw(0)


# ------------------------------------------------------------------ вкладки-таблетки

class PillTabs(ttk.Frame):
    """Замена ttk.Notebook: заголовки-таблетки, активная плавно «переезжает»."""

    def __init__(self, parent):
        ttk.Frame.__init__(self, parent, style="Panel.TFrame")
        s = scale_of(self)
        self.s = s
        self.hdr = tk.Canvas(self, bg=PANEL, highlightthickness=0, bd=0, height=int(42 * s))
        self.hdr.grid(row=0, column=0, sticky="ew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.font = tkfont.Font(root=self._root(), family=FONT, size=10)
        self.items, self.sel, self.job, self.cur = [], -1, None, None
        self.on_select = None
        self.ind = RR(self.hdr, 0, 0, 20, 20, 10, SELECT, ("ind",))
        self.hdr.tag_lower("ind")

    def add(self, child, text):
        i = len(self.items)
        s = self.s
        tag = "tab%d" % i
        x = (self.items[-1]["x"] + self.items[-1]["w"] + int(6 * s)) if self.items else int(8 * s)
        w = self.font.measure(text) + int(36 * s)
        h = int(32 * s)
        y = int(5 * s)
        t = self.hdr.create_text(x + w // 2, y + h // 2, text=text, font=self.font, fill=MUTED, tags=(tag,))
        hit = self.hdr.create_rectangle(x, y, x + w, y + h, outline="", fill="", tags=(tag,))
        self.items.append({"child": child, "x": x, "y": y, "w": w, "h": h, "text": t})
        self.hdr.tag_bind(tag, "<ButtonRelease-1>", lambda e, i=i: self.select(i))
        self.hdr.tag_bind(tag, "<Enter>", lambda e, i=i: self._hover(i, True))
        self.hdr.tag_bind(tag, "<Leave>", lambda e, i=i: self._hover(i, False))
        child.grid(row=1, column=0, sticky="nsew")
        if self.sel < 0:
            self.select(0, animate=False)
        else:
            child.grid_remove()

    def _hover(self, i, on):
        self.hdr.configure(cursor="hand2" if on else "")
        if i != self.sel:
            self.hdr.itemconfigure(self.items[i]["text"], fill=FG if on else MUTED)

    def select(self, i, animate=True):
        if not (0 <= i < len(self.items)) or i == self.sel:
            return
        if animate and ANIMATIONS:
            quiet(0.5)
        for j, it in enumerate(self.items):
            if j == i:
                it["child"].grid()
            else:
                it["child"].grid_remove()
            self.hdr.itemconfigure(it["text"], fill=ACCENT_HOVER if j == i else MUTED)
        self.sel = i
        it = self.items[i]
        goal = (it["x"], it["y"], it["w"], it["h"])
        if self.job is not None:
            self.after_cancel(self.job)
            self.job = None
        if self.on_select and animate:
            self.after(30, lambda i=i: self.on_select(i))
        if not animate or not ANIMATIONS or self.cur is None:
            self._put(goal)
            return
        try:
            self.update_idletasks()        # тяжёлая перекладка содержимого — до начала анимации
        except tk.TclError:
            pass
        start, t0 = self.cur, time.perf_counter()

        def step():
            k = min(1.0, (time.perf_counter() - t0) / 0.14)
            e = 1 - (1 - k) ** 3
            self._put(tuple(a + (b - a) * e for a, b in zip(start, goal)))
            self.job = self.after(10, step) if k < 1.0 else None

        step()

    def _put(self, g):
        self.cur = g
        x, y, w, h = g
        self.ind.place(x, y, x + w, y + h)


# ------------------------------------------------------------------ фон «лава-лампа»

def _blob(master, radius, rgb, amax):
    """Мягкое пятно: цвет постоянный, прозрачность плавно спадает к краю."""
    r = int(radius)
    n = 2 * r + 1
    r2 = r * r
    tbl = [int(255 * amax * (1 - d2 / float(r2)) ** 3) for d2 in range(r2 + 1)]
    cr, cg, cb = rgb
    rows = []
    for dy in range(0, r + 1):
        half = [tbl[dx * dx + dy * dy] if dx * dx + dy * dy <= r2 else 0 for dx in range(r + 1)]
        alphas = bytes(half[:0:-1] + half)
        row = bytearray(n * 4)
        row[0::4] = bytes((cr,)) * n
        row[1::4] = bytes((cg,)) * n
        row[2::4] = bytes((cb,)) * n
        row[3::4] = alphas
        rows.append(bytes(row))
    full = rows[:0:-1] + rows
    return _photo(master, n, n, b"".join(full))


class LavaBackground(object):
    """Медленно плывущие зелёные пятна. Экономит ресурсы: стоит, пока игра запущена, окно свёрнуто
    или анимации выключены; на слабом компьютере сама снижает частоту кадров."""

    SPEC = ((270, _rgb(ACCENT), 0.62), (215, _rgb(mix(ACCENT, "#000000", 0.12)), 0.58), (170, _rgb(mix(ACCENT, "#ffffff", 0.25)), 0.46))

    def __init__(self, cv, app):
        self.cv, self.app = cv, app
        self.W = self.H = 0
        self.blobs, self.images = [], []
        self.enabled = False
        self.interval, self.last, self.slow = 66, None, []
        self.t0 = time.perf_counter()
        self.job = None

    def set_enabled(self, on):
        on = bool(on)
        if on == self.enabled:
            return
        self.enabled = on
        if on:
            if not self.blobs:
                self._build()
            self.cv.itemconfigure("lava", state="normal")
            self.last, self.slow, self.interval = None, [], 66
            self._place(time.perf_counter() - self.t0)
            if self.job is None:
                self.job = self.cv.after(self.interval, self._tick)
        else:
            self.cv.itemconfigure("lava", state="hidden")

    def resize(self, w, h):
        self.W, self.H = w, h
        if self.enabled:
            self._place(time.perf_counter() - self.t0)

    def _build(self):
        s = scale_of(self.cv)
        master = self.cv._root()
        self.images = [_blob(master, rad * s, rgb, a) for rad, rgb, a in self.SPEC]
        rnd = random.Random(11)
        for i in range(7):
            img = self.images[i % len(self.images)]
            item = self.cv.create_image(0, 0, image=img, tags=("lava",))
            self.blobs.append({
                "item": item,
                "px": rnd.uniform(0, 6.28), "py": rnd.uniform(0, 6.28),
                "tx": rnd.uniform(42, 78), "ty": rnd.uniform(36, 70),
                "ax": rnd.uniform(0.30, 0.50), "ay": rnd.uniform(0.28, 0.48)})
        self.cv.tag_lower("lava")

    def _place(self, t):
        if not self.blobs or self.W < 10:
            return
        for b in self.blobs:
            x = self.W * (0.5 + b["ax"] * math.sin(6.283 * t / b["tx"] + b["px"]))
            y = self.H * (0.5 + b["ay"] * math.sin(6.283 * t / b["ty"] + b["py"]))
            self.cv.coords(b["item"], x, y)

    def _active(self):
        try:
            return (ANIMATIONS and self.enabled and self.app.proc is None
                    and time.perf_counter() > QUIET_UNTIL and self.app.state() != "iconic")
        except tk.TclError:
            return False

    def _tick(self):
        self.job = None
        if not self.enabled:
            return
        if not self._active():
            self.last = None
            self.job = self.cv.after(150, self._tick)
            return
        now = time.perf_counter()
        if self.last is not None:                      # следим за нагрузкой
            self.slow.append(now - self.last)
            if len(self.slow) >= 24:
                avg = sum(self.slow) / len(self.slow)
                self.slow = []
                if avg > 0.45:                          # совсем слабый компьютер — выключаем
                    self.app.log("Анимированный фон отключён: компьютер не успевает его рисовать.")
                    self.set_enabled(False)
                    return
                self.interval = 130 if avg > 0.17 else 66
        self.last = now
        self._place(now - self.t0)
        self.job = self.cv.after(self.interval, self._tick)

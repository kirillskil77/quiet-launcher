"""Страница проекта из каталога Modrinth: описание и скриншоты. Открывается стрелкой ▸ у названия."""
import re
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk

from . import mods
from .dialogs import Dialog
from .theme import FIELD, FG, MUTED, FONT as FONT_NAME
from .widgets import RoundButton as Button, Well

try:                                     # Pillow нужна, чтобы показывать jpg/webp и ужимать большие картинки
    from PIL import Image, ImageTk
    _LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
except Exception:                        # без неё покажем только png/gif
    Image = ImageTk = None
    _LANCZOS = None


def plain_text(md, limit=6000):
    """Markdown/HTML из описания проекта в простой читаемый текст."""
    s = (md or "").replace("\r", "")
    s = re.sub(r"```.*?```", "", s, flags=re.S)
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)
    s = re.sub(r"<img[^>]*>", "", s, flags=re.I)
    s = re.sub(r"<br\s*/?>|</p>|</h\d>|</li>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"^\s{0,3}#{1,6}\s*", "", s, flags=re.M)
    s = re.sub(r"^\s*[-*+]\s+", "• ", s, flags=re.M)
    s = re.sub(r"(\*\*|__|`|~~)", "", s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s if len(s) <= limit else s[:limit].rsplit(" ", 1)[0] + "…"


def load_image(path, max_w, max_h):
    """Читает и ужимает картинку (можно в потоке). Возвращает объект для make_photo или None."""
    if Image is not None:
        try:
            im = Image.open(path)
            im.draft("RGB", (max_w * 2, max_h * 2))          # jpeg раскодируется сразу в уменьшенном виде
            im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
            im.thumbnail((max_w, max_h), _LANCZOS)
            return im
        except Exception:
            return None
    return path


def make_photo(master, obj, max_w, max_h):
    """Создаёт PhotoImage — только в потоке интерфейса."""
    if obj is None:
        return None
    try:
        if Image is not None:
            return ImageTk.PhotoImage(obj, master=master)
        img = tk.PhotoImage(master=master, file=obj)              # встроенный Tk умеет png/gif
        k = max(1, -(-img.width() // max_w), -(-img.height() // max_h))
        return img.subsample(k, k) if k > 1 else img
    except Exception:
        return None


class ProjectDialog(Dialog):
    W, H = 560, 300

    def __init__(self, app, hit, kind, install):
        self.hit, self.kind, self.install = hit, kind, install
        self.info, self.shots, self.idx = None, [], 0
        self.photos, self.loading = {}, set()
        self.alive = True
        self.icon_img = None
        Dialog.__init__(self, app, hit.get("title") or "Проект")

    # ---- интерфейс
    def build(self, body):
        s = getattr(self.app, "scale", 1.0)
        self.W, self.H = int(560 * s), int(300 * s)
        h = self.hit
        head = ttk.Frame(body)
        head.pack(fill="x")
        self.icon = tk.Label(head, bd=0, bg=self.app.cget("bg"))
        col = ttk.Frame(head)
        col.pack(side="left", fill="x", expand=True)
        ttk.Label(col, text=h.get("title", ""), style="Title.TLabel", wraplength=self.W - 80).pack(anchor="w")
        n = "{:,}".format(h.get("downloads", 0)).replace(",", " ")
        ttk.Label(col, text="%s · скачиваний: %s" % (h.get("author", ""), n), style="Muted.TLabel").pack(anchor="w")
        self.desc = ttk.Label(col, text=h.get("description", ""), wraplength=self.W - 80, justify="left")
        self.desc.pack(anchor="w", pady=(4, 0))

        well = Well(body, color=FIELD, bg=self.app.cget("bg"), radius=12, pad=4)
        well.pack(fill="x", pady=(12, 6))
        self.shot = tk.Label(well, bg=FIELD, fg=MUTED, text="Загружаю…", width=1, height=1, bd=0)
        self.shot.configure(width=self.W // 8, height=self.H // 16)
        well.set_child(self.shot)
        well.configure(width=self.W + 12, height=self.H + 12)
        nav = ttk.Frame(body)
        nav.pack(fill="x")
        self.prev_b = Button(nav, text="‹", command=lambda: self.step(-1))
        self.prev_b.pack(side="left")
        self.next_b = Button(nav, text="›", command=lambda: self.step(1))
        self.next_b.pack(side="left", padx=(6, 10))
        self.counter = ttk.Label(nav, text="", style="Muted.TLabel", wraplength=self.W - 140)
        self.counter.pack(side="left")

        tw = Well(body, color=FIELD, bg=self.app.cget("bg"), radius=12, pad=4)
        tw.pack(fill="both", expand=True, pady=(10, 0))
        inner = ttk.Frame(tw, style="Field.TFrame")
        self.text = tk.Text(inner, height=8, width=70, wrap="word", bg=FIELD, fg=FG, bd=0, highlightthickness=0,
                            padx=8, pady=6, font=(FONT_NAME, 10), insertwidth=0, cursor="arrow")
        sb = ttk.Scrollbar(inner, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.text.insert("1.0", "Загружаю описание…")
        self.text.configure(state="disabled")
        tw.set_child(inner)

        row = ttk.Frame(body)
        row.pack(fill="x", pady=(14, 0))
        Button(row, text="Закрыть", command=self.close).pack(side="right")
        Button(row, text="Установить", style="Accent.TButton", command=self.do_install).pack(side="right", padx=(0, 8))
        Button(row, text="На сайте", command=self.open_site).pack(side="left")
        self.bind("<Left>", lambda e: self.step(-1))
        self.bind("<Right>", lambda e: self.step(1))
        self.bind("<Return>", lambda e: self.do_install())
        self._nav()
        threading.Thread(target=self._load_info, daemon=True).start()
        pid_icon = h.get("icon_url")
        if pid_icon:
            threading.Thread(target=self._load_icon, args=(pid_icon,), daemon=True).start()

    # ---- загрузка (в потоках; в интерфейс возвращаемся через app.post)
    def _ui(self, fn):
        def call():
            if self.alive:
                try:
                    fn()
                except tk.TclError:
                    pass
        self.app.post(call)

    def _load_info(self):
        try:
            info = mods.project_info(self.hit["project_id"])
        except Exception as e:
            self._ui(lambda: self._set_text("Не удалось загрузить страницу: %s" % e))
            self._ui(lambda: self.shot.configure(text="Нет связи с Modrinth"))
            return
        self._ui(lambda: self._fill(info))

    def _fill(self, info):
        self.info = info
        gallery = sorted(info.get("gallery") or [], key=lambda g: (not g.get("featured"), g.get("ordering", 0)))
        self.shots = gallery[:12]
        self._set_text(plain_text(info.get("body")) or info.get("description", ""))
        self.idx = 0
        self._nav()
        if self.shots:
            self.show(0)
        else:
            self.shot.configure(text="Скриншотов нет")

    def _set_text(self, s):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", s)
        self.text.configure(state="disabled")

    def _load_icon(self, url):
        try:
            im = load_image(mods.fetch_image(url, self.app.store.cache), 64, 64)
        except Exception:
            return
        self._ui(lambda: self._set_icon(im))

    def _set_icon(self, im):
        ph = make_photo(self, im, 64, 64)
        if ph is not None:
            self.icon_img = ph
            self.icon.configure(image=ph)
            self.icon.pack(side="left", padx=(0, 12), before=self.icon.master.winfo_children()[0])

    def show(self, i):
        if not self.shots:
            return
        if i in self.photos:
            self.shot.configure(image=self.photos[i], text="")
            self.shot.image = self.photos[i]
        else:
            self.shot.configure(image="", text="Загружаю…")
            self._fetch(i)
        self._nav()
        nxt = (i + 1) % len(self.shots)
        if nxt not in self.photos:
            self._fetch(nxt, quiet=True)             # следующий кадр грузим заранее

    def _fetch(self, i, quiet=False):
        if i in self.loading:
            return
        self.loading.add(i)
        g = self.shots[i]
        url = g.get("url") or g.get("raw_url")

        def work():
            try:
                im = load_image(mods.fetch_image(url, self.app.store.cache), self.W, self.H)
            except Exception:
                im = None
            self._ui(lambda: self._shot_ready(i, im, quiet))
        threading.Thread(target=work, daemon=True).start()

    def _shot_ready(self, i, im, quiet):
        self.loading.discard(i)
        ph = make_photo(self, im, self.W, self.H)
        if ph is None:
            if i == self.idx and not quiet:
                self.shot.configure(image="", text="Этот скриншот не получилось показать — он есть на сайте проекта")
            return
        self.photos[i] = ph
        if i == self.idx:
            self.show(i)

    def step(self, d):
        if len(self.shots) > 1:
            self.idx = (self.idx + d) % len(self.shots)
            self.show(self.idx)

    def _nav(self):
        n = len(self.shots)
        state = "normal" if n > 1 else "disabled"
        self.prev_b.configure(state=state)
        self.next_b.configure(state=state)
        if n:
            title = (self.shots[self.idx].get("title") or "").strip()
            self.counter.configure(text="%d / %d%s" % (self.idx + 1, n, "  ·  " + title if title else ""))
        else:
            self.counter.configure(text="")

    # ---- действия
    def do_install(self):
        self.close()
        self.install(self.hit, self.kind)

    def open_site(self):
        slug = self.hit.get("slug") or self.hit.get("project_id")
        webbrowser.open("https://modrinth.com/%s/%s" % (self.kind, slug))

    def close(self):
        self.alive = False
        self.photos.clear()
        Dialog.close(self)

"""Главное окно."""
import logging
import os
import queue
import subprocess
import threading
import time
import tkinter as tk
import traceback
from tkinter import ttk, messagebox, filedialog

from . import APP_NAME, APP_VERSION, auth, backup, game, icons, instances, mods, skins, updater
from .browse import ProjectDialog
from .friends_ui import FriendsTab
from .dialogs import AccountsDialog, NewInstanceDialog, SettingsDialog, UpdateDialog, UpdatedDialog, WelcomeDialog, pick_java
from . import widgets
from .theme import apply_theme, ACCENT_HOVER, BG, PANEL, FIELD, FG, MUTED, MONO, FONT as FONT_NAME
from .widgets import (ButtonArt, Card, LavaBackground, PillTabs, RoundButton as Button, RoundEntry as Entry,
                      RoundCombo, RoundProgress, Well, bg_of)
from .util import Cancelled, os_name, resource_path, total_ram_mb


def open_folder(path):
    os.makedirs(path, exist_ok=True)
    if os_name() == "windows":
        os.startfile(path)  # noqa
    else:
        subprocess.Popen(["xdg-open" if os_name() == "linux" else "open", path])


def _tree(parent, columns, height):
    """Таблица с прокруткой в скруглённой рамке. columns: [(id, заголовок, ширина)] — первый столбец идёт в #0."""
    well = Well(parent, bg=bg_of(parent))
    inner = ttk.Frame(well, style="Field.TFrame")
    ids = [c[0] for c in columns[1:]]
    tree = ttk.Treeview(inner, columns=ids, height=height, selectmode="browse")
    for i, (cid, title, width) in enumerate(columns):
        key = "#0" if i == 0 else cid
        tree.heading(key, text=title, anchor="w")
        tree.column(key, width=width, anchor="w", stretch=(i == 0))
    sb = ttk.Scrollbar(inner, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    well.set_child(inner)
    return well, tree


class _CText(object):
    """Текст на общем фоне с интерфейсом как у Label.configure(text=...)."""

    def __init__(self, cv, item):
        self.cv, self.item = cv, item

    def configure(self, **kw):
        if "text" in kw:
            self.cv.itemconfigure(self.item, text=kw["text"])


LAYOUTS = {
    "classic": dict(title="Классика", note="список сборок слева", m=16, g=12, bar=54, left=250, hero=92, sub=44, font=22, mirror=False),
    "right": dict(title="Зеркальная", note="список сборок справа", m=16, g=12, bar=54, left=250, hero=92, sub=44, font=22, mirror=True),
    "compact": dict(title="Компактная", note="уже список, меньше отступов", m=10, g=8, bar=50, left=228, hero=74, sub=36, font=18, mirror=False),
}


class App(tk.Tk):
    def _set_icon(self):
        """Иконка окна и панели задач; на всех дочерних окнах тоже (default=...)."""
        try:
            if os_name() == "windows":
                self.iconbitmap(default=resource_path(os.path.join("assets", "icon.ico")))
            else:
                self.iconphoto(True, tk.PhotoImage(file=resource_path(os.path.join("assets", "icon.png"))))
        except Exception:
            pass  # без иконки лаунчер работает так же

    def _load_logo(self):
        """Маленький логотип в верхней панели: берём файл ближайшего подходящего размера."""
        want = 28 * self.scale
        size = next((n for n in (28, 42, 56) if n >= want - 1), 56)
        try:
            return tk.PhotoImage(master=self, file=resource_path(os.path.join("assets", "logo_%d.png" % size)))
        except Exception:
            return None

    def __init__(self, store):
        tk.Tk.__init__(self)
        self.store = store
        self.scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
        self.title(APP_NAME)
        self._set_icon()
        self.geometry("%dx%d" % (int(1060 * self.scale), int(680 * self.scale)))
        self.minsize(int(920 * self.scale), int(600 * self.scale))
        widgets.set_animations(store.settings.get("animations", True) and not os.environ.get("QL_NO_ANIM"))
        apply_theme(self, self.scale)
        self.q = queue.Queue()
        self.busy = False
        self.cancel = None
        self.proc = None
        self.insts = []
        self.current = None
        self.hits = []
        self.acc_ids = []
        self._pb_mode = None
        self._build()
        self.refresh_accounts()
        self.reload_instances(store.settings.get("last_instance"))
        self.after(80, self._pump)
        self.after(40, lambda: self.lava.set_enabled(widgets.ANIMATIONS))   # пятна рисуем после показа окна
        self.after(700, self._welcome)
        self.after(2500, self.check_updates)
        self.log("%s запущен. Папка данных: %s" % (APP_NAME, store.home))

    # ------------------------------------------------------------ построение окна

    def _build(self):
        sc = self.scale
        cv = self.bg = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0)
        cv.pack(fill="both", expand=True)
        self.lava = LavaBackground(cv, self)
        r = int(18 * sc)
        self.card_top, self.card_left = Card(cv, int(20 * sc)), Card(cv, r)
        self.card_tabs, self.card_bottom = Card(cv, r), Card(cv, r)

        # --- верхняя панель
        top = ttk.Frame(cv, style="Panel.TFrame")
        self.logo = self._load_logo()
        if self.logo is not None:
            tk.Label(top, image=self.logo, bg=PANEL, bd=0).pack(side="left", padx=(8, 10))
        ttk.Label(top, text=APP_NAME, style="PanelTitle.TLabel").pack(side="left")
        Button(top, text="Настройки", command=self.open_settings).pack(side="right", padx=(8, 6))
        self.upd_info = None
        self.upd_btn = Button(top, text="Обновить", style="Accent.TButton", command=self.show_update)
        Button(top, text="Журнал", command=self.open_log).pack(side="right", padx=(8, 0))
        Button(top, text="Аккаунты", command=self.open_accounts).pack(side="right")
        self.acc_var = tk.StringVar()
        self.acc_box = RoundCombo(top, textvariable=self.acc_var, state="readonly", width=26)
        self.acc_box.pack(side="right", padx=(0, 10))
        self.acc_box.bind("<<ComboboxSelected>>", self.on_account_pick)
        self.head_lbl = tk.Label(top, bg=PANEL, bd=0)
        self.head_lbl.pack(side="right", padx=(0, 8))
        self.w_top = cv.create_window(0, 0, window=top, anchor="nw")

        # --- список сборок
        left = ttk.Frame(cv, style="Panel.TFrame")
        ttk.Label(left, text="СБОРКИ", style="PanelMuted.TLabel").pack(anchor="w", padx=14, pady=(12, 4))
        self.itree = ttk.Treeview(left, show="tree", selectmode="browse", style="List.Treeview")
        self.itree.pack(fill="both", expand=True, padx=6)
        self.itree.bind("<<TreeviewSelect>>", self.on_select)
        lb = ttk.Frame(left, style="Panel.TFrame")
        lb.pack(fill="x", padx=10, pady=(8, 8))
        Button(lb, text="Создать", command=self.new_instance).pack(side="left")
        Button(lb, text="Импорт .mrpack", command=self.import_pack).pack(side="left", padx=(8, 0))
        self.w_left = cv.create_window(0, 0, window=left, anchor="nw")

        # --- заголовок сборки прямо на фоне, кнопки справа
        self.t_name = cv.create_text(0, 0, anchor="nw", text="", font=(FONT_NAME, 22, "bold"), fill="#f4f7f5")
        self.t_sub = cv.create_text(0, 0, anchor="nw", text="", font=(FONT_NAME, 10), fill="#b4bdb7")
        self.h_name, self.h_sub = _CText(cv, self.t_name), _CText(cv, self.t_sub)
        self.play_btn = ButtonArt(cv, "Играть", self.play, accent=True)
        self.stop_btn = ButtonArt(cv, "Остановить", self.stop_game)

        # --- вкладки
        self.nb = PillTabs(cv)
        self.w_tabs = cv.create_window(0, 0, window=self.nb, anchor="nw")
        self._build_log_tab()
        self._build_mods_tab()
        self._build_installed_tab()
        self._build_instance_tab()
        self.friends_tab = FriendsTab(self, _tree)
        self.friends_index = 4
        self.nb.add(self.friends_tab.frame, text="Друзья")

        # --- строка состояния
        bottom = ttk.Frame(cv, style="Panel.TFrame")
        self.status = tk.StringVar(value="Готово")
        ttk.Label(bottom, textvariable=self.status, style="PanelNote.TLabel").pack(side="left", padx=(14, 0))
        self.cancel_btn = Button(bottom, text="Отмена", command=self.cancel_task)
        self.pb = RoundProgress(bottom, length=int(240 * sc), mode="determinate")
        self.w_bottom = cv.create_window(0, 0, window=bottom, anchor="nw")

        cv.bind("<Configure>", self._layout)
        self.bind("<Configure>", self._on_move, add="+")

    def _on_move(self, e):
        if e.widget is self:        # окно двигают или тянут — фон замирает, пока не отпустят
            widgets.quiet(0.35)

    # ------------------------------------------------------------ приветствие и обновления

    def _welcome(self):
        s = self.store.settings
        if s.get("welcome_seen") == APP_VERSION:
            return
        old = s.get("welcome_seen") or ""
        s["welcome_seen"] = APP_VERSION
        self.store.save_settings()
        if old:                                        # обновились: счётчик версии и список нового
            self.wait_window(UpdatedDialog(self, old))
        else:                                          # первый запуск: знакомство
            self.wait_window(WelcomeDialog(self))

    def check_updates(self):
        s = self.store.settings
        if not updater.due(s):
            return

        def work():
            try:
                info = updater.check(s)
            except Exception as e:
                logging.warning("Проверка обновлений не удалась: %s", e)
                return
            self.q.put(lambda: self._update_found(info))
            self.store.save_settings()

        threading.Thread(target=work, daemon=True).start()

    def _update_found(self, info):
        if not info:
            return
        self.upd_info = info
        self.upd_btn.configure(text="Обновить до %s" % info["version"])
        self.upd_btn.pack(side="left", padx=(14, 0))            # слева от названия: справа кнопке может не хватить места
        self.log("Доступна новая версия лаунчера: %s" % info["version"])
        s = self.store.settings
        if s.get("update_offered") != info["version"] and self.proc is None and not self.busy:
            s["update_offered"] = info["version"]               # окно с предложением — один раз на версию
            self.store.save_settings()
            self.after(300, self.show_update)

    def check_updates_now(self, report):
        """Проверка по кнопке в настройках: без 4-часовой паузы, с пояснением результата."""
        def work():
            info, text = updater.check_report()
            self.q.put(lambda: (report(text), self._update_found(info) if info else None))
        threading.Thread(target=work, daemon=True).start()

    def show_update(self):
        if self.upd_info:
            self.wait_window(UpdateDialog(self, self.upd_info))

    def install_update(self, info):
        if self.proc is not None:
            messagebox.showinfo(APP_NAME, "Сначала закройте игру, потом обновляйте лаунчер.", parent=self)
            return

        last = [0.0]

        def on_bytes(got, total):
            now = time.perf_counter()
            if now - last[0] > 0.15 or got == total:       # не засыпаем интерфейс событиями
                last[0] = now
                self.progress("Скачиваю обновление", got, total or info.get("size") or 0)

        def work(cancel):
            return updater.download_installer(info, on_bytes, cancel)

        def done(path):
            self.log("Запускаю установщик обновления")
            updater.run_installer(path)
            self.destroy()
            os._exit(0)

        self.run_task(work, done, "Скачиваю обновление")

    def open_log(self):
        path = os.path.join(self.store.home, "launcher.log")
        if os.path.isfile(path):
            if os_name() == "windows":
                os.startfile(path)  # noqa
            else:
                subprocess.Popen(["xdg-open" if os_name() == "linux" else "open", path])
        else:
            messagebox.showinfo(APP_NAME, "Журнала пока нет.", parent=self)

    def set_layout(self, name):
        self.store.settings["layout"] = name if name in LAYOUTS else "classic"
        self._layout()

    def _layout(self, e=None):
        cv = self.bg
        W, H = cv.winfo_width(), cv.winfo_height()
        if W < 100 or H < 100:
            return
        sc = self.scale
        lay = LAYOUTS.get(self.store.settings.get("layout"), LAYOUTS["classic"])
        M, G, inset = int(lay["m"] * sc), int(lay["g"] * sc), int(9 * sc)
        top_h, bot_h = int(lay["bar"] * sc), int(lay["bar"] * sc)
        left_w, hero_h = int(lay["left"] * sc), int(lay["hero"] * sc)
        mirror = lay["mirror"]

        def put(card, item, x1, y1, x2, y2):
            card.place(x1, y1, x2, y2)
            cv.coords(item, x1 + inset, y1 + inset)
            cv.itemconfigure(item, width=max(1, x2 - x1 - 2 * inset), height=max(1, y2 - y1 - 2 * inset))

        body_top, body_bot = M + top_h + G, H - M - bot_h - G
        put(self.card_top, self.w_top, M, M, W - M, M + top_h)
        put(self.card_bottom, self.w_bottom, M, H - M - bot_h, W - M, H - M)
        if mirror:
            lx1, x0, x1 = W - M - left_w, M, W - M - left_w - G
        else:
            lx1, x0, x1 = M, M + left_w + G, W - M
        put(self.card_left, self.w_left, lx1, body_top, lx1 + left_w, body_bot)
        put(self.card_tabs, self.w_tabs, x0, body_top + hero_h + int(6 * sc), x1, body_bot)

        # заголовок и кнопки на общем фоне
        tx, ty = x0 + int(6 * sc), body_top + int(2 * sc)
        cv.coords(self.t_name, tx, ty)
        cv.coords(self.t_sub, tx, ty + int(lay["sub"] * sc))
        px = x1 - self.play_btn.w - int(4 * sc)
        py = body_top + (hero_h - self.play_btn.h) // 2 - int(2 * sc)
        self.play_btn.move_to(px, py)
        self.stop_btn.move_to(px - int(10 * sc) - self.stop_btn.w, py + (self.play_btn.h - self.stop_btn.h) // 2)
        text_w = max(100, px - self.stop_btn.w - int(24 * sc) - tx)
        cv.itemconfigure(self.t_name, width=text_w, font=(FONT_NAME, lay["font"], "bold"))
        cv.itemconfigure(self.t_sub, width=text_w)
        self.lava.resize(W, H)

    def _build_log_tab(self):
        f = ttk.Frame(self.nb, style="Panel.TFrame", padding=(10, 4, 10, 10))
        well = Well(f, bg=PANEL)
        inner = ttk.Frame(well, style="Field.TFrame")
        self.logbox = tk.Text(inner, bg=FIELD, fg=FG, relief="flat", wrap="word", state="disabled",
                              font=(MONO, 9), padx=10, pady=8, insertbackground=FG, height=8,
                              highlightthickness=0, borderwidth=0)
        sb = ttk.Scrollbar(inner, orient="vertical", command=self.logbox.yview)
        self.logbox.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.logbox.pack(side="left", fill="both", expand=True)
        well.set_child(inner)
        well.pack(fill="both", expand=True)
        self.nb.add(f, text="Журнал")

    def _build_mods_tab(self):
        f = ttk.Frame(self.nb, style="Panel.TFrame", padding=(14, 4, 14, 12))
        row = ttk.Frame(f, style="Panel.TFrame")
        row.pack(fill="x")
        self.arrow_img = widgets.chevron(self, max(10, int(14 * self.scale)), ACCENT_HOVER)
        self.kind_var = tk.StringVar(value=mods.KINDS["mod"][0])
        self.kind_box = RoundCombo(row, textvariable=self.kind_var, state="readonly", width=12,
                                   values=[v[0] for v in mods.KINDS.values()])
        self.kind_box.pack(side="left", padx=(0, 8))
        self.kind_box.bind("<<ComboboxSelected>>", lambda ev: self._kind_changed())
        self.q_var = tk.StringVar()
        e = Entry(row, textvariable=self.q_var, width=20)
        e.pack(side="left", fill="x", expand=True)
        e.bind("<Return>", lambda ev: self.search_mods())
        Button(row, text="Найти", command=self.search_mods).pack(side="left", padx=(8, 0))
        self.mods_note = ttk.Label(f, text="", style="PanelNote.TLabel", wraplength=520)
        self.mods_note.pack(anchor="w", pady=(6, 0))
        box, self.rtree = _tree(f, [("title", "Стрелка — подробнее, двойной клик — установить", 330),
                                    ("author", "Автор", 110), ("downloads", "Скачиваний", 90)], 5)
        box.pack(fill="both", expand=True, pady=(8, 6))
        self.rtree.bind("<Double-1>", self._rdouble)
        self.rtree.bind("<Button-1>", self._rclick)
        self.rtree.bind("<Motion>", self._rmotion)
        self.rtree.bind("<Return>", lambda ev: self.install_selected())
        self.rtree.bind("<Right>", lambda ev: self.show_selected())
        brow = ttk.Frame(f, style="Panel.TFrame")
        brow.pack(side="bottom", fill="x")                 # кнопки занимают место первыми — таблица сжимается, а не они
        box.pack_forget()
        box.pack(fill="both", expand=True, pady=(8, 6))
        Button(brow, text="Установить выбранный", command=self.install_selected).pack(side="left")
        Button(brow, text="Подробнее", command=self.show_selected).pack(side="left", padx=6)
        self.more_btn = Button(brow, text="Показать ещё", command=lambda: self.search_mods(more=True))
        self.more_btn.pack(side="left")
        self.cat_state = ttk.Label(brow, text="", style="PanelNote.TLabel")
        self.cat_state.pack(side="left", padx=10)
        self.nb.add(f, text="Каталог")
        self._cat_gen, self._cat_loaded, self.hits_kind = 0, False, "mod"
        self.nb.on_select = self._tab_selected

    def _build_installed_tab(self):
        f = ttk.Frame(self.nb, style="Panel.TFrame", padding=(14, 8, 14, 12))
        ttk.Label(f, text="Моды, ресурс-паки и шейдеры этой сборки. Если файла нет в списке, "
                          "добавьте его кнопкой ниже или положите в папку сборки.",
                  style="PanelNote.TLabel", wraplength=560).pack(anchor="w", pady=(0, 8))
        box2, self.mtree = _tree(f, [("title", "Название", 300), ("kind", "Тип", 100), ("file", "Файл", 200)], 8)
        box2.pack(fill="both", expand=True)
        row2 = ttk.Frame(f, style="Panel.TFrame")
        row2.pack(side="bottom", fill="x", pady=(10, 0))
        box2.pack_forget()
        box2.pack(fill="both", expand=True)
        Button(row2, text="Удалить", command=self.remove_selected_mod).pack(side="left")
        Button(row2, text="Обновить все", command=self.update_all_mods).pack(side="left", padx=6)
        Button(row2, text="Добавить файл…", command=self.add_mod_file).pack(side="left")
        Button(row2, text="Папка сборки", command=self.open_game_folder).pack(side="right")
        self.nb.add(f, text="Установлено")

    def _build_instance_tab(self):
        f = ttk.Frame(self.nb, style="Panel.TFrame", padding=(18, 8, 18, 14))
        top = max(2048, total_ram_mb())
        ttk.Label(f, text="Память, МБ (0 — как в общих настройках)", style="Panel.TLabel").pack(anchor="w")
        self.i_ram = tk.StringVar()
        ttk.Spinbox(f, from_=0, to=top, increment=256, textvariable=self.i_ram, width=10).pack(anchor="w", pady=(3, 12))
        ttk.Label(f, text="Путь к Java (пусто — автоматически)", style="Panel.TLabel").pack(anchor="w")
        self.i_java = tk.StringVar()
        row = ttk.Frame(f, style="Panel.TFrame")
        row.pack(fill="x", pady=(3, 12))
        Entry(row, textvariable=self.i_java, width=20).pack(side="left", fill="x", expand=True)
        Button(row, text="Найти…", command=lambda: pick_java(self, self.i_java)).pack(side="left", padx=(8, 0))
        Button(row, text="Обзор…", command=self.pick_java).pack(side="left", padx=(6, 0))
        Button(row, text="Авто", command=lambda: self.i_java.set("")).pack(side="left", padx=(6, 0))
        ttk.Label(f, text="Дополнительные аргументы JVM", style="Panel.TLabel").pack(anchor="w")
        self.i_jvm = tk.StringVar()
        Entry(f, textvariable=self.i_jvm, width=20).pack(fill="x", pady=(3, 14))
        row2 = ttk.Frame(f, style="Panel.TFrame")
        row2.pack(fill="x")
        Button(row2, text="Сохранить", style="Accent.TButton", command=self.save_instance).pack(side="left")
        Button(row2, text="Открыть папку", command=self.open_instance_folder).pack(side="left", padx=8)
        Button(row2, text="Дублировать", command=self.duplicate_instance).pack(side="left")
        Button(row2, text="Удалить", command=self.delete_instance).pack(side="right")
        row3 = ttk.Frame(f, style="Panel.TFrame")
        row3.pack(fill="x", pady=(10, 0))
        Button(row3, text="Иконка сборки…", command=self.open_icons).pack(side="left")
        Button(row3, text="Копии миров…", command=self.open_backups).pack(side="left", padx=8)
        self.nb.add(f, text="Сборка")

    # ------------------------------------------------------------ очередь, журнал, задачи

    def post(self, fn):
        self.q.put(fn)

    def _pump(self):
        try:
            while True:
                fn = self.q.get_nowait()
                try:
                    fn()
                except Exception:
                    logging.exception("callback")
        except queue.Empty:
            pass
        if self.proc is not None and self.proc.poll() is not None:
            code = self.proc.returncode
            self.proc = None
            self.log("Игра закрыта (код %s)." % code)
            self.set_status("Игра закрыта" if code == 0 else "Игра завершилась с ошибкой — см. журнал")
            self._update_buttons()
        self.after(80, self._pump)

    def log(self, msg):
        logging.info(msg)
        self.q.put(lambda m=msg: self._append_log(m))

    def _append_log(self, msg):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", msg + "\n")
        lines = int(self.logbox.index("end-1c").split(".")[0])
        if lines > 3000:
            self.logbox.delete("1.0", "%d.0" % (lines - 2500))
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def set_status(self, text):
        self.status.set(text)

    def progress(self, label, done, total):
        self.q.put(lambda: self._set_progress(label, done, total))

    def _set_progress(self, label, done, total):
        if not self.busy:
            return
        if total:
            if self._pb_mode != "d":
                self.pb.stop()
                self.pb.configure(mode="determinate")
                self._pb_mode = "d"
            self.pb.configure(maximum=total, value=done)
            self.set_status("%s: %d / %d" % (label, done, total))
        else:
            if self._pb_mode != "i":
                self.pb.configure(mode="indeterminate")
                self.pb.start(14)
                self._pb_mode = "i"
            self.set_status(label + "…")

    def run_task(self, fn, done=None, label="", on_error=None):
        """Выполняет fn(cancel) в потоке, затем done(результат) в интерфейсном потоке."""
        if self.busy:
            messagebox.showinfo(APP_NAME, "Подождите, пока закончится текущая операция.", parent=self)
            return False
        self.busy = True
        self.cancel = threading.Event()
        self.set_status(label)
        self.pb.pack(side="right")
        self.cancel_btn.pack(side="right", padx=(0, 10))
        self._pb_mode = None
        self._set_progress(label, 0, 0)
        self._update_buttons()
        cancel = self.cancel

        def work():
            try:
                res, err = fn(cancel), None
            except BaseException as e:
                res, err = None, e
                if not isinstance(e, Cancelled):
                    logging.error("task failed\n%s", traceback.format_exc())
            self.q.put(lambda: self._task_done(done, res, err, on_error))

        threading.Thread(target=work, daemon=True).start()
        return True

    def _task_done(self, done, res, err, on_error):
        self.busy = False
        self.pb.stop()
        self.pb.pack_forget()
        self.cancel_btn.pack_forget()
        self._update_buttons()
        if isinstance(err, Cancelled):
            self.set_status("Отменено")
            return
        if err is not None:
            self.set_status("Ошибка")
            self.log("Ошибка: %s" % err)
            if on_error and on_error(err):
                return
            messagebox.showerror(APP_NAME, str(err), parent=self)
            return
        self.set_status("Готово")
        if done:
            done(res)

    def cancel_task(self):
        if self.cancel is not None:
            self.cancel.set()
            self.set_status("Отменяю…")

    def report_callback_exception(self, exc, val, tb):
        logging.error("ui error\n%s", "".join(traceback.format_exception(exc, val, tb)))
        messagebox.showerror(APP_NAME, "Внутренняя ошибка: %s" % val, parent=self)

    # ------------------------------------------------------------ аккаунты

    def refresh_accounts(self):
        accs = self.store.accounts
        self.acc_ids = [a["id"] for a in accs]
        self.acc_box.configure(values=["%s  ·  %s" % (a["name"], auth.type_title(a["type"])) for a in accs])
        last = self.store.settings.get("last_account")
        if last in self.acc_ids:
            self.acc_box.current(self.acc_ids.index(last))
        elif accs:
            self.acc_box.current(0)
            self.store.settings["last_account"] = accs[0]["id"]
        else:
            self.acc_var.set("Нет аккаунта")
        self._update_buttons()
        self.refresh_head()

    def current_account(self):
        i = self.acc_box.current()
        if 0 <= i < len(self.acc_ids):
            return self.store.find_account(self.acc_ids[i])
        return None

    def on_account_pick(self, _=None):
        acc = self.current_account()
        if acc:
            self.store.settings["last_account"] = acc["id"]
            self.store.save_settings()
        self.refresh_head()

    def open_accounts(self):
        d = AccountsDialog(self)
        self.wait_window(d)
        self.refresh_accounts()

    def open_settings(self):
        d = SettingsDialog(self)
        self.wait_window(d)

    # ------------------------------------------------------------ сборки

    def icon_photo(self, inst):
        """Картинка иконки сборки для списка (или пустая заглушка, чтобы строки не прыгали)."""
        size = icons.icon_size(self.scale)
        cache = self.__dict__.setdefault("_icon_cache", {})
        key = inst.icon if inst.icon in icons.TITLES else ""
        if (key, size) not in cache:
            img = None
            path = icons.icon_file(self.store, key, size) if key else ""
            if path and not os.path.exists(path) and size not in self.__dict__.setdefault("_icon_tried", set()):
                self._icon_tried.add(size)
                icons.extract(self.store, size)          # иконки для этого размера ещё не вырезаны
            if path and os.path.exists(path):
                try:
                    img = tk.PhotoImage(master=self, file=path)
                except tk.TclError:
                    img = None
            if img is None:
                img = tk.PhotoImage(master=self, width=size, height=size)    # прозрачная пустышка
            cache[(key, size)] = img
        return cache[(key, size)]

    def accent_color(self):
        from . import theme
        return theme.ACCENT

    def open_backups(self):
        backup.BackupsDialog(self)

    def open_icons(self):
        if self.current:
            from .dialogs import IconDialog
            IconDialog(self)

    def set_icon(self, inst, key):
        inst.icon = key
        inst.save()
        self.reload_instances(inst.slug)

    def refresh_head(self):
        """Голова рядом с ником: сразу стандартная или из кэша, настоящую скачиваем в фоне."""
        acc = self.current_account()
        size = int(24 * self.scale)
        if acc is None:
            self.head_lbl.configure(image="")
            return
        path = skins.head_path(self.store, acc, size) or skins.stale_head(self.store, acc, size) \
            or skins.default_head(self.store, size)
        self._set_head(path)
        if acc["type"] in ("elyby", "microsoft") and not skins.head_path(self.store, acc, size):
            acc_id = acc["id"]

            def work():
                p = skins.fetch_head(self.store, acc, size)
                if p:
                    self.post(lambda: self._head_ready(acc_id, p))
            threading.Thread(target=work, daemon=True).start()

    def _head_ready(self, acc_id, path):
        cur = self.current_account()
        if cur and cur["id"] == acc_id:
            self._set_head(path)

    def _set_head(self, path):
        try:
            self._head_img = tk.PhotoImage(master=self, file=path)
            self.head_lbl.configure(image=self._head_img)
        except tk.TclError:
            self.head_lbl.configure(image="")

    def reload_instances(self, select=None):
        self.insts = instances.list_instances(self.store)
        self.itree.delete(*self.itree.get_children())
        for inst in self.insts:
            self.itree.insert("", "end", iid=inst.slug, text="  " + inst.name, image=self.icon_photo(inst))
        target = select if select in [i.slug for i in self.insts] else (self.insts[0].slug if self.insts else None)
        if target:
            self.itree.selection_set(target)
            self.itree.focus(target)
        else:
            self.current = None
            self.refresh_header()

    def on_select(self, _=None):
        sel = self.itree.selection()
        self.current = next((i for i in self.insts if sel and i.slug == sel[0]), None)
        if self.current:
            self.store.settings["last_instance"] = self.current.slug
            self.store.save_settings()
        self.refresh_header()

    def refresh_header(self):
        inst = self.current
        if inst:
            self.h_name.configure(text=inst.name)
            self.h_sub.configure(text="%s  ·  последний запуск: %s" % (inst.title(), inst.last_played_text()))
            self.i_ram.set(str(inst.ram_mb))
            self.i_java.set(inst.java_path)
            self.i_jvm.set(inst.jvm_args)
            self.refresh_installed()
        else:
            self.h_name.configure(text="Нет сборок")
            self.h_sub.configure(text="Нажмите «Создать» слева — выберите версию и, если нужно, загрузчик модов.")
            self.mtree.delete(*self.mtree.get_children())
        self._update_note()
        self._cat_loaded = False                       # результаты поиска зависят от версии игры и загрузчика
        if inst and self.nb.sel == 1 and self._kind() != "modpack":
            self._cat_loaded = True
            self.search_mods()
        self._update_buttons()

    def _update_buttons(self):
        running = self.proc is not None
        can_play = self.current is not None and not self.busy and not running
        self.play_btn.configure(state="normal" if can_play else "disabled")
        self.stop_btn.configure(state="normal" if running else "disabled")

    def new_instance(self):
        d = NewInstanceDialog(self)
        self.wait_window(d)
        if d.result:
            self.reload_instances(d.result.slug)

    def import_pack(self):
        path = filedialog.askopenfilename(parent=self, title="Сборка Modrinth",
                                          filetypes=[("Сборка Modrinth", "*.mrpack"), ("Все файлы", "*.*")])
        if not path:
            return
        self.run_task(lambda c: mods.import_mrpack(self.store, path, self.log, self.progress, c),
                      lambda inst: self.reload_instances(inst.slug), "Импорт сборки")

    def save_instance(self):
        inst = self.current
        if not inst:
            return
        try:
            inst.ram_mb = max(0, int(self.i_ram.get() or 0))
        except ValueError:
            messagebox.showerror(APP_NAME, "Память должна быть числом (МБ)", parent=self)
            return
        inst.java_path = self.i_java.get().strip()
        inst.jvm_args = self.i_jvm.get().strip()
        inst.save()
        self.set_status("Настройки сборки сохранены")

    def pick_java(self):
        p = filedialog.askopenfilename(parent=self, title="Java (java.exe)")
        if p:
            self.i_java.set(p)

    def open_instance_folder(self):
        if self.current:
            open_folder(self.current.game_dir)

    def duplicate_instance(self):
        inst = self.current
        if not inst:
            return
        copy = instances.duplicate_instance(self.store, inst, inst.name + " (копия)")
        self.reload_instances(copy.slug)

    def delete_instance(self):
        inst = self.current
        if inst and messagebox.askyesno(APP_NAME, "Удалить сборку «%s» вместе с мирами и модами?" % inst.name,
                                        parent=self):
            instances.delete_instance(inst)
            self.reload_instances()

    # ------------------------------------------------------------ игра

    def play(self):
        inst, acc, store = self.current, self.current_account(), self.store
        if not inst:
            return
        if not acc:
            messagebox.showinfo(APP_NAME, "Сначала добавьте аккаунт: офлайн, Ely.by или Microsoft.", parent=self)
            self.open_accounts()
            return
        self.nb.select(0)
        if store.settings.get("backup_worlds", True) and self.proc is None:
            backup.backup_in_background(inst, int(store.settings.get("backup_keep", 3)), self.log)

        def work(cancel):
            if auth.ensure_fresh(store, acc):
                store.save_accounts()
            prep = game.prepare(store, inst, self.log, self.progress, cancel)
            agent = auth.authlib_injector(store, self.log) if acc["type"] == "elyby" else None
            ident = auth.identity(acc)
            return game.build_command(store, inst, prep, ident, agent), ident

        def done(res):
            cmd, ident = res
            self.log("Запуск: " + game.describe_command(cmd, [ident["access_token"]]))
            self.proc = game.start(cmd, inst.game_dir, self.log)
            inst.last_played = int(time.time())
            inst.save()
            self.set_status("Игра запущена")
            self.refresh_header()

        self.run_task(work, done, "Подготовка к запуску")

    def stop_game(self):
        if self.proc is not None:
            self.proc.terminate()
            self.log("Игра остановлена.")

    # ------------------------------------------------------------ моды

    # ------------------------------------------------------------ каталог

    def _kind(self):
        name = self.kind_var.get()
        return next((k for k, v in mods.KINDS.items() if v[0] == name), "mod")

    def _tab_selected(self, i):
        if i == 4:
            self.friends_tab.on_show()
        if i == 1 and not self._cat_loaded and self.current:
            self._cat_loaded = True
            self.search_mods()

    def _kind_changed(self):
        self._update_note()
        self.q_var.set("")
        self.search_mods()

    def _update_note(self):
        inst, kind = self.current, self._kind()
        text = {
            "mod": "" if inst and inst.loader != "vanilla" else
                   "Моды работают в сборках с Fabric, Quilt, Forge или NeoForge — выберите загрузчик при создании сборки.",
            "resourcepack": "Ресурс-пак ляжет в папку сборки; включите его в игре: Настройки, Ресурс-паки.",
            "shader": "Шейдеры нужны вместе с модом Iris (Fabric/Quilt) или Oculus (Forge); включаются в игре: Настройки, Шейдеры.",
            "modpack": "Сборка скачивается целиком и появится слева как новая сборка со своей версией игры и модами.",
        }[kind]
        self.mods_note.configure(text=text)

    def search_mods(self, more=False):
        inst, kind = self.current, self._kind()
        if kind != "modpack" and not inst:
            return
        if kind == "mod" and inst.loader == "vanilla":
            self._update_note()
            self._show_hits([], self._cat_gen, False, kind)
            return
        q = self.q_var.get().strip()
        offset = len(self.hits) if more and self.hits_kind == kind else 0
        self._cat_gen += 1
        gen = self._cat_gen
        self.cat_state.configure(text="Ищу…")
        mc, ld = (inst.mc_version, inst.loader) if inst else ("", "")

        def work():
            try:
                hits = mods.search(q, mc, ld, 30, offset, kind)
                err = None
            except Exception as e:
                hits, err = [], e
            self.post(lambda: self._show_hits(hits, gen, offset > 0, kind, err))

        threading.Thread(target=work, daemon=True).start()

    def _show_hits(self, hits, gen, more, kind, err=None):
        if gen != self._cat_gen:
            return                                      # пока ждали, запустили новый поиск
        self._update_note()
        if more and self.hits_kind == kind:
            start = len(self.hits)
            self.hits = self.hits + hits
        else:
            start, self.hits = 0, list(hits)
            self.rtree.delete(*self.rtree.get_children())
        self.hits_kind = kind
        for i, h in enumerate(hits, start):
            n = "{:,}".format(h.get("downloads", 0)).replace(",", " ")
            self.rtree.insert("", "end", iid=str(i), text=" " + h.get("title", ""), image=self.arrow_img,
                              values=(h.get("author", ""), n))
        if err is not None:
            self.cat_state.configure(text="Нет связи с Modrinth")
        elif not self.hits:
            self.cat_state.configure(text="Ничего не найдено" + ("" if kind == "modpack" else " для этой версии игры"))
        else:
            self.cat_state.configure(text="Найдено: %d" % len(self.hits))
        self.more_btn.configure(state="normal" if len(hits) >= 30 else "disabled")

    def _hit_at(self, event):
        iid = self.rtree.identify_row(event.y)
        return int(iid) if iid else None

    def _arrow_zone(self, event):
        return event.x < int(46 * self.scale) and self.rtree.identify_region(event.x, event.y) in ("tree", "cell")

    def _rmotion(self, event):
        want = "hand2" if self._arrow_zone(event) and self._hit_at(event) is not None else ""
        if self.rtree.cget("cursor") != want:
            self.rtree.configure(cursor=want)

    def _rclick(self, event):
        i = self._hit_at(event)
        if i is not None and self._arrow_zone(event):
            self.rtree.selection_set(str(i))
            self.after(1, lambda: self.show_hit(self.hits[i]))
            return "break"

    def _rdouble(self, event):
        if self._hit_at(event) is not None and not self._arrow_zone(event):
            self.install_selected()

    def show_selected(self):
        sel = self.rtree.selection()
        if sel:
            self.show_hit(self.hits[int(sel[0])])

    def show_hit(self, hit):
        ProjectDialog(self, hit, self.hits_kind, self.install_hit)

    def install_selected(self):
        sel = self.rtree.selection()
        if sel:
            self.install_hit(self.hits[int(sel[0])], self.hits_kind)

    def install_hit(self, hit, kind):
        inst, store = self.current, self.store
        title, pid = hit.get("title", ""), hit["project_id"]
        if kind == "modpack":
            self.run_task(lambda c: mods.install_modpack(store, pid, title, self.log, self.progress, c),
                          lambda i: (self.reload_instances(i.slug), self.nb.select(0),
                                     self.set_status("Сборка «%s» установлена" % i.name)),
                          "Установка сборки")
            return
        if not inst:
            messagebox.showinfo(APP_NAME, "Сначала создайте сборку слева.", parent=self)
            return
        if kind == "mod" and inst.loader == "vanilla":
            messagebox.showinfo(APP_NAME, "Для сборки без загрузчика моды недоступны. "
                                          "Создайте сборку с Fabric, Quilt, Forge или NeoForge.", parent=self)
            return
        word = mods.KINDS[kind][2].lower()
        self.run_task(lambda c: mods.install_mod(inst, pid, title, self.log, c, kind=kind),
                      lambda r: (self.refresh_installed(),
                                 self.set_status("Установлено: %d" % len(r) if r else "Уже установлено")),
                      "Установка: " + word)

    def refresh_installed(self):
        self.mtree.delete(*self.mtree.get_children())
        if self.current:
            for i, m in enumerate(self.current.mods):
                self.mtree.insert("", "end", iid=str(i), text=m.get("title", ""),
                                  values=(mods.KINDS[mods.entry_kind(m)][2], m.get("filename", "")))

    def remove_selected_mod(self):
        inst, sel = self.current, self.mtree.selection()
        if inst and sel:
            mods.remove_mod(inst, inst.mods[int(sel[0])])
            self.refresh_installed()

    def update_all_mods(self):
        inst = self.current
        if not inst:
            return
        self.run_task(lambda c: mods.update_mods(inst, self.log, c),
                      lambda n: (self.refresh_installed(), self.set_status("Обновлено модов: %d" % n)),
                      "Обновление модов")

    def add_mod_file(self):
        inst = self.current
        if not inst:
            return
        for p in filedialog.askopenfilenames(parent=self, title="Файлы модов",
                                             filetypes=[("Моды", "*.jar"), ("Все файлы", "*.*")]):
            mods.add_local_file(inst, p)
        self.refresh_installed()

    def open_game_folder(self):
        if self.current:
            open_folder(self.current.game_dir)

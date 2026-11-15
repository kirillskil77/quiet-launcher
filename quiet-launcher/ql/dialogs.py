"""Диалоги: аккаунты, новая сборка, настройки."""
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk, messagebox

from . import auth, game, instances, javart, loaders, widgets
from .widgets import (RoundButton as Button, RoundEntry as Entry, RoundCombo as Combobox,
                      RoundSlider as Scale, Switch as Checkbutton)
from .instances import LOADERS, LOADER_TITLES
from .theme import PANEL, FIELD, FG, MUTED, LINE as LINE_COLOR, FONT as FONT_NAME
from .util import Cancelled, total_ram_mb


class Dialog(tk.Toplevel):
    def __init__(self, app, title):
        tk.Toplevel.__init__(self, app)
        self.app = app
        self.result = None
        self.title(title)
        self.configure(bg=app.cget("bg"))
        self.transient(app)
        self.resizable(False, False)
        body = ttk.Frame(self, padding=20)
        body.pack(fill="both", expand=True)
        self.build(body)
        self.bind("<Escape>", lambda e: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = app.winfo_rootx() + (app.winfo_width() - w) // 2
        y = app.winfo_rooty() + (app.winfo_height() - h) // 3
        self.geometry("+%d+%d" % (max(x, 0), max(y, 0)))
        self.after(50, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.focus_set()
        except tk.TclError:
            pass

    def build(self, body):
        pass

    def close(self):
        self.destroy()

    def buttons(self, body, ok_text, ok_cmd, accent=True):
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(14, 0))
        Button(row, text="Отмена", command=self.close).pack(side="right")
        Button(row, text=ok_text, command=ok_cmd,
                   style="Accent.TButton" if accent else "TButton").pack(side="right", padx=(0, 8))
        return row


class FormDialog(Dialog):
    """Простая форма из текстовых полей. Результат — словарь или None."""

    def __init__(self, app, title, fields, ok="OK", hint=""):
        self.fields, self.ok_text, self.hint = fields, ok, hint
        self.vars = {}
        Dialog.__init__(self, app, title)

    def build(self, body):
        if self.hint:
            ttk.Label(body, text=self.hint, style="Muted.TLabel", wraplength=380,
                      justify="left").pack(anchor="w", pady=(0, 12))
        first = None
        for key, label, secret, init in self.fields:
            ttk.Label(body, text=label).pack(anchor="w")
            v = tk.StringVar(value=init)
            e = Entry(body, textvariable=v, width=44, show="•" if secret else "")
            e.pack(fill="x", pady=(3, 10))
            e.bind("<Return>", lambda ev: self.accept())
            self.vars[key] = v
            first = first or e
        self.buttons(body, self.ok_text, self.accept)
        if first:
            first.focus_set()

    def accept(self):
        self.result = {k: v.get() for k, v in self.vars.items()}
        self.destroy()


def ask_form(app, title, fields, ok="OK", hint=""):
    d = FormDialog(app, title, fields, ok, hint)
    app.wait_window(d)
    return d.result


# ------------------------------------------------------------------ аккаунты

class AccountsDialog(Dialog):
    def __init__(self, app):
        Dialog.__init__(self, app, "Аккаунты")

    def build(self, body):
        self.tree = ttk.Treeview(body, columns=("type",), height=7, selectmode="browse")
        self.tree.heading("#0", text="Игровой ник", anchor="w")
        self.tree.heading("type", text="Тип", anchor="w")
        self.tree.column("#0", width=240)
        self.tree.column("type", width=110)
        self.tree.pack(fill="x")
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(12, 0))
        Button(row, text="Офлайн…", command=self.add_offline).pack(side="left")
        Button(row, text="Ely.by…", command=self.add_ely).pack(side="left", padx=6)
        Button(row, text="Microsoft…", command=self.add_ms).pack(side="left")
        Button(row, text="Удалить", command=self.remove).pack(side="right")
        ttk.Label(body, text="Офлайн-ник работает в одиночной игре и на серверах без проверки лицензии. "
                  "Ely.by и Microsoft входят по своим аккаунтам.", style="Muted.TLabel",
                  wraplength=380, justify="left").pack(anchor="w", pady=(12, 0))
        self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for a in self.app.store.accounts:
            self.tree.insert("", "end", iid=a["id"], text=a["name"], values=(auth.type_title(a["type"]),))
        self.app.refresh_accounts()

    def _added(self, acc):
        self.app.store.accounts.append(acc)
        self.app.store.settings["last_account"] = acc["id"]
        self.app.store.save_accounts()
        self.app.store.save_settings()
        if self.winfo_exists():
            self.refresh()

    def add_offline(self):
        res = ask_form(self.app, "Офлайн-аккаунт", [("name", "Ник (3–16 символов: латиница, цифры, _)", False, "")],
                       "Добавить")
        if not res:
            return
        try:
            self._added(auth.new_offline(res["name"]))
        except auth.AuthError as e:
            messagebox.showerror("Офлайн-аккаунт", str(e), parent=self)

    def add_ely(self, login="", password=""):
        fields = [("login", "Ник или e-mail на Ely.by", False, login), ("password", "Пароль", True, password)]
        res = ask_form(self.app, "Вход через Ely.by", fields, "Войти")
        if not res:
            return
        self._ely_try(res["login"], res["password"], "")

    def _ely_try(self, login, password, totp):
        def on_error(err):
            if isinstance(err, auth.TwoFactorRequired):
                code = ask_form(self.app, "Двухфакторная защита",
                                [("code", "Код из приложения-аутентификатора", False, "")], "Войти",
                                "На этом аккаунте включена двухфакторная защита.")
                if code and code["code"].strip():
                    self._ely_try(login, password, code["code"])
                return True
            return False

        self.app.run_task(lambda c: auth.ely_login(login, password, totp), self._added,
                          "Вход в Ely.by…", on_error=on_error)

    def add_ms(self):
        d = MsDialog(self.app)
        self.app.wait_window(d)
        if d.result:
            self._added(d.result)

    def remove(self):
        sel = self.tree.selection()
        if not sel:
            return
        store = self.app.store
        store.accounts = [a for a in store.accounts if a["id"] != sel[0]]
        store.save_accounts()
        self.refresh()


class MsDialog(Dialog):
    """Вход через Microsoft по коду (device code flow): открываем страницу, вводим код."""

    def __init__(self, app):
        self.cancel = threading.Event()
        Dialog.__init__(self, app, "Вход через Microsoft")

    def build(self, body):
        self.body = body
        ttk.Label(body, text="Client id приложения Azure", style="Muted.TLabel").pack(anchor="w")
        self.cid = tk.StringVar(value=self.app.store.settings.get("ms_client_id", ""))
        self.entry = Entry(body, textvariable=self.cid, width=44)
        self.entry.pack(fill="x", pady=(3, 4))
        ttk.Label(body, text="Как его получить — в README, раздел «Вход через Microsoft».",
                  style="Muted.TLabel").pack(anchor="w")
        self.info = ttk.Label(body, text="", wraplength=380, justify="left")
        self.info.pack(anchor="w", pady=(12, 0))
        self.code = ttk.Label(body, text="", style="Code.TLabel")
        self.code.pack(anchor="w", pady=(6, 0))
        self.row = ttk.Frame(body)
        self.row.pack(fill="x", pady=(14, 0))
        Button(self.row, text="Отмена", command=self.close).pack(side="right")
        self.go = Button(self.row, text="Продолжить", style="Accent.TButton", command=self.start)
        self.go.pack(side="right", padx=(0, 8))
        self.open_btn = Button(self.row, text="Открыть страницу", command=self.open_page)
        self.url = ""

    def close(self):
        self.cancel.set()
        self.destroy()

    def open_page(self):
        webbrowser.open(self.url)

    def _post(self, fn):
        def safe():
            if self.winfo_exists():
                fn()
        self.app.q.put(safe)

    def start(self):
        cid = self.cid.get().strip()
        if not cid:
            self.info.configure(text="Укажите client id.")
            return
        self.app.store.settings["ms_client_id"] = cid
        self.app.store.save_settings()
        self.entry.configure(state="disabled")
        self.go.configure(state="disabled")
        self.info.configure(text="Связываюсь с Microsoft…")

        def work():
            try:
                dev = auth.ms_device_start(cid)
                self._post(lambda: self._show_code(dev))
                tok = auth.ms_device_wait(cid, dev, self.cancel)
                self._post(lambda: self.info.configure(text="Проверяю Xbox и Minecraft…"))
                acc = auth.ms_account_from_token(tok)
                self._post(lambda: self._finish(acc))
            except Cancelled:
                return
            except Exception as e:
                msg = str(e)
                self._post(lambda: self._fail(msg))

        threading.Thread(target=work, daemon=True).start()

    def _show_code(self, dev):
        self.url = dev.get("verification_uri", "https://microsoft.com/link")
        self.info.configure(text="Откройте %s и введите код:" % self.url)
        self.code.configure(text=dev["user_code"])
        self.open_btn.pack(side="left")
        self.clipboard_clear()
        self.clipboard_append(dev["user_code"])
        webbrowser.open(self.url)

    def _finish(self, acc):
        self.result = acc
        self.cancel.set()
        self.destroy()

    def _fail(self, msg):
        self.info.configure(text=msg)
        self.code.configure(text="")
        self.entry.configure(state="normal")
        self.go.configure(state="normal")


# ------------------------------------------------------------------ новая сборка

class NewInstanceDialog(Dialog):
    def __init__(self, app):
        self.token = 0
        Dialog.__init__(self, app, "Новая сборка")

    def build(self, body):
        store = self.app.store
        ttk.Label(body, text="Название").pack(anchor="w")
        self.name = tk.StringVar()
        e = Entry(body, textvariable=self.name, width=44)
        e.pack(fill="x", pady=(3, 10))
        e.focus_set()

        ttk.Label(body, text="Версия Minecraft").pack(anchor="w")
        self.mc = tk.StringVar()
        self.mc_box = Combobox(body, textvariable=self.mc, values=[], width=42)
        self.mc_box.pack(fill="x", pady=(3, 4))
        self.snap = tk.BooleanVar(value=bool(store.settings.get("show_snapshots")))
        Checkbutton(body, text="Показывать снапшоты", variable=self.snap,
                        command=self.load_versions).pack(anchor="w", pady=(0, 10))

        ttk.Label(body, text="Загрузчик модов").pack(anchor="w")
        self.loader = tk.StringVar(value=LOADER_TITLES["vanilla"])
        self.loader_box = Combobox(body, textvariable=self.loader, state="readonly", width=42,
                                       values=[LOADER_TITLES[k] for k in LOADERS])
        self.loader_box.pack(fill="x", pady=(3, 10))
        self.loader_box.bind("<<ComboboxSelected>>", lambda e: self.load_loader_versions())
        self.mc_box.bind("<<ComboboxSelected>>", lambda e: self.load_loader_versions())

        ttk.Label(body, text="Версия загрузчика (пусто — последняя)").pack(anchor="w")
        self.lv = tk.StringVar()
        self.lv_box = Combobox(body, textvariable=self.lv, values=[], width=42)
        self.lv_box.pack(fill="x", pady=(3, 4))
        self.note = ttk.Label(body, text="", style="Muted.TLabel", wraplength=380, justify="left")
        self.note.pack(anchor="w")
        self.buttons(body, "Создать", self.create)
        self.load_versions()

    def _loader_key(self):
        for k in LOADERS:
            if LOADER_TITLES[k] == self.loader.get():
                return k
        return "vanilla"

    def load_versions(self):
        store = self.app.store
        snaps = self.snap.get()
        self.note.configure(text="Загружаю список версий…")

        def work():
            try:
                vs = game.list_versions(store, snaps)
                err = ""
            except Exception as e:
                vs, err = [], "Не удалось получить список версий (%s). Версию можно ввести вручную." % e
            self.app.q.put(lambda: self._versions_ready(vs, err))

        threading.Thread(target=work, daemon=True).start()

    def _versions_ready(self, vs, err):
        if not self.winfo_exists():
            return
        self.mc_box.configure(values=vs)
        if vs and not self.mc.get():
            self.mc.set(vs[0])
        self.note.configure(text=err)
        self.load_loader_versions()

    def load_loader_versions(self):
        loader, mc = self._loader_key(), self.mc.get().strip()
        self.lv.set("")
        self.lv_box.configure(values=[])
        if loader == "vanilla" or not mc:
            return
        self.token += 1
        token = self.token
        self.note.configure(text="Ищу версии загрузчика…")

        def work():
            try:
                vs, err = loaders.list_loader_versions(loader, mc), ""
                if not vs:
                    err = "Для Minecraft %s загрузчик %s не найден." % (mc, LOADER_TITLES[loader])
            except Exception as e:
                vs, err = [], "Не удалось получить версии загрузчика: %s" % e

            def apply():
                if self.winfo_exists() and token == self.token:
                    self.lv_box.configure(values=vs)
                    if vs:
                        self.lv.set(vs[0])
                    self.note.configure(text=err)
            self.app.q.put(apply)

        threading.Thread(target=work, daemon=True).start()

    def create(self):
        store = self.app.store
        mc = self.mc.get().strip()
        if not mc:
            messagebox.showerror("Новая сборка", "Выберите версию Minecraft", parent=self)
            return
        try:
            inst = instances.create_instance(store, self.name.get() or mc, mc,
                                             self._loader_key(), self.lv.get().strip())
        except ValueError as e:
            messagebox.showerror("Новая сборка", str(e), parent=self)
            return
        store.settings["show_snapshots"] = bool(self.snap.get())
        store.save_settings()
        self.result = inst
        self.destroy()


# ------------------------------------------------------------------ выбор Java

class JavaPickDialog(Dialog):
    """Ищет установленные Java (в лаунчере, у других лаунчеров, в системе) и даёт выбрать одну."""

    def __init__(self, app):
        self.paths = {}
        Dialog.__init__(self, app, "Выбор Java")

    def build(self, body):
        self.note = ttk.Label(body, text="Ищу Java на компьютере…", style="Muted.TLabel")
        self.note.pack(anchor="w", pady=(0, 8))
        self.tree = ttk.Treeview(body, columns=("src", "path"), height=8, selectmode="browse")
        self.tree.heading("#0", text="Версия", anchor="w")
        self.tree.heading("src", text="Откуда", anchor="w")
        self.tree.heading("path", text="Путь", anchor="w")
        self.tree.column("#0", width=80, stretch=False)
        self.tree.column("src", width=120, stretch=False)
        self.tree.column("path", width=420)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self.choose())
        self.buttons(body, "Выбрать", self.choose)
        store = self.app.store

        def work():
            try:
                found = javart.detect_javas(store)
            except Exception:
                found = []
            self.app.q.put(lambda: self._show(found))

        threading.Thread(target=work, daemon=True).start()

    def _show(self, found):
        if not self.winfo_exists():
            return
        for i, j in enumerate(found):
            self.paths[str(i)] = j["path"]
            self.tree.insert("", "end", iid=str(i), text="Java %d" % j["major"],
                             values=(j["source"], j["path"]))
        self.note.configure(text="Найдено: %d. Выберите нужную (для Minecraft 1.20.5+ — Java 21)."
                            % len(found) if found else "Java не найдена. Лаунчер скачает Java сам при первом запуске игры.")
        if found:
            self.tree.selection_set("0")

    def choose(self):
        sel = self.tree.selection()
        if sel:
            self.result = self.paths[sel[0]]
            self.destroy()


def pick_java(app, var):
    d = JavaPickDialog(app)
    app.wait_window(d)
    if d.result:
        var.set(d.result)


# ------------------------------------------------------------------ настройки

class SettingsDialog(Dialog):
    def __init__(self, app):
        Dialog.__init__(self, app, "Настройки")

    def build(self, body):
        from .ui import LAYOUTS
        from .theme import THEMES, ACCENTS
        s = self.app.store.settings
        self.orig_layout = s.get("layout", "classic")
        self.layout_name = self.orig_layout
        self.theme_name = s.get("theme", "black")
        self.accent_val = s.get("accent", "#4f8f6a")
        self.saved = False
        tabs = widgets.PillTabs(body)
        tabs.pack(fill="both", expand=True)

        pages = []

        def page(title):
            f = ttk.Frame(tabs, style="Panel.TFrame", padding=(14, 12, 14, 10))
            tabs.add(f, text=title)
            pages.append(f)
            return f

        # --- основное
        f = page("Основное")
        top = max(2048, min(total_ram_mb(), 32768))
        ttk.Label(f, text="Память для игры по умолчанию", style="Panel.TLabel").pack(anchor="w")
        row = ttk.Frame(f, style="Panel.TFrame")
        row.pack(fill="x", pady=(3, 12))
        self.ram = tk.IntVar(value=int(s.get("ram_mb", 2048)))
        self.ram_label = ttk.Label(row, text="", width=9, anchor="e", style="Panel.TLabel")
        self.ram_label.pack(side="right")
        Scale(row, from_=1024, to=top, variable=self.ram, command=self._ram_changed, bg=PANEL).pack(
            side="left", fill="x", expand=True, padx=(0, 10))
        self._ram_changed()
        self.zulu = tk.BooleanVar(value=bool(s.get("use_zulu", True)))
        Checkbutton(f, variable=self.zulu, bg=PANEL, text="Если Java от Mojang не запускается (например, на Windows 7),\n"
                    "ставить Java Zulu 21").pack(anchor="w", pady=(0, 12))
        ttk.Label(f, text="Путь к Java (пусто — подобрать автоматически)", style="Panel.TLabel").pack(anchor="w")
        self.java = tk.StringVar(value=s.get("java_path", ""))
        jrow = ttk.Frame(f, style="Panel.TFrame")
        jrow.pack(fill="x", pady=(3, 12))
        Entry(jrow, textvariable=self.java, width=30, bg=PANEL).pack(side="left", fill="x", expand=True)
        Button(jrow, text="Найти…", command=lambda: pick_java(self.app, self.java)).pack(side="left", padx=(8, 0))
        Button(jrow, text="Авто", command=lambda: self.java.set("")).pack(side="left", padx=(6, 0))
        self.upd = tk.BooleanVar(value=bool(s.get("check_updates", True)))
        Checkbutton(f, variable=self.upd, bg=PANEL, text="Проверять обновления лаунчера при запуске").pack(anchor="w", pady=(0, 6))
        urow = ttk.Frame(f, style="Panel.TFrame")
        urow.pack(fill="x", pady=(0, 12))
        self.upd_note = tk.StringVar(value="")
        Button(urow, text="Проверить сейчас", command=self._check_now).pack(side="left")
        ttk.Label(urow, textvariable=self.upd_note, style="PanelNote.TLabel", wraplength=300,
                  justify="left").pack(side="left", padx=10)
        ttk.Label(f, text="Client id приложения Microsoft", style="Panel.TLabel").pack(anchor="w")
        self.cid = tk.StringVar(value=s.get("ms_client_id", ""))
        Entry(f, textvariable=self.cid, width=40, bg=PANEL).pack(fill="x", pady=(3, 4))

        # --- производительность
        f = page("Производительность")
        ttk.Label(f, text="Пресет параметров JVM", style="Panel.TLabel").pack(anchor="w")
        self.preset_keys = list(game.PRESETS)
        cur = s.get("perf_preset", "default")
        self.preset = tk.StringVar(value=game.PRESETS.get(cur, game.PRESETS["default"])[0])
        pc = Combobox(f, textvariable=self.preset, state="readonly", width=24, bg=PANEL,
                      values=[game.PRESETS[k][0] for k in self.preset_keys])
        pc.pack(anchor="w", pady=(3, 4))
        self.preset_note = ttk.Label(f, text="", style="PanelNote.TLabel", wraplength=420, justify="left")
        self.preset_note.pack(anchor="w", pady=(0, 12))
        pc.bind("<<ComboboxSelected>>", lambda e: self._preset_changed())
        self._preset_changed()
        self.tune = tk.BooleanVar(value=bool(s.get("jvm_tuning", True)))
        Checkbutton(f, variable=self.tune, bg=PANEL, text="Для пресета «По умолчанию»: оптимизировать параметры JVM\n"
                    "(рекомендуется)").pack(anchor="w", pady=(0, 10))
        self.anim = tk.BooleanVar(value=bool(s.get("animations", True)))
        Checkbutton(f, variable=self.anim, bg=PANEL, text="Анимированный фон и плавные эффекты\n"
                    "(во время игры не работают)").pack(anchor="w", pady=(0, 12))
        ttk.Label(f, text="Дополнительные аргументы JVM (через пробел)", style="Panel.TLabel").pack(anchor="w")
        self.jvm = tk.StringVar(value=s.get("jvm_args", ""))
        Entry(f, textvariable=self.jvm, width=40, bg=PANEL).pack(fill="x", pady=(3, 4))
        ttk.Label(f, text="Ваш сборщик мусора (например -XX:+UseZGC) пресеты не заменяют.", style="PanelNote.TLabel",
                  wraplength=420).pack(anchor="w")

        # --- оформление
        f = page("Оформление")
        ttk.Label(f, text="Тема", style="Panel.TLabel").pack(anchor="w")
        trow = ttk.Frame(f, style="Panel.TFrame")
        trow.pack(fill="x", pady=(4, 10))
        self.theme_btns = {}
        for key, (title, pal) in THEMES.items():
            cv = tk.Canvas(trow, width=int(92 * self.app.scale), height=int(52 * self.app.scale), bg=PANEL,
                           highlightthickness=0, cursor="hand2")
            cv.pack(side="left", padx=(0, 8))
            cv.bind("<Button-1>", lambda e, k=key: self._pick_theme(k))
            self.theme_btns[key] = cv
        ttk.Label(f, text="Цвет акцента", style="Panel.TLabel").pack(anchor="w")
        arow = ttk.Frame(f, style="Panel.TFrame")
        arow.pack(fill="x", pady=(4, 4))
        self.acc_cv = tk.Canvas(arow, width=int((len(ACCENTS) * 34 + 4) * self.app.scale), height=int(34 * self.app.scale),
                                bg=PANEL, highlightthickness=0, cursor="hand2")
        self.acc_cv.pack(side="left")
        self.acc_cv.bind("<Button-1>", self._acc_click)
        Button(arow, text="Свой цвет…", command=self._custom_accent).pack(side="left", padx=(10, 0))
        self.restart_note = ttk.Label(f, text="Тема и акцент применятся после перезапуска лаунчера.",
                                      style="PanelNote.TLabel", wraplength=440)
        self.restart_note.pack(anchor="w", pady=(2, 12))
        ttk.Label(f, text="Расположение элементов (применяется сразу)", style="Panel.TLabel").pack(anchor="w")
        lrow = ttk.Frame(f, style="Panel.TFrame")
        lrow.pack(fill="x", pady=(4, 0))
        self.lay_btns = {}
        for key, lay in LAYOUTS.items():
            cv = tk.Canvas(lrow, width=int(128 * self.app.scale), height=int(92 * self.app.scale), bg=PANEL,
                           highlightthickness=0, cursor="hand2")
            cv.pack(side="left", padx=(0, 8))
            cv.bind("<Button-1>", lambda e, k=key: self._pick_layout(k))
            self.lay_btns[key] = cv
        self._draw_themes()
        self._draw_accents()
        self._draw_layouts()

        # --- миры
        f = page("Миры")
        self.backup = tk.BooleanVar(value=bool(s.get("backup_worlds", True)))
        Checkbutton(f, variable=self.backup, bg=PANEL, text="Делать копию миров перед запуском сборки\n"
                    "(только если мир изменился)").pack(anchor="w", pady=(0, 10))
        ttk.Label(f, text="Сколько последних копий хранить для каждого мира", style="Panel.TLabel").pack(anchor="w")
        self.keep = tk.StringVar(value=str(int(s.get("backup_keep", 3))))
        Combobox(f, textvariable=self.keep, state="readonly", width=6, bg=PANEL,
                 values=["1", "2", "3", "5", "10"]).pack(anchor="w", pady=(3, 10))
        ttk.Label(f, text="Копия делается в фоне и пропускается, если мир больше 2 ГБ или на диске мало места.",
                  style="PanelNote.TLabel", wraplength=440, justify="left").pack(anchor="w", pady=(0, 12))
        Button(f, text="Восстановить мир из копии…", command=self._open_backups).pack(anchor="w")
        # одинаковый размер у всех вкладок: окно не прыгает при переключении
        mw = mh = 0
        for i, pg in enumerate(pages):
            tabs.select(i, animate=False)
            tabs.update_idletasks()
            mw, mh = max(mw, pg.winfo_reqwidth()), max(mh, pg.winfo_reqheight())
        tabs.grid_rowconfigure(1, minsize=mh)
        tabs.grid_columnconfigure(0, minsize=mw)
        tabs.select(0, animate=False)
        self.buttons(body, "Сохранить", self.save)

    # --- помощники вкладок
    def _check_now(self):
        self.upd_note.set("Проверяю…")
        self.app.check_updates_now(lambda t: self.winfo_exists() and self.upd_note.set(t))

    def _ram_changed(self, *_):
        v = int(round(self.ram.get() / 256.0) * 256)
        self.ram_label.configure(text="%.1f ГБ" % (v / 1024.0))

    def _preset_key(self):
        name = self.preset.get()
        for k, v in game.PRESETS.items():
            if v[0] == name:
                return k
        return "default"

    def _preset_changed(self):
        self.preset_note.configure(text=game.PRESETS[self._preset_key()][1])

    def _draw_themes(self):
        from .theme import THEMES
        sc = self.app.scale
        for key, cv in self.theme_btns.items():
            title, pal = THEMES[key]
            cv.delete("all")
            w, h = int(92 * sc), int(52 * sc)
            sel = key == self.theme_name
            widgets.RR(cv, 1, 1, w - 1, h - 1, 10, pal["BG"])
            widgets.RR(cv, 6, 6, w * 0.45, h - 6, 6, pal["PANEL"])
            widgets.RR(cv, w * 0.5, 6, w - 6, h * 0.45, 6, self.accent_val)
            if sel:
                cv.create_rectangle(1, 1, w - 1, h - 1, outline=self.accent_val, width=2)
            cv.create_text(w // 2, h - 11, text=title if len(title) < 13 else "Фиолетовая", fill="#c9ced3",
                           font=(FONT_NAME, 8))

    def _pick_theme(self, key):
        self.theme_name = key
        self._draw_themes()

    def _draw_accents(self):
        from .theme import ACCENTS
        sc = self.app.scale
        cv = self.acc_cv
        cv.delete("all")
        cols = [c for c, _ in ACCENTS]
        if self.accent_val.lower() not in cols:
            cols.append(self.accent_val.lower())
            cv.configure(width=int((len(cols) * 34 + 4) * sc))
        self._acc_cols = cols
        for i, c in enumerate(cols):
            x = int((4 + i * 34) * sc)
            r = int(12 * sc)
            cv.create_oval(x + 2, 3, x + 2 + 2 * r, 3 + 2 * r, fill=c, outline="")
            if c == self.accent_val.lower():
                cv.create_oval(x - 1, 0, x + 5 + 2 * r, 6 + 2 * r, outline="#e8ebee", width=2)

    def _acc_click(self, e):
        i = int((e.x / self.app.scale - 4) // 34)
        if 0 <= i < len(self._acc_cols):
            self.accent_val = self._acc_cols[i]
            self._draw_accents()
            self._draw_themes()

    def _custom_accent(self):
        from tkinter import colorchooser
        c = colorchooser.askcolor(color=self.accent_val, parent=self, title="Цвет акцента")
        if c and c[1]:
            self.accent_val = c[1].lower()
            self._draw_accents()
            self._draw_themes()

    def _draw_layouts(self):
        from .ui import LAYOUTS
        sc = self.app.scale
        for key, cv in self.lay_btns.items():
            lay = LAYOUTS[key]
            cv.delete("all")
            w, h = int(128 * sc), int(92 * sc)
            sel = key == self.layout_name
            widgets.RR(cv, 1, 1, w - 1, h - 17, 8, FIELD)
            pad = 5 if lay["m"] > 12 else 3
            widgets.RR(cv, pad + 1, pad + 1, w - pad - 1, pad + 9, 3, widgets.BTN)
            lw = int(w * (0.30 if lay["left"] > 220 else 0.24))
            top, bot = pad + 12, h - 17 - pad - 1
            lx = (w - pad - 1 - lw) if lay["mirror"] else pad + 1
            widgets.RR(cv, lx, top, lx + lw, bot, 3, widgets.BTN_HOVER)
            mx1 = pad + 1 if lay["mirror"] else lx + lw + 3
            mx2 = lx - 3 if lay["mirror"] else w - pad - 1
            widgets.RR(cv, mx1, top, mx2, top + (10 if lay["hero"] < 80 else 14), 3, self.accent_val)
            widgets.RR(cv, mx1, top + (14 if lay["hero"] < 80 else 18), mx2, bot, 3, widgets.PANEL)
            if sel:
                cv.create_rectangle(1, 1, w - 1, h - 17, outline=self.accent_val, width=2)
            cv.create_text(w // 2, h - 8, text=lay["title"], fill="#c9ced3", font=(FONT_NAME, 8))

    def _pick_layout(self, key):
        self.layout_name = key
        self.app.set_layout(key)
        self._draw_layouts()

    def _open_backups(self):
        from .backup import BackupsDialog
        BackupsDialog(self.app)

    def close(self):
        if not self.saved:
            self.app.set_layout(self.orig_layout)      # отмена — возвращаем прежнюю раскладку
        self.destroy()

    def save(self):
        s = self.app.store.settings
        s["ram_mb"] = int(round(self.ram.get() / 256.0) * 256)
        s["java_path"] = self.java.get().strip()
        s["use_zulu"] = bool(self.zulu.get())
        s["jvm_tuning"] = bool(self.tune.get())
        s["perf_preset"] = self._preset_key()
        s["check_updates"] = bool(self.upd.get())
        s["animations"] = bool(self.anim.get())
        widgets.set_animations(s["animations"])
        self.app.lava.set_enabled(s["animations"])
        s["jvm_args"] = self.jvm.get().strip()
        s["ms_client_id"] = self.cid.get().strip()
        changed = (s.get("theme") != self.theme_name) or (s.get("accent", "").lower() != self.accent_val.lower())
        s["theme"], s["accent"] = self.theme_name, self.accent_val
        s["layout"] = self.layout_name
        s["backup_worlds"] = bool(self.backup.get())
        try:
            s["backup_keep"] = max(1, int(self.keep.get()))
        except ValueError:
            s["backup_keep"] = 3
        self.app.store.save_settings()
        self.saved = True
        self.destroy()
        if changed:
            messagebox.showinfo("Оформление", "Тема и цвет акцента изменятся при следующем запуске лаунчера.",
                                parent=self.app)


class IconDialog(Dialog):
    """Выбор иконки сборки: блоки и лица мобов из файлов игры на этом компьютере."""

    def __init__(self, app):
        self.inst = app.current
        Dialog.__init__(self, app, "Иконка сборки")

    def build(self, body):
        from . import icons
        app = self.app
        size = icons.icon_size(app.scale)
        ttk.Label(body, text="Иконка для «%s»" % self.inst.name, style="Title.TLabel").pack(anchor="w")
        have = icons.extract(app.store, size)
        self.imgs = []
        if not have:
            note = ("Иконки берутся из файлов самой игры, поэтому сначала один раз запустите любую сборку "
                    "(или установите Pillow при запуске из исходников).")
            ttk.Label(body, text=note, style="Muted.TLabel", wraplength=420, justify="left").pack(anchor="w", pady=(8, 0))
        else:
            ttk.Label(body, text="Картинки вырезаны из вашей копии Minecraft и хранятся только у вас.",
                      style="Muted.TLabel", wraplength=420).pack(anchor="w", pady=(2, 10))
            grid = ttk.Frame(body)
            grid.pack(anchor="w")
            cols = 7
            for i, key in enumerate(have):
                img = tk.PhotoImage(master=app, file=icons.icon_file(app.store, key, size))
                self.imgs.append(img)
                b = tk.Button(grid, image=img, bd=0, relief="flat", bg=PANEL, activebackground=FIELD, cursor="hand2",
                              highlightthickness=2, highlightbackground=PANEL, padx=4, pady=4,
                              command=lambda k=key: self.pick(k))
                if key == self.inst.icon:
                    b.configure(highlightbackground=app.accent_color())
                b.grid(row=i // cols, column=i % cols, padx=3, pady=3)
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(14, 0))
        Button(row, text="Закрыть", command=self.close).pack(side="right")
        Button(row, text="Без иконки", command=lambda: self.pick("")).pack(side="right", padx=(0, 8))

    def pick(self, key):
        self.app.set_icon(self.inst, key)
        self.close()


def _plain(md, limit=1400):
    """Markdown из описания релиза — в простой текст."""
    import re
    out = []
    for line in (md or "").replace("\r", "").split("\n"):
        line = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)
        line = re.sub(r"^\s*[-*]\s+", "• ", line)
        line = re.sub(r"[*_`]{1,3}", "", line)
        line = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)
        out.append(line.rstrip())
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


class WelcomeDialog(Dialog):
    """Показывается один раз для каждой версии: что за версия, что нового, кто делал."""

    def __init__(self, app):
        Dialog.__init__(self, app, "Добро пожаловать")

    def build(self, body):
        from . import APP_NAME, APP_VERSION, changelog
        if getattr(self.app, "logo", None) is not None:
            tk.Label(body, image=self.app.logo, bd=0).pack(pady=(0, 6))
        ttk.Label(body, text="Добро пожаловать в %s!" % APP_NAME, style="Title.TLabel").pack()
        ttk.Label(body, text="Версия %s" % APP_VERSION, style="Muted.TLabel").pack(pady=(2, 12))
        ttk.Label(body, text="Что нового", font=(FONT_NAME, 10, "bold")).pack(anchor="w")
        for line in changelog.news_for(APP_VERSION):
            ttk.Label(body, text="•  " + line, wraplength=440, justify="left").pack(anchor="w", pady=(4, 0))
        tk.Frame(body, height=1, bg=LINE_COLOR).pack(fill="x", pady=14)
        ttk.Label(body, text="Разработчик: %s" % changelog.AUTHOR, font=(FONT_NAME, 10, "bold")).pack(anchor="w")
        ttk.Label(body, text=changelog.TAGLINE, style="Muted.TLabel", wraplength=440, justify="left").pack(anchor="w", pady=(2, 0))
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(16, 0))
        Button(row, text="Поехали", style="Accent.TButton", command=self.close).pack(side="right")


class UpdatedDialog(Dialog):
    """После обновления: счётчик версии «пробегает» до новой, затем плавно проявляется список нового."""

    def __init__(self, app, old):
        self.old = old
        self.alive = True
        Dialog.__init__(self, app, "Лаунчер обновлён")

    def build(self, body):
        import time
        from . import APP_VERSION, changelog
        from .theme import BG, ACCENT, ACCENT_HOVER, mix_hex
        self.bgc = PANEL
        self.items, self.older = changelog.updated_items(self.old, APP_VERSION)
        self.path = changelog.counter_path(self.old, APP_VERSION)
        ttk.Label(body, text="Обновлено до %s" % APP_VERSION, style="Title.TLabel").pack()
        self.counter = tk.Label(body, text=self.path[0], font=(FONT_NAME, 40, "bold"), fg=MUTED,
                                bg=self.cget("bg"), width=8)
        self.counter.pack(pady=(4, 10))
        tk.Frame(body, height=1, bg=LINE_COLOR).pack(fill="x", pady=(0, 10))
        ttk.Label(body, text="Что нового", font=(FONT_NAME, 10, "bold")).pack(anchor="w")
        self.lines, self.fg_end = [], FG
        for line in self.items:
            lb = tk.Label(body, text="•  " + line, wraplength=460, justify="left", anchor="w",
                          bg=self.cget("bg"), fg=self.cget("bg"), font=(FONT_NAME, 10))
            lb.pack(anchor="w", pady=(4, 0), fill="x")
            self.lines.append(lb)
        self.more_frame = ttk.Frame(body)
        self.more_frame.pack(fill="x")
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(16, 0))
        Button(row, text="Поехали", style="Accent.TButton", command=self.close).pack(side="right")
        if self.older:
            self.more_btn = Button(row, text="Что было в прошлых версиях", command=self.show_older)
            self.more_btn.pack(side="left")
        self.t0 = time.perf_counter()
        self.a_final, self.a_hi, self.a_mix = ACCENT_HOVER, ACCENT, mix_hex
        if widgets.ANIMATIONS:
            self.after(250, self.tick)
        else:
            self.finish()

    def show_older(self):
        self.more_btn.pack_forget()
        ttk.Label(self.more_frame, text="Раньше", font=(FONT_NAME, 10, "bold")).pack(anchor="w", pady=(12, 0))
        for line in self.older:
            ttk.Label(self.more_frame, text="•  " + line, wraplength=460, justify="left",
                      style="Muted.TLabel").pack(anchor="w", pady=(3, 0))
        self.update_idletasks()

    def finish(self):
        self.counter.configure(text=self.path[-1], fg=self.a_final)
        for lb in self.lines:
            lb.configure(fg=self.fg_end)

    def close(self):
        self.alive = False
        self.destroy()

    def tick(self):
        import time
        if not self.alive:
            return
        COUNT, GAP, FADE = 1.7, 0.16, 0.35
        t = time.perf_counter() - self.t0
        n = len(self.path) - 1
        if t < COUNT:
            k = t / COUNT
            idx = int(n * (1 - (1 - k) ** 3))                # быстро в начале, замедляется к концу
            self.counter.configure(text=self.path[min(n, idx)],
                                   fg=self.a_mix(MUTED, self.a_final, k))
        else:
            self.counter.configure(text=self.path[-1], fg=self.a_final)
            t2 = t - COUNT - 0.25
            done = True
            for i, lb in enumerate(self.lines):
                k = max(0.0, min(1.0, (t2 - i * GAP) / FADE))
                lb.configure(fg=self.a_mix(self.cget("bg"), self.fg_end, k))
                if k < 1.0:
                    done = False
            if done:
                return
        self.after(16, self.tick)


class UpdateDialog(Dialog):
    def __init__(self, app, info):
        self.info = info
        Dialog.__init__(self, app, "Обновление")

    def build(self, body):
        from . import APP_VERSION, updater
        i = self.info
        ttk.Label(body, text="Доступна версия %s" % i["version"], style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text="У вас установлена %s" % APP_VERSION, style="Muted.TLabel").pack(anchor="w", pady=(2, 10))
        notes = _plain(i.get("notes"))
        if notes:
            ttk.Label(body, text=notes, wraplength=440, justify="left").pack(anchor="w")
        auto = updater.can_self_update()
        if not auto:
            ttk.Label(body, text="Эта копия запущена не из установщика — страница релиза откроется в браузере.",
                      style="Muted.TLabel", wraplength=440).pack(anchor="w", pady=(10, 0))
        else:
            ttk.Label(body, text="Сборки и миры сохранятся. Лаунчер закроется и откроется снова сам.",
                      style="Muted.TLabel", wraplength=440).pack(anchor="w", pady=(10, 0))
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(16, 0))
        Button(row, text="Позже", command=self.close).pack(side="right")
        Button(row, text="Обновить сейчас" if auto else "Открыть страницу", style="Accent.TButton",
               command=self.go).pack(side="right", padx=(0, 8))

    def go(self):
        from . import updater
        self.destroy()
        if updater.can_self_update():
            self.app.install_update(self.info)
        else:
            webbrowser.open(self.info.get("page") or "")

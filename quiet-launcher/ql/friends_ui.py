"""Вкладка «Друзья» и окно с модами друга."""
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from . import APP_NAME, mods
from .dialogs import Dialog
from .friends import Friends, FriendsError, collect_projects
from .theme import PANEL, FONT as FONT_NAME
from .widgets import RoundButton as Button, RoundEntry as Entry, Switch as Checkbutton

REFRESH_MS = 60000


class FriendsTab(object):
    """Строит содержимое вкладки и живёт, пока открыто окно лаунчера."""

    def __init__(self, app, tree_factory):
        self.app = app
        self.api = Friends(app.store)
        self._tree = tree_factory
        self.frame = ttk.Frame(app.nb, style="Panel.TFrame", padding=(14, 8, 14, 12))
        self.data = None
        self.busy = False
        self.share = tk.BooleanVar(value=False)
        self.presence = tk.BooleanVar(value=False)
        self.code_var = tk.StringVar()
        self.nick_var = tk.StringVar()
        self.add_var = tk.StringVar()
        self.note = tk.StringVar(value="")
        self._build()
        self.frame.after(REFRESH_MS, self._tick)

    # --- построение
    def _build(self):
        for w in self.frame.winfo_children():
            w.destroy()
        if not self.api.registered:
            self._build_signup()
        else:
            self._build_main()

    def _build_signup(self):
        f = self.frame
        ttk.Label(f, text="Друзья в Quiet Launcher", style="Panel.TLabel", font=(FONT_NAME, 12, "bold")).pack(anchor="w")
        ttk.Label(f, wraplength=560, justify="left", style="PanelNote.TLabel", text=(
            "Добавляйте друзей по коду и смотрите, какие моды стоят у них, чтобы поставить такие же в один клик. "
            "Пароль не нужен: на сервер уходят только ник, код и список друзей. Список ваших модов и статус "
            "«в сети» отправляются, только если вы сами это включите. Файлы никому не передаются, "
            "моды ставятся из каталога Modrinth.")).pack(anchor="w", pady=(6, 12))
        ttk.Label(f, text="Ваш ник для друзей (2–20 символов)", style="Panel.TLabel").pack(anchor="w")
        row = ttk.Frame(f, style="Panel.TFrame")
        row.pack(fill="x", pady=(4, 8))
        acc = self.app.current_account()
        if not self.nick_var.get():
            self.nick_var.set(acc["name"] if acc and 2 <= len(acc["name"]) <= 20 else "")
        Entry(row, textvariable=self.nick_var, width=22).pack(side="left")
        Button(row, text="Создать профиль", style="Accent.TButton", command=self.signup).pack(side="left", padx=10)
        ttk.Label(f, textvariable=self.note, style="PanelNote.TLabel", wraplength=560).pack(anchor="w")

    def _build_main(self):
        f = self.frame
        p = self.api.profile
        head = ttk.Frame(f, style="Panel.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="Вы: %s" % p["nick"], style="Panel.TLabel", font=(FONT_NAME, 11, "bold")).pack(side="left")
        ttk.Label(head, text="  ваш код:", style="PanelNote.TLabel").pack(side="left")
        ttk.Label(head, text=p["code"], style="Panel.TLabel", font=(FONT_NAME, 11, "bold")).pack(side="left", padx=(4, 8))
        Button(head, text="Копировать", command=self.copy_code).pack(side="left")
        Button(head, text="Обновить", command=self.refresh).pack(side="right")
        sw = ttk.Frame(f, style="Panel.TFrame")
        sw.pack(fill="x", pady=(6, 4))
        Checkbutton(sw, variable=self.share, bg=PANEL, text="Показывать друзьям мои моды",
                    command=self.privacy_changed).pack(side="left", padx=(0, 18))
        Checkbutton(sw, variable=self.presence, bg=PANEL, text="Показывать, что я в лаунчере",
                    command=self.privacy_changed).pack(side="left")
        add = ttk.Frame(f, style="Panel.TFrame")
        add.pack(fill="x", pady=(4, 6))
        Entry(add, textvariable=self.add_var, width=16).pack(side="left")
        Button(add, text="Добавить по коду", command=self.add_friend).pack(side="left", padx=8)
        ttk.Label(add, textvariable=self.note, style="PanelNote.TLabel").pack(side="left", padx=4)
        row = ttk.Frame(f, style="Panel.TFrame")
        row.pack(side="bottom", fill="x", pady=(8, 0))
        Button(row, text="Принять", command=lambda: self.answer(True)).pack(side="left")
        Button(row, text="Отклонить", command=lambda: self.answer(False)).pack(side="left", padx=6)
        Button(row, text="Моды друга", command=self.show_mods).pack(side="left")
        Button(row, text="Удалить", command=self.remove).pack(side="left", padx=6)
        Button(row, text="Выйти из профиля", command=self.leave).pack(side="right")
        box, self.tree = self._tree(f, [("name", "Ник", 260), ("state", "Состояние", 200)], 6)
        box.pack(fill="both", expand=True)
        self.tree.tag_configure("group", foreground="#8d949b")
        self._fill()

    # --- действия
    def _async(self, work, done, quiet=False):
        if self.busy:
            return
        self.busy = True

        def run():
            try:
                res, err = work(), None
            except FriendsError as e:
                res, err = None, e
            except Exception as e:                       # сеть не должна ронять лаунчер
                res, err = None, FriendsError("Не удалось связаться с сервером: %s" % e)
            self.app.post(lambda: self._finish(done, res, err, quiet))
        threading.Thread(target=run, daemon=True).start()

    def _finish(self, done, res, err, quiet):
        self.busy = False
        if err is not None:
            if not quiet:
                self.note.set(str(err))
            return
        done(res)

    def signup(self):
        nick = self.nick_var.get().strip()
        self.note.set("Создаю профиль…")
        self._async(lambda: self.api.register(nick), lambda r: (self.note.set(""), self._build(), self.refresh()))

    def on_show(self):
        if not self.api.registered:
            acc = self.app.current_account()
            if not self.nick_var.get() and acc and 2 <= len(acc["name"]) <= 20:
                self.nick_var.set(acc["name"])
            return
        self.refresh()

    def refresh(self):
        if not self.api.registered:
            return
        def done(r):
            self.data = r
            self.share.set(r["me"]["share_mods"])
            self.presence.set(r["me"]["presence"])
            self._fill()
            if r["me"]["share_mods"]:
                self._push_projects()
        self._async(self.api.overview, done, quiet=True)

    def _push_projects(self):
        proj = collect_projects(self.app.insts)
        threading.Thread(target=lambda: self._safe(lambda: self.api.update(projects=proj)), daemon=True).start()

    @staticmethod
    def _safe(fn):
        try:
            fn()
        except Exception:
            pass

    def privacy_changed(self):
        share, pres = bool(self.share.get()), bool(self.presence.get())
        proj = collect_projects(self.app.insts) if share else []
        self.busy = False
        self._async(lambda: self.api.update(share_mods=share, presence=pres, projects=proj),
                    lambda r: self.note.set("Сохранено"))

    def copy_code(self):
        self.app.clipboard_clear()
        self.app.clipboard_append(self.api.profile["code"])
        self.note.set("Код скопирован")

    def add_friend(self):
        code = self.add_var.get().strip().upper()
        if not code:
            return
        def done(r):
            self.add_var.set("")
            self.note.set("Вы друзья с %s" % r["nick"] if r.get("friends") else "Заявка отправлена: %s" % r.get("nick", ""))
            self.refresh()
        self._async(lambda: self.api.request_friend(code), done)

    def _selected(self):
        sel = self.tree.selection()
        if not sel or ":" not in sel[0]:
            return None, None
        kind, uid = sel[0].split(":", 1)
        return kind, uid

    def answer(self, accept):
        kind, uid = self._selected()
        if kind != "in":
            self.note.set("Выберите входящую заявку в списке")
            return
        block = False
        if not accept:
            block = messagebox.askyesno(APP_NAME, "Заблокировать этого пользователя, чтобы он больше не слал заявки?",
                                        parent=self.app)
        self._async(lambda: self.api.respond(uid, accept, block), lambda r: self.refresh())

    def remove(self):
        kind, uid = self._selected()
        if kind == "out":
            self._async(lambda: self.api.cancel(uid), lambda r: self.refresh())
        elif kind == "fr":
            if messagebox.askyesno(APP_NAME, "Удалить из друзей?", parent=self.app):
                self._async(lambda: self.api.remove(uid), lambda r: self.refresh())
        else:
            self.note.set("Выберите друга или отправленную заявку")

    def show_mods(self):
        kind, uid = self._selected()
        if kind != "fr":
            self.note.set("Выберите друга в списке")
            return
        name = self.tree.item(self.tree.selection()[0], "text").strip()
        FriendModsDialog(self.app, self.api, uid, name)

    def leave(self):
        if messagebox.askyesno(APP_NAME, "Удалить профиль «Друзья»?\n\nДрузья, заявки и ваш код будут удалены "
                                         "с сервера безвозвратно.", parent=self.app):
            def done(_r):
                self.data = None
                self.note.set("")
                self._build()
            self._async(self.api.delete_account, done)

    # --- отображение
    def _fill(self):
        if not self.api.registered or not hasattr(self, "tree"):
            return
        t = self.tree
        t.delete(*t.get_children())
        d = self.data or {"friends": [], "incoming": [], "outgoing": []}
        if d["incoming"]:
            t.insert("", "end", iid="g1", text="  Заявки в друзья", values=("",), tags=("group",), open=True)
            for u in d["incoming"]:
                t.insert("g1", "end", iid="in:" + u["id"], text="  " + u["nick"], values=("хочет дружить",))
        t.insert("", "end", iid="g2", text="  Друзья (%d)" % len(d["friends"]), values=("",), tags=("group",), open=True)
        for u in d["friends"]:
            state = (u["status"] or "в лаунчере") if u["online"] else "не в сети"
            if u["shares"]:
                state += "  ·  моды открыты"
            t.insert("g2", "end", iid="fr:" + u["id"], text="  " + u["nick"], values=(state,))
        if not d["friends"]:
            t.insert("g2", "end", text="  Пока никого — добавьте друга по его коду", values=("",))
        if d["outgoing"]:
            t.insert("", "end", iid="g3", text="  Отправленные заявки", values=("",), tags=("group",), open=True)
            for u in d["outgoing"]:
                t.insert("g3", "end", iid="out:" + u["id"], text="  " + u["nick"], values=("ждёт ответа",))

    def _tick(self):
        try:
            if self.api.registered:
                if self.app.nb.sel == self.app.friends_index:
                    self.refresh()
                if self.presence.get():
                    st = "играет" if self.app.proc is not None else "в лаунчере"
                    threading.Thread(target=lambda: self._safe(lambda: self.api.heartbeat(st)), daemon=True).start()
        finally:
            self.frame.after(REFRESH_MS, self._tick)


class FriendModsDialog(Dialog):
    def __init__(self, app, api, uid, nick):
        self.api, self.uid, self.nick = api, uid, nick
        self.items = []
        Dialog.__init__(self, app, "Моды друга")

    def build(self, body):
        from .ui import _tree
        ttk.Label(body, text="Проекты Modrinth: %s" % self.nick, style="Title.TLabel").pack(anchor="w")
        self.info = ttk.Label(body, text="Загружаю…", style="Muted.TLabel", wraplength=480)
        self.info.pack(anchor="w", pady=(2, 8))
        box, self.tree = _tree(body, [("title", "Название", 320), ("kind", "Тип", 120)], 10)
        self.tree.configure(selectmode="extended")
        box.pack(fill="both", expand=True)
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(12, 0))
        Button(row, text="Закрыть", command=self.close).pack(side="right")
        Button(row, text="Установить выбранные в текущую сборку", style="Accent.TButton",
               command=self.install).pack(side="right", padx=(0, 8))

        def work():
            try:
                r, err = self.api.projects_of(self.uid), None
            except Exception as e:
                r, err = None, e
            self.app.post(lambda: self._loaded(r, err))
        threading.Thread(target=work, daemon=True).start()

    def _loaded(self, r, err):
        if not self.winfo_exists():
            return
        if err is not None:
            self.info.configure(text=str(err))
            return
        if not r.get("shared"):
            self.info.configure(text="Друг не открыл список модов. Он включается в его вкладке «Друзья».")
            return
        self.items = r["projects"]
        self.info.configure(text="Выберите проекты и нажмите кнопку. Ставятся последние версии под вашу сборку.")
        for i, p in enumerate(self.items):
            self.tree.insert("", "end", iid=str(i), text="  " + p.get("title", p["id"]),
                             values=(mods.KINDS.get(p.get("kind"), mods.KINDS["mod"])[2],))

    def install(self):
        app = self.app
        inst = app.current
        picked = [self.items[int(i)] for i in self.tree.selection()]
        if not picked:
            return
        if not inst:
            messagebox.showinfo(APP_NAME, "Сначала выберите сборку слева.", parent=self)
            return
        packs = [p for p in picked if p.get("kind") == "modpack"]
        rest = [p for p in picked if p.get("kind") != "modpack"]
        if packs and not rest:
            messagebox.showinfo(APP_NAME, "Сборки ставятся из каталога (раздел «Сборки»).", parent=self)
            return
        self.close()

        def work(cancel):
            done, failed = 0, []
            for p in rest:
                kind = p.get("kind") or "mod"
                if kind == "mod" and inst.loader == "vanilla":
                    failed.append(p.get("title", ""))
                    continue
                try:
                    done += len(mods.install_mod(inst, p["id"], p.get("title", ""), app.log, cancel, kind=kind))
                except mods.ModError as e:
                    app.log("Пропущено «%s»: %s" % (p.get("title", ""), e))
                    failed.append(p.get("title", ""))
            return done, failed

        def finished(r):
            app.refresh_installed()
            app.set_status("Установлено: %d, пропущено: %d" % (r[0], len(r[1])))
        app.run_task(work, finished, "Установка модов друга")

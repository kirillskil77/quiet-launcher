"""Резервные копии миров: перед запуском сборки, в фоне, только если мир изменился."""
import json
import os
import shutil
import threading
import time
import zipfile

MAX_WORLD_BYTES = 2 * 1024 ** 3        # мир больше — не копируем, а предупреждаем
MIN_FREE_EXTRA = 300 * 1024 ** 2       # запас свободного места сверх размера мира
SKIP_FILES = ("session.lock",)


def saves_dir(inst):
    return os.path.join(inst.game_dir, "saves")


def backups_dir(inst):
    return os.path.join(inst.folder, "backups")


def list_worlds(inst):
    root = saves_dir(inst)
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    return [n for n in names if os.path.isfile(os.path.join(root, n, "level.dat"))]


def world_stats(path):
    """(число файлов, размер, самое позднее изменение) — отпечаток состояния мира."""
    count = size = 0
    newest = 0.0
    for base, _dirs, files in os.walk(path):
        for f in files:
            if f in SKIP_FILES:
                continue
            try:
                st = os.stat(os.path.join(base, f))
            except OSError:
                continue
            count += 1
            size += st.st_size
            newest = max(newest, st.st_mtime)
    return count, size, newest


def _state_file(wdir):
    return os.path.join(wdir, "state.json")


def _read_state(wdir):
    try:
        with open(_state_file(wdir), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def list_backups(inst, world=None):
    """[(мир, файл, время, размер)] от новых к старым."""
    out = []
    root = backups_dir(inst)
    try:
        worlds = [world] if world else sorted(os.listdir(root))
    except OSError:
        return out
    for w in worlds:
        wdir = os.path.join(root, w)
        try:
            files = os.listdir(wdir)
        except OSError:
            continue
        for f in files:
            if f.endswith(".zip"):
                p = os.path.join(wdir, f)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                out.append((w, p, st.st_mtime, st.st_size))
    out.sort(key=lambda t: t[2], reverse=True)
    return out


def backup_world(inst, name, keep=3, log=None):
    """Копирует один мир. Возвращает строку-результат: 'saved' / 'same' / 'big' / 'nospace' / 'error'."""
    src = os.path.join(saves_dir(inst), name)
    wdir = os.path.join(backups_dir(inst), name)
    count, size, newest = world_stats(src)
    sig = [count, size, round(newest, 2)]
    if _read_state(wdir).get("sig") == sig:
        return "same"
    if size > MAX_WORLD_BYTES:
        return "big"
    try:
        os.makedirs(wdir, exist_ok=True)
        if shutil.disk_usage(wdir).free < size + MIN_FREE_EXTRA:
            return "nospace"
        stamp = time.strftime("%Y%m%d-%H%M%S")
        final = os.path.join(wdir, stamp + ".zip")
        tmp = final + ".part"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=3) as z:
            for base, _dirs, files in os.walk(src):
                for f in files:
                    if f in SKIP_FILES:
                        continue
                    full = os.path.join(base, f)
                    try:
                        z.write(full, os.path.join(name, os.path.relpath(full, src)))
                    except OSError:
                        continue                  # файл занят игрой или пропал — остальное сохраняем
        os.replace(tmp, final)
        with open(_state_file(wdir), "w", encoding="utf-8") as f:
            json.dump({"sig": sig}, f)
        old = sorted(x for x in os.listdir(wdir) if x.endswith(".zip"))
        for x in old[:-max(1, int(keep))]:
            try:
                os.remove(os.path.join(wdir, x))
            except OSError:
                pass
        return "saved"
    except Exception as e:                        # копия — не повод ронять запуск
        if log:
            log("Копия мира «%s» не удалась: %s" % (name, e))
        return "error"


def backup_all(inst, keep=3, log=None):
    res = {}
    for name in list_worlds(inst):
        res[name] = backup_world(inst, name, keep, log)
    return res


def backup_in_background(inst, keep, log):
    """Запускает копирование и пишет итог в журнал. Вызывается до старта игры."""
    def work():
        try:
            res = backup_all(inst, keep, log)
        except Exception as e:
            log("Копирование миров: %s" % e)
            return
        saved = [n for n, r in res.items() if r == "saved"]
        if saved:
            log("Копии миров сохранены: %s." % ", ".join(saved))
        for n, r in res.items():
            if r == "big":
                log("Мир «%s» больше 2 ГБ — копию не делаю." % n)
            elif r == "nospace":
                log("Мир «%s»: мало места на диске, копию не делаю." % n)
    t = threading.Thread(target=work, daemon=True)
    t.start()
    return t


def restore(inst, backup_path):
    """Распаковывает копию рядом с миром под новым именем — существующие миры не трогаем.
    Возвращает имя новой папки."""
    world = os.path.basename(os.path.dirname(backup_path))
    stamp = time.strftime("%Y-%m-%d %H-%M", time.localtime(os.path.getmtime(backup_path)))
    root = saves_dir(inst)
    os.makedirs(root, exist_ok=True)
    target, n = "%s (копия %s)" % (world, stamp), 1
    while os.path.exists(os.path.join(root, target)):
        n += 1
        target = "%s (копия %s) %d" % (world, stamp, n)
    dest = os.path.join(root, target)
    real_dest = os.path.realpath(dest)
    with zipfile.ZipFile(backup_path) as z:
        for info in z.infolist():
            parts = info.filename.replace("\\", "/").split("/", 1)
            rel = parts[1] if len(parts) > 1 else ""
            if not rel:
                continue
            out = os.path.realpath(os.path.join(dest, rel))
            if not (out == real_dest or out.startswith(real_dest + os.sep)):
                raise ValueError("Небезопасный путь в копии: " + info.filename)
            if info.filename.endswith("/"):
                os.makedirs(out, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with z.open(info) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
    return target


def human_size(n):
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024 or unit == "ГБ":
            return ("%d %s" % (n, unit)) if unit == "Б" else ("%.1f %s" % (n, unit))
        n /= 1024.0


class BackupsDialog(object):
    """Окно «Резервные копии миров» — создаётся лениво, чтобы модуль грузился без tkinter."""

    def __new__(cls, app):
        import tkinter as tk
        from tkinter import ttk, messagebox
        from .dialogs import Dialog
        from .widgets import RoundButton as Button
        from . import theme

        class _Dlg(Dialog):
            def __init__(self, app):
                Dialog.__init__(self, app, "Резервные копии миров")

            def build(self, body):
                inst = self.app.current
                self.inst = inst
                if not inst:
                    ttk.Label(body, text="Сначала выберите сборку.").pack()
                    Button(body, text="Закрыть", command=self.close).pack(pady=(12, 0))
                    return
                ttk.Label(body, text="Сборка: " + inst.name, style="Title.TLabel").pack(anchor="w")
                ttk.Label(body, text="Восстановление создаёт новый мир рядом со старым — ничего не перезаписывается.",
                          style="Muted.TLabel", wraplength=480).pack(anchor="w", pady=(2, 8))
                cols = ("world", "date", "size")
                self.tree = ttk.Treeview(body, columns=cols, show="headings", height=8)
                for c, t, w in (("world", "Мир", 220), ("date", "Дата копии", 150), ("size", "Размер", 80)):
                    self.tree.heading(c, text=t)
                    self.tree.column(c, width=w, anchor="w")
                self.tree.pack(fill="both", expand=True)
                self.items = {}
                self.fill()
                row = ttk.Frame(body)
                row.pack(fill="x", pady=(12, 0))
                Button(row, text="Закрыть", command=self.close).pack(side="right")
                Button(row, text="Восстановить", style="Accent.TButton", command=self.do_restore).pack(side="right", padx=(0, 8))
                Button(row, text="Сделать копию сейчас", command=self.now).pack(side="left")

            def fill(self):
                self.tree.delete(*self.tree.get_children())
                self.items = {}
                for w, p, t, sz in list_backups(self.inst):
                    iid = self.tree.insert("", "end", values=(w, time.strftime("%d.%m.%Y %H:%M", time.localtime(t)),
                                                              human_size(sz)))
                    self.items[iid] = p
                if not self.items:
                    self.tree.insert("", "end", values=("Копий пока нет", "", ""))

            def now(self):
                keep = int(self.app.store.settings.get("backup_keep", 3))
                res = backup_all(self.inst, keep, self.app.log)
                self.fill()
                if not res:
                    messagebox.showinfo("Копии", "В этой сборке пока нет миров.", parent=self)

            def do_restore(self):
                sel = self.tree.selection()
                if not sel or sel[0] not in self.items:
                    return
                try:
                    name = restore(self.inst, self.items[sel[0]])
                except Exception as e:
                    messagebox.showerror("Копии", "Не удалось восстановить: %s" % e, parent=self)
                    return
                messagebox.showinfo("Копии", "Готово. В игре появится мир «%s»." % name, parent=self)

        return _Dlg(app)

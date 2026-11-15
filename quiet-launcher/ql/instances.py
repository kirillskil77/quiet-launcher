"""Сборки: у каждой своя папка с игрой, модами, сохранениями и настройками."""
import os
import shutil

from .util import read_json, write_json, slugify

LOADERS = ["vanilla", "fabric", "quilt", "forge", "neoforge"]
LOADER_TITLES = {"vanilla": "Без модов", "fabric": "Fabric", "quilt": "Quilt",
                 "forge": "Forge", "neoforge": "NeoForge"}

_FIELDS = {
    "name": "",
    "mc_version": "",
    "loader": "vanilla",
    "loader_version": "",
    "version_id": "",      # id версии, с которой реально запускаем (после установки загрузчика)
    "ram_mb": 0,           # 0 = общая настройка
    "java_path": "",
    "jvm_args": "",
    "mods": [],            # [{project_id, version_id, filename, title}]
    "icon": "",            # ключ из icons.ICONS или пусто
    "last_played": 0,      # время последнего запуска (unix)
}


class Instance:
    def __init__(self, folder, data=None):
        self.folder = folder
        data = data or {}
        for k, v in _FIELDS.items():
            setattr(self, k, data.get(k, [] if k == "mods" else v))

    @property
    def dir(self):
        return self.folder

    @property
    def game_dir(self):
        return os.path.join(self.folder, "minecraft")

    @property
    def mods_dir(self):
        return os.path.join(self.game_dir, "mods")

    @property
    def natives_dir(self):
        return os.path.join(self.folder, "natives")

    @property
    def slug(self):
        return os.path.basename(self.folder)

    def to_dict(self):
        return {k: getattr(self, k) for k in _FIELDS}

    def save(self):
        write_json(os.path.join(self.folder, "instance.json"), self.to_dict())

    def last_played_text(self, now=None):
        import time
        ts = self.last_played or 0
        if not ts:
            return "ещё не запускалась"
        now = now or time.time()
        day = lambda t: time.strftime("%Y%m%d", time.localtime(t))
        if day(ts) == day(now):
            return "сегодня, " + time.strftime("%H:%M", time.localtime(ts))
        if day(ts) == day(now - 86400):
            return "вчера, " + time.strftime("%H:%M", time.localtime(ts))
        return time.strftime("%d.%m.%Y", time.localtime(ts))

    def title(self):
        t = LOADER_TITLES.get(self.loader, self.loader)
        if self.loader == "vanilla":
            return "%s · %s" % (self.mc_version, t)
        extra = " " + self.loader_version if self.loader_version else ""
        return "%s · %s%s" % (self.mc_version, t, extra)


def list_instances(store):
    out = []
    for d in sorted(os.listdir(store.instances), key=str.lower):
        folder = os.path.join(store.instances, d)
        data = read_json(os.path.join(folder, "instance.json"))
        if data:
            out.append(Instance(folder, data))
    return out


def _unique_folder(store, name):
    base = slugify(name)
    folder = os.path.join(store.instances, base)
    n = 2
    while os.path.exists(folder):
        folder = os.path.join(store.instances, "%s (%d)" % (base, n))
        n += 1
    return folder


def create_instance(store, name, mc_version, loader="vanilla", loader_version=""):
    name = name.strip()
    if not name:
        raise ValueError("Укажите название сборки")
    inst = Instance(_unique_folder(store, name), {
        "name": name, "mc_version": mc_version, "loader": loader, "loader_version": loader_version,
    })
    os.makedirs(inst.game_dir, exist_ok=True)
    inst.save()
    return inst


def delete_instance(inst):
    shutil.rmtree(inst.folder, ignore_errors=True)


def duplicate_instance(store, inst, new_name):
    folder = _unique_folder(store, new_name)
    shutil.copytree(inst.folder, folder, ignore=shutil.ignore_patterns("natives"))
    copy = Instance(folder, inst.to_dict())
    copy.name = new_name.strip() or inst.name + " (копия)"
    copy.save()
    return copy

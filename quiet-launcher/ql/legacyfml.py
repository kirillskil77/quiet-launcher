"""Forge для Minecraft 1.5.2 при первом запуске качает deobfuscation_data_1.5.2.zip с files.minecraftforge.net,
а этого адреса больше нет (отдаётся страница 404 с чужой контрольной суммой). Кладём файл заранее."""
import hashlib
import os
import shutil

from .util import download

# версия игры -> (имя файла, sha1, который ждёт Forge)
DATA = {"1.5.2": ("deobfuscation_data_1.5.2.zip", "446e55cd986582c70fcf12cb27bc00114c5adfd9")}

MIRRORS = [
    "https://maven.minecraftforge.net/fmllibs/%s",
    "https://web.archive.org/web/2020id_/http://files.minecraftforge.net/fmllibs/%s",
    "https://web.archive.org/web/2016id_/http://files.minecraftforge.net/fmllibs/%s",
    "https://web.archive.org/web/2019id_/https://files.minecraftforge.net/fmllibs/%s",
]


def sha1_of(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def lib_dirs(inst, appdata=None):
    """Где Forge 1.5.2 ищет lib: у старых версий игра игнорирует папку сборки и берёт общий .minecraft."""
    appdata = appdata if appdata is not None else os.environ.get("APPDATA")
    dirs = [os.path.join(inst.game_dir, "lib")]
    if appdata:
        dirs.append(os.path.join(appdata, ".minecraft", "lib"))
    return dirs


def _local_copies(appdata):
    """Файл мог остаться от других лаунчеров (общая папка .minecraft, TLauncher)."""
    if not appdata:
        return
    for root in (os.path.join(appdata, ".minecraft"), os.path.join(appdata, ".tlauncher")):
        base_depth = root.rstrip(os.sep).count(os.sep)
        for cur, dirs, files in os.walk(root):
            if cur.count(os.sep) - base_depth >= 6:
                dirs[:] = []
            for name in files:
                if name == "deobfuscation_data_1.5.2.zip":
                    yield os.path.join(cur, name)


def ensure(inst, mc, store, log=None, cancel=None, appdata=None):
    """Кладёт deobfuscation_data в папки lib. Возвращает True, если файл на месте."""
    if mc not in DATA:
        return True
    name, sha1 = DATA[mc]
    appdata = appdata if appdata is not None else os.environ.get("APPDATA")
    targets = [os.path.join(d, name) for d in lib_dirs(inst, appdata)]
    if all(os.path.isfile(t) and sha1_of(t) == sha1 for t in targets):
        return True
    cache = os.path.join(store.cache, "fmllibs", name)
    source = cache if os.path.isfile(cache) and sha1_of(cache) == sha1 else None
    if source is None:
        for cand in _local_copies(appdata):
            if sha1_of(cand) == sha1:
                source = cand
                break
    if source is None:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        for m in MIRRORS:
            try:
                download(m % name, cache, sha1=sha1, cancel=cancel, retries=1)
                source = cache
                break
            except Exception as e:
                if log:
                    log("Не удалось скачать %s с %s: %s" % (name, m.split("/")[2], e))
    if source is None:
        return False
    for t in targets:
        try:
            if not (os.path.isfile(t) and sha1_of(t) == sha1):
                os.makedirs(os.path.dirname(t), exist_ok=True)
                shutil.copyfile(source, t)
        except OSError as e:
            if log:
                log("Не удалось положить %s: %s" % (t, e))
    if source != cache and not os.path.isfile(cache):
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        shutil.copyfile(source, cache)
    return True

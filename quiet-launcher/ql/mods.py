"""Моды (Modrinth) и импорт сборок .mrpack."""
import hashlib
import json
import os
import shutil
import threading
import time
import urllib.parse
import zipfile

from . import endpoints
from .instances import create_instance, delete_instance
from .util import get_json, download, download_many, safe_join


class ModError(Exception):
    pass


LOADER_CATEGORIES = {"fabric": ["fabric"], "quilt": ["quilt", "fabric"],
                     "forge": ["forge"], "neoforge": ["neoforge"]}


# Что можно ставить из каталога: тип -> (название, папка внутри сборки, подпись в списке)
KINDS = {
    "mod": ("Моды", "mods", "Мод"),
    "resourcepack": ("Ресурс-паки", "resourcepacks", "Ресурс-пак"),
    "shader": ("Шейдеры", "shaderpacks", "Шейдер"),
    "modpack": ("Сборки", None, "Сборка"),
}

_cache = {}
_cache_lock = threading.Lock()


def _cached(key, fn, ttl=600):
    """Один и тот же запрос в течение нескольких минут не гоняем по сети."""
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = fn()
    with _cache_lock:
        if len(_cache) > 200:
            _cache.clear()
        _cache[key] = (now, value)
    return value


def entry_kind(entry):
    return entry.get("kind") if entry.get("kind") in KINDS else "mod"


def entry_dir(inst, entry):
    return os.path.join(inst.game_dir, KINDS[entry_kind(entry)][1] or "mods")


def search(query, mc, loader, limit=30, offset=0, kind="mod"):
    facets = [["project_type:%s" % kind]]
    if kind != "modpack":                               # сборка приносит свою версию игры и загрузчик
        facets.append(["versions:%s" % mc])
    cats = LOADER_CATEGORIES.get(loader) if kind == "mod" else None
    if cats:
        facets.append(["categories:%s" % c for c in cats])
    params = {"query": query, "facets": json.dumps(facets), "limit": limit, "offset": offset,
              "index": "relevance" if query else "downloads"}
    url = "%s/search?%s" % (endpoints.MODRINTH_API, urllib.parse.urlencode(params))
    return _cached(("search", url), lambda: get_json(url).get("hits", []))


def project_info(project_id):
    """Страница проекта: описание, скриншоты, ссылки."""
    url = "%s/project/%s" % (endpoints.MODRINTH_API, urllib.parse.quote(project_id))
    return _cached(("project", url), lambda: get_json(url), ttl=1800)


def fetch_image(url, cache_dir, cancel=None):
    """Скачивает картинку в кеш (один раз) и возвращает путь."""
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()[:6] or ".img"
    path = os.path.join(cache_dir, "images", hashlib.sha1(url.encode("utf-8")).hexdigest() + ext)
    download(url, path, cancel=cancel, retries=2)
    return path


def latest_version(project_id, mc, loader):
    params = {"game_versions": json.dumps([mc])}
    if loader:
        params["loaders"] = json.dumps(LOADER_CATEGORIES.get(loader, [loader]))
    url = "%s/project/%s/version?%s" % (endpoints.MODRINTH_API, urllib.parse.quote(project_id),
                                        urllib.parse.urlencode(params))
    versions = get_json(url)
    if not versions:
        return None
    for v in versions:
        if v.get("version_type") == "release":
            return v
    return versions[0]


def _primary_file(version):
    files = version.get("files") or []
    for f in files:
        if f.get("primary"):
            return f
    if not files:
        raise ModError("У версии мода нет файлов")
    return files[0]


def _project_title(project_id):
    try:
        return get_json("%s/project/%s" % (endpoints.MODRINTH_API, urllib.parse.quote(project_id))).get("title", project_id)
    except Exception:
        return project_id


def install_mod(inst, project_id, title="", log=None, cancel=None, _seen=None, kind="mod"):
    """Ставит мод, ресурс-пак или шейдер (и обязательные зависимости модов).
    Возвращает список записей о новых файлах."""
    if kind == "mod" and inst.loader == "vanilla":
        raise ModError("Для сборки без загрузчика моды недоступны")
    seen = _seen if _seen is not None else set()
    if project_id in seen or any(m.get("project_id") == project_id for m in inst.mods):
        return []
    seen.add(project_id)
    what = KINDS[kind][2].lower()
    v = latest_version(project_id, inst.mc_version, inst.loader if kind == "mod" else None)
    if not v:
        raise ModError("Нет подходящей версии (%s) для Minecraft %s%s" % (
            what, inst.mc_version, " / " + inst.loader if kind == "mod" else ""))
    f = _primary_file(v)
    filename = os.path.basename(f["filename"])
    dest = safe_join(os.path.join(inst.game_dir, KINDS[kind][1]), filename)
    download(f["url"], dest, (f.get("hashes") or {}).get("sha1"), f.get("size"), cancel=cancel)
    entry = {"project_id": project_id, "version_id": v["id"], "filename": filename,
             "title": title or _project_title(project_id)}
    if kind != "mod":
        entry["kind"] = kind
    inst.mods.append(entry)
    inst.save()
    if log:
        log("Установлено (%s): %s" % (what, entry["title"]))
    done = [entry]
    for dep in (v.get("dependencies") or []) if kind == "mod" else []:
        if dep.get("dependency_type") == "required" and dep.get("project_id"):
            try:
                done += install_mod(inst, dep["project_id"], "", log, cancel, seen)
            except ModError as e:
                if log:
                    log("Зависимость пропущена: %s" % e)
    return done


def remove_mod(inst, entry):
    try:
        os.remove(safe_join(entry_dir(inst, entry), entry["filename"]))
    except OSError:
        pass
    inst.mods = [m for m in inst.mods if m is not entry and m.get("filename") != entry["filename"]]
    inst.save()


def add_local_file(inst, path):
    name = os.path.basename(path)
    os.makedirs(inst.mods_dir, exist_ok=True)
    shutil.copyfile(path, safe_join(inst.mods_dir, name))
    if not any(m.get("filename") == name for m in inst.mods):
        inst.mods.append({"project_id": "", "version_id": "", "filename": name, "title": name})
    inst.save()


def update_mods(inst, log=None, cancel=None):
    """Обновляет моды из Modrinth до последних версий. Возвращает число обновлённых."""
    changed = 0
    for entry in list(inst.mods):
        if not entry.get("project_id"):
            continue
        kind = entry_kind(entry)
        v = latest_version(entry["project_id"], inst.mc_version, inst.loader if kind == "mod" else None)
        if not v or v["id"] == entry.get("version_id"):
            continue
        f = _primary_file(v)
        filename = os.path.basename(f["filename"])
        folder = entry_dir(inst, entry)
        download(f["url"], safe_join(folder, filename),
                 (f.get("hashes") or {}).get("sha1"), f.get("size"), cancel=cancel)
        if filename != entry["filename"]:
            try:
                os.remove(safe_join(folder, entry["filename"]))
            except OSError:
                pass
        entry["filename"], entry["version_id"] = filename, v["id"]
        changed += 1
        if log:
            log("Обновлён: %s" % entry["title"])
    inst.save()
    return changed


def install_modpack(store, project_id, title="", log=None, progress=None, cancel=None):
    """Скачивает последнюю версию сборки с Modrinth и превращает её в новую сборку лаунчера."""
    url = "%s/project/%s/version" % (endpoints.MODRINTH_API, urllib.parse.quote(project_id))
    versions = get_json(url)
    if not versions:
        raise ModError("У этой сборки нет доступных версий")
    v = next((x for x in versions if x.get("version_type") == "release"), versions[0])
    files = [f for f in v.get("files", []) if f.get("filename", "").endswith(".mrpack")]
    if not files:
        raise ModError("В версии нет файла .mrpack")
    f = files[0]
    dest = safe_join(os.path.join(store.cache, "modpacks"), os.path.basename(f["filename"]))
    if progress:
        progress("Скачиваю сборку", 0, 0)
    download(f["url"], dest, (f.get("hashes") or {}).get("sha1"), f.get("size"), cancel=cancel)
    return import_mrpack(store, dest, log, progress, cancel)


def import_mrpack(store, path, log=None, progress=None, cancel=None):
    """Создаёт сборку из файла .mrpack (формат Modrinth)."""
    with zipfile.ZipFile(path) as zf:
        try:
            idx = json.loads(zf.read("modrinth.index.json").decode("utf-8"))
        except KeyError:
            raise ModError("В архиве нет modrinth.index.json — это не .mrpack")
        deps = idx.get("dependencies") or {}
        mc = deps.get("minecraft")
        if not mc:
            raise ModError("В сборке не указана версия Minecraft")
        loader, lv = "vanilla", ""
        for key, name in (("fabric-loader", "fabric"), ("quilt-loader", "quilt"),
                          ("neoforge", "neoforge"), ("forge", "forge")):
            if key in deps:
                loader, lv = name, deps[key]
                break
        inst = create_instance(store, idx.get("name") or os.path.splitext(os.path.basename(path))[0],
                               mc, loader, lv)
        try:
            tasks, mod_entries = [], []
            for f in idx.get("files", []):
                if (f.get("env") or {}).get("client") == "unsupported":
                    continue
                dest = safe_join(inst.game_dir, f["path"])
                tasks.append((f["downloads"][0], dest, (f.get("hashes") or {}).get("sha1"), f.get("fileSize")))
                if f["path"].replace("\\", "/").startswith("mods/"):
                    name = os.path.basename(f["path"])
                    mod_entries.append({"project_id": "", "version_id": "", "filename": name, "title": name})
            if log:
                log("Скачиваю файлы сборки: %d" % len(tasks))
            download_many(tasks, (lambda d, t: progress("Файлы сборки", d, t)) if progress else None, cancel)
            for prefix in ("overrides/", "client-overrides/"):
                for name in zf.namelist():
                    if name.startswith(prefix) and not name.endswith("/"):
                        dest = safe_join(inst.game_dir, name[len(prefix):])
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        with zf.open(name) as src, open(dest, "wb") as out:
                            shutil.copyfileobj(src, out)
            inst.mods = mod_entries
            inst.save()
        except BaseException:
            delete_instance(inst)
            raise
    return inst

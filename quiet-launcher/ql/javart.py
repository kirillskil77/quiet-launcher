"""Java: берём собственную сборку от Mojang (как официальный лаунчер) или подходящую системную."""
import glob
import os
import re
import shutil
import stat
import subprocess
import urllib.parse
import zipfile

from . import endpoints
from .util import (Cancelled, get_json, download, download_many, safe_join, os_name, os_arch,
                   hidden_window_flags, is_windows7)

ZULU_MAJOR = 21


class JavaError(Exception):
    pass


def runtime_platform():
    n, a = os_name(), os_arch()
    if n == "windows":
        return {"x86_64": "windows-x64", "arm64": "windows-arm64"}.get(a, "windows-x86")
    if n == "osx":
        return "mac-os-arm64" if a == "arm64" else "mac-os"
    return "linux" if a == "x86_64" else "linux-i386"


def java_exe(root):
    """java внутри папки среды. На macOS у Mojang она лежит в jre.bundle/Contents/Home."""
    name = "java.exe" if os_name() == "windows" else "java"
    for sub in ("", os.path.join("jre.bundle", "Contents", "Home"), os.path.join("Contents", "Home")):
        p = os.path.join(root, sub, "bin", name)
        if os.path.isfile(p):
            return p
    return os.path.join(root, "bin", name)


def ensure_runtime(store, component, log=None, progress=None, cancel=None):
    root = os.path.join(store.runtime, component)
    marker = os.path.join(root, ".ok")
    exe = java_exe(root)
    if os.path.isfile(marker) and os.path.isfile(exe):
        return exe
    if log:
        log("Скачиваю Java (%s)…" % component)
    index = get_json(endpoints.JAVA_RUNTIME_INDEX)
    entries = (index.get(runtime_platform()) or {}).get(component) or []
    if not entries:
        raise JavaError("Mojang не публикует Java «%s» для этой системы" % component)
    manifest = get_json(entries[0]["manifest"]["url"])
    tasks, links, execs = [], [], []
    for rel, info in manifest["files"].items():
        kind = info.get("type")
        if kind == "file":
            raw = info["downloads"]["raw"]
            dest = safe_join(root, rel)
            tasks.append((raw["url"], dest, raw["sha1"], raw["size"]))
            if info.get("executable"):
                execs.append(dest)
        elif kind == "link":
            links.append((rel, info.get("target", "")))
    cb = (lambda d, t: progress("Java", d, t)) if progress else None
    download_many(tasks, cb, cancel)
    for dest in execs:
        try:
            os.chmod(dest, os.stat(dest).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except OSError:
            pass
    for rel, target in links:
        path = safe_join(root, rel)
        if hasattr(os, "symlink") and not os.path.lexists(path):
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                os.symlink(target, path)
            except OSError:
                pass
    with open(marker, "w") as f:
        f.write(entries[0].get("version", {}).get("name", ""))
    if not os.path.isfile(exe):
        raise JavaError("После установки не найден %s" % exe)
    return exe


# ---------------------------------------------------------------- Java Zulu 21

def zulu_arch():
    return {"x86_64": "x64", "x86": "x86"}.get(os_arch())


def zulu_supported():
    return os_name() == "windows" and zulu_arch() is not None


def zulu_root(store):
    return os.path.join(store.runtime, "zulu-%d" % ZULU_MAJOR)


def _zulu_package():
    """(ссылка, sha256 или None). Сначала спрашиваем Azul, при сбое берём запасную ссылку."""
    arch = zulu_arch()
    try:
        params = {"java_version": ZULU_MAJOR, "os": "windows", "arch": arch, "archive_type": "zip",
                  "java_package_type": "jre", "javafx_bundled": "false", "latest": "true",
                  "availability_types": "CA", "release_status": "ga", "page_size": 1}
        pkg = get_json(endpoints.AZUL_API + "?" + urllib.parse.urlencode(params))[0]
        url, sha = pkg["download_url"], None
        if pkg.get("package_uuid"):
            try:
                sha = (get_json(endpoints.AZUL_API + pkg["package_uuid"]).get("sha256_hash") or "").lower() or None
            except Exception:
                pass
        return url, sha
    except Exception:
        return endpoints.ZULU_FALLBACK[arch], None


def _unpack_zip(zpath, root, cancel=None):
    """Распаковывает архив в root (верхнюю папку архива отбрасывает), сначала во временную папку."""
    tmp = root + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(zpath) as zf:
        infos = zf.infolist()
        tops = set(i.filename.split("/")[0] for i in infos)
        strip = len(tops) == 1 and all("/" in i.filename for i in infos)
        for info in infos:
            if cancel is not None and cancel.is_set():
                shutil.rmtree(tmp, ignore_errors=True)
                raise Cancelled()
            rel = info.filename.split("/", 1)[1] if strip else info.filename
            if not rel or info.is_dir():
                continue
            dest = safe_join(tmp, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with zf.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
    shutil.rmtree(root, ignore_errors=True)
    os.rename(tmp, root)


def ensure_zulu(store, log=None, progress=None, cancel=None):
    """Скачивает и ставит Java Zulu 21 в папку лаунчера. Возвращает путь к java.exe."""
    root = zulu_root(store)
    exe = java_exe(root)
    marker = os.path.join(root, ".ok")
    if os.path.isfile(marker) and os.path.isfile(exe):
        return exe
    if not zulu_supported():
        raise JavaError("Zulu 21 для этой системы не предусмотрена")
    if log:
        log("Скачиваю Java Zulu %d (один раз, около 50 МБ)…" % ZULU_MAJOR)
    url, sha = _zulu_package()
    zpath = os.path.join(store.cache, "zulu", url.rsplit("/", 1)[-1])
    cb = (lambda got, total: progress("Java Zulu %d, МБ" % ZULU_MAJOR, got >> 20, total >> 20)) if progress else None
    for attempt in (0, 1):
        download(url, zpath, retries=1, cancel=cancel, sha256=sha, on_bytes=cb)
        try:
            _unpack_zip(zpath, root, cancel)
            break
        except zipfile.BadZipFile:
            try:
                os.remove(zpath)
            except OSError:
                pass
            if attempt:
                raise JavaError("Архив Java повреждён, попробуйте позже")
    major = probe(exe) if os.path.isfile(exe) else None
    if not major or major < ZULU_MAJOR:
        shutil.rmtree(root, ignore_errors=True)
        raise JavaError("Скачанная Java Zulu не запускается на этой системе")
    with open(marker, "w") as f:
        f.write(url.rsplit("/", 1)[-1])
    return exe


# ---------------------------------------------------------------- системная Java

def parse_major(text):
    m = re.search(r'version "(\d+)(?:\.(\d+))?', text)
    if not m:
        return None
    major = int(m.group(1))
    if major == 1 and m.group(2):
        major = int(m.group(2))
    return major


def probe(path):
    try:
        p = subprocess.run([path, "-version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=20, creationflags=hidden_window_flags())
        return parse_major(p.stdout.decode("utf-8", "replace"))
    except Exception:
        return None


def _system_candidates():
    exe = "java.exe" if os_name() == "windows" else "java"
    cands = []
    jh = os.environ.get("JAVA_HOME")
    if jh:
        cands.append(os.path.join(jh, "bin", exe))
    w = shutil.which("java")
    if w:
        cands.append(w)
    if os_name() == "windows":
        for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            base = os.environ.get(env)
            if not base:
                continue
            for sub in ("Java", "Eclipse Adoptium", "Eclipse Foundation", "Zulu", "Microsoft", "BellSoft", "AdoptOpenJDK"):
                cands += glob.glob(os.path.join(base, sub, "*", "bin", exe))
    elif os_name() == "osx":
        for base in ("/Library/Java/JavaVirtualMachines", os.path.expanduser("~/Library/Java/JavaVirtualMachines")):
            cands += glob.glob(os.path.join(base, "*", "Contents", "Home", "bin", "java"))
        cands += glob.glob("/opt/homebrew/opt/openjdk*/bin/java") + glob.glob("/usr/local/opt/openjdk*/bin/java")
        cands += glob.glob("/opt/homebrew/Cellar/openjdk*/*/bin/java")
    else:
        for base in ("/usr/lib/jvm", "/usr/lib64/jvm", "/usr/java", os.path.expanduser("~/.sdkman/candidates/java")):
            cands += glob.glob(os.path.join(base, "*", "bin", "java"))
    return cands


def _probe_unique(cands, source=""):
    seen, out = set(), []
    for c in cands:
        key = os.path.normcase(os.path.abspath(c))
        if key in seen or not os.path.isfile(c):
            continue
        seen.add(key)
        major = probe(c)
        if major:
            out.append((c, major))
    return out


def find_system_javas():
    return _probe_unique(_system_candidates())


_SKIP_DIRS = {"assets", "libraries", "versions", "saves", "mods", "resourcepacks", "shaderpacks",
              "screenshots", "logs", "crash-reports", "config", "natives"}


def _scan(root, max_depth=7):
    """Ищет bin/java(.exe) внутри папки другого лаунчера, не заходя в тяжёлые папки игры."""
    exe = "java.exe" if os_name() == "windows" else "java"
    base_depth = root.rstrip("\\/").count(os.sep)
    for cur, dirs, files in os.walk(root):
        if cur.count(os.sep) - base_depth >= max_depth:
            dirs[:] = []
        dirs[:] = [d for d in dirs if d.lower() not in _SKIP_DIRS]
        if exe in files and os.path.basename(cur).lower() == "bin":
            yield os.path.join(cur, exe)


def detect_javas(store):
    """Все найденные Java: [{path, major, source}], новые первыми. Может занять несколько секунд."""
    found = []  # (путь, откуда)
    for d in sorted(glob.glob(os.path.join(store.runtime, "*"))):
        found.append((java_exe(d), "Лаунчер"))
    appdata = os.environ.get("APPDATA")
    if appdata:
        for sub in (os.path.join(".minecraft", "runtime"), ".tlauncher"):
            root = os.path.join(appdata, sub)
            if os.path.isdir(root):
                found += [(p, "Другой лаунчер") for p in _scan(root)]
    found += [(p, "Система") for p in _system_candidates()]
    seen, out = set(), []
    for path, source in found[:60]:
        key = os.path.normcase(os.path.abspath(path))
        if key in seen or not os.path.isfile(path):
            continue
        seen.add(key)
        major = probe(path)
        if major:
            out.append({"path": path, "major": major, "source": source})
    out.sort(key=lambda j: -j["major"])
    return out


def resolve_java(store, inst, version, log=None, progress=None, cancel=None):
    """Возвращает путь к java для запуска этой версии."""
    manual = inst.java_path or store.settings.get("java_path", "")
    if manual:
        if not os.path.isfile(manual):
            raise JavaError("Не найден файл Java: %s" % manual)
        return manual
    req = version.get("javaVersion") or {"component": "jre-legacy", "majorVersion": 8}
    need = int(req.get("majorVersion", 8))
    # Сначала Java от Mojang (быстро качается, обычно работает и на Windows 7). Если она не скачалась
    # или не запускается на этой системе — ставим Zulu 21 (для Minecraft 1.17+).
    zulu_ok = store.settings.get("use_zulu", True) and zulu_supported() and 16 <= need <= ZULU_MAJOR
    try:
        exe = ensure_runtime(store, req.get("component", "jre-legacy"), log, progress, cancel)
        if not zulu_ok or probe(exe):
            return exe
        problem = "Java от Mojang не запускается на этой системе"
    except Cancelled:
        raise
    except Exception as e:
        problem = "Java от Mojang недоступна (%s)" % e
    if zulu_ok:
        if log:
            log("%s, ставлю Java Zulu %d…" % (problem, ZULU_MAJOR))
        try:
            return ensure_zulu(store, log, progress, cancel)
        except Cancelled:
            raise
        except Exception as e:
            if log:
                log("Java Zulu недоступна (%s), ищу установленную…" % e)
    elif log:
        log("%s, ищу установленную…" % problem)
    for path, major in find_system_javas():
        if (need <= 8 and major == 8) or (need > 8 and major >= need):
            return path
    raise JavaError("Не удалось найти Java %d. Установите её или укажите путь в настройках." % need)

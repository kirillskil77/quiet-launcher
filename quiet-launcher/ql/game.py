"""Версии Minecraft: скачивание, правила библиотек, сборка команды запуска."""
import os
import re
import shutil
import subprocess
import threading
import zipfile

from . import legacyfml, APP_VERSION, endpoints, javart, loaders
from .util import (HttpError, get_json, download, download_many, read_json, write_json,
                   safe_join, os_name, os_arch, os_version, hidden_window_flags)


class GameError(Exception):
    pass


# ------------------------------------------------------------------ список версий

def get_manifest(store):
    cache = os.path.join(store.cache, "version_manifest.json")
    try:
        try:
            data = get_json(endpoints.VERSION_MANIFEST)
        except HttpError:
            data = get_json(endpoints.VERSION_MANIFEST_FALLBACK)
        write_json(cache, data)
        return data
    except HttpError:
        data = read_json(cache)
        if data:
            return data
        raise


def list_versions(store, snapshots=False):
    """Список id версий Minecraft, новые первыми."""
    out = []
    for v in get_manifest(store)["versions"]:
        if v["type"] == "release" or (snapshots and v["type"] == "snapshot"):
            out.append(v["id"])
    return out


def ensure_vanilla_json(store, mc):
    path = os.path.join(store.versions, mc, mc + ".json")
    if read_json(path):
        return  # уже скачано — интернет не нужен
    for v in get_manifest(store)["versions"]:
        if v["id"] == mc:
            download(v["url"], path, v.get("sha1"))
            return
    raise GameError("Версия Minecraft %s не найдена" % mc)


# ------------------------------------------------------------------ правила

def current_env():
    return {"os": os_name(), "arch": os_arch(), "os_version": os_version()}


def _rule_match(rule, env, features):
    o = rule.get("os")
    if o:
        if "name" in o and o["name"] != env["os"]:
            return False
        if "arch" in o and o["arch"] != env["arch"]:
            return False
        if "version" in o and not re.search(o["version"], env["os_version"]):
            return False
    f = rule.get("features")
    if f:
        for k, v in f.items():
            if bool(features.get(k, False)) != bool(v):
                return False
    return True


def rules_allow(rules, env, features=None):
    if not rules:
        return True
    features = features or {}
    allowed = False
    for r in rules:
        if _rule_match(r, env, features):
            allowed = r.get("action") == "allow"
    return allowed


# ------------------------------------------------------------------ json версии

def _merge(parent, child):
    out = dict(parent)
    for k, v in child.items():
        if k not in ("libraries", "arguments", "inheritsFrom"):
            out[k] = v
    out["libraries"] = list(child.get("libraries", [])) + list(parent.get("libraries", []))
    pa, ca = parent.get("arguments"), child.get("arguments")
    if pa or ca:
        out["arguments"] = {kind: list((pa or {}).get(kind, [])) + list((ca or {}).get(kind, []))
                            for kind in ("game", "jvm")}
    return out


def load_version(store, vid):
    data = read_json(os.path.join(store.versions, vid, vid + ".json"))
    if data is None:
        raise GameError("Нет файла версии %s" % vid)
    parent_id = data.get("inheritsFrom")
    if parent_id:
        parent = load_version(store, parent_id)
        merged = _merge(parent, data)
        merged["_jar_id"] = data.get("jar") or parent["_jar_id"]
    else:
        merged = dict(data)
        merged["_jar_id"] = data.get("jar") or vid
    merged["id"] = data.get("id", vid)
    return merged


# ------------------------------------------------------------------ библиотеки

class Lib:
    def __init__(self, path, url, sha1, size, native=False, exclude=None, classpath=True, key=""):
        self.path, self.url, self.sha1, self.size = path, url, sha1, size
        self.native, self.exclude, self.classpath, self.key = native, exclude or [], classpath, key


def parse_name(name):
    ext = "jar"
    if "@" in name:
        name, ext = name.split("@", 1)
    parts = name.split(":")
    return parts[0], parts[1], parts[2], (parts[3] if len(parts) > 3 else None), ext


def maven_path(name):
    g, a, v, c, ext = parse_name(name)
    return "%s/%s/%s/%s-%s%s.%s" % (g.replace(".", "/"), a, v, a, v, "-" + c if c else "", ext)


def arm_mac_problem(libs, env):
    """На Mac с чипом M1 и новее нужны нативные библиотеки LWJGL под arm64; в старых версиях игры их нет."""
    if env.get("os") != "osx" or env.get("arch") != "arm64":
        return ""
    lw = [l for l in libs if "lwjgl" in l.path.lower()]
    if lw and not any("arm64" in l.path.lower() for l in lw):
        return ("В этой версии Minecraft нет библиотек LWJGL для Mac на чипе M1 — игра, скорее всего, не запустится. "
                "Начиная с 1.19 всё работает; для старых версий нужна Java под Rosetta (x86_64), её можно указать в настройках.")
    return ""


def resolve_libraries(version, env):
    bits = "64" if env["arch"] in ("x86_64", "arm64") else "32"
    libs, seen = [], set()
    for lib in version.get("libraries", []):
        if not rules_allow(lib.get("rules"), env):
            continue
        name = lib["name"]
        g, a, v, c, _ = parse_name(name)
        dl = lib.get("downloads") or {}
        natives = lib.get("natives")
        if natives:  # старый формат: нативные библиотеки лежат в classifiers
            cls = natives.get(env["os"])
            if cls:
                cls = cls.replace("${arch}", bits)
                info = (dl.get("classifiers") or {}).get(cls)
                if info:
                    libs.append(Lib(info["path"], info.get("url"), info.get("sha1"), info.get("size"),
                                    native=True, exclude=(lib.get("extract") or {}).get("exclude"),
                                    classpath=False))
                elif not dl:
                    p = maven_path(name + ":" + cls)
                    libs.append(Lib(p, (lib.get("url") or endpoints.LIBRARIES_BASE) + p, None, None,
                                    native=True, exclude=(lib.get("extract") or {}).get("exclude"),
                                    classpath=False))
            if "artifact" not in dl:
                continue
        key = "%s:%s:%s" % (g, a, c or "")
        if key in seen:
            continue  # версия из «дочернего» профиля (Fabric/Forge) важнее родительской
        seen.add(key)
        art = dl.get("artifact")
        if art:
            path = art.get("path") or maven_path(name)
            libs.append(Lib(path, art.get("url") or None, art.get("sha1"), art.get("size"),
                            native=bool(c and c.startswith("natives-")), key=key))
        else:
            path = maven_path(name)
            libs.append(Lib(path, (lib.get("url") or endpoints.LIBRARIES_BASE) + path,
                            lib.get("sha1"), lib.get("size"), key=key))
    return libs


def extract_natives(store, libs, natives_dir):
    os.makedirs(natives_dir, exist_ok=True)
    exts = (".dll", ".so", ".dylib", ".jnilib")
    for lib in libs:
        if not lib.native:
            continue
        jar = os.path.join(store.libraries, lib.path)
        if not os.path.isfile(jar):
            continue
        with zipfile.ZipFile(jar) as zf:
            for info in zf.infolist():
                n = info.filename
                if info.is_dir() or any(n.startswith(x) for x in lib.exclude):
                    continue
                if not n.lower().endswith(exts):
                    continue
                dest = os.path.join(natives_dir, os.path.basename(n))
                if os.path.isfile(dest) and os.path.getsize(dest) == info.file_size:
                    continue  # DLL может быть занята уже запущенной игрой
                with zf.open(info) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)


# ------------------------------------------------------------------ ассеты

def ensure_assets(store, inst, version, progress, cancel):
    ai = version.get("assetIndex")
    if not ai:
        raise GameError("В описании версии нет assetIndex")
    idx_path = os.path.join(store.assets, "indexes", ai["id"] + ".json")
    download(ai["url"], idx_path, ai.get("sha1"), ai.get("size"), cancel=cancel)
    idx = read_json(idx_path) or {}
    objects = idx.get("objects", {})
    tasks = []
    for name, o in objects.items():
        h = o["hash"]
        tasks.append((endpoints.ASSETS_BASE + h[:2] + "/" + h,
                      os.path.join(store.assets, "objects", h[:2], h), h, o["size"]))
    download_many(tasks, lambda d, t: progress("Ресурсы игры", d, t), cancel)
    game_assets = store.assets
    target = None
    if idx.get("virtual"):
        target = os.path.join(store.assets, "virtual", "legacy")
    elif idx.get("map_to_resources"):
        target = os.path.join(inst.game_dir, "resources")
    if target:
        for name, o in objects.items():
            h = o["hash"]
            dest = safe_join(target, name)
            if not os.path.isfile(dest):
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copyfile(os.path.join(store.assets, "objects", h[:2], h), dest)
        game_assets = target
    return store.assets, game_assets


# ------------------------------------------------------------------ подготовка

class Prepared:
    version = None
    java = ""
    classpath = None
    natives_dir = ""
    assets_root = ""
    game_assets = ""
    log_config = ""


def prepare(store, inst, log, progress, cancel):
    """Скачивает и готовит всё нужное для запуска. progress(метка, сделано, всего)."""
    mc = inst.mc_version
    progress("Версия Minecraft", 0, 0)
    ensure_vanilla_json(store, mc)
    vanilla = load_version(store, mc)
    env = current_env()

    java = javart.resolve_java(store, inst, vanilla, log, progress, cancel)
    _ensure_client_jar(store, vanilla, cancel)

    vid = loaders.ensure_loader(store, inst, java, log, progress, cancel)
    inst.version_id = vid
    inst.save()
    if inst.loader == "forge" and not legacyfml.ensure(inst, inst.mc_version, store, log, cancel):
        raise GameError(
            "Forge для Minecraft 1.5.2 при запуске качает файл deobfuscation_data_1.5.2.zip, но с сайта Forge он удалён. "
            "Найдите этот файл (например, в папке lib другого лаунчера) и положите в %s. Подробности — в журнале."
            % os.path.join(os.environ.get("APPDATA", "%APPDATA%"), ".minecraft", "lib"))
    version = load_version(store, vid)
    if version.get("javaVersion") != vanilla.get("javaVersion"):
        java = javart.resolve_java(store, inst, version, log, progress, cancel)

    libs = resolve_libraries(version, env)
    warn = arm_mac_problem(libs, env)
    if warn and log:
        log(warn)
    tasks = [(l.url, os.path.join(store.libraries, l.path), l.sha1, l.size) for l in libs if l.url]
    download_many(tasks, lambda d, t: progress("Библиотеки", d, t), cancel)
    for l in libs:
        if l.classpath and not os.path.isfile(os.path.join(store.libraries, l.path)):
            raise GameError("Не хватает библиотеки %s. Для Forge/NeoForge попробуйте удалить загрузчик "
                            "и поставить заново." % l.path)

    jar = _ensure_client_jar(store, version, cancel)
    if version.get("mainClass") == "net.minecraft.launchwrapper.Launch" and needs_unsigned_jar(inst.mc_version):
        jar = unsigned_copy(jar)
    assets_root, game_assets = ensure_assets(store, inst, version, progress, cancel)

    log_config = ""
    lc = (version.get("logging") or {}).get("client")
    if lc and lc.get("file"):
        f = lc["file"]
        log_config = os.path.join(store.assets, "log_configs", f["id"])
        download(f["url"], log_config, f.get("sha1"), f.get("size"), cancel=cancel)

    extract_natives(store, libs, inst.natives_dir)
    os.makedirs(inst.game_dir, exist_ok=True)

    p = Prepared()
    p.version = version
    p.java = java
    p.classpath = [os.path.join(store.libraries, l.path) for l in libs if l.classpath] + [jar]
    p.natives_dir = inst.natives_dir
    p.assets_root, p.game_assets = assets_root, game_assets
    p.log_config = log_config
    return p


def _ensure_client_jar(store, version, cancel=None):
    jar_id = version["_jar_id"]
    jar = os.path.join(store.versions, jar_id, jar_id + ".jar")
    info = (version.get("downloads") or {}).get("client")
    if info:
        download(info["url"], jar, info.get("sha1"), info.get("size"), cancel=cancel)
    elif not os.path.isfile(jar):
        raise GameError("Нет клиентского jar для версии %s" % jar_id)
    return jar


def needs_unsigned_jar(mc):
    """Подпись снимаем только для Forge на 1.5.2 и старше. С 1.6 Forge сам проверяет подпись игры
    и без неё считает jar повреждённым («CRITICAL TAMPERING WITH MINECRAFT»)."""
    nums = [int(x) for x in re.findall(r"\d+", mc or "")[:2]]
    return len(nums) == 2 and tuple(nums) < (1, 6)


def unsigned_copy(jar):
    """Копия клиентского jar без подписей (META-INF). Старый Forge (LaunchWrapper) правит классы игры,
    и Java отказывается грузить их вместе с подписанными: «signer information does not match»."""
    dest = jar[:-4] + "-unsigned.jar"
    if os.path.isfile(dest) and os.path.getmtime(dest) >= os.path.getmtime(jar):
        return dest
    tmp = dest + ".part"
    with zipfile.ZipFile(jar) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            if info.filename.upper().startswith("META-INF/"):
                continue
            zout.writestr(info, zin.read(info.filename))
    os.replace(tmp, dest)
    return dest


# ------------------------------------------------------------------ команда запуска

_PLACEHOLDER = re.compile(r"\$\{([^}]+)\}")


def _subst(s, values):
    return _PLACEHOLDER.sub(lambda m: str(values.get(m.group(1), m.group(0))), s)


def _expand(items, env, values):
    out = []
    for it in items:
        if isinstance(it, str):
            out.append(_subst(it, values))
        elif rules_allow(it.get("rules"), env, {}):
            v = it.get("value")
            for x in ([v] if isinstance(v, str) else (v or [])):
                out.append(_subst(x, values))
    return out


_GC_FLAGS = ("UseG1GC", "UseZGC", "UseParallelGC", "UseSerialGC", "UseShenandoahGC", "UseConcMarkSweepGC")


def jvm_tuning(ram, user_args=()):
    """Параметры для ровного FPS: куча сразу нужного размера (без дорогого роста посреди игры)
    и G1 с короткими паузами — как в официальном лаунчере. Если сборщик мусора задан
    пользователем, свой не навязываем."""
    out = ["-Xmx%dM" % ram, "-Xms%dM" % ram]
    if not any(f in a for a in user_args for f in _GC_FLAGS):
        out += ["-XX:+UnlockExperimentalVMOptions", "-XX:+UseG1GC", "-XX:G1NewSizePercent=20",
                "-XX:G1ReservePercent=20", "-XX:MaxGCPauseMillis=50",
                "-XX:G1HeapRegionSize=%dM" % (32 if ram >= 4096 else 16)]
    return out


PRESETS = {
    "default": ("По умолчанию", "как раньше: куча сразу нужного размера и G1 с короткими паузами"),
    "balanced": ("Баланс", "куча растёт по мере надобности, чуть меньше занимает память"),
    "fps": ("Максимум FPS", "чуть больше памяти под молодое поколение, реже сборка мусора; запуск немного дольше"),
    "lowend": ("Слабый ПК", "меньше потоков и памяти; выключите анимации фона в настройках"),
}


def preset_args(preset, ram, user_args=()):
    """Параметры JVM для выбранного пресета. Сборщик мусора, заданный пользователем, не трогаем."""
    if preset == "default" or preset not in PRESETS:
        return jvm_tuning(ram, user_args)
    own_gc = any(f in a for a in user_args for f in _GC_FLAGS)
    if preset == "lowend":
        mx = min(ram, 3072)
        out = ["-Xmx%dM" % mx, "-Xms%dM" % min(768, mx)]
        if not own_gc:
            out += ["-XX:+UseG1GC", "-XX:MaxGCPauseMillis=100", "-XX:ParallelGCThreads=2", "-XX:ConcGCThreads=1"]
        return out
    if preset == "balanced":
        out = ["-Xmx%dM" % ram, "-Xms%dM" % min(ram, max(1024, ram // 2))]
        if not own_gc:
            out += ["-XX:+UseG1GC", "-XX:MaxGCPauseMillis=80"]
        return out
    out = ["-Xmx%dM" % ram, "-Xms%dM" % ram]                  # fps
    if not own_gc:
        out += ["-XX:+UnlockExperimentalVMOptions", "-XX:+UseG1GC", "-XX:G1NewSizePercent=30",
                "-XX:G1MaxNewSizePercent=40", "-XX:G1ReservePercent=20", "-XX:MaxGCPauseMillis=40",
                "-XX:G1HeapRegionSize=%dM" % (32 if ram >= 4096 else 16),
                "-XX:+ParallelRefProcEnabled", "-XX:+DisableExplicitGC"]
    return out


def build_command(store, inst, prep, ident, agent_jar=None):
    version = prep.version
    env = current_env()
    sep = ";" if os_name() == "windows" else ":"
    classpath = sep.join(prep.classpath)
    values = {
        "auth_player_name": ident["username"], "auth_uuid": ident["uuid"],
        "auth_access_token": ident["access_token"], "auth_session": ident["access_token"],
        "user_type": ident["user_type"], "user_properties": "{}", "clientid": "", "auth_xuid": "",
        "version_name": version["id"], "version_type": version.get("type", "release"),
        "game_directory": inst.game_dir, "assets_root": prep.assets_root,
        "assets_index_name": (version.get("assetIndex") or {}).get("id", version.get("assets", "")),
        "game_assets": prep.game_assets, "natives_directory": prep.natives_dir,
        "launcher_name": "QuietLauncher", "launcher_version": APP_VERSION,
        "classpath": classpath, "classpath_separator": sep, "library_directory": store.libraries,
    }
    ram = inst.ram_mb or int(store.settings.get("ram_mb", 2048))
    jvm = []
    if agent_jar:
        jvm.append("-javaagent:%s=%s" % (agent_jar, endpoints.ELY_AGENT_SERVER))
    user_args = (store.settings.get("jvm_args", "") + " " + inst.jvm_args).split()
    preset = store.settings.get("perf_preset", "default")
    if preset != "default" and preset in PRESETS:
        jvm += preset_args(preset, ram, user_args)
    elif store.settings.get("jvm_tuning", True):
        jvm += jvm_tuning(ram, user_args)
    else:
        jvm += ["-Xmx%dM" % ram, "-Xms%dM" % min(512, ram)]
    jvm += user_args

    args = version.get("arguments")
    if args:
        jvm += _expand(args.get("jvm", []), env, values)
        game = _expand(args.get("game", []), env, values)
    else:  # версии до 1.13
        jvm += ["-Djava.library.path=" + prep.natives_dir,
                "-Dminecraft.launcher.brand=QuietLauncher",
                "-Dminecraft.launcher.version=" + APP_VERSION,
                "-cp", classpath]
        game = [_subst(t, values) for t in version.get("minecraftArguments", "").split()]
    lc = (version.get("logging") or {}).get("client")
    if lc and prep.log_config:
        jvm.append(_subst(lc["argument"], {"path": prep.log_config}))
    return [prep.java] + jvm + [version["mainClass"]] + game


def describe_command(cmd, secrets):
    text = " ".join('"%s"' % c if " " in c else c for c in cmd)
    for s in secrets:
        if s and len(s) > 3:
            text = text.replace(s, "***")
    return text


def start(cmd, cwd, log):
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, creationflags=hidden_window_flags())

    def pump():
        for raw in iter(proc.stdout.readline, b""):
            log(raw.decode("utf-8", "replace").rstrip("\r\n"))

    threading.Thread(target=pump, daemon=True).start()
    return proc

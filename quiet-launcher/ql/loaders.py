"""Загрузчики модов: Fabric, Quilt (готовый профиль с сервера) и Forge, NeoForge (через их установщик)."""
import json
import os
import subprocess
import zipfile
import urllib.parse
import xml.etree.ElementTree as ET

from . import endpoints
from .util import (Cancelled, get_json, get_text, download, write_json, hidden_window_flags, safe_join)


class LoaderError(Exception):
    pass


def _q(s):
    return urllib.parse.quote(s, safe="")


def _maven_versions(url):
    root = ET.fromstring(get_text(url))
    return [e.text for e in root.iter("version") if e.text]


def _neo_prefix(mc):
    parts = mc.split(".")
    if parts[0] == "1" and len(parts) >= 2:
        return "%s.%s." % (parts[1], parts[2] if len(parts) > 2 else "0")
    return mc + "."


def list_loader_versions(loader, mc):
    """Версии загрузчика для данной версии Minecraft, новые первыми."""
    if loader in ("fabric", "quilt"):
        base = endpoints.FABRIC_META if loader == "fabric" else endpoints.QUILT_META
        data = get_json("%s/versions/loader/%s" % (base, _q(mc)))
        return [d["loader"]["version"] for d in data]
    if loader == "forge":
        prefix = mc + "-"
        vs = [v[len(prefix):] for v in _maven_versions(endpoints.FORGE_MAVEN + "maven-metadata.xml")
              if v.startswith(prefix)]
        return vs[::-1]
    if loader == "neoforge":
        prefix = _neo_prefix(mc)
        vs = [v for v in _maven_versions(endpoints.NEOFORGE_MAVEN + "maven-metadata.xml") if v.startswith(prefix)]
        return vs[::-1]
    return []


def _find_installed(store, loader, lv):
    core = lv.split("-")[0]
    for d in sorted(os.listdir(store.versions)):
        low = d.lower()
        if core in d and loader in low and os.path.isfile(os.path.join(store.versions, d, d + ".json")):
            if loader == "forge" and "neoforge" in low:
                continue
            return d
    return None


def _run(cmd, cwd, log, cancel):
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, creationflags=hidden_window_flags())
    tail = []
    try:
        for raw in iter(p.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line.strip():
                tail = (tail + [line.strip()])[-6:]
            if log:
                log(line)
            if cancel is not None and cancel.is_set():
                p.terminate()
                raise Cancelled()
    finally:
        p.stdout.close()
        p.wait()
    return p.returncode, tail


def _modern_url(url):
    """Старые профили Forge ссылаются на http и умершие адреса — переводим на живые."""
    url = url.replace("files.minecraftforge.net/maven", "maven.minecraftforge.net")
    url = url.replace("http://", "https://")
    return url if url.endswith("/") else url + "/"


def _maven_rel(name):
    ext = "jar"
    if "@" in name:
        name, ext = name.split("@", 1)
    p = name.split(":")
    g, a, v = p[0], p[1], p[2]
    c = "-" + p[3] if len(p) > 3 else ""
    return "%s/%s/%s/%s-%s%s.%s" % (g.replace(".", "/"), a, v, a, v, c, ext)


def install_old_format(store, installer, mc, log=None):
    """Forge до 1.12.2: внутри установщика лежит готовый профиль версии и jar самого Forge.
    Запускать установщик (а он на новых Java и в Windows 7 часто падает) не нужно:
    достаточно разложить файлы. Возвращает id версии или None, если формат новый."""
    with zipfile.ZipFile(installer) as zf:
        try:
            prof = json.loads(zf.read("install_profile.json").decode("utf-8"))
        except (KeyError, ValueError):
            return None
        vi = prof.get("versionInfo")
        if not isinstance(vi, dict) or not vi.get("id"):
            return None
        info = prof.get("install") or {}
        libs = []
        for lib in vi.get("libraries", []):
            if lib.get("clientreq") is False:          # нужна только серверу
                continue
            if lib.get("url"):
                lib["url"] = _modern_url(lib["url"])
            libs.append(lib)
        vi["libraries"] = libs
        vi["inheritsFrom"] = mc                        # Minecraft, ресурсы и Java берём у ванильной версии
        vi.pop("jar", None)
        file_path, coord = info.get("filePath"), info.get("path")
        if file_path and coord:
            dest = safe_join(store.libraries, _maven_rel(coord))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            try:
                data = zf.read(file_path)
            except KeyError:
                raise LoaderError("В установщике Forge нет файла %s" % file_path)
            with open(dest, "wb") as f:
                f.write(data)
        vid = vi["id"]
        write_json(os.path.join(store.versions, vid, vid + ".json"), vi)
    if log:
        log("Forge %s установлен без запуска установщика" % vid)
    return vid


def ensure_loader(store, inst, java, log=None, progress=None, cancel=None):
    """Устанавливает загрузчик (если надо) и возвращает id версии, с которой запускаем игру."""
    loader, mc = inst.loader, inst.mc_version
    if loader == "vanilla":
        return mc
    lv = inst.loader_version
    if not lv:
        vs = list_loader_versions(loader, mc)
        if not vs:
            raise LoaderError("Для Minecraft %s нет загрузчика %s" % (mc, loader))
        lv = vs[0]
        inst.loader_version = lv

    if loader in ("fabric", "quilt"):
        vid = "%s-loader-%s-%s" % (loader, lv, mc)
        if not os.path.isfile(os.path.join(store.versions, vid, vid + ".json")):
            if progress:
                progress("Загрузчик " + loader, 0, 0)
            base = endpoints.FABRIC_META if loader == "fabric" else endpoints.QUILT_META
            data = get_json("%s/versions/loader/%s/%s/profile/json" % (base, _q(mc), _q(lv)))
            vid = data.get("id", vid)
            write_json(os.path.join(store.versions, vid, vid + ".json"), data)
        return vid

    found = _find_installed(store, loader, lv)
    if found:
        return found
    if loader == "forge":
        url = "%s%s-%s/forge-%s-%s-installer.jar" % (endpoints.FORGE_MAVEN, mc, lv, mc, lv)
    else:
        url = "%s%s/neoforge-%s-installer.jar" % (endpoints.NEOFORGE_MAVEN, lv, lv)
    installer = os.path.join(store.cache, "installers", url.rsplit("/", 1)[-1])
    if progress:
        progress("Установщик " + loader, 0, 0)
    download(url, installer, cancel=cancel)
    old = install_old_format(store, installer, mc, log)
    if old:
        return old
    profiles = os.path.join(store.shared, "launcher_profiles.json")
    if not os.path.isfile(profiles):  # установщик Forge требует этот файл
        write_json(profiles, {"profiles": {}, "selectedProfile": "", "clientToken": "",
                              "authenticationDatabase": {}, "launcherVersion": {"name": "QuietLauncher", "format": 21}})
    if log:
        log("Запускаю установщик %s %s (это может занять пару минут)…" % (loader, lv))
    code, tail = _run([java, "-jar", installer, "--installClient", store.shared], store.shared, log, cancel)
    found = _find_installed(store, loader, lv)
    if code != 0 or not found:
        hint = ("\n\nПоследние строки установщика:\n" + "\n".join(tail)) if tail else ""
        old = "\n\nУстановщики Forge для очень старых версий Minecraft (до 1.6) этим способом не ставятся." \
            if loader == "forge" and mc.split(".")[:2] in (["1", "0"], ["1", "1"], ["1", "2"], ["1", "3"], ["1", "4"], ["1", "5"]) else ""
        raise LoaderError("Установщик %s завершился с ошибкой (код %s).%s%s\n\nПолный текст — вкладка «Журнал» или кнопка «Журнал» сверху."
                          % (loader, code, hint, old))
    return found

"""Обновление лаунчера через GitHub Releases: в релизе лежит QuietLauncher-Setup.exe."""
import os
import re
import subprocess
import sys
import tempfile
import time

from . import APP_VERSION, endpoints
from .util import get_json, get_text, download

CHECK_EVERY = 4 * 3600


def parse_version(s):
    nums = re.findall(r"\d+", s or "")
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(remote, local=APP_VERSION):
    a, b = parse_version(remote), parse_version(local)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def due(settings, now=None):
    """Пора ли спрашивать GitHub (не чаще раза в несколько часов, чтобы не упереться в лимит)."""
    if not settings.get("check_updates", True):
        return False
    now = now or time.time()
    last = float(settings.get("update_checked") or 0)
    return last > now or now - last > CHECK_EVERY


def fetch_latest_ex(api=None):
    """Последний релиз и пояснение: (сведения или None, причина по-русски, если сведений нет)."""
    rel = get_json(api or endpoints.UPDATE_API, headers={"Accept": "application/vnd.github+json"}, timeout=8, retries=1)
    if not isinstance(rel, dict) or not rel.get("tag_name") and not rel.get("name"):
        return None, "GitHub не вернул данные о релизе"
    tag = (rel.get("tag_name") or rel.get("name") or "").lstrip("vV")
    if rel.get("draft") or rel.get("prerelease"):
        return None, "Последний релиз %s — черновик или пре-релиз, такие лаунчер не предлагает" % tag
    asset = None
    for a in rel.get("assets") or []:
        n = a.get("name", "").lower()
        if n.endswith(".exe") and "setup" in n:
            asset = a
            break
    if not asset:
        return None, ("В релизе %s нет файла установщика: нужен .exe со словом Setup в названии "
                      "(например QuietLauncher-Setup.exe), дождитесь конца его загрузки" % tag)
    sha = ""
    digest = asset.get("digest") or ""
    if digest.lower().startswith("sha256:"):
        sha = digest[7:].strip().lower()
    else:                                              # запасной вариант: файл QuietLauncher-Setup.exe.sha256
        for a in rel.get("assets") or []:
            if a.get("name", "").lower() == asset["name"].lower() + ".sha256":
                try:
                    sha = get_text(a["browser_download_url"], timeout=8, retries=1).split()[0].lower()
                except Exception:
                    sha = ""
    return {"version": tag, "notes": rel.get("body") or "", "url": asset["browser_download_url"], "name": asset["name"],
            "size": int(asset.get("size") or 0), "sha256": sha,
            "page": rel.get("html_url") or endpoints.RELEASES_PAGE}, ""


def fetch_latest(api=None):
    """Последний релиз: {version, notes, url, name, size, sha256, page} или None, если ничего не нашли."""
    return fetch_latest_ex(api)[0]


def check(settings, api=None, local=APP_VERSION):
    """Возвращает сведения о новой версии или None. Время проверки запоминается только после ответа GitHub,
    чтобы случайный сбой сети не откладывал следующую попытку на несколько часов."""
    info = fetch_latest(api)
    settings["update_checked"] = time.time()
    if info and is_newer(info["version"], local):
        return info
    return None


def check_report(api=None, local=APP_VERSION):
    """Для кнопки «Проверить сейчас»: (сведения о новой версии или None, текст для пользователя)."""
    try:
        info, why = fetch_latest_ex(api)
    except Exception as e:
        return None, "Не удалось связаться с GitHub: %s" % e
    if info is None:
        return None, why
    if is_newer(info["version"], local):
        return info, "Доступна версия %s" % info["version"]
    return None, "У вас последняя версия (%s). Последний релиз на GitHub: %s" % (local, info["version"])


def download_installer(info, on_bytes=None, cancel=None):
    folder = os.path.join(tempfile.gettempdir(), "QuietLauncherUpdate")
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, info["name"])
    if os.path.exists(dest):
        os.remove(dest)
    download(info["url"], dest, size=info.get("size") or None, sha256=info.get("sha256") or None,
             cancel=cancel, on_bytes=on_bytes)
    return dest


def can_self_update():
    return bool(getattr(sys, "frozen", False)) and os.name == "nt"


def run_installer(path):
    """Тихая установка поверх текущей (сборки и миры в data остаются), затем лаунчер откроется снова."""
    flags = 0
    if os.name == "nt":
        flags = 0x00000008 | 0x00000200            # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([path, "/SILENT", "/NORESTART", "/CLOSEAPPLICATIONS", "/relaunch=1"],
                     creationflags=flags, close_fds=True)

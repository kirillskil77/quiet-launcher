"""Папки лаунчера, настройки и список аккаунтов."""
import os
import sys
import threading

from .util import os_name, read_json, write_json

DEFAULT_SETTINGS = {
    "ms_client_id": "",       # Azure client id для входа через Microsoft (см. README)
    "ram_mb": 2048,
    "java_path": "",          # пусто = подобрать автоматически
    "use_zulu": True,         # для Minecraft 1.17+ на Windows ставить Java Zulu 21 (работает и на Windows 7)
    "animations": True,       # анимированный фон и плавные эффекты (в игре и при сворачивании не работают)
    "check_updates": True,    # раз в несколько часов смотреть, нет ли новой версии лаунчера
    "update_checked": 0,
    "update_offered": "",     # версия, о которой уже показывали окно
    "welcome_seen": "",       # версия, для которой уже показывали приветствие
    "jvm_tuning": True,       # параметры JVM для ровного FPS (G1, куча сразу нужного размера)
    "jvm_args": "",
    "theme": "black",         # black / graphite / navy / purple (применяется после перезапуска)
    "accent": "#4f8f6a",
    "layout": "classic",      # classic / right / compact (применяется сразу)
    "perf_preset": "default", # default / balanced / fps / lowend
    "backup_worlds": True,
    "backup_keep": 3,
    "show_snapshots": False,
    "last_instance": "",
    "last_account": "",
}


def user_data_dir():
    """Папка данных пользователя: %APPDATA%, ~/Library/Application Support или ~/.local/share."""
    n = os_name()
    if n == "windows":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif n == "osx":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "QuietLauncher")


def default_home():
    env = os.environ.get("QL_HOME")
    if env:
        return env
    if getattr(sys, "frozen", False) and os_name() != "windows":
        return user_data_dir()                       # внутри .app / AppImage писать нельзя и не нужно
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    home = os.path.join(base, "data")
    try:  # портативная папка, если в неё можно писать
        os.makedirs(home, exist_ok=True)
        probe = os.path.join(home, ".w")
        with open(probe, "w") as f:
            f.write("1")
        os.remove(probe)
        return home
    except OSError:
        return user_data_dir()


class Store:
    def __init__(self, home=None):
        self.home = home or default_home()
        self.shared = os.path.join(self.home, "shared")
        self.versions = os.path.join(self.shared, "versions")
        self.libraries = os.path.join(self.shared, "libraries")
        self.assets = os.path.join(self.shared, "assets")
        self.runtime = os.path.join(self.shared, "runtime")
        self.instances = os.path.join(self.home, "instances")
        self.cache = os.path.join(self.home, "cache")
        for d in (self.versions, self.libraries, self.assets, self.runtime, self.instances, self.cache):
            os.makedirs(d, exist_ok=True)
        self._lock = threading.Lock()
        self._settings_file = os.path.join(self.home, "settings.json")
        self._accounts_file = os.path.join(self.home, "accounts.json")
        self.settings = dict(DEFAULT_SETTINGS)
        self.settings.update(read_json(self._settings_file, {}) or {})
        self.accounts = read_json(self._accounts_file, []) or []

    def save_settings(self):
        with self._lock:
            write_json(self._settings_file, self.settings)

    def save_accounts(self):
        with self._lock:
            write_json(self._accounts_file, self.accounts)

    def find_account(self, acc_id):
        for a in self.accounts:
            if a.get("id") == acc_id:
                return a
        return None

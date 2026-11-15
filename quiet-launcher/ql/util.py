"""Сеть, файлы, мелкие помощники. Только стандартная библиотека, Python 3.8+."""
import hashlib
import http.client
import json
import os
import platform
import re
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import APP_VERSION

USER_AGENT = "QuietLauncher/%s (personal launcher)" % APP_VERSION


class Cancelled(Exception):
    pass


class HttpError(Exception):
    def __init__(self, message, status=None, body=None):
        Exception.__init__(self, message)
        self.status = status
        self.body = body


# ---------------------------------------------------------------- система

def os_name():
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "osx"
    return "linux"


def os_arch():
    m = (os.environ.get("PROCESSOR_ARCHITEW6432")
         or os.environ.get("PROCESSOR_ARCHITECTURE")
         or platform.machine() or "").lower()
    if m in ("amd64", "x86_64"):
        return "x86_64"
    if m in ("arm64", "aarch64"):
        return "arm64"
    if m in ("x86", "i386", "i686"):
        return "x86"
    return m


def os_version():
    try:
        return platform.version()
    except Exception:
        return ""


def is_windows7():
    if os_name() != "windows":
        return False
    try:
        v = sys.getwindowsversion()
        return (v.major, v.minor) < (6, 2)
    except Exception:
        return False


def total_ram_mb():
    """Объём оперативной памяти, МБ (по умолчанию 8192, если узнать не вышло)."""
    try:
        if os_name() == "windows":
            import ctypes

            class MEMSTATUS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = MEMSTATUS()
            st.dwLength = ctypes.sizeof(MEMSTATUS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return int(st.ullTotalPhys // (1024 * 1024))
        pages = os.sysconf("SC_PHYS_PAGES")
        size = os.sysconf("SC_PAGE_SIZE")
        return int(pages * size // (1024 * 1024))
    except Exception:
        return 8192


def hidden_window_flags():
    return getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0) if os_name() == "windows" else 0


# ---------------------------------------------------------------- файлы

def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def slugify(name):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return s or "instance"


def safe_join(base, name):
    """Защита от zip-slip: путь внутри base, иначе ValueError."""
    base_n = os.path.normpath(base)
    dest = os.path.normpath(os.path.join(base_n, name))
    if dest != base_n and not dest.startswith(base_n + os.sep):
        raise ValueError("Небезопасный путь в архиве: %s" % name)
    return dest


def sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def file_ok(path, sha1=None, size=None):
    """Файл на месте и (по размеру или хэшу) совпадает с ожидаемым."""
    if not os.path.isfile(path):
        return False
    if size is not None:
        return os.path.getsize(path) == size
    if sha1:
        return sha1_file(path) == sha1.lower()
    return True


# ---------------------------------------------------------------- сеть

_ctx = None


def ssl_context():
    """certifi, если он есть (в exe он вшит) — на Windows 7 системные корневые сертификаты часто устарели."""
    global _ctx
    if _ctx is None:
        try:
            import certifi
            _ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            _ctx = ssl.create_default_context()
    return _ctx


def _open(req, timeout):
    return urllib.request.urlopen(req, timeout=timeout, context=ssl_context())


_tls = threading.local()


class _PooledResponse(object):
    """Ответ по постоянному соединению: после полного чтения соединение возвращается в пул потока."""

    def __init__(self, resp, conn, pool, key):
        self.resp, self.conn, self.pool, self.key = resp, conn, pool, key
        self.headers = resp.headers

    def read(self, n=-1):
        return self.resp.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if not exc[0] and self.resp.isclosed() and not self.resp.will_close:
            self.pool[self.key] = self.conn
        else:
            self.conn.close()


def _get(url, timeout=60):
    """GET с повторным использованием соединения (тысячи мелких файлов игры качаются
    заметно быстрее, чем с новым TLS-рукопожатием на каждый). Всё нестандартное
    (редиректы, ошибки, прокси) уходит в обычный urllib."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ("http", "https") or not u.netloc:
        return _open(req, timeout)
    pool = getattr(_tls, "pool", None)
    if pool is None:
        pool = _tls.pool = {}
    key = (u.scheme, u.netloc)
    conn = pool.pop(key, None)
    path = (u.path or "/") + ("?" + u.query if u.query else "")
    for _ in (0, 1):
        fresh = conn is None
        if fresh:
            if u.scheme == "https":
                conn = http.client.HTTPSConnection(u.netloc, timeout=timeout, context=ssl_context())
            else:
                conn = http.client.HTTPConnection(u.netloc, timeout=timeout)
        try:
            conn.request("GET", path, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
            resp = conn.getresponse()
        except (OSError, http.client.HTTPException):
            conn.close()
            conn = None
            if fresh:
                break
            continue          # устаревшее соединение: пробуем ещё раз на новом
        if resp.status != 200:
            conn.close()
            break
        return _PooledResponse(resp, conn, pool, key)
    return _open(req, timeout)


def _body_text(e):
    try:
        return e.read().decode("utf-8", "replace")
    except Exception:
        return ""


def request(url, data=None, headers=None, method=None, timeout=30, retries=3):
    """Возвращает (status, bytes). 4xx не повторяются, 429/5xx и сетевые сбои — да."""
    h = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        h.update(headers)
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=h, method=method)
            with _open(req, timeout) as r:
                return (getattr(r, "status", None) or 200), r.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(1 + attempt)
                last = e
                continue
            raise HttpError("HTTP %s: %s" % (e.code, url), e.code, _body_text(e))
        except (urllib.error.URLError, OSError, ssl.SSLError, socket.timeout) as e:
            last = e
            if attempt < retries - 1:
                time.sleep(1 + attempt)
    raise HttpError("Нет связи с сервером (%s): %s" % (last, url))


def get_json(url, headers=None, **kw):
    _, body = request(url, headers=headers, **kw)
    return json.loads(body.decode("utf-8"))


def get_text(url, **kw):
    _, body = request(url, **kw)
    return body.decode("utf-8", "replace")


def post_json(url, payload, headers=None, **kw):
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        h.update(headers)
    status, body = request(url, data=json.dumps(payload).encode("utf-8"), headers=h, method="POST", **kw)
    if not body.strip():
        return {}
    return json.loads(body.decode("utf-8"))


def post_form(url, fields, **kw):
    h = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
    status, body = request(url, data=urllib.parse.urlencode(fields).encode("utf-8"),
                           headers=h, method="POST", **kw)
    return json.loads(body.decode("utf-8")) if body.strip() else {}


def download(url, dest, sha1=None, size=None, retries=3, cancel=None, sha256=None, on_bytes=None):
    """Скачивает файл через .part, сверяет sha1/sha256. Возвращает True, если что-то скачано.
    on_bytes(получено, всего) — для прогресса крупных файлов (всего может быть 0)."""
    if file_ok(dest, sha1, size):
        return False
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    part = dest + ".part"
    last = None
    for attempt in range(retries):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        try:
            h = hashlib.sha1()
            h2 = hashlib.sha256() if sha256 else None
            got = 0
            with _get(url, 60) as r, open(part, "wb") as f:
                try:
                    total = int(r.headers.get("Content-Length") or 0)
                except ValueError:
                    total = 0
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    if cancel is not None and cancel.is_set():
                        raise Cancelled()
                    f.write(chunk)
                    h.update(chunk)
                    if h2 is not None:
                        h2.update(chunk)
                    got += len(chunk)
                    if on_bytes:
                        on_bytes(got, total)
            if sha1 and h.hexdigest() != sha1.lower():
                raise HttpError("Контрольная сумма не совпала: %s" % url)
            if h2 is not None and h2.hexdigest() != sha256.lower():
                raise HttpError("Контрольная сумма sha256 не совпала: %s" % url)
            os.replace(part, dest)
            return True
        except Cancelled:
            _silent_remove(part)
            raise
        except urllib.error.HTTPError as e:
            _silent_remove(part)
            last = HttpError("HTTP %s: %s" % (e.code, url), e.code)
            if e.code not in (429, 500, 502, 503, 504):
                raise last
        except (urllib.error.URLError, OSError, ssl.SSLError, socket.timeout, HttpError) as e:
            _silent_remove(part)
            last = e
        time.sleep(1 + attempt)
    if isinstance(last, HttpError):
        raise last
    raise HttpError("Не удалось скачать (%s): %s" % (last, url))


def _silent_remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def download_many(tasks, progress=None, cancel=None, workers=16):
    """tasks: список (url, dest, sha1, size). progress(done, total)."""
    total = len(tasks)
    if not total:
        return
    state = {"done": 0}
    errors = []
    lock = threading.Lock()
    stop = threading.Event()

    def run(t):
        if stop.is_set():
            return
        try:
            download(t[0], t[1], t[2], t[3], cancel=cancel)
        except Exception as e:
            errors.append(e)
            stop.set()
            return
        with lock:
            state["done"] += 1
            d = state["done"]
        if progress:
            progress(d, total)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(run, tasks))
    if errors:
        raise errors[0]
    if cancel is not None and cancel.is_set():
        raise Cancelled()


def resource_path(rel):
    """Путь к файлу, лежащему внутри программы (и в исходниках, и в собранном exe)."""
    import sys
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)

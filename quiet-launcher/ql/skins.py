"""Головы аккаунтов для верхней панели. Скин берётся с серверов скинов; для офлайна рисуется простая
стандартная голова (свой рисунок, без файлов Mojang). Для вырезания лица из скина нужна Pillow."""
import base64
import json
import os
import struct
import time
import zlib

from . import endpoints
from .util import get_json, download

try:
    from PIL import Image
except Exception:
    Image = None

HEAD_TTL = 24 * 3600
_NEAREST = None
if Image is not None:
    _NEAREST = getattr(getattr(Image, "Resampling", Image), "NEAREST")

# 8x8: H — волосы, S — кожа, W — белок, P — зрачок, M — рот
_DEFAULT = ("HHHHHHHH", "HHHHHHHH", "HSSSSSSH", "SSSSSSSS", "SWPSSPWS", "SSSSSSSS", "SSSMMSSS", "SSSSSSSS")
_PAL = {"H": (74, 52, 38), "S": (196, 150, 112), "W": (238, 238, 238), "P": (60, 80, 150), "M": (140, 84, 70)}


def write_png(path, rows, scale=1):
    """Минимальный PNG-писатель: rows — список строк из (r, g, b) — чтобы не зависеть от Pillow."""
    h, w = len(rows) * scale, len(rows[0]) * scale
    raw = bytearray()
    for row in rows:
        line = bytearray([0])
        for px in row:
            line += bytes(px) * scale
        raw += bytes(line) * scale

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(png)
    os.replace(tmp, path)


def default_head(store, size=24):
    k = max(1, size // 8)
    path = os.path.join(store.cache, "heads", "default_%d.png" % (8 * k))
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_png(path, [[_PAL[c] for c in row] for row in _DEFAULT], k)
    return path


def cut_head(skin_png, out_png, size):
    """Лицо + второй слой (шляпа) из файла скина, увеличение без сглаживания. Нужна Pillow."""
    if Image is None:
        return False
    im = Image.open(skin_png).convert("RGBA")
    k = max(1, im.width // 64)
    face = im.crop((8 * k, 8 * k, 16 * k, 16 * k))
    if im.height >= 32 * k:
        hat = im.crop((40 * k, 8 * k, 48 * k, 16 * k))
        face.alpha_composite(hat)
    face.resize((size, size), _NEAREST).save(out_png)
    return True


def _skin_url(acc):
    if acc.get("type") == "elyby":
        return endpoints.ELY_SKIN.format(name=acc["name"])
    if acc.get("type") == "microsoft":
        data = get_json("https://sessionserver.mojang.com/session/minecraft/profile/" + acc["uuid"])
        for p in data.get("properties", []):
            if p.get("name") == "textures":
                tex = json.loads(base64.b64decode(p["value"]).decode("utf-8"))
                url = ((tex.get("textures") or {}).get("SKIN") or {}).get("url", "")
                if url.startswith("https://textures.minecraft.net/") or url.startswith("http://textures.minecraft.net/"):
                    return url
    return ""


def head_path(store, acc, size=24):
    """Путь к готовой голове из кэша (свежей), иначе None."""
    size = 8 * max(1, size // 8)
    path = os.path.join(store.cache, "heads", "%s_%d.png" % (acc.get("uuid") or acc.get("id"), size))
    try:
        if time.time() - os.path.getmtime(path) < HEAD_TTL:
            return path
    except OSError:
        pass
    return None


def fetch_head(store, acc, size=24):
    """Скачивает скин и делает голову (в потоке). Возвращает путь или None."""
    if acc.get("type") not in ("elyby", "microsoft") or Image is None:
        return None
    size = 8 * max(1, size // 8)
    d = os.path.join(store.cache, "heads")
    os.makedirs(d, exist_ok=True)
    name = acc.get("uuid") or acc.get("id")
    try:
        url = _skin_url(acc)
        if not url:
            return None
        skin = os.path.join(d, "%s_skin.png" % name)
        download(url, skin, retries=1)
        out = os.path.join(d, "%s_%d.png" % (name, size))
        return out if cut_head(skin, out, size) else None
    except Exception:
        return None


def stale_head(store, acc, size=24):
    """Старая голова из кэша — лучше, чем стандартная, пока скачивается новая."""
    size = 8 * max(1, size // 8)
    path = os.path.join(store.cache, "heads", "%s_%d.png" % (acc.get("uuid") or acc.get("id"), size))
    return path if os.path.exists(path) else None

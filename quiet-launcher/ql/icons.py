"""Иконки сборок: блоки и лица мобов, вырезанные из клиентского jar самого игрока.
Файлы Mojang с лаунчером не поставляются — используется то, что уже скачано для игры."""
import glob
import os
import zipfile

try:
    from PIL import Image
    _NEAREST = getattr(getattr(Image, "Resampling", Image), "NEAREST")
except Exception:
    Image = None
    _NEAREST = None

_B = "assets/minecraft/textures/block/%s.png"
_OB = "assets/minecraft/textures/blocks/%s.png"
_E = "assets/minecraft/textures/entity/%s.png"
_OM = "assets/minecraft/textures/mob/%s.png"

# ключ, подпись, [пути в jar по порядку], лицо ли моба
ICONS = (
    ("grass", "Трава", [_B % "grass_block_side", _OB % "grass_side"], False),
    ("dirt", "Земля", [_B % "dirt", _OB % "dirt"], False),
    ("stone", "Камень", [_B % "stone", _OB % "stone"], False),
    ("cobble", "Булыжник", [_B % "cobblestone", _OB % "cobblestone"], False),
    ("planks", "Доски", [_B % "oak_planks", _OB % "planks_oak"], False),
    ("sand", "Песок", [_B % "sand", _OB % "sand"], False),
    ("diamond_ore", "Алмазная руда", [_B % "diamond_ore", _OB % "diamond_ore"], False),
    ("gold", "Золотой блок", [_B % "gold_block", _OB % "gold_block"], False),
    ("iron", "Железный блок", [_B % "iron_block", _OB % "iron_block"], False),
    ("tnt", "TNT", [_B % "tnt_side", _OB % "tnt_side"], False),
    ("glowstone", "Светокамень", [_B % "glowstone", _OB % "glowstone"], False),
    ("obsidian", "Обсидиан", [_B % "obsidian", _OB % "obsidian"], False),
    ("netherrack", "Незерак", [_B % "netherrack", _OB % "netherrack"], False),
    ("bookshelf", "Книжная полка", [_B % "bookshelf", _OB % "bookshelf"], False),
    ("creeper", "Крипер", [_E % "creeper/creeper", _OM % "creeper"], True),
    ("zombie", "Зомби", [_E % "zombie/zombie", _OM % "zombie"], True),
    ("skeleton", "Скелет", [_E % "skeleton/skeleton", _OM % "skeleton"], True),
    ("pig", "Свинья", [_E % "pig/pig_temperate", _E % "pig/pig", _OM % "pig"], True),
    ("enderman", "Эндермен", [_E % "enderman/enderman", _OM % "enderman"], True),
)
TITLES = {k: t for k, t, _p, _m in ICONS}


def icon_size(scale):
    return int(24 * scale)


def _dir(store):
    return os.path.join(store.cache, "icons")


def icon_file(store, key, size):
    return os.path.join(_dir(store), "%s_%d.png" % (key, size))


def _read(z, names, member):
    for n in member:
        if n in names:
            return z.read(n)
    return None


def _render(raw, mob, size):
    import io
    im = Image.open(io.BytesIO(raw)).convert("RGBA")
    if mob:
        k = max(1, im.width // 64)
        im = im.crop((8 * k, 8 * k, 16 * k, 16 * k))
    else:
        if im.height > im.width:                 # анимированная полоса — берём первый кадр
            im = im.crop((0, 0, im.width, im.width))
    return im.resize((size, size), _NEAREST)


def find_jar(store):
    jars = glob.glob(os.path.join(store.versions, "*", "*.jar"))
    jars.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return jars


def extract(store, size, log=None):
    """Достаёт иконки из клиентских jar в кэш. Возвращает список ключей, которые удалось получить.
    Без Pillow блоки не масштабируются, лица мобов недоступны — иконок не будет."""
    got = set(k for k, _t, _p, _m in ICONS if os.path.exists(icon_file(store, k, size)))
    if Image is None or len(got) == len(ICONS):
        return [k for k, _t, _p, _m in ICONS if k in got]
    os.makedirs(_dir(store), exist_ok=True)
    for jar in find_jar(store):
        try:
            with zipfile.ZipFile(jar) as z:
                names = set(z.namelist())
                for key, _t, paths, mob in ICONS:
                    if key in got:
                        continue
                    raw = _read(z, names, paths)
                    if raw is None:
                        continue
                    try:
                        _render(raw, mob, size).save(icon_file(store, key, size))
                        got.add(key)
                    except Exception:
                        continue
        except (OSError, zipfile.BadZipFile):
            continue
        if len(got) == len(ICONS):
            break
    return [k for k, _t, _p, _m in ICONS if k in got]


def available(store, size):
    return [k for k, _t, _p, _m in ICONS if os.path.exists(icon_file(store, k, size))]

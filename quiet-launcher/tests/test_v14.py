import io
import os
import shutil
import sys
import tempfile
import time
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ql import backup, changelog, game, instances, skins, icons  # noqa: E402
from ql.config import Store  # noqa: E402

try:
    from PIL import Image
except Exception:
    Image = None


def make_world(inst, name, data=b"x" * 100):
    d = os.path.join(inst.game_dir, "saves", name)
    os.makedirs(os.path.join(d, "region"), exist_ok=True)
    for rel in ("level.dat", "region/r.0.0.mca", "session.lock"):
        with open(os.path.join(d, rel), "wb") as f:
            f.write(data)
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(os.path.join(self.tmp, "h"))
        self.inst = instances.create_instance(self.store, "T", "1.20.1")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class BackupTests(Base):
    def test_backup_only_when_changed_and_keep_limit(self):
        w = make_world(self.inst, "Мир1")
        self.assertEqual(backup.backup_world(self.inst, "Мир1", keep=2), "saved")
        self.assertEqual(backup.backup_world(self.inst, "Мир1", keep=2), "same")      # не менялся
        for i in range(3):
            time.sleep(1.05)
            with open(os.path.join(w, "level.dat"), "wb") as f:
                f.write(b"y" * (200 + i))
            self.assertEqual(backup.backup_world(self.inst, "Мир1", keep=2), "saved")
        self.assertEqual(len(backup.list_backups(self.inst, "Мир1")), 2)               # лишние удалены

    def test_session_lock_not_in_zip_and_no_other_dirs(self):
        make_world(self.inst, "A")
        os.makedirs(os.path.join(self.inst.game_dir, "saves", "not_a_world"))
        self.assertEqual(backup.list_worlds(self.inst), ["A"])
        backup.backup_world(self.inst, "A")
        _w, path, _t, _s = backup.list_backups(self.inst)[0]
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
        self.assertTrue(any(n.endswith("level.dat") for n in names))
        self.assertFalse(any("session.lock" in n for n in names))

    def test_big_world_and_no_space(self):
        make_world(self.inst, "B")
        old = backup.MAX_WORLD_BYTES
        backup.MAX_WORLD_BYTES = 10
        try:
            self.assertEqual(backup.backup_world(self.inst, "B"), "big")
        finally:
            backup.MAX_WORLD_BYTES = old
        old_extra = backup.MIN_FREE_EXTRA
        backup.MIN_FREE_EXTRA = 1 << 60
        try:
            self.assertEqual(backup.backup_world(self.inst, "B"), "nospace")
        finally:
            backup.MIN_FREE_EXTRA = old_extra

    def test_restore_creates_new_folder_and_keeps_world(self):
        w = make_world(self.inst, "C", b"orig")
        backup.backup_world(self.inst, "C")
        with open(os.path.join(w, "level.dat"), "wb") as f:
            f.write(b"changed")
        path = backup.list_backups(self.inst)[0][1]
        name = backup.restore(self.inst, path)
        self.assertNotEqual(name, "C")
        with open(os.path.join(self.inst.game_dir, "saves", name, "level.dat"), "rb") as f:
            self.assertEqual(f.read(), b"orig")
        with open(os.path.join(w, "level.dat"), "rb") as f:
            self.assertEqual(f.read(), b"changed")
        self.assertNotEqual(backup.restore(self.inst, path), name)                      # повторно — новое имя

    def test_restore_rejects_path_traversal(self):
        d = os.path.join(backup.backups_dir(self.inst), "Z")
        os.makedirs(d)
        p = os.path.join(d, "x.zip")
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("Z/../../evil.txt", "bad")
        with self.assertRaises(ValueError):
            backup.restore(self.inst, p)
        self.assertFalse(os.path.exists(os.path.join(self.inst.game_dir, "evil.txt")))

    def test_background_thread_logs(self):
        make_world(self.inst, "D")
        logs = []
        backup.backup_in_background(self.inst, 3, logs.append).join(10)
        self.assertTrue(any("D" in m for m in logs))


class ChangelogTests(unittest.TestCase):
    def test_counter_path(self):
        self.assertEqual(changelog.counter_path("1.3.2", "1.4.0")[0], "1.3.2")
        self.assertEqual(changelog.counter_path("1.3.2", "1.4.0")[-1], "1.4.0")
        self.assertEqual(changelog.counter_path("1.4.0", "1.4.0"), ["1.4.0"])
        self.assertLessEqual(len(changelog.counter_path("1.0.0", "3.9.0")), 41)

    def test_generation_lists(self):
        items, older = changelog.updated_items("1.3.2", "1.4.0")
        self.assertEqual(items, changelog.GENERATIONS["1.4"])
        self.assertEqual(older, changelog.GENERATIONS["1.3"])
        self.assertFalse(any("1.3" in i and "Forge" in i for i in items))
        items2, older2 = changelog.updated_items("1.4.0", "1.4.1")
        self.assertIsNone(older2)
        self.assertEqual(items2, changelog.PATCHES["1.4.1"])
        items3, _o = changelog.updated_items("1.4.0", "1.4.2")          # пропущенная версия: пункты обеих
        self.assertEqual(items3, changelog.PATCHES["1.4.1"] + changelog.PATCHES["1.4.2"])
        self.assertEqual(changelog.updated_items("1.4.1", "1.4.2")[0], changelog.PATCHES["1.4.2"])


class PresetTests(unittest.TestCase):
    def test_default_equals_tuning(self):
        self.assertEqual(game.preset_args("default", 4096, ()), game.jvm_tuning(4096, ()))

    def test_user_gc_is_kept(self):
        for p in ("balanced", "fps", "lowend"):
            out = game.preset_args(p, 4096, ["-XX:+UseZGC"])
            self.assertFalse(any("G1" in a or "UseG1GC" in a for a in out), p)

    def test_presets_differ_and_have_memory(self):
        seen = set()
        for p in game.PRESETS:
            out = game.preset_args(p, 4096, ())
            self.assertTrue(any(a.startswith("-Xmx") for a in out))
            seen.add(tuple(out))
        self.assertEqual(len(seen), len(game.PRESETS))
        self.assertIn("-Xmx3072M", game.preset_args("lowend", 8192, ()))


class SkinsIconsTests(Base):
    def test_default_head_is_png(self):
        p = skins.default_head(self.store, 24)
        with open(p, "rb") as f:
            self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")

    @unittest.skipIf(Image is None, "нужна Pillow")
    def test_cut_head_with_hat_and_hd(self):
        for k in (1, 2):
            skin = Image.new("RGBA", (64 * k, 64 * k), (0, 0, 0, 0))
            skin.paste((200, 0, 0, 255), (8 * k, 8 * k, 16 * k, 16 * k))
            skin.paste((0, 0, 200, 255), (40 * k, 8 * k, 44 * k, 16 * k))       # половина шляпы
            sp, out = os.path.join(self.tmp, "s.png"), os.path.join(self.tmp, "h.png")
            skin.save(sp)
            self.assertTrue(skins.cut_head(sp, out, 24))
            im = Image.open(out).convert("RGBA")
            self.assertEqual(im.size, (24, 24))
            self.assertEqual(im.getpixel((1, 1)), (0, 0, 200, 255))             # шляпа поверх лица
            self.assertEqual(im.getpixel((22, 22)), (200, 0, 0, 255))

    @unittest.skipIf(Image is None, "нужна Pillow")
    def test_icons_extracted_from_jar(self):
        vdir = os.path.join(self.store.versions, "1.20.1")
        os.makedirs(vdir)
        buf = io.BytesIO()
        with zipfile.ZipFile(os.path.join(vdir, "1.20.1.jar"), "w") as z:
            im = Image.new("RGBA", (16, 16), (10, 200, 10, 255))
            im.save(buf, "PNG")
            z.writestr("assets/minecraft/textures/block/dirt.png", buf.getvalue())
            mob = Image.new("RGBA", (64, 32), (0, 0, 0, 0))
            mob.paste((0, 255, 0, 255), (8, 8, 16, 16))
            b2 = io.BytesIO()
            mob.save(b2, "PNG")
            z.writestr("assets/minecraft/textures/entity/creeper/creeper.png", b2.getvalue())
        got = icons.extract(self.store, 24)
        self.assertEqual(sorted(got), ["creeper", "dirt"])
        face = Image.open(icons.icon_file(self.store, "creeper", 24)).convert("RGBA")
        self.assertEqual(face.size, (24, 24))
        self.assertEqual(face.getpixel((12, 12)), (0, 255, 0, 255))
        self.assertEqual(icons.available(self.store, 24), ["dirt", "creeper"])

    def test_last_played_text(self):
        i = self.inst
        self.assertEqual(i.last_played_text(), "ещё не запускалась")
        i.last_played = int(time.time())
        self.assertTrue(i.last_played_text().startswith("сегодня"))
        i.last_played = int(time.time()) - 86400
        self.assertTrue(i.last_played_text().startswith("вчера"))
        i.last_played = int(time.time()) - 10 * 86400
        self.assertRegex(i.last_played_text(), r"\d\d\.\d\d\.\d{4}")


if __name__ == "__main__":
    unittest.main()


class PortTests(unittest.TestCase):
    def test_user_data_dir_per_os(self):
        from unittest import mock
        from ql import config
        with mock.patch.object(config, "os_name", return_value="osx"):
            self.assertTrue(config.user_data_dir().replace("\\", "/").endswith("Library/Application Support/QuietLauncher"))
        with mock.patch.object(config, "os_name", return_value="linux"), \
                mock.patch.dict(os.environ, {"XDG_DATA_HOME": "/x/share"}):
            self.assertEqual(config.user_data_dir().replace("\\", "/"), "/x/share/QuietLauncher")

    def test_frozen_unix_does_not_write_next_to_app(self):
        from unittest import mock
        from ql import config
        with mock.patch.object(config, "os_name", return_value="osx"), mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.dict(os.environ, {"QL_HOME": ""}):
            self.assertIn("Application Support", config.default_home())

    def test_mojang_mac_runtime_layout(self):
        from unittest import mock
        from ql import javart
        root = tempfile.mkdtemp()
        exe = os.path.join(root, "jre.bundle", "Contents", "Home", "bin", "java")
        os.makedirs(os.path.dirname(exe))
        open(exe, "w").close()
        with mock.patch.object(javart, "os_name", return_value="osx"):
            self.assertEqual(javart.java_exe(root), exe)

    def test_arm_mac_warning(self):
        from ql import game
        L = game.Lib
        env = {"os": "osx", "arch": "arm64"}
        old = [L("org/lwjgl/lwjgl/3.2.2/lwjgl-3.2.2.jar", None, None, None)]
        new = old + [L("org/lwjgl/lwjgl/3.3.1/lwjgl-3.3.1-natives-macos-arm64.jar", None, None, None)]
        self.assertIn("M1", game.arm_mac_problem(old, env))
        self.assertEqual(game.arm_mac_problem(new, env), "")
        self.assertEqual(game.arm_mac_problem(old, {"os": "windows", "arch": "x86_64"}), "")

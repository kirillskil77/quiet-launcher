import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ql import game, loaders  # noqa: E402
from ql.config import Store  # noqa: E402

WIN = {"os": "windows", "arch": "x86_64", "os_version": "6.1.7601"}


def fake_old_installer(path):
    prof = {
        "install": {"profileName": "Forge", "target": "1.7.10-Forge10.13.4.1614-1.7.10",
                    "path": "net.minecraftforge:forge:1.7.10-10.13.4.1614-1.7.10",
                    "filePath": "forge-1.7.10-10.13.4.1614-1.7.10-universal.jar", "minecraft": "1.7.10"},
        "versionInfo": {
            "id": "1.7.10-Forge10.13.4.1614-1.7.10", "mainClass": "net.minecraft.launchwrapper.Launch",
            "minecraftArguments": "--username ${auth_player_name} --tweakClass cpw.mods.fml.common.launcher.FMLTweaker",
            "jar": "1.7.10",
            "libraries": [
                {"name": "net.minecraftforge:forge:1.7.10-10.13.4.1614-1.7.10"},
                {"name": "org.scala-lang:scala-library:2.10.2", "url": "http://files.minecraftforge.net/maven/"},
                {"name": "net.minecraft:launchwrapper:1.12", "serverreq": True, "clientreq": True},
                {"name": "only:server:1.0", "clientreq": False},
            ]}}
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("install_profile.json", json.dumps(prof))
        zf.writestr("forge-1.7.10-10.13.4.1614-1.7.10-universal.jar", b"JARDATA")


class OldForgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(os.path.join(self.tmp, "home"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_old_installer_is_unpacked_without_running_java(self):
        inst = os.path.join(self.tmp, "forge-installer.jar")
        fake_old_installer(inst)
        vid = loaders.install_old_format(self.store, inst, "1.7.10")
        self.assertEqual(vid, "1.7.10-Forge10.13.4.1614-1.7.10")
        jar = os.path.join(self.store.libraries, "net", "minecraftforge", "forge",
                           "1.7.10-10.13.4.1614-1.7.10", "forge-1.7.10-10.13.4.1614-1.7.10.jar")
        with open(jar, "rb") as f:
            self.assertEqual(f.read(), b"JARDATA")
        data = json.load(open(os.path.join(self.store.versions, vid, vid + ".json")))
        self.assertEqual(data["inheritsFrom"], "1.7.10")
        self.assertNotIn("jar", data)
        names = [l["name"] for l in data["libraries"]]
        self.assertNotIn("only:server:1.0", names)
        scala = [l for l in data["libraries"] if "scala" in l["name"]][0]
        self.assertEqual(scala["url"], "https://maven.minecraftforge.net/")

    def test_resolved_libraries_prefer_forge_and_keep_vanilla(self):
        inst = os.path.join(self.tmp, "i.jar")
        fake_old_installer(inst)
        vid = loaders.install_old_format(self.store, inst, "1.7.10")
        vdir = os.path.join(self.store.versions, "1.7.10")
        os.makedirs(vdir)
        json.dump({"id": "1.7.10", "mainClass": "net.minecraft.client.main.Main", "assets": "1.7.10",
                   "libraries": [{"name": "net.minecraft:launchwrapper:1.5"}, {"name": "com.google.guava:guava:14.0"}]},
                  open(os.path.join(vdir, "1.7.10.json"), "w"))
        v = game.load_version(self.store, vid)
        self.assertEqual(v["mainClass"], "net.minecraft.launchwrapper.Launch")
        libs = game.resolve_libraries(v, WIN)
        paths = [l.path for l in libs]
        self.assertIn("net/minecraft/launchwrapper/1.12/launchwrapper-1.12.jar", paths)
        self.assertNotIn("net/minecraft/launchwrapper/1.5/launchwrapper-1.5.jar", paths)
        self.assertIn("com/google/guava/guava/14.0/guava-14.0.jar", paths)

    def test_signature_stripping_only_for_pre_1_6(self):
        for mc, want in (("1.5.2", True), ("1.4.7", True), ("1.6.4", False), ("1.9", False), ("1.12.2", False), ("1.20.1", False)):
            self.assertEqual(game.needs_unsigned_jar(mc), want, mc)

    def test_unsigned_copy_drops_signatures(self):
        jar = os.path.join(self.tmp, "1.5.2.jar")
        with zipfile.ZipFile(jar, "w") as zf:
            zf.writestr("META-INF/MOJANG_C.SF", "sig")
            zf.writestr("META-INF/MOJANG_C.DSA", "sig")
            zf.writestr("bkf.class", b"\xca\xfe")
            zf.writestr("net/minecraft/client/Minecraft.class", b"\xca\xfe")
        out = game.unsigned_copy(jar)
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        self.assertEqual(sorted(names), ["bkf.class", "net/minecraft/client/Minecraft.class"])
        self.assertEqual(game.unsigned_copy(jar), out)             # второй раз — готовая копия
        with zipfile.ZipFile(jar) as zf:                           # оригинал не тронут
            self.assertIn("META-INF/MOJANG_C.SF", zf.namelist())

    def test_new_format_installer_is_left_to_the_installer(self):
        inst = os.path.join(self.tmp, "new.jar")
        with zipfile.ZipFile(inst, "w") as zf:
            zf.writestr("install_profile.json", json.dumps({"spec": 1, "processors": []}))
        self.assertIsNone(loaders.install_old_format(self.store, inst, "1.20.1"))

    def test_error_shows_installer_output(self):
        tail = []
        code, tail = loaders._run([sys.executable, "-c", "print('a');print('boom');raise SystemExit(1)"],
                                  self.tmp, None, None)
        self.assertEqual(code, 1)
        self.assertEqual(tail[-1], "boom")


if __name__ == "__main__":
    unittest.main()


class LegacyFmlTests(unittest.TestCase):
    def setUp(self):
        import hashlib
        import http.server
        self.tmp = tempfile.mkdtemp()
        self.store = Store(os.path.join(self.tmp, "home"))
        from ql import instances
        self.inst = instances.create_instance(self.store, "old", "1.5.2", "forge", "7.8.0.684")
        self.data = b"PK-deobf-data"
        from ql import legacyfml
        self.lf = legacyfml
        self.saved = dict(legacyfml.DATA)
        legacyfml.DATA["1.5.2"] = ("deobfuscation_data_1.5.2.zip", hashlib.sha1(self.data).hexdigest())
        data = self.data

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path.startswith("/good/"):
                    body = data
                    self.send_response(200)
                else:
                    body = b"<html>404</html>"       # как делает files.minecraftforge.net: страница вместо файла
                    self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        import threading
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]
        self.saved_m = list(legacyfml.MIRRORS)

    def tearDown(self):
        self.srv.shutdown()
        self.lf.DATA.clear()
        self.lf.DATA.update(self.saved)
        self.lf.MIRRORS[:] = self.saved_m
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_downloads_from_second_mirror_and_places_in_both_lib_dirs(self):
        self.lf.MIRRORS[:] = [self.base + "/bad/%s", self.base + "/good/%s"]
        appdata = os.path.join(self.tmp, "appdata")
        self.assertTrue(self.lf.ensure(self.inst, "1.5.2", self.store, appdata=appdata))
        for d in (os.path.join(self.inst.game_dir, "lib"), os.path.join(appdata, ".minecraft", "lib")):
            with open(os.path.join(d, "deobfuscation_data_1.5.2.zip"), "rb") as f:
                self.assertEqual(f.read(), self.data)

    def test_reuses_copy_from_other_launcher_and_fails_cleanly_without_any(self):
        self.lf.MIRRORS[:] = [self.base + "/bad/%s"]
        appdata = os.path.join(self.tmp, "appdata")
        self.assertFalse(self.lf.ensure(self.inst, "1.5.2", self.store, appdata=appdata))
        other = os.path.join(appdata, ".tlauncher", "legacy", "lib")
        os.makedirs(other)
        with open(os.path.join(other, "deobfuscation_data_1.5.2.zip"), "wb") as f:
            f.write(self.data)
        self.assertTrue(self.lf.ensure(self.inst, "1.5.2", self.store, appdata=appdata))
        self.assertTrue(os.path.isfile(os.path.join(appdata, ".minecraft", "lib", "deobfuscation_data_1.5.2.zip")))

    def test_other_versions_are_ignored(self):
        self.assertTrue(self.lf.ensure(self.inst, "1.7.10", self.store, appdata=self.tmp))

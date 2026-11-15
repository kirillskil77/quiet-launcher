import hashlib
import http.server
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import uuid
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ql import auth, endpoints, game, instances, javart, mods, util  # noqa: E402
from ql.config import Store  # noqa: E402

WIN = {"os": "windows", "arch": "x86_64", "os_version": "6.1.7601"}
WIN10 = {"os": "windows", "arch": "x86_64", "os_version": "10.0.19045"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(os.path.join(self.tmp, "home"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class AuthTests(unittest.TestCase):
    def test_offline_uuid_matches_java(self):
        for n in ("Notch", "Steve", "Player_1"):
            md5 = hashlib.md5(("OfflinePlayer:" + n).encode()).digest()
            self.assertEqual(auth.offline_uuid(n), uuid.UUID(bytes=md5, version=3).hex)

    def test_offline_name_validation(self):
        self.assertEqual(auth.new_offline(" Steve ")["name"], "Steve")
        for bad in ("ab", "x" * 17, "имя", "a b", ""):
            with self.assertRaises(auth.AuthError):
                auth.new_offline(bad)

    def test_identity_user_types(self):
        self.assertEqual(auth.identity({"type": "offline", "name": "a", "uuid": "u", "access_token": "0"})["user_type"], "legacy")
        self.assertEqual(auth.identity({"type": "elyby", "name": "a", "uuid": "u", "access_token": "t"})["user_type"], "mojang")
        self.assertEqual(auth.identity({"type": "microsoft", "name": "a", "uuid": "u", "access_token": "t"})["user_type"], "msa")


class RulesTests(unittest.TestCase):
    def test_rules(self):
        rules = [{"action": "allow"}, {"action": "disallow", "os": {"name": "osx"}}]
        self.assertTrue(game.rules_allow(rules, WIN))
        self.assertFalse(game.rules_allow(rules, {"os": "osx", "arch": "x86_64", "os_version": ""}))
        self.assertTrue(game.rules_allow(None, WIN))

    def test_os_version_rule(self):
        rules = [{"action": "allow", "os": {"name": "windows", "version": "^10\\."}}]
        self.assertFalse(game.rules_allow(rules, WIN))
        self.assertTrue(game.rules_allow(rules, WIN10))

    def test_feature_rules_are_off(self):
        rules = [{"action": "allow", "features": {"is_demo_user": True}}]
        self.assertFalse(game.rules_allow(rules, WIN, {}))

    def test_maven_path(self):
        self.assertEqual(game.maven_path("org.lwjgl:lwjgl:3.3.1:natives-windows"),
                         "org/lwjgl/lwjgl/3.3.1/lwjgl-3.3.1-natives-windows.jar")
        self.assertEqual(game.maven_path("a.b:c:1.0@zip"), "a/b/c/1.0/c-1.0.zip")


class VersionTests(Base):
    def _write(self, vid, data):
        d = os.path.join(self.store.versions, vid)
        os.makedirs(d)
        util.write_json(os.path.join(d, vid + ".json"), data)

    def test_inherits_and_libraries(self):
        self._write("1.20.1", {
            "id": "1.20.1", "mainClass": "net.minecraft.client.main.Main", "type": "release",
            "javaVersion": {"component": "java-runtime-gamma", "majorVersion": 17},
            "libraries": [
                {"name": "org.ow2.asm:asm:9.3", "downloads": {"artifact": {"path": "a/asm.jar", "url": "u", "sha1": "x", "size": 1}}},
                {"name": "org.lwjgl:lwjgl:3.3.1:natives-windows", "rules": [{"action": "allow", "os": {"name": "windows"}}],
                 "downloads": {"artifact": {"path": "lwjgl-win.jar", "url": "u2", "sha1": "y", "size": 2}}},
                {"name": "org.lwjgl:lwjgl:3.3.1:natives-linux", "rules": [{"action": "allow", "os": {"name": "linux"}}],
                 "downloads": {"artifact": {"path": "lwjgl-linux.jar", "url": "u3", "sha1": "z", "size": 3}}},
            ],
            "arguments": {"game": ["--username", "${auth_player_name}"], "jvm": ["-cp", "${classpath}"]},
        })
        self._write("fabric-loader-0.15-1.20.1", {
            "id": "fabric-loader-0.15-1.20.1", "inheritsFrom": "1.20.1",
            "mainClass": "net.fabricmc.loader.impl.launch.knot.KnotClient",
            "libraries": [{"name": "org.ow2.asm:asm:9.6", "url": "https://maven.fabricmc.net/"}],
            "arguments": {"game": [], "jvm": ["-DFabricMcEmu= net.minecraft.client.main.Main "]},
        })
        v = game.load_version(self.store, "fabric-loader-0.15-1.20.1")
        self.assertEqual(v["mainClass"], "net.fabricmc.loader.impl.launch.knot.KnotClient")
        self.assertEqual(v["_jar_id"], "1.20.1")
        self.assertEqual(v["javaVersion"]["majorVersion"], 17)
        libs = game.resolve_libraries(v, WIN10)
        paths = [l.path for l in libs]
        # версия asm из загрузчика важнее; linux-natives отброшены
        self.assertIn("org/ow2/asm/asm/9.6/asm-9.6.jar", paths)
        self.assertNotIn("a/asm.jar", paths)
        self.assertIn("lwjgl-win.jar", paths)
        self.assertNotIn("lwjgl-linux.jar", paths)

    def test_build_command_modern_and_legacy(self):
        inst = instances.create_instance(self.store, "Test", "1.20.1")

        class P:
            pass
        p = P()
        p.java, p.classpath, p.natives_dir = "java", ["a.jar", "b.jar"], inst.natives_dir
        p.assets_root = p.game_assets = self.store.assets
        p.log_config = ""
        p.version = {"id": "1.20.1", "type": "release", "mainClass": "Main", "assetIndex": {"id": "5"},
                     "arguments": {"game": ["--username", "${auth_player_name}",
                                            {"rules": [{"action": "allow", "features": {"is_demo_user": True}}], "value": "--demo"}],
                                   "jvm": [{"rules": [{"action": "allow", "os": {"name": "windows"}}], "value": "-Dwin=1"},
                                           "-Djava.library.path=${natives_directory}", "-cp", "${classpath}"]}}
        ident = auth.identity(auth.new_offline("Steve"))
        cmd = game.build_command(self.store, inst, p, ident, agent_jar="/x/authlib.jar")
        self.assertEqual(cmd[0], "java")
        self.assertIn("-javaagent:/x/authlib.jar=ely.by", cmd)
        self.assertIn("Steve", cmd)
        self.assertNotIn("--demo", cmd)
        self.assertEqual(cmd[cmd.index("Main") - 1], cmd[cmd.index("-cp") + 1])  # classpath прямо перед mainClass
        self.assertIn("-Xmx2048M", cmd)
        self.assertIn("-Xms2048M", cmd)             # куча сразу полного размера
        self.assertIn("-XX:+UseG1GC", cmd)
        self.assertIn("-XX:MaxGCPauseMillis=50", cmd)
        self.assertLess(cmd.index("-XX:+UnlockExperimentalVMOptions"), cmd.index("-XX:G1NewSizePercent=20"))
        # свой сборщик мусора пользователя не перебиваем
        self.store.settings["jvm_args"] = "-XX:+UseZGC"
        cmd2 = game.build_command(self.store, inst, p, ident)
        self.assertNotIn("-XX:+UseG1GC", cmd2)
        self.assertIn("-XX:+UseZGC", cmd2)
        # оптимизацию можно выключить
        self.store.settings["jvm_args"] = ""
        self.store.settings["jvm_tuning"] = False
        cmd3 = game.build_command(self.store, inst, p, ident)
        self.assertNotIn("-XX:+UseG1GC", cmd3)
        self.assertIn("-Xms512M", cmd3)
        self.store.settings["jvm_tuning"] = True

        p.version = {"id": "1.8.9", "type": "release", "mainClass": "Main", "assets": "1.8",
                     "minecraftArguments": "--username ${auth_player_name} --uuid ${auth_uuid} --userType ${user_type}"}
        cmd = game.build_command(self.store, inst, p, ident)
        self.assertIn("-cp", cmd)
        self.assertEqual(cmd[-1], "legacy")

    def test_describe_command_hides_token(self):
        text = game.describe_command(["java", "--accessToken", "SECRETTOKEN"], ["SECRETTOKEN"])
        self.assertNotIn("SECRETTOKEN", text)


class InstanceTests(Base):
    def test_create_unique_duplicate_delete(self):
        a = instances.create_instance(self.store, "Моя сборка", "1.20.1", "fabric")
        b = instances.create_instance(self.store, "Моя сборка", "1.20.1")
        self.assertNotEqual(a.folder, b.folder)
        c = instances.duplicate_instance(self.store, a, "Копия")
        self.assertEqual(len(instances.list_instances(self.store)), 3)
        self.assertEqual(c.loader, "fabric")
        instances.delete_instance(b)
        self.assertEqual(len(instances.list_instances(self.store)), 2)
        with self.assertRaises(ValueError):
            instances.create_instance(self.store, "  ", "1.20.1")

    def test_slugify_bad_chars(self):
        self.assertEqual(util.slugify('a:b/c*'), "a_b_c_")
        self.assertEqual(util.slugify("..."), "instance")

    def test_safe_join(self):
        base = os.path.join(self.tmp, "b")
        self.assertTrue(util.safe_join(base, "x/y.txt").startswith(base))
        for bad in ("../x", "a/../../x"):
            with self.assertRaises(ValueError):
                util.safe_join(base, bad)


class _Handler(http.server.BaseHTTPRequestHandler):
    files = {}

    def do_GET(self):
        body = self.files.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class NetTests(Base):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_download_checks_sha1(self):
        data = b"hello world" * 1000
        _Handler.files["/f.bin"] = data
        dest = os.path.join(self.tmp, "d", "f.bin")
        self.assertTrue(util.download(self.base + "/f.bin", dest, hashlib.sha1(data).hexdigest(), len(data)))
        self.assertFalse(util.download(self.base + "/f.bin", dest, hashlib.sha1(data).hexdigest(), len(data)))
        bad = os.path.join(self.tmp, "d", "bad.bin")
        with self.assertRaises(util.HttpError):
            util.download(self.base + "/f.bin", bad, "0" * 40, None, retries=1)
        self.assertFalse(os.path.exists(bad))
        self.assertFalse(os.path.exists(bad + ".part"))

    def test_download_many_and_404(self):
        _Handler.files["/a"] = b"a"
        _Handler.files["/b"] = b"b"
        tasks = [(self.base + "/a", os.path.join(self.tmp, "a"), None, None),
                 (self.base + "/b", os.path.join(self.tmp, "b"), None, None)]
        seen = []
        util.download_many(tasks, lambda d, t: seen.append((d, t)))
        self.assertEqual(seen[-1], (2, 2))
        with self.assertRaises(util.HttpError):
            util.download_many([(self.base + "/nope", os.path.join(self.tmp, "n"), None, None)])

    def test_mrpack_import(self):
        jar = b"PK-fake-mod"
        _Handler.files["/mods/cool.jar"] = jar
        index = {"formatVersion": 1, "game": "minecraft", "name": "Пак", "dependencies": {
            "minecraft": "1.20.1", "fabric-loader": "0.15.0"},
            "files": [{"path": "mods/cool.jar", "hashes": {"sha1": hashlib.sha1(jar).hexdigest()},
                       "downloads": [self.base + "/mods/cool.jar"], "fileSize": len(jar)}]}
        pack = os.path.join(self.tmp, "p.mrpack")
        with zipfile.ZipFile(pack, "w") as z:
            z.writestr("modrinth.index.json", json.dumps(index))
            z.writestr("overrides/config/x.toml", "a=1")
        inst = mods.import_mrpack(self.store, pack)
        self.assertEqual((inst.mc_version, inst.loader, inst.loader_version), ("1.20.1", "fabric", "0.15.0"))
        self.assertTrue(os.path.isfile(os.path.join(inst.mods_dir, "cool.jar")))
        self.assertTrue(os.path.isfile(os.path.join(inst.game_dir, "config", "x.toml")))
        self.assertEqual(inst.mods[0]["filename"], "cool.jar")

    def test_mrpack_zip_slip_is_rejected_and_cleaned(self):
        index = {"name": "evil", "dependencies": {"minecraft": "1.20.1"}, "files": []}
        pack = os.path.join(self.tmp, "e.mrpack")
        with zipfile.ZipFile(pack, "w") as z:
            z.writestr("modrinth.index.json", json.dumps(index))
            z.writestr("overrides/../../evil.txt", "x")
        with self.assertRaises(ValueError):
            mods.import_mrpack(self.store, pack)
        self.assertEqual(instances.list_instances(self.store), [])
        self.assertFalse(os.path.exists(os.path.join(self.store.home, "evil.txt")))

    def test_modrinth_search_and_install(self):
        # подменяем адрес API на локальный сервер
        search = json.dumps({"hits": [{"project_id": "P1", "title": "Sodium"}]}).encode()
        version = [{"id": "V1", "version_type": "release", "files": [
            {"primary": True, "filename": "sodium.jar", "url": self.base + "/sodium.jar",
             "hashes": {"sha1": hashlib.sha1(b"JAR").hexdigest()}, "size": 3}],
            "dependencies": [{"dependency_type": "required", "project_id": "P2"}]}]
        dep_version = [{"id": "V2", "version_type": "release", "files": [
            {"primary": True, "filename": "dep.jar", "url": self.base + "/dep.jar",
             "hashes": {"sha1": hashlib.sha1(b"DEP").hexdigest()}, "size": 3}], "dependencies": []}]
        old = endpoints.MODRINTH_API
        endpoints.MODRINTH_API = self.base + "/v2"
        try:
            class H(_Handler):
                pass
            _Handler.files["/sodium.jar"] = b"JAR"
            _Handler.files["/dep.jar"] = b"DEP"
            # маршруты с параметрами: обработчик сравнивает путь целиком, поэтому подменяем do_GET
            routes = {"/v2/project/P1/version": json.dumps(version).encode(),
                      "/v2/project/P2/version": json.dumps(dep_version).encode(),
                      "/v2/project/P2": json.dumps({"title": "Dep"}).encode()}
            orig = _Handler.do_GET

            def do_GET(h):
                path = h.path.split("?")[0]
                if path == "/v2/search":
                    _Handler.files[h.path] = search
                elif path in routes:
                    _Handler.files[h.path] = routes[path]
                orig(h)
            _Handler.do_GET = do_GET
            try:
                hits = mods.search("sod", "1.20.1", "fabric")
                self.assertEqual(hits[0]["title"], "Sodium")
                inst = instances.create_instance(self.store, "M", "1.20.1", "fabric")
                done = mods.install_mod(inst, "P1", "Sodium")
            finally:
                _Handler.do_GET = orig
        finally:
            endpoints.MODRINTH_API = old
        self.assertEqual([m["filename"] for m in done], ["sodium.jar", "dep.jar"])
        self.assertTrue(os.path.isfile(os.path.join(inst.mods_dir, "dep.jar")))
        mods.remove_mod(inst, inst.mods[0])
        self.assertFalse(os.path.exists(os.path.join(inst.mods_dir, "sodium.jar")))

    def test_vanilla_mods_refused(self):
        inst = instances.create_instance(self.store, "V", "1.20.1")
        with self.assertRaises(mods.ModError):
            mods.install_mod(inst, "P1")


class _KeepAliveHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        http.server.BaseHTTPRequestHandler.setup(self)
        self.server.connections += 1

    def do_GET(self):
        if self.path.startswith("/redir"):
            self.send_response(302)
            self.send_header("Location", "/f0")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = (self.path * 50).encode()
        self.send_response(200 if self.path.startswith("/f") else 404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class KeepAliveTests(Base):
    def test_connections_are_reused_and_redirects_work(self):
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _KeepAliveHandler)
        srv.connections = 0
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        try:
            for i in range(20):
                util.download(base + "/f%d" % i, os.path.join(self.tmp, "k", "f%d" % i))
            self.assertEqual(srv.connections, 1)               # все 20 файлов по одному соединению
            self.assertEqual(open(os.path.join(self.tmp, "k", "f7")).read(), "/f7" * 50)
            util.download(base + "/redir", os.path.join(self.tmp, "k", "r"))   # редирект через urllib
            self.assertEqual(open(os.path.join(self.tmp, "k", "r")).read(), "/f0" * 50)
            with self.assertRaises(util.HttpError):
                util.download(base + "/nope", os.path.join(self.tmp, "k", "n"), retries=1)
        finally:
            srv.shutdown()


class _ZuluHandler(http.server.BaseHTTPRequestHandler):
    routes = {}

    def do_GET(self):
        path = self.path.split("?")[0]
        body = self.routes.get(path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def _fake_zulu_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("zulu21.38.21-ca-jre21.0.5-win_x64/bin/java.exe", "MZ")
        z.writestr("zulu21.38.21-ca-jre21.0.5-win_x64/release", 'JAVA_VERSION="21.0.5"')
    return buf.getvalue()


class ZuluTests(Base):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), _ZuluHandler)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        Base.setUp(self)
        self.saved = (javart.os_name, javart.os_arch, javart.probe, endpoints.AZUL_API, dict(endpoints.ZULU_FALLBACK),
                      javart._system_candidates)
        javart.os_name = lambda: "windows"
        javart.os_arch = lambda: "x86_64"
        javart.probe = lambda p: 21
        endpoints.AZUL_API = self.base + "/api/"
        self.zip = _fake_zulu_zip()
        _ZuluHandler.routes = {
            "/api/": json.dumps([{"download_url": self.base + "/zulu.zip", "package_uuid": "U1"}]).encode(),
            "/api/U1": json.dumps({"sha256_hash": hashlib.sha256(self.zip).hexdigest()}).encode(),
            "/zulu.zip": self.zip,
        }

    def tearDown(self):
        javart.os_name, javart.os_arch, javart.probe, endpoints.AZUL_API, fb, javart._system_candidates = self.saved
        endpoints.ZULU_FALLBACK.update(fb)
        Base.tearDown(self)

    def test_install_and_cache(self):
        seen = []
        exe = javart.ensure_zulu(self.store, progress=lambda *a: seen.append(a))
        self.assertTrue(exe.endswith(os.path.join("zulu-21", "bin", "java.exe")))
        self.assertTrue(os.path.isfile(exe))
        self.assertTrue(os.path.isfile(os.path.join(javart.zulu_root(self.store), "release")))  # верхняя папка срезана
        _ZuluHandler.routes = {}  # второй вызов не должен ходить в сеть
        self.assertEqual(javart.ensure_zulu(self.store), exe)

    def test_fallback_url_when_api_down(self):
        _ZuluHandler.routes.pop("/api/")
        endpoints.ZULU_FALLBACK["x64"] = self.base + "/zulu.zip"
        self.assertTrue(os.path.isfile(javart.ensure_zulu(self.store)))

    def test_wrong_sha256_rejected(self):
        _ZuluHandler.routes["/api/U1"] = json.dumps({"sha256_hash": "0" * 64}).encode()
        with self.assertRaises(util.HttpError):
            javart.ensure_zulu(self.store)
        self.assertFalse(os.path.exists(javart.zulu_root(self.store)))

    def test_not_runnable_is_removed(self):
        javart.probe = lambda p: None
        with self.assertRaises(javart.JavaError):
            javart.ensure_zulu(self.store)
        self.assertFalse(os.path.exists(javart.zulu_root(self.store)))

    def test_zip_slip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("top/bin/java.exe", "MZ")
            z.writestr("top/../../evil.txt", "x")
        zp = os.path.join(self.tmp, "bad.zip")
        open(zp, "wb").write(buf.getvalue())
        with self.assertRaises(ValueError):
            javart._unpack_zip(zp, os.path.join(self.tmp, "root"))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.txt")))

    def test_resolve_policy(self):
        inst = instances.create_instance(self.store, "J", "1.20.5")
        v21 = {"javaVersion": {"component": "java-runtime-delta", "majorVersion": 21}}
        v8 = {"javaVersion": {"component": "jre-legacy", "majorVersion": 8}}
        mojang_works = [True]
        runtime_calls = []
        saved = javart.ensure_runtime, javart.probe

        def runtime(store, component, *a, **k):
            runtime_calls.append(component)
            if runtime_calls[-1] == "BOOM":
                raise javart.JavaError("нет сети")
            return "mojang-java"
        javart.ensure_runtime = runtime
        javart.probe = lambda p: (21 if mojang_works[0] else None) if p == "mojang-java" else 21
        try:
            # Java от Mojang запускается — Zulu даже не скачиваем
            self.assertEqual(javart.resolve_java(self.store, inst, v21), "mojang-java")
            self.assertFalse(os.path.exists(javart.zulu_root(self.store)))
            self.assertEqual(javart.resolve_java(self.store, inst, v8), "mojang-java")
            # Mojang не запускается (как на части Windows 7) — Zulu
            mojang_works[0] = False
            msgs = []
            self.assertIn("zulu-21", javart.resolve_java(self.store, inst, v21, log=msgs.append))
            self.assertTrue(any("не запускается" in m for m in msgs))
            # Mojang не скачалась — тоже Zulu
            mojang_works[0] = True
            vboom = {"javaVersion": {"component": "BOOM", "majorVersion": 21}}
            self.assertIn("zulu-21", javart.resolve_java(self.store, inst, vboom))
            # Zulu выключена — Mojang возвращается как есть
            mojang_works[0] = False
            self.store.settings["use_zulu"] = False
            self.assertEqual(javart.resolve_java(self.store, inst, v21), "mojang-java")
            # свой путь важнее всего
            mine = os.path.join(self.tmp, "myjava.exe")
            open(mine, "w").close()
            inst.java_path = mine
            self.assertEqual(javart.resolve_java(self.store, inst, v21), mine)
        finally:
            javart.ensure_runtime, javart.probe = saved

    def test_all_fail_falls_back_to_system_java(self):
        _ZuluHandler.routes = {}
        inst = instances.create_instance(self.store, "J", "1.20.5")
        saved = javart.ensure_runtime, javart.find_system_javas
        javart.ensure_runtime = lambda *a, **k: (_ for _ in ()).throw(javart.JavaError("нет сети"))
        javart.find_system_javas = lambda: [("sys-java", 21)]
        msgs = []
        try:
            endpoints.ZULU_FALLBACK["x64"] = self.base + "/missing.zip"
            v = {"javaVersion": {"component": "java-runtime-delta", "majorVersion": 21}}
            self.assertEqual(javart.resolve_java(self.store, inst, v, log=msgs.append), "sys-java")
        finally:
            javart.ensure_runtime, javart.find_system_javas = saved
        self.assertTrue(any("Zulu недоступна" in m for m in msgs))

    def test_detect_javas(self):
        os.environ["APPDATA"] = os.path.join(self.tmp, "appdata")
        d = os.path.join(os.environ["APPDATA"], ".tlauncher", "legacy", "Minecraft", "runtime", "x", "bin")
        os.makedirs(d)
        open(os.path.join(d, "java.exe"), "w").close()
        skip = os.path.join(os.environ["APPDATA"], ".tlauncher", "legacy", "Minecraft", "mods", "bin")
        os.makedirs(skip)
        open(os.path.join(skip, "java.exe"), "w").close()
        javart.ensure_zulu(self.store)
        javart._system_candidates = lambda: []
        found = javart.detect_javas(self.store)
        sources = sorted(j["source"] for j in found)
        self.assertEqual(sources, ["Другой лаунчер", "Лаунчер"])
        self.assertTrue(all(j["major"] == 21 for j in found))


if __name__ == "__main__":
    unittest.main()

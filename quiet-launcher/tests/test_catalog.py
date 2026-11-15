import hashlib
import http.server
import io
import json
import os
import shutil
import struct
import sys
import tempfile
import threading
import unittest
import urllib.parse
import zlib
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ql import endpoints, instances, mods  # noqa: E402
from ql.config import Store  # noqa: E402


def tiny_png(w=40, h=24, rgb=(60, 140, 100)):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def ch(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
            ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b""))


def make_mrpack():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("modrinth.index.json", json.dumps({
            "name": "Тестовая сборка", "dependencies": {"minecraft": "1.20.1", "fabric-loader": "0.15.0"}, "files": []}))
        zf.writestr("overrides/options.txt", "lang:ru_ru")
    return buf.getvalue()


FILES = {"/files/pack.zip": b"RESOURCEPACK", "/files/shader.zip": b"SHADER", "/files/mod.jar": b"MODJAR",
         "/files/pack.mrpack": make_mrpack(), "/img/a.png": tiny_png()}
CALLS = []


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        base = "http://127.0.0.1:%d" % self.server.server_address[1]
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        CALLS.append(self.path)
        if u.path == "/api/search":
            facets = json.loads(q["facets"][0])
            kind = facets[0][0].split(":")[1]
            body = json.dumps({"hits": [{"project_id": kind + "1", "title": "Hit " + kind, "author": "me",
                                         "downloads": 1234567, "description": "d", "slug": kind + "-slug"}]})
        elif u.path.startswith("/api/project/") and u.path.endswith("/version"):
            pid = u.path.split("/")[3]
            f = {"resourcepack1": "pack.zip", "shader1": "shader.zip", "mod1": "mod.jar", "modpack1": "pack.mrpack"}[pid]
            if "game_versions" in q and json.loads(q["game_versions"][0]) == ["0.0"]:
                body = "[]"
            else:
                body = json.dumps([{"id": "v-" + pid, "version_type": "release", "dependencies": [],
                                    "files": [{"primary": True, "filename": f, "url": base + "/files/" + f,
                                               "hashes": {}, "size": len(FILES["/files/" + f])}]}])
        elif u.path.startswith("/api/project/"):
            body = json.dumps({"title": "T", "body": "# Hi\n![x](http://x/y.png)\n**bold** [link](http://a)",
                               "gallery": [{"url": base + "/img/a.png", "featured": False, "ordering": 1, "title": "second"},
                                           {"url": base + "/img/a.png", "featured": True, "ordering": 2, "title": "first"}]})
        elif u.path in FILES:
            data = FILES[u.path]
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        else:
            self.send_response(404)
            self.end_headers()
            return
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.saved = endpoints.MODRINTH_API
        endpoints.MODRINTH_API = "http://127.0.0.1:%d/api" % cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        endpoints.MODRINTH_API = cls.saved
        cls.srv.shutdown()

    def setUp(self):
        mods._cache.clear()
        self.tmp = tempfile.mkdtemp()
        self.store = Store(os.path.join(self.tmp, "home"))
        self.inst = instances.create_instance(self.store, "t", "1.20.1", "fabric", "0.15.0")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_search_kinds_and_cache(self):
        for kind in mods.KINDS:
            self.assertEqual(mods.search("", "1.20.1", "fabric", kind=kind)[0]["project_id"], kind + "1")
        n = len(CALLS)
        mods.search("", "1.20.1", "fabric", kind="mod")
        self.assertEqual(len(CALLS), n)                         # второй раз — из кеша

    def test_install_each_kind_into_its_folder(self):
        mods.install_mod(self.inst, "mod1", "M")
        mods.install_mod(self.inst, "resourcepack1", "RP", kind="resourcepack")
        mods.install_mod(self.inst, "shader1", "SH", kind="shader")
        g = self.inst.game_dir
        self.assertTrue(os.path.isfile(os.path.join(g, "mods", "mod.jar")))
        self.assertTrue(os.path.isfile(os.path.join(g, "resourcepacks", "pack.zip")))
        self.assertTrue(os.path.isfile(os.path.join(g, "shaderpacks", "shader.zip")))
        kinds = sorted(mods.entry_kind(e) for e in self.inst.mods)
        self.assertEqual(kinds, ["mod", "resourcepack", "shader"])
        rp = [e for e in self.inst.mods if mods.entry_kind(e) == "resourcepack"][0]
        mods.remove_mod(self.inst, rp)
        self.assertFalse(os.path.exists(os.path.join(g, "resourcepacks", "pack.zip")))
        self.assertTrue(os.path.isfile(os.path.join(g, "mods", "mod.jar")))

    def test_resourcepack_ignores_loader_and_vanilla_instance(self):
        van = instances.create_instance(self.store, "v", "1.20.1")
        mods.install_mod(van, "resourcepack1", "RP", kind="resourcepack")
        self.assertTrue(os.path.isfile(os.path.join(van.game_dir, "resourcepacks", "pack.zip")))
        with self.assertRaises(mods.ModError):
            mods.install_mod(van, "mod1", "M")

    def test_no_compatible_version_message(self):
        bad = instances.create_instance(self.store, "old", "0.0", "fabric", "1")
        with self.assertRaises(mods.ModError) as c:
            mods.install_mod(bad, "resourcepack1", "RP", kind="resourcepack")
        self.assertIn("0.0", str(c.exception))

    def test_modpack_becomes_instance(self):
        inst = mods.install_modpack(self.store, "modpack1", "P")
        self.assertEqual((inst.mc_version, inst.loader), ("1.20.1", "fabric"))
        self.assertTrue(os.path.isfile(os.path.join(inst.game_dir, "options.txt")))

    def test_project_page_and_images(self):
        info = mods.project_info("mod1")
        self.assertEqual(len(info["gallery"]), 2)
        p = mods.fetch_image(info["gallery"][0]["url"], self.store.cache)
        self.assertTrue(os.path.getsize(p) > 50)
        self.assertEqual(mods.fetch_image(info["gallery"][0]["url"], self.store.cache), p)

    def test_plain_text(self):
        from ql.browse import plain_text
        t = plain_text(FILES and "# Hi\n![x](http://x/y.png)\n**bold** [link](http://a)\n<p>x</p>")
        self.assertNotIn("http", t)
        self.assertIn("Hi", t)
        self.assertIn("bold link", t)


if __name__ == "__main__":
    unittest.main()

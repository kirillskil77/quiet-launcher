import hashlib
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ql import updater, util  # noqa: E402

PAYLOAD = b"MZ-fake-installer" * 1000
SHA = hashlib.sha256(PAYLOAD).hexdigest()
STATE = {"digest": "sha256:" + SHA, "tag": "v9.9.9", "draft": False, "noexe": False}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        base = "http://127.0.0.1:%d" % self.server.server_address[1]
        if self.path == "/api/latest":
            assets = [{"name": "QuietLauncher-Setup.exe", "size": len(PAYLOAD), "digest": STATE["digest"],
                       "browser_download_url": base + "/dl/QuietLauncher-Setup.exe"},
                      {"name": "source.zip", "browser_download_url": base + "/x"}]
            if STATE["noexe"]:
                assets = assets[1:]
            if STATE["digest"] is None:
                assets.append({"name": "QuietLauncher-Setup.exe.sha256", "browser_download_url": base + "/dl/sha"})
            body = json.dumps({"tag_name": STATE["tag"], "body": "## Что нового\n- раз\n- два", "draft": STATE["draft"],
                               "html_url": base + "/rel", "assets": assets}).encode()
        elif self.path == "/dl/QuietLauncher-Setup.exe":
            body = PAYLOAD
        elif self.path == "/dl/sha":
            body = (SHA + "  QuietLauncher-Setup.exe\n").encode()
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class UpdaterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.api = "http://127.0.0.1:%d/api/latest" % cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        STATE.update(digest="sha256:" + SHA, tag="v9.9.9", draft=False, noexe=False)
        self.tmp = tempfile.mkdtemp()
        self._gt, updater.tempfile.gettempdir = updater.tempfile.gettempdir, lambda: self.tmp

    def tearDown(self):
        updater.tempfile.gettempdir = self._gt
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_version_compare(self):
        self.assertTrue(updater.is_newer("1.10.0", "1.9.9"))
        self.assertTrue(updater.is_newer("1.3.1", "1.3"))
        self.assertFalse(updater.is_newer("1.3.0", "1.3"))
        self.assertFalse(updater.is_newer("1.2.9", "1.3.0"))
        self.assertFalse(updater.is_newer("", "1.0.0"))

    def test_finds_newer_release(self):
        info = updater.check({}, self.api, local="1.3.0")
        self.assertEqual(info["version"], "9.9.9")
        self.assertEqual(info["sha256"], SHA)
        self.assertTrue(info["url"].endswith("QuietLauncher-Setup.exe"))
        self.assertIn("раз", info["notes"])

    def test_same_version_and_draft_are_ignored(self):
        self.assertIsNone(updater.check({}, self.api, local="9.9.9"))
        STATE["draft"] = True
        self.assertIsNone(updater.check({}, self.api, local="1.0.0"))

    def test_checksum_from_side_file(self):
        STATE["digest"] = None
        self.assertEqual(updater.fetch_latest(self.api)["sha256"], SHA)

    def test_download_verifies_hash(self):
        info = updater.fetch_latest(self.api)
        path = updater.download_installer(info)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), PAYLOAD)
        info["sha256"] = "0" * 64
        with self.assertRaises(Exception):
            updater.download_installer(info)

    def test_check_throttle(self):
        s = {"check_updates": True, "update_checked": time.time()}
        self.assertFalse(updater.due(s))
        s["update_checked"] = time.time() - 5 * 3600
        self.assertTrue(updater.due(s))
        s["check_updates"] = False
        self.assertFalse(updater.due(s))

    def test_unreachable_server_raises_quickly(self):
        t = time.time()
        with self.assertRaises(Exception):
            updater.fetch_latest("http://127.0.0.1:9/none")
        self.assertLess(time.time() - t, 6)

    def test_failed_check_does_not_start_pause(self):
        s = {"check_updates": True, "update_checked": 0}
        with self.assertRaises(Exception):
            updater.check(s, "http://127.0.0.1:9/none")
        self.assertEqual(s["update_checked"], 0)                    # следующая попытка — при ближайшем запуске
        self.assertTrue(updater.due(s))
        updater.check(s, self.api, local="1.0.0")
        self.assertFalse(updater.due(s))

    def test_report_explains_every_case(self):
        info, text = updater.check_report(self.api, local="1.0.0")
        self.assertIsNotNone(info)
        self.assertIn("9.9.9", text)
        info, text = updater.check_report(self.api, local="9.9.9")
        self.assertIsNone(info)
        self.assertIn("последняя версия", text)
        STATE["draft"] = True
        info, text = updater.check_report(self.api, local="1.0.0")
        self.assertIsNone(info)
        self.assertIn("черновик", text)
        STATE.update(draft=False, noexe=True)
        info, text = updater.check_report(self.api, local="1.0.0")
        self.assertIsNone(info)
        self.assertIn("нет файла установщика", text)
        info, text = updater.check_report("http://127.0.0.1:9/none", local="1.0.0")
        self.assertIsNone(info)
        self.assertIn("Не удалось связаться", text)


if __name__ == "__main__":
    unittest.main()

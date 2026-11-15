"""Клиент «Друзья» против настоящего worker.js, запущенного локально на Node (если Node 22+ есть)."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ql import friends, instances  # noqa: E402
from ql.config import Store  # noqa: E402

SERVER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server", "dev_server.mjs")


def node_ok():
    exe = shutil.which("node")
    if not exe:
        return None
    try:
        out = subprocess.check_output([exe, "--version"]).decode().strip().lstrip("v")
        return exe if int(out.split(".")[0]) >= 22 else None
    except Exception:
        return None


@unittest.skipUnless(node_ok(), "нужен Node 22+")
class FriendsClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proc = subprocess.Popen([node_ok(), "--no-warnings", SERVER, "0"], stdout=subprocess.PIPE)
        line = cls.proc.stdout.readline().decode().strip()
        cls.base = "http://127.0.0.1:%s" % line.split()[-1]

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def client(self, name):
        return friends.Friends(Store(os.path.join(self.tmp, name)), base=self.base)

    def test_full_flow(self):
        a, b = self.client("a"), self.client("b")
        self.assertFalse(a.registered)
        with self.assertRaises(friends.FriendsError):
            a.overview()
        a.register("Alice")
        b.register("Bob")
        self.assertTrue(friends.Friends(Store(os.path.join(self.tmp, "a")), base=self.base).registered)   # профиль сохранён
        with self.assertRaises(friends.FriendsError) as ctx:
            a.request_friend("QL-ZZZZZZ")
        self.assertIn("не найден", str(ctx.exception))
        a.request_friend(b.profile["code"])
        inc = b.overview()["incoming"]
        self.assertEqual([u["nick"] for u in inc], ["Alice"])
        b.respond(inc[0]["id"], True)
        fa = a.overview()["friends"]
        self.assertEqual(fa[0]["nick"], "Bob")
        # список модов: сначала закрыт, потом открыт
        store = Store(os.path.join(self.tmp, "s"))
        inst = instances.create_instance(store, "T", "1.20.1", "fabric", "0.15.0")
        inst.mods = [{"project_id": "AANobbMI", "title": "Sodium"}, {"project_id": "P7dR8mSH", "title": "Fabric API"},
                     {"project_id": "AANobbMI", "title": "dup"}, {"title": "без id"}]
        proj = friends.collect_projects([inst])
        self.assertEqual([p["id"] for p in proj], ["AANobbMI", "P7dR8mSH"])
        a.update(projects=proj)
        self.assertFalse(b.projects_of(a.profile["id"])["shared"])
        a.update(share_mods=True)
        got = b.projects_of(a.profile["id"])
        self.assertTrue(got["shared"])
        self.assertEqual([p["title"] for p in got["projects"]], ["Sodium", "Fabric API"])
        # удаление аккаунта и потеря профиля
        b.delete_account()
        self.assertFalse(b.registered)
        self.assertEqual(a.overview()["friends"], [])

    def test_bad_nick_message_and_lost_profile(self):
        c = self.client("c")
        with self.assertRaises(friends.FriendsError) as ctx:
            c.register("x")
        self.assertIn("Ник", str(ctx.exception))
        c.register("Carol")
        c.profile["key"] = "0" * 64
        with self.assertRaises(friends.FriendsError) as ctx:
            c.overview()
        self.assertIn("Профиль не найден", str(ctx.exception))

    def test_no_connection(self):
        c = friends.Friends(Store(os.path.join(self.tmp, "d")), base="http://127.0.0.1:1")
        with self.assertRaises(friends.FriendsError) as ctx:
            c.register("Dave")
        self.assertIn("связи", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

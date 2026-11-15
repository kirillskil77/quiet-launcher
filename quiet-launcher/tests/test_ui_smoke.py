"""Проверка окна. Включается переменной QL_UI_TEST=1 (на Windows или под xvfb-run)."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@unittest.skipUnless(os.environ.get("QL_UI_TEST"), "задайте QL_UI_TEST=1")
class UiSmoke(unittest.TestCase):
    def test_window_builds_and_dialogs_open(self):
        from ql.config import Store
        from ql.ui import App
        from ql import instances, auth
        from ql.dialogs import AccountsDialog, SettingsDialog, NewInstanceDialog, MsDialog

        tmp = tempfile.mkdtemp()
        try:
            store = Store(os.path.join(tmp, "h"))
            store.accounts.append(auth.new_offline("Steve"))
            instances.create_instance(store, "Тест", "1.20.1", "fabric", "0.15.0")
            app = App(store)
            app.update()
            self.assertEqual(len(app.insts), 1)
            self.assertEqual(app.current.name, "Тест")
            self.assertEqual(app.current_account()["name"], "Steve")
            self.assertEqual(str(app.play_btn.cget("state")), "normal")
            for cls in (AccountsDialog, SettingsDialog, MsDialog):
                d = cls(app)
                d.update()
                d.destroy()
            d = NewInstanceDialog(app)
            d.update()
            d.destroy()
            from ql.dialogs import IconDialog, UpdatedDialog
            from ql.backup import BackupsDialog
            from ql.ui import LAYOUTS
            for cls in (IconDialog, BackupsDialog):
                d = cls(app)
                d.update()
                d.destroy()
            d = UpdatedDialog(app, "1.3.2")
            d.update()
            d.close()
            for name in LAYOUTS:                      # все раскладки применяются на лету
                app.set_layout(name)
                app.update()
            self.assertEqual(app.store.settings["layout"], "compact")
            app.destroy()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

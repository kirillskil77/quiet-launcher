import logging
import os
import sys


def _dpi_awareness():
    if os.name != "nt":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)      # Windows 8.1+
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()       # Windows 7
        except Exception:
            pass


def main():
    _dpi_awareness()
    from ql.config import Store
    from ql import theme

    store = Store()
    theme.configure(store.settings.get("theme"), store.settings.get("accent"))
    from ql.ui import App
    handler = logging.FileHandler(os.path.join(store.home, "launcher.log"), encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    App(store).mainloop()


if __name__ == "__main__":
    sys.exit(main())

"""Versioned source entry; original sidequest.py and V9 remain unchanged."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "ui"), str(ROOT / "engine")]

if __name__ == "__main__":
    try:
        import ctl
        if ctl._discover("quest_window"):
            raise RuntimeError("旧面板仍在运行。请使用 launch_sidequest_v10.ps1 -ReplacePanel 切换；后台和任务数据会保留。")
        from quest_window_v10_2 import main
        raise SystemExit(main())
    except Exception as exc:
        import logging
        import ctypes
        logging.basicConfig(filename=ROOT / "engine" / "panel_v10_error.log", level=logging.INFO, encoding="utf-8")
        logging.exception("V10 failed to start")
        ctypes.windll.user32.MessageBoxW(None, str(exc)+"\n详情：engine/panel_v10_error.log", "SideQuest V10 启动失败", 0x10)
        raise SystemExit(1)

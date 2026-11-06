"""Open the existing detailed settings, without starting any workers or model calls."""
import sys
import json
from pathlib import Path
import tkinter as tk

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "engine"), str(ROOT / "ui")]
import quest_window as legacy
from settings_window import SettingsWindow, palette_from

if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    saved = legacy.load_ui()
    try:
        prefs = json.loads((ROOT / "config" / "ui_v10.json").read_text(encoding="utf-8"))
        saved["skin"] = prefs.get("skin", saved.get("skin"))
    except (OSError, ValueError):
        pass
    window = SettingsWindow(root, palette_from(legacy.SKINS.get(saved.get("skin"), legacy.SKINS["glass"])))
    window.top.bind("<Destroy>", lambda event: root.quit() if event.widget is window.top else None)
    root.mainloop()
    root.destroy()

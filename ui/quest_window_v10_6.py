"""V10.6 priority typography and progress colors; task and timing rules unchanged."""
import ctypes
from ctypes import wintypes
import hashlib
import logging
from pathlib import Path
from v10_bridge_v10_5 import Bridge,ROOT
from quest_window_v10_5 import DwellDesktop


def main():
    import webview
    mutex_name = "Local\\SideQuestV10_" + hashlib.sha256(str(ROOT).lower().encode()).hexdigest()[:20]
    kernel = ctypes.windll.kernel32
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    mutex = kernel.CreateMutexW(None, False, mutex_name)
    if kernel.GetLastError() == 183:
        return 0
    logs = ROOT / "engine" / "panel_v10_error.log"
    logging.basicConfig(filename=logs, level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(message)s")
    desktop = DwellDesktop()
    for screen in webview.screens:
        scale = getattr(screen, "scale", 1.)
        frame = getattr(screen, "frame", None)
        desktop._screens.append({"left": getattr(frame, "Left", screen.x), "top": getattr(frame, "Top", screen.y),
                                  "right": getattr(frame, "Right", screen.x+screen.width),
                                  "bottom": getattr(frame, "Bottom", screen.y+screen.height),
                                  "origin_x": screen.x, "origin_y": screen.y,
                                  "scale": scale, "physical_x": getattr(screen, "physical_x", screen.x*scale),
                                  "physical_y": getattr(screen, "physical_y", screen.y*scale),
                                  "physical_w": getattr(screen, "physical_width", screen.width*scale),
                                  "physical_h": getattr(screen, "physical_height", screen.height*scale)})
    if not desktop._screens:
        raise RuntimeError("未检测到可用显示器")
    bridge = Bridge(controller=desktop)
    desktop._bridge = bridge
    prefs = bridge._prefs
    screen = desktop._screens[0]
    desktop._width = max(300, min(prefs.get("width", 336), screen["right"]-screen["left"]))
    desktop._height_cap = max(240, min(prefs.get("height", 620), screen["bottom"]-screen["top"]-40))
    desktop._height = desktop._target_h = desktop._restore_h = desktop._height_cap
    desktop._x = prefs.get("x", screen["right"]-desktop._width-24)
    desktop._y = prefs.get("y", screen["top"]+36)
    # Clamp stale/off-screen saved positions after monitor changes.
    screen = desktop._screen()
    desktop._x = max(screen["left"], min(desktop._x, screen["right"]-desktop._width))
    desktop._y = max(screen["top"], min(desktop._y, screen["bottom"]-80))
    desktop._auto_hide = bool(prefs.get("autoHide", True))
    desktop._pinned = bool(prefs.get("pinned", True))
    desktop._side = prefs.get("edgeSide") if prefs.get("edgeSide") in ("left", "right") else None
    assets = ROOT / "ui" / "web_v10"
    html = (assets / "index.html").read_text(encoding="utf-8")
    html = html.replace("/*__LOCAL_CSS__*/", (assets / "approved.css").read_text(encoding="utf-8"))
    html = html.replace("/*__RUNTIME_CSS__*/", (assets / "desktop_v10_6.css").read_text(encoding="utf-8"))
    html = html.replace("/*__LOCAL_ICONS__*/", (assets / "vendor" / "lucide.min.js").read_text(encoding="utf-8"))
    html = html.replace("/*__LOCAL_APP__*/", (assets / "desktop_v10_6.js").read_text(encoding="utf-8"))
    desktop._window = webview.create_window(
        "SideQuest V10", html=html, js_api=bridge, width=round(desktop._width), height=round(desktop._height),
        x=round(desktop._x), y=round(desktop._y), frameless=True, easy_drag=False, resizable=False,
        on_top=desktop._pinned, min_size=(300, 80), text_select=True, background_color="#14171f")
    desktop._window.events.loaded += desktop._loaded_event
    desktop._window.events.closed += desktop._closed_event
    try:
        webview.start(desktop._run, gui="edgechromium", debug=False, private_mode=True)
    finally:
        desktop._stop.set()
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle(mutex)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

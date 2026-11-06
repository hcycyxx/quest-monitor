"""SideQuest V10: approved local HTML in a frameless Windows WebView2 host."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import hashlib
import logging
import math
import os
from pathlib import Path
import sys
import threading
import time

from v10_bridge import Bridge, ROOT, read_json


class Desktop:
    def __init__(self):
        self._lock = threading.RLock()
        self._window = None
        self._bridge = None
        self._stop = threading.Event()
        self._loaded = False
        self._tray = None
        self._hidden = False
        self._closing = False
        self._hold = False
        self._gesture = False
        self._hovered = True
        self._side = None
        self._edge_hidden = False
        self._auto_hide = True
        self._leave_since = None
        self._target_x = None
        self._velocity_x = 0.
        self._target_h = 620.
        self._velocity_h = 0.
        self._x, self._y, self._width, self._height = 0., 36., 336., 620.
        self._height_cap = 620
        self._restore_h = 620
        self._minimized = False
        self._last_size = None
        self._last_pos = None
        self._pinned = True
        self._screens = []

    def state(self):
        with self._lock:
            return {"x": round(self._x), "y": round(self._y), "width": round(self._width),
                    "height": round(self._height), "heightCap": self._height_cap,
                    "edgeSide": self._side, "edgeHidden": self._edge_hidden,
                    "autoHide": self._auto_hide, "pinned": self._pinned,
                    "minimized": self._minimized, "trayAvailable": self._tray is not None}

    def _screen(self, x=None, y=None):
        x = self._x + self._width / 2 if x is None else x
        y = self._y + 24 if y is None else y
        for screen in self._screens:
            if screen["left"] <= x < screen["right"] and screen["top"] <= y < screen["bottom"]:
                return screen
        return min(self._screens, key=lambda s: (max(s["left"]-x, 0, x-s["right"]))**2
                   + (max(s["top"]-y, 0, y-s["bottom"]))**2)

    def _cursor(self):
        point = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
        for screen in self._screens:
            px, py, scale = screen["physical_x"], screen["physical_y"], screen["scale"]
            if px <= point.x < px+screen["physical_w"] and py <= point.y < py+screen["physical_h"]:
                return (screen.get("origin_x", screen["left"])+(point.x-px)/scale,
                        screen.get("origin_y", screen["top"])+(point.y-py)/scale)
        return point.x, point.y

    def configure(self, patch):
        with self._lock:
            if "pinned" in patch:
                self._pinned = bool(patch["pinned"])
                if self._window:
                    self._window.on_top = self._pinned
            if "autoHide" in patch:
                self._auto_hide = bool(patch["autoHide"])
                if not self._auto_hide:
                    self._reveal()
            if "height" in patch:
                self._height_cap = int(patch["height"])
            if "edgeSide" in patch:
                self._side = patch["edgeSide"]
                self._dock(self._side)

    def _persist_geometry(self):
        self._bridge.preferences({"x": round(self._x), "y": round(self._y),
                                  "width": round(self._width), "height": self._height_cap})

    def _publish(self):
        if self._loaded and not self._closing:
            try:
                self._window.evaluate_js("window.sidequestDesktop && window.sidequestDesktop(" +
                                         json.dumps(self.state()) + ")")
            except Exception:
                logging.exception("V10 desktop state notification failed")

    def _dock(self, side):
        if side not in ("left", "right"):
            self._side = None
            self._target_x = None
            return
        screen = self._screen()
        self._side = side
        self._edge_hidden = False
        self._target_x = screen["left"] if side == "left" else screen["right"] - self._width
        self._leave_since = time.monotonic()

    def _reveal(self):
        if not self._side:
            return
        screen = self._screen()
        changed = self._edge_hidden
        self._edge_hidden = False
        self._target_x = screen["left"] if self._side == "left" else screen["right"]-self._width
        self._target_h = self._restore_h
        self._leave_since = None
        if changed:
            self._publish()

    def action(self, name, payload=None):
        try:
            with self._lock:
                payload = payload if isinstance(payload, dict) else {}
                if name == "fit":
                    value = payload.get("height")
                    if type(value) not in (int, float) or not math.isfinite(value):
                        raise ValueError("窗口高度不正确")
                    if not self._gesture and not self._edge_hidden:
                        screen = self._screen()
                        cap = min(self._height_cap, screen["bottom"]-self._y)
                        self._target_h = max(80, min(float(value), cap))
                        self._restore_h = self._target_h
                elif name == "geometry":
                    phase = payload.get("phase")
                    if phase not in ("move", "resize", "end"):
                        raise ValueError("窗口操作不正确")
                    for key in ("x", "y", "width", "height"):
                        if key in payload and (type(payload[key]) not in (int, float)
                                               or not math.isfinite(payload[key]) or abs(payload[key]) > 100000):
                            raise ValueError("窗口位置不正确")
                    if phase != "end":
                        self._gesture = True
                        self._target_x = None
                        self._velocity_x = self._velocity_h = 0
                        self._side = None
                        self._edge_hidden = False
                        self._x = float(payload.get("x", self._x))
                        self._y = float(payload.get("y", self._y))
                        screen = self._screen()
                        self._width = max(300, min(float(payload.get("width", self._width)), screen["right"]-screen["left"]))
                        self._x = max(screen["left"], min(self._x, screen["right"]-self._width))
                        self._y = max(screen["top"], min(self._y, screen["bottom"]-80))
                        if phase == "resize":
                            self._height = max(240, min(float(payload.get("height", self._height)), screen["bottom"]-self._y))
                            self._height_cap = round(self._height)
                        self._target_h = self._height
                        self._apply()
                    else:
                        self._gesture = False
                        screen = self._screen()
                        if payload.get("dock", True):
                            left = abs(self._x-screen["left"])
                            right = abs(self._x+self._width-screen["right"])
                            if min(left, right) <= 24:
                                self._dock("left" if left <= right else "right")
                        self._persist_geometry()
                        self._bridge.preferences({"edgeSide": self._side})
                elif name == "hold":
                    self._hold = bool(payload.get("active"))
                    self._leave_since = None
                elif name == "hover":
                    self._hovered = bool(payload.get("inside"))
                    if self._hovered:
                        self._reveal()
                    else:
                        self._leave_since = time.monotonic()
                elif name == "dock":
                    self._bridge.preferences({"edgeSide": payload.get("side")})
                elif name == "minimize":
                    self._reveal()
                    self._minimized = not self._minimized
                elif name == "hide":
                    if self._tray is None:
                        raise ValueError("托盘不可用，请使用最小化，避免找不到窗口")
                    self._hidden = True
                    self._window.hide()
                elif name == "show":
                    self._hidden = False
                    self._window.show()
                    self._window.restore()
                    self._reveal()
                elif name == "reveal":
                    self._reveal()
                elif name == "reset":
                    screen = self._screen()
                    self._side = None
                    self._edge_hidden = False
                    self._target_x = None
                    self._width = 336
                    self._height_cap = 620
                    self._x, self._y = screen["right"]-360, screen["top"]+36
                    self._bridge.preferences({"edgeSide": None, "width": 336, "height": 620})
                    self._persist_geometry()
                elif name == "quit":
                    # Exit uses the same worker-stop behavior as V9's tray Quit.
                    import ctl
                    ctl.stop_workers()
                    self._closing = True
                    self._window.destroy()
                else:
                    raise ValueError("未知窗口操作")
                self._publish()
                return {"ok": True, "desktop": self.state()}
        except Exception as exc:
            logging.exception("V10 window action failed: %s", name)
            return {"ok": False, "error": str(exc)[:200]}

    @staticmethod
    def _spring(x, velocity, target, dt):
        omega = 10.5
        offset = x-target
        coefficient = velocity+omega*offset
        decay = math.exp(-omega*dt)
        new_x = target+(offset+coefficient*dt)*decay
        new_v = (velocity-omega*coefficient*dt)*decay
        return (target, 0.) if abs(new_x-target) < .4 and abs(new_v) < 4 else (new_x, new_v)

    def _apply(self):
        size = (round(self._width), round(self._height))
        pos = (round(self._x), round(self._y))
        if size != self._last_size:
            self._window.resize(*size)
            self._last_size = size
            self._round_corners()
        if pos != self._last_pos:
            self._window.move(*pos)
            self._last_pos = pos

    def _round_corners(self):
        try:
            hwnd = int(self._window.native.Handle.ToInt64())
            user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
            rect = wintypes.RECT()
            user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            user.GetWindowRect(hwnd, ctypes.byref(rect))
            user.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
            gdi.CreateRoundRectRgn.argtypes = [ctypes.c_int]*6
            gdi.CreateRoundRectRgn.restype = wintypes.HRGN
            gdi.DeleteObject.argtypes = [wintypes.HGDIOBJ]
            scale = self._screen()["scale"]
            radius = round(28*scale)
            region = gdi.CreateRoundRectRgn(0, 0, rect.right-rect.left+1, rect.bottom-rect.top+1, radius, radius)
            if region and not user.SetWindowRgn(hwnd, region, True):
                gdi.DeleteObject(region)
        except Exception:
            logging.debug("Native rounded region unavailable", exc_info=True)

    def _loaded_event(self):
        self._loaded = True
        self._round_corners()
        try:
            import tray
            self._tray = tray.Tray({})
            if not self._tray.start():
                self._tray = None
        except Exception:
            logging.exception("V10 tray unavailable")
            self._tray = None
        self._publish()

    def _closed_event(self):
        self._stop.set()
        if not self._closing:
            import ctl
            ctl.stop_workers()
        self._closing = True
        if self._tray:
            self._tray.stop()
        try:
            (Path(self._bridge._data) / "panel_alive").unlink(missing_ok=True)
        except OSError:
            pass

    def _run(self):
        stamp = time.monotonic()
        last_heartbeat = last_daily = 0.
        while not self._stop.wait(1/60):
            now = time.monotonic()
            dt, stamp = min(.05, now-stamp), now
            if not self._loaded or self._closing:
                continue
            try:
                with self._lock:
                    if not self._hidden and self._side:
                        px, py = self._cursor()
                        inside = self._x <= px < self._x+self._width and self._y <= py < self._y+self._height
                        if inside:
                            self._leave_since = None
                            if self._edge_hidden or (self._target_x is not None and
                                    (self._target_x < self._screen()["left"] or
                                     self._target_x > self._screen()["right"]-self._width)):
                                self._reveal()
                        elif self._auto_hide and not self._hold and not self._gesture:
                            if self._leave_since is None:
                                self._leave_since = now
                            if now-self._leave_since >= .75 and not self._edge_hidden:
                                screen = self._screen()
                                self._restore_h = self._target_h
                                self._target_x = screen["left"]-self._width+12 if self._side == "left" else screen["right"]-12
                    if self._target_x is not None and not self._gesture:
                        self._x, self._velocity_x = self._spring(self._x, self._velocity_x, self._target_x, dt)
                        screen = self._screen()
                        hide_target = screen["left"]-self._width+12 if self._side == "left" else screen["right"]-12
                        if self._side and not self._edge_hidden and abs(self._x-hide_target)<.4 and abs(self._target_x-hide_target)<.4:
                            self._edge_hidden = True
                            self._target_h = 100
                            self._publish()
                    if not self._gesture:
                        self._height, self._velocity_h = self._spring(self._height, self._velocity_h, self._target_h, dt)
                    if not self._hidden:
                        self._apply()
                if now-last_heartbeat >= 3:
                    (self._bridge._data / "panel_alive").write_text(str(int(time.time())), encoding="utf-8")
                    last_heartbeat = now
                if now-last_daily >= 10:
                    self._bridge._daily_tick()
                    if self._tray:
                        import daily_summary as ds
                        self._tray.set_history(ds.history())
                    last_daily = now
                action = self._tray.poll() if self._tray else None
                if action in ("panel", "quit"):
                    self.action("show" if action == "panel" else "quit")
                elif action == "settings":
                    self._bridge.open_detail_settings()
                elif action == "summary":
                    self._bridge.summary()
                elif action == "generate":
                    self._bridge.summary(generate=True)
                elif action and action.startswith("summary:"):
                    self._bridge.summary(day=action.split(":", 1)[1])
            except Exception:
                logging.exception("V10 desktop loop failed")


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
    desktop = Desktop()
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
    html = html.replace("/*__RUNTIME_CSS__*/", (assets / "desktop.css").read_text(encoding="utf-8"))
    html = html.replace("/*__LOCAL_ICONS__*/", (assets / "vendor" / "lucide.min.js").read_text(encoding="utf-8"))
    html = html.replace("/*__LOCAL_APP__*/", (assets / "desktop.js").read_text(encoding="utf-8"))
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

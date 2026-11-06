"""V10.1: 165 Hz target, native geometry fast path and reduced bridge chatter.

The approved layout and task/data rules are inherited unchanged from V10.
"""
import ctypes
from ctypes import wintypes
import logging
import math
import time
from pathlib import Path
import quest_window_v10 as previous


class SmoothDesktop(previous.Desktop):
    def __init__(self):
        super().__init__()
        self._refresh_hz = 165
        self._frame_stamp = time.monotonic()
        self._timer_active = False
        self._native_hwnd = None
        self._physical_geometry = None
        self._region_signature = None
        self._native_failed = False
        self._suppress_publish = False

    def _motion_active(self):
        return (not self._hidden and not self._gesture and
                ((self._target_x is not None and abs(self._x-self._target_x) > .1)
                 or abs(self._height-self._target_h) > .1
                 or abs(self._velocity_x) > .1 or abs(self._velocity_h) > .1))

    def _timer_resolution(self, active):
        if active == self._timer_active:
            return
        try:
            if active:
                self._timer_active = ctypes.windll.winmm.timeBeginPeriod(1) == 0
            else:
                ctypes.windll.winmm.timeEndPeriod(1)
                self._timer_active = False
        except (AttributeError, OSError):
            self._timer_active = False

    def _wait_frame(self):
        active = self._loaded and not self._closing and self._motion_active()
        self._timer_resolution(active)
        interval = 1 / self._refresh_hz if active else .04
        # Account for work done in the previous frame instead of adding a full sleep.
        delay = max(0., interval-(time.monotonic()-self._frame_stamp))
        stopped = self._stop.wait(delay)
        self._frame_stamp = time.monotonic()
        return stopped

    def _publish(self):
        if not self._suppress_publish:
            super()._publish()

    def action(self, name, payload=None):
        payload = payload if isinstance(payload, dict) else {}
        # These high-frequency calls do not change visible application state.
        # Do not send a second Python -> JS render for each incoming frame.
        if name in ('fit', 'hold', 'hover'):
            with self._lock:
                if name == 'fit':
                    value = payload.get('height')
                    if type(value) not in (int,float) or not math.isfinite(value):
                        return {'ok':False,'error':'窗口高度不正确'}
                    if not self._gesture and not self._edge_hidden:
                        screen = self._screen()
                        cap = min(self._height_cap, screen['bottom']-self._y)
                        self._target_h = max(80,min(float(value),cap))
                        self._restore_h = self._target_h
                elif name == 'hold':
                    self._hold = bool(payload.get('active'))
                    self._leave_since = None
                else:
                    self._hovered = bool(payload.get('inside'))
                    if self._hovered:
                        self._reveal()
                    else:
                        self._leave_since = time.monotonic()
                return {'ok':True}
        if name == 'geometry' and payload.get('phase') in ('move','resize'):
            with self._lock:
                self._suppress_publish = True
                try:
                    return super().action(name,payload)
                finally:
                    self._suppress_publish = False
        return super().action(name,payload)

    def _native(self):
        if self._native_hwnd is None:
            self._native_hwnd = int(self._window.native.Handle.ToInt64())
            u,g = ctypes.windll.user32,ctypes.windll.gdi32
            u.SetWindowPos.argtypes = [wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_uint]
            u.SetWindowPos.restype = wintypes.BOOL
            u.GetDpiForWindow.argtypes = [wintypes.HWND]
            u.GetDpiForWindow.restype = ctypes.c_uint
            u.SetWindowRgn.argtypes = [wintypes.HWND,wintypes.HRGN,wintypes.BOOL]
            u.SetWindowRgn.restype = ctypes.c_int
            g.CreateRoundRectRgn.argtypes = [ctypes.c_int]*6
            g.CreateRoundRectRgn.restype = wintypes.HRGN
            g.DeleteObject.argtypes = [wintypes.HGDIOBJ]
            g.DeleteObject.restype = wintypes.BOOL
        scale = ctypes.windll.user32.GetDpiForWindow(self._native_hwnd)/96.
        return self._native_hwnd,scale or self._screen().get('scale',1.)

    def _round_corners(self):
        try:
            hwnd,scale = self._native()
            width,height = max(1,round(self._width*scale)),max(1,round(self._height*scale))
            signature = (width,height,round(28*scale))
            if signature == self._region_signature:
                return
            g,u = ctypes.windll.gdi32,ctypes.windll.user32
            region = g.CreateRoundRectRgn(0,0,width+1,height+1,signature[2],signature[2])
            if region:
                if u.SetWindowRgn(hwnd,region,True):
                    self._region_signature = signature
                else:
                    g.DeleteObject(region)
        except Exception:
            logging.debug('V10.1 native corner fallback',exc_info=True)
            super()._round_corners()

    def _apply(self):
        if self._native_failed:
            return super()._apply()
        try:
            hwnd,scale = self._native()
            target = (round(self._x*scale),round(self._y*scale),max(1,round(self._width*scale)),max(1,round(self._height*scale)))
            if target == self._physical_geometry:
                return
            old = self._physical_geometry
            # Update position and dimensions together, preserve focus and stacking order.
            flags = 0x0004 | 0x0010
            if old and old[:2] == target[:2]:
                flags |= 0x0002
            if old and old[2:] == target[2:]:
                flags |= 0x0001
            if not ctypes.windll.user32.SetWindowPos(hwnd,None,*target,flags):
                raise OSError('Native window geometry update failed')
            self._physical_geometry = target
            self._last_size = (round(self._width),round(self._height))
            self._last_pos = (round(self._x),round(self._y))
            if old is None or old[2:] != target[2:]:
                self._round_corners()
        except Exception:
            self._native_failed = True
            logging.warning('V10.1 geometry reverted to compatible path',exc_info=True)
            super()._apply()

    def _run(self):
        try:
            self._run_smooth()
        finally:
            self._timer_resolution(False)

    def _closed_event(self):
        self._timer_resolution(False)
        super()._closed_event()

    def _run_smooth(self):
            stamp = time.monotonic()
            last_heartbeat = last_daily = 0.
            while not self._wait_frame():
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
    previous.Desktop = SmoothDesktop
    return previous.main()


if __name__ == "__main__":
    raise SystemExit(main())

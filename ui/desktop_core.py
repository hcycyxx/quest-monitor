"""Shared native desktop core: current behavior without importing historical releases."""
import ctypes
from ctypes import wintypes
import json
import logging
import math
from pathlib import Path
import threading
import time


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
        self._refresh_hz = 165
        self._frame_stamp = time.monotonic()
        self._timer_active = False
        self._native_hwnd = None
        self._physical_geometry = None
        self._region_signature = None
        self._native_failed = False
        self._suppress_publish = False
        self._managed_size=None
        self._strict_preference_errors=False
        self._allow_destroy=False
        self._lifecycle=None
        self._maintenance_thread=None

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

    @staticmethod
    def _spring(x, velocity, target, dt):
        omega = 10.5
        offset = x-target
        coefficient = velocity+omega*offset
        decay = math.exp(-omega*dt)
        new_x = target+(offset+coefficient*dt)*decay
        new_v = (velocity-omega*coefficient*dt)*decay
        return (target, 0.) if abs(new_x-target) < .4 and abs(new_v) < 4 else (new_x, new_v)

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

    def _apply_compat(self):
        size = (round(self._width), round(self._height))
        pos = (round(self._x), round(self._y))
        if size != self._last_size:
            self._window.resize(*size)
            self._last_size = size
            self._round_corners()
        if pos != self._last_pos:
            self._window.move(*pos)
            self._last_pos = pos

    def _round_corners_compat(self):
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

    def _publish_actual(self):
        if self._loaded and not self._closing:
            try:
                self._window.evaluate_js("window.sidequestDesktop && window.sidequestDesktop(" +
                                         json.dumps(self.state()) + ")")
            except Exception:
                logging.exception("V10 desktop state notification failed")

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

    def _run(self):
        try:
            self._run_smooth()
        finally:
            self._timer_resolution(False)

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
                        self._schedule_maintenance()
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

    def _publish(self):
        if not self._suppress_publish:
            self._publish_actual()

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
            self._round_corners_compat()

    def _apply_fast(self):
        if self._native_failed:
            return self._apply_compat()
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
            self._apply_compat()

    def _apply(self):
        # Resizing must update the managed WebView host, not only its outer HWND.
        # Native position-only motion keeps V10.1's high-refresh fast path.
        size=(round(self._width),round(self._height))
        if size!=self._managed_size:
            self._window.resize(*size)
            self._managed_size=size
            self._last_size=size
            old=self._physical_geometry
            if old is not None:
                try:
                    _,scale=self._native()
                    self._physical_geometry=(old[0],old[1],max(1,round(self._width*scale)),max(1,round(self._height*scale)))
                except Exception:
                    self._physical_geometry=None
            self._region_signature=None
            self._round_corners()
        self._apply_fast()

    def _save_geometry(self):
        with self._lock:
            patch={'x':round(self._x),'y':round(self._y),'width':round(self._width),'height':self._height_cap,'edgeSide':self._side}
        result=self._bridge.preferences(patch)
        if not result.get('ok'):raise OSError(result.get('error','窗口设置未保存'))

    def action(self,name,payload=None):
        payload=payload if isinstance(payload,dict) else {}
        try:
            if name=='quit':
                with self._lock:
                    if self._closing:return {'ok':True,'queued':True}
                    self._closing=True
                result=self._lifecycle.submit(True,self._finish_close,closing=True)
                if not result.get('ok'):
                    with self._lock:self._closing=False
                return result
            if name=='dock':
                if payload.get('side') not in ('left','right',None):raise ValueError('停靠方向不正确')
                result=self._bridge.preferences({'edgeSide':payload.get('side')})
                if not result.get('ok'):return result
                self._publish();return {'ok':True,'desktop':self.state()}
            if name=='geometry' and payload.get('phase')=='end':
                with self._lock:
                    self._gesture=False;screen=self._screen()
                    if payload.get('dock',True):
                        left=abs(self._x-screen['left']);right=abs(self._x+self._width-screen['right'])
                        if min(left,right)<=24:self._dock('left' if left<=right else 'right')
                self._save_geometry();self._publish();return {'ok':True,'desktop':self.state()}
            if name=='reset':
                with self._lock:
                    screen=self._screen();self._side=None;self._edge_hidden=False;self._target_x=None
                    self._width=336;self._height_cap=620;self._x,self._y=screen['right']-360,screen['top']+36
                self._save_geometry();self._publish();return {'ok':True,'desktop':self.state()}
            with self._lock:
                if name=='fit':
                    value=payload.get('height')
                    if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('窗口高度不正确')
                    if self._gesture or self._edge_hidden:return {'ok':True,'applied':False}
                    cap=min(self._height_cap,self._screen()['bottom']-self._y)
                    self._target_h=max(80,min(float(value),cap));self._restore_h=self._target_h
                    return {'ok':True,'applied':True,'targetHeight':self._target_h}
                if name=='hold':
                    self._hold=bool(payload.get('active'))
                    if not self._hold and self._leave_since is None:self._leave_since=time.monotonic()
                    return {'ok':True}
                if name=='hover':
                    self._hovered=bool(payload.get('inside'))
                    if self._hovered:self._reveal()
                    else:self._leave_since=time.monotonic()
                    return {'ok':True}
                if name=='geometry':
                    phase=payload.get('phase')
                    if phase not in ('move','resize'):raise ValueError('窗口操作不正确')
                    for key in ('x','y','width','height'):
                        if key in payload and (type(payload[key]) not in (int,float) or not math.isfinite(payload[key]) or abs(payload[key])>100000):raise ValueError('窗口位置不正确')
                    self._gesture=True;self._target_x=None;self._velocity_x=self._velocity_h=0;self._side=None;self._edge_hidden=False
                    self._x=float(payload.get('x',self._x));self._y=float(payload.get('y',self._y));screen=self._screen()
                    self._width=max(300,min(float(payload.get('width',self._width)),screen['right']-screen['left']))
                    self._x=max(screen['left'],min(self._x,screen['right']-self._width));self._y=max(screen['top'],min(self._y,screen['bottom']-80))
                    if phase=='resize':self._height=max(240,min(float(payload.get('height',self._height)),screen['bottom']-self._y));self._height_cap=round(self._height)
                    self._target_h=self._height;self._apply()
                    return {'ok':True,'desktop':self.state()}
                if name=='minimize':self._reveal();self._minimized=not self._minimized
                elif name=='hide':
                    if self._tray is None:raise ValueError('托盘不可用，请使用最小化')
                    self._hidden=True;self._window.hide()
                elif name=='show':self._hidden=False;self._window.show();self._window.restore();self._reveal()
                elif name=='reveal':self._reveal()
                else:raise ValueError('未知窗口操作')
            self._publish();return {'ok':True,'desktop':self.state()}
        except Exception as exc:
            logging.exception('Desktop action failed: %s',name)
            return {'ok':False,'error':str(exc)[:180]}

    def _finish_close(self,success,error):
        if success:
            self._allow_destroy=True;self._window.destroy()
        else:
            with self._lock:self._closing=False
            self._publish()

    def _closing_event(self):
        if self._allow_destroy:return True
        self.action('quit')
        return False

    def _closed_event(self):
        self._stop.set();self._closing=True;self._timer_resolution(False)
        try:
            store=getattr(self._bridge,'_timeline_store',None)
            if store:store.close()
        except Exception:logging.exception('Timeline shutdown failed')
        if self._tray:self._tray.stop()
        if self._lifecycle:self._lifecycle.close()
        try:(self._bridge._data/'panel_alive').unlink(missing_ok=True)
        except OSError:pass

    def _schedule_maintenance(self):
        if self._maintenance_thread is not None and self._maintenance_thread.is_alive():return
        def work():
            if self._closing:return
            try:
                self._bridge._daily_tick()
                if self._tray:
                    import daily_summary as ds
                    self._tray.set_history(ds.history())
            except Exception:logging.exception('Periodic UI maintenance failed')
        self._maintenance_thread=threading.Thread(target=work,daemon=True)
        self._maintenance_thread.start()

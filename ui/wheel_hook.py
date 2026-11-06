# -*- coding: utf-8 -*-
"""滚轮钩子：overrideredirect 的 HUD 收不到 WM_MOUSEWHEEL，只能自己钩。

Windows 把 WM_MOUSEWHEEL 发给**有键盘焦点**的窗口。面板是置顶 HUD，从来不抢
焦点（抢了就会把用户正在打字的光标拽走），所以 Tk 那条路根本拿不到滚轮消息
—— 这就是"鼠标放上去滚不动"的真正原因，不是 yview 没绑好。

这里装一个 WH_MOUSE_LL 低层钩子，只在指针落在面板矩形内时把滚轮增量塞进队列，
由面板自己按拍取走。钩子跑在独立线程里，回调只做整数比较和 put，绝不碰 Tk。
"""
import ctypes
import ctypes.wintypes as wt
import queue
import threading
import time

WH_MOUSE_LL = 14
WM_MOUSEWHEEL = 0x020A
WM_QUIT = 0x0012


class _MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wt.POINT),
                ("mouseData", wt.DWORD),
                ("flags", wt.DWORD),
                ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_void_p)]


_HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                               wt.WPARAM, wt.LPARAM)


class WheelHook:
    """把「指针在面板上时滚了轮子」这件事，变成一个可以轮询的队列。"""

    def __init__(self):
        self.queue = queue.Queue(maxsize=64)
        self._rect = (0, 0, 0, 0)
        self._thread = None
        self._hook = None
        self._proc = None
        self.ok = False

    def set_rect(self, rect):
        """rect 是物理像素的 (left, top, right, bottom)。"""
        try:
            self._rect = tuple(int(v) for v in rect)
        except (TypeError, ValueError):
            self._rect = (0, 0, 0, 0)

    def start(self):
        if self._thread is not None:
            return self.ok
        try:
            self._thread = threading.Thread(target=self._run, name="wheel-hook",
                                            daemon=True)
            self._thread.start()
        except Exception:
            self._thread = None
            self.ok = False
            return False
        # 钩子是在线程里装的，start() 直接返回会读到还没写好的 ok
        for _ in range(60):                      # 最多等 0.6 秒
            if self.ok or not self._thread.is_alive():
                break
            time.sleep(0.01)
        return self.ok

    def _run(self):
        try:
            u = ctypes.windll.user32
            # 64 位下句柄是指针宽度，不声明 restype 会被截成 32 位
            u.SetWindowsHookExW.restype = ctypes.c_void_p
            u.SetWindowsHookExW.argtypes = [ctypes.c_int, _HOOKPROC,
                                            wt.HINSTANCE, wt.DWORD]
            u.CallNextHookEx.restype = ctypes.c_ssize_t
            u.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                         wt.WPARAM, wt.LPARAM]
            self._proc = _HOOKPROC(self._callback)   # 必须保住引用，否则被回收
            self._hook = u.SetWindowsHookExW(WH_MOUSE_LL, self._proc, None, 0)
            if not self._hook:
                return
            self.ok = True
            msg = wt.MSG()
            while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                u.TranslateMessage(ctypes.byref(msg))
                u.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            pass
        finally:
            self.ok = False
            hook = self._hook
            self._hook = None
            if hook:
                try:
                    u = ctypes.windll.user32
                    u.UnhookWindowsHookEx.restype = wt.BOOL
                    u.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
                    u.UnhookWindowsHookEx(hook)
                except Exception:
                    pass

    def _callback(self, nCode, wParam, lParam):
        if nCode == 0 and wParam == WM_MOUSEWHEEL:
            try:
                info = ctypes.cast(lParam,
                                   ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
                l, t, r, b = self._rect
                if l <= info.pt.x < r and t <= info.pt.y < b:
                    raw = (info.mouseData >> 16) & 0xFFFF
                    delta = ctypes.c_short(raw).value
                    try:
                        self.queue.put_nowait(delta)
                    except queue.Full:
                        pass
            except Exception:
                pass
        try:
            return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)
        except Exception:
            return 0

    def stop(self):
        thread, hook = self._thread, self._hook
        self._thread = None
        self.ok = False
        if thread is not None:
            try:
                ctypes.windll.user32.PostThreadMessageW(thread.ident, WM_QUIT, 0, 0)
            except Exception:
                pass
        self._hook = None
        if hook:
            try:
                ctypes.windll.user32.UnhookWindowsHookEx(hook)
            except Exception:
                pass

    def drain(self):
        """把攒下的滚轮增量取出来，返回合计数（正=向上）。"""
        total = 0
        while True:
            try:
                total += self.queue.get_nowait()
            except queue.Empty:
                break
        return total

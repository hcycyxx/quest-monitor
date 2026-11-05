# -*- coding: utf-8 -*-
"""Quest HUD V6. Native-DPI tkinter UI and shared transactional state storage.

DSH pause/worker control is retained. User edits and AI updates share one lock.
Optional engine fields are read only; absent estimates/timestamps stay unknown.
"""
import json
import os
import sys
import time
import math
import re
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "engine"))

import paths

STATE_FILE = paths.config("quest_state.json")
ALIVE_FILE = paths.config("panel_alive")
UI_FILE = paths.config("ui.json")

try:
    import ctl as svc
except Exception:                      # 控制模块缺失时面板照常显示，按钮退化为无操作
    svc = None

import state_store as store


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"main_quests": [], "side_quests": [], "current_activity": "",
                "suggestion": "", "updated_at": ""}

def save_state(s):
    store.save_state(STATE_FILE, s)


def load_ui():
    """面板自己的偏好（皮肤、透明度）。和任务状态分开存，互不影响。"""
    try:
        with open(UI_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_ui(**patch):
    """合并写入。写失败就静默放弃：偏好丢了不算故障，不能让面板崩。"""
    data = load_ui()
    data.update(patch)
    try:
        os.makedirs(os.path.dirname(UI_FILE), exist_ok=True)
        tmp = UI_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, UI_FILE)
    except OSError:
        pass
    return data


GLASS_BG = "#14171f"
GLASS_HI = "#232a38"
STROKE = "#38465c"
WHITE = "#f1f5fc"
SUB = "#a8b7cc"
FAINT = SUB
GOLD = "#ffd166"
GOLD_DIM = "#bca66b"
CYAN = "#7de3f4"
GREEN = "#5be3a2"
RED = "#ff8080"
# 进度条按紧急程度上色：红=马上要、橙=今天做、灰蓝=有空再做、青=在等别人。
# 这组色是深色皮肤的默认值，换皮肤时由 SKINS 里各自的 prio_* 覆盖。
PRIO_HIGH = "#ff6f5e"
PRIO_MID = "#ffb454"
PRIO_LOW = "#6f8fa6"
PRIO_WAIT = "#7de3f4"
TRANSPARENT = "#010203"
# 透明度下限 0.35：再低就既看不清也点不到，等于把面板弄丢在桌面上。
ALPHA_MIN = 0.35
ALPHA_MAX = 1.0

# 文字层：Windows 的 -alpha 作用在整个窗口上，文字会跟着一起变淡。
# tkinter 没有"只让背景透明"的开关，所以另开一个同尺寸的覆盖窗口，只把文字、
# 线条和图标复制上去，alpha 固定 1.0，背景色用 -transparentcolor 抠掉，
# 并设成点击穿透——所有交互仍然落在主窗口上。
TEXT_OVERLAY = True
# 逻辑像素面积超过这个值的多边形当背景块，不复制到文字层（否则玻璃被盖死）
OV_SKIP_AREA = 5200
OV_OPTS = {
    "text": ("text", "fill", "font", "anchor", "justify", "angle"),
    "line": ("fill", "width", "dash", "capstyle", "joinstyle", "arrow", "smooth", "stipple"),
    "polygon": ("fill", "outline", "width", "dash", "smooth", "splinesteps", "joinstyle", "stipple"),
    "rectangle": ("fill", "outline", "width", "dash", "stipple"),
    "oval": ("fill", "outline", "width", "dash", "stipple"),
    "arc": ("fill", "outline", "width", "dash", "style", "start", "extent"),
}
F_TITLE = ("Microsoft YaHei UI", 10, "bold")
F_BODY = ("Microsoft YaHei UI", 10)
F_SMALL = ("Microsoft YaHei UI", 8)
F_MICRO = F_SMALL
W = 336
TZ = timezone(timedelta(hours=8))
SKINS = {
    "glass": {"name":"深蓝玻璃", "bg":"#14171f", "hi":"#232a38", "text":"#f1f5fc", "muted":"#a8b7cc", "gold":"#ffd166", "cyan":"#7de3f4", "green":"#5be3a2", "alpha":1., "radius":16, "family":"Microsoft YaHei UI", "brand":"SideQuest",
              "prio_high":"#ff6f5e", "prio_mid":"#ffb454", "prio_low":"#6f8fa6", "prio_wait":"#7de3f4"},
    "transparent": {"name":"轻透悬浮", "bg":"#182330", "hi":"#2b3c4e", "text":"#ffffff", "muted":"#cfdaea", "gold":"#ffe1a0", "cyan":"#b3efff", "green":"#92efc3", "alpha":.90, "radius":16, "family":"Microsoft YaHei UI", "brand":"SideQuest",
              "prio_high":"#ff8577", "prio_mid":"#ffc670", "prio_low":"#8fa9bd", "prio_wait":"#b3efff"},
    "journal": {"name":"杂志手账", "bg":"#f4efe3", "hi":"#eae1ce", "text":"#342e29", "muted":"#6b6054", "gold":"#96623b", "cyan":"#396c73", "green":"#3c7052", "alpha":1., "radius":7, "family":"SimSun", "brand":"SideQuest",
              "prio_high":"#b23b28", "prio_mid":"#a9761c", "prio_low":"#5f7f8c", "prio_wait":"#396c73"},
    "night": {"name":"夜航 HUD", "bg":"#101b25", "hi":"#1c2e3c", "text":"#edf8ff", "muted":"#abc4d6", "gold":"#8ae8ff", "cyan":"#c0b3ff", "green":"#68edb8", "alpha":1., "radius":6, "family":"Microsoft YaHei UI", "brand":"SideQuest",
              "prio_high":"#ff7a6a", "prio_mid":"#ffc266", "prio_low":"#7f9fb5", "prio_wait":"#c0b3ff"},
}


def mix(a, b, amount):
    amount = max(0., min(1., amount))
    rgb = [round(int(a[i:i + 2], 16) * (1 - amount) +
                 int(b[i:i + 2], 16) * amount) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(rgb)


def rounded(cv, x, y, w, h, radius=10, **kw):
    r = min(radius, w / 2, h / 2)
    return cv.create_polygon(x+r,y, x+w-r,y, x+w,y, x+w,y+r,
                             x+w,y+h-r, x+w,y+h, x+w-r,y+h,
                             x+r,y+h, x,y+h, x,y+h-r, x,y+r, x,y,
                             smooth=True, splinesteps=20, **kw)


def enable_dpi():
    if os.name == 'nt':
        import ctypes
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass


class DesignCanvas(tk.Canvas):
    """Draw in 336-wide logical units while Windows renders at native DPI."""
    def __init__(self, master, **kw):
        self.factor = master.winfo_toplevel()._ui_scale
        super().__init__(master, **kw)

    def _create(self, itemType, args, kw):
        args = tuple(float(v)*self.factor for v in tk._flatten(args))
        kw = dict(kw)
        for key in ('width','height','activewidth','disabledwidth'):
            if key in kw and isinstance(kw[key], (int,float)):
                kw[key] *= self.factor
        return super()._create(itemType, args, kw)

    def coords(self, tag, *args):
        if args:
            return super().coords(tag, *(float(v)*self.factor for v in tk._flatten(args)))
        return [v/self.factor for v in super().coords(tag)]

    def move(self, tag, x, y):
        return super().move(tag,x*self.factor,y*self.factor)

    def canvasy(self, screeny, gridspacing=None):
        return super().canvasy(screeny,gridspacing)/self.factor

    def configure(self, cnf=None, **kw):
        if 'scrollregion' in kw:
            kw['scrollregion'] = tuple(v*self.factor for v in kw['scrollregion'])
        return super().configure(cnf,**kw)

    config = configure

    def itemconfigure(self, tag, cnf=None, **kw):
        for key in ('height','width'):
            if key in kw and isinstance(kw[key],(int,float)):
                kw[key] *= self.factor
        return super().itemconfigure(tag,cnf,**kw)

    itemconfig = itemconfigure


class QuestHUD(tk.Tk):
    EDGE = 12

    def __init__(self):
        enable_dpi()
        super().__init__()
        self._ui_scale = max(1., self.winfo_fpixels("1i") / 96.)
        self.EDGE = round(12*self._ui_scale)
        self.title("SideQuest")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=TRANSPARENT)
        try:
            self.attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            self.configure(bg=GLASS_BG)
        sw = self.winfo_screenwidth()
        self.geometry(f"{round(W*self._ui_scale)}x{round(128*self._ui_scale)}+{sw-round((W+24)*self._ui_scale)}+{round(36*self._ui_scale)}")
        self._drag = None
        self._expanded = False
        self._minimized = False
        # 头部「当前行动」默认两行；点箭头展开完整描述（长句会被截断成「中途…」）
        self._act_open = False
        self._show_done = False
        self._show_recap = False
        self._groups = {"main_quests": True, "side_quests": True}
        self._open_steps = {}
        self._tip = None
        self._last_mtime = 0
        self._serial = 0
        self._motion_job = None
        self._edge_job = None
        self._effect_job = None
        self._effects = None
        self._click_context = None
        self._pending_completion = None
        self._completion_times = {}
        self._progress_cache = {}
        self._anchors = {}
        self._dock_side = "right"
        self._right_margin = 24
        self._edge_hidden = False
        self._edge_pinned = False
        self._reveal_until = 0.
        self._normal_height = 128
        self._paused = bool(svc and svc.is_paused())
        self._power_busy = False
        self._power_serial = 0
        # 皮肤与透明度存在 config/ui.json，重启后接着用上次的
        saved = load_ui()
        self._skin_key = saved.get("skin") if saved.get("skin") in SKINS else "glass"
        self._skin_choice = tk.StringVar(self, value=self._skin_key)
        # 用户拖过滑块就记下来，之后换皮肤不再覆盖他的选择
        self._alpha_custom = "alpha" in saved
        self._alpha = self._clamp_alpha(saved.get("alpha", SKINS[self._skin_key]["alpha"]))
        # 总在最前：默认开。有些全屏程序会抢走 z 序，tick 里会定期抢回来。
        self._topmost = bool(saved.get("topmost", True))
        # 字体大小存在 ui.json 的 font_size，托盘设置里可调，改完立刻生效
        try:
            self._font_size = max(8, min(16, int(saved.get("font_size", 10) or 10)))
        except (TypeError, ValueError):
            self._font_size = 10
        self._summary_hour = saved.get("summary_hour", 18)
        self._settings = None
        self._settings_body = None
        self._settings_open = False
        self._pct_label = None
        self._slider = None
        # 托盘与详细设置窗口
        self._tray = None
        self._detail = None
        self._summary_busy = False
        self._summary_at = 0.
        self._note = None
        try:
            self.attributes("-alpha", self._alpha)
            self.attributes("-topmost", self._topmost)
        except tk.TclError:
            pass
        # 文字层：主窗口半透明时，文字另画在一个 alpha=1.0 的穿透窗口上
        self._ov = None
        self._ov_cv = None
        self._ov_visible = False
        self._ov_rect = None
        self._ov_stamp = 0.
        self._make_overlay()
        self.bind("<Configure>", self._place_overlay, add="+")
        self._fonts = {"title": tkfont.Font(self, family=SKINS[self._skin_key]["family"],
                                            size=self._font_size + 0, weight="bold"),
                       "body": tkfont.Font(self, family=SKINS[self._skin_key]["family"],
                                           size=self._font_size),
                       "small": tkfont.Font(self, family=SKINS[self._skin_key]["family"],
                                            size=max(7, self._font_size - 2))}
        self._line = max(21, self._fonts["body"].metrics("linespace") / self._ui_scale + 3)
        self._small_line = max(17, self._fonts["small"].metrics("linespace") / self._ui_scale + 2)
        self.body = DesignCanvas(self, bg=TRANSPARENT, highlightthickness=0, bd=0)
        self.body.pack(fill="both", expand=True)
        self.list = DesignCanvas(self.body, bg=GLASS_BG, highlightthickness=0, bd=0)
        self.list.configure(yscrollcommand=self._scroll_changed)
        self._list_window = None
        self.list.bind("<MouseWheel>", self._wheel)
        self.bind("<Enter>", self._enter, add="+")
        self.bind("<Leave>", self._leave, add="+")
        self.bind("<Escape>", self._escape)
        self.bind("<space>", lambda e: self._reveal_edge(True) if self._edge_hidden else None)
        self._start_tray()
        self.render()
        self.after(3000, self.tick)

    def _drag_start(self, e):
        self._cancel_edge()
        # 拖窗口时设置面板会留在原地，先收掉
        self._close_settings()
        self._drag = (e.x_root - self.winfo_x(), e.y_root - self.winfo_y())
        self._dock_side = None
        self._edge_pinned = False

    def _drag_move(self, e):
        if self._drag:
            x = e.x_root - self._drag[0]
            y = max(0, e.y_root - self._drag[1])
            x = max(0, min(self.winfo_screenwidth() - round(W*self._ui_scale), x))
            self.geometry(f"+{x}+{y}")
            # 拖窗口时不动画也不重绘，文字层得自己跟上，否则字会留在原地
            self._ov_rect = None
            self._place_overlay()

    def _drag_end(self, e):
        if self._drag:
            self._drag = None
            self._snap_edge()
            x = self.winfo_x()
            if x == 0:
                self._dock_side = "left"
                self._right_margin = 0
            elif x + self.winfo_width() >= self.winfo_screenwidth():
                self._dock_side = "right"
                self._right_margin = 0
            self._schedule_edge()
            self.render()

    def _toggle_panel_visible(self):
        """托盘里的「显示 / 隐藏面板」。隐藏只收起窗口，进程和引擎继续跑。"""
        try:
            if self.state() == "withdrawn":
                self.deiconify()
                self.lift()
                self.render()
            else:
                self._close_settings()
                self._hide_tip()
                self.withdraw()
        except tk.TclError:
            pass

    def _toggle(self, e=None):
        if self._guard_reveal(e):
            return
        self._expanded = not self._expanded
        self.render()

    def _close(self, e=None):
        if self._guard_reveal(e):
            return
        self._close_settings()
        for job in (self._motion_job, self._edge_job, self._effect_job):
            if job:
                self.after_cancel(job)
        self._hide_tip()
        if self._ov is not None:
            try:
                self._ov.destroy()
            except tk.TclError:
                pass
            self._ov, self._ov_cv = None, None
        try:
            os.remove(ALIVE_FILE)
        except OSError:
            pass
        if self._tray is not None:
            try:
                self._tray.stop()
            except Exception:
                pass
            self._tray = None
        self.destroy()

    def _minimize(self, e=None):
        if self._guard_reveal(e):
            return
        self._minimized = not self._minimized
        self.render()

    def _snap_edge(self):
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x, y, w, h = self.winfo_x(), self.winfo_y(), self.winfo_width(), self.winfo_height()
        nx, ny = x, y
        if x < self.EDGE:
            nx = 0
        elif x + w > sw - self.EDGE:
            nx = sw - w
        if y < self.EDGE:
            ny = 0
        elif y + h > sh - self.EDGE:
            ny = sh - h
        if (nx, ny) != (x, y):
            self.geometry(f"+{nx}+{ny}")

    def _toggle_step(self, key, qid, idx):
        try:
            store.user_toggle(STATE_FILE, key, qid, step=idx)
        except (OSError, ValueError, TimeoutError) as exc:
            self._pending_completion = None
            self._click_context = None
            from tkinter import messagebox
            messagebox.showerror("任务未保存", str(exc), parent=self)
            return
        self._last_mtime = os.path.getmtime(STATE_FILE)
        self.render()

    def _toggle_quest(self, key, qid):
        try:
            store.user_toggle(STATE_FILE, key, qid, step=None)
        except (OSError, ValueError, TimeoutError) as exc:
            self._pending_completion = None
            self._click_context = None
            from tkinter import messagebox
            messagebox.showerror("任务未保存", str(exc), parent=self)
            return
        self._last_mtime = os.path.getmtime(STATE_FILE)
        self.render()

    def _show_tip(self, text, e):
        if self._tip:
            self._tip.destroy()
        # 气泡自带不透明底色，压在文字层上会被遮一半
        self._hide_overlay()
        self._tip = tk.Toplevel(self)
        self._tip.overrideredirect(True)
        self._tip.attributes("-topmost", True)
        x = self.winfo_pointerx() + 14
        y = self.winfo_pointery() + 10
        self._tip.geometry(f"+{x}+{y}")
        fr = tk.Frame(self._tip, bg=GLASS_HI, highlightthickness=1, highlightbackground=STROKE)
        fr.pack(fill="both", expand=True)
        tk.Label(fr, text=text, font=F_SMALL, fg=SUB, bg=GLASS_HI,
                 wraplength=round(280*self._ui_scale), justify="left").pack(padx=10, pady=8)
        self._tip.update_idletasks()
        x = max(0, min(x, self.winfo_screenwidth()-self._tip.winfo_reqwidth()-8))
        y = max(0, min(y, self.winfo_screenheight()-self._tip.winfo_reqheight()-8))
        self._tip.geometry(f"+{x}+{y}")

    def tick(self):
        try:
            with open(ALIVE_FILE, "w", encoding="utf-8") as f:
                f.write(str(int(time.time())))
        except OSError:
            pass
        # 暂停标记可能被外部脚本改动，每拍对一次，别只信内存里的值
        if svc is not None and not self._power_busy:
            flag = svc.is_paused()
            if flag != self._paused:
                self._paused = flag
                self._last_mtime = None
        try:
            m = os.path.getmtime(STATE_FILE) if not self._paused else 0
        except OSError:
            m = 0
        if m != self._last_mtime:
            self._last_mtime = m
            # render 里任何一处异常都不能中断 after 链，否则面板永久停止刷新
            try:
                self.render()
            except Exception:
                pass
        self._raise_topmost()
        self._summary_tick()
        self.after(3000, self.tick)

    def _hide_tip(self, e=None):
        if not self._tip:
            return
        self._tip.destroy()
        self._tip = None
        # 气泡收起后把文字层放回来（设置面板还开着就不放）。
        # 这里清掉节流时间戳而不是 force：render 每帧都会调 _hide_tip，
        # force 会让同一帧重画两次文字层。
        self._ov_stamp = 0.
        if not self._settings_open:
            self._sync_overlay()

    def _cancel_edge(self):
        if self._edge_job:
            self.after_cancel(self._edge_job)
            self._edge_job = None

    def _enter(self, e=None):
        self._cancel_edge()
        if self._edge_hidden:
            self._reveal_edge()

    def _leave(self, e=None):
        self._schedule_edge()

    def _schedule_edge(self):
        self._cancel_edge()
        if self._dock_side and not self._edge_pinned and not self._drag:
            self._edge_job = self.after(750, self._maybe_hide)

    def _maybe_hide(self):
        self._edge_job = None
        if self._edge_pinned or self._drag or not self._dock_side:
            return
        x, y = self.winfo_pointerxy()
        inside = self.winfo_x() <= x < self.winfo_x()+self.winfo_width() and \
            self.winfo_y() <= y < self.winfo_y()+self.winfo_height()
        if inside or self._tip:
            return
        self._normal_height = self.winfo_height()
        self._edge_hidden = True
        self._hide_tip()
        self.render()

    def _reveal_edge(self, pin=False):
        self._cancel_edge()
        if self._edge_hidden:
            self._reveal_until = time.monotonic()+.45
        self._edge_hidden = False
        if pin:
            self._edge_pinned = True
        self.render()

    def _guard_reveal(self,e):
        if e is not None and time.monotonic()<self._reveal_until:
            self._edge_pinned = True
            self.render()
            return True
        return False

    def _pin_edge(self, e=None):
        self._edge_pinned = not self._edge_pinned
        self.render()
        self._schedule_edge()

    def _toggle_topmost(self, e=None):
        """总在最前。关掉之后面板会被别的窗口盖住，但采样和分析照跑。"""
        if self._guard_reveal(e):
            return
        self._topmost = not self._topmost
        try:
            self.attributes("-topmost", self._topmost)
            if self._ov is not None:
                self._ov.attributes("-topmost", self._topmost)
        except tk.TclError:
            pass
        save_ui(topmost=self._topmost)
        self.render()

    def _raise_topmost(self):
        """有些全屏程序会抢走 z 序。定时抢回来，只在被盖住时才动手。"""
        if not self._topmost:
            return
        try:
            if self._ov is not None and self._ov_visible:
                self._ov.attributes("-topmost", True)
                self._ov.lift()
            self.attributes("-topmost", True)
            self.lift()
        except tk.TclError:
            pass

    def _escape(self, e=None):
        self._hide_tip()
        if self._settings_open:
            self._close_settings()
            return
        if self._expanded:
            self._expanded = False
            self.render()

    def _wheel(self, e):
        if e.delta:
            self.list.yview_scroll(-max(1,abs(int(e.delta/120))) if e.delta>0 else max(1,abs(int(e.delta/120))), "units")
        return "break"

    def _scroll_changed(self,first,last):
        if not hasattr(self,"_viewport_h") or self._edge_hidden:
            return
        self.body.delete("scrollbar")
        first,last = float(first),float(last)
        if last-first>=.999 or self._viewport_h<=24:
            return
        y,h = self._header_h,self._viewport_h
        rounded(self.body,W-9,y,4,h,2,fill=mix(GLASS_BG,SUB,.1),outline="",tags="scrollbar")
        rounded(self.body,W-9,y+h*first,4,max(18,h*(last-first)),2,fill=mix(GLASS_BG,SUB,.65),outline="",tags="scrollbar")
        def move(e):
            self.list.yview_moveto(max(0,min(1,(e.y/self._ui_scale-y)/max(1,h))))
        self.body.tag_bind("scrollbar","<Button-1>",move)
        self.body.tag_bind("scrollbar","<B1-Motion>",move)

    @staticmethod
    def _word_safe(text, i):
        """在 text[i] 前断开会不会劈开一个拉丁单词。"""
        if i <= 0 or i >= len(text):
            return True
        a, b = text[i-1], text[i]

        def latin(c):
            return c.isascii() and (c.isalnum() or c in "._-")
        if not (latin(a) and latin(b)):
            return True
        return a in "._-" or b in "._-"

    def _fix_orphan(self, text, lines, px, f):
        """第二行只剩一两个字时，重新挑一个读得下去的断点。

        中文贪心断行本身没问题，只有「屏幕监 / 视」这种孤行才难看。
        所以只在这一种情况下动断点，正常的两行保持原样 —— 强行均衡
        反而会把「咨询对话」劈成「咨询对 / 话」。
        """
        if len(lines) != 2:
            return lines
        first, second = lines[0], lines[1]
        if f.measure(second) >= f.measure(first) * 0.45:
            return lines
        best = None
        for i in range(1, len(text)):
            if not self._word_safe(text, i):
                continue
            a, b = text[:i].strip(), text[i:].strip()
            if not a or not b:
                continue
            wa, wb = f.measure(a), f.measure(b)
            if wa > px or wb > px or wb < wa * 0.45:
                continue
            score = abs(wa - wb)
            if text[i-1] in "，。、；：）】」 ":
                score -= px * 0.35      # 断在标点后读起来更顺
            if best is None or score < best[0]:
                best = (score, [a, b])
        return best[1] if best else lines

    def _wrap(self, text, width, font="body", limit=0):
        f = self._fonts[font]
        lines, line = [], ""
        for ch in str(text):
            if ch == "\n" or (line and f.measure(line + ch) > width*self._ui_scale):
                lines.append(line)
                line = "" if ch == "\n" else ch
            else:
                line += ch
        if line or not lines:
            lines.append(line)
        if len(lines) == 2 and "\n" not in str(text):
            lines = self._fix_orphan(str(text), lines, width*self._ui_scale, f)
        if limit and len(lines) > limit:
            lines = lines[:limit]
            while lines[-1] and f.measure(lines[-1] + "…") > width*self._ui_scale:
                lines[-1] = lines[-1][:-1]
            lines[-1] += "…"
        return lines

    def _text(self, cv, x, y, text, width, font="body", color=None,
              limit=0, tags=()):
        color = WHITE if color is None else color
        lines = self._wrap(text, width, font, limit)
        line_h = self._line if font != "small" else self._small_line
        for i, line in enumerate(lines):
            cv.create_text(x, y + i*line_h, anchor="nw", text=line,
                           fill=color, font=self._fonts[font], tags=tags)
        return len(lines)*line_h

    def _hit(self, cv, x, y, w, h, tag, callback, bg=None):
        bg = GLASS_BG if bg is None else bg
        item = rounded(cv,x,y,w,h,6,fill=bg,outline="",tags=(tag,))
        cv.tag_bind(tag,"<Button-1>",callback)
        def enter(e):
            cv.configure(cursor="hand2")
            cv.itemconfigure(item,fill=mix(bg,WHITE,.065))
        def leave(e):
            cv.configure(cursor="arrow")
            cv.itemconfigure(item,fill=bg)
        cv.tag_bind(tag,"<Enter>",enter)
        cv.tag_bind(tag,"<Leave>",leave)

    def _chevron(self, cv, x, y, opened, color=None, tags=()):
        color = SUB if color is None else color
        points = (x-3,y-2,x,y+1,x+3,y-2) if opened else (x-2,y-3,x+1,y,x-2,y+3)
        cv.create_line(*points, fill=color, width=1.6, capstyle="round", tags=tags)

    def _measure_progress(self, q):
        if q.get("status") == "done":
            return 1., "100%", "已完成"
        for field in ("progress_percent", "estimated_progress"):
            value = q.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                value = max(0., min(95., value))
                return value/100, f"估算 {value:.0f}%", "估算"
        value = str(q.get("progress", "")).strip()
        percent = re.fullmatch(r"(?:约|估算)?\s*(\d+(?:\.\d+)?)\s*%", value)
        if percent:
            p = min(95., float(percent.group(1)))
            return p/100, f"估算 {p:.0f}%", "估算"
        steps = q.get("steps") or []
        if steps:
            done = sum(bool(st.get("done")) for st in steps)
            return done/len(steps), f"步骤 {done}/{len(steps)}", "步骤"
        fraction = re.fullmatch(r"(\d+)\s*/\s*(\d+)", value)
        if fraction and int(fraction.group(2)) > 0:
            p = min(1., int(fraction.group(1))/int(fraction.group(2)))
            return p, f"步骤 {fraction.group(1)}/{fraction.group(2)}", "步骤"
        return None, "待估算", "未知"

    def _live_line(self, q):
        text = q.get("live_progress") or q.get("progress_summary")
        if not text:
            progress = str(q.get("progress", ""))
            text = progress if progress and not re.fullmatch(r"[\d\s./%]+", progress) else ""
        if not text and q.get("status") == "waiting":
            text = q.get("waiting_reason") or "等待回复，进度暂停"
        return str(text or "暂无实时进展")

    @staticmethod
    def _completed_time(q):
        raw = q.get("completed_at") or q.get("completedAt") or q.get("done_at") or q.get("_ui_completed_at")
        if not isinstance(raw, str):
            return None
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return (value.replace(tzinfo=TZ) if value.tzinfo is None else value).astimezone(TZ)
        except ValueError:
            return None

    def _draw_progress(self, cv, q, uid, x, y, width, color):
        frac, label, source = self._measure_progress(q)
        rounded(cv, x, y, width, 4, 2, fill=mix(GLASS_BG,SUB,.18), outline="")
        if frac is not None:
            old = self._progress_cache.get(uid, frac)
            item = rounded(cv, x, y, max(.1, width*old), 4, 2, fill=color, outline="")
            self._bar_anims.append((item, x, y, width, old, frac))
            self._progress_cache[uid] = frac
        return label

    def _activity_text(self, s):
        # 托盘操作的结果（比如"总结没生成出来"）优先显示两秒，
        # 否则用户点完菜单什么反馈都没有，会以为点了没反应。
        if self._note:
            return self._note
        act = str(s.get("current_activity") or "暂无当前行动")
        # 括号里的文件名对判断没帮助，还占掉半行
        act = re.sub(r"[（(][a-zA-Z0-9_.\-]+\.(?:exe|py|txt|xlsx?|docx?|pdf)[）)]", "", act).strip()
        if self._paused and not s.get("current_activity"):
            act = "观察已暂停"
        return act or "暂无当前行动"

    def _header_height(self, act):
        if self._minimized:
            return 44
        # 头部高度要容得下进度环（cy=76 r=21，下沿 97）和它下面的来源标签
        # （居中在 cy+32=108，半高 small_line/2）。算小了会把「步骤」那行切掉。
        base = max(130, 108 + self._small_line // 2 + 10)
        if self._act_open:
            # 展开完整描述：两行之外每多一行就加一行高，主线名跟着往下走
            base += max(0, len(self._wrap(act, W - 113, "body", 0)) - 2) * self._line
        return base

    def _header(self, s, current, act):
        cv = self.body
        mini = self._minimized
        # 顶部整条都能拖。先画拖拽底块，按钮后画、盖在上面，
        # 所以 canvas 命中测试自然优先给按钮，不用手工切热区宽度。
        self._hit(cv, 2, 2, W-4, 35, "drag", self._drag_start, GLASS_BG)
        cv.create_line(17,15,17,25,fill=SUB,width=1,tags="drag")
        cv.create_line(21,15,21,25,fill=SUB,width=1,tags="drag")
        cv.tag_bind("drag", "<B1-Motion>", self._drag_move)
        cv.tag_bind("drag", "<ButtonRelease-1>", self._drag_end)
        cv.tag_bind("drag", "<Enter>", lambda e: cv.configure(cursor="fleur"))
        cv.tag_bind("drag", "<Leave>", lambda e: cv.configure(cursor="arrow"))
        paused = self._paused
        if not mini:
            brand = SKINS[self._skin_key]["brand"] + (" · 暂停" if paused else "")
            cv.create_text(30,20,anchor="w",text=brand,font=self._fonts["small"],
                           fill=SUB,tags="drag")
        self._hit(cv,W-160,7,25,27,"skin",self._skin_picker,GLASS_BG)
        for dx,dy,c in ((-3,-3,SUB),(4,-3,SUB),(-3,4,SUB),(4,4,SUB)):
            cv.create_oval(W-148+dx-2,20+dy-2,W-148+dx+2,20+dy+2,fill=c,outline="",tags="skin")
        # 暂停/继续：停掉采样看门与 LLM 引擎，面板本身留着，否则没按钮点继续
        self._hit(cv,W-132,7,24,27,"power",self._toggle_power)
        pc = GOLD if paused else SUB
        if paused:
            cv.create_polygon(W-126,15,W-126,25,W-118,20,fill=pc,outline="",tags="power")
        else:
            cv.create_line(W-125,15,W-125,25,fill=pc,width=2.2,tags="power")
            cv.create_line(W-117,15,W-117,25,fill=pc,width=2.2,tags="power")
        # 总在最前：一个图钉横放的小图标，开启时金色
        self._hit(cv,W-104,7,24,27,"top",self._toggle_topmost)
        tc = GOLD if self._topmost else SUB
        cv.create_line(W-99,15,W-99,20,fill=tc,width=1.6,tags="top")
        cv.create_line(W-95,15,W-95,20,fill=tc,width=1.6,tags="top")
        cv.create_polygon(W-101,20,W-93,20,W-97,25,fill=tc,outline="",tags="top")
        for name, x, callback in (("pin",W-76,self._pin_edge),
                                   ("minus",W-48,self._minimize),
                                   ("close",W-20,self._close)):
            self._hit(cv,x-12,7,24,27,name,callback)
            if name == "minus":
                cv.create_line(x-5,20,x+5,20,fill=SUB,width=1.4,tags=name)
            elif name == "close":
                cv.create_line(x-4,16,x+4,24,fill=SUB,width=1.4,tags=name)
                cv.create_line(x-4,24,x+4,16,fill=SUB,width=1.4,tags=name)
            else:
                # 未贴边时也画，只是压暗：图标忽隐忽现会让整排按钮跳动，用户找不到位置。
                if not self._dock_side:
                    color = mix(GLASS_BG,SUB,.55)
                else:
                    color = GOLD if self._edge_pinned else SUB
                cv.create_oval(x-4,15,x+4,23,outline=color,width=1.4,tags=name)
                cv.create_line(x,23,x,27,fill=color,width=1.4,tags=name)
        # 这排图标没有文字，鼠标停上去得说清楚是干什么的
        hints = {
            "skin": "皮肤与透明度",
            "power": "继续（重启采样与 AI 分析）" if self._paused else "暂停（停止采样，不再消耗 token）",
            "top": "总在最前：关闭后会被其他窗口盖住" if self._topmost else "总在最前：已关闭，点击重新置顶",
            "pin": ("固定：贴边后不自动缩成把手" if not self._edge_pinned else "取消贴边固定")
                   if self._dock_side else "把面板拖到屏幕边缘后，这里可以固定成常驻展开",
            "minus": "收起成一条窄条",
            "close": "关闭面板（托盘图标还在，右键可重新打开）",
        }
        for tag, text in hints.items():
            cv.tag_bind(tag, "<Enter>", lambda e, t=text: self._show_tip(t, e), add="+")
            cv.tag_bind(tag, "<Leave>", self._hide_tip, add="+")
        act = self._activity_text(s)
        if mini:
            self._hit(cv,28,7,W-185,28,"restore",self._minimize)
            self._text(cv,32,11,act,W-191,"small",GOLD if paused else WHITE,1,("restore",))
            return
        self._hit(cv,12,40,W-24,self._header_h-46,"expand",self._toggle,GLASS_BG)
        frac, label, source = self._measure_progress(current) if current else (None,"—","未知")
        color = GOLD
        cx, cy, r = 37, 76, 21
        cv.create_oval(cx-r,cy-r,cx+r,cy+r,outline=mix(GLASS_BG,SUB,.22),width=3,tags="expand")
        if frac is not None:
            cv.create_arc(cx-r,cy-r,cx+r,cy+r,start=90,extent=-max(.01,min(359.99,frac*360)),style="arc",outline=color,width=3,tags="expand")
        ring_text = f"{frac*100:.0f}%" if frac is not None else "—"
        cv.create_text(cx,cy,text=ring_text,font=self._fonts["small"],fill=WHITE,tags="expand")
        cv.create_text(cx,cy+32,text="待估算" if source=="未知" else source,font=self._fonts["small"],
                       fill=SUB,tags="expand")
        # 折叠时只给两行，第三行以后必须能点开看，否则「中途…」永远读不到后半句
        lines_all = self._wrap(act, W-113, "body", 0)
        self._text(cv,73,46,act,W-113,"body",WHITE,0 if self._act_open else 2,("expand",))
        if len(lines_all) > 2:
            shown_lines = len(lines_all) if self._act_open else 2
            more = "act:" + ("less" if self._act_open else "more")
            # 热区跟着文字块长高，否则展开后箭头跑到热区外面点不到
            self._hit(cv,W-40,42,28,max(24, shown_lines*self._line - 4),more,
                      self._toggle_act,GLASS_BG)
            self._chevron(cv,W-26,46 + shown_lines*self._line - self._line//2 - 2,
                          self._act_open,SUB,tags=(more,))
            cv.tag_bind(more,"<Enter>",lambda e,t=("收起完整描述" if self._act_open
                                                  else "展开完整描述"):self._show_tip(t,e))
            cv.tag_bind(more,"<Leave>",self._hide_tip)
        title = current.get("title", "") if current else "暂无主线任务"
        self._text(cv,73,self._header_h-self._small_line-12,title,W-113,"small",SUB,1,("expand",))
        self._chevron(cv,W-25,self._header_h-28 if self._act_open else 76,self._expanded,tags=("expand",))

    def _toggle_act(self, e=None):
        if self._guard_reveal(e):
            return
        self._act_open = not self._act_open
        self.render()

    def _toggle_power(self, e=None):
        if self._guard_reveal(e):
            return
        if svc is None:
            return
        busy = getattr(self, "_power_busy", False)
        if busy:
            return
        self._power_busy = True
        was_paused = svc.is_paused()
        self._paused = was_paused
        self._power_serial = getattr(self, "_power_serial", 0) + 1
        serial = self._power_serial

        def run():
            # 启停要拉起/杀掉进程，几百毫秒级；放到线程里，别卡住 tkinter 事件循环
            # 注意：必须用闭包里的 was_paused，不能读 self._paused —— 主线程会在
            # 线程启动后立刻翻转 self._paused 做视觉反馈，读它就等于掷硬币。
            try:
                if was_paused:
                    svc.start_workers()
                else:
                    svc.stop_workers()
            finally:
                self._power_busy = False
                self.after(0, after)

        def after():
            if serial != self._power_serial:
                return
            self._paused = svc.is_paused()
            self._last_mtime = None      # 强制下一拍重画
            self.render()

        import threading
        threading.Thread(target=run, daemon=True).start()
        self._paused = not was_paused        # 立即给视觉反馈，真状态在线程回来后对齐
        self.render()

    @staticmethod
    def _priority_rank(q):
        """模型给的 priority 决定排序；waiting 沉到最后（在等别人，不是该做的）。"""
        table = {"high": 0, "mid": 1, "low": 2}
        rank = table.get(str(q.get("priority") or "").lower(), 1)
        if q.get("status") == "waiting":
            rank += 3
        return rank

    def _sort_by_priority(self, quests):
        # 稳定排序：同优先级保持模型给的原始顺序，不因每轮刷新而跳动
        return sorted(quests, key=self._priority_rank)

    @staticmethod
    def _prio_color(q):
        """进度条颜色 = 紧急程度。红要马上做、橙是今天的、灰蓝是有空再说、
        青是在等别人（不是你能推进的，所以不催）。"""
        if q.get("status") == "waiting":
            return PRIO_WAIT
        prio = str(q.get("priority") or "").lower()
        if prio == "high":
            return PRIO_HIGH
        if prio == "low":
            return PRIO_LOW
        return PRIO_MID

    def _section(self, quests, label, color, key, readonly=False):
        cv = self.list
        y = self._draw_y
        active = [q for q in quests if q.get("status") != "done"]
        active = self._sort_by_priority(active)
        opened = self._groups.get(key, True)
        tag = "group:"+key
        cv.create_line(10,y,W-34,y,fill=mix(GLASS_BG,SUB,.22),dash=(3,3) if self._skin_key=="journal" else ())
        self._hit(cv,8,y+4,W-40,34,tag,lambda e,k=key:self._toggle_group(k))
        cv.create_polygon(19,y+16,24,y+21,19,y+26,14,y+21,fill=color,outline="",tags=tag)
        cv.create_text(35,y+21,text=label,anchor="w",font=self._fonts["small"],fill=color,tags=tag)
        cv.create_text(W-57,y+21,text=f"{len(active)} 项",anchor="e",font=self._fonts["small"],fill=SUB,tags=tag)
        self._chevron(cv,W-45,y+21,opened,tags=(tag,))
        y += 43
        if opened:
            if not active:
                y += self._text(cv,17,y,"暂无待办任务",W-60,"small",SUB)+10
            for index, q in enumerate(active):
                y = self._task(q,key,color,y,index)
        self._draw_y = y + 4

    def _task(self, q, key, color, y, index):
        cv = self.list
        qid = q.get("id", "")
        uid = f"{key}:{qid or index}"
        group = "layout:"+uid
        self._anchors[group] = y
        start = len(cv.find_all())
        title = str(q.get("title") or "未命名任务")
        lines = self._wrap(title,W-95,"body",2)
        h = len(lines)*self._line
        # 标题区只负责展开/收起步骤：把"点一下标题就算完成"取消掉，
        # 因为标题文字很长、和右边的 ⓘ 只隔几像素，很容易点错把任务误标完成。
        steps_for_toggle = q.get("steps") or []
        title_tag = "quest:"+uid
        if steps_for_toggle:
            self._hit(cv,34,y,W-90,h+4,title_tag,
                      lambda e,u=uid:self._toggle_steps(u))
        self._text(cv,40,y+2,title,W-95,"body",WHITE,2,(title_tag,))
        # 左侧圆点才是"完成/恢复"开关，位置固定、热区足够大。
        mark = "mark:"+uid
        done_now = q.get("status") == "done"
        self._hit(cv,12,y,24,h+4,mark,lambda e,k=key,i=qid:self._quest_click(k,i,e))
        if done_now:
            rounded(cv,19,y+6,14,14,4,fill=mix(GLASS_BG,GREEN,.14),outline=GREEN,width=1.2,tags=mark)
            cv.create_line(22,y+13,25,y+16,30,y+9,fill=GREEN,width=1.8,
                           capstyle="round",joinstyle="round",tags=mark)
        else:
            cv.create_oval(20,y+7,32,y+19,outline=mix(GLASS_BG,color,.75),width=1.2,tags=mark)
        cv.tag_bind(mark,"<Enter>",lambda e,t="标记完成" if not done_now else "恢复为进行中":self._show_tip(t,e))
        cv.tag_bind(mark,"<Leave>",self._hide_tip)
        note = str(q.get("note") or "暂无补充说明")
        prio = str(q.get("priority") or "").lower()
        if prio in ("high", "mid", "low"):
            # 优先级是模型自己判的，得让人看得见，否则排序像是随机的
            note = f"优先级：{'高' if prio=='high' else ('中' if prio=='mid' else '低')}\n" + note
        info = "info:"+uid
        # list 画布宽只有 W-24，图标右缘必须收在 310 以内，否则会被裁掉半个。
        self._hit(cv,W-46,y,26,27,info,lambda e,t=note:self._show_tip(t,e))
        cv.create_oval(W-39,y+5,W-26,y+18,outline=SUB,width=1,tags=info)
        cv.create_text(W-32.5,y+11,text="i",font=self._fonts["small"],fill=SUB,tags=info)
        cv.tag_bind(info,"<Enter>",lambda e,t=note:self._show_tip(t,e))
        cv.tag_bind(info,"<Leave>",self._hide_tip)
        y += h + 7
        frac, label, source = self._measure_progress(q)
        self._text(cv,17,y,self._live_line(q),W-145,"small",SUB,1)
        cv.create_text(W-31,y,anchor="ne",text=label,font=self._fonts["small"],
                       fill=self._prio_color(q) if q.get("status") != "done" else SUB)
        y += self._small_line + 6
        waiting = q.get("status") == "waiting"
        self._draw_progress(cv,q,uid,17,y,W-48,self._prio_color(q))
        y += 15
        if waiting:
            y += self._text(cv,17,y,"等待回复 · 进度暂停",W-60,"small",CYAN)+4
        steps = q.get("steps") or []
        opened = self._open_steps.get(uid, False)
        if steps:
            done_n = sum(1 for st in steps if st.get("done"))
            toggle = "steps:"+uid
            self._hit(cv,13,y-2,W-45,24,toggle,lambda e,u=uid:self._toggle_steps(u))
            self._chevron(cv,20,y+10,opened,tags=(toggle,))
            cv.create_text(29,y+10,anchor="w",text=f"{'收起' if opened else '展开'} {len(steps)} 个步骤",
                           font=self._fonts["small"],fill=SUB,tags=toggle)
            cv.create_text(W-31,y+10,anchor="e",text=f"{done_n}/{len(steps)}",
                           font=self._fonts["small"],fill=mix(GLASS_BG,SUB,.9),tags=toggle)
            y += 22
        for idx, st in enumerate(steps if opened else []):
            height = max(27,len(self._wrap(st.get("text",""),W-91,"small"))*self._small_line+10)
            step = f"step:{uid}:{idx}"
            self._hit(cv,15,y,W-45,height,step,
                      lambda e,k=key,i=qid,j=idx,cy=y+13:self._step_click(k,i,j,e,cy))
            done = bool(st.get("done"))
            rounded(cv,20,y+6,14,14,4,fill=mix(GLASS_BG,GREEN,.14) if done else GLASS_BG,
                    outline=mix(GLASS_BG,GREEN,.65) if done else SUB,width=1,tags=step)
            if done:
                cv.create_line(23,y+13,26,y+16,31,y+10,fill=GREEN,width=1.8,
                               capstyle="round",joinstyle="round",tags=step)
            self._text(cv,44,y+4,st.get("text",""),W-91,"small",SUB if done else WHITE,0,(step,))
            y += height
        y += 12
        for item in cv.find_all()[start:]:
            cv.addtag_withtag(group,item)
        return y

    def _toggle_group(self,key):
        self._groups[key] = not self._groups.get(key,True)
        self.render()

    def _toggle_steps(self,uid):
        self._open_steps[uid] = not self._open_steps.get(uid,False)
        self.render()

    def _toggle_done(self,e=None):
        self._show_done = not self._show_done
        self.render()

    def _timeline(self, all_quests):
        cv = self.list
        done = [(k,q) for k,q in all_quests if q.get("status") == "done"]
        y = self._draw_y
        cv.create_line(10,y,W-34,y,fill=mix(GLASS_BG,SUB,.22))
        self._hit(cv,9,y+3,W-40,30,"done",self._toggle_done)
        self._chevron(cv,19,y+18,self._show_done,tags=("done",))
        cv.create_text(32,y+18,anchor="w",text=f"已完成（{len(done)}）",font=self._fonts["small"],fill=SUB,tags="done")
        y += 38
        if self._show_done:
            done.sort(key=lambda pair:self._completed_time(pair[1]) or datetime.min.replace(tzinfo=TZ),reverse=True)
            previous = object()
            today = datetime.now(TZ).date()
            for n,(key,q) in enumerate(done):
                stamp = self._completed_time(q)
                day = stamp.date() if stamp else None
                if day != previous:
                    title = ("今天 · " if day == today else "")+stamp.strftime("%Y年%m月%d日") if stamp else "时间未记录"
                    y += self._text(cv,15,y+3,title,W-60,"small",SUB)+9
                    previous = day
                uid = f"done:{n}"
                text_h = len(self._wrap(q.get("title",""),W-83,"small",2))*self._small_line
                height = text_h+self._small_line+15
                self._hit(cv,31,y,W-62,height,uid,lambda e,k=key,i=q.get("id",""):self._quest_click(k,i,e))
                cv.create_line(20,y,20,y+height,fill=mix(GLASS_BG,GREEN,.35))
                cv.create_oval(17,y+7,23,y+13,fill=GREEN,outline="")
                self._text(cv,35,y+2,q.get("title",""),W-83,"small",WHITE,2,(uid,))
                when = stamp.strftime("%H:%M 完成") if stamp else "完成时间未记录"
                self._text(cv,35,y+text_h+3,when,W-83,"small",SUB,1,(uid,))
                y += height
            if not done:
                y += self._text(cv,16,y,"暂无已完成任务",W-60,"small",SUB)+10
        self._draw_y = y

    def _recap(self, all_quests):
        cv = self.list
        y = self._draw_y
        cv.create_line(10,y,W-34,y,fill=mix(GLASS_BG,SUB,.22))
        self._hit(cv,9,y+3,W-40,30,"recap",self._toggle_recap)
        self._chevron(cv,19,y+18,self._show_recap,tags=("recap",))
        cv.create_text(32,y+18,anchor="w",text="今日回顾",font=self._fonts["small"],fill=SUB,tags="recap")
        y += 38
        if self._show_recap:
            today = datetime.now(TZ).date()
            qs = [q for _,q in all_quests]
            completed = [q for q in qs if q.get("status")=="done" and self._completed_time(q) and self._completed_time(q).date()==today]
            unknown = sum(q.get("status")=="done" and not self._completed_time(q) for q in qs)
            sections = [("今日完成",completed),("进行中",[q for q in qs if q.get("status")=="active"]),
                        ("等待回复",[q for q in qs if q.get("status")=="waiting"])]
            for label,items in sections:
                y += self._text(cv,16,y,label,W-60,"small",SUB)+5
                if items:
                    for q in items:
                        y += self._text(cv,21,y,q.get("title",""),W-72,"small",WHITE,2)+6
                else:
                    y += self._text(cv,21,y,"暂无记录",W-72,"small",SUB)+6
                y += 6
            if unknown:
                y += self._text(cv,16,y,f"另有 {unknown} 项历史完成，日期未记录。",W-60,"small",SUB)+10
        self._draw_y = y

    def _toggle_recap(self,e=None):
        self._show_recap = not self._show_recap
        self.render()

    def _skin_picker(self,e):
        if self._guard_reveal(e):
            return
        self._hide_tip()
        if self._settings_open:
            self._close_settings()
            return
        self._open_settings()

    # ── 皮肤与透明度设置面板 ────────────────────────────────────────────
    # 原来是一个 tk.Menu 单选列表。加了透明度拖动条之后菜单放不下，
    # 改成自绘的弹出面板：上半皮肤列表，下半滑块。

    def _clamp_alpha(self, v):
        """0.35 是下限。再低就基本看不见也点不到了，等于把面板弄丢。"""
        try:
            v = float(v)
        except (TypeError, ValueError):
            return 1.0
        return max(ALPHA_MIN, min(ALPHA_MAX, v))

    def _apply_alpha(self, v, save=False):
        self._alpha = self._clamp_alpha(v)
        self._alpha_custom = True
        try:
            self.attributes("-alpha", self._alpha)
        except tk.TclError:
            pass
        # 背景透明度变了，文字层要跟着出现/消失或重画
        self._sync_overlay(force=True)
        if self._pct_label is not None:
            try:
                self._pct_label.configure(text=f"{int(round(self._alpha*100))}%")
            except tk.TclError:
                self._pct_label = None
        if save:
            save_ui(alpha=self._alpha)

    def _close_settings(self):
        self._settings_open = False
        self._pct_label = None
        self._slider = None
        if self._settings is not None:
            try:
                self._settings.destroy()
            except tk.TclError:
                pass
            self._settings = None
        self._sync_overlay(force=True)

    def _hide_overlay(self):
        """临时收起文字层（设置面板、气泡这类自带不透明背景的窗口要用）。"""
        if self._ov is not None and self._ov_visible:
            try:
                self._ov.withdraw()
            except tk.TclError:
                self._ov = None
            self._ov_visible = False
            self._ov_rect = None

    def _open_settings(self):
        self._settings_open = True
        # 设置面板是独立窗口、自己就不透明；文字层盖上去会把它弄花
        self._hide_overlay()
        top = tk.Toplevel(self)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        self._settings = top
        self._settings_body = tk.Frame(top, bg=GLASS_HI, highlightthickness=1,
                                       highlightbackground=STROKE)
        self._settings_body.pack(fill="both", expand=True)
        self._fill_settings()
        top.bind("<Escape>", lambda ev: self._close_settings())
        top.bind("<FocusOut>", lambda ev: self.after(120, self._maybe_close_settings))
        try:
            top.focus_force()
        except tk.TclError:
            pass
        self._place_settings()

    def _maybe_close_settings(self):
        """点面板外面就收起来。焦点回到本进程任何控件都算还在用。"""
        if not self._settings_open or self._settings is None:
            return
        try:
            focus = self._settings.focus_get()
        except (tk.TclError, KeyError):
            focus = None
        if focus is None:
            self._close_settings()

    def _place_settings(self):
        top = self._settings
        if top is None:
            return
        top.update_idletasks()
        w, h = top.winfo_reqwidth(), top.winfo_reqheight()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        px, py = self.winfo_rootx(), self.winfo_rooty()
        pw = self.winfo_width()
        y = py + round(38*self._ui_scale)
        # 面板通常贴在屏幕右侧，所以优先把设置面板放到左边，别盖住任务列表；
        # 左边放不下就翻到右边，再不行才叠在面板上。
        x = px - w - round(8*self._ui_scale)
        if x < 4:
            x = px + pw + round(8*self._ui_scale)
        if x + w > sw - 4:
            x = px + round((W-8)*self._ui_scale) - w
        x = max(4, min(x, sw-w-4))
        y = max(4, min(y, sh-h-4))
        top.geometry(f"+{x}+{y}")

    def _fill_settings(self):
        """重建面板内容。换皮肤后颜色变了，直接重画一遍最省事。"""
        body = self._settings_body
        # 容器自己的底色也要跟着换。只重建子控件的话，旧皮肤的底色会留在
        # 下面，新皮肤的浅色行块浮在深色底上，看着像一排输入框。
        try:
            body.configure(bg=GLASS_HI, highlightbackground=STROKE)
            if self._settings is not None:
                self._settings.configure(bg=GLASS_HI)
        except tk.TclError:
            pass
        for child in body.winfo_children():
            child.destroy()
        self._pct_label = None
        self._slider = None
        pad = round(10*self._ui_scale)

        tk.Label(body, text="皮肤", font=F_SMALL, fg=SUB, bg=GLASS_HI,
                 anchor="w").pack(fill="x", padx=pad, pady=(round(8*self._ui_scale), 0))

        for key, skin in SKINS.items():
            current = key == self._skin_key
            row = tk.Frame(body, bg=GLASS_HI, cursor="hand2")
            row.pack(fill="x", padx=round(6*self._ui_scale), pady=round(1*self._ui_scale))
            chip = tk.Canvas(row, width=round(14*self._ui_scale), height=round(14*self._ui_scale),
                             bg=GLASS_HI, highlightthickness=0)
            chip.create_oval(round(2*self._ui_scale), round(2*self._ui_scale),
                             round(12*self._ui_scale), round(12*self._ui_scale),
                             fill=skin["gold"], outline="")
            chip.pack(side="left", padx=(round(6*self._ui_scale), round(8*self._ui_scale)),
                      pady=round(5*self._ui_scale))
            label = tk.Label(row, text=skin["name"], font=F_SMALL, bg=GLASS_HI,
                             fg=WHITE if current else SUB, anchor="w")
            label.pack(side="left", fill="x", expand=True)
            tick = tk.Label(row, text="●" if current else "", font=F_SMALL,
                            bg=GLASS_HI, fg=GOLD)
            tick.pack(side="right", padx=(0, round(8*self._ui_scale)))

            def enter(ev, r=row, lbl=label):
                r.configure(bg=mix(GLASS_HI, SUB, .14))
                lbl.configure(bg=mix(GLASS_HI, SUB, .14))
            def leave(ev, r=row, lbl=label):
                r.configure(bg=GLASS_HI)
                lbl.configure(bg=GLASS_HI)
            for widget in (row, chip, label, tick):
                widget.bind("<Enter>", enter)
                widget.bind("<Leave>", leave)
                widget.bind("<Button-1>", lambda ev, k=key: self._set_skin(k))

        tk.Frame(body, bg=mix(GLASS_HI, SUB, .22), height=1).pack(
            fill="x", padx=pad, pady=(round(7*self._ui_scale), round(5*self._ui_scale)))

        head = tk.Frame(body, bg=GLASS_HI)
        head.pack(fill="x", padx=pad)
        tk.Label(head, text="透明度", font=F_SMALL, fg=SUB, bg=GLASS_HI,
                 anchor="w").pack(side="left")
        self._pct_label = tk.Label(head, text=f"{int(round(self._alpha*100))}%",
                                   font=F_SMALL, fg=GOLD, bg=GLASS_HI, anchor="e")
        self._pct_label.pack(side="right")

        sw = round(196*self._ui_scale)
        sh = round(22*self._ui_scale)
        scv = tk.Canvas(body, width=sw, height=sh, bg=GLASS_HI, highlightthickness=0,
                        cursor="hand2")
        scv.pack(padx=pad, pady=(round(2*self._ui_scale), round(10*self._ui_scale)))
        self._slider = scv

        state = {"dragging": False}

        def geom():
            # winfo_width() 在 canvas 还没被映射时返回 1（不是 0），
            # 拿它当宽度会让 span 变成 1px，点哪儿都算拖到最右端。
            w = scv.winfo_width()
            if w <= 1:
                w = sw
            edge = round(7*self._ui_scale)
            return w, edge, max(1, w - edge*2)

        def draw():
            scv.delete("all")
            w, edge, span = geom()
            cy = sh/2
            x0, x1 = edge, w - edge
            frac = (self._alpha - ALPHA_MIN) / (ALPHA_MAX - ALPHA_MIN)
            kx = x0 + span*frac
            thick = round(3*self._ui_scale)
            scv.create_line(x0, cy, x1, cy, fill=mix(GLASS_HI, SUB, .32),
                            width=thick, capstyle="round")
            scv.create_line(x0, cy, kx, cy, fill=GOLD, width=thick, capstyle="round")
            r = round(6*self._ui_scale)
            scv.create_oval(kx-r, cy-r, kx+r, cy+r, fill=GOLD,
                            outline=GLASS_HI, width=round(1.5*self._ui_scale))

        def pick(ev):
            w, edge, span = geom()
            frac = max(0., min(1., (ev.x - edge)/span))
            self._apply_alpha(ALPHA_MIN + (ALPHA_MAX - ALPHA_MIN)*frac)
            draw()

        def press(ev):
            state["dragging"] = True
            pick(ev)
        def move(ev):
            if state["dragging"]:
                pick(ev)
        def release(ev):
            if state["dragging"]:
                state["dragging"] = False
                pick(ev)
                save_ui(alpha=self._alpha)   # 拖完才落盘，别每一像素都写文件

        scv.bind("<Configure>", lambda ev: draw())
        scv.bind("<Button-1>", press)
        scv.bind("<B1-Motion>", move)
        scv.bind("<ButtonRelease-1>", release)
        scv.bind("<MouseWheel>", lambda ev: (
            self._apply_alpha(self._alpha + (0.05 if ev.delta > 0 else -0.05), save=True),
            draw()))
        draw()

    def _set_skin(self,key):
        global GLASS_BG,GLASS_HI,STROKE,WHITE,SUB,FAINT,GOLD,GOLD_DIM,CYAN,GREEN,F_SMALL
        global PRIO_HIGH,PRIO_MID,PRIO_LOW,PRIO_WAIT
        skin = SKINS[key]
        self._skin_key = key
        self._skin_choice.set(key)
        GLASS_BG,GLASS_HI = skin["bg"],skin["hi"]
        WHITE,SUB,FAINT = skin["text"],skin["muted"],skin["muted"]
        GOLD,CYAN,GREEN = skin["gold"],skin["cyan"],skin["green"]
        PRIO_HIGH,PRIO_MID = skin["prio_high"],skin["prio_mid"]
        PRIO_LOW,PRIO_WAIT = skin["prio_low"],skin["prio_wait"]
        STROKE,GOLD_DIM = mix(GLASS_BG,SUB,.4),GOLD
        F_SMALL = (skin["family"],8)
        for font in self._fonts.values():
            font.configure(family=skin["family"])
        self._line = max(21,self._fonts["body"].metrics("linespace")/self._ui_scale+3)
        self._small_line = max(17,self._fonts["small"].metrics("linespace")/self._ui_scale+2)
        # 用户手动调过透明度就以他为准，换皮肤不再把它顶掉；
        # 没调过才跟着皮肤走各自的默认值。
        if not self._alpha_custom:
            self._alpha = self._clamp_alpha(skin["alpha"])
        try:
            self.attributes("-alpha",self._alpha)
        except tk.TclError:
            pass
        save_ui(skin=key)
        if self._settings_open:
            self._fill_settings()
            self._place_settings()
        self.render()

    def render(self):
        self._serial += 1
        serial = self._serial
        if self._motion_job:
            self.after_cancel(self._motion_job)
            self._motion_job = None
        if self._effect_job:
            self.after_cancel(self._effect_job)
            self._effect_job = None
        self._hide_tip()
        old_anchors = self._anchors
        self._anchors = {}
        old_scroll = self.list.yview()[0]
        self.body.delete("all")
        self.list.delete("all")
        self.list.place_forget()
        self._bar_anims = []
        if self._edge_hidden:
            self._paint_handle(serial)
            return
        s = load_state()
        mains,sides = s.get("main_quests",[]),s.get("side_quests",[])
        all_quests = [("main_quests",q) for q in mains]+[("side_quests",q) for q in sides]
        # Only direct successful UI completions have a known local completion time.
        # This cache is never sent to save_state; pre-existing done tasks stay unknown.
        pending,self._pending_completion = self._pending_completion,None
        for key,q in all_quests:
            identity = (key,q.get("id",""),q.get("title",""))
            if pending and identity==pending[:3] and q.get("status")=="done":
                self._completion_times[identity] = pending[3]
            if q.get("status")!="done":
                self._completion_times.pop(identity,None)
            elif not self._completed_time(q) and identity in self._completion_times:
                q["_ui_completed_at"] = self._completion_times[identity]
        # 顶部进度环跟的是「最该做的那条主线」，不是模型碰巧排在第一个的
        ordered = self._sort_by_priority([q for q in mains if q.get("status") != "done"])
        current = next((q for q in ordered if q.get("status") == "active"), None)
        current = current or (ordered[0] if ordered else None)
        # A layered outline rather than artificial noise; transparent outside corners.
        self.list.configure(bg=GLASS_BG)
        act = self._activity_text(s)
        self._header_h = self._header_height(act)
        # 外壳跟着头部高度走，否则展开完整描述时卡片底边会压在文字中间
        self._shell = rounded(self.body,1,1,W-2,self._header_h-4,SKINS[self._skin_key]["radius"],fill=GLASS_BG,outline=mix(GLASS_BG,SUB,.65),width=1)
        self.body.create_line(24,2,W-24,2,fill=mix(GLASS_HI,WHITE,.5))
        self.body.create_line(17,3,W//2,3,fill=GLASS_HI)
        self._header(s,current,act)
        self._draw_y = 4
        if self._expanded and not self._minimized:
            self._section(mains,"主线 / 今日重点" if self._skin_key=="journal" else "主线任务",GOLD,"main_quests")
            self._section(sides,"支线 / 随手记" if self._skin_key=="journal" else "支线任务",CYAN,"side_quests")
            suggestion = str(s.get("suggestion") or "")
            if suggestion:
                y = self._draw_y
                self.list.create_line(10,y,W-34,y,fill=mix(GLASS_BG,SUB,.22))
                y += 12
                y += self._text(self.list,16,y,"下一步建议",W-60,"small",GOLD)+4
                y += self._text(self.list,16,y,suggestion,W-60,"small",WHITE,3)+15
                self._draw_y = y
            self._timeline(all_quests)
            self._recap(all_quests)
        total = self._draw_y+4 if self._expanded and not self._minimized else 0
        self.list.configure(scrollregion=(0,0,W-24,max(total,1)))
        if total:
            self.list.yview_moveto(old_scroll)
        y = max(0,min(self.winfo_y(),self.winfo_screenheight()-round((self._header_h+30)*self._ui_scale)))
        if not getattr(self,"_placed",False):
            y, self._placed = round(36*self._ui_scale), True
        available = max(self._header_h+20,(self.winfo_screenheight()-y)/self._ui_scale-16)
        cap = max(self._header_h+180,int(self.winfo_screenheight()/self._ui_scale*0.60))
        available = min(available,cap)
        target_h = min(self._header_h+total+8,available)
        self._normal_height = target_h
        self._list_window = self.body.create_window(12,self._header_h,window=self.list,anchor="nw",width=W-24,height=max(1,target_h-self._header_h-8),state="normal" if total else "hidden")
        self._layout_anims = []
        for tag,new_y in self._anchors.items():
            if tag in old_anchors:
                delta = old_anchors[tag]-new_y
                if delta:
                    self.list.move(tag,0,delta)
                    self._layout_anims.append([tag,delta])
        start_h = max(1,self.winfo_height()/self._ui_scale)
        start_w = max(1,self.winfo_width()/self._ui_scale)
        start_t = time.monotonic()
        def animate():
            if serial != self._serial:
                return
            elapsed = (time.monotonic()-start_t)/.32
            t = min(1.,elapsed)
            ease = 1-(1-t)**3
            h = round(start_h+(target_h-start_h)*ease)
            width = round(start_w+(W-start_w)*ease)
            self._set_size(width,h,y)
            self.body.coords(self._shell,*self._rounded_coords(1,1,W-2,max(1,h-2),SKINS[self._skin_key]["radius"]))
            if total:
                self._viewport_h = max(1,h-self._header_h-8)
                self.body.itemconfigure(self._list_window,height=self._viewport_h)
                self._scroll_changed(*self.list.yview())
            for item,x,by,bw,old,new in self._bar_anims:
                frac = old+(new-old)*ease
                self.list.coords(item,*self._rounded_coords(x,by,max(.1,bw*frac),4,2))
            for entry in self._layout_anims:
                tag,remaining = entry
                desired = (1-ease)*(old_anchors[tag]-self._anchors[tag])
                self.list.move(tag,0,desired-remaining)
                entry[1] = desired
            if t < 1:
                self._motion_job = self.after(16,animate)
            else:
                self._motion_job = None
            self._sync_overlay()
        animate()
        self._start_effect(serial)

    @staticmethod
    def _rounded_coords(x,y,w,h,r):
        r = min(r,w/2,h/2)
        return (x+r,y,x+w-r,y,x+w,y,x+w,y+r,x+w,y+h-r,x+w,y+h,
                x+w-r,y+h,x+r,y+h,x,y+h,x,y+h-r,x,y+r,x,y)

    def _set_size(self,width,height,y):
        width,height = max(1,round(width*self._ui_scale)),max(1,round(height*self._ui_scale))
        if self._dock_side == "right":
            x = self.winfo_screenwidth()-width-round(max(0,getattr(self,"_right_margin",0))*self._ui_scale)
        elif self._dock_side == "left":
            x = 0
        else:
            x = max(0,min(self.winfo_x(),self.winfo_screenwidth()-width))
        self.geometry(f"{width}x{height}+{x}+{round(y)}")

    def _paint_handle(self,serial):
        start_w,start_h = self.winfo_width()/self._ui_scale,self.winfo_height()/self._ui_scale
        y = min(self.winfo_y(),self.winfo_screenheight()-round(72*self._ui_scale))
        start = time.monotonic()
        def frame():
            if serial != self._serial:
                return
            t = min(1.,(time.monotonic()-start)/.24)
            k = 1-(1-t)**3
            w = round(start_w+(20-start_w)*k)
            h = round(start_h+(68-start_h)*k)
            self._set_size(w,h,y)
            self.body.delete("edge")
            rounded(self.body,0,0,w,h,9,fill=GLASS_HI,outline="#667890",tags="edge")
            cx = w/2
            self.body.create_polygon(cx,15,cx+4,20,cx,25,cx-4,20,fill=GOLD,outline="",tags="edge")
            self.body.create_line(cx,35,cx,50,fill=SUB,width=2,tags="edge")
            self.body.tag_bind("edge","<Button-1>",lambda e:self._reveal_edge(True))
            if t<1:
                self._motion_job = self.after(16,frame)
            else:
                self._motion_job = None
            self._sync_overlay()
        frame()

    def _step_click(self,key,qid,idx,e,cy=None):
        if self._guard_reveal(e):
            return
        # Effects wrap the original handler; only that handler writes engine state.
        state = load_state()
        q = next((q for q in state.get(key,[]) if q.get("id")==qid),{})
        steps = q.get("steps") or []
        on = idx<len(steps) and not bool(steps[idx].get("done"))
        whole = on and all(st.get("done") or i==idx for i,st in enumerate(steps))
        if whole:
            self._pending_completion = (key,qid,q.get("title",""),datetime.now(TZ).isoformat())
        self._click_context = (27,cy if cy is not None else self.list.canvasy(e.y),on,whole,True)
        self._toggle_step(key,qid,idx)

    def _quest_click(self,key,qid,e):
        if self._guard_reveal(e):
            return
        state = load_state()
        q = next((q for q in state.get(key,[]) if q.get("id")==qid),{})
        on = q.get("status")!="done"
        if on:
            self._pending_completion = (key,qid,q.get("title",""),datetime.now(TZ).isoformat())
        self._click_context = (e.x,self.list.canvasy(e.y),on,on,False)
        self._toggle_quest(key,qid)

    def _start_effect(self,serial):
        context,self._click_context = self._click_context,None
        if not context or not context[2]:
            return
        x,y,on,whole,is_step = context
        halo_cv = self.list if is_step else self.body
        hx,hy = (27,y) if is_step else (W/2,74)
        # Keep the halo on the clicked checkbox; completion particles stay visible
        # in the header even when the completed row leaves the active section.
        cv = self.body if whole else self.list
        x,y = (W/2,74) if whole else (27,y)
        start = time.monotonic()
        count = 16 if whole else 7
        particles = [(i*math.tau/count,16+(i%4)*8) for i in range(count)]
        def frame():
            if serial!=self._serial:
                return
            t = min(1.,(time.monotonic()-start)/.58)
            self.body.delete("celebration")
            self.list.delete("celebration")
            if whole and is_step:
                # A short departing check mark leaves the click location readable
                # while its completed task is being moved out of the active list.
                rounded(halo_cv,hx-7,hy-7,14,14,4,fill=mix(GREEN,GLASS_BG,t),
                        outline="",tags="celebration",state="disabled")
                halo_cv.create_line(hx-4,hy,hx-1,hy+3,hx+4,hy-3,
                                    fill=mix(WHITE,GLASS_BG,t),width=1.6,
                                    tags="celebration",state="disabled")
            for j in range(3):
                p = min(1.,t+j*.09)
                radius = 9+p*(29 if whole else 23)
                color = mix("#75c7ff",GLASS_BG,min(1.,p*1.05))
                halo_cv.create_oval(hx-radius,hy-radius,hx+radius,hy+radius,outline=color,
                                    width=max(1,3-j),tags="celebration",state="disabled")
            for i,(angle,speed) in enumerate(particles):
                d = speed*(1-(1-t)**2)
                px = x+math.cos(angle)*d
                py = y+math.sin(angle)*d+t*t*12
                color = mix(("#75c7ff",GOLD,GREEN)[i%3] if whole else "#75c7ff",GLASS_BG,t)
                length = max(1,4*(1-t))
                cv.create_line(px,py,px+math.cos(angle)*length,
                               py+math.sin(angle)*length,fill=color,width=1.6,
                               capstyle="round",tags="celebration",state="disabled")
            if t<1:
                self._effect_job = self.after(16,frame)
            else:
                self.body.delete("celebration")
                self.list.delete("celebration")
                self._effect_job = None
            self._sync_overlay()
        frame()

    def _fit(self,min_h=76):
        # Compatibility hook for external callers; rendering owns animated sizing.
        self.update_idletasks()

    # ── 文字层（主窗口半透明，文字保持不透明）──────────────────────────────
    # 思路：另开一个同尺寸、点击穿透的覆盖窗口，alpha 固定 1.0，
    # 只把文字/线条/图标复制上去，背景色抠成透明。这样调低主窗口 alpha
    # 只有玻璃变透，字还是实的。

    def _make_overlay(self):
        if not TEXT_OVERLAY:
            return
        try:
            ov = tk.Toplevel(self)
        except tk.TclError:
            return
        ov.withdraw()
        ov.overrideredirect(True)
        ov.attributes("-topmost", True)
        ov.configure(bg=TRANSPARENT)
        try:
            ov.attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            ov.configure(bg=GLASS_BG)
        try:
            ov.attributes("-alpha", 1.0)
        except tk.TclError:
            pass
        cv = tk.Canvas(ov, bg=TRANSPARENT, highlightthickness=0, bd=0)
        cv.pack(fill="both", expand=True)
        self._ov, self._ov_cv = ov, cv
        self._set_click_through(ov)

    @staticmethod
    def _set_click_through(win):
        """WS_EX_TRANSPARENT|WS_EX_NOACTIVATE：看得见，但点击落到下面的窗口。

        只加这两个位，绝不碰 WS_EX_LAYERED —— Tk 的 Toplevel 内层 HWND 一旦被
        标成 layered 而又没有 SetLayeredWindowAttributes，它会被当成 alpha=0
        合成，内容直接看不见（这正是文字层"完全没效果"的原因）。
        layered 由 -transparentcolor 自己加在外层，不用我们管。
        """
        if os.name != "nt":
            return
        import ctypes
        GWL_EXSTYLE = -20
        WS_EX_TRANSPARENT, WS_EX_NOACTIVATE = 0x20, 0x8000000
        u = ctypes.windll.user32
        inner = win.winfo_id()
        handles = [inner]
        parent = u.GetParent(inner)
        if parent:
            handles.append(parent)
        for hwnd in handles:
            try:
                style = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
                u.SetWindowLongW(hwnd, GWL_EXSTYLE,
                                 style | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
            except (AttributeError, OSError):
                pass

    def _place_overlay(self, e=None):
        ov = self._ov
        if ov is None:
            return
        # alpha 拉满时不需要文字层；跟着主窗口移动也没意义，直接收起来，
        # 免得桌面上多一个看不见却吃点击的窗口。
        if self._alpha >= .999:
            if self._ov_visible:
                try:
                    ov.withdraw()
                except tk.TclError:
                    self._ov = None
                self._ov_visible = False
            return
        x, y = self.winfo_rootx(), self.winfo_rooty()
        w, h = self.winfo_width(), self.winfo_height()
        if self._ov_rect == (x, y, w, h):
            return
        self._ov_rect = (x, y, w, h)
        try:
            ov.geometry(f"{max(1,w)}x{max(1,h)}+{x}+{y}")
            ov.deiconify()
            # deiconify 之后样式可能被重置，重新压一遍穿透
            self._set_click_through(ov)
            ov.attributes("-topmost", self._topmost)
            ov.lift()
            self._ov_visible = True
        except tk.TclError:
            self._ov = None

    def _near_bg(self, color):
        """这个填充色是不是就是面板底色。是的话在文字层里当背景丢掉。"""
        try:
            c = self.winfo_rgb(color)
        except tk.TclError:
            return False
        c = (c[0] // 256, c[1] // 256, c[2] // 256)
        for base in (GLASS_BG, GLASS_HI):
            try:
                b = self.winfo_rgb(base)
            except tk.TclError:
                continue
            b = (b[0] // 256, b[1] // 256, b[2] // 256)
            d = sum((c[i] - b[i]) ** 2 for i in range(3)) ** .5
            if d < 30:
                return True
        return False

    def _copy_items(self, src, dst, dx, dy, clip=None):
        """把 src 画布上的线条/图标/文字抄到文字层。

        src 是 DesignCanvas，coords() 返回逻辑单位，得乘回 factor 才能对上
        覆盖窗口的物理像素。dx/dy 也是物理像素。
        """
        factor = getattr(src, "factor", self._ui_scale)
        for item in src.find_all():
            try:
                kind = src.type(item)
            except tk.TclError:
                continue
            allowed = OV_OPTS.get(kind)
            if not allowed:
                continue
            try:
                if src.itemcget(item, "state") == "hidden":
                    continue
            except tk.TclError:
                pass
            coords = src.coords(item)
            if not coords:
                continue
            box = None
            try:
                box = src.bbox(item)
            except tk.TclError:
                box = None
            if clip and box:
                if box[3] < clip[0] or box[1] > clip[1]:
                    continue
            conf = {}
            for opt in allowed:
                try:
                    value = src.itemcget(item, opt)
                except tk.TclError:
                    continue
                if value != "":
                    conf[opt] = value
            if kind != "text":
                fill = conf.get("fill")
                if fill and self._near_bg(fill):
                    conf.pop("fill")
                if not conf.get("fill") and not conf.get("outline"):
                    continue
                if conf.get("fill") and box and \
                        (box[2] - box[0]) * (box[3] - box[1]) > OV_SKIP_AREA * factor * factor:
                    continue
            pts = [coords[i] * factor + (dx if i % 2 == 0 else dy)
                   for i in range(len(coords))]
            try:
                if kind == "text":
                    dst.create_text(pts[0], pts[1], **conf)
                elif kind == "line":
                    dst.create_line(*pts, **conf)
                elif kind == "polygon":
                    dst.create_polygon(*pts, **conf)
                elif kind == "rectangle":
                    dst.create_rectangle(*pts, **conf)
                elif kind == "oval":
                    dst.create_oval(*pts, **conf)
                elif kind == "arc":
                    dst.create_arc(*pts, **conf)
            except tk.TclError:
                pass

    def _sync_overlay(self, force=False):
        """把当前画面里该实的部分抄到文字层。alpha 拉满时整个隐藏。

        主窗口里的字不隐藏：它已经画在那儿了，藏起来会让文字上的点击热区失效
        （canvas 的 hidden item 收不到事件）。同一位置、同一颜色再盖一层不透明
        的字，视觉上就是"背景透了、字还是实的"，没有副作用。
        """
        if self._ov is None or self._ov_cv is None:
            return
        now = time.monotonic()
        if not force and now - self._ov_stamp < .045:
            return
        self._ov_stamp = now
        try:
            if self._alpha >= .999:
                if self._ov_visible:
                    self._ov_cv.delete("all")
                    self._ov.withdraw()
                    self._ov_visible = False
                return
            self._place_overlay()
            if self._ov is None:
                return
            cv = self._ov_cv
            cv.delete("all")
            self._copy_items(self.body, cv, 0, 0)
            if self._list_window is not None:
                scale = self._ui_scale
                # coords() 给的是逻辑单位，_copy_items 内部会再乘 factor，
                # 所以这里的偏移必须换成物理像素。
                lx, ly = self.body.coords(self._list_window)
                top = self.list.canvasy(0) * scale
                clip = (0, max(0, getattr(self, "_viewport_h", 0)) * scale)
                self._copy_items(self.list, cv, lx * scale, ly * scale - top, clip)
            if not self._ov_visible:
                self._ov.deiconify()
                self._ov.lift()
                self._ov_visible = True
        except tk.TclError:
            self._ov, self._ov_cv, self._ov_visible = None, None, False

    # ------------------------------------------------------------ 托盘与总结

    def _start_tray(self):
        """托盘图标是关闭面板后还能找回它的唯一入口，所以尽量起来。"""
        try:
            import tray as tray_mod
        except Exception:
            return
        try:
            self._tray = tray_mod.Tray({})
            if self._tray.start():
                self._refresh_tray_history()
            else:
                self._tray = None
        except Exception:
            self._tray = None
        if self._tray is not None:
            self.after(400, self._tray_poll)

    def _refresh_tray_history(self):
        if self._tray is None:
            return
        try:
            import daily_summary as ds
            self._tray.set_history(ds.history())
        except Exception:
            pass

    def _tray_poll(self):
        """pystray 在自己的线程里，只能把动作名塞队列，主线程在这里取。"""
        if self._tray is None:
            return
        try:
            action = self._tray.poll()
        except Exception:
            action = None
        if action:
            try:
                self._tray_action(action)
            except Exception:
                pass
        self.after(400, self._tray_poll)

    def _tray_action(self, action):
        if action == "summary":
            self._open_summary()
        elif action.startswith("summary:"):
            self._open_summary(action.split(":", 1)[1])
        elif action == "generate":
            self._generate_summary(open_after=True)
        elif action == "settings":
            self._open_detail_settings()
        elif action == "panel":
            self._toggle_panel_visible()
        elif action == "quit":
            self._quit_all()

    def _open_summary(self, date=None):
        """没指定日期就打开今天；今天还没生成过就先生成再打开。"""
        try:
            import daily_summary as ds
        except Exception:
            return
        try:
            if date:
                path = os.path.join(ds.OUT, "%s.html" % date)
                if not os.path.exists(path):
                    path = ds.build(ds.datetime.strptime(date, "%Y-%m-%d").date(),
                                    use_llm=False)
            else:
                path = os.path.join(ds.OUT, "%s.html" % ds.datetime.now(ds.TZ).date())
                if not os.path.exists(path):
                    path = self._generate_summary(open_after=False)
            if path and os.path.exists(path):
                os.startfile(path)
        except Exception:
            pass

    def _generate_summary(self, open_after=False):
        """生成会问一次模型，可能要几秒；放后台线程，别卡住面板。"""
        if self._summary_busy:
            return None
        self._summary_busy = True
        result = {}

        def run():
            try:
                import daily_summary as ds
                path = ds.build()
                result["path"] = path
                ds.mark_auto(ds.datetime.now(ds.TZ).date())
            except Exception as exc:
                result["error"] = str(exc)
            finally:
                self._summary_busy = False

        import threading
        threading.Thread(target=run, daemon=True).start()

        def wait(n=0):
            if self._summary_busy and n < 120:
                self.after(250, lambda: wait(n + 1))
                return
            path = result.get("path")
            self._refresh_tray_history()
            if not path:
                self._flash_note("总结没生成出来，看 logs 里的报错")
                return
            if open_after and os.path.exists(path):
                try:
                    os.startfile(path)
                except OSError:
                    pass
        self.after(250, wait)
        return result.get("path")

    def _flash_note(self, text):
        """在顶栏当前行动位置闪一句提示，2 秒后自动回到正常内容。

        不弹窗：托盘操作经常是顺手点的，弹窗要额外点一次才能关掉。
        """
        try:
            self._note = text
            self.render()
            self.after(2200, self._clear_note)
        except tk.TclError:
            pass

    def _clear_note(self):
        self._note = None
        try:
            self.render()
        except tk.TclError:
            pass

    def _summary_tick(self):
        """到点自动生成。每天只生成一次，靠 summaries/.auto-<date> 记。"""
        try:
            import daily_summary as ds
            hour = int(self._summary_hour or 18)
            day = ds.auto_due(hour)
            if day and not self._summary_busy:
                self._generate_summary(open_after=False)
                ds.mark_auto(day)
                self._refresh_tray_history()
        except Exception:
            pass

    def _open_detail_settings(self):
        try:
            import settings_window as sw
        except Exception:
            return
        if self._detail is not None:
            try:
                if self._detail.top.winfo_exists():
                    self._detail.focus()
                    return
            except tk.TclError:
                pass
            self._detail = None
        pal = sw.palette_from(SKINS[self._skin_key])
        self._detail = sw.SettingsWindow(self, pal, on_saved=self._apply_detail)

    def _apply_detail(self, llm, ui):
        """设置保存后立刻生效：字体大小和皮肤不用重启。"""
        size = ui.get("font_size")
        if isinstance(size, int) and size != self._font_size:
            self._font_size = max(8, min(16, size))
            for key, font in self._fonts.items():
                font.configure(size=self._font_size if key != "small"
                               else max(7, self._font_size - 2))
            self._line = max(21, self._fonts["body"].metrics("linespace") / self._ui_scale + 3)
            self._small_line = max(17, self._fonts["small"].metrics("linespace") / self._ui_scale + 2)
            self.render()
        hour = ui.get("summary_hour")
        if isinstance(hour, int):
            self._summary_hour = hour

    def _quit_all(self):
        """托盘退出 = 面板和后台引擎一起停，否则进程会留在后台没人看得见。"""
        if svc is not None:
            try:
                svc.stop_workers()
            except Exception:
                pass
        self._close(None)

    def _card_click(self,e):
        if e.x < W-95:
            self._toggle(e)


if __name__ == "__main__":
    QuestHUD().mainloop()

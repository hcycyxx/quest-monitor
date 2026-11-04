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

STATE_FILE = os.path.join(ROOT, "config", "quest_state.json")
ALIVE_FILE = os.path.join(ROOT, "config", "panel_alive")

sys.path.insert(0, os.path.join(ROOT, "engine"))
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
TRANSPARENT = "#010203"
F_TITLE = ("Microsoft YaHei UI", 10, "bold")
F_BODY = ("Microsoft YaHei UI", 10)
F_SMALL = ("Microsoft YaHei UI", 8)
F_MICRO = F_SMALL
W = 336
TZ = timezone(timedelta(hours=8))
SKINS = {
    "glass": {"name":"深蓝玻璃", "bg":"#14171f", "hi":"#232a38", "text":"#f1f5fc", "muted":"#a8b7cc", "gold":"#ffd166", "cyan":"#7de3f4", "green":"#5be3a2", "alpha":1., "radius":16, "family":"Microsoft YaHei UI", "brand":"任务追踪"},
    "transparent": {"name":"轻透悬浮", "bg":"#182330", "hi":"#2b3c4e", "text":"#ffffff", "muted":"#cfdaea", "gold":"#ffe1a0", "cyan":"#b3efff", "green":"#92efc3", "alpha":.90, "radius":16, "family":"Microsoft YaHei UI", "brand":"轻透任务"},
    "journal": {"name":"杂志手账", "bg":"#f4efe3", "hi":"#eae1ce", "text":"#342e29", "muted":"#6b6054", "gold":"#96623b", "cyan":"#396c73", "green":"#3c7052", "alpha":1., "radius":7, "family":"SimSun", "brand":"工作手记"},
    "night": {"name":"夜航 HUD", "bg":"#101b25", "hi":"#1c2e3c", "text":"#edf8ff", "muted":"#abc4d6", "gold":"#8ae8ff", "cyan":"#c0b3ff", "green":"#68edb8", "alpha":1., "radius":6, "family":"Microsoft YaHei UI", "brand":"任务导航"},
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
        self.title("任务追踪 · Codex V6")
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
        self._skin_key = "glass"
        self._skin_choice = tk.StringVar(self, value="glass")
        self._fonts = {"title": tkfont.Font(self, font=F_TITLE),
                       "body": tkfont.Font(self, font=F_BODY),
                       "small": tkfont.Font(self, font=F_SMALL)}
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
        self.render()
        self.after(3000, self.tick)

    def _drag_start(self, e):
        self._cancel_edge()
        self._drag = (e.x_root - self.winfo_x(), e.y_root - self.winfo_y())
        self._dock_side = None
        self._edge_pinned = False

    def _drag_move(self, e):
        if self._drag:
            x = e.x_root - self._drag[0]
            y = max(0, e.y_root - self._drag[1])
            x = max(0, min(self.winfo_screenwidth() - round(W*self._ui_scale), x))
            self.geometry(f"+{x}+{y}")

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

    def _toggle(self, e=None):
        if self._guard_reveal(e):
            return
        self._expanded = not self._expanded
        self.render()

    def _close(self, e=None):
        if self._guard_reveal(e):
            return
        for job in (self._motion_job, self._edge_job, self._effect_job):
            if job:
                self.after_cancel(job)
        self._hide_tip()
        try:
            os.remove(ALIVE_FILE)
        except OSError:
            pass
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
        self.after(3000, self.tick)

    def _hide_tip(self, e=None):
        if self._tip:
            self._tip.destroy()
            self._tip = None

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

    def _escape(self, e=None):
        self._hide_tip()
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

    def _header(self, s, current):
        cv = self.body
        mini = self._minimized
        self._header_h = 44 if mini else max(112, 47 + self._line*2 + self._small_line)
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
        self._hit(cv,W-146,7,25,27,"skin",self._skin_picker,GLASS_BG)
        for dx,dy,c in ((-3,-3,SUB),(4,-3,SUB),(-3,4,SUB),(4,4,SUB)):
            cv.create_oval(W-134+dx-2,20+dy-2,W-134+dx+2,20+dy+2,fill=c,outline="",tags="skin")
        # 暂停/继续：停掉采样看门与 LLM 引擎，面板本身留着，否则没按钮点继续
        self._hit(cv,W-114,7,24,27,"power",self._toggle_power)
        pc = GOLD if paused else SUB
        if paused:
            cv.create_polygon(W-108,15,W-108,25,W-100,20,fill=pc,outline="",tags="power")
        else:
            cv.create_line(W-107,15,W-107,25,fill=pc,width=2.2,tags="power")
            cv.create_line(W-99,15,W-99,25,fill=pc,width=2.2,tags="power")
        for name, x, callback in (("pin",W-84,self._pin_edge),
                                   ("minus",W-54,self._minimize),
                                   ("close",W-24,self._close)):
            if name == "pin" and not self._dock_side:
                continue
            self._hit(cv,x-12,7,24,27,name,callback)
            if name == "minus":
                cv.create_line(x-5,20,x+5,20,fill=SUB,width=1.4,tags=name)
            elif name == "close":
                cv.create_line(x-4,16,x+4,24,fill=SUB,width=1.4,tags=name)
                cv.create_line(x-4,24,x+4,16,fill=SUB,width=1.4,tags=name)
            else:
                color = GOLD if self._edge_pinned else SUB
                cv.create_oval(x-4,15,x+4,23,outline=color,width=1.4,tags=name)
                cv.create_line(x,23,x,27,fill=color,width=1.4,tags=name)
        # 这排图标没有文字，鼠标停上去得说清楚是干什么的
        hints = {
            "skin": "换皮肤",
            "power": "继续（重启采样与 AI 分析）" if self._paused else "暂停（停止采样，不再消耗 token）",
            "pin": "取消贴边固定" if self._edge_pinned else "固定：贴边后不自动缩成把手",
            "minus": "收起成一条窄条",
            "close": "关闭面板（后台服务仍在运行）",
        }
        for tag, text in hints.items():
            cv.tag_bind(tag, "<Enter>", lambda e, t=text: self._show_tip(t, e), add="+")
            cv.tag_bind(tag, "<Leave>", self._hide_tip, add="+")
        act = str(s.get("current_activity") or "暂无当前行动")
        act = re.sub(r"[（(][a-zA-Z0-9_.\-]+\.(?:exe|py|txt|xlsx?|docx?|pdf)[）)]", "", act)
        if paused and not s.get("current_activity"):
            act = "观察已暂停"
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
        self._text(cv,73,46,act,W-113,"body",WHITE,2,("expand",))
        title = current.get("title", "") if current else "暂无主线任务"
        self._text(cv,73,self._header_h-self._small_line-12,title,W-113,"small",SUB,1,("expand",))
        self._chevron(cv,W-25,76,self._expanded,tags=("expand",))

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

    def _section(self, quests, label, color, key, readonly=False):
        cv = self.list
        y = self._draw_y
        active = [q for q in quests if q.get("status") != "done"]
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
        lines = self._wrap(title,W-78,"body",2)
        h = len(lines)*self._line
        self._hit(cv,13,y,W-73,h+4,"quest:"+uid,
                  lambda e,k=key,i=qid:self._quest_click(k,i,e))
        self._text(cv,17,y+2,title,W-78,"body",WHITE,2,("quest:"+uid,))
        note = str(q.get("note") or "暂无补充说明")
        info = "info:"+uid
        self._hit(cv,W-52,y,26,27,info,lambda e,t=note:self._show_tip(t,e))
        cv.create_oval(W-45,y+5,W-32,y+18,outline=SUB,width=1,tags=info)
        cv.create_text(W-38.5,y+11,text="i",font=self._fonts["small"],fill=SUB,tags=info)
        cv.tag_bind(info,"<Enter>",lambda e,t=note:self._show_tip(t,e))
        cv.tag_bind(info,"<Leave>",self._hide_tip)
        y += h + 7
        frac, label, source = self._measure_progress(q)
        self._text(cv,17,y,self._live_line(q),W-145,"small",SUB,1)
        cv.create_text(W-31,y,anchor="ne",text=label,font=self._fonts["small"],fill=SUB)
        y += self._small_line + 6
        waiting = q.get("status") == "waiting"
        self._draw_progress(cv,q,uid,17,y,W-48,CYAN if waiting else color)
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
        menu = tk.Menu(self,tearoff=False,bg=GLASS_HI,fg=WHITE,
                       activebackground=mix(GLASS_HI,SUB,.2),activeforeground=WHITE,
                       selectcolor=GOLD,font=self._fonts["small"],borderwidth=0)
        for key,skin in SKINS.items():
            menu.add_radiobutton(label=skin["name"],variable=self._skin_choice,
                                 value=key,command=lambda k=key:self._set_skin(k))
        menu.bind("<Unmap>",lambda e: self.after_idle(menu.destroy))
        try:
            menu.tk_popup(min(e.x_root,self.winfo_screenwidth()-180),e.y_root+8)
        finally:
            menu.grab_release()

    def _set_skin(self,key):
        global GLASS_BG,GLASS_HI,STROKE,WHITE,SUB,FAINT,GOLD,GOLD_DIM,CYAN,GREEN,F_SMALL
        skin = SKINS[key]
        self._skin_key = key
        self._skin_choice.set(key)
        GLASS_BG,GLASS_HI = skin["bg"],skin["hi"]
        WHITE,SUB,FAINT = skin["text"],skin["muted"],skin["muted"]
        GOLD,CYAN,GREEN = skin["gold"],skin["cyan"],skin["green"]
        STROKE,GOLD_DIM = mix(GLASS_BG,SUB,.4),GOLD
        F_SMALL = (skin["family"],8)
        for font in self._fonts.values():
            font.configure(family=skin["family"])
        self._line = max(21,self._fonts["body"].metrics("linespace")/self._ui_scale+3)
        self._small_line = max(17,self._fonts["small"].metrics("linespace")/self._ui_scale+2)
        try:
            self.attributes("-alpha",skin["alpha"])
        except tk.TclError:
            pass
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
        current = next((q for q in mains if q.get("status")=="active"),None)
        current = current or next((q for q in mains if q.get("status")!="done"),None)
        # A layered outline rather than artificial noise; transparent outside corners.
        self.list.configure(bg=GLASS_BG)
        self._shell = rounded(self.body,1,1,W-2,126,SKINS[self._skin_key]["radius"],fill=GLASS_BG,outline=mix(GLASS_BG,SUB,.65),width=1)
        self.body.create_line(24,2,W-24,2,fill=mix(GLASS_HI,WHITE,.5))
        self.body.create_line(17,3,W//2,3,fill=GLASS_HI)
        self._header(s,current)
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
        frame()

    def _fit(self,min_h=76):
        # Compatibility hook for external callers; rendering owns animated sizing.
        self.update_idletasks()

    def _card_click(self,e):
        if e.x < W-95:
            self._toggle(e)


if __name__ == "__main__":
    QuestHUD().mainloop()

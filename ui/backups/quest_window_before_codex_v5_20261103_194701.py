# -*- coding: utf-8 -*-
"""任务面板 · 液态玻璃 HUD（方向 A）
- 亚克力质感：分层噪声纹理 + 高光描边 + 深色玻璃底
- 默认折叠：只显示 当前行动 + 主线进度条；点击展开
- 步骤为进度环 + 可点击勾选；note 收进悬浮提示
"""
import json
import os
import time
import math
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(ROOT, "config", "quest_state.json")

# ── 液态玻璃皮肤 ─────────────────────────────────────────
GLASS_BG    = "#14171f"    # 玻璃深底
GLASS_HI    = "#232a38"    # 玻璃亮部（卡片）
STROKE      = "#3a4358"    # 描边
WHITE       = "#f2f4fa"
SUB         = "#a8b1c7"    # 次级文字（比旧灰亮，保证对比度）
FAINT       = "#77809a"
GOLD        = "#ffd166"    # 主线琥珀金
GOLD_DIM    = "#8a7440"
CYAN        = "#7de3f4"    # 支线冰青
GREEN       = "#5be3a2"
RED         = "#ff8080"

F_TITLE = ("Microsoft YaHei UI", 11, "bold")
F_BODY  = ("Microsoft YaHei UI", 10)
F_SMALL = ("Microsoft YaHei UI", 8)
F_MICRO = ("Microsoft YaHei UI", 7)

W = 336   # 面板宽


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"main_quests": [], "side_quests": [], "current_activity": "",
                "suggestion": "", "updated_at": ""}


def save_state(s):
    s["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S") + "+08:00"
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


def noise_canvas(cv, w, h, seed=7):
    """在 canvas 上画细微噪点+顶部高光，模拟玻璃质感"""
    import random
    rnd = random.Random(seed)
    for _ in range(int(w * h / 900)):
        x, y = rnd.randrange(w), rnd.randrange(h)
        a = rnd.choice(("#1c2029", "#181c25", "#1a1e28"))
        cv.create_rectangle(x, y, x + 1, y + 1, fill=a, outline="")
    # 顶部高光斜线
    cv.create_line(0, 1, w, 1, fill="#4a5570", width=1)
    cv.create_line(2, 2, w - 2, 2, fill="#2a3140", width=1)


def ring(cv, cx, cy, r, frac, color, width=3):
    """圆环进度"""
    bg = cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline="#2a3140", width=width)
    if frac <= 0:
        return bg
    extent = -360 * frac
    arc = cv.create_arc(cx - r, cy - r, cx + r, cy + r, start=90, extent=extent,
                        style="arc", outline=color, width=width)
    return arc


class QuestHUD(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("任务面板")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=GLASS_BG)
        sw = self.winfo_screenwidth()
        self.geometry(f"{W}x160+{sw-W-24}+36")
        self._drag = None
        self._expanded = False
        self._minimized = False
        self._show_done = False
        self._tip = None

        self.body = tk.Frame(self, bg=GLASS_BG)
        self.body.pack(fill="both", expand=True)
        self._last_mtime = 0
        self.render()
        self.after(3000, self.tick)

    # ── 交互 ──
    def _drag_start(self, e):
        self._drag = (e.x, e.y)
    def _drag_move(self, e):
        if self._drag:
            self.geometry(f"+{self.winfo_x()+(e.x-self._drag[0])}+{self.winfo_y()+(e.y-self._drag[1])}")

    def _drag_end(self, e):
        if self._drag:
            self._drag = None
            self._snap_edge()

    def _toggle(self, e=None):
        self._expanded = not self._expanded
        self.render()

    def _close(self, e):
        self.destroy()

    def _minimize(self, e):
        self._minimized = not self._minimized
        self.render()

    # ── 贴边吸附 ──
    EDGE = 12  # 吸附半径

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
        s = load_state()
        for q in s.get(key, []):
            if q.get("id") == qid:
                st = q.get("steps", [])
                if idx < len(st):
                    st[idx]["done"] = not st[idx].get("done")
                if st and all(x.get("done") for x in st):
                    q["status"] = "done"
                break
        save_state(s)
        self._last_mtime = os.path.getmtime(STATE_FILE)
        self.render()

    def _toggle_quest(self, key, qid):
        s = load_state()
        for q in s.get(key, []):
            if q.get("id") == qid:
                q["status"] = "done" if q.get("status") != "done" else "active"
                if q["status"] == "done" and q.get("steps"):
                    for x in q["steps"]:
                        x["done"] = True
                break
        save_state(s)
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
        self._tip.geometry(f"300x?+{x}+{y}")
        fr = tk.Frame(self._tip, bg="#0f1218", highlightthickness=1, highlightbackground=STROKE)
        fr.pack(fill="both", expand=True)
        tk.Label(fr, text=text, font=F_SMALL, fg=SUB, bg="#0f1218",
                 wraplength=280, justify="left").pack(padx=10, pady=8)

    def _hide_tip(self, e=None):
        if self._tip:
            self._tip.destroy()
            self._tip = None

    def tick(self):
        try:
            m = os.path.getmtime(STATE_FILE)
        except OSError:
            m = 0
        if m != self._last_mtime:
            self._last_mtime = m
            self.render()
        self.after(3000, self.tick)

    # ── 渲染 ──
    def render(self):
        for w in self.body.winfo_children():
            w.destroy()
        s = load_state()

        mains = s.get("main_quests", [])
        sides = s.get("side_quests", [])
        active_main = next((q for q in mains if q.get("status") == "active"), None)
        if not active_main and mains:
            active_main = mains[0]

        # 计算主线进度
        prog_frac = 0.0
        prog_text = ""
        if active_main:
            steps = active_main.get("steps", [])
            if steps:
                dn = sum(1 for x in steps if x.get("done"))
                prog_frac = dn / len(steps)
                prog_text = f"{dn}/{len(steps)}"
            elif active_main.get("progress"):
                prog_text = active_main["progress"]

        # 最小化态：只画窄标题条
        if self._minimized:
            bar = tk.Frame(self.body, bg=GLASS_HI, highlightthickness=1,
                           highlightbackground=STROKE, cursor="hand2")
            bar.pack(fill="x", padx=10, pady=10)
            bcv = tk.Canvas(bar, width=W - 40, height=26, bg=GLASS_HI, highlightthickness=0)
            bcv.pack()
            noise_canvas(bcv, W - 40, 26)
            ring(bcv, 14, 13, 8, prog_frac, GOLD, 2)
            bcv.create_text(28, 13, anchor="w", text=(s.get("current_activity", "") or "任务面板")[:24],
                            font=F_SMALL, fill=WHITE)
            bcv.create_text(W - 64, 13, anchor="e", text="▣", font=F_MICRO, fill=SUB,
                            tags=("mb2",))
            bcv.tag_bind("mb2", "<Button-1>", self._minimize)
            bcv.create_text(W - 44, 13, anchor="e", text="✕", font=F_MICRO, fill=SUB,
                            tags=("xb2",))
            bcv.tag_bind("xb2", "<Button-1>", self._close)
            bcv.bind("<B1-Motion>", self._drag_move)
            bcv.bind("<ButtonRelease-1>", self._drag_end)
            bcv.bind("<Button-1>", lambda e: self._drag_start(e))
            self._fit(min_h=30)
            return

        # ── 主玻璃卡 ──
        card = tk.Frame(self.body, bg=GLASS_HI, highlightthickness=1,
                        highlightbackground=STROKE, cursor="hand2")
        card.pack(fill="x", padx=10, pady=10)
        cv = tk.Canvas(card, width=W - 40, height=70, bg=GLASS_HI, highlightthickness=0)
        cv.pack()
        noise_canvas(cv, W - 40, 70)
        # 玻璃高光：顶部 1px 亮边 + 左上斜向高光线
        cv.create_line(1, 1, W - 42, 1, fill="#5a647f", width=1)
        cv.create_line(4, 2, int((W - 42) * 0.55), 2, fill="#3d465c", width=1)

        # 左：进度环（更大更醒目）
        ring(cv, 27, 35, 19, prog_frac, GOLD, 4)
        cv.create_text(27, 35, text=prog_text or "—", font=("Microsoft YaHei UI", 9, "bold"), fill=WHITE)

        # 右：当前行动（两行，剥离进程名等噪音；在自然断点断行）
        cv.create_text(58, 12, anchor="w", text="◈ 当前行动", font=F_MICRO, fill=FAINT)
        import re as _re
        act = s.get("current_activity", "") or "空闲"
        act = _re.sub(r"[（(][a-zA-Z0-9_.\-]+\.(exe|py|txt|xlsx?|docx?|pdf)[）)]", "", act)
        act = _re.sub(r"\s+", " ", act).strip() or "空闲"
        # 优先在 "，" "、" "：" 后断行
        cut = -1
        for ch in ("，", "、", "："):
            p = act.find(ch)
            if 0 < p <= 22:
                cut = max(cut, p + 1)
        if cut > 0:
            l1, l2 = act[:cut], act[cut:cut + 20]
        else:
            l1, l2 = act[:20], act[20:40]
        cv.create_text(58, 27, anchor="w", text=l1, font=F_BODY, fill=WHITE)
        cv.create_text(58, 44, anchor="w", text=l2, font=F_SMALL, fill=SUB)
        main_title = active_main.get("title", "") if active_main else "暂无主线 · 点此展开"
        cv.create_text(58, 58, anchor="w", text="★ " + main_title[:24], font=F_SMALL, fill=GOLD)

        # 状态灯（右上角）
        cv.create_text(W - 56, 12, anchor="e", text="●", font=F_MICRO,
                       fill=GREEN if active_main else FAINT)
        cv.create_text(W - 46, 12, anchor="e", text=s.get("updated_at", "")[11:16],
                       font=F_MICRO, fill=SUB)
        # 关闭/最小化按钮（加大热区：透明矩形 24x20）
        mb = cv.create_text(W - 38, 12, text="—", font=("Microsoft YaHei UI", 9, "bold"), fill=SUB)
        cv.create_rectangle(W - 50, 2, W - 26, 22, fill="", outline="", tags=("mb_hit",))
        cv.tag_bind("mb_hit", "<Button-1>", self._minimize)
        xb = cv.create_text(W - 14, 12, text="✕", font=("Microsoft YaHei UI", 9, "bold"), fill=SUB)
        cv.create_rectangle(W - 26, 2, W - 2, 22, fill="", outline="", tags=("xb_hit",))
        cv.tag_bind("xb_hit", "<Button-1>", self._close)
        # 卡片点击展开（排除右上角按钮热区）
        card.bind("<Button-1>", self._card_click)
        # 拖动（松手吸附贴边）
        cv.bind("<B1-Motion>", self._drag_move)
        cv.bind("<ButtonRelease-1>", self._drag_end)
        cv.bind("<Button-1>", lambda e: self._drag_start(e) if e.y < 16 else None)

        if not self._expanded:
            # 折叠态：底部一行小箭头提示
            foot = tk.Label(self.body, text="⌃ 展开任务列表", font=F_MICRO, fg=FAINT,
                            bg=GLASS_BG, cursor="hand2")
            foot.pack(pady=(0, 8))
            foot.bind("<Button-1>", self._toggle)
            self._fit()
            return

        # ── 展开态 ──
        self._section(mains, "★ 主线", GOLD, "main_quests")
        self._section(sides, "◆ 支线", CYAN, "side_quests")

        # 已完成任务折叠区
        done_quests = [q for q in mains + sides if q.get("status") == "done"]
        if done_quests:
            n = len(done_quests)
            head = tk.Frame(self.body, bg=GLASS_BG, cursor="hand2")
            head.pack(fill="x", padx=12, pady=(8, 2))
            txt = f"{'▾' if self._show_done else '▸'} ✓ 已完成 ({n})"
            tk.Label(head, text=txt, font=("Microsoft YaHei UI", 9, "bold"),
                     fg=GREEN, bg=GLASS_BG).pack(side="left")
            head.bind("<Button-1>", lambda e: self._toggle_done())
            if self._show_done:
                self._section(done_quests, "", GREEN, None, readonly=True)

        sug = s.get("suggestion", "")
        if sug:
            bar = tk.Frame(self.body, bg=GLASS_HI, highlightthickness=1,
                           highlightbackground=GOLD_DIM)
            bar.pack(fill="x", padx=10, pady=(6, 4))
            tk.Label(bar, text="💡 建议", font=("Microsoft YaHei UI", 8, "bold"),
                     fg=GOLD_DIM, bg=GLASS_HI).pack(anchor="w", padx=10, pady=(6, 0))
            tk.Label(bar, text=sug, font=F_SMALL, fg=GOLD, bg=GLASS_HI,
                     wraplength=W - 60, justify="left").pack(padx=10, pady=(2, 8))

        foot = tk.Label(self.body, text="⌄ 收起", font=F_MICRO, fg=FAINT,
                        bg=GLASS_BG, cursor="hand2")
        foot.pack(pady=(0, 8))
        foot.bind("<Button-1>", self._toggle)
        self._fit()

    def _toggle_done(self, e=None):
        self._show_done = not self._show_done
        self.render()

    def _section(self, quests, label, color, key, readonly=False):
        if not quests:
            return
        if label:
            head = tk.Frame(self.body, bg=GLASS_BG)
            head.pack(fill="x", padx=12, pady=(8, 2))
            tk.Label(head, text=label, font=("Microsoft YaHei UI", 9, "bold"),
                     fg=color, bg=GLASS_BG).pack(side="left")
            tk.Frame(head, bg=STROKE, height=1).pack(side="left", fill="x", expand=True, padx=8, pady=4)
        for q in quests:
            qid = q.get("id", "")
            done = q.get("status") == "done"
            active = q.get("status") == "active"
            fg = GREEN if done else (WHITE if active else SUB)
            steps = q.get("steps", [])
            dn = sum(1 for x in steps if x.get("done"))
            frac = (dn / len(steps)) if steps else (1.0 if done else 0.0)

            row = tk.Frame(self.body, bg=GLASS_HI, highlightthickness=1,
                           highlightbackground=STROKE, cursor="hand2")
            row.pack(fill="x", padx=10, pady=2)
            top = tk.Frame(row, bg=GLASS_HI)
            top.pack(fill="x", padx=8, pady=(6, 2))
            # 6px 实心色点（支线=冰青 / 主线=金 / 完成=绿），替代大空心圆
            dot_c = GREEN if done else color
            dot = tk.Canvas(top, width=10, height=10, bg=GLASS_HI, highlightthickness=0)
            dot.pack(side="left", padx=(2, 4), pady=6)
            dot.create_oval(1, 1, 9, 9, fill=dot_c, outline="")
            # 标题手动断行：在自然断点（空格/括号前）预插 \n，避免 DeepSeek 被劈开
            title = q.get("title", "")
            lbl = tk.Label(top, text=title, font=F_BODY, fg=fg,
                           bg=GLASS_HI, wraplength=W - 120, justify="left")
            lbl.pack(side="left", padx=(4, 0), pady=(0, 2))
            if not readonly:
                lbl.bind("<Button-1>", lambda e, k=key, i=qid: self._toggle_quest(k, i))
            # note → 悬浮提示
            note = q.get("note", "")
            if note:
                info = tk.Label(top, text="ⓘ", font=F_MICRO, fg=FAINT, bg=GLASS_HI, cursor="hand2")
                info.pack(side="right")
                info.bind("<Enter>", lambda e, t=note: self._show_tip(t, e))
                info.bind("<Leave>", self._hide_tip)
            # 步骤（已完成区只读展示）
            for idx, st in enumerate(steps):
                sd = st.get("done")
                sl = tk.Label(row, text=f"{'✓' if sd else '○'} {st.get('text','')}",
                              font=F_SMALL, fg=GREEN if sd else SUB, bg=GLASS_HI,
                              cursor="hand2" if not readonly else "arrow", anchor="w")
                sl.pack(fill="x", padx=30, pady=1)
                if not readonly:
                    sl.bind("<Button-1>", lambda e, k=key, i=qid, j=idx: self._toggle_step(k, i, j))

    def _fit(self, min_h=76):
        self.update_idletasks()
        h = self.body.winfo_reqheight() + 6
        self.geometry(f"{W}x{max(h, min_h)}+{self.winfo_x()}+{self.winfo_y()}")

    def _card_click(self, e):
        # canvas 坐标 x >= W-52 区域是 —/✕ 按钮热区，不触发展开
        if e.x >= W - 52:
            return
        self._toggle(e)


if __name__ == "__main__":
    QuestHUD().mainloop()

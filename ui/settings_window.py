# -*- coding: utf-8 -*-
"""详细设置窗口：模型 API、字体大小、皮肤、透明度、内容抓取、每日总结时间。

从托盘右键菜单打开。跟面板里那个小设置气泡不是一回事：
那个只管皮肤和透明度（改完立刻见效），这个管所有落盘的配置项。
"""
import json
import os
import tkinter as tk
import tkinter.font as tkfont

import paths

LLM = paths.config("llm.json")
UI = paths.config("ui.json")

LEVELS = (("off", "关闭：只带窗口标题"), ("light", "轻量：最近 2 段"),
          ("full", "完整：最近 5 段"))
ENGINES = (("auto", "自动（先用 RapidOCR）"), ("rapid", "只用 RapidOCR"),
           ("windows", "只用系统 OCR"), ("off", "不做 OCR"))


def _read(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else dict(default)
    except (OSError, ValueError):
        return dict(default)


def _write(path, data):
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


class SettingsWindow:
    """普通带边框的窗口：设置这种东西需要能拖动、能最小化、能同时看文档。"""

    def __init__(self, master, palette, on_saved=None):
        self.master = master
        self.pal = palette
        self.on_saved = on_saved
        self.top = tk.Toplevel(master)
        self.top.title("SideQuest 设置")
        self.top.configure(bg=palette["bg"])
        self.top.geometry("560x660")
        self.top.minsize(520, 480)
        try:
            self.top.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.llm = _read(LLM, {"base_url": "http://127.0.0.1:8899/v1",
                               "api_key": "sk-local",
                               "model": "deepseek-v4.1-flash",
                               "interval_seconds": 60})
        self.ui = _read(UI, {})
        self.vars = {}
        self._build()
        self.top.protocol("WM_DELETE_WINDOW", self.close)

    # ---------------------------------------------------------------- 构件
    def _label(self, parent, text, size=9, color=None, bold=False):
        font = (self.pal["family"], size, "bold") if bold else (self.pal["family"], size)
        return tk.Label(parent, text=text, bg=self.pal["bg"],
                        fg=color or self.pal["muted"], font=font, anchor="w")

    def _entry(self, parent, key, value, width=32):
        var = tk.StringVar(value=str(value))
        self.vars[key] = var
        box = tk.Entry(parent, textvariable=var, width=width,
                       bg=self.pal["hi"], fg=self.pal["text"],
                       insertbackground=self.pal["text"], relief="flat",
                       highlightthickness=1, highlightbackground=self.pal["stroke"],
                       highlightcolor=self.pal["gold"], font=(self.pal["family"], 9))
        return box

    def _section(self, parent, title):
        frame = tk.Frame(parent, bg=self.pal["bg"])
        frame.pack(fill="x", padx=18, pady=(14, 2))
        tk.Label(frame, text=title, bg=self.pal["bg"], fg=self.pal["gold"],
                 font=(self.pal["family"], 10, "bold"), anchor="w").pack(side="left")
        tk.Frame(frame, bg=self.pal["stroke"], height=1).pack(
            side="left", fill="x", expand=True, padx=(10, 0), pady=(8, 0))
        return frame

    def _row(self, parent, label, widget, hint=""):
        row = tk.Frame(parent, bg=self.pal["bg"])
        row.pack(fill="x", padx=18, pady=3)
        self._label(row, label).pack(side="left", anchor="n", pady=4)
        widget.pack(side="right", anchor="e")
        if hint:
            tip = tk.Label(parent, text=hint, bg=self.pal["bg"], fg=self.pal["faint"],
                           font=(self.pal["family"], 8), anchor="w", justify="left")
            tip.pack(fill="x", padx=18, pady=(0, 2))
        return row

    def _build(self):
        bg = self.pal["bg"]
        outer = tk.Frame(self.top, bg=bg)
        outer.pack(fill="both", expand=True)

        # ---- 模型 API
        self._section(outer, "模型 API")
        self._row(outer, "接口地址",
                  self._entry(outer, "base_url", self.llm.get("base_url", "")),
                  "OpenAI 兼容的 /v1 地址，例如 http://127.0.0.1:8899/v1")
        self._row(outer, "API Key",
                  self._entry(outer, "api_key", self.llm.get("api_key", "")),
                  "本地网关随便填；云端服务要填真 key")
        self._row(outer, "模型名",
                  self._entry(outer, "model", self.llm.get("model", "")),
                  "例如 deepseek-v4.1-flash、gpt-4o-mini")
        self._row(outer, "分析间隔（秒）",
                  self._entry(outer, "interval_seconds",
                              self.llm.get("interval_seconds", 60), 8),
                  "多久看一次轨迹。60 秒是默认值，调小会更灵敏也更费 token")

        # ---- 窗口内容
        self._section(outer, "窗口内容")
        capture = tk.BooleanVar(value=bool(self.llm.get("content_capture", True)))
        self.vars["content_capture"] = capture
        tk.Checkbutton(outer, text="读取窗口里显示的文字（关掉就只看窗口标题）",
                       variable=capture, bg=bg, fg=self.pal["text"],
                       activebackground=bg, activeforeground=self.pal["gold"],
                       selectcolor=self.pal["hi"], anchor="w",
                       font=(self.pal["family"], 9)).pack(fill="x", padx=18, pady=3)

        doc = tk.BooleanVar(value=bool(self.llm.get("doc_read", True)))
        self.vars["doc_read"] = doc
        tk.Checkbutton(outer, text="直接读 Excel / Word 文件的原文（最准，推荐）",
                       variable=doc, bg=bg, fg=self.pal["text"],
                       activebackground=bg, activeforeground=self.pal["gold"],
                       selectcolor=self.pal["hi"], anchor="w",
                       font=(self.pal["family"], 9)).pack(fill="x", padx=18, pady=3)

        self._label(outer, "带多少内容给模型").pack(fill="x", padx=18, pady=(6, 0))
        level = tk.StringVar(value=str(self.llm.get("content_level", "light")))
        self.vars["content_level"] = level
        for key, text in LEVELS:
            tk.Radiobutton(outer, text=text, value=key, variable=level,
                           bg=bg, fg=self.pal["text"], activebackground=bg,
                           activeforeground=self.pal["gold"], selectcolor=self.pal["hi"],
                           anchor="w", font=(self.pal["family"], 9)).pack(
                fill="x", padx=26, pady=1)

        engine = tk.StringVar(value=str(self.llm.get("ocr_engine", "auto")))
        self.vars["ocr_engine"] = engine
        row = tk.Frame(outer, bg=bg)
        row.pack(fill="x", padx=18, pady=(6, 3))
        self._label(row, "OCR 引擎").pack(side="left")
        pick = tk.OptionMenu(row, engine, *[k for k, _ in ENGINES])
        pick.configure(bg=self.pal["hi"], fg=self.pal["text"], relief="flat",
                       highlightthickness=0, font=(self.pal["family"], 9),
                       activebackground=self.pal["hi"], activeforeground=self.pal["gold"])
        pick["menu"].configure(bg=self.pal["hi"], fg=self.pal["text"],
                               font=(self.pal["family"], 9))
        pick.pack(side="right")

        # ---- 界面
        self._section(outer, "界面")
        font_size = tk.IntVar(value=int(self.ui.get("font_size", 10) or 10))
        self.vars["font_size"] = font_size
        row = tk.Frame(outer, bg=bg)
        row.pack(fill="x", padx=18, pady=3)
        self._label(row, "悬浮窗字体大小").pack(side="left")
        spin = tk.Spinbox(row, from_=8, to=16, textvariable=font_size, width=5,
                          bg=self.pal["hi"], fg=self.pal["text"], relief="flat",
                          buttonbackground=self.pal["hi"], insertbackground=self.pal["text"],
                          font=(self.pal["family"], 9))
        spin.pack(side="right")
        self._label(outer, "改完立刻生效，不用重启。10 是默认，11~12 适合高分屏",
                    size=8, color=self.pal["faint"]).pack(fill="x", padx=18)

        # ---- 每日总结
        self._section(outer, "每日总结")
        hour = tk.IntVar(value=int(self.ui.get("summary_hour", 18) or 18))
        self.vars["summary_hour"] = hour
        row = tk.Frame(outer, bg=bg)
        row.pack(fill="x", padx=18, pady=3)
        self._label(row, "自动生成时间（点）").pack(side="left")
        tk.Spinbox(row, from_=0, to=23, textvariable=hour, width=5,
                   bg=self.pal["hi"], fg=self.pal["text"], relief="flat",
                   buttonbackground=self.pal["hi"], insertbackground=self.pal["text"],
                   font=(self.pal["family"], 9)).pack(side="right")
        self._label(outer, "到点后自动生成一份手账风格的 HTML，存在 summaries 目录里",
                    size=8, color=self.pal["faint"]).pack(fill="x", padx=18)

        # ---- 底部按钮
        bar = tk.Frame(outer, bg=bg)
        bar.pack(fill="x", padx=18, pady=16, side="bottom")
        self.status = tk.Label(bar, text="", bg=bg, fg=self.pal["muted"],
                               font=(self.pal["family"], 9), anchor="w")
        self.status.pack(side="left", fill="x", expand=True)

        def button(text, command, accent=False):
            return tk.Button(bar, text=text, command=command, relief="flat",
                             bg=self.pal["gold"] if accent else self.pal["hi"],
                             fg="#14171f" if accent else self.pal["text"],
                             activebackground=self.pal["gold"], activeforeground="#14171f",
                             font=(self.pal["family"], 9), padx=14, pady=4,
                             cursor="hand2", borderwidth=0)
        button("保存", self.save, accent=True).pack(side="right", padx=(8, 0))
        button("关闭", self.close).pack(side="right")

    # ---------------------------------------------------------------- 动作
    def _collect(self):
        llm = dict(self.llm)
        for key in ("base_url", "api_key", "model"):
            value = str(self.vars[key].get()).strip()
            if value:
                llm[key] = value
        try:
            llm["interval_seconds"] = max(15, min(3600, int(
                float(str(self.vars["interval_seconds"].get()).strip() or 60))))
        except ValueError:
            llm["interval_seconds"] = 60
        llm["content_capture"] = bool(self.vars["content_capture"].get())
        llm["doc_read"] = bool(self.vars["doc_read"].get())
        llm["content_level"] = str(self.vars["content_level"].get())
        llm["ocr_engine"] = str(self.vars["ocr_engine"].get())

        ui = dict(self.ui)
        try:
            ui["font_size"] = max(8, min(16, int(self.vars["font_size"].get())))
        except (ValueError, tk.TclError):
            ui["font_size"] = 10
        try:
            ui["summary_hour"] = max(0, min(23, int(self.vars["summary_hour"].get())))
        except (ValueError, tk.TclError):
            ui["summary_hour"] = 18
        return llm, ui

    def save(self):
        llm, ui = self._collect()
        try:
            _write(LLM, llm)
            _write(UI, ui)
        except OSError as exc:
            self.status.configure(text="保存失败：%s" % exc, fg=self.pal["danger"])
            return
        self.llm, self.ui = llm, ui
        self.status.configure(text="已保存", fg=self.pal["green"])
        if self.on_saved:
            try:
                self.on_saved(llm, ui)
            except Exception:
                pass

    def close(self):
        try:
            self.top.destroy()
        except tk.TclError:
            pass

    def focus(self):
        try:
            self.top.deiconify()
            self.top.lift()
            self.top.focus_force()
        except tk.TclError:
            pass


def palette_from(skin):
    """把皮肤字典翻成设置窗口要用的色板（键名跟皮肤不一样，别混用）。"""
    return {
        "bg": skin["bg"], "hi": skin["hi"], "text": skin["text"],
        "muted": skin["muted"], "faint": skin["muted"],
        "gold": skin["gold"], "green": skin["green"], "danger": "#ff8080",
        "stroke": skin["hi"], "family": skin["family"],
    }


def default_font(family, size, bold=False):
    return tkfont.Font(family=family, size=size, weight="bold" if bold else "normal")

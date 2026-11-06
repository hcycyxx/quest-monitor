# -*- coding: utf-8 -*-
"""窗口看门：记录前台窗口标题 + 进程名 + 窗口内具体内容到 win_log.jsonl

两级采集：
- 标题层（零成本，2 秒一次）：前台窗口变化立刻记一条；同一窗口每 HEARTBEAT 秒补心跳，
  这样引擎能算出"停留了多久"，否则一直不动就没有采样点，末段停留时长永远是 0。
- 内容层（0.3~1 秒 CPU，按需）：窗口切换时、以及同一窗口每 CONTENT_EVERY 秒，
  抓一次"这个窗口里具体在干什么"（UIA 控件/文档正文，必要时退回系统 OCR）。
  放在后台线程做，不阻塞 2 秒的标题采样；忙不过来就丢帧，绝不排队堆积。

内容只在内存里处理，写进日志的是纯文字，截图不落盘。
"""
import ctypes
import json
import os
import queue
import threading
import time
from ctypes import wintypes

try:
    from . import content_probe
except ImportError:                     # 直接当脚本跑时没有包上下文
    import content_probe

import paths
from inference_control import IdleState
import state_store

ROOT = paths.PROGRAM_DIR
LOG = paths.config("win_log.jsonl")
CFG = paths.config("llm.json")
MAX_BYTES = 4 * 1024 * 1024  # 4MB 轮转（带内容后单条变长，上限跟着放大）
KEEP_LINES = 2000
HEARTBEAT = 60.0             # 同窗口每 60 秒补一条标题心跳
CONTENT_EVERY = 45.0         # 同窗口每 45 秒重抓一次内容
TICK = 2.0                   # 标题轮询间隔
AWAY = 180.0                 # 人离开超过这个秒数就不再补心跳/内容
CONTENT_IDLE_LIMIT = 90.0    # 人已经闲置这么久就别抓内容了，抓了也是静态画面


def content_enabled():
    """config/llm.json 里 content_capture 为 false 就只记标题，不抓窗口内容。
    文件不存在/读坏了按开启处理 —— 内容层是主功能，静默关掉更难查。"""
    try:
        with open(CFG, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        return True
    return bool(cfg.get("content_capture", True))


def content_cfg():
    """读内容层两个开关：ocr_engine（auto/rapid/windows）、doc_read（读不读文件）。
    读不到就用默认值，绝不因为配置写错就停掉内容层。"""
    out = {"ocr_engine": "auto", "doc_read": True}
    try:
        with open(CFG, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        return out
    eng = str(cfg.get("ocr_engine", "auto")).lower()
    if eng in ("auto", "rapid", "windows", "off"):
        out["ocr_engine"] = eng
    out["doc_read"] = bool(cfg.get("doc_read", True))
    return out

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


# GetTickCount64 返回 64 位，必须声明返回类型，否则 ctypes 默认按 int(32 位) 截断
kernel32.GetTickCount64.restype = ctypes.c_ulonglong
psapi.GetModuleFileNameExW.argtypes = [
    wintypes.HANDLE, wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
psapi.GetModuleFileNameExW.restype = wintypes.DWORD

_log_lock = threading.Lock()


def active_window():
    h = user32.GetForegroundWindow()
    if not h:
        return None
    n = user32.GetWindowTextLengthW(h)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(h, buf, n + 1)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    name = ""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kh = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if kh:
        try:
            buf2 = ctypes.create_unicode_buffer(260)
            got = psapi.GetModuleFileNameExW(kh, None, buf2, 260)
            if got:
                name = os.path.basename(buf2.value)
        except OSError:
            pass
        finally:
            kernel32.CloseHandle(kh)
    return {"hwnd": h, "title": buf.value, "exe": name, "pid": pid.value}


SELF_PREFIXES = ("SideQuest", "任务追踪")


def is_self(w):
    """面板自己也是 python.exe 的 Tk 窗口，点它一下就会被记成"当前活动"，
    导致 AI 把面板标题（"SideQuest"）当成用户在做的事。这类记录直接跳过。
    旧标题也留着，避免改名前的历史窗口漏进来。"""
    if (w.get("exe") or "").lower() not in ("python.exe", "pythonw.exe"):
        return False
    t = w.get("title") or ""
    return any(t.startswith(p) for p in SELF_PREFIXES)


def idle_seconds():
    """距最后一次键鼠输入的秒数。

    GetLastInputInfo 的 dwTime 是 32 位 tick，49.7 天回绕一次，
    所以两端都取低 32 位再相减，差值也要 & 0xFFFFFFFF。
    """
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    now = kernel32.GetTickCount64() & 0xFFFFFFFF
    ms = (now - lii.dwTime) & 0xFFFFFFFF
    if ms > 0x7FFFFFFF:          # 回绕产生的天文数字，判为 0
        return 0.0
    return ms / 1000.0


def trim_log():
    """超限时保留最后 KEEP_LINES 行，用临时文件 + 原子替换，避免并发读到半截文件。"""
    try:
        if os.path.getsize(LOG) <= MAX_BYTES:
            return
        with open(LOG, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-KEEP_LINES:]
        tmp = LOG + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(lines)
        os.replace(tmp, LOG)
    except OSError:
        pass


def append_rec(rec):
    with _log_lock:
        try:
            paths.ensure_parent(LOG)
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            return
        trim_log()


# ---------------------------------------------------------------- 内容层线程

_probe_q = queue.Queue(maxsize=1)
_last_content = {"key": None, "text": None}


def _probe_worker():
    while True:
        item = _probe_q.get()
        if item is None:
            return
        hwnd, base = item
        try:
            got = content_probe.probe(hwnd, exe=base.get("exe", ""),
                                      title=base.get("title", ""))
        except Exception:
            continue
        text = (got or {}).get("text") or ""
        if not text:
            continue
        # 同一窗口同一段文字不重复写，省磁盘也省引擎的 token
        key = (base["title"], base["exe"])
        if _last_content["key"] == key and _last_content["text"] == text:
            continue
        _last_content["key"] = key
        _last_content["text"] = text
        rec = dict(base)
        rec["content"] = text
        rec["src"] = got.get("src", "")
        rec["evidence"] = got.get("evidence") or {}
        append_rec(rec)


def request_content(w, now_mono):
    """把一次内容抓取丢给后台线程。队列满就放弃这一帧 —— 内容层是增强，
    宁可缺一条也不能让标题采样卡住。"""
    if _probe_q.full():
        return now_mono
    try:
        _probe_q.put_nowait((w["hwnd"], {
            "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "title": w["title"], "exe": w["exe"], "pid": w["pid"],
            "idle_s": round(idle_seconds(), 1),
        }))
    except queue.Full:
        return now_mono
    return now_mono


def write_rec(w, now_mono):
    append_rec({"t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "title": w["title"], "exe": w["exe"], "pid": w["pid"],
                "idle_s": round(idle_seconds(), 1)})
    return now_mono


def main():
    capture = content_enabled()
    ccfg = content_cfg()
    if capture:
        content_probe.set_ocr_engine(ccfg["ocr_engine"])
        content_probe.set_doc_read(ccfg["doc_read"])
        threading.Thread(target=_probe_worker, daemon=True).start()
    last = None
    last_write = 0.0
    last_content_at = 0.0
    was_idle = False
    idle_monitor=IdleState()
    status_at=0.;sample_at=0.;last_status=None
    while True:
        try:
            w = active_window()
            clock=time.monotonic();idle_now=idle_seconds();sample=None
            if capture and w and not is_self(w) and idle_now>=120 and clock-sample_at>=15:
                sample_at=clock
                try:
                    image=content_probe._grab(w["hwnd"],crop_top=120)
                    if image is not None:sample=image.convert("L").resize((48,27)).tobytes()
                except Exception:
                    pass
            status=idle_monitor.observe(idle_now,(w.get("hwnd"),w.get("title")) if w else None,sample,clock)
            resumed=last_status is True and not status["suspended"]
            if clock-status_at>=10 or status["suspended"]!=last_status:
                state_store._atomic_write(paths.config("activity_status.json"),{"checked_at":time.time(),**status})
                status_at=clock;last_status=status["suspended"]
            if w and not is_self(w):
                if resumed:
                    last_write=write_rec(w,clock)
                    if capture:last_content_at=request_content(w,clock)
                key = (w["title"], w["exe"])
                now = time.monotonic()
                idle = idle_seconds()
                changed = key != last
                # 人离开 180 秒以上不再补心跳，避免"打开文档去吃饭"被算成专注 3 小时。
                away = idle >= AWAY
                # 人回到电脑前立刻补一条，否则要等下一个心跳，回来后这段会漏记。
                back = was_idle and idle < 10
                was_idle = away
                stale = (now - last_write) >= HEARTBEAT and not away
                if changed or stale or back:
                    last = key
                    last_write = write_rec(w, now)
                    # 换窗口就抓一次内容；同一窗口按 CONTENT_EVERY 重抓，
                    # 这样"在同一个 Excel 里从填价格切到核包装"也能被看见。
                    if capture and idle < CONTENT_IDLE_LIMIT:
                        last_content_at = request_content(w, now)
                        _last_content["key"] = None      # 新窗口，允许重写同文本
                elif (capture and idle < CONTENT_IDLE_LIMIT
                      and (now - last_content_at) >= CONTENT_EVERY):
                    last_content_at = request_content(w, now)
        except Exception:
            pass
        time.sleep(TICK)


if __name__ == "__main__":
    main()

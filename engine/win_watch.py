# -*- coding: utf-8 -*-
"""窗口标题看门：记录前台窗口标题 + 进程名到 win_log.jsonl
零 AI 成本，供任务面板引擎读取活动线索。

采集策略：
- 前台窗口变化 → 立刻写一条。
- 同一窗口持续停留 → 每 HEARTBEAT 秒补一条心跳，这样引擎能算出"停留了多久"，
  否则一直不动就没有任何采样点，末段停留时长永远是 0。
"""
import json
import time
import os
import ctypes
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "config", "win_log.jsonl")
MAX_BYTES = 2 * 1024 * 1024  # 2MB 轮转
KEEP_LINES = 2000
HEARTBEAT = 60.0             # 同窗口每 60 秒补一条心跳
TICK = 2.0                   # 轮询间隔

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
    return {"title": buf.value, "exe": name, "pid": pid.value}


SELF_PREFIXES = ("任务追踪",)


def is_self(w):
    """面板自己也是 python.exe 的 Tk 窗口，点它一下就会被记成"当前活动"，
    导致 AI 把面板标题（"任务追踪 · Codex V6"）当成用户在做的事。这类记录直接跳过。"""
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


def write_rec(w, now_mono):
    rec = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "title": w["title"], "exe": w["exe"], "pid": w["pid"],
           "idle_s": round(idle_seconds(), 1)}
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return now_mono


def main():
    last = None
    last_write = 0.0
    was_idle = False
    while True:
        try:
            w = active_window()
            if w and not is_self(w):
                key = (w["title"], w["exe"])
                now = time.monotonic()
                idle = idle_seconds()
                changed = key != last
                # 人离开 180 秒以上不再补心跳，避免"打开文档去吃饭"被算成专注 3 小时。
                away = idle >= 180
                # 人回到电脑前立刻补一条，否则要等下一个心跳，回来后这段会漏记。
                back = was_idle and idle < 10
                was_idle = away
                stale = (now - last_write) >= HEARTBEAT and not away
                if changed or stale or back:
                    last = key
                    last_write = write_rec(w, now)
                    trim_log()
        except Exception:
            pass
        time.sleep(TICK)


if __name__ == "__main__":
    main()

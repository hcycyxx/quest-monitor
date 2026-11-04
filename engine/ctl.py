# -*- coding: utf-8 -*-
"""服务启停控制：暂停 = 停掉采样看门与 LLM 引擎；继续 = 重新拉起。

面板进程自己不在停的范围里——它得留着，否则没有按钮可以按"继续"。
暂停状态写在 config/paused，重启后再打开面板也能记住。
"""
import ctypes
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAUSE_FLAG = os.path.join(ROOT, "config", "paused")
PIDFILE = os.path.join(ROOT, "config", "workers.json")

WORKERS = {
    "win_watch": os.path.join(ROOT, "engine", "win_watch.py"),
    "llm_engine": os.path.join(ROOT, "engine", "llm_engine.py"),
}
PANEL = os.path.join(ROOT, "ui", "quest_window.py")

CREATE_NO_WINDOW = 0x08000000
STILL_ACTIVE = 259

kernel32 = ctypes.windll.kernel32
kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


# ---------- 暂停标记 ----------

def is_paused():
    return os.path.exists(PAUSE_FLAG)


def set_paused(value):
    try:
        if value:
            with open(PAUSE_FLAG, "w", encoding="utf-8") as f:
                f.write(str(int(time.time())))
        elif os.path.exists(PAUSE_FLAG):
            os.remove(PAUSE_FLAG)
    except OSError:
        pass


# ---------- 进程工具 ----------

def _pid_alive(pid):
    if not pid:
        return False
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(h, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(h)


def _kill(pid):
    if not pid:
        return False
    h = kernel32.OpenProcess(PROCESS_TERMINATE, False, int(pid))
    if not h:
        return False
    try:
        return bool(kernel32.TerminateProcess(h, 1))
    finally:
        kernel32.CloseHandle(h)


def _load_pids():
    try:
        with open(PIDFILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_pids(pids):
    try:
        with open(PIDFILE, "w", encoding="utf-8") as f:
            json.dump(pids, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _norm(text):
    """统一路径写法，便于做命令行里的目录归属判断。"""
    return (text or "").replace("/", "\\").lower()


def _discover(name):
    """按命令行找已经在跑、但不在 pid 记录里的同名脚本进程。

    必须同时匹配脚本名和本项目的根目录：同一台机器上可能有第二份
    quest-monitor（测试副本或另一个安装），只按脚本名匹配会误杀别人的进程。
    """
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=15,
            creationflags=CREATE_NO_WINDOW,
        )
        raw = (out.stdout or "").strip()
        if not raw:
            return []
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
        root_key = _norm(ROOT)
        hits = []
        for item in data:
            cmd = _norm(item.get("CommandLine") or "")
            if name not in cmd or root_key not in cmd:
                continue
            try:
                hits.append(int(item.get("ProcessId")))
            except (TypeError, ValueError):
                pass
        return hits
    except Exception:
        return []


def status():
    """返回 {name: pid or None}，顺带清理已经死掉的记录。"""
    pids = _load_pids()
    out = {}
    for name in WORKERS:
        pid = pids.get(name)
        if _pid_alive(pid):
            out[name] = int(pid)
            continue
        found = _discover(name)
        out[name] = found[0] if found else None
    _save_pids({k: v for k, v in out.items() if v})
    return out


def is_running():
    st = status()
    return any(st.get(n) for n in WORKERS)


# ---------- 启停 ----------

def stop_workers():
    """停掉采样与引擎。面板不动。"""
    pids = _load_pids()
    killed = []
    for name in WORKERS:
        pid = pids.get(name)
        if _pid_alive(pid) and _kill(pid):
            killed.append((name, pid))
        for stray in _discover(name):
            if stray not in [p for _, p in killed] and _kill(stray):
                killed.append((name, stray))
    _save_pids({})
    set_paused(True)
    return killed


def start_workers():
    """拉起采样与引擎，返回 {name: pid}。"""
    set_paused(False)
    pids = _load_pids()
    started = {}
    for name, script in WORKERS.items():
        if _pid_alive(pids.get(name)):
            started[name] = pids[name]
            continue
        try:
            p = subprocess.Popen(
                [sys.executable, script],
                cwd=ROOT,
                creationflags=CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            started[name] = p.pid
        except Exception:
            started[name] = None
    _save_pids({k: v for k, v in started.items() if v})
    return started


def toggle():
    """返回切换后的状态：True = 已暂停。"""
    if is_paused():
        start_workers()
        return False
    stop_workers()
    return True


def start_panel():
    """单独拉起面板（不碰暂停标记），用于面板自己崩溃/被关后恢复。"""
    if _discover("quest_window"):
        return None
    try:
        p = subprocess.Popen(
            [sys.executable, PANEL],
            cwd=ROOT,
            creationflags=CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return p.pid
    except Exception:
        return None


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    if action == "pause":
        print("killed", stop_workers())
    elif action == "resume":
        print("started", start_workers())
    elif action == "toggle":
        print("paused" if toggle() else "running")
    elif action == "panel":
        print("panel", start_panel())
    else:
        print("paused" if is_paused() else "running", status())

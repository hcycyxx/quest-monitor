# -*- coding: utf-8 -*-
"""路径解析：源码运行和打包成 exe 后，代码位置和数据位置不是同一个地方。

源码运行时 DATA_DIR 就是项目根目录，行为和以前完全一样。
打包后程序目录在 Program Files（只读），配置和日志必须落到用户目录，
否则写 quest_state.json 会被 UAC 拦掉。
"""
import os
import sys

APP_NAME = "SideQuest"


def _program_dir():
    """代码/资源所在目录。打包后是 exe 旁边，源码运行时是项目根。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _data_dir(program):
    if not getattr(sys, "frozen", False):
        return program
    override = os.environ.get("SIDEQUEST_HOME")
    if override:
        return override
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_NAME)


PROGRAM_DIR = _program_dir()
DATA_DIR = _data_dir(PROGRAM_DIR)
CONFIG_DIR = os.path.join(DATA_DIR, "config")
SUMMARY_DIR = os.path.join(DATA_DIR, "summaries")


def ensure_dirs():
    for path in (CONFIG_DIR, SUMMARY_DIR):
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            pass
    _seed()


# 首次运行时需要先有这两个文件，否则引擎会因为「没有 api_key」直接退出。
# 打包版把它们随包带进来，源码版直接从项目里复制。
# 用 llm.default.json 而不是 llm.example.json：example 里 api_key 是
# YOUR_API_KEY 占位，引擎会判成「没填」然后退出，装机版就永远不动了。
SEEDS = (("llm.default.json", "llm.json"),
         ("quest_state.example.json", "quest_state.json"))


def _seed():
    if not getattr(sys, "frozen", False):
        return
    import shutil
    for src_name, dst_name in SEEDS:
        dst = config(dst_name)
        if os.path.exists(dst):
            continue
        src = bundled(os.path.join("config", src_name))
        if not os.path.exists(src):
            continue
        try:
            shutil.copyfile(src, dst)
        except OSError:
            pass


def config(name):
    return os.path.join(CONFIG_DIR, name)


def bundled(name):
    """只读资源（图标之类）。打包后在 sys._MEIPASS 里。"""
    base = getattr(sys, "_MEIPASS", None) or PROGRAM_DIR
    return os.path.join(base, name)


def runtime_log(name):
    """运行日志。源码时留在 engine/ 下（README 里就是这个路径），
    打包后写进数据目录，程序目录在 Program Files 里是只读的。"""
    if getattr(sys, "frozen", False):
        return os.path.join(DATA_DIR, "logs", name)
    return os.path.join(PROGRAM_DIR, "engine", name)


def ensure_parent(path):
    parent = os.path.dirname(path)
    if parent:
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError:
            pass
    return path


def is_frozen():
    return bool(getattr(sys, "frozen", False))

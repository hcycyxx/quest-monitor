# -*- coding: utf-8 -*-
"""SideQuest 启动入口。源码运行和打包成 exe 都走这里。

用法：
    python sidequest.py              启动面板（引擎没跑就一起拉起）
    python sidequest.py --panel      只启动面板
    python sidequest.py --worker win_watch
    python sidequest.py --worker llm_engine
    python sidequest.py --summary    生成今天的总结并打印路径
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for sub in ("engine", "ui"):
    path = os.path.join(HERE, sub)
    if os.path.isdir(path) and path not in sys.path:
        sys.path.insert(0, path)

# 显式 import：PyInstaller 靠静态分析找依赖，动态 sys.path 拼接它看不见。
# state_store / summary_html 由 daily_summary 与面板间接使用，这里点名是为了
# 让打包工具把它们收进去（frozen 之后没有源码目录可以再扫）。
import paths                      # noqa: E402
import state_store                # noqa: E402,F401
import summary_html               # noqa: E402,F401
import daily_summary              # noqa: E402,F401
import ctl                        # noqa: E402,F401


def _run_panel():
    import quest_window
    quest_window.QuestHUD().mainloop()


def _run_worker(name):
    if name == "win_watch":
        import win_watch
        win_watch.main()
    elif name == "llm_engine":
        import llm_engine
        llm_engine.main_loop()
    else:
        raise SystemExit("unknown worker: %s" % name)


def main(argv):
    paths.ensure_dirs()
    args = argv[1:]
    if args[:1] == ["--worker"]:
        _run_worker(args[1] if len(args) > 1 else "")
        return 0
    if args[:1] == ["--panel"]:
        _run_panel()
        return 0
    if args[:1] == ["--summary"]:
        print(daily_summary.build())
        return 0
    # 默认：面板起得来就起，引擎跟着。已经有一份在跑就只把面板叫出来。
    if not ctl.is_paused():
        ctl.start_workers()
    ctl.start_panel()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

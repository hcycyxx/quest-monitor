# -*- coding: utf-8 -*-
# PyInstaller 打包描述：pyinstaller build.spec
#
# 用单目录（onedir）而不是单文件（onefile）。原因：
# RapidOCR 带着 onnxruntime 的 dll 和模型，整个包 140MB 以上；onefile 每次启动
# 都要把这 140MB 解压到临时目录，冷启动十几秒，机器上临时目录被清过还会直接
# 报 "Could not create temporary directory"。单目录只解压一次（安装时复制），
# 之后启动就是直接映射文件，快得多也稳得多。安装器负责把整个目录装进去。
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.getcwd())
HIDDEN = [
    "pystray._win32",
    "PIL._tkinter_finder",
    "comtypes.gen",
    "comtypes.gen.UIAutomationClient",
    "winsdk.windows.globalization",
    "winsdk.windows.graphics.imaging",
    "winsdk.windows.media.ocr",
    "winsdk.windows.storage.streams",
    "rapidocr",
    "onnxruntime",
    "xlrd",
    # 自有模块：入口按 sys.path 动态找，静态分析看不见，必须点名
    "state_store",
    "summary_html",
    "daily_summary",
    "paths",
    "ctl",
    "win_watch",
    "llm_engine",
    "content_probe",
    "doc_reader",
    "quest_window",
    "settings_window",
    "tray",
]
HIDDEN += collect_submodules("rapidocr")
HIDDEN += collect_submodules("onnxruntime")

datas = [("assets/sidequest.ico", "assets")]
# 首次运行要播种的配置：没有 llm.json 引擎会直接退出，没有 quest_state.json
# 面板会是空白的。这两个文件不装到程序目录，而是在用户数据目录里生成。
for name in ("config/llm.default.json", "config/quest_state.example.json"):
    datas.append((name, "config"))
for pkg in ("rapidocr", "onnxruntime"):
    try:
        datas += collect_data_files(pkg)
    except Exception:
        pass

a = Analysis(
    ["sidequest.py"],
    pathex=[ROOT, os.path.join(ROOT, "engine"), os.path.join(ROOT, "ui")],
    binaries=[],
    datas=datas,
    hiddenimports=HIDDEN,
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "scipy", "pandas", "PyQt5", "PySide2", "notebook", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SideQuest",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=os.path.join(ROOT, "assets", "sidequest.ico"),
    version=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SideQuest",
)

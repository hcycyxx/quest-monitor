# -*- coding: utf-8 -*-
"""托盘图标：右键菜单是设置、总结和历史总结的入口。

pystray 自己跑一个线程、有自己的消息循环，而 tkinter 只能在主线程碰。
所以菜单回调一律往队列里塞一个动作名，由面板用 after() 在主线程取出来执行。
"""
import os
import queue
import threading

try:
    import pystray
    from PIL import Image, ImageDraw
except Exception:                       # 没装 pystray 也不该让面板起不来
    pystray = None
    Image = ImageDraw = None

import paths

ICON_SIZE = 64


def _draw_icon(accent="#ffd166", bg="#14171f"):
    """画一个任务面板形状的图标：圆角方块 + 三条任务线 + 一个金色进度点。"""
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((6, 6, ICON_SIZE - 6, ICON_SIZE - 6), radius=14, fill=bg)
    for i, y in enumerate((22, 33, 44)):
        width = (30, 22, 26)[i]
        d.rounded_rectangle((17, y, 17 + width, y + 4), radius=2,
                            fill="#a8b7cc" if i else accent)
    d.ellipse((44, 42, 52, 50), fill=accent)
    return img


def _icon_path():
    """打包时图标文件跟着走；源码运行时从 assets 里取，没有就现画。"""
    for name in ("sidequest.ico", "assets/sidequest.ico"):
        path = paths.bundled(name)
        if os.path.exists(path):
            return path
    return None


class Tray:
    """持有 pystray 图标。面板通过 poll() 拿用户点了什么。"""

    def __init__(self, actions):
        self.actions = queue.Queue()
        self.icon = None
        self.thread = None
        self._actions = actions          # 名字 -> 中文标签的映射，用来生成菜单
        self._history = []

    # ---------------------------------------------------------------- 菜单
    def _menu(self):
        items = []
        items.append(pystray.MenuItem("打开今日总结", lambda: self._emit("summary"),
                                      default=True))
        hist = []
        for item in self._history[:12]:
            label = "%s%s" % (item["date"], "" if item.get("size") else "（空）")
            hist.append(pystray.MenuItem(
                label, (lambda d=item["date"]: self._emit("summary:" + d))))
        if hist:
            items.append(pystray.MenuItem("历史总结", pystray.Menu(*hist)))
        else:
            items.append(pystray.MenuItem("历史总结（暂无）", None, enabled=False))
        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("显示 / 隐藏面板", lambda: self._emit("panel")))
        items.append(pystray.MenuItem("立即生成总结", lambda: self._emit("generate")))
        items.append(pystray.MenuItem("详细设置…", lambda: self._emit("settings")))
        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("退出 SideQuest", lambda: self._emit("quit")))
        return pystray.Menu(*items)

    def _emit(self, action):
        self.actions.put(action)

    def set_history(self, history):
        """历史列表变了要重建菜单，否则新生成的总结不在右键里。"""
        self._history = list(history)
        if self.icon is not None:
            try:
                self.icon.update_menu()
            except Exception:
                pass

    # ---------------------------------------------------------------- 生命周期
    def start(self):
        if pystray is None:
            return False
        try:
            image = _draw_icon()
            path = _icon_path()
            if path:
                try:
                    image = Image.open(path)
                except Exception:
                    pass
            self.icon = pystray.Icon("sidequest", image, "SideQuest",
                                     menu=self._menu())
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
            return True
        except Exception:
            self.icon = None
            return False

    def _run(self):
        try:
            self.icon.run()
        except Exception:
            pass

    def stop(self):
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None

    def poll(self):
        """取一个待执行动作；没有就返回 None。"""
        try:
            return self.actions.get_nowait()
        except queue.Empty:
            return None

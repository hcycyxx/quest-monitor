# -*- coding: utf-8 -*-
"""内容层：窗口标题之外，再抓一层"这个窗口里具体在干什么"。

三条来源，都不联网、不花 token：
1. 读文件：窗口标题里的文档名 → 找到磁盘上的 .xlsx/.docx → 直接解析。
   一个字都不会错，2 毫秒。办公文档优先走这条。
2. UIA（UI Automation）：直接问程序要控件名/值/文档正文。快（100~400ms），
   质量取决于程序配不配合 —— 浏览器、Electron 应用、资源管理器好用；
   WPS / Office 基本什么都不给。
3. Windows 自带 OCR：截图后调系统 OCR 引擎认字。什么程序都能用，代价约 0.3~0.7 秒
   CPU，但表格里的字会认错（「绩效」→「缋效」）。只在前两条都不行时才用。

产出的**文字**才写进 win_log.jsonl，截图在内存里用完即丢，不落盘、不上传。
依赖全部可选：缺 comtypes / winsdk / Pillow 时各自降级，绝不会让看门进程挂掉。
"""
import ctypes
import ctypes.wintypes as wt
import io
import os
import re
import tempfile
import time

import doc_reader

user32 = ctypes.windll.user32

_loop = None                # 旧字段，OCR 已改到独立线程，保留避免误删引用
_uia = None
_uia_failed = False

OCR_MAX_W = 1400            # OCR 前把窗口缩到这个宽度，再大既慢又没帮助
TEXT_CAP = 700              # 单条内容记录的字符上限
UIA_ITEM_CAP = 30           # UIA 最多取多少个控件
UIA_ITEM_LEN = 70           # 单个控件文本上限
UIA_MIN_GOOD = 250          # UIA 拿到这么多字就认为够用，不必再 OCR

# 这些程序对 UIA 基本不设防也不配合：能问出来的只有"文档内按F1"这类固定文案，
# 真正的内容（表格单元格、正文）全在自绘画布里，只能靠 OCR。
OCR_ONLY_EXES = {
    "et.exe", "wps.exe", "wpp.exe", "wpsoffice.exe",
    "excel.exe", "winword.exe", "powerpnt.exe", "onenote.exe",
    "acrobat.exe", "acrord32.exe", "foxitreader.exe", "sumatrapdf.exe",
}

# 这些程序顶部有 120~190px 的 ribbon 功能区，全是一模一样的固定按钮名。
# 切掉它，OCR 出来就只剩表格/正文，省下的长度能装更多真正的内容。
OCR_CROP_TOP = {
    "et.exe": 190, "wps.exe": 150, "wpp.exe": 170, "wpsoffice.exe": 160,
    "excel.exe": 150, "winword.exe": 150, "powerpnt.exe": 150,
}

CTRL = {
    50002: "CheckBox", 50003: "ComboBox", 50004: "Edit", 50005: "Hyperlink",
    50007: "ListItem", 50008: "List", 50011: "MenuItem", 50013: "RadioButton",
    50015: "Slider", 50017: "StatusBar", 50018: "Tab", 50019: "TabItem",
    50020: "Text", 50021: "ToolBar", 50023: "Tree", 50024: "TreeItem",
    50028: "DataGrid", 50029: "DataItem", 50030: "Document", 50032: "Window",
    50033: "Pane", 50034: "Header", 50035: "HeaderItem", 50036: "Table",
    50037: "TitleBar",
}
# 只有这些控件承载"内容"。按钮名、菜单名、工具栏名是噪声，全是程序固定文案，
# 对判断"在干什么"没有信息量，还白占长度。
KEEP_TYPES = {50004, 50005, 50007, 50019, 50020, 50024, 50029, 50030, 50034, 50035, 50036}


# ---------------------------------------------------------------- UIA

def _get_uia():
    global _uia, _uia_failed
    if _uia is not None or _uia_failed:
        return _uia
    try:
        import comtypes.client
        comtypes.client.GetModule("UIAutomationCore.dll")
        import comtypes.gen.UIAutomationClient as UIA
        obj = comtypes.client.CreateObject(UIA.CUIAutomation, interface=UIA.IUIAutomation)
        obj._UIA = UIA
        _uia = obj
    except Exception:
        _uia_failed = True
        _uia = None
    return _uia


def _safe(fn, default=""):
    try:
        return fn()
    except Exception:
        return default


def uia_text(hwnd):
    """返回 (text, item_count)。拿不到就 ("", 0)。

    优先取 Document 正文 —— 浏览器、Electron 应用、记事本类能给整段可见文字，
    比一堆控件名有用得多。没有 Document 才退回收集控件文本。
    """
    uia = _get_uia()
    if uia is None:
        return "", 0
    UIA = uia._UIA
    try:
        root = uia.ElementFromHandle(hwnd)
    except Exception:
        return "", 0

    parts = []

    # 焦点控件最能说明"正在操作哪一格"，单独标出来放最前面
    foc = _safe(lambda: uia.GetFocusedElement())
    if foc is not None:
        try:
            ct = int(_safe(lambda: foc.CurrentControlType, 0))
            val = _safe(lambda: foc.GetCurrentPattern(UIA.UIA_ValuePatternId)
                        .QueryInterface(UIA.IUIAutomationValuePattern).CurrentValue)
            nm = _safe(lambda: foc.CurrentName) or ""
            piece = " ".join((val or nm or "").split())
            if piece:
                parts.append(f"[焦点:{CTRL.get(ct, '?')}] {piece[:120]}")
        except Exception:
            pass

    try:
        found = root.FindAll(UIA.TreeScope_Descendants, uia.CreateTrueCondition())
        total = found.Length
    except Exception:
        return " · ".join(parts), len(parts)

    # Document 正文优先
    body = ""
    for i in range(min(total, 80)):
        try:
            el = found.GetElement(i)
            if int(_safe(lambda: el.CurrentControlType, 0)) != 50030:
                continue
            body = _safe(lambda: el.GetCurrentPattern(UIA.UIA_TextPatternId)
                         .QueryInterface(UIA.IUIAutomationTextPattern)
                         .DocumentRange.GetText(1000)) or ""
        except Exception:
            continue
        if body.strip():
            break

    if body.strip():
        parts.append(" ".join(body.split()))
        return " · ".join(parts)[:TEXT_CAP], len(parts)

    kept = 0
    for i in range(min(total, 400)):
        if kept >= UIA_ITEM_CAP:
            break
        try:
            el = found.GetElement(i)
            ct = int(_safe(lambda: el.CurrentControlType, 0))
        except Exception:
            continue
        if ct not in KEEP_TYPES:
            continue
        n = _safe(lambda: el.CurrentName) or ""
        if not n:
            continue
        n = " ".join(n.split())[:UIA_ITEM_LEN]
        if n not in parts:              # 表格里同一格名会重复几百次
            parts.append(n)
            kept += 1

    return " · ".join(parts)[:TEXT_CAP], len(parts)


# ---------------------------------------------------------------- 截图 + OCR

def _grab(hwnd, crop_top=0):
    """只抓前台窗口，所以它一定没被盖住，屏幕截图就是它自己的内容。
    不用 PrintWindow：那个 API 在某些程序上会卡住不返回，看门进程不能冒这个险。

    crop_top 用来切掉窗口顶部的功能区/工具栏：办公套件的 ribbon 上一堆
    "插入 页面布局 公式" 这类固定按钮名，OCR 出来全是噪声，白占长度。
    """
    from PIL import ImageGrab
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    if r.right - r.left <= 0 or r.bottom - r.top <= 0:
        return None
    top = r.top + max(0, int(crop_top))
    if r.bottom - top < 60:            # 切太多就退回整窗
        top = r.top
    return ImageGrab.grab(bbox=(r.left, top, r.right, r.bottom), all_screens=True)


def _ocr_windows(img):
    try:
        import asyncio
        from winsdk.windows.globalization import Language
        from winsdk.windows.graphics.imaging import BitmapDecoder
        from winsdk.windows.media.ocr import OcrEngine
        from winsdk.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
    except Exception:
        return ""

    if img.width > OCR_MAX_W:
        img = img.resize((OCR_MAX_W, int(img.height * OCR_MAX_W / img.width)))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    data = buf.getvalue()

    async def run():
        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream.get_output_stream_at(0))
        writer.write_bytes(data)
        await writer.store_async()
        await writer.flush_async()
        stream.seek(0)
        dec = await BitmapDecoder.create_async(stream)
        bmp = await dec.get_software_bitmap_async()
        engine = (OcrEngine.try_create_from_language(Language("zh-Hans-CN"))
                  or OcrEngine.try_create_from_user_profile_languages())
        if engine is None:
            return ""
        res = await engine.recognize_async(bmp)
        return res.text or ""

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(run())
    finally:
        loop.close()


# ---- RapidOCR（可选）：准确率高得多，代价是慢 ----
# 同一张绩效表，系统 OCR 把「绩效」认成「缋效」、「报价」认成「报佾」，
# 九个常用词一个都没认对；RapidOCR 9/9 全对。但 3 秒 vs 0.35 秒。
# 只在装了 rapidocr 时启用 —— 内容抓取本来就在后台线程跑，45 秒一轮，3 秒不碍事。
_rapid = None
_rapid_failed = False


def _ocr_rapid(img):
    global _rapid, _rapid_failed
    if _rapid_failed:
        return ""
    if _rapid is None:
        try:
            from rapidocr import RapidOCR
        except ImportError:
            _rapid_failed = True
            return ""
        try:
            _rapid = RapidOCR()
        except Exception:
            _rapid_failed = True
            return ""
    if img.width > OCR_MAX_W:
        img = img.resize((OCR_MAX_W, int(img.height * OCR_MAX_W / img.width)))
    tmp = os.path.join(tempfile.gettempdir(), "sidequest_ocr.png")
    try:
        img.convert("RGB").save(tmp)
        res = _rapid(tmp)
    except Exception:
        return ""
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    texts = getattr(res, "txts", None)
    if texts is None:
        try:
            texts = res[1]
        except Exception:
            return ""
    return "\n".join(t for t in texts if t)


OCR_ENGINE = "auto"          # auto / rapid / windows / off，由 win_watch 按配置设置
DOC_READ = True              # 是否读磁盘上的办公文档


def set_ocr_engine(name):
    global OCR_ENGINE
    if name in ("auto", "rapid", "windows", "off"):
        OCR_ENGINE = name


def set_doc_read(flag):
    global DOC_READ
    DOC_READ = bool(flag)


def _ocr_direct(img):
    """按 OCR_ENGINE 选引擎。auto = 装了 RapidOCR 就用它，否则用系统 OCR。"""
    if OCR_ENGINE == "off":
        return ""
    if OCR_ENGINE == "windows":
        return _ocr_windows(img)
    if OCR_ENGINE == "rapid":
        return _ocr_rapid(img)
    text = _ocr_rapid(img) if _have("rapidocr") else ""
    return text or _ocr_windows(img)


# OCR 必须在自己线程里跑。comtypes 建 UIA 对象时把主线程的 COM 初始化成 STA，
# 而 winsdk 的 async 完成回调要回到那个 STA 线程 —— 主线程正卡在
# run_until_complete 里等它，两边互等，进程就死在那里（实测卡死过一次）。
_ocr_q = None
_ocr_lock = None
_ocr_thread = None
_ocr_dead = False


def _ocr_worker():
    while True:
        item = _ocr_q.get()
        if item is None:
            return
        img, box = item
        try:
            box["v"] = _ocr_direct(img)
        except Exception as exc:
            box["e"] = repr(exc)


def _ocr(img, timeout=25.0):
    """把图交给独立线程做 OCR，主线程最多等 timeout 秒。
    超时就判 OCR 不可用并永久关掉它 —— 看门进程不能被一个卡住的 API 拖死。

    timeout 给到 25 秒是因为 RapidOCR 在 1400px 宽的表格上要 3~5 秒，
    系统 OCR 只要 0.4 秒。抓内容本来就在后台线程、45 秒一轮，等得起；
    原来 8 秒的阈值会让 RapidOCR 在大图上反复被判超时，反而永久关掉了准确率高的那个。
    """
    global _ocr_q, _ocr_lock, _ocr_thread, _ocr_dead
    if _ocr_dead:
        return ""
    import queue as _queue
    import threading
    if _ocr_q is None:
        _ocr_q = _queue.Queue(maxsize=2)
        _ocr_lock = threading.Lock()
    if _ocr_thread is None or not _ocr_thread.is_alive():
        _ocr_thread = threading.Thread(target=_ocr_worker, daemon=True)
        _ocr_thread.start()
    box = {}
    try:
        _ocr_q.put_nowait((img, box))
    except _queue.Full:
        return ""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if box:
            break
        time.sleep(0.02)
    if not box:
        _ocr_dead = True
        return ""
    return box.get("v") or ""


CJK = "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3000-\u303f\uff00-\uffef"
_CJK_GAP = re.compile(rf"(?<=[{CJK}])[ \t]+(?=[{CJK}])")

# 办公软件界面上的固定文案，跟"在干什么"毫无关系，留着只会污染判断。
NOISE = (
    "文档内按F1", "官方协同办公软件提供商", "正在打开文档", "文档已损坏",
    "新建", "共享", "开始", "插入", "页面布局", "公式", "数据", "审阅", "视图",
    "帮助", "开发工具", "会员专享", "开通会员", "广告", "反馈",
)


def strip_noise(text):
    """逐段扔掉界面固定文案。切分符是 UIA 用的 ' · '，OCR 那边靠整段匹配。"""
    if not text:
        return ""
    keep = []
    for piece in text.split(" · "):
        p = piece.strip()
        if not p or len(p) <= 1:
            continue
        if any(n in p for n in NOISE) and len(p) < 60:
            continue
        keep.append(p)
    return " · ".join(keep)



def tidy(text):
    """系统 OCR 把每个汉字都用空格隔开，读起来像天书，也白占 token。
    只合并"两个汉字之间"的空格，拉丁词之间的空格要留着。"""
    if not text:
        return ""
    prev = None
    while prev != text:                 # 连续汉字要反复合并才能全去掉
        prev = text
        text = _CJK_GAP.sub("", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    # 头像/图标在 OCR 里会变成一串 \ufffc（对象替换符），几十个连着毫无意义
    text = re.sub(r"(?:\ufffc\s*){2,}", " ", text)
    text = text.replace("\ufffc", "")
    lines = [" ".join(ln.split()) for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln).strip()


def _have(mod):
    import importlib.util
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def ocr_text(hwnd, exe=""):
    # 用 RapidOCR 时不需要 winsdk；只有退回系统 OCR 才需要。
    # 原来无条件要求 winsdk，装了 RapidOCR 的机器反而被判成"没有 OCR"。
    need_win = _have("rapidocr") is False or OCR_ENGINE == "windows"
    if not _have("PIL") or (need_win and not _have("winsdk")):
        return ""
    crop = OCR_CROP_TOP.get((exe or "").lower(), 0)
    try:
        img = _grab(hwnd, crop_top=crop)
    except Exception:
        return ""
    if img is None:
        return ""
    return tidy(_ocr(img))


# ---------------------------------------------------------------- 对外

def probe(hwnd, want_ocr=True, exe="", title=""):
    """返回 {"src","text","ms"}。src 说明这段字是怎么来的，方便判断可靠性。

    优先级：读文件 > UIA > OCR。

    读文件排最前，因为 OCR 认表格必错字 —— 同一张绩效表，系统 OCR 把
    「绩效」认成「缋效」、「报价」认成「报佾」，九个常用词只对零个；
    RapidOCR 好些也只有八成。而 .xlsx/.docx 里存的就是原文，读出来一字不差，
    还只要 2 毫秒。只有读不到文件（PDF、网页、WPS 私有格式、图片）才退回 OCR。
    """
    t0 = time.time()
    text, src = "", "none"

    if DOC_READ:
        doc = doc_reader.read_for_title(title)
        if doc["text"]:
            text, src = doc["text"], "file"
        elif (exe or "").lower() == "explorer.exe":
            # 资源管理器：标题就是路径，直接列目录，比 OCR 认界面强得多
            # （OCR 只会读到"文件 主页 共享 查看 剪切 新建项目"这些按钮名）
            listing = doc_reader.explorer_listing(title)
            if listing["text"]:
                text, src = listing["text"], "file"

    if not text:
        text, _items = uia_text(hwnd)
        src = "uia"
        # 办公套件对 UIA 基本不配合，能问出来的只有"文档内按F1"这类固定文案，
        # 真内容全在自绘画布里 —— 这类程序直接走 OCR，别浪费时间问。
        forced = (exe or "").lower() in OCR_ONLY_EXES
        if want_ocr and OCR_ENGINE != "off" and (forced or len(text) < UIA_MIN_GOOD):
            alt = ocr_text(hwnd, exe=exe)
            if len(alt) > len(text) or forced:
                text, src = alt, ("ocr" if not text else "uia+ocr")

    text = strip_noise(tidy(text))[:TEXT_CAP]
    return {"src": src if text else "none",
            "text": text,
            "ms": int((time.time() - t0) * 1000)}


if __name__ == "__main__":
    import json
    import sys
    user32.SetProcessDPIAware()
    h = user32.GetForegroundWindow()
    n = user32.GetWindowTextLengthW(h)
    b = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(h, b, n + 1)
    r = probe(h, title=b.value)
    out = {"title": b.value, **r}
    with open(sys.argv[1] if len(sys.argv) > 1 else "probe_out.json",
              "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(out["src"], out["ms"], "ms", len(out["text"]), "chars")

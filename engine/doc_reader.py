# -*- coding: utf-8 -*-
"""文件层：办公文档直接读文件，不做 OCR。

OCR 认表格必错字 —— 同一个窗口，Windows 自带 OCR 把「绩效」认成「缋效」、
「报价」认成「报佾」，九个常用词只对零个；RapidOCR 好些但也只有八成。
而 .xlsx / .docx 本来就是 zip 包，里面存的是**原文**，读出来一个字都不会错，
而且只要 2 毫秒 —— 比 OCR 快一千多倍。

所以顺序是：能读文件就读文件，读不了（PDF、图片、网页、WPS 私有格式）才退回 OCR。

怎么从窗口标题找到文件：标题里一般就带着文件名（`2609绩效-Jack.xlsx - WPS 表格`）。
拿这个名字去三个地方找：
1. 最近使用记录（`%APPDATA%\\Microsoft\\Windows\\Recent\\*.lnk`）—— 用户刚打开过，命中率最高
2. 索引好的目录树（后台扫一次，缓存十分钟）
3. 都没有就放弃，交给 OCR

同一个文件名在多个目录存在时（"2609绩效"在 2609 和 2610 两个文件夹里都有），
取修改时间最新的那个 —— 正在编辑的一定是最近动过的。
"""
import glob
import os
import re
import threading
import time
import zipfile

# 这些扩展名能直接解析。WPS 私有的 .et / .wps / .dps 是 OLE 复合文档，
# 解析代价大且格式未公开，宁可退回 OCR。
PARSE_EXTS = {"xlsx", "xlsm", "docx", "pptx", "xls", "csv"}
OFFICE_EXES = {
    "et.exe", "wps.exe", "wpp.exe", "wpsoffice.exe",
    "excel.exe", "winword.exe", "powerpnt.exe", "onenote.exe",
}

# 窗口标题里找文件名。允许文件名中间有空格（`cherry 10月业务绩效.xlsx`），
# 但不许跨过 " - " —— 那是标题里"文档名 - 程序名"的分隔符。
_TITLE_DOC = re.compile(
    r"([^\s\\/:*?\"<>|][^\\/:*?\"<>|]*?\.(" + "|".join(sorted(PARSE_EXTS | {"et", "wps", "dps", "pdf"})) + r"))\b",
    re.I,
)
_SEG_SPLIT = re.compile(r"\s+-\s+")
# 只读模式会给标题加这些前缀/后缀，不是文件名的一部分
_DECOR = re.compile(r"^\s*(?:[\[(【（][^\])\]】）]*[\])\]】）]\s*)+|[\s*]+$")

TEXT_CAP = 700              # 单条内容记录的字符上限，跟 content_probe 保持一致
INDEX_TTL = 600.0           # 目录索引多久重建一次
RECENT_TTL = 120.0          # 最近使用记录多久重建一次
SCAN_ROOTS = ("E:\\desktop", "D:\\", "C:\\Users\\Blank\\Desktop", "C:\\Users\\Blank\\Documents")

_lock = threading.Lock()
_recent = {"at": 0.0, "map": {}}
_index = {"at": 0.0, "map": {}}
_scanning = False


# ---------------------------------------------------------------- 标题解析

def doc_name(title):
    """从窗口标题里抠出文档名。找不到返回空串。

    `2609绩效-Jack.xlsx * - WPS 表格`                   → 2609绩效-Jack.xlsx
    `cherry 10月业务绩效.xlsx (只读) * - [只读]cherry...`  → cherry 10月业务绩效.xlsx
    `KYNKO Offer 261029.xlsx - WPS 表格`                → KYNKO Offer 261029.xlsx

    标题结构是「文档名 [*] [只读] - 程序名」，所以先按 " - " 切段，
    只看第一段 —— 第二段往后是程序名、只读标记、重复的文档名，都不是要的。
    """
    if not title:
        return ""
    seg = _SEG_SPLIT.split(title, 1)[0]
    hits = [m.group(1) for m in _TITLE_DOC.finditer(seg)]
    if not hits:
        return ""
    # 同一段里还可能有前缀（`[只读]xxx.xlsx`），去掉后再剥一遍
    name = max(hits, key=len).strip()
    stripped = _DECOR.sub("", name).strip()
    return stripped or name.strip()


def ext_of(name):
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


# ---------------------------------------------------------------- 定位文件

def _recent_map():
    """`%APPDATA%\\Microsoft\\Windows\\Recent` 里的快捷方式 → 真实路径。
    用户刚打开过的文档一定在这里，比全盘扫快得多（1.3 秒扫 1100 个，之后走缓存）。"""
    now = time.time()
    with _lock:
        if _recent["map"] and now - _recent["at"] < RECENT_TTL:
            return _recent["map"]
    out = {}
    try:
        import win32com.client
        recent = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Recent")
        shell = win32com.client.Dispatch("WScript.Shell")
        for lnk in glob.glob(os.path.join(recent, "*.lnk")):
            try:
                target = shell.CreateShortcut(lnk).TargetPath
            except Exception:
                continue
            if not target or not os.path.isfile(target):
                continue
            key = os.path.basename(target).lower()
            out.setdefault(key, []).append(target)
    except Exception:
        return {}
    with _lock:
        _recent["map"] = out
        _recent["at"] = now
    return out


def _scan_index():
    """扫一遍常见工作目录，建 文件名 → 路径 索引。慢（秒级），放后台线程。"""
    global _scanning
    out = {}
    for root in SCAN_ROOTS:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            # 跳过明显无关的大目录，否则会扫到 node_modules / 缓存里去
            dirnames[:] = [d for d in dirnames if not d.startswith((".", "$"))]
            for f in filenames:
                if ext_of(f) in PARSE_EXTS:
                    key = f.lower()
                    full = os.path.join(dirpath, f)
                    out.setdefault(key, []).append(full)
    with _lock:
        _index["map"] = out
        _index["at"] = time.time()
        _scanning = False


def _index_map():
    global _scanning
    now = time.time()
    with _lock:
        if _index["map"] and now - _index["at"] < INDEX_TTL:
            return _index["map"]
        start = not _scanning
        if start:
            _scanning = True
    if start:
        threading.Thread(target=_scan_index, daemon=True).start()
    with _lock:
        return _index["map"]       # 首次调用时是空的，下一轮就有了


def locate(name):
    if not name:
        return ""
    if os.path.isabs(name):
        return name if os.path.isfile(name) else ""
    candidates = []
    for mapping in (_recent_map(), _index_map()):
        value = mapping.get(name.lower(), [])
        candidates.extend([value] if isinstance(value,str) else value)
    paths = {os.path.normcase(os.path.abspath(p)):p for p in candidates if os.path.isfile(p)}
    return next(iter(paths.values())) if len(paths)==1 else ""


# ---------------------------------------------------------------- 解析

def _decode(xml, tag_re):
    """从 XML 里把文本片段抠出来，顺手解掉 XML 实体和 Excel 的换行转义。"""
    out = []
    for frag in re.findall(tag_re, xml, re.S):
        t = frag
        t = t.replace("&#10;", " ").replace("&#13;", " ").replace("&amp;", "&")
        t = t.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
        t = t.replace("&apos;", "'")
        if t.strip():
            out.append(t.strip())
    return out


def _read_xlsx(path, budget):
    """读 xlsx/xlsm：先取共享字符串表，再按行拼出每个单元格。

    直接把 sharedStrings 全倒出来是不行的 —— 里面是去重后的碎片，
    顺序跟表格排版无关，读出来像乱码。必须按 sheet 的行列结构还原。
    """
    z = zipfile.ZipFile(path)
    names = z.namelist()
    shared = []
    if "xl/sharedStrings.xml" in names:
        xml = z.read("xl/sharedStrings.xml").decode("utf-8", "ignore")
        for si in re.findall(r"<si>(.*?)</si>", xml, re.S):
            shared.append("".join(_decode(si, r"<t[^>]*>(.*?)</t>")))

    sheets = sorted(n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
    lines = []
    for sheet in sheets:
        xml = z.read(sheet).decode("utf-8", "ignore")
        for row in re.findall(r"<row[^>]*>(.*?)</row>", xml, re.S):
            cells = []
            for m in re.finditer(r"<c\b([^>]*)>(.*?)</c>", row, re.S):
                attrs, body = m.group(1), m.group(2)
                typ = re.search(r'\bt="([^"]+)"', attrs)
                inline = re.search(r"<is>.*?<t[^>]*>(.*?)</t>", body, re.S)
                val = re.search(r"<v>(.*?)</v>", body, re.S)
                text = ""
                if inline:
                    text = inline.group(1)
                elif val:
                    raw = val.group(1)
                    if typ and typ.group(1) == "s" and raw.isdigit() and int(raw) < len(shared):
                        text = shared[int(raw)]
                    else:
                        text = raw
                text = text.replace("&#10;", " ").strip()
                if text:
                    cells.append(text[:40])
            line = " | ".join(cells)
            if line.strip():
                lines.append(line[:200])
            if sum(len(x) for x in lines) >= budget:
                break
        if sum(len(x) for x in lines) >= budget:
            break
    return "\n".join(lines)


def _read_docx(path, budget):
    z = zipfile.ZipFile(path)
    if "word/document.xml" not in z.namelist():
        return ""
    xml = z.read("word/document.xml").decode("utf-8", "ignore")
    xml = xml.replace("</w:p>", "\n")
    lines = [ln for ln in _decode(xml, r"<w:t[^>]*>(.*?)</w:t>") if ln]
    text = "\n".join(lines)
    return text[:budget]


def _read_pptx(path, budget):
    z = zipfile.ZipFile(path)
    slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                    key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[-1]).group(1)))
    out = []
    for s in slides:
        xml = z.read(s).decode("utf-8", "ignore")
        parts = _decode(xml, r"<a:t[^>]*>(.*?)</a:t>")
        if parts:
            out.append(" ".join(parts)[:200])
        if sum(len(x) for x in out) >= budget:
            break
    return "\n".join(out)


def _read_xls(path, budget):
    """老式 .xls 是二进制 OLE，需要 xlrd。没装就返回空，让上层退回 OCR。"""
    try:
        import xlrd
    except ImportError:
        return ""
    book = xlrd.open_workbook(path, on_demand=True)
    lines = []
    for sh in book.sheets():
        for r in range(min(sh.nrows, 80)):
            cells = []
            for c in range(min(sh.ncols, 20)):
                v = sh.cell_value(r, c)
                if v == "" or v is None:
                    continue
                cells.append(str(v).replace("\n", " ")[:40])
            if cells:
                lines.append(" | ".join(cells)[:200])
            if sum(len(x) for x in lines) >= budget:
                break
        if sum(len(x) for x in lines) >= budget:
            break
    return "\n".join(lines)


def _read_csv(path, budget):
    for enc in ("utf-8-sig", "gbk", "utf-16"):
        try:
            with open(path, "r", encoding=enc) as f:
                text = f.read(budget)
            return "\n".join(ln.strip()[:200] for ln in text.splitlines() if ln.strip())
        except (UnicodeDecodeError, OSError):
            continue
    return ""


READERS = {
    "xlsx": _read_xlsx, "xlsm": _read_xlsx,
    "docx": _read_docx, "pptx": _read_pptx,
    "xls": _read_xls, "csv": _read_csv,
}


def read_file(path, budget=TEXT_CAP):
    """按扩展名选解析器。解析失败一律返回空串，由调用方退回 OCR。"""
    ext = ext_of(path)
    fn = READERS.get(ext)
    if not fn:
        return ""
    try:
        return fn(path, budget) or ""
    except (zipfile.BadZipFile, OSError, ValueError, KeyError):
        return ""


# ---------------------------------------------------------------- 对外

def read_for_title(title, budget=TEXT_CAP):
    # A '*' explicitly means that disk content may be stale. Prefer UIA/OCR.
    if "*" in title:
        return {"path":"", "text":""}
    name = doc_name(title)
    path = locate(name) if name else ""
    if not path:
        return {"path":"", "text":""}
    from datetime import datetime, timezone, timedelta
    try:
        modified = datetime.fromtimestamp(os.path.getmtime(path),timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    except OSError:
        return {"path":"", "text":""}
    return {"path":path,"text":read_file(path,budget),"file_modified_at":modified,"scope":"saved-file-candidate"}


def explorer_listing(title, budget=TEXT_CAP, limit=25):
    """资源管理器窗口标题就是路径（`E:\\desktop\\客户\\智利`）→ 列这个目录里有什么。

    比 OCR 强的地方：一个字都不会错，而且能看到"这个文件夹里躺着哪些单据" ——
    判断"他在翻智利客户的资料"靠的就是这些文件名，标题只说了文件夹名。
    """
    raw = (title or "").strip()
    for cand in (raw, raw.split(" - ", 1)[0].strip()):
        if not cand or len(cand) < 3 or not os.path.isdir(cand):
            continue
        try:
            entries = list(os.scandir(cand))
        except OSError:
            continue
        files = []
        for e in entries:
            try:
                if e.is_file():
                    files.append((e.stat().st_mtime, e.name))
            except OSError:
                continue
        if not files:
            continue
        files.sort(reverse=True)
        names = [n for _m, n in files[:limit]]
        text = "文件夹「" + os.path.basename(cand) + "」里：" + " / ".join(names)
        return {"path": cand, "text": text[:budget]}
    return {"path": "", "text": ""}

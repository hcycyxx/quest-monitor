# -*- coding: utf-8 -*-
"""任务面板本地引擎：读窗口日志 → LLM 分析 → 写 quest_state.json
完全本地运行，不经过 DSH，无排队消息。
OpenAI 兼容 API（DeepSeek/硅基流动/OpenRouter/本地 vLLM 均可）。
"""
import json
import os
import time
from datetime import datetime
import urllib.request
import state_store as store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(ROOT, "config", "llm.json")
LOG = os.path.join(ROOT, "config", "win_log.jsonl")
STATE = os.path.join(ROOT, "config", "quest_state.json")
ALIVE = os.path.join(ROOT, "config", "panel_alive")
ENGINE_LOG = os.path.join(ROOT, "engine", "engine_run.log")


def log(msg):
    line = f"[engine] {time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        if os.path.exists(ENGINE_LOG) and os.path.getsize(ENGINE_LOG) > 1_000_000:
            with open(ENGINE_LOG, "r", encoding="utf-8", errors="replace") as f:
                keep = f.readlines()[-800:]
            with open(ENGINE_LOG, "w", encoding="utf-8") as f:
                f.writelines(keep)
        with open(ENGINE_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass

SYSTEM_PROMPT = """你是任务面板分析引擎。用户在你不知道的时候用电脑工作，你每分钟收到一次他最近的窗口活动轨迹（前台窗口标题+时间），任务是更新他的游戏风格任务面板状态。

规则：
1. main_quests 主线：今天的主要工作目标。side_quests 支线：中途插入的短任务（如临时搜文件、回消息、整理包材）。
2. status 取值 active/pending/done。steps 是可勾选步骤。progress 简短如"2/3"或"草拟中"。note 记录判断依据（窗口标题+时间）。
3. current_activity：一句话描述他现在在干嘛（从最新窗口标题推断，格式如"文档名 - 应用"要翻译成人话）。
4. suggestion：一句话建议（下一步做什么、是否跑偏、支线该收尾回主线了）。
5. 幂等节俭：与上次状态相比无实质变化时，输出 {"changed": false} 即可，不要重新生成全部内容。
6. 从窗口标题推断任务时要具体（文件名、客户名都保留）。看到新文档/新客户名可自动建支线或更新主线。
7. 只输出 JSON，不要 markdown 代码块，不要解释。

输出格式：
{"changed": true/false, "state": {"main_quests":[{"id":"M1","title":"...","status":"active","progress":"...","note":"...","steps":[{"text":"...","done":false}]}], "side_quests":[同结构], "current_activity":"...", "suggestion":"...", "updated_at":"ISO时间"}}
只输出 JSON。"""


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _ts(rec):
    """把 '2026-11-03T20:42:38' 解析成秒；失败返回 None。"""
    try:
        return datetime.strptime(rec.get("t", ""), "%Y-%m-%dT%H:%M:%S").timestamp()
    except (ValueError, TypeError):
        return None


def _clean_title(title, exe):
    """去掉浏览器/编辑器共有的尾巴，只留真正的内容部分。"""
    t = (title or "").strip()
    for suffix in (" - Google Chrome", " - Microsoft Edge", " \u2014 Mozilla Firefox",
                   " - Visual Studio Code", " \u2014 DeepSeek Harness"):
        if t.endswith(suffix):
            t = t[: -len(suffix)]
            break
    if exe == "chrome.exe" and t.startswith("WhatsApp"):
        return "WhatsApp 聊天"
    return t or "(\u684c\u9762)"


def read_log_tail(n=10, stall=5.0, scan=400, absorb=180.0):
    """把窗口轨迹压成"专注段"：合并重复标题、算停留时长、丢掉 stall 秒内的抖动。

    返回形如 "20:42:38 [chrome.exe] WhatsApp 聊天 · 2分36秒" 的多行文本。
    喂给模型的不再是 40 条原始采样，而是真正有语义的几次"做了什么"。
    """
    try:
        with open(LOG, "r", encoding="utf-8") as f:
            lines = f.readlines()[-scan:]
    except OSError:
        return "(日志为空)"
    recs = []
    for ln in lines:
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            continue
        ts = _ts(r)
        if ts is not None:
            r["_ts"] = ts
            recs.append(r)
    if not recs:
        return "(日志为空)"
    recs.sort(key=lambda r: r["_ts"])

    segments = []
    for r in recs:
        key = (r.get("exe", "?"), r.get("title", "") or "")
        if segments and segments[-1]["key"] == key:
            segments[-1]["end"] = r["_ts"]
            segments[-1]["idle"] = max(segments[-1]["idle"], float(r.get("idle_s") or 0))
        else:
            segments.append({"key": key, "start": r["_ts"], "end": r["_ts"],
                             "idle": float(r.get("idle_s") or 0)})

    for i, seg in enumerate(segments):
        # 末段没有"下一条记录"作为终点：用最后一条采样 + 一个心跳周期估算，
        # 而不是 0（否则最后那段专注永远被判成碎片丢掉）。
        nxt = segments[i + 1]["start"] if i + 1 < len(segments) else seg["end"] + 60.0
        seg["dwell"] = max(0.0, nxt - seg["start"])

    # 1) 抖动过滤：不足 stall 秒的碎片，若与最近同类段相隔 <= absorb 秒就并入，否则丢弃。
    kept = []
    for seg in segments:
        target = None
        if seg["dwell"] < stall:
            for cand in reversed(kept):
                if cand["key"] == seg["key"] and seg["start"] - cand["start"] <= absorb:
                    target = cand
                    break
            if target is None:
                continue
        if target is not None:
            target["dwell"] += seg["dwell"]
            target["idle"] = max(target["idle"], seg["idle"])
        else:
            kept.append(dict(seg))
    if not kept:
        kept = [dict(s) for s in segments]

    # 2) 跨噪合并：同一窗口被几个短噪打断（WhatsApp→桌面→WhatsApp）时并回一段。
    #    条件是中间夹着的其它段总时长 <= noise 秒，这样真实的长专注不会被误并。
    merged = []
    for seg in kept:
        if merged and merged[-1]["key"] == seg["key"] \
                and seg["start"] - merged[-1]["start"] <= absorb:
            merged[-1]["dwell"] += seg["dwell"]
            merged[-1]["idle"] = max(merged[-1]["idle"], seg["idle"])
        else:
            merged.append(dict(seg))
    kept = merged[-n:]

    out = []
    for seg in kept:
        exe, title = seg["key"]
        stamp = time.strftime("%H:%M:%S", time.localtime(seg["start"]))
        # 离开电脑的那段时间不算专注：否则"打开文档去吃饭"会被读成"专注了 3 小时"。
        dwell = seg["dwell"] - seg["idle"] if seg["idle"] >= 120 else seg["dwell"]
        d = max(0, int(dwell))
        span = "%d\u5206%d\u79d2" % (d // 60, d % 60) if d >= 60 else "%d\u79d2" % d
        idle = " \u00b7 \u79bb\u5f00%d\u79d2" % int(seg["idle"]) if seg["idle"] >= 120 else ""
        out.append("%s [%s] %s \u00b7 %s%s" % (stamp, exe, _clean_title(title, exe), span, idle))
    return "\n".join(out)


def state_digest(state):
    """把上次状态压成紧凑摘要给模型看，避免 2000 字硬截断把 JSON 切坏。"""
    if not isinstance(state, dict):
        return "(无)"
    out = []
    out.append("当前行动: " + str(state.get("current_activity") or "—"))
    for key, label in (("main_quests", "主线"), ("side_quests", "支线")):
        quests = state.get(key) or []
        if not quests:
            out.append(f"{label}: 无")
            continue
        out.append(f"{label}({len(quests)}):")
        # Keep full completion history on disk; send a bounded recent summary to AI.
        active = [q for q in quests if q.get("status") != "done"]
        done = [q for q in quests if q.get("status") == "done"]
        recent = sorted(done, key=lambda q: str(q.get("completed_at") or ""), reverse=True)[:6]
        if len(done) > len(recent):
            out.append(f"  另有{len(done)-len(recent)}项历史完成，已在本地保留")
        for q in active + recent:
            qid = q.get("id", "")
            title = q.get("title", "")
            status = q.get("status", "")
            prog = q.get("progress", "")
            steps = q.get("steps") or []
            sp = ""
            if steps:
                done = sum(1 for s in steps if s.get("done"))
                sp = f" 步骤{done}/{len(steps)}"
            out.append(f"  [{qid}] {title} <{status}> {prog}{sp}")
    sug = state.get("suggestion")
    if sug:
        out.append("上次建议: " + str(sug))
    return "\n".join(out)


def call_llm(cfg, user_msg, retries=2):
    body = json.dumps({
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.2,
        "max_tokens": 1500,
    }).encode("utf-8")
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    last_err = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}",
        })
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(3 * (attempt + 1))
    raise last_err


def parse_llm_json(text):
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    t = t.strip()
    start = t.find("{")
    end = t.rfind("}")
    if start >= 0 and end > start:
        return json.loads(t[start:end + 1])
    raise ValueError("no json in llm output")


def panel_alive(max_age=20):
    """面板每 3 秒写一次心跳；超过 max_age 没更新视为面板已关闭，引擎休眠不调模型。"""
    try:
        m = os.path.getmtime(ALIVE)
    except OSError:
        return False
    return (time.time() - m) < max_age


def _sig(state):
    """比较用的签名：忽略 updated_at，否则每轮都不相等，去重形同虚设。"""
    d = {k: v for k, v in state.items() if k != "updated_at"}
    return json.dumps(d, ensure_ascii=False, sort_keys=True)


def _quest_index(state):
    out = {}
    for key in ("main_quests", "side_quests"):
        for q in state.get(key) or []:
            if isinstance(q, dict):
                out[(key, str(q.get("id", "")), str(q.get("title", "")))] = q
    return out


def merge_user_ticks(new, old):
    return store.merge_ai_state(new, old)


def write_json_atomic(path, obj):
    return store.save_state(path, obj)


def trim_state(state, max_quests=8, max_steps=10):
    return store.merge_ai_state(state, {}, max_active=max_quests)


def main_loop():
    cfg = load_json(CFG, {})
    if not cfg.get("api_key") or "填入" in cfg.get("api_key", ""):
        log("请先在 config/llm.json 填入 api_key")
        return
    interval = max(30, int(cfg.get("interval_seconds", 60)))
    log(f"启动，每 {interval}s 分析一轮，model={cfg.get('model')}")
    # 去重现在由 state_store.apply_ai_update 内部的签名比对负责：
    # 它拿磁盘上最新状态和合并结果比，比这里留一个本进程内的快照可靠
    # （重启后不会重写、也不会被其他进程的写入骗过去）。
    idle_noted = False
    try:
        cfg_mtime = os.path.getmtime(CFG)
    except OSError:
        cfg_mtime = 0.0
    while True:
        # 配置热重载：改 llm.json 不用重启引擎
        try:
            m = os.path.getmtime(CFG)
            if m != cfg_mtime:
                cfg_mtime = m
                new_cfg = load_json(CFG, {})
                if new_cfg.get("model"):
                    cfg = new_cfg
                    interval = max(30, int(cfg.get("interval_seconds", 60)))
                    log(f"配置已重载，每 {interval}s 一轮，model={cfg.get('model')}")
        except OSError:
            pass
        if not panel_alive():
            if not idle_noted:
                log("面板已关闭 → 暂停分析，等待面板重新打开")
                idle_noted = True
            time.sleep(5)
            continue
        if idle_noted:
            log("面板已恢复 → 继续分析")
            idle_noted = False
        try:
            log_text = read_log_tail()
            prev = load_json(STATE, {})
            user_msg = (
                f"当前时间: {time.strftime('%Y-%m-%dT%H:%M:%S')}\n"
                f"上次面板状态:\n{state_digest(prev)}\n\n"
                f"最近窗口活动轨迹:\n{log_text}\n\n"
                f"请判断是否有实质变化并输出 JSON。"
            )
            raw = call_llm(cfg, user_msg)
            result = parse_llm_json(raw)
            if result.get("changed") and isinstance(result.get("state"), dict):
                st = result["state"]
                st.setdefault("main_quests", [])
                st.setdefault("side_quests", [])
                st.setdefault("current_activity", "")
                st.setdefault("suggestion", "")
                changed, st = store.apply_ai_update(STATE, st)
                if changed:
                    log(f"状态已更新（主线{len(st['main_quests'])} 支线{len(st['side_quests'])}）")
                else:
                    log("内容相同，跳过写入")
            else:
                log("无变化")
        except Exception as e:
            log(f"错误: {type(e).__name__}: {e}")
        time.sleep(interval)


if __name__ == "__main__":
    main_loop()

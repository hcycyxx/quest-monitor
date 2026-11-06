# -*- coding: utf-8 -*-
"""每日总结：把任务状态和窗口轨迹压成一份手账风格的 HTML。

数据来源只有本地两个文件：
  config/quest_state.json   任务、完成时间、优先级
  config/win_log.jsonl      窗口轨迹（用来算专注时长和主要工作段）

「明天优先做」会问一次模型；接口不通就退化成按优先级的启发式排序，
保证任何时候都能生成出一份完整的总结。
"""
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import paths
import summary_html

ROOT = paths.PROGRAM_DIR
STATE = paths.config("quest_state.json")
CFG = paths.config("llm.json")
LOG = paths.config("win_log.jsonl")
OUT = paths.SUMMARY_DIR

TZ = timezone(timedelta(hours=8))
WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
# 闲置超过这个秒数的记录不算在专注时间里（人在吃饭，不是在工作）
FOCUS_IDLE = 60.0
# 单条记录最多能代表多少秒的工作：心跳是 60 秒一条，给到 120 秒够宽松了
FOCUS_CAP = 120.0
MAX_TOMORROW = 5


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _stamp(raw):
    """把各种历史写法的时间统一成带时区的 datetime；解析不了返回 None。"""
    if not isinstance(raw, str) or not raw:
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    return value.replace(tzinfo=TZ) if value.tzinfo is None else value.astimezone(TZ)


def _hhmm(value):
    return value.strftime("%H:%M") if value else None


def _day_of(value):
    return value.date() if value else None


def _all_quests(state):
    out = []
    for key in ("main_quests", "side_quests"):
        for q in state.get(key) or []:
            if isinstance(q, dict):
                out.append((key, q))
    return out


def _completed_at(q):
    for field in ("completed_at", "completedAt", "done_at"):
        value = _stamp(q.get(field))
        if value:
            return value
    return None


def _priority(q):
    value = str(q.get("priority") or "").lower()
    return value if value in ("high", "mid", "low") else ""


def _step_counts(q):
    steps = [s for s in (q.get("steps") or []) if isinstance(s, dict)]
    return sum(1 for s in steps if s.get("done")), len(steps), steps


def _brief(q, key):
    done_steps, total_steps, steps = _step_counts(q)
    return {
        "title": str(q.get("title") or "未命名任务"),
        "id": str(q.get("id") or ""),
        "key": key,
        "priority": _priority(q),
        "status": str(q.get("status") or "active"),
        "progress": str(q.get("progress") or ""),
        "note": str(q.get("note") or ""),
        "steps": [{"text": str(s.get("text") or ""), "done": bool(s.get("done"))}
                  for s in steps][:10],
        "done_steps": done_steps,
        "total_steps": total_steps,
    }


def focus_stats(day):
    """从窗口轨迹算专注时长和主要工作段。日志轮转过就只能算到最近的部分。"""
    records = []
    try:
        with open(LOG, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if not str(rec.get("t", "")).startswith(day.isoformat()):
                    continue
                records.append(rec)
    except OSError:
        return 0, []
    if not records:
        return 0, []

    def secs(rec):
        return _stamp(rec.get("t"))

    total = 0.0
    previous = None
    for rec in records:
        stamp = secs(rec)
        if stamp is None:
            continue
        try:
            idle = float(rec.get("idle_s") or 0)
        except (TypeError, ValueError):
            idle = 0.
        if idle < FOCUS_IDLE:
            span = FOCUS_CAP
            if previous is not None:
                span = min(FOCUS_CAP, max(0., (stamp - previous).total_seconds()))
            total += span
        previous = stamp

    # 主要工作段：同标题连续出现 ≥ 4 分钟才算一段，取最长的 4 段
    segments = []
    current = None
    for rec in records:
        stamp = secs(rec)
        if stamp is None:
            continue
        title = str(rec.get("title") or "").strip()
        if not title:
            continue
        if current and current["title"] == title:
            current["to"] = stamp
            current["n"] += 1
        else:
            if current:
                segments.append(current)
            current = {"title": title, "from": stamp, "to": stamp, "n": 1}
    if current:
        segments.append(current)

    picked = []
    for seg in segments:
        minutes = (seg["to"] - seg["from"]).total_seconds() / 60.
        if minutes < 4:
            continue
        picked.append({"minutes": minutes,
                       "from": _hhmm(seg["from"]), "to": _hhmm(seg["to"]),
                       "title": seg["title"]})
    picked.sort(key=lambda s: s["minutes"], reverse=True)
    picked = picked[:4]
    picked.sort(key=lambda s: str(s["from"]))
    activity = [{"from": s["from"], "to": s["to"],
                 "text": f"在 {s['title']}（约 {s['minutes']:.0f} 分钟）"}
                for s in picked]
    return int(round(total / 60.)), activity


def _fallback_tomorrow(active):
    order = {"high": 0, "mid": 1, "low": 2, "": 1}
    ranked = sorted(active, key=lambda q: order.get(q["priority"], 1))
    out = []
    for q in ranked[:MAX_TOMORROW]:
        out.append({
            "title": q["title"],
            "why": ("今天没做完，优先级高" if q["priority"] == "high"
                    else "今天开了头，接着收尾"),
            "priority": q["priority"] or "mid",
        })
    return out


def _ask_llm(cfg, user_msg, timeout=60):
    """总结用的最小调用：不重试、不抛错，失败就当没有模型可用。"""
    if not cfg.get("api_key") or not cfg.get("base_url"):
        return ""
    body = json.dumps({
        "model": cfg.get("model"),
        "messages": [
            {"role": "system", "content": (
                "你是任务面板的收尾助手。根据用户今天完成和未完成的任务，"
                "给出明天最该先做的 3~5 件事。"
                "只输出 JSON：{\"tomorrow\":[{\"title\":\"...\",\"why\":\"一句话理由\","
                "\"priority\":\"high|mid|low\"}]}。不要 markdown，不要解释。")},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.3,
        "max_tokens": 700,
    }).encode("utf-8")
    req = urllib.request.Request(
        str(cfg["base_url"]).rstrip("/") + "/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer %s" % cfg.get("api_key")})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except Exception:
        return ""


def _parse_tomorrow(raw):
    text = (raw or "").strip()
    if not text:
        return []
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return []
    items = data.get("tomorrow") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    out = []
    for item in items[:MAX_TOMORROW]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        prio = str(item.get("priority") or "").lower()
        out.append({"title": title,
                    "why": str(item.get("why") or "").strip(),
                    "priority": prio if prio in ("high", "mid", "low") else "mid"})
    return out


def collect(day=None, use_llm=True):
    """组装 render() 需要的完整数据。缺什么字段就补空，不抛错。"""
    day = day or datetime.now(TZ).date()
    state = _read_json(STATE, {})
    quests = _all_quests(state)

    done, active, timeline = [], [], []
    for key, q in quests:
        stamp = _completed_at(q)
        brief = _brief(q, key)
        created = _stamp(q.get("created_at"))
        reopened = _stamp(q.get("reopened_at"))
        if _day_of(created) == day:
            timeline.append({"time": _hhmm(created), "title": brief["title"],
                             "kind": "created"})
        if _day_of(reopened) == day:
            timeline.append({"time": _hhmm(reopened), "title": brief["title"],
                             "kind": "reopened"})
        if q.get("status") == "done":
            if _day_of(stamp) == day:
                brief["completed_at"] = _hhmm(stamp)
                done.append(brief)
                timeline.append({"time": _hhmm(stamp), "title": brief["title"],
                                 "kind": "done"})
        else:
            active.append(brief)

    done.sort(key=lambda q: str(q.get("completed_at") or ""))
    timeline.sort(key=lambda e: str(e.get("time") or ""))

    order = {"high": 0, "mid": 1, "low": 2, "": 1}
    status_rank = {"active": 0, "pending": 1, "waiting": 2}
    active.sort(key=lambda q: (order.get(q["priority"], 1),
                               status_rank.get(q["status"], 1)))

    focus_minutes, activity = focus_stats(day)
    times = [e["time"] for e in timeline if e.get("time")]

    tomorrow = []
    if use_llm and active:
        cfg = _read_json(CFG, {})
        lines = ["今天是 %s。" % day.isoformat()]
        lines.append("今天完成：")
        if done:
            lines.extend("  - %s" % q["title"] for q in done[:12])
        else:
            lines.append("  （无）")
        lines.append("还在进行中：")
        for q in active[:10]:
            lines.append("  - [%s] %s（%s）" % (q["priority"] or "mid", q["title"],
                                               q["status"]))
        if state.get("suggestion"):
            lines.append("今天最后一条建议：%s" % state.get("suggestion"))
        lines.append("请给出明天最该先做的 %d 件事。" % MAX_TOMORROW)
        tomorrow = _parse_tomorrow(_ask_llm(cfg, "\n".join(lines)))
    if not tomorrow:
        tomorrow = _fallback_tomorrow(active)

    return {
        "date": day.isoformat(),
        "weekday": WEEKDAYS[day.weekday()],
        "generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "done": done,
        "active": active,
        "suggestion": str(state.get("suggestion") or ""),
        "tomorrow": tomorrow,
        "timeline": timeline,
        "stats": {
            "done": len(done),
            "active": len(active),
            "side_done": sum(1 for q in done if q["key"] == "side_quests"),
            "main_done": sum(1 for q in done if q["key"] == "main_quests"),
            "focus_minutes": focus_minutes,
            "first_at": times[0] if times else None,
            "last_at": times[-1] if times else None,
        },
        "activity": activity,
    }


def build(day=None, use_llm=True):
    """生成 HTML 并返回文件路径。文件名固定用日期，重复生成直接覆盖。

    写不进去时返回空串而不是抛异常：总结是自动触发的，半夜三点因为
    目录只读崩一次，用户第二天只会看到托盘菜单点了没反应。
    """
    day = day or datetime.now(TZ).date()
    data = collect(day, use_llm=use_llm)
    html = summary_html.render(data)
    path = os.path.join(OUT, "%s.html" % day.isoformat())
    tmp = path + ".tmp"
    try:
        os.makedirs(OUT, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(html)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return ""
    return path


def history():
    """按日期倒序列出已生成的总结：[{date, path, mtime, size}]。"""
    items = []
    try:
        names = os.listdir(OUT)
    except OSError:
        return items
    for name in names:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.html", name):
            continue
        path = os.path.join(OUT, name)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        items.append({"date": name[:-5], "path": path,
                      "mtime": stat.st_mtime, "size": stat.st_size})
    items.sort(key=lambda i: i["date"], reverse=True)
    return items


def _marker_path(day):
    return os.path.join(OUT, ".auto-%s" % day.isoformat())


def auto_due(hour=18):
    """到点且今天还没自动生成过，返回今天日期；否则 None。"""
    now = datetime.now(TZ)
    if now.hour < int(hour):
        return None
    day = now.date()
    if os.path.exists(_marker_path(day)):
        return None
    return day


def mark_auto(day):
    os.makedirs(OUT, exist_ok=True)
    try:
        with open(_marker_path(day), "w", encoding="utf-8") as f:
            f.write(str(int(time.time())))
    except OSError:
        pass


if __name__ == "__main__":
    print(build())

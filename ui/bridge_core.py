"""V10 desktop adapter. Reuses the project's state transactions and workers.

No GUI, workers, model requests or files are created by importing this module.
Only whitelisted data is sent to the local renderer; credentials stay in Python.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / "engine", ROOT / "ui"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import paths
import state_store as store


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as stream:
            result = json.load(stream)
        return result if isinstance(result, dict) else default
    except (OSError, ValueError):
        return default


def progress(task):
    """Keep V9's precedence: completion, evidence-backed estimate, then steps."""
    if task.get("status") == "done":
        return {"low": 100, "high": 100, "label": "100% · 已确认完成", "source": "done"}
    if task.get("completion_candidate"):
        return {"low": None, "high": None, "label": "待确认完成", "source": "unknown"}
    bounds = task.get("progress_range")
    finite = lambda x: type(x) in (int, float) and math.isfinite(x)
    if (isinstance(bounds, list) and len(bounds) == 2 and all(map(finite, bounds))
            and 0 <= bounds[0] <= bounds[1] <= 95 and task.get("progress_basis")):
        return {"low": bounds[0], "high": bounds[1],
                "label": f"估算 {bounds[0]:.0f}–{bounds[1]:.0f}%", "source": "estimate"}
    for field in ("progress_percent", "estimated_progress"):
        value = task.get(field)
        if finite(value):
            value = max(0, min(95, value))
            return {"low": value, "high": value, "label": f"估算 {value:.0f}%", "source": "estimate"}
    raw = str(task.get("progress", "")).strip()
    match = re.fullmatch(r"(?:约|估算)?\s*(\d+(?:\.\d+)?)\s*%", raw)
    if match:
        value = min(95, float(match[1]))
        return {"low": value, "high": value, "label": f"估算 {value:.0f}%", "source": "estimate"}
    steps = task.get("steps") or []
    if steps:
        count = sum(bool(step.get("done")) for step in steps)
        value = count * 100 / len(steps)
        return {"low": value, "high": value, "label": f"步骤 {count}/{len(steps)}", "source": "steps"}
    match = re.fullmatch(r"(\d+)\s*/\s*(\d+)", raw)
    if match and int(match[2]) > 0:
        value = min(100, int(match[1]) * 100 / int(match[2]))
        return {"low": value, "high": value, "label": f"步骤 {match[1]}/{match[2]}", "source": "steps"}
    return {"low": None, "high": None, "label": "待估算", "source": "unknown"}


def task_view(task, key):
    result = {name: task.get(name) for name in
              ("id", "title", "status", "priority", "note", "progress_basis", "completion_candidate")}
    result["key"] = key
    result["steps"] = [{"text": str(step.get("text", "")), "done": bool(step.get("done"))}
                       for step in (task.get("steps") or []) if isinstance(step, dict)]
    old_progress = str(task.get("progress", ""))
    old_progress = old_progress if not re.fullmatch(r"[\d\s./%]+", old_progress) else ""
    result["live"] = str(task.get("live_progress") or task.get("progress_summary") or
                         task.get("waiting_reason") or old_progress or "暂无实时进展")
    result["completed_at"] = task.get("completed_at") or task.get("completedAt") or task.get("done_at")
    result["progress"] = progress(task)
    if task.get("status") == "waiting":
        result["progress"]["label"] += " · 进度暂停"
    return result


def rank(task):
    return ({"high": 0, "mid": 1, "low": 2}.get(task.get("priority"), 1)
            + (3 if task.get("status") == "waiting" else 0))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


from datetime import datetime
from timeline_core import TimelineStore,TZ
from service_lifecycle_v11 import Lifecycle

class Bridge:
    def __init__(self, data_dir=None, controller=None):
        self._data = Path(data_dir or paths.CONFIG_DIR)
        self._state_path = self._data / "quest_state.json"
        self._prefs_path = self._data / "ui_v10.json"
        self._last_state = {"main_quests": [], "side_quests": []}
        self._lock = threading.RLock()
        self._controller = controller
        self._undo = {}
        self._requests = {}
        self._summary_busy = False
        self._summary_error = ""
        self._summary_retry = 0
        self._settings_process = None
        self._message = ""
        old = read_json(self._data / "ui.json", {})
        def number(value, default, low, high):
            if type(value) not in (int,float) or not math.isfinite(value):return default
            return max(low,min(high,int(value)))
        font=number(old.get('font_size'),10,8,16)
        self._prefs={'skin':old.get('skin','glass'),'font':round(font*4/3),
                     'pinned':old.get('topmost',True),'autoHide':True,'width':336,'height':620,
                     'expanded':True,'stepsOpen':False,'edgeSide':None}
        saved=read_json(self._prefs_path,{})
        self._prefs.update({key:value for key,value in saved.items() if key in self._prefs or key in ('x','y')})
        if self._prefs.get('skin') not in ('glass','transparent','journal','night'):self._prefs['skin']='glass'
        for key,default,low,high in [('font',14,13,21),('width',336,300,1600),('height',620,240,1800)]:
            self._prefs[key]=number(self._prefs.get(key),default,low,high)
        for key in ('pinned','autoHide','expanded','stepsOpen'):
            if type(self._prefs.get(key)) is not bool:self._prefs[key]=key!='stepsOpen'
        if self._prefs.get('edgeSide') not in (None,'left','right'):self._prefs['edgeSide']=None
        for key in ('x','y'):
            if key in self._prefs:
                value=self._prefs[key]
                if type(value) not in (int,float) or not math.isfinite(value):self._prefs.pop(key,None)
                else:self._prefs[key]=number(value,0,-100000,100000)
        self._old_ui_stamp=self._file_stamp(self._data/'ui.json')
        self._old_ui_font=read_json(self._data/'ui.json',{}).get('font_size')
        self._base_python = str(Path(sys.base_prefix) / "python.exe")
        self._lifecycle=Lifecycle()
        if self._controller:self._controller._lifecycle=self._lifecycle
        self._cancelled_operations=set()
        self._undo_results={}
        self._timeline_store=None
        self._timeline_error=''
        self._timeline_signature=None
        try:self._timeline_store=TimelineStore(self._data)
        except Exception as exc:self._timeline_error='时间轴存储未打开：'+str(exc)[:160]
        try:self._prefs['cardOrder']=self._card_order(read_json(self._prefs_path,{}).get('cardOrder',[]))
        except ValueError:self._prefs['cardOrder']=[]

    @staticmethod
    def _file_stamp(path):
        try:
            return path.stat().st_mtime_ns
        except OSError:
            return None

    def _sync_detailed_font(self):
        path = self._data / "ui.json"
        stamp = self._file_stamp(path)
        if stamp != self._old_ui_stamp:
            self._old_ui_stamp = stamp
            value = read_json(path, {}).get("font_size")
            if value!=self._old_ui_font:
                self._old_ui_font=value
                if type(value) is int:self.preferences({"font": round(value * 4 / 3)})

    def _save_preferences(self, patch):
        with self._lock:
            try:
                if not isinstance(patch, dict):
                    raise ValueError("设置格式不正确")
                approved = {}
                for key in ("expanded", "stepsOpen", "pinned", "autoHide"):
                    if key in patch and type(patch[key]) is bool:
                        approved[key] = patch[key]
                if patch.get("skin") in ("glass", "transparent", "journal", "night"):
                    approved["skin"] = patch["skin"]
                for key, low, high in (("font", 13, 21), ("width", 300, 1600), ("height", 240, 1800)):
                    if key in patch and type(patch[key]) in (int, float) and math.isfinite(patch[key]):
                        approved[key] = max(low, min(high, int(patch[key])))
                if "edgeSide" in patch and patch["edgeSide"] in (None, "left", "right"):
                    approved["edgeSide"] = patch["edgeSide"]
                for key in ("x", "y"):
                    if key in patch and type(patch[key]) in (int, float) and math.isfinite(patch[key]):
                        approved[key] = max(-100000, min(100000, int(patch[key])))
                new = {**self._prefs, **approved}
                # Runtime preferences are intentionally mutable; earlier UI artifacts are not touched.
                self._data.mkdir(parents=True, exist_ok=True)
                store._atomic_write(self._prefs_path, new)
                self._prefs = new
                if self._controller:
                    self._controller.configure(approved)
                return {"ok": True, "prefs": copy.deepcopy(new)}
            except (OSError, ValueError) as exc:
                return {"ok": False, "error": "设置未保存：" + str(exc)}

    def window_action(self, name, payload=None):
        if not self._controller:
            return {"ok": False, "error": "桌面窗口未连接"}
        return self._controller.action(name, payload)

    def open_detail_settings(self):
        try:
            if self._settings_process and self._settings_process.poll() is None:
                return {"ok": True}
            self._settings_process = subprocess.Popen(
                [self._base_python, str(ROOT / "ui" / "settings_v10.py")], cwd=ROOT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return {"ok": True}
        except OSError as exc:
            return {"ok": False, "error": "设置打开失败：" + str(exc)}

    def summary(self, generate=False, day=None):
        """Model requests occur only through the original daily-summary workflow."""
        import daily_summary as ds
        try:
            selected = ds.datetime.strptime(day, "%Y-%m-%d").date() if day else ds.datetime.now(ds.TZ).date()
        except (TypeError, ValueError):
            return {"ok": False, "error": "日报日期不正确"}
        path = ds.latest(selected)
        if path and not generate:
            os.startfile(path)
            return {"ok": True}
        with self._lock:
            if self._summary_busy:
                return {"ok": True, "message": "日报正在生成，请稍候"}
            self._summary_busy = True
            self._summary_error = ""
        def build():
            try:
                result = ds.build(selected)
                if not result or not Path(result).is_file():
                    raise RuntimeError("日报未生成，请稍后重试")
                ds.mark_auto(selected)
                if generate != "automatic":
                    os.startfile(result)
            except Exception as exc:
                self._summary_error = str(exc)[:200]
                self._summary_retry = time.monotonic() + 300
            finally:
                self._summary_busy = False
        threading.Thread(target=build, daemon=True).start()
        return {"ok": True, "message": "正在生成日报"}

    def _data_snapshot(self):
        with self._lock:
            self._sync_detailed_font()
            error = ""
            try:
                if not self._state_path.exists():
                    raise FileNotFoundError("任务文件暂不可用")
                value = store.read_state(self._state_path)
                for key in ("main_quests", "side_quests"):
                    if not isinstance(value.get(key, []), list):
                        raise ValueError("任务列表格式不正确")
                for key in ('main_quests','side_quests'):
                    for task in value.get(key,[]):
                        if not isinstance(task,dict):raise ValueError('任务条目格式不正确')
                        if task.get('title') is not None and not isinstance(task['title'],str):raise ValueError('任务标题格式不正确')
                        if task.get('priority') is not None and not isinstance(task['priority'],str):raise ValueError('任务优先级格式不正确')
                        steps=task.get('steps') or []
                        if not isinstance(steps,list) or any(not isinstance(step,dict) for step in steps):raise ValueError('任务步骤格式不正确')
                self._last_state = value
            except (OSError, ValueError) as exc:
                error = "任务读取失败，保留上次内容：" + str(exc)[:100]
            value = self._last_state
            mains = sorted([q for q in value.get("main_quests", []) if q.get("status") != "done"], key=rank)
            current = next((q for q in mains if q.get("status") == "active"), mains[0] if mains else None)
            others = ([task_view(q, "main_quests") for q in mains if q is not current]
                      + [task_view(q, "side_quests") for q in sorted(
                          [q for q in value.get("side_quests", []) if q.get("status") != "done"], key=rank)])
            history = [task_view(q, key) for key in ("main_quests", "side_quests")
                       for q in value.get(key, []) if q.get("status") == "done"]
            history.sort(key=lambda q: str(q.get("completed_at") or ""), reverse=True)
            idle = read_json(self._data / "activity_status.json", {})
            try:
                resting = bool(idle.get("suspended")) and time.time() - float(idle.get("checked_at", 0)) < 35
            except (TypeError, ValueError):
                resting = False
            return {"ok": True, "current": task_view(current, "main_quests") if current else None,
                    "others": others, "history": history, "activity": str(value.get("current_activity") or "暂无当前活动"),
                    "suggestion": str(value.get("suggestion") or "暂无下一步建议"),
                    "updated_at": value.get("updated_at"), "paused": (self._data / "paused").exists(),
                    "resting": resting, "error": error, "prefs": copy.deepcopy(self._prefs),
                    "summaryBusy": self._summary_busy, "summaryError": self._summary_error,
                    "message": self._message, "desktop": self._controller.state() if self._controller else {}}

    def _data_task_action(self, request):
        """Explicit target values, deduplicated requests, identity checked inside the file lock."""
        with self._lock:
            try:
                if not isinstance(request, dict):
                    raise ValueError("操作格式不正确")
                request_id = str(request.get("request_id", ""))
                if not request_id or len(request_id) > 100:
                    raise ValueError("缺少操作编号")
                if ('task',request_id) in self._cancelled_operations:raise ValueError('该请求已取消，未重复写入')
                request_digest = digest(request)
                if request_id in self._requests:
                    prior_digest, result = self._requests[request_id]
                    if prior_digest != request_digest:
                        raise ValueError("操作编号已被其他请求使用")
                    return self._receipt_reply(result)
                key, qid = request.get("key"), request.get("id")
                if key not in ("main_quests", "side_quests"):
                    raise ValueError("任务分组不正确")
                before, after = {}, {}
                def edit(state):
                    task = next((q for q in state.get(key, []) if q.get("id") == qid), None)
                    if task is None or task.get("title") != request.get("title"):
                        raise ValueError("任务已变化，请刷新后重试")
                    before.update(copy.deepcopy(task))
                    steps = task.get("steps") or []
                    if not isinstance(steps,list) or any(not isinstance(step,dict) for step in steps):
                        raise ValueError("步骤数据格式不正确，未改写任务")
                    if '_user_state' in task and not isinstance(task['_user_state'],dict):
                        raise ValueError("人工状态格式不正确，未改写任务")
                    manual = task.setdefault("_user_state", {"steps": {}})
                    if 'steps' in manual and not isinstance(manual['steps'],dict):
                        raise ValueError("人工步骤状态格式不正确，未改写任务")
                    overrides = manual.setdefault("steps", {})
                    if request.get("kind") == "step":
                        index = request.get("step")
                        if type(index) is not int or not 0 <= index < len(steps):
                            raise ValueError("步骤已变化，请刷新后重试")
                        step = steps[index]
                        if step.get("text", "") != request.get("step_text"):
                            raise ValueError("步骤已变化，请刷新后重试")
                        if type(request.get("done")) is not bool:
                            raise ValueError("步骤状态不正确")
                        step["done"] = request["done"]
                        overrides[str(step.get("text", "")).strip()] = step["done"]
                        if all(s.get("done") for s in steps):
                            task["status"] = "done"
                        elif task.get("status") == "done":
                            task["status"] = "active"
                    elif request.get("kind") == "task":
                        if type(request.get("done")) is not bool:
                            raise ValueError("任务状态不正确")
                        task["status"] = "done" if request["done"] else "active"
                        for step in steps:
                            step["done"] = request["done"]
                            overrides[str(step.get("text", "")).strip()] = step["done"]
                    else:
                        raise ValueError("未知任务操作")
                    if task.get("status") == "done":
                        task.setdefault("completed_at", store.now())
                    else:
                        for field in ("completed_at", "completedAt", "done_at"):
                            task.pop(field, None)
                    manual.update(status=task.get("status", "active"), changed_at=store.now())
                    after.update(copy.deepcopy(task))
                store.mutate_state(self._state_path, edit)
                token = uuid.uuid4().hex
                self._undo[token] = (key, qid, before, digest(after))
                if len(self._undo) > 25:
                    self._undo.pop(next(iter(self._undo)))
                receipt={'ok':True,'undo':token,'task':task_view(after,key)}
                self._requests[request_id]=(request_digest,receipt)
                return self._receipt_reply(receipt)
            except (OSError, ValueError, TimeoutError) as exc:
                return {"ok": False, "error": "任务未保存：" + str(exc)}

    def _data_undo(self, token):
        with self._lock:
            if str(token) in self._undo_results:return self._receipt_reply(self._undo_results[str(token)])
            if ('undo',str(token)) in self._cancelled_operations:return {'ok':False,'error':'撤销请求已取消'}
            record = self._undo.get(str(token))
            if not record:
                return {"ok": False, "error": "此操作已撤销或已过期"}
            key, qid, before, expected = record
            try:
                def edit(state):
                    task = next((q for q in state.get(key, []) if q.get("id") == qid), None)
                    if task is None or digest(task) != expected:
                        raise ValueError("任务已有新变化，请从完成历史中核对后恢复")
                    task.clear()
                    task.update(copy.deepcopy(before))
                store.mutate_state(self._state_path, edit)
                self._undo.pop(str(token), None)
                receipt={'ok':True}
                self._undo_results[str(token)]=receipt
                return self._receipt_reply(receipt)
            except (OSError, ValueError, TimeoutError) as exc:
                return {"ok": False, "error": str(exc)}

    def _base_preferences(self, patch):
        result=self._save_preferences(patch)
        return result

    def _summary_daily_tick(self):
        if self._summary_busy or time.monotonic() < self._summary_retry:
            return
        try:
            import daily_summary as ds
            old = read_json(self._data / "ui.json", {})
            day = ds.auto_due(int(old.get("summary_hour", 18)))
            if day:
                self.summary(generate="automatic", day=day.isoformat())
        except Exception as exc:
            self._summary_error = str(exc)[:200]
            self._summary_retry = time.monotonic() + 300

    def snapshot(self):
        result=self._data_snapshot()
        if self._timeline_store and not result.get('error'):
            try:
                with self._lock:
                    signature=tuple((key,str(task.get('id')),str(task.get('title')),str(task.get('status')),
                                     str(task.get('created_at')),str(task.get('completed_at') or task.get('completedAt') or task.get('done_at')))
                                    for key in ('main_quests','side_quests') for task in self._last_state.get(key,[]))
                    if signature!=self._timeline_signature:
                        self._timeline_store.observe_tasks(self._last_state)
                        self._timeline_signature=signature
            except Exception as exc:self._timeline_error='时间轴事件未保存：'+str(exc)[:160]
        result['health']=self._lifecycle.snapshot()
        return result

    def task_action(self,request):
        result=self._data_task_action(request)
        if result.get('ok') and isinstance(request,dict) and request.get('kind')=='task' and request.get('done') is False and self._timeline_store:
            try:self._timeline_store.action_event(request.get('request_id'),request.get('title'),'reopened')
            except Exception as exc:self._timeline_error='恢复事件未记录：'+str(exc)[:160]
        return result

    def undo(self,token):
        with self._lock:
            prior=self._undo.get(str(token))
            result=self._data_undo(token)
            if result.get('ok') and prior and self._timeline_store:
                try:self._timeline_store.action_event('undo:'+str(token),prior[2].get('title'),'undone')
                except Exception as exc:self._timeline_error='撤销事件未记录：'+str(exc)[:160]
            return result

    @staticmethod
    def _card_order(value):
        if not isinstance(value,list) or len(value)>2000:raise ValueError('卡片顺序格式不正确')
        result=[];seen=set()
        for key in value:
            if not isinstance(key,str) or len(key)>250 or not key.startswith(('main_quests:','side_quests:')):
                raise ValueError('卡片标识不正确')
            if key not in seen:result.append(key);seen.add(key)
        return result

    def preferences(self,patch):
        if not isinstance(patch,dict) or 'cardOrder' not in patch:return self._base_preferences(patch)
        with self._lock:
            old=copy.deepcopy(self._prefs)
            try:
                self._prefs['cardOrder']=self._card_order(patch['cardOrder'])
                result=self._base_preferences({key:value for key,value in patch.items() if key!='cardOrder'})
                if not result.get('ok'):self._prefs=old
                return result
            except (ValueError,OSError) as exc:
                self._prefs=old
                return {'ok':False,'error':'卡片顺序未保存：'+str(exc)}

    def _receipt_reply(self,receipt):
        result=copy.deepcopy(receipt)
        try:result['snapshot']=self.snapshot()
        except Exception:result['snapshotError']='操作已保存，但界面刷新暂未成功'
        return result

    def resolve_operation(self,kind,operation_id):
        if kind not in ('task','undo') or not isinstance(operation_id,str) or not 0<len(operation_id)<=200:
            return {'ok':False,'error':'操作标识不正确'}
        with self._lock:
            receipt=self._requests.get(operation_id,(None,None))[1] if kind=='task' else self._undo_results.get(operation_id)
            if receipt:return {'ok':True,'state':'committed','result':self._receipt_reply(receipt)}
            # Reserving a cancellation while owning the mutation lock makes late arrivals harmless.
            self._cancelled_operations.add((kind,operation_id))
            return {'ok':True,'state':'cancelled','error':'未执行的请求已取消，可以重新操作'}

    def pause(self,paused):
        return self._lifecycle.submit(paused)

    def _daily_tick(self):
        self._summary_daily_tick()

    def timeline(self,day=None,cursor=None):
        if not self._timeline_store:return {'ok':False,'error':self._timeline_error or '时间轴不可用'}
        try:
            selected=day or datetime.now(TZ).date().isoformat()
            return self._timeline_store.collect(selected,cursor)
        except Exception as exc:return {'ok':False,'error':'时间轴读取失败：'+str(exc)[:180]}

    def timeline_delta(self,day,since):
        if not self._timeline_store:return {'ok':False,'error':'时间轴不可用'}
        try:return self._timeline_store.delta(day,since)
        except Exception as exc:return {'ok':False,'error':'时间轴更新失败：'+str(exc)[:180]}

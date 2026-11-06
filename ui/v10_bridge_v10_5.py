"""V10.4 local timeline API; no model calls are used for timeline records."""
from datetime import datetime
import threading
from window_dwell_v10_5 import TimelineStore
from timeline_v10_4 import TZ
from v10_bridge_v10_3 import Bridge as PreviousBridge,ROOT


class Bridge(PreviousBridge):
    def __init__(self,data_dir=None,controller=None):
        super().__init__(data_dir,controller)
        self._timeline_store=None
        self._timeline_error=''
        self._timeline_signature=None
        self._capture_thread=None
        try:self._timeline_store=TimelineStore(self._data)
        except Exception as exc:self._timeline_error='时间轴存储未打开：'+str(exc)[:160]

    def snapshot(self):
        result=super().snapshot()
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
        return result

    def _capture_timeline(self):
        try:
            if self._timeline_store:self._timeline_store.capture()
        except Exception as exc:self._timeline_error='活动归档暂不可用：'+str(exc)[:160]

    def task_action(self,request):
        result=super().task_action(request)
        if result.get('ok') and isinstance(request,dict) and request.get('kind')=='task' and request.get('done') is False and self._timeline_store:
            try:self._timeline_store.action_event(request.get('request_id'),request.get('title'),'reopened')
            except Exception as exc:self._timeline_error='恢复事件未记录：'+str(exc)[:160]
        return result

    def undo(self,token):
        with self._lock:
            prior=self._undo.get(str(token))
            result=super().undo(token)
            if result.get('ok') and prior and self._timeline_store:
                try:self._timeline_store.action_event('undo:'+str(token),prior[2].get('title'),'undone')
                except Exception as exc:self._timeline_error='撤销事件未记录：'+str(exc)[:160]
            return result

    def _daily_tick(self):
        super()._daily_tick()
        if self._timeline_store and (self._capture_thread is None or not self._capture_thread.is_alive()):
            self._capture_thread=threading.Thread(target=self._capture_timeline,daemon=True)
            self._capture_thread.start()

    def timeline(self,day=None):
        if not self._timeline_store:return {'ok':False,'error':self._timeline_error or '时间轴不可用'}
        try:
            selected=day or datetime.now(TZ).date().isoformat()
            datetime.strptime(selected,'%Y-%m-%d')
            self.snapshot()
            self._timeline_store.capture()
            result=self._timeline_store.collect(selected)
            result['error']=self._timeline_error
            return result
        except Exception as exc:return {'ok':False,'error':'时间轴读取失败：'+str(exc)[:180]}

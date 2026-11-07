"""Background lifecycle/health work never owns the native geometry lock."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
from datetime import datetime,timedelta,timezone
import logging
from pathlib import Path
import re
import threading
import time
import process_control_v11 as control

TZ=timezone(timedelta(hours=8))

class Lifecycle:
    def __init__(self):
        self._lock=threading.RLock();self._pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='SideQuest-control')
        self._stop=threading.Event();self._closing=False;self._pending=0
        self._state={'busy':False,'operation':'','running':False,'workers':{},'error':'','checkedAt':None,'stale':True,
                     'lastSuccess':None,'lastEngineError':'','successSource':'unknown'}
        threading.Thread(target=self._health_loop,daemon=True,name='SideQuest-health').start()

    def snapshot(self):
        with self._lock:return copy.deepcopy(self._state)

    def _engine_status(self):
        path=control.ROOT/'engine/engine_run.log'
        telemetry=control.ROOT/'config/runtime_v11/engine_status.json'
        if telemetry.exists() and (not path.exists() or telemetry.stat().st_mtime>=path.stat().st_mtime):
            try:
                value=json.loads(telemetry.read_text(encoding='utf-8'))
                success=value.get('lastSuccess')
                return {'lastSuccess':datetime.fromtimestamp(success,TZ).isoformat() if isinstance(success,(int,float)) else None,
                        'lastEngineError':str(value.get('lastEngineError') or '')[:160],'successSource':'engine-telemetry',
                        'enginePhase':value.get('phase'),'lastAttempt':value.get('lastAttempt'),'lastFailure':value.get('lastFailure')}
            except (OSError,ValueError,TypeError):pass
        if not path.exists():return {}
        with path.open('rb') as stream:
            stream.seek(max(0,path.stat().st_size-32768));lines=stream.read().decode('utf-8',errors='replace').splitlines()
        anchor=datetime.fromtimestamp(path.stat().st_mtime,TZ);success=None;error=''
        for line in reversed(lines):
            match=re.search(r'\[engine\] (\d\d:\d\d:\d\d) (.*)',line)
            if not match:continue
            message=match[2]
            if success is None and message.startswith(('状态已更新','无变化','内容相同，跳过写入')):
                moment=datetime.combine(anchor.date(),datetime.strptime(match[1],'%H:%M:%S').time(),TZ)
                if moment>anchor+timedelta(seconds=2):moment-=timedelta(days=1)
                success=moment.isoformat()
            if not error and message.startswith('错误:'):
                # Expose an actionable category, never model output, credentials or document contents.
                lower=message.lower()
                error=('模型返回格式不正确' if 'json' in lower or 'parse' in lower else
                       '模型请求超时' if 'timeout' in lower or 'timed out' in lower else
                       '接口认证失败' if '401' in lower or '403' in lower else
                       '接口限流，等待重试' if '429' in lower else '后台识别请求失败，请查看本地日志')
            if success:break
        return {'lastSuccess':success,'lastEngineError':error,'successSource':'engine-log'}

    def refresh(self):
        try:
            records=control.scan();workers={role:[r['pid'] for r in records if r['role']==role] for role in control.WORKERS}
            detail=self._engine_status()
            with self._lock:
                self._state.update(workers=workers,running=all(workers.values()),checkedAt=time.time(),stale=False,
                                   error='检测到重复后台进程' if any(len(ids)>1 for ids in workers.values()) else '',**detail)
        except Exception as exc:
            with self._lock:self._state.update(error=str(exc)[:180],checkedAt=time.time(),stale=True)

    def _health_loop(self):
        while not self._stop.is_set():
            self.refresh();self._stop.wait(10)

    def submit(self,paused,callback=None,closing=False):
        if type(paused) is not bool:return {'ok':False,'error':'后台目标状态不正确'}
        with self._lock:
            if self._closing and not closing:return {'ok':False,'error':'应用正在退出，未恢复后台'}
            if self._pending and not closing:return {'ok':False,'error':'后台正在切换，请稍候'}
            if closing:self._closing=True
            self._pending+=1;self._state.update(busy=True,operation='退出' if closing else '暂停' if paused else '启动')
        def work():
            error=''
            try:
                with self._lock:skip=self._closing and not paused
                if not skip:
                    if paused:control.stop_workers()
                    else:control.start_workers()
            except Exception as exc:error=str(exc)[:180];logging.exception('V11 lifecycle operation failed')
            finally:
                self.refresh()
                with self._lock:
                    self._pending-=1;self._state.update(busy=self._pending>0)
                    if error:self._state['error']=error
                    if closing and error:self._closing=False
                if callback:
                    try:callback(not error,error)
                    except Exception:logging.exception('V11 lifecycle callback failed')
        self._pool.submit(work)
        return {'ok':True,'queued':True,'message':'正在'+('退出' if closing else '暂停后台' if paused else '启动后台')}

    def close(self):
        self._stop.set();self._pool.shutdown(wait=False)

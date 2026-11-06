"""Foreground-window dwell timer. Counts presence, irrespective of keyboard idle."""
import ctypes
from ctypes import wintypes
from datetime import datetime,timedelta
from pathlib import Path
import threading
import time
import uuid
from timeline_v10_4 import TimelineStore as ArchiveStore,TZ


class TimelineStore(ArchiveStore):
    def __init__(self,config):
        super().__init__(config)
        self.config=Path(config)
        self._stop=threading.Event()
        self._row=None
        self._key=None
        self._last_mono=None
        self._last_wall=None
        self._error=''
        with self.lock,self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS dwells(id TEXT PRIMARY KEY,start REAL NOT NULL,end REAL NOT NULL,seconds REAL NOT NULL,title TEXT NOT NULL,exe TEXT NOT NULL,active INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS dwell_time ON dwells(start,end);''')
            # A previous process can have stopped abruptly: never count its unobserved tail.
            db.execute('UPDATE dwells SET active=0 WHERE active=1')
        self._prepare_windows()
        threading.Thread(target=self._monitor,daemon=True,name='SideQuest-window-dwell').start()

    def _prepare_windows(self):
        self.user=ctypes.windll.user32
        self.kernel=ctypes.windll.kernel32
        self.user.GetForegroundWindow.restype=wintypes.HWND
        self.user.GetWindowTextLengthW.argtypes=[wintypes.HWND]
        self.user.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
        self.user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
        self.user.OpenInputDesktop.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        self.user.OpenInputDesktop.restype=wintypes.HANDLE
        self.user.CloseDesktop.argtypes=[wintypes.HANDLE]
        self.kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        self.kernel.OpenProcess.restype=wintypes.HANDLE
        self.kernel.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
        self.kernel.CloseHandle.argtypes=[wintypes.HANDLE]

    def _foreground(self):
        desktop=self.user.OpenInputDesktop(0,False,1)
        if not desktop:return None
        self.user.CloseDesktop(desktop)
        hwnd=self.user.GetForegroundWindow()
        if not hwnd:return None
        size=min(8192,self.user.GetWindowTextLengthW(hwnd)+1)
        title=ctypes.create_unicode_buffer(max(1,size))
        self.user.GetWindowTextW(hwnd,title,max(1,size))
        pid=wintypes.DWORD()
        self.user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        exe=''
        handle=self.kernel.OpenProcess(0x1000,False,pid.value)
        if handle:
            try:
                length=wintypes.DWORD(32768);path=ctypes.create_unicode_buffer(length.value)
                if self.kernel.QueryFullProcessImageNameW(handle,0,path,ctypes.byref(length)):exe=Path(path.value).name
            finally:self.kernel.CloseHandle(handle)
        if exe.lower() in ('lockapp.exe','logonui.exe'):return None
        label=title.value.strip() or exe or '无标题窗口'
        return (int(hwnd),pid.value,label,exe)

    def _close_current(self,db):
        if self._row:db.execute('UPDATE dwells SET active=0 WHERE id=?',(self._row,))
        self._row=None;self._key=None

    def _tick(self):
        wall=time.time();mono=time.monotonic()
        paused=(self.config/'paused').exists()
        window=None if paused else self._foreground()
        elapsed=mono-self._last_mono if self._last_mono is not None else 0
        gap=(self._last_wall is not None and (wall<self._last_wall or wall-self._last_wall>elapsed+8))
        with self.lock,self.connect() as db:
            if self._stop.is_set():return
            if elapsed>6 or gap or paused or window is None:
                self._close_current(db)
            elif self._row:
                db.execute('UPDATE dwells SET end=?,seconds=seconds+? WHERE id=?',(wall,max(0,elapsed),self._row))
            if window is not None and not paused:
                key=window[:3]
                if key!=self._key:
                    self._close_current(db)
                    self._row=uuid.uuid4().hex;self._key=key
                    db.execute('INSERT INTO dwells VALUES(?,?,?,?,?,?,1)',(self._row,wall,wall,0.,window[2],window[3]))
        self._last_mono=mono;self._last_wall=wall

    def _monitor(self):
        while not self._stop.is_set():
            try:self._tick();self._error=''
            except Exception as exc:
                self._error='窗口停留记录暂不可用：'+str(exc)[:140]
                self._last_mono=None;self._last_wall=None
                # Do not bridge an unobserved recording failure with elapsed time later.
                try:
                    with self.lock,self.connect() as db:self._close_current(db)
                except Exception:pass
            self._stop.wait(2)

    def close(self):
        self._stop.set()
        with self.lock,self.connect() as db:self._close_current(db)

    def capture(self):
        # This mode uses the dedicated foreground timer, not historical idle-filtered samples.
        return

    def collect(self,day):
        selected=datetime.strptime(day,'%Y-%m-%d').replace(tzinfo=TZ)
        start=selected.timestamp();end=(selected+timedelta(days=1)).timestamp()
        with self.lock,self.connect() as db:
            records=db.execute('SELECT id,start,end,seconds,title,exe,active FROM dwells WHERE start<? AND end>=? ORDER BY start',(end,start)).fetchall()
            events=db.execute('SELECT id,t,title,kind FROM events WHERE t>=? AND t<? ORDER BY t',(start,end)).fetchall()
        rows=[]
        for rid,begin,finish,seconds,title,exe,active in records:
            clipped_start=max(start,begin);clipped_end=min(end,finish)
            span=finish-begin
            seconds=seconds*max(0,clipped_end-clipped_start)/span if span>0 else 0.
            rows.append({'id':rid,'kind':'activity','start':clipped_start,'end':clipped_end,
                         'seconds':seconds,'title':title,'exe':exe,'active':bool(active and finish<end),'method':'window-dwell'})
        rows.extend({'id':eid,'kind':kind,'start':t,'end':t,'seconds':None,'title':title,'exe':''} for eid,t,title,kind in events)
        rows.sort(key=lambda row:(row['start'],row['kind']))
        return {'ok':True,'day':day,'rows':rows,'totalSeconds':sum(row['seconds'] or 0 for row in rows),
                'completedCount':sum(row['kind']=='completed' for row in rows),'morePending':False,
                'note':(self._error+'。' if self._error else '')+'按前台窗口停留计时，不扣键鼠空闲；约每2秒记录。暂停观察、锁屏和休眠间隔不计。停留计时从V10.5启用起记录，历史采样不混入本统计。'}

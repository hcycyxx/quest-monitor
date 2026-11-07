"""Local timeline archive. Window samples estimate activity; completion stamps stay factual."""
import ctypes
from ctypes import wintypes
import time
import uuid
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone

TZ=timezone(timedelta(hours=8))

def stamp(raw):
    try:
        value=datetime.fromisoformat(str(raw).replace('Z','+00:00'))
        return (value.replace(tzinfo=TZ) if value.tzinfo is None else value.astimezone(TZ)).timestamp()
    except (ValueError,TypeError,OverflowError):return None

def identity(*values):
    return hashlib.sha256(json.dumps(values,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

class ArchiveStore:
    def __init__(self,config):
        self.folder=Path(config)/'timeline_v10_4'
        self.source=Path(config)/'win_log.jsonl'
        self.lock=threading.RLock()
        self.folder.mkdir(parents=True,exist_ok=True)
        ignore=self.folder/'.gitignore'
        if not ignore.exists():
            try:
                with ignore.open('x',encoding='utf-8') as stream:stream.write('*\n')
            except FileExistsError:pass
        self.db=self.folder/'timeline.sqlite3'
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS samples(id TEXT PRIMARY KEY,t REAL NOT NULL,title TEXT NOT NULL,exe TEXT NOT NULL,idle REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS sample_time ON samples(t);
    CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,t REAL NOT NULL,title TEXT NOT NULL,kind TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS event_time ON events(t);
    CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);''')

    @contextmanager
    def connect(self):
        connection=sqlite3.connect(self.db,timeout=5)
        try:
            with connection:yield connection
        finally:connection.close()

    def observe_tasks(self,state):
        with self.lock,self.connect() as db:
            for key in ('main_quests','side_quests'):
                for task in state.get(key,[]) or []:
                    if not isinstance(task,dict):continue
                    title=str(task.get('title') or '未命名任务')
                    fields=[('created',task.get('created_at'))]
                    if task.get('status')=='done':
                        fields.append(('completed',task.get('completed_at') or task.get('completedAt') or task.get('done_at')))
                    for kind,raw in fields:
                        t=stamp(raw)
                        if t is None:continue
                        db.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?)',
                                   (identity(key,task.get('id'),kind,t),t,title,kind))

    def action_event(self,event_id,title,kind):
        with self.lock,self.connect() as db:
            db.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?)',
                       (identity('action',event_id),datetime.now(TZ).timestamp(),str(title),kind))

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
        self._initialize_changes()
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

    def _initialize_changes(self):
        with self.lock,self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''CREATE INDEX IF NOT EXISTS dwell_end_start_v11 ON dwells(end,start);
CREATE TABLE IF NOT EXISTS timeline_serial(singleton INTEGER PRIMARY KEY,value INTEGER NOT NULL);
INSERT OR IGNORE INTO timeline_serial VALUES(1,0);
CREATE TABLE IF NOT EXISTS timeline_dirty(kind TEXT,id TEXT,seq INTEGER NOT NULL,PRIMARY KEY(kind,id));
CREATE INDEX IF NOT EXISTS timeline_dirty_seq ON timeline_dirty(seq);
CREATE TRIGGER IF NOT EXISTS dwell_insert_v11 AFTER INSERT ON dwells BEGIN
UPDATE timeline_serial SET value=value+1 WHERE singleton=1;
INSERT OR REPLACE INTO timeline_dirty VALUES('activity',NEW.id,(SELECT value FROM timeline_serial WHERE singleton=1)); END;
CREATE TRIGGER IF NOT EXISTS dwell_update_v11 AFTER UPDATE ON dwells BEGIN
UPDATE timeline_serial SET value=value+1 WHERE singleton=1;
INSERT OR REPLACE INTO timeline_dirty VALUES('activity',NEW.id,(SELECT value FROM timeline_serial WHERE singleton=1)); END;
CREATE TRIGGER IF NOT EXISTS event_insert_v11 AFTER INSERT ON events BEGIN
UPDATE timeline_serial SET value=value+1 WHERE singleton=1;
INSERT OR REPLACE INTO timeline_dirty VALUES('event',NEW.id,(SELECT value FROM timeline_serial WHERE singleton=1)); END;''')

    @staticmethod
    def _activity(record,start,end):
        rid,begin,finish,seconds,title,exe,active=record
        a,b=max(start,begin),min(end,finish)
        seconds=seconds*max(0,b-a)/(finish-begin) if finish>begin else 0.
        return {'id':rid,'kind':'activity','start':a,'end':b,'seconds':seconds,'title':title,'exe':exe,'active':bool(active and finish<end),'method':'window-dwell'}

    @staticmethod
    def _event(record):
        eid,t,title,kind=record
        return {'id':eid,'kind':kind,'start':t,'end':t,'seconds':None,'title':title,'exe':''}

    def _range(self,day):
        value=datetime.strptime(day,'%Y-%m-%d').replace(tzinfo=TZ)
        return value.timestamp(),(value+timedelta(days=1)).timestamp()

    def _summary(self,db,day,start,end):
        row=db.execute('''SELECT COALESCE(SUM(CASE WHEN end>start THEN seconds*(MIN(end,?)-MAX(start,?))/(end-start) ELSE 0 END),0),
COALESCE(MAX(CASE WHEN end>start THEN seconds*(MIN(end,?)-MAX(start,?))/(end-start) ELSE 0 END),0)
FROM dwells WHERE start<? AND end>=?''',(end,start,end,start,end,start)).fetchone()
        complete=db.execute("SELECT COUNT(*) FROM events WHERE t>=? AND t<? AND kind='completed'",(start,end)).fetchone()[0]
        return {'ok':True,'day':day,'totalSeconds':row[0],'maxSeconds':max(1,row[1]),'completedCount':complete,'morePending':False,
                'note':(self._error+'。' if self._error else '')+'按前台窗口停留计时；约每2秒记录。暂停、锁屏和休眠不计。'}

    def collect(self,day,cursor=None,limit=100):
        start,end=self._range(day);limit=max(1,min(200,int(limit)))
        with self.lock,self.connect() as db:
            db.execute('BEGIN')
            watermark=db.execute('SELECT value FROM timeline_serial WHERE singleton=1').fetchone()[0]
            sql='''WITH items AS (
SELECT id,'activity' AS kind,MAX(start,?) AS t,end,seconds,title,exe,active,start AS original_start FROM dwells WHERE start<? AND end>=?
UNION ALL SELECT id,kind,t,t,NULL,title,'',0,t FROM events WHERE t>=? AND t<?)
SELECT * FROM items'''
            params=[start,end,start,start,end]
            if cursor:
                t=float(cursor['t']);rid=str(cursor['id'])
                sql+=' WHERE t<? OR (t=? AND id<?)';params.extend([t,t,rid])
            sql+=' ORDER BY t DESC,id DESC LIMIT ?';params.append(limit+1)
            values=db.execute(sql,params).fetchall();more=len(values)>limit;values=values[:limit];rows=[]
            for rid,kind,t,finish,seconds,title,exe,active,original in values:
                if kind=='activity':rows.append(self._activity((rid,original,finish,seconds,title,exe,active),start,end))
                else:rows.append(self._event((rid,t,title,kind)))
            result=self._summary(db,day,start,end)
        result.update(rows=rows,watermark=watermark,hasMore=more,nextCursor={'t':rows[-1]['start'],'id':rows[-1]['id']} if rows else None)
        return result

    def delta(self,day,since):
        start,end=self._range(day);since=max(0,int(since))
        with self.lock,self.connect() as db:
            db.execute('BEGIN');current=db.execute('SELECT value FROM timeline_serial WHERE singleton=1').fetchone()[0]
            changes=db.execute('SELECT kind,id,seq FROM timeline_dirty WHERE seq>? ORDER BY seq LIMIT 501',(since,)).fetchall()
            more=len(changes)>500;changes=changes[:500];rows=[]
            for kind,rid,seq in changes:
                if kind=='activity':
                    record=db.execute('SELECT id,start,end,seconds,title,exe,active FROM dwells WHERE id=? AND start<? AND end>=?',(rid,end,start)).fetchone()
                    if record:rows.append(self._activity(record,start,end))
                else:
                    record=db.execute('SELECT id,t,title,kind FROM events WHERE id=? AND t>=? AND t<?',(rid,start,end)).fetchone()
                    if record:rows.append(self._event(record))
            result=self._summary(db,day,start,end)
        result.update(rows=rows,watermark=changes[-1][2] if more and changes else current,hasMoreChanges=more)
        return result

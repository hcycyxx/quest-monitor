"""Local timeline archive. Window samples estimate activity; completion stamps stay factual."""
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

class TimelineStore:
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

    def capture(self):
        """Incremental bounded import; store no OCR text, file contents or credentials."""
        if not self.source.exists():return
        with self.lock,self.connect() as db:
            meta=dict(db.execute('SELECT key,value FROM meta'))
            offset=int(meta.get('offset','0'));boundary=meta.get('boundary','')
            with self.source.open('rb') as source:
                size=self.source.stat().st_size
                if offset>size:offset=0
                if offset:
                    source.seek(max(0,offset-64))
                    if source.read(min(64,offset)).hex()!=boundary:offset=0
                source.seek(offset);limit=offset+4*1024*1024
                while source.tell()<limit:
                    begin=source.tell();line=source.readline(1024*1024)
                    if not line:break
                    if not line.endswith(b'\n'):
                        if len(line)<1024*1024:source.seek(begin);break
                        while line and not line.endswith(b'\n'):line=source.readline(1024*1024)
                        continue
                    try:
                        record=json.loads(line)
                        t=stamp(record.get('t'));title=str(record.get('title') or '').strip();exe=str(record.get('exe') or '')
                        idle=float(record.get('idle_s') or 0)
                        if t is None or not title or not math.isfinite(idle):continue
                        if title.startswith(('SideQuest','任务追踪')) and exe.lower() in ('python.exe','pythonw.exe'):continue
                        db.execute('INSERT OR IGNORE INTO samples VALUES(?,?,?,?,?)',(identity(t,title,exe),t,title,exe,max(0,idle)))
                    except (ValueError,TypeError,AttributeError):continue
                offset=source.tell();source.seek(max(0,offset-64));boundary=source.read(min(64,offset)).hex()
            db.executemany('INSERT OR REPLACE INTO meta VALUES(?,?)',[('offset',str(offset)),('boundary',boundary)])

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

    def collect(self,day):
        selected=datetime.strptime(day,'%Y-%m-%d').replace(tzinfo=TZ)
        start=selected.timestamp();end=(selected+timedelta(days=1)).timestamp()
        with self.lock,self.connect() as db:
            samples=db.execute('SELECT t,title,exe,idle FROM samples WHERE t>=? AND t<? ORDER BY t,id',(start,end)).fetchall()
            events=db.execute('SELECT id,t,title,kind FROM events WHERE t>=? AND t<? ORDER BY t',(start,end)).fetchall()
            offset=int(dict(db.execute('SELECT key,value FROM meta')).get('offset','0'))
        rows=[];segment=None
        def flush():
            nonlocal segment
            if segment:rows.append(segment);segment=None
        for index,sample in enumerate(samples):
            t,title,exe,idle=sample
            next_sample=samples[index+1] if index+1<len(samples) else None
            gap=next_sample[0]-t if next_sample else None
            eligible=(idle<60 and next_sample is not None and next_sample[3]<60 and 0<gap<=90)
            if not eligible:
                if gap==0:continue
                covered=segment and segment['title']==title and segment['exe']==exe and abs(segment['end']-t)<.01
                flush()
                if idle<60 and not covered:rows.append({'id':identity('point',t,title,exe),'kind':'activity','start':t,'end':None,'seconds':None,'title':title,'exe':exe})
                continue
            if segment and segment['title']==title and segment['exe']==exe and abs(segment['end']-t)<.01:
                segment['end']=next_sample[0];segment['seconds']+=gap
            else:
                flush();segment={'id':identity('session',t,title,exe),'kind':'activity','start':t,'end':next_sample[0],'seconds':gap,'title':title,'exe':exe}
        flush()
        rows.extend({'id':eid,'kind':kind,'start':t,'end':t,'seconds':None,'title':title,'exe':''} for eid,t,title,kind in events)
        rows.sort(key=lambda row:(row['start'],row['kind']))
        more=self.source.exists() and self.source.stat().st_size>offset
        return {'ok':True,'day':day,'rows':rows,'totalSeconds':sum(row['seconds'] or 0 for row in rows),
                'completedCount':sum(row['kind']=='completed' for row in rows),'morePending':more,
                'note':'活动时长按窗口采样估算，空闲或记录间断不补计；单次采样不推算时长。任务完成时间来自已保存记录。'}

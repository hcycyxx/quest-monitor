"""Verified process control: one scan, pinned handles, project-wide serialization."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import paths
import state_store as store

ROOT=Path(paths.PROGRAM_DIR)
PAUSE_FLAG=paths.config('paused')
PIDFILE=paths.config('workers.json')
BASE_PYTHON=Path(sys.base_prefix)/'python.exe'
WORKERS={'win_watch':str(ROOT/'engine/win_watch.py'),'llm_engine':str(ROOT/'engine/llm_engine_v11.py')}
PANEL=str(ROOT/'sidequest_latest.py')
CREATE_NO_WINDOW=0x08000000
_K=ctypes.windll.kernel32
_K.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];_K.OpenProcess.restype=wintypes.HANDLE
_K.CloseHandle.argtypes=[wintypes.HANDLE]
_K.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
_K.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
_K.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]
_K.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR];_K.CreateMutexW.restype=wintypes.HANDLE
_K.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];_K.WaitForSingleObject.restype=wintypes.DWORD
_K.ReleaseMutex.argtypes=[wintypes.HANDLE]
_S=ctypes.windll.shell32
_S.CommandLineToArgvW.argtypes=[wintypes.LPCWSTR,ctypes.POINTER(ctypes.c_int)]
_S.CommandLineToArgvW.restype=ctypes.POINTER(wintypes.LPWSTR)
_K.LocalFree.argtypes=[ctypes.c_void_p]

def _norm(value):return os.path.normcase(os.path.abspath(str(value))).replace('/','\\')
def is_paused():return Path(PAUSE_FLAG).exists()
def set_paused(value):
    path=Path(PAUSE_FLAG)
    if value:path.write_text(str(int(time.time())),encoding='utf-8')
    else:path.unlink(missing_ok=True)

@contextmanager
def control_lock():
    name='Local\\SideQuestControl_'+hashlib.sha256(_norm(ROOT).encode()).hexdigest()[:20]
    handle=_K.CreateMutexW(None,False,name)
    if not handle:raise OSError('无法建立后台控制锁')
    acquired=False
    try:
        code=_K.WaitForSingleObject(handle,15000)
        if code not in (0,0x80):raise TimeoutError('另一个后台启停操作尚未结束')
        acquired=True;yield
    finally:
        if acquired:_K.ReleaseMutex(handle)
        _K.CloseHandle(handle)

def _argv(command):
    count=ctypes.c_int();pointer=_S.CommandLineToArgvW(command,ctypes.byref(count))
    if not pointer:return []
    try:return [pointer[i] for i in range(count.value)]
    finally:_K.LocalFree(pointer)

def _role(arguments):
    entry=None
    for argument in arguments[1:]:
        if argument in ('-u','-I','-B','-E','-s','-S'):continue
        entry=_norm(argument) if str(argument).lower().endswith('.py') else None
        break
    scripts={entry} if entry else set()
    for role in WORKERS:
        allowed={_norm(ROOT/'engine'/f'{role}.py'),_norm(ROOT/'engine'/f'{role}_v11.py')}
        if scripts&allowed:return role
    for script in scripts:
        path=Path(script)
        if _norm(path.parent)==_norm(ROOT):
            if path.name.lower() in ('sidequest_latest.py','sidequest.py','sidequest_legacy_v9.py') and '--panel' in arguments:return 'panel'
            if re.fullmatch(r'sidequest_v\d+(?:_\d+)*\.py',path.name,re.I):return 'panel'
        if _norm(path.parent)==_norm(ROOT/'ui') and re.fullmatch(r'(?:quest_window(?:_v\d+(?:_\d+)*)?|app_v\d+)\.py',path.name,re.I):return 'panel'
    return None

def _inspect(handle):
    created,ended,kernel,user=(wintypes.FILETIME() for _ in range(4))
    if not _K.GetProcessTimes(handle,*[ctypes.byref(v) for v in (created,ended,kernel,user)]):return None
    capacity=wintypes.DWORD(32768);name=ctypes.create_unicode_buffer(capacity.value)
    if not _K.QueryFullProcessImageNameW(handle,0,name,ctypes.byref(capacity)):return None
    return {'created':(created.dwHighDateTime<<32)|created.dwLowDateTime,'exe':_norm(name.value)}

def scan():
    script="""[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); @(Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | Select-Object ProcessId,ExecutablePath,CommandLine,@{Name='CreatedTicks';Expression={$_.CreationDate.ToFileTimeUtc()}}) | ConvertTo-Json -Compress"""
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],
                          capture_output=True,encoding='utf-8',errors='replace',timeout=7,creationflags=CREATE_NO_WINDOW)
    if result.returncode:raise RuntimeError('无法核对后台进程身份，未执行强制启停')
    rows=json.loads(result.stdout.strip() or '[]');rows=[rows] if isinstance(rows,dict) else rows
    known={_norm(BASE_PYTHON),_norm(BASE_PYTHON.with_name('pythonw.exe')),_norm(sys.executable)}
    records=[]
    for row in rows:
        if not isinstance(row,dict) or not row.get('CommandLine'):continue
        arguments=_argv(row['CommandLine']);role=_role(arguments)
        if not role:continue
        if not row.get('ExecutablePath') or _norm(row['ExecutablePath']) not in known:
            raise RuntimeError('检测到本项目进程，但运行路径未核验，未自动启停')
        pid=int(row['ProcessId'])
        if pid==os.getpid():continue
        if role=='panel' and pid==os.getppid():continue
        handle=_K.OpenProcess(0x1000,False,pid)
        if not handle:continue
        try:identity=_inspect(handle)
        finally:_K.CloseHandle(handle)
        # CIM rounds creation stamps to microseconds. Refuse mismatches and missing stamps.
        expected=row.get('CreatedTicks')
        if not identity or type(expected) is not int or abs(identity['created']-expected)>10:
            raise RuntimeError('进程创建时间发生变化或无法核验，未自动启停')
        if identity['exe']!=_norm(row['ExecutablePath']):raise RuntimeError('进程身份发生变化，未自动启停')
        records.append({'pid':pid,'role':role,**identity})
    return records

def _terminate(record):
    handle=_K.OpenProcess(0x1001,False,int(record['pid']))
    if not handle:return False
    try:
        current=_inspect(handle)
        if not current or current['created']!=record['created'] or current['exe']!=record['exe']:return False
        if not _K.TerminateProcess(handle,0):raise OSError('无法停止已核验的后台进程')
        return True
    finally:_K.CloseHandle(handle)

def _load_pids():
    try:
        value=json.loads(Path(PIDFILE).read_text(encoding='utf-8'));return value if isinstance(value,dict) else {}
    except (OSError,ValueError):return {}
def _save_pids(values):store._atomic_write(Path(PIDFILE),values)
def _spawn_args(name):return [str(BASE_PYTHON),WORKERS[name]]
def _discover(name):return [r['pid'] for r in scan() if r['role']==('panel' if name=='quest_window' else name)]
def _kill(pid):
    record=next((r for r in scan() if r['pid']==int(pid) and r['role'] in WORKERS),None)
    return _terminate(record) if record else False
def _pid_alive(pid):
    return any(r['pid']==int(pid) for r in scan()) if pid else False

def status():
    records=scan()
    return {role:next((r['pid'] for r in records if r['role']==role),None) for role in WORKERS}
def is_running():return any(status().values())

def start_workers():
    with control_lock():
        records=scan();result={};started=[]
        try:
            for role in WORKERS:
                present=sorted([r for r in records if r['role']==role],key=lambda r:r['created'])
                if present:result[role]=present[0]['pid'];continue
                process=subprocess.Popen(_spawn_args(role),cwd=ROOT,creationflags=CREATE_NO_WINDOW,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                started.append(process);result[role]=process.pid
            _save_pids(result);set_paused(False)
            return result
        except Exception:
            # Only handles for children started by this operation are eligible for rollback.
            for process in started:
                if process.poll() is None:process.terminate()
            raise

def stop_workers():
    with control_lock():
        records=scan();set_paused(True);stopped=[]
        for record in records:
            if record['role'] in WORKERS and _terminate(record):stopped.append((record['role'],record['pid']))
        _save_pids({});return stopped
def toggle():
    if is_paused():start_workers();return False
    stop_workers();return True

def start_panel(replace=False):
    with control_lock():
        panels=[r for r in scan() if r['role']=='panel']
        if panels and not replace:return None
        for record in panels:_terminate(record)
        runtime=Path(os.environ['LOCALAPPDATA'])/'SideQuestV10Runtime/Scripts/pythonw.exe'
        if not runtime.exists():raise RuntimeError('桌面运行环境尚未安装')
        return subprocess.Popen([str(runtime),PANEL,'--panel'],cwd=ROOT,creationflags=CREATE_NO_WINDOW).pid

"""Frozen-process support, portable data and in-EXE settings. Source runtime is untouched."""
import ctypes
from datetime import datetime,timezone,timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

def configure(home):
    import paths
    import process_control_v11 as control
    import service_lifecycle_v11 as lifecycle
    import bridge_core
    home=Path(home).resolve();executable=Path(sys.executable).resolve()
    control.ROOT=home;control.BASE_PYTHON=executable
    def role(arguments):
        if '--home' not in arguments and '--worker' not in arguments and '--settings' not in arguments:return 'panel'
        try:
            index=arguments.index('--home');candidate=Path(arguments[index+1]).resolve()
            if control._norm(candidate)!=control._norm(home):return None
        except (ValueError,IndexError,OSError):return None
        if '--worker' in arguments:
            index=arguments.index('--worker')
            return arguments[index+1] if index+1<len(arguments) and arguments[index+1] in control.WORKERS else None
        return None if '--settings' in arguments else 'panel'
    def scan():
        environment=os.environ.copy();environment['SIDEQUEST_PROCESS_NAME']=executable.name
        script="[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); @(Get-CimInstance Win32_Process | Where-Object {$_.Name -eq $env:SIDEQUEST_PROCESS_NAME} | Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine,@{Name='CreatedTicks';Expression={$_.CreationDate.ToFileTimeUtc()}}) | ConvertTo-Json -Compress"
        result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],env=environment,capture_output=True,encoding='utf-8',errors='replace',timeout=8,creationflags=control.CREATE_NO_WINDOW)
        if result.returncode:raise RuntimeError('无法核对便携后台，未执行强制启停')
        rows=json.loads(result.stdout.strip() or '[]');rows=[rows] if isinstance(rows,dict) else rows;records=[]
        for row in rows:
            if not row.get('CommandLine') or not row.get('ExecutablePath'):continue
            if control._norm(row['ExecutablePath'])!=control._norm(executable):continue
            which=role(control._argv(row['CommandLine']))
            if not which:continue
            pid=int(row['ProcessId'])
            if pid==os.getpid():continue
            handle=control._K.OpenProcess(0x1000,False,pid)
            if not handle:continue
            try:identity=control._inspect(handle)
            finally:control._K.CloseHandle(handle)
            expected=row.get('CreatedTicks')
            if not identity or type(expected) is not int or abs(identity['created']-expected)>10:raise RuntimeError('便携后台身份发生变化，未自动启停')
            records.append({'pid':pid,'parent':int(row.get('ParentProcessId') or 0),'role':which,**identity})
        parents={record['parent'] for record in records}
        return [record for record in records if record['pid'] not in parents]
    control.scan=scan
    control._spawn_args=lambda name:[str(executable),'--worker',name,'--home',str(home)]
    def start_panel(replace=False):
        with control.control_lock():
            panels=[record for record in scan() if record['role']=='panel']
            if panels and not replace:return None
            for record in panels:control._terminate(record)
            return subprocess.Popen([str(executable),'--panel','--home',str(home)],cwd=home,creationflags=control.CREATE_NO_WINDOW).pid
    control.start_panel=start_panel
    def engine_status(self):
        path=Path(paths.CONFIG_DIR)/'runtime_v11/engine_status.json';data={}
        try:data=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError,TypeError):pass
        success=data.get('lastSuccess');phase=data.get('phase');failure=str(data.get('lastEngineError') or '')[:160]
        for name in ('win_watch','llm_engine'):
            try:
                worker=json.loads(Path(paths.config('runtime_v11/worker_'+name+'.json')).read_text(encoding='utf-8'))
                if worker.get('phase') in ('failed','stopped') and time.time()-worker.get('updatedAt',0)<120:
                    failure=('窗口监测' if name=='win_watch' else '任务识别')+'后台未就绪：'+str(worker.get('error') or worker['phase'])[:140];phase='error'
                elif worker.get('phase')=='starting' and not phase:phase='starting'
            except (OSError,ValueError,TypeError):pass
        return {'lastSuccess':datetime.fromtimestamp(success,timezone(timedelta(hours=8))).isoformat() if isinstance(success,(int,float)) else None,
                'lastEngineError':failure,'successSource':'engine-telemetry','enginePhase':phase,'lastAttempt':data.get('lastAttempt'),'lastFailure':data.get('lastFailure')}
    lifecycle.Lifecycle._engine_status=engine_status
    def detail(self):
        try:
            if self._settings_process and self._settings_process.poll() is None:return {'ok':True}
            self._settings_process=subprocess.Popen([str(executable),'--settings','--home',str(home)],cwd=home,creationflags=control.CREATE_NO_WINDOW)
            return {'ok':True}
        except OSError as exc:return {'ok':False,'error':'设置打开失败：'+str(exc)}
    bridge_core.Bridge.open_detail_settings=detail
    original_pause=bridge_core.Bridge.pause
    def pause(self,paused):
        if not paused:
            config=self._data/'llm.json'
            try:data=json.loads(config.read_text(encoding='utf-8'))
            except (OSError,ValueError):data={}
            if not data.get('base_url') or not data.get('api_key'):
                detail(self)
                return {'ok':False,'error':'请先填写这台电脑本地接口的地址和密钥，保存后点击启动'}
        return original_pause(self,paused)
    bridge_core.Bridge.pause=pause

def open_settings():
    import tkinter as tk
    import paths
    from settings_window import SettingsWindow,palette_from
    palettes={
      'glass':{'bg':'#14171f','hi':'#232a38','text':'#f1f5fc','muted':'#a8b7cc','gold':'#ffd166','cyan':'#7de3f4','green':'#5be3a2','family':'Microsoft YaHei UI'},
      'transparent':{'bg':'#182330','hi':'#2b3c4e','text':'#ffffff','muted':'#cfdaea','gold':'#ffe1a0','cyan':'#b3efff','green':'#92efc3','family':'Microsoft YaHei UI'},
      'journal':{'bg':'#f4efe3','hi':'#eae1ce','text':'#342e29','muted':'#6b6054','gold':'#96623b','cyan':'#396c73','green':'#3c7052','family':'SimSun'},
      'night':{'bg':'#101b25','hi':'#1c2e3c','text':'#edf8ff','muted':'#abc4d6','gold':'#8ae8ff','cyan':'#c0b3ff','green':'#68edb8','family':'Microsoft YaHei UI'}}
    try:prefs=json.loads(Path(paths.config('ui_v10.json')).read_text(encoding='utf-8'))
    except (OSError,ValueError):prefs={}
    root=tk.Tk();root.withdraw();asked=[False]
    def saved(config,ui):
        if asked[0] or not config.get('api_key'):return
        asked[0]=True
        from tkinter import messagebox
        if not messagebox.askyesno('启动识别','配置已保存。现在启动后台开始识别窗口任务吗？',parent=window.top):return
        def start():
            try:
                import process_control_v11
                process_control_v11.start_workers()
                window._results.put(('startup',None,None))
            except Exception as exc:window._results.put(('startup',None,'后台未启动：'+str(exc)[:160]))
        threading.Thread(target=start,daemon=False).start()
    window=SettingsWindow(root,palette_from(palettes.get(prefs.get('skin'),palettes['glass'])),on_saved=saved)
    def labels(parent):
        for child in parent.winfo_children():
            if isinstance(child,tk.Label) and child.cget('text')=='本地网关随便填；云端服务要填真 key':
                child.configure(text='请填写目标电脑本地接口要求的密钥；便携包不带出原电脑密钥')
            labels(child)
    labels(window.top)
    window.top.bind('<Destroy>',lambda event:root.quit() if event.widget is window.top else None)
    root.mainloop();root.destroy()

"""Installed EXE: fixed user-local runtime and separate persistent data directory."""
import ctypes
import json
import os
from pathlib import Path
import sys
import threading
import time

def main():
    home=Path(sys.executable).parent.resolve()
    arguments=list(sys.argv[1:])
    if '--home' in arguments:
        index=arguments.index('--home')
        if index+1>=len(arguments) or Path(arguments[index+1]).resolve()!=home:raise ValueError('后台所属安装目录不一致')
        del arguments[index:index+2]
    data=Path(os.environ['LOCALAPPDATA'])/'SideQuestDesktop/data'
    os.environ['SIDEQUEST_HOME']=str(data)
    import paths
    paths.ensure_dirs()
    from installed_adapter import configure,open_settings
    configure(home)
    if arguments[:1]==['--worker']:
        role=arguments[1] if len(arguments)>1 else ''
        if role not in ('win_watch','llm_engine'):raise ValueError('后台名称不正确')
        import state_store
        folder=Path(paths.CONFIG_DIR)/'runtime_v11';folder.mkdir(parents=True,exist_ok=True)
        state={'pid':os.getpid(),'role':role,'phase':'starting','startedAt':time.time(),'updatedAt':time.time(),'error':''}
        status=folder/('worker_'+role+'.json');stop=threading.Event();lock=threading.Lock()
        def write():
            with lock:
                state['updatedAt']=time.time();state_store._atomic_write(status,dict(state))
        def pulse():
            while not stop.wait(5):
                try:write()
                except OSError:pass
        write();threading.Thread(target=pulse,daemon=True).start()
        try:
            if role=='win_watch':
                import win_watch
                original=win_watch.is_self
                win_watch.is_self=lambda window:original(window) or ((window.get('exe') or '').lower()==home.joinpath('SideQuest.exe').name.lower() and (window.get('title') or '').startswith('SideQuest'))
                run=win_watch.main
            else:
                import llm_engine_v11
                run=llm_engine_v11.main
            with lock:state['phase']='running'
            write();run()
            with lock:state.update(phase='stopped',error='后台已结束，请查看本地日志和连接配置')
            write()
        except Exception as exc:
            with lock:state.update(phase='failed',error=type(exc).__name__+': '+str(exc)[:160])
            write();raise
        finally:stop.set()
        return 0
    if arguments[:1]==['--settings']:open_settings();return 0
    import bridge_core
    bridge_core.ROOT=Path(sys._MEIPASS)
    import installed_app_v11
    return installed_app_v11.main()

if __name__=='__main__':
    try:
        import multiprocessing
        multiprocessing.freeze_support()
        if sys.stdout is None:sys.stdout=open(os.devnull,'w',encoding='utf-8')
        if sys.stderr is None:sys.stderr=open(os.devnull,'w',encoding='utf-8')
        raise SystemExit(main())
    except Exception as exc:
        import traceback
        try:
            folder=Path(os.environ['LOCALAPPDATA'])/'SideQuestDesktop/data/logs';folder.mkdir(parents=True,exist_ok=True)
            with (folder/'installed_error.log').open('a',encoding='utf-8') as stream:stream.write(traceback.format_exc()+'\n')
        except OSError:pass
        if '--worker' not in sys.argv:
            ctypes.windll.user32.MessageBoxW(None,str(exc),'SideQuest 启动失败',0x10)
        raise SystemExit(1)

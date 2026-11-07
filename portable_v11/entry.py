"""Portable executable entry. No source checkout, Python install or user secrets required."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import winreg

NO_WINDOW=0x08000000

def message(text,title='SideQuest 便携版',flags=0):
    return ctypes.windll.user32.MessageBoxW(None,str(text),title,flags)

def home_argument():
    arguments=list(sys.argv[1:])
    if '--home' in arguments:
        index=arguments.index('--home')
        if index+1>=len(arguments):raise ValueError('便携数据目录参数不完整')
        home=Path(arguments[index+1]).resolve();del arguments[index:index+2]
    else:home=Path(os.environ.get('SIDEQUEST_PORTABLE_HOME') or Path(sys.executable).parent).resolve()
    return home,arguments

def trusted_cache(home,args):
    """Run managed DLLs from a standard local cache, not a downloaded ZIP/Desktop zone."""
    bundle=Path(sys._MEIPASS)
    metadata=json.loads((bundle/'portable/meta.json').read_text(encoding='utf-8'))
    key=metadata['build_id']+'_'+hashlib.sha256(str(home).lower().encode()).hexdigest()[:12]
    root=Path(os.environ['LOCALAPPDATA'])/'SideQuestPortableRuntime'
    target=root/key
    if Path(sys.executable).parent.resolve()==target.resolve():return False
    root.mkdir(parents=True,exist_ok=True)
    kernel=ctypes.windll.kernel32
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR];kernel.CreateMutexW.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.ReleaseMutex.argtypes=[wintypes.HANDLE];kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.CreateMutexW(None,False,'Local\\SideQuestPortableCache_'+key)
    if not handle:raise RuntimeError('无法建立便携组件准备锁')
    acquired=False
    try:
        if kernel.WaitForSingleObject(handle,120000) not in (0,0x80):raise RuntimeError('正在准备运行组件，请稍后再打开')
        acquired=True
        marker=target/'ready.json'
        if not marker.exists():
            stage=root/(key+'.preparing_'+uuid.uuid4().hex[:8])
            if stage.resolve().parent!=root.resolve() or target.resolve().parent!=root.resolve():raise ValueError('运行目录不正确')
            stage.mkdir(exist_ok=False)
            shutil.copyfile(sys.executable,stage/Path(sys.executable).name)
            shutil.copytree(bundle,stage/'_internal')
            (stage/'ready.json').write_text(json.dumps(metadata),encoding='utf-8')
            stage.rename(target)
        executable=target/Path(sys.executable).name
        if not executable.exists():raise RuntimeError('便携运行目录不完整，请重新解压便携包')
        subprocess.Popen([str(executable),*args,'--home',str(home)],cwd=home,creationflags=NO_WINDOW)
        return True
    finally:
        if acquired:kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)

def has_framework():
    for view in (winreg.KEY_WOW64_64KEY,winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full',0,winreg.KEY_READ|view) as key:
                if int(winreg.QueryValueEx(key,'Release')[0])>=528040:return True
        except (OSError,TypeError,ValueError):pass
    return False

def has_webview():
    guid='{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY,winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive,'SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\'+guid,0,winreg.KEY_READ|view) as key:
                    if int(str(winreg.QueryValueEx(key,'pv')[0]).split('.')[0])>=86:return True
            except (OSError,ValueError,TypeError):pass
    candidates=[Path(os.environ.get('PROGRAMFILES(X86)','C:/Program Files (x86)'))/'Microsoft/EdgeWebView/Application',
                Path(os.environ['LOCALAPPDATA'])/'Microsoft/EdgeWebView/Application']
    return any(any(root.glob('*/msedgewebview2.exe')) for root in candidates if root.exists())

def prerequisites(home):
    checks=[(has_framework,'.NET Framework 4.8','NDP48-x86-x64-AllOS-ENU.exe',['/passive','/norestart']),
            (has_webview,'Microsoft WebView2','MicrosoftEdgeWebView2RuntimeInstallerX64.exe',['/silent','/install'])]
    for check,label,name,args in checks:
        if check():continue
        installer=home/'运行组件'/name
        if not installer.exists():raise RuntimeError('缺少'+label+'，请保留“运行组件”文件夹并重新打开')
        if message('这台电脑缺少 '+label+'。\n是否安装随包提供的微软官方组件？安装后可继续使用。',flags=0x24)!=6:return False
        result=subprocess.run([str(installer),*args],cwd=home)
        if result.returncode==3010:
            message(label+' 已安装，请重启 Windows 后再打开 SideQuest。');return False
        if result.returncode not in (0,1638) or not check():raise RuntimeError(label+' 安装未完成，请手动运行“运行组件”中的安装程序')
    return True

def main():
    if not getattr(sys,'frozen',False):raise RuntimeError('此入口只用于便携版打包')
    home,args=home_argument()
    if trusted_cache(home,args):return 0
    os.environ['SIDEQUEST_HOME']=str(home/'data')
    os.environ['SIDEQUEST_PORTABLE_HOME']=str(home)
    import paths
    paths.ensure_dirs()
    from portable_adapter import configure,open_settings
    configure(home)
    if args[:1]==['--worker']:
        if len(args)<2:raise ValueError('缺少后台名称')
        if args[1]=='win_watch':
            import win_watch
            original=win_watch.is_self
            win_watch.is_self=lambda window:original(window) or ((window.get('exe') or '').lower()==Path(sys.executable).name.lower() and (window.get('title') or '').startswith('SideQuest'))
            win_watch.main()
        elif args[1]=='llm_engine':
            import llm_engine_v11
            llm_engine_v11.main()
        else:raise ValueError('后台名称不正确')
        return 0
    if args[:1]==['--settings']:open_settings();return 0
    if not prerequisites(home):return 0
    import bridge_core
    bridge_core.ROOT=Path(sys._MEIPASS)
    import portable_app_v11
    return portable_app_v11.main()

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
            folder=Path(os.environ.get('SIDEQUEST_HOME') or Path(sys.executable).parent/'data')/'logs'
            folder.mkdir(parents=True,exist_ok=True)
            with (folder/'portable_error.log').open('a',encoding='utf-8') as stream:stream.write(traceback.format_exc()+'\n')
        except OSError:pass
        message(str(exc),flags=0x10)
        raise SystemExit(1)

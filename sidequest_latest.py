"""Stable entry. Historical release files remain available for explicit rollback."""
import ctypes
import importlib
import json
import logging
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'ui'),str(ROOT/'engine')]

def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    import process_control_v11 as control
    if args[:1]==['--replace-panel']:
        control.start_panel(replace=True);return 0
    if args[:1]==['--worker']:
        name=args[1] if len(args)>1 else ''
        if name=='win_watch':importlib.import_module('win_watch').main()
        elif name=='llm_engine':importlib.import_module('llm_engine_v11').main()
        else:raise ValueError('后台名称不正确')
        return 0
    if args[:1]==['--summary']:
        print(importlib.import_module('daily_summary').build());return 0
    if args[:1]!=['--panel']:
        control.start_panel();return 0
    manifest=json.loads((ROOT/'ui/current_release.json').read_text(encoding='utf-8'))
    module=manifest.get('app','')
    if not re.fullmatch(r'app_v\d+',module):raise ValueError('最新界面入口格式不正确')
    return importlib.import_module(module).main()

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        logging.basicConfig(filename=ROOT/'engine/panel_latest_error.log',level=logging.INFO,encoding='utf-8')
        logging.exception('Latest SideQuest entry failed')
        ctypes.windll.user32.MessageBoxW(None,str(exc),'SideQuest 启动失败',0x10)
        raise SystemExit(1)

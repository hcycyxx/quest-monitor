"""Compatibility facade for verified V11 process control. V9 retained separately."""
import process_control_v11 as _control
for _name in dir(_control):
    if not _name.startswith('__'):globals()[_name]=getattr(_control,_name)
if __name__ == '__main__':
    import sys
    _action=sys.argv[1] if len(sys.argv)>1 else 'status'
    if _action=='pause':print('killed',stop_workers())
    elif _action=='resume':print('started',start_workers())
    elif _action=='toggle':print('paused' if toggle() else 'running')
    elif _action=='panel':print('panel',start_panel())
    else:print('paused' if is_paused() else 'running',status())

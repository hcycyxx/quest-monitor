"""Original inference behavior, with explicit success/error telemetry on normal requests."""
from pathlib import Path
import time
import llm_engine as engine
import paths
import state_store as store

def main():
    folder=Path(paths.CONFIG_DIR)/'runtime_v11';folder.mkdir(parents=True,exist_ok=True)
    ignore=folder/'.gitignore'
    if not ignore.exists():
        with ignore.open('x',encoding='utf-8') as stream:stream.write('*\n')
    path=folder/'engine_status.json'
    state={};original=engine.log
    def log(message):
        original(message)
        if message.startswith(('状态已更新','无变化','内容相同，跳过写入')):
            state.update(lastSuccess=time.time(),lastEngineError='')
        elif message.startswith('错误:'):
            state.update(lastFailure=time.time(),lastEngineError='后台请求失败，正在按既有规则等待重试')
        else:return
        try:store._atomic_write(path,state)
        except OSError:pass
    engine.log=log
    engine.main_loop()

if __name__=='__main__':main()

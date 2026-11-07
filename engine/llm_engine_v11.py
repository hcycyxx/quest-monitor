"""Original inference behavior, with explicit success/error telemetry on normal requests."""
from pathlib import Path
import time
import llm_engine_runtime_v11_2 as engine
import paths
import state_store as store

def main():
    folder=Path(paths.CONFIG_DIR)/'runtime_v11';folder.mkdir(parents=True,exist_ok=True)
    ignore=folder/'.gitignore'
    if not ignore.exists():
        with ignore.open('x',encoding='utf-8') as stream:stream.write('*\n')
    path=folder/'engine_status.json'
    state={'phase':'starting'};original=engine.log
    def log(message):
        original(message)
        if message.startswith(('状态已更新','无变化','内容相同，跳过写入')):
            state.update(lastSuccess=time.time(),lastEngineError='',phase='idle')
        elif message.startswith('提交原因：'):
            state.update(lastAttempt=time.time(),phase='analyzing')
        elif message.startswith('错误:'):
            lower=message.lower()
            reason=('当前模型返回空内容，请更换能稳定输出JSON的模型' if '空内容' in message else
                    '模型输出被截断，请调整输出上限或更换模型' if '截断' in message else
                    '接口认证失败，请核对密钥' if '401' in lower or '403' in lower else
                    '接口或模型未找到，请核对地址和模型名称' if '404' in lower else
                    '接口限流，正在等待重试' if '429' in lower else
                    '模型请求超时，正在等待重试' if 'timed out' in lower or 'timeout' in lower else
                    '模型返回格式不符合任务JSON要求' if 'json' in lower or 'boolean changed' in lower else
                    '后台识别失败：'+message.split(':',2)[1].strip()[:60])
            state.update(lastFailure=time.time(),lastEngineError=reason,phase='error')
        elif message.startswith('连接配置已变化'):
            state.update(phase='waiting',lastEngineError='')
        else:return
        try:store._atomic_write(path,state)
        except OSError:pass
    engine.log=log
    engine.main_loop()

if __name__=='__main__':main()

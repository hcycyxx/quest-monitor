"""Bounded append-only prompts, semantic call gating and privacy-light idle state."""
import hashlib
import re
import time


def semantic_signature(text):
    text=re.sub(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[.+\d:-]*)?', '', str(text))
    text=re.sub(r'(?<!\d)\d{2}:\d{2}(?::\d{2})?', '', text)
    text=re.sub(r'\d+分\d+秒|\d+秒', '', text)
    text=re.sub(r'\s+', ' ', text).strip()
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class CallGate:
    def __init__(self):
        self.last_at=None;self.last_signature=None
    def due(self,activity,state,now,minimum=30,refresh=300):
        signature=(semantic_signature(activity),semantic_signature(state))
        if self.last_at is None:return True,'首次分析'
        if now-self.last_at<minimum:return False,'等待最短间隔'
        if signature!=self.last_signature:return True,'实质变化'
        if now-self.last_at>=refresh:return True,'低频复核'
        return False,'内容无实质变化'
    def commit(self,activity,state,now):
        self.last_at=now
        self.last_signature=(semantic_signature(activity),semantic_signature(state))


class PromptSession:
    def __init__(self,system,max_turns=6,max_chars=24000):
        self.system=system;self.max_turns=max_turns;self.max_chars=max_chars
        self.history=[];self.pending=None
    def prepare(self,state,activity,stamp):
        if len(self.history)>=self.max_turns*2 or sum(len(m['content']) for m in self.history)>self.max_chars:
            self.history=[]
        content=('当前权威任务状态（覆盖旧轮次）：\n'+state+
                 '\n\n本轮窗口活动：\n'+activity+
                 '\n\n当前时间：'+stamp+'\n仅依据本轮证据更新；无实质变化只返回 changed:false。')
        self.pending={'role':'user','content':content}
        return [{'role':'system','content':self.system}]+list(self.history)+[dict(self.pending)]
    def commit(self,response):
        if self.pending is not None:
            self.history.extend([self.pending,{'role':'assistant','content':response}])
            self.pending=None


class IdleState:
    def __init__(self,now=None,threshold=1800):
        self.threshold=threshold;self.last_visual=time.monotonic() if now is None else now
        self.previous_key=None;self.previous_sample=None;self.suspended=False;self.revision=0
    def observe(self,idle_seconds,key,sample=None,now=None):
        now=time.monotonic() if now is None else now
        changed=self.previous_key is not None and key!=self.previous_key
        self.previous_key=key
        if sample is not None:
            if self.previous_sample is not None and len(sample)==len(self.previous_sample):
                deltas=[abs(a-b) for a,b in zip(sample,self.previous_sample)]
                changed=changed or (sum(deltas)/max(1,len(deltas))>1.2 and sum(v>16 for v in deltas)>len(deltas)*.015)
            self.previous_sample=sample
        was=self.suspended
        if idle_seconds<2 or changed:
            self.last_visual=now
        self.suspended=idle_seconds>=self.threshold and now-self.last_visual>=self.threshold
        if changed or (was and not self.suspended):self.revision+=1
        return {'suspended':self.suspended,'idle_input_seconds':round(idle_seconds,1),
                'idle_visual_seconds':round(max(0,now-self.last_visual),1),'activity_revision':self.revision}


def usage_metrics(usage):
    usage=usage if isinstance(usage,dict) else {}
    hit=usage.get('prompt_cache_hit_tokens')
    details=usage.get('prompt_tokens_details')
    if hit is None and isinstance(details,dict):hit=details.get('cached_tokens')
    return {'input_tokens':usage.get('prompt_tokens'),'output_tokens':usage.get('completion_tokens'),
            'cached_tokens':hit,'uncached_tokens':usage.get('prompt_cache_miss_tokens'),
            'cache_reported':hit is not None}

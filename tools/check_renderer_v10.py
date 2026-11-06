"""Exercise the local renderer with an in-memory fake bridge in isolated headless Chrome."""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".venv" / ("v10-render-check-" + time.strftime("%Y%m%d_%H%M%S"))
OUT.mkdir(parents=True, exist_ok=False)
assets = ROOT / "ui" / "web_v10"
fixture_task = {"id": "M1", "key": "main_quests", "title": "客户 A 报价（3 个型号）", "status": "active",
                "priority": "high", "live": "已核对型号，待确认采购数量", "note": "离线虚拟任务",
                "steps": [{"text": "核对型号与参数", "done": True}, {"text": "确认采购数量", "done": False},
                          {"text": "更新报价草稿", "done": False}],
                "progress": {"low": 30, "high": 50, "label": "估算 30–50%", "source": "estimate"}}
others = []
for index, title in enumerate(("确认样品交期", "整理订单资料", "确认包装方案")):
    task = dict(fixture_task, id="S"+str(index), key="side_quests", title=title, steps=[],
                status="waiting" if index == 2 else "pending", live="仅离线虚拟任务，用于检查布局")
    others.append(task)
snapshot = {"ok": True, "current": fixture_task, "others": others, "history": [],
            "activity": "在产品资料中核对参数", "suggestion": "确认客户所需数量，再更新报价。",
            "updated_at": "2026-11-06T16:00:00+08:00", "paused": False, "resting": False, "error": "",
            "prefs": {"skin": "glass", "font": 14, "pinned": True, "autoHide": True, "expanded": True, "stepsOpen": False},
            "desktop": {"x": 0, "y": 0, "width": 336, "height": 620, "heightCap": 620,
                        "edgeSide": None, "edgeHidden": False, "autoHide": True, "pinned": True, "minimized": False}}
mock = "window.__fixture=" + json.dumps(snapshot, ensure_ascii=False) + ";\n" + r"""
window.__errors=[];window.addEventListener('error',e=>window.__errors.push(e.message));
window.addEventListener('unhandledrejection',e=>window.__errors.push(String(e.reason)));
const clone=x=>JSON.parse(JSON.stringify(x));let model=clone(window.__fixture),prior=null;
window.pywebview={api:{
 snapshot:async()=>clone(model),
 preferences:async patch=>{Object.assign(model.prefs,patch);return {ok:true,prefs:clone(model.prefs)};},
 window_action:async(name,payload)=>{if(name==='minimize')model.desktop.minimized=!model.desktop.minimized;
   return {ok:true,desktop:clone(model.desktop)};},
 task_action:async request=>{prior=clone(model);if(request.kind==='step')model.current.steps[request.step].done=request.done;
   return {ok:true,undo:'fake-undo',snapshot:clone(model)};},
 undo:async()=>{model=clone(prior);return {ok:true,snapshot:clone(model)};},
 pause:async value=>{model.paused=value;return {ok:true,snapshot:clone(model)};},
 summary:async()=>({ok:true}),open_detail_settings:async()=>({ok:true})
}};
"""
checks = r"""
(async()=>{
const wait=ms=>new Promise(r=>setTimeout(r,ms));const root=document.getElementById('sidequest-app-v10');
const q=s=>root.querySelector(s);let count=0;
function assert(test,message){if(!test)throw Error(message);count++;}
try{
 await wait(200);
 assert(q('[data-title]').textContent.includes('客户 A 报价'),'Task data did not load');
 assert(q('.sq-count').textContent==='3','Task count wrong');
 assert(root.querySelectorAll('[role=progressbar]').length===4,'Per-task progress missing');
 q('[data-action=expand]').click();await wait(1300);
 assert(q('#sq-task-list').hidden,'Disclosure did not close');
 q('[data-action=expand]').click();await wait(1300);
 assert(!q('#sq-task-list').hidden&&q('#sq-task-list').getBoundingClientRect().height>50,'Disclosure did not reopen');
 q('.sq-steps summary').click();await wait(1300);
 assert(q('.sq-steps summary').getAttribute('aria-expanded')==='true','Step disclosure state wrong');
 assert(q('#sq-step-content').getBoundingClientRect().height>30,'Step disclosure did not reveal');
 const checkbox=q('.sq-step-list input');checkbox.checked=false;checkbox.dispatchEvent(new Event('change',{bubbles:true}));await wait(100);
 assert(q('[data-message]').textContent==='已保存','Save feedback missing');
 assert(!q('[data-action=undo]').hidden,'Undo action missing');
 q('[data-action=undo]').click();await wait(100);
 assert(q('.sq-step-list input').checked,'Undo did not restore checkbox');
 q('[data-action=menu]').click();q('[data-action=settings]').click();
 const journal=q('[name=sq-skin][value=journal]');journal.checked=true;journal.dispatchEvent(new Event('change',{bubbles:true}));await wait(100);
 assert(root.dataset.skin==='journal','Skin change failed');
 const glass=q('[name=sq-skin][value=glass]');glass.checked=true;glass.dispatchEvent(new Event('change',{bubbles:true}));await wait(100);
 q('[data-action=back]').click();q('.sq-steps summary').click();await wait(1300);
 q('[data-action=minimize]').click();await wait(100);
 assert(!q('.sq-mini-restore').hidden&&q('.sq-main-view').hidden,'Minimize failed');
 q('[data-action=minimize]').click();await wait(100);
 assert(!q('.sq-main-view').hidden,'Restore failed');
 assert(window.__errors.length===0,'JavaScript errors: '+window.__errors.join(';'));
 document.documentElement.dataset.offlineResult='PASS '+count;
}catch(error){document.documentElement.dataset.offlineResult='FAIL '+error.message;}
})();
"""
html = (assets / "index.html").read_text(encoding="utf-8")
for placeholder, name in (("/*__LOCAL_CSS__*/", "approved.css"), ("/*__RUNTIME_CSS__*/", "desktop.css"),
                          ("/*__LOCAL_ICONS__*/", "vendor/lucide.min.js")):
    html = html.replace(placeholder, (assets / name).read_text(encoding="utf-8"))
html = html.replace("/*__LOCAL_APP__*/", mock + (assets / "desktop.js").read_text(encoding="utf-8") + checks)
html = html.replace("</style>", "html,body{width:336px;height:620px}</style>")
page = OUT / "fixture.html"
page.write_text(html, encoding="utf-8")
result = subprocess.run(["node", str(ROOT / "tools" / "render_check_cdp_v10.cjs"), str(OUT)],
                        timeout=45, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
report = json.loads((OUT / "report.json").read_text(encoding="utf-8")) if (OUT / "report.json").exists() else {}
print(report.get("status", "FAIL missing renderer report"))
print("Evidence:", OUT)
if not report.get("status", "").startswith("PASS"):
    raise SystemExit(1)
raise SystemExit(result.returncode)

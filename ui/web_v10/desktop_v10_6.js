/* SideQuest V10. All task text is inserted as text, never interpreted as markup. */
(() => {
  'use strict';
  const root=document.getElementById('sidequest-app-v10'), q=s=>root.querySelector(s);
  const win=q('.sq-window'), viewport=q('.sq-viewport'), toolbar=q('.sq-toolbar'), grip=q('.sq-resize-handle');
  const reduced=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
  const state={expanded:true,stepsOpen:false,settings:false,timeline:false,history:false,more:false,current:null,others:[],historyRows:[],prefs:{},desktop:{},paused:false};
  const skins={glass:['#14171f','#232a38','#f1f5fc','#a8b7cc','#ffd166','#7de3f4','#5be3a2','#38465c'],transparent:['#182330','#2b3c4e','#ffffff','#cfdaea','#ffe1a0','#b3efff','#92efc3','#506479'],journal:['#f4efe3','#eae1ce','#342e29','#6b6054','#96623b','#396c73','#3c7052','#c6b9a2','#c6b9a2'],night:['#101b25','#1c2e3c','#edf8ff','#abc4d6','#8ae8ff','#c0b3ff','#68edb8','#3e566a']};
  const priorityPalettes={glass:['#ff6f5e','#ffb454','#6f8fa6','#7de3f4','#5be3a2'],transparent:['#ff8577','#ffc670','#8fa9bd','#b3efff','#92efc3'],journal:['#b23b28','#8b5b12','#526d7b','#396c73','#3c7052'],night:['#ff7a6a','#ffc266','#7f9fb5','#c0b3ff','#68edb8']};
  function taskLevel(task){if(!task)return 'unknown';if(task.status==='done')return 'done';if(task.status==='waiting')return 'wait';const priority=String(task.priority||'').trim().toLowerCase();return ['high','mid','low'].includes(priority)?priority:'unknown';}
  function levelLabel(task){return {high:'高优先级',mid:'中优先级',low:'低优先级',wait:'等待回复',done:'已完成',unknown:'未分级'}[taskLevel(task)];}
  const holds=new Set(), detailOpen=new Set();
  let bridge=null, pollBusy=false, pending=false, undoToken=null, initialized=false,dataEpoch=0;
  let prefsQueue=Promise.resolve(),prefsPending=0;
  let othersSignature='', stepSignature='', historySignature='', feedbackKind='', geometry=null, lastInputKeyboard=false,lastSummaryError='';
  const text=(selector,value)=>{const el=q(selector);if(el&&el.textContent!==String(value??''))el.textContent=String(value??'');};
  function icon(name){const el=document.createElement('i');el.dataset.lucide=name;el.setAttribute('aria-hidden','true');return el;}
  function icons(){if(globalThis.lucide)lucide.createIcons({attrs:{width:16,height:16,'stroke-width':1.7}});root.querySelectorAll('[data-tooltip]').forEach(el=>el.title=el.dataset.tooltip);}
  function el(tag,cls,content){const node=document.createElement(tag);if(cls)node.className=cls;if(content!==undefined)node.textContent=content;return node;}
  let lastHold=null,holdSending=false,holdPending=null;
  async function sendHold(){
    if(holdSending||!bridge)return;holdSending=true;
    try{while(holdPending){const next=holdPending;holdPending=null;try{const result=await bridge.window_action('hold',next);if(!result?.ok)lastHold=null;}catch(error){lastHold=null;}}}
    finally{holdSending=false;}
  }
  function setHold(name,active){
    if(active)holds.add(name);else holds.delete(name);
    const reasons=[...holds].sort(),signature=reasons.join('|');
    if(bridge&&signature!==lastHold){lastHold=signature;holdPending={active:reasons.length>0,reasons};sendHold();}
  }
  async function call(method,...args){
    if(!bridge)throw Error('桌面连接尚未就绪');
    const result=await bridge[method](...args);
    if(!result||!result.ok)throw Error(result?.error||'操作未完成，请重试');
    return result;
  }
  function feedback(message,error=false,token=null){
    const panel=q('.sq-feedback');panel.hidden=false;panel.dataset.error=String(error);
    panel.setAttribute('role',error?'alert':'status');text('[data-message]',message);
    undoToken=token;q('[data-action=undo]').hidden=!token;feedbackKind=error?'error':'action';requestFit();
  }
  function buttonIcon(button,name){const current=button.dataset.icon;if(current===name)return;button.dataset.icon=name;button.replaceChildren(icon(name));}
  function applyPrefs(prefs,initial=false){
    state.prefs={...state.prefs,...prefs};const p=state.prefs, colors=skins[p.skin]||skins.glass;
    ['bg','hi','fg','muted','gold','cyan','green','stroke'].forEach((key,i)=>root.style.setProperty('--sq-'+key,colors[i]));
    root.dataset.skin=p.skin||'glass';document.body.style.backgroundColor=colors[0];
    const priorityColors=priorityPalettes[p.skin]||priorityPalettes.glass;['high','mid','low','wait','done'].forEach((key,index)=>root.style.setProperty('--sq-prio-'+key,priorityColors[index]));
    root.style.setProperty('--sq-size',Number(p.font||14)+'px');
    q('#sq-font').value=p.font||14;text('#sq-font-value',p.font||14);
    root.querySelectorAll('[name=sq-skin]').forEach(input=>input.checked=input.value===p.skin);
    if(initial){state.expanded=p.expanded!==false;state.stepsOpen=p.stepsOpen===true;}
  }
  function savePrefs(patch){
    dataEpoch++;
    prefsPending++;
    const operation=prefsQueue.then(async()=>{
      try{const result=await call('preferences',patch);applyPrefs(result.prefs);renderChrome();}
      catch(error){applyPrefs(state.prefs);feedback(error.message,true);}
      finally{prefsPending--;}
    });
    prefsQueue=operation.catch(()=>{});return operation;
  }
  function progressNode(progress,waiting=false){
    const area=el('div','sq-task-progress'+(waiting?' sq-progress-waiting':''));
    const track=el('div','sq-progress-track');track.setAttribute('role','progressbar');track.setAttribute('aria-label','任务进度');track.setAttribute('aria-valuetext',progress.label);
    if(progress.low!==null){track.setAttribute('aria-valuemin','0');track.setAttribute('aria-valuemax','100');track.setAttribute('aria-valuenow',(progress.low+progress.high)/2);
      const fill=el('span','sq-progress-fill');fill.style.width=progress.low+'%';track.append(fill);
      if(progress.high>progress.low){const range=el('span','sq-progress-range');range.style.left=progress.low+'%';range.style.width=(progress.high-progress.low)+'%';track.append(range);}}
    area.append(track,el('span','sq-progress-label',progress.label));return area;
  }
  function idOf(task){return task.key+':'+task.id;}
  function taskRequest(task,patch){return {request_id:crypto.randomUUID(),key:task.key,id:task.id,title:task.title,...patch};}
  async function changeTask(task,patch){
    if(pending)return;pending=true;dataEpoch++;setHold('save',true);setSaving(true);feedback('正在保存…');
    try{const result=await call('task_action',taskRequest(task,patch));applySnapshot(result.snapshot);feedback('已保存',false,result.undo);}
    catch(error){feedback(error.message,true);pending=false;await poll();}
    finally{pending=false;setSaving(false);setHold('save',false);}
  }
  function setSaving(value){root.querySelectorAll('[data-save-control]').forEach(control=>control.disabled=value);q('[data-action=complete]').disabled=value||!state.current;}
  function checkbox(task,step,index){
    const label=el('label'),input=el('input');input.type='checkbox';input.checked=step.done;input.dataset.saveControl='true';input.disabled=pending;
    input.addEventListener('change',()=>{const desired=input.checked;input.checked=step.done;changeTask(task,{kind:'step',step:index,step_text:step.text,done:desired});});
    label.append(input,el('span','',step.text));return label;
  }
  function renderMain(task){
    state.current=task;q('.sq-focus').dataset.level=taskLevel(task);
    text('[data-title]',task?.title||'暂无主线任务');text('[data-mini-title]',task?.title||'SideQuest');
    q('[data-action=complete]').disabled=pending||!task;
    q('.sq-title-toggle').setAttribute('aria-label',(task?.title||'暂无主线任务')+'，收起或展开其他任务');
    const p=task?.progress||{low:null,high:null,label:'待估算',source:'unknown'};
    const value=p.low===null?0:(p.low+p.high)/2;
    q('.sq-ring-fill').setAttribute('stroke-dasharray',(170*value/100)+' 170');
    q('.sq-ring').setAttribute('aria-label',p.label);text('.sq-ring span','主线');
    q('[data-main-fill]').style.width=(p.low||0)+'%';q('[data-main-range]').style.left=(p.low||0)+'%';q('[data-main-range]').style.width=(p.low===null?0:p.high-p.low)+'%';
    const bar=q('[data-main-bar]');bar.setAttribute('aria-valuetext',p.label);
    if(p.low===null)bar.removeAttribute('aria-valuenow');else bar.setAttribute('aria-valuenow',value);
    text('[data-main-bar-label]',p.label+(task&&taskLevel(task)!=='unknown'?' · '+levelLabel(task):''));text('[data-progress]',task?.live||'后台识别任务后会显示在这里');
    const signature=JSON.stringify([task?.key,task?.id,task?.title,task?.steps]);
    if(signature!==stepSignature){
      const focused=stepsInner.contains(document.activeElement)?document.activeElement?.dataset.stepIndex:null;
      stepsInner.replaceChildren();(task?.steps||[]).forEach((step,index)=>{const label=checkbox(task,step,index);label.querySelector('input').dataset.stepIndex=index;stepsInner.append(label);});
      stepSignature=signature;
      if(focused!==null)stepsInner.querySelector('[data-step-index="'+focused+'"]')?.focus({preventScroll:true});
    }
    q('.sq-steps').hidden=!task?.steps?.length;
    text('.sq-steps summary span:first-child',task?.title?.includes('报价')?'报价步骤':'任务步骤');
    text('[data-step-count]',(task?.steps||[]).filter(step=>step.done).length+' / '+(task?.steps?.length||0));
  }
  function taskRow(task){
    const article=el('article','sq-task'),heading=el('div','sq-task-heading');article.dataset.level=taskLevel(task);
    const complete=el('button','sq-check');complete.type='button';complete.dataset.saveControl='true';complete.setAttribute('aria-label','标记“'+task.title+'”完成');complete.append(icon('check'));
    complete.addEventListener('click',()=>changeTask(task,{kind:'task',done:true}));
    const title=el('button','sq-task-name',task.title),details=el('div','sq-task-details');
    title.type='button';title.setAttribute('aria-expanded',String(detailOpen.has(idOf(task))));details.hidden=!detailOpen.has(idOf(task));
    title.addEventListener('click',()=>{details.hidden=!details.hidden;title.setAttribute('aria-expanded',String(!details.hidden));if(details.hidden)detailOpen.delete(idOf(task));else detailOpen.add(idOf(task));requestFit();});
    const label=task.status==='waiting'?'等待回复':task.completion_candidate?'待确认'+(taskLevel(task)!=='unknown'?' · '+levelLabel(task):''):(task.key==='main_quests'?'主线 · ':'')+levelLabel(task);
    heading.append(complete,title,el('span',task.status==='waiting'?'sq-waiting':'sq-priority',label));
    const note=[task.note,task.progress_basis?'估算依据：'+task.progress_basis:''].filter(Boolean).join('\n');
    if(note)details.append(el('p','sq-note',note));
    (task.steps||[]).forEach((step,index)=>details.append(checkbox(task,step,index)));
    if(!note&&!task.steps?.length)details.append(el('p','','暂无补充说明'));
    article.append(heading,el('p','',task.live),progressNode(task.progress,task.status==='waiting'),details);return article;
  }
  function renderOthers(){
    const signature=JSON.stringify([state.others,state.more]);if(signature===othersSignature)return;
    othersSignature=signature;const list=listInner;list.replaceChildren();
    const visible=state.more?state.others:state.others.slice(0,3);
    visible.forEach(task=>list.append(taskRow(task)));
    if(!visible.length)list.append(el('div','sq-empty','暂无其他待办任务'));
    if(state.others.length>3){const more=el('button','sq-text-button',state.more?'收起更多':'查看其余 '+(state.others.length-3)+' 项');more.addEventListener('click',()=>{state.more=!state.more;renderOthers();requestFit();});list.append(more);}
    text('.sq-count',state.others.length);icons();
  }
  function renderHistory(){
    const signature=JSON.stringify(state.historyRows);if(signature===historySignature)return;historySignature=signature;
    const listing=q('[data-history-list]');listing.replaceChildren();
    state.historyRows.forEach(task=>{const row=el('div','sq-history-row'),content=el('div','',task.title);
      const time=task.completed_at?new Date(task.completed_at).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}):'完成时间未记录';
      content.append(el('span','sq-history-time',time));const restore=el('button','sq-text-button','恢复');restore.dataset.saveControl='true';restore.addEventListener('click',()=>changeTask(task,{kind:'task',done:false}));row.append(content,restore);listing.append(row);});
    if(!state.historyRows.length)listing.append(el('p','','暂无完成记录'));
  }
  function applySnapshot(snapshot){
    if(!snapshot)return;
    state.paused=!!snapshot.paused;state.resting=!!snapshot.resting;state.others=snapshot.others;state.historyRows=snapshot.history;
    if(!prefsPending)applyPrefs(snapshot.prefs,!initialized);initialized=true;applyDesktop(snapshot.desktop);
    renderMain(snapshot.current);renderOthers();renderHistory();
    text('[data-next]',snapshot.suggestion);text('.sq-observation p',snapshot.activity);
    const date=snapshot.updated_at?new Date(snapshot.updated_at):null;
    text('[data-updated]',date&&!Number.isNaN(date.getTime())?'更新于 '+date.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'}):'更新时间未知');
    if(snapshot.error){feedback(snapshot.error,true);feedbackKind='read';}else if(feedbackKind==='read'){q('.sq-feedback').hidden=true;feedbackKind='';}
    if(snapshot.summaryError&&snapshot.summaryError!==lastSummaryError)feedback('日报生成失败：'+snapshot.summaryError,true);
    lastSummaryError=snapshot.summaryError;
    renderChrome();syncTaskList(true);settleInitialSteps();requestFit();
  }
  function renderChrome(){
    text('[data-status]',state.paused?'已暂停':state.resting?'自动休息':'观察中');q('.sq-dot').style.background=state.paused?'var(--sq-gold)':'var(--sq-green)';
    const pause=q('[data-action=pause]');pause.setAttribute('aria-pressed',String(state.paused));pause.setAttribute('aria-label',state.paused?'继续观察':'暂停观察');pause.dataset.tooltip=state.paused?'继续观察':'暂停观察';buttonIcon(pause,state.paused?'play':'pause');
    q('[data-action=pin]').setAttribute('aria-pressed',String(state.prefs.pinned!==false));
    q('[data-action=dock]').setAttribute('aria-pressed',String(state.prefs.autoHide!==false));text('[data-dock-label]',state.prefs.autoHide!==false?'贴边自动隐藏：开启':'贴边自动隐藏：关闭');
    root.querySelectorAll('[data-action=expand]').forEach(button=>button.setAttribute('aria-expanded',String(state.expanded)));text('[data-list-state]',state.expanded?'收起':'展开');
    q('.sq-main-view').hidden=state.settings||state.timeline||state.desktop.minimized;q('.sq-settings').hidden=!state.settings||state.desktop.minimized;timelineView.hidden=!state.timeline||state.desktop.minimized;q('.sq-mini-restore').hidden=!state.desktop.minimized;
    const min=q('.sq-tools [data-action=minimize]');buttonIcon(min,state.desktop.minimized?'maximize-2':'minus');min.dataset.tooltip=state.desktop.minimized?'还原任务面板':'最小化为窄条';min.setAttribute('aria-label',min.dataset.tooltip);
    q('.sq-resize-handle').hidden=!!state.desktop.minimized;q('.sq-history').hidden=!state.history;icons();
  }
  function applyDesktop(value){if(!value||!Object.keys(value).length)return;state.desktop=value;root.dataset.edge=value.edgeSide||'';root.dataset.hidden=String(!!value.edgeHidden);q('.sq-edge-tab').hidden=!value.edgeHidden;renderChrome();requestFit();}
  window.sidequestDesktop=applyDesktop;
  function menu(open){q('#sq-menu').hidden=!open;q('#sq-menu').style.top=(toolbar.offsetHeight+4)+'px';q('[data-action=menu]').setAttribute('aria-expanded',String(open));setHold('menu',open);requestFit();}
  // Both disclosures use the approved critically damped spring and fresh measurements.
  function disclosure(body,inner,getOpen,finish){
    const motion={raf:0,x:0,v:0,time:0,started:false};
    function settle(){if(motion.raf)cancelAnimationFrame(motion.raf);motion.raf=0;motion.v=0;body.style.height='';body.style.overflow='';body.hidden=!getOpen();body.inert=!getOpen();body.setAttribute('aria-hidden',String(!getOpen()));finish?.();requestFit(true);}
    function animate(instant=false){
      const closed=body.hidden;if(instant||reduced()){motion.started=true;settle();return;}
      motion.x=closed?0:body.getBoundingClientRect().height;if(closed)motion.v=0;if(motion.raf)cancelAnimationFrame(motion.raf);
      body.hidden=false;body.inert=!getOpen();body.setAttribute('aria-hidden',String(!getOpen()));body.style.height=motion.x+'px';body.style.overflow='hidden';motion.time=performance.now();
      function frame(now){if(reduced()||!inner.getClientRects().length){settle();return;}
        const target=getOpen()?inner.getBoundingClientRect().height:0,dt=Math.min((now-motion.time)/1000,.04);motion.time=now;
        const omega=10.5,offset=motion.x-target,c=motion.v+omega*offset,decay=Math.exp(-omega*dt);
        motion.x=target+(offset+c*dt)*decay;motion.v=(motion.v-omega*c*dt)*decay;if(motion.x<0){motion.x=0;motion.v=0;}
        body.style.height=motion.x+'px';requestFit();if(Math.abs(motion.x-target)<.4&&Math.abs(motion.v)<4){settle();return;}motion.raf=requestAnimationFrame(frame);}
      motion.started=true;motion.raf=requestAnimationFrame(frame);
    }
    matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change',()=>{if(reduced())settle();});return {animate,motion};
  }
  const list=q('#sq-task-list'),listInner=el('div','sq-list-inner');list.replaceChildren(listInner);
  // Keep the inner wrapper stable so newly received task data cannot stale an animation endpoint.
  const listDisclosure=disclosure(list,listInner,()=>state.expanded);
  let listTarget=null;
  function syncTaskList(initial=false){if(listTarget===state.expanded)return;const first=listTarget===null;listTarget=state.expanded;listDisclosure.animate(first&&initial);}
  const stepsPanel=q('.sq-steps'),stepsSummary=stepsPanel.querySelector('summary'),stepsBody=q('#sq-step-content'),stepsInner=stepsBody.querySelector('.sq-step-list');
  const stepsDisclosure=disclosure(stepsBody,stepsInner,()=>state.stepsOpen,()=>{stepsPanel.open=state.stepsOpen;});
  let initialSteps=false;
  function settleInitialSteps(){if(initialSteps)return;initialSteps=true;stepsSummary.setAttribute('aria-expanded',String(state.stepsOpen));stepsPanel.open=true;stepsDisclosure.animate(true);}
  stepsSummary.addEventListener('click',event=>{event.preventDefault();stopScroll();state.stepsOpen=!state.stepsOpen;if(!state.stepsOpen&&stepsBody.contains(document.activeElement))stepsSummary.focus({preventScroll:true});stepsSummary.setAttribute('aria-expanded',String(state.stepsOpen));const h=stepsBody.hidden?0:stepsBody.getBoundingClientRect().height;stepsPanel.open=true;stepsBody.style.height=h+'px';stepsDisclosure.animate();savePrefs({stepsOpen:state.stepsOpen});});
  let fitFrame=0,lastFit='',fitSending=false,fitActive=null,fitPending=null;
  function contentHeight(body){
    const box=body.getBoundingClientRect(),style=getComputedStyle(body);
    const paddingBottom=parseFloat(style.paddingBottom)||0;
    const children=Array.from(body.children).filter(child=>!child.hidden&&getComputedStyle(child).display!=='none');
    if(!children.length)return box.height;
    let bottom=box.top;
    children.forEach(child=>{const rect=child.getBoundingClientRect();const margin=parseFloat(getComputedStyle(child).marginBottom)||0;bottom=Math.max(bottom,rect.bottom+margin);});
    return Math.max(0,bottom-box.top+paddingBottom);
  }
  async function pumpFit(){
    if(fitSending)return;
    fitSending=true;
    try{
      while(fitPending){
        const next=fitPending;fitPending=null;fitActive=next;
        try{
          const result=await bridge.window_action('fit',{height:next.height});
          lastFit=result?.ok&&result.applied!==false?next.signature:'';
        }catch(error){lastFit='';}
      }
    }finally{fitActive=null;fitSending=false;}
  }
  function requestFit(force=false){
    if(force===true)lastFit='';
    if(fitFrame||!bridge||geometry)return;
    fitFrame=requestAnimationFrame(()=>{
      fitFrame=0;if(state.desktop.edgeHidden||geometry)return;
      const body=state.desktop.minimized?q('.sq-mini-restore'):state.timeline?timelineView:state.settings?q('.sq-settings'):q('.sq-main-view');
      let height=Math.ceil(toolbar.getBoundingClientRect().height+contentHeight(body)+3);
      if(!q('#sq-menu').hidden)height=Math.max(height,toolbar.offsetHeight+q('#sq-menu').scrollHeight+16);
      const signature=height+':'+state.desktop.heightCap;
      if(fitPending?.signature===signature)return;
      if(fitSending&&!fitPending&&fitActive?.signature===signature)return;
      if(!fitSending&&!fitPending&&signature===lastFit)return;
      fitPending={height,signature};pumpFit();
    });
  }
  // Smooth discrete mouse wheels; touchpads and touch scrolling keep native behavior.
  let scrollFrame=0,scrollTarget=0,scrollTime=0;
  function stopScroll(){if(scrollFrame)cancelAnimationFrame(scrollFrame);scrollFrame=0;scrollTarget=viewport.scrollTop;setHold('scroll',false);}
  viewport.addEventListener('wheel',event=>{if(event.ctrlKey||event.shiftKey||event.deltaX||event.target.closest('input,textarea,select')||reduced())return;if(event.deltaMode===0&&Math.abs(event.deltaY)<50){stopScroll();return;}
    const max=Math.max(0,viewport.scrollHeight-viewport.clientHeight),delta=event.deltaY*(event.deltaMode===1?18:event.deltaMode===2?viewport.clientHeight:1);
    if(!max||(viewport.scrollTop<=0&&delta<0)||(viewport.scrollTop>=max-1&&delta>0)){stopScroll();return;}event.preventDefault();setHold('scroll',true);
    if(!scrollFrame||Math.sign(delta)!==Math.sign(scrollTarget-viewport.scrollTop))scrollTarget=viewport.scrollTop;scrollTarget=Math.max(0,Math.min(max,scrollTarget+delta));if(scrollFrame)return;scrollTime=performance.now();
    function tick(now){const dt=Math.min(now-scrollTime,50);scrollTime=now;scrollTarget=Math.min(scrollTarget,viewport.scrollHeight-viewport.clientHeight);const gap=scrollTarget-viewport.scrollTop;if(Math.abs(gap)<.7){viewport.scrollTop=scrollTarget;stopScroll();return;}const before=viewport.scrollTop;viewport.scrollTop=before+gap*(1-Math.exp(-dt/60));if(dt>5&&Math.abs(viewport.scrollTop-before)<.1){viewport.scrollTop=scrollTarget;stopScroll();return;}scrollFrame=requestAnimationFrame(tick);}scrollFrame=requestAnimationFrame(tick);
  },{passive:false});
  viewport.addEventListener('pointerdown',stopScroll,{passive:true});viewport.addEventListener('touchstart',stopScroll,{passive:true});
  // Coalesce pointer updates; release commits only after the latest move reaches the native host.
  let geometryPayload=null,geometryBusy=false,geometryEnded=false;
  async function pumpGeometry(){if(geometryBusy||!geometryPayload)return;geometryBusy=true;while(geometryPayload){const payload=geometryPayload;geometryPayload=null;try{await call('window_action','geometry',payload);}catch(error){feedback(error.message,true);}}geometryBusy=false;if(geometryEnded){geometryEnded=false;await call('window_action','geometry',{phase:'end',dock:geometry?.kind==='move'}).catch(error=>feedback(error.message,true));geometry=null;setHold('gesture',false);requestFit(true);}}
  function beginGeometry(event,kind){if(geometry||geometryBusy||geometryEnded||event.button!==0||(kind==='move'&&event.target.closest('button,input,summary,a')))return;event.preventDefault();stopScroll();menu(false);setHold('gesture',true);const d=state.desktop;geometry={kind,id:event.pointerId,element:event.currentTarget,startX:event.screenX,startY:event.screenY,x:d.x,y:d.y,width:innerWidth,height:innerHeight};event.currentTarget.setPointerCapture(event.pointerId);}
  function moveGeometry(event){if(!geometry||geometry.id!==event.pointerId)return;const dx=event.screenX-geometry.startX,dy=event.screenY-geometry.startY;geometryPayload=geometry.kind==='move'?{phase:'move',x:geometry.x+dx,y:geometry.y+dy}:{phase:'resize',x:geometry.x,y:geometry.y,width:geometry.width+dx,height:geometry.height+dy};geometry.lastPayload=geometryPayload;pumpGeometry();}
  function endGeometry(event){if(geometryEnded||!geometry||(event.pointerId!==undefined&&event.pointerId!==geometry.id))return;const g=geometry;geometryEnded=true;if(g.element.hasPointerCapture(g.id))g.element.releasePointerCapture(g.id);if(!geometryPayload)geometryPayload=g.lastPayload||{phase:g.kind==='move'?'move':'resize',x:g.x,y:g.y,width:g.width,height:g.height};pumpGeometry();}
  toolbar.addEventListener('pointerdown',event=>beginGeometry(event,'move'));grip.addEventListener('pointerdown',event=>beginGeometry(event,'resize'));
  [toolbar,grip].forEach(target=>{target.addEventListener('pointermove',moveGeometry);target.addEventListener('pointerup',endGeometry);target.addEventListener('pointercancel',endGeometry);target.addEventListener('lostpointercapture',event=>{if(!geometryEnded)endGeometry(event);});});
  grip.addEventListener('keydown',async event=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key))return;event.preventDefault();const amount=event.shiftKey?24:8;try{await call('window_action','geometry',{phase:'resize',width:innerWidth+({'ArrowLeft':-amount,'ArrowRight':amount}[event.key]||0),height:innerHeight+({'ArrowUp':-amount,'ArrowDown':amount}[event.key]||0)});await call('window_action','geometry',{phase:'end',dock:false});requestFit();}catch(error){feedback(error.message,true);}});
  root.addEventListener('click',async event=>{const button=event.target.closest('[data-action]');if(!button)return;try{switch(button.dataset.action){
    case 'pause':dataEpoch++;button.disabled=true;try{applySnapshot((await call('pause',!state.paused)).snapshot);}finally{button.disabled=false;}break;
    case 'pin':await savePrefs({pinned:state.prefs.pinned===false});break;
    case 'menu':menu(q('#sq-menu').hidden);break;
    case 'expand':stopScroll();state.expanded=!state.expanded;renderChrome();syncTaskList();await savePrefs({expanded:state.expanded});break;
    case 'complete':if(state.current)await changeTask(state.current,{kind:'task',done:true});break;
    case 'undo':if(undoToken&&!pending){pending=true;dataEpoch++;setSaving(true);setHold('save',true);try{const result=await call('undo',undoToken);applySnapshot(result.snapshot);feedback('已撤销');}finally{pending=false;setSaving(false);setHold('save',false);}}break;
    case 'history':state.history=!state.history;button.setAttribute('aria-expanded',String(state.history));renderChrome();requestFit();break;
    case 'settings':menu(false);state.timeline=false;state.settings=true;setHold('settings',true);renderChrome();requestFit();break;
    case 'back':state.timeline=false;state.settings=false;setHold('settings',false);renderChrome();requestFit();break;
    case 'timeline':menu(false);state.settings=false;setHold('settings',false);state.timeline=true;renderChrome();requestFit(true);loadTimeline();break;
    case 'details':await call('open_detail_settings');break;
    case 'summary':{const result=await call('summary');if(result.message)feedback(result.message);break;}
    case 'dock':menu(false);await savePrefs({autoHide:state.prefs.autoHide===false});break;
    case 'dockleft':case 'dockright':menu(false);applyDesktop((await call('window_action','dock',{side:button.dataset.action==='dockleft'?'left':'right'})).desktop);break;
    case 'resetgeometry':menu(false);applyDesktop((await call('window_action','reset')).desktop);requestFit();break;
    case 'minimize':applyDesktop((await call('window_action','minimize')).desktop);requestFit();break;
    case 'hide':menu(false);await call('window_action','hide');break;
    case 'close':await call('window_action','quit');break;
    case 'revealedge':applyDesktop((await call('window_action','reveal')).desktop);break;
  }}catch(error){feedback(error.message,true);}});
  root.addEventListener('click',event=>{if(!event.target.closest('.sq-menu')&&!event.target.closest('[data-action=menu]'))menu(false);});
  root.addEventListener('change',event=>{if(event.target.name==='sq-skin')savePrefs({skin:event.target.value});if(event.target.id==='sq-font')savePrefs({font:Number(event.target.value)});});
  q('#sq-font').addEventListener('input',event=>{root.style.setProperty('--sq-size',event.target.value+'px');text('#sq-font-value',event.target.value);requestFit();});
  root.addEventListener('keydown',event=>{lastInputKeyboard=true;if(event.key==='Escape'){menu(false);state.settings=false;state.timeline=false;setHold('settings',false);renderChrome();requestFit();}});
  root.addEventListener('pointerdown',()=>{lastInputKeyboard=false;if(!document.activeElement.matches('input,textarea,select'))setHold('focus',false);});
  root.addEventListener('focusin',event=>setHold('focus',lastInputKeyboard&&document.hasFocus()));
  root.addEventListener('focusout',()=>setTimeout(()=>setHold('focus',document.hasFocus()&&root.contains(document.activeElement)&&lastInputKeyboard),0));
  document.addEventListener('pointerenter',()=>bridge?.window_action('hover',{inside:true}));document.addEventListener('pointerleave',()=>{setHold('focus',false);bridge?.window_action('hover',{inside:false});});
  q('.sq-edge-tab').addEventListener('pointerenter',()=>bridge?.window_action('reveal'));
  q('.sq-edge-tab').addEventListener('focus',async()=>{await bridge?.window_action('reveal');q('[data-action=menu]').focus({preventScroll:true});});
  window.addEventListener('blur',()=>{if(geometry)endGeometry({pointerId:geometry.id});stopScroll();menu(false);setHold('focus',false);setHold('settings',false);});
  window.addEventListener('focus',()=>{if(state.settings)setHold('settings',true);});

  const timelineButton=el('button','sq-text-button','时间轴');timelineButton.dataset.action='timeline';timelineButton.type='button';q('.sq-footer').append(timelineButton);
  const timelineView=el('section','sq-timeline');timelineView.hidden=true;timelineView.setAttribute('aria-label','活动时间轴');
  const timelineHeading=el('div','sq-settings-header'),timelineTitle=el('h2','','时间轴'),timelineBack=el('button','sq-icon');
  timelineBack.type='button';timelineBack.dataset.action='back';timelineBack.setAttribute('aria-label','返回任务');timelineBack.append(icon('x'));timelineHeading.append(timelineTitle,timelineBack);
  const timelineControls=el('div','sq-timeline-controls'),dateLabel=el('label','','日期'),timelineDate=el('input');timelineDate.type='date';
  const today=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
  const part=kind=>today.find(x=>x.type===kind).value;timelineDate.value=part('year')+'-'+part('month')+'-'+part('day');timelineDate.max=timelineDate.value;timelineDate.setAttribute('aria-label','时间轴日期');dateLabel.append(timelineDate);
  const timelineRefresh=el('button','sq-text-button','刷新');timelineRefresh.type='button';timelineRefresh.addEventListener('click',()=>loadTimeline());timelineControls.append(dateLabel,timelineRefresh);
  const timelineSummary=el('p','sq-timeline-summary','正在读取记录…'),timelineNote=el('p','sq-timeline-note'),timelineRows=el('div','sq-timeline-rows');
  timelineSummary.setAttribute('role','status');timelineSummary.setAttribute('aria-live','polite');timelineView.append(timelineHeading,timelineControls,timelineSummary,timelineNote,timelineRows);viewport.append(timelineView);
  let timelineBusy=false,timelineSequence=0,timelineData=null,timelineLimit=100;
  const timelineTime=value=>new Date(value*1000).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit'});
  function duration(seconds){if(seconds===null||seconds===undefined)return '时长未记录';const n=Math.round(seconds);if(n<60)return n+'秒';if(n<3600)return Math.floor(n/60)+'分'+(n%60?n%60+'秒':'');return Math.floor(n/3600)+'小时'+Math.floor(n%3600/60)+'分';}
  function drawTimeline(){
    timelineRows.replaceChildren();if(!timelineData)return;
    const rows=[...timelineData.rows].reverse(),maximum=Math.max(1,...rows.map(row=>row.seconds||0));
    rows.slice(0,timelineLimit).forEach(row=>{
      const item=el('article','sq-timeline-row'),when=el('time','sq-timeline-time',timelineTime(row.start)),content=el('div','sq-timeline-content');when.dateTime=new Date(row.start*1000).toISOString();
      const title=el('div','sq-timeline-title',row.title);content.append(title);
      if(row.kind==='activity'){
        content.append(el('p','sq-timeline-meta',row.active?'正在停留 · 开始 '+timelineTime(row.start):'开始 '+timelineTime(row.start)+' · 至 '+timelineTime(row.end)));
        const track=el('div','sq-timeline-track');track.setAttribute('role','img');track.setAttribute('aria-label','窗口停留时长：'+duration(row.seconds));
        if(row.seconds!==null){const fill=el('span','sq-timeline-fill');fill.style.width=(row.seconds/maximum*100)+'%';track.append(fill);}
        content.append(track,el('p','sq-timeline-duration',row.seconds===null?'停留时长未记录':'停留 '+duration(row.seconds)));
      }else{
        item.dataset.kind=row.kind;const label={completed:'完成于 ',created:'任务建立于 ',reopened:'恢复为进行中 ',undone:'撤销任务操作 '};content.append(el('p','sq-timeline-event',(label[row.kind]||'记录于 ')+timelineTime(row.start)));
      }
      item.append(when,content);timelineRows.append(item);
    });
    if(!rows.length)timelineRows.append(el('p','sq-empty','这一天暂无可用记录。后续活动会继续归档。'));
    if(rows.length>timelineLimit){const more=el('button','sq-text-button','再显示较早的100条');more.type='button';more.addEventListener('click',()=>{timelineLimit+=100;drawTimeline();requestFit(true);});timelineRows.append(more);}
    requestFit(true);icons();
  }
  async function loadTimeline(explicit=true){
    const selected=timelineDate.value;if(!selected||!bridge||(!explicit&&timelineBusy))return;
    const sequence=++timelineSequence;
    if(explicit){timelineLimit=100;timelineSummary.textContent='正在读取记录…';}
    timelineBusy=true;
    try{
      const result=await call('timeline',selected);if(sequence!==timelineSequence||selected!==timelineDate.value)return;
      timelineData=result;timelineSummary.textContent='窗口停留 '+duration(result.totalSeconds)+' · 完成记录 '+result.completedCount+' 条 · 最近在上方';
      timelineNote.textContent=(result.error?result.error+'。':'')+result.note+(result.morePending?' 更多历史正在归档，可稍后刷新。':'');drawTimeline();
    }catch(error){if(sequence===timelineSequence)timelineSummary.textContent=error.message;}
    finally{if(sequence===timelineSequence)timelineBusy=false;requestFit(true);}
  }
  timelineDate.addEventListener('change',()=>loadTimeline());
  new ResizeObserver(requestFit).observe(timelineView);
  new ResizeObserver(requestFit).observe(q('.sq-main-view'));new ResizeObserver(requestFit).observe(q('.sq-settings'));window.addEventListener('resize',requestFit);
  async function poll(){if(!bridge||pollBusy||pending||prefsPending)return;pollBusy=true;const epoch=dataEpoch;try{const snapshot=await call('snapshot');if(epoch===dataEpoch&&!pending)applySnapshot(snapshot);}catch(error){if(epoch===dataEpoch&&!pending)feedback('刷新失败，保留现有内容：'+error.message,true);}finally{pollBusy=false;}}
  async function ready(){if(bridge)return;bridge=window.pywebview?.api;if(!bridge)return;icons();await poll();setInterval(poll,2000);setInterval(()=>{if(state.timeline&&!state.desktop.minimized)loadTimeline(false);},2000);}
  window.addEventListener('pywebviewready',ready);if(window.pywebview?.api)ready();
})();

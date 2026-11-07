  function progressNode(progress,waiting=false){
    const area=el('div','sq-task-progress'+(waiting?' sq-progress-waiting':''));
    const track=el('div','sq-progress-track');track.setAttribute('role','progressbar');track.setAttribute('aria-label','任务进度');track.setAttribute('aria-valuetext',progress.label);
    if(progress.low!==null){track.setAttribute('aria-valuemin','0');track.setAttribute('aria-valuemax','100');track.setAttribute('aria-valuenow',(progress.low+progress.high)/2);
      const fill=el('span','sq-progress-fill');fill.style.width=progress.low+'%';track.append(fill);
      if(progress.high>progress.low){const range=el('span','sq-progress-range');range.style.left=progress.low+'%';range.style.width=(progress.high-progress.low)+'%';track.append(range);}}
    area.append(track,el('span','sq-progress-label',progress.label));return area;
  }
  function idOf(task){return task.key+':'+task.id;}
  let requestSequence=0;
  function requestId(){
    try{if(globalThis.crypto?.randomUUID)return globalThis.crypto.randomUUID();}catch(error){}
    const values=new Uint32Array(4);
    try{globalThis.crypto.getRandomValues(values);return 'sq-'+Array.from(values,n=>n.toString(16).padStart(8,'0')).join('');}catch(error){}
    return 'sq-'+Date.now().toString(36)+'-'+(++requestSequence).toString(36)+'-'+Math.random().toString(36).slice(2);
  }
  function taskRequest(task,patch){return {request_id:requestId(),key:task.key,id:task.id,title:task.title,...patch};}
  let lastTaskPointer=null;
  root.addEventListener('pointerdown',event=>{lastTaskPointer={x:event.clientX,y:event.clientY,target:event.target,time:performance.now()};},{capture:true});
  function effectPoint(options){
    const control=options.control, event=options.event;
    if(event&&event.detail>0&&Number.isFinite(event.clientX)&&Number.isFinite(event.clientY))return {x:event.clientX,y:event.clientY};
    if(lastTaskPointer&&performance.now()-lastTaskPointer.time<1200&&control?.contains(lastTaskPointer.target))return {x:lastTaskPointer.x,y:lastTaskPointer.y};
    const box=control?.getBoundingClientRect()||{left:innerWidth/2,top:innerHeight/2,width:0,height:0};return {x:box.left+box.width/2,y:box.top+box.height/2};
  }
  function celebrate(point){
    if(reduced())return;
    const layer=el('div','sq-complete-effects');layer.setAttribute('aria-hidden','true');
    const x=Math.max(28,Math.min(innerWidth-28,point.x)),y=Math.max(28,Math.min(innerHeight-28,point.y));
    layer.style.left=x+'px';layer.style.top=y+'px';document.body.append(layer);
    const ring=el('span','sq-complete-ring');layer.append(ring);
    ring.animate?.([{transform:'translate(-50%,-50%) scale(.12)',opacity:0},{offset:.18,transform:'translate(-50%,-50%) scale(.5)',opacity:.95},{transform:'translate(-50%,-50%) scale(1)',opacity:0}],{duration:500,easing:'cubic-bezier(.16,1,.3,1)',fill:'forwards'});
    [-155,-100,-45,10,65,120].forEach((degrees,group)=>{
      const angle=degrees*Math.PI/180,cx=Math.cos(angle)*28,cy=Math.sin(angle)*28;
      for(let k=0;k<12;k++){
        const theta=(k*30+group*11)*Math.PI/180,dx=Math.cos(theta)*22,dy=Math.sin(theta)*22;
        const spark=el('span','sq-complete-spark');spark.style.left=cx+'px';spark.style.top=cy+'px';spark.style.rotate=(k*30+group*11)+'deg';const sparkColor=['#f3bf6b','#ee92aa','#b5a0ef','#88c1f2','#87d8cb','#e0eaf8'][group];spark.style.background=sparkColor;spark.style.color=sparkColor;layer.append(spark);
        spark.animate?.([{transform:'translate(0,0) scale(.2)',opacity:0},{offset:.15,transform:'translate('+dx*.3+'px,'+dy*.3+'px) scale(1)',opacity:1},{transform:'translate('+dx+'px,'+dy+'px) scale(.1)',opacity:0}],{duration:720,delay:100+group*45,easing:'cubic-bezier(.2,.6,.4,1)',fill:'forwards'});
      }
    });
    setTimeout(()=>layer.remove(),1300);
  }
  async function retireTask(node,onAnimation=null){
    if(!node?.isConnected||reduced()||!node.animate)return ()=>{};
    const height=node.getBoundingClientRect().height,style=getComputedStyle(node);
    const pt=parseFloat(style.paddingTop)||0,pb=parseFloat(style.paddingBottom)||0,mt=parseFloat(style.marginTop)||0,mb=parseFloat(style.marginBottom)||0;
    const oldOverflow=node.style.overflow;node.style.overflow='hidden';node.classList.add('sq-completed-leaving');
    const animation=node.animate([
      {offset:0,height:height+'px',paddingTop:pt+'px',paddingBottom:pb+'px',marginTop:mt+'px',marginBottom:mb+'px',opacity:1,clipPath:'inset(0 0 0 0)',easing:'cubic-bezier(.55,0,.85,.45)'},
      {offset:.22,height:height*.97+'px',paddingTop:pt*.97+'px',paddingBottom:pb*.97+'px',marginTop:mt*.97+'px',marginBottom:mb*.97+'px',opacity:1,clipPath:'inset(0 0 0 0)',easing:'cubic-bezier(.55,.03,.85,.55)'},
      {offset:.86,height:height*.06+'px',paddingTop:'0px',paddingBottom:'0px',marginTop:'0px',marginBottom:'0px',opacity:.12,clipPath:'inset(0 0 65% 0)',easing:'cubic-bezier(.16,1,.3,1)'},
      {offset:1,height:'0px',paddingTop:'0px',paddingBottom:'0px',marginTop:'0px',marginBottom:'0px',opacity:0,clipPath:'inset(0 0 100% 0)'}
    ],{duration:740,fill:'forwards'});
    onAnimation?.(animation);
    try{await animation.finished;}catch(error){}
    return ()=>{animation.cancel();node.style.overflow=oldOverflow;node.classList.remove('sq-completed-leaving');};
  }
  function localTaskError(node,message){
    if(!node?.isConnected)return;
    node.querySelector('.sq-action-error')?.remove();const error=el('p','sq-action-error',message);error.setAttribute('role','alert');node.append(error);requestFit(true);
  }
  async function changeTask(task,patch,options={}){
    if(pending||cardDrag||cardOrderSaving)return;
    const point=effectPoint(options),node=options.node||options.control?.closest('.sq-task')||null;
    node?.querySelector('.sq-action-error')?.remove();
    pending=true;savingNode=node;dataEpoch++;setHold('save',true);setSaving(true);feedback('正在保存…');
    let cleanup=()=>{};
    try{
      const result=await call('task_action',taskRequest(task,patch));
      if(!result.snapshot){feedback('任务已保存，界面刷新暂未成功，请稍后核对',true);return;}
      const candidates=[result.snapshot?.current,...(result.snapshot?.others||[]),...(result.snapshot?.history||[])].filter(Boolean);
      const saved=candidates.find(item=>item.key===task.key&&String(item.id)===String(task.id));
      const confirmed=patch.kind==='task'?saved?.status===(patch.done?'done':'active'):saved?.steps?.[patch.step]?.done===patch.done;
      if(!confirmed)throw Error('保存结果尚未确认，请刷新后核对，暂不播放完成效果');
      const completed=saved.status==='done'&&task.status!=='done';
      if(options.control?.type==='checkbox')options.control.checked=patch.done;
      if(patch.done&&!result.lateConfirmed)celebrate(point);
      if(completed){
        node?.classList.add('sq-completion-ack');
        node?.querySelectorAll('.sq-progress-fill').forEach(fill=>fill.style.width='100%');
        node?.querySelectorAll('.sq-progress-range').forEach(fill=>fill.style.width='0%');
        try{cleanup=await retireTask(node);}catch(error){}
      }
      applySnapshot(result.snapshot);cleanup();node?.classList.remove('sq-completion-ack');
      feedback(completed?'已完成，已移入完成历史':'已保存',false,result.undo);
    }catch(error){
      cleanup();node?.classList.remove('sq-completion-ack');
      feedback(error.message,true);localTaskError(node,error.message);pending=false;await poll();
    }finally{pending=false;savingNode=null;setSaving(false);setHold('save',false);requestFit(true);}
  }
  function setSaving(value){root.querySelectorAll('[data-save-control]').forEach(control=>control.disabled=value);q('[data-action=complete]').disabled=value||!state.current;}
  function checkbox(task,step,index){
    const label=el('label'),input=el('input');input.type='checkbox';input.checked=step.done;input.dataset.saveControl='true';input.disabled=pending;
    input.addEventListener('change',()=>{const desired=input.checked;input.checked=step.done;changeTask(task,{kind:'step',step:index,step_text:step.text,done:desired},{control:input,node:input.closest('.sq-task')||q('.sq-focus')});});
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
    const article=el('article','sq-task'),heading=el('div','sq-task-heading');article.dataset.level=taskLevel(task);article.dataset.cardId=idOf(task);
    const complete=el('button','sq-check');complete.type='button';complete.dataset.saveControl='true';complete.setAttribute('aria-label','标记“'+task.title+'”完成');complete.append(icon('check'));
    complete.addEventListener('click',event=>{event.preventDefault();changeTask(task,{kind:'task',done:true},{event,control:complete,node:article});});
    const title=el('button','sq-task-name',task.title),details=el('div','sq-task-details');
    title.type='button';title.setAttribute('aria-expanded',String(detailOpen.has(idOf(task))));details.hidden=!detailOpen.has(idOf(task));
    title.addEventListener('click',()=>{details.hidden=!details.hidden;title.setAttribute('aria-expanded',String(!details.hidden));if(details.hidden)detailOpen.delete(idOf(task));else detailOpen.add(idOf(task));requestFit();});
    const label=task.status==='waiting'?'等待回复':task.completion_candidate?'待确认'+(taskLevel(task)!=='unknown'?' · '+levelLabel(task):''):(task.key==='main_quests'?'主线 · ':'')+levelLabel(task);
    heading.append(complete,title,el('span',task.status==='waiting'?'sq-waiting':'sq-priority',label));
    const note=[task.note,task.progress_basis?'估算依据：'+task.progress_basis:''].filter(Boolean).join('\n');
    if(note)details.append(el('p','sq-note',note));
    (task.steps||[]).forEach((step,index)=>details.append(checkbox(task,step,index)));
    if(!note&&!task.steps?.length)details.append(el('p','','暂无补充说明'));
    article.append(heading,el('p','',task.live),progressNode(task.progress,task.status==='waiting'),details);attachCardGrip(article,task);attachTextPress(article);return article;
  }
  function renderOthers(){
    const signature=JSON.stringify([state.others,state.more,state.prefs.cardOrder]);if(signature===othersSignature)return;
    othersSignature=signature;const list=listInner;list.replaceChildren();
    const ordered=orderedCards();const visible=state.more?ordered:ordered.slice(0,3);
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
    state.health=snapshot.health||{};state.serviceBusy=!!state.health.busy;state.paused=!!snapshot.paused;state.resting=!!snapshot.resting;state.others=snapshot.others;state.historyRows=snapshot.history;
    if(!prefsPending)applyPrefs(snapshot.prefs,!initialized);initialized=true;applyDesktop(snapshot.desktop);
    renderMain(snapshot.current);renderOthers();renderHistory();
    text('[data-next]',snapshot.suggestion);text('.sq-observation p',snapshot.activity);
    const date=snapshot.updated_at?new Date(snapshot.updated_at):null;
    text('[data-updated]',date&&!Number.isNaN(date.getTime())?'更新于 '+date.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'}):state.health.lastSuccess?'识别于 '+new Date(state.health.lastSuccess).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'}):'等待首次识别');
    if(controlNotice&&!state.serviceBusy){controlNotice=false;if(state.health.error)feedback('后台切换失败：'+state.health.error,true);else if(state.paused)feedback('已暂停后台');else if(state.health.running)feedback('已启动后台，正在等待识别结果');else feedback('后台未就绪，请查看后台状态',true);}
    if(snapshot.error){feedback(snapshot.error,true);feedbackKind='read';}else if(feedbackKind==='read'){q('.sq-feedback').hidden=true;feedbackKind='';}
    if(snapshot.summaryError&&snapshot.summaryError!==lastSummaryError)feedback('日报生成失败：'+snapshot.summaryError,true);
    lastSummaryError=snapshot.summaryError;
    renderChrome();syncTaskList(true);settleInitialSteps();requestFit();
  }
  function renderChrome(){
    text('[data-status]',state.serviceBusy?'切换中':!state.health.checkedAt?'核验中':state.health.stale?'待核验':state.health.error?'后台异常':state.paused?'已暂停':state.health.lastEngineError?'识别异常':state.health.enginePhase==='starting'?'后台准备中':state.health.enginePhase==='analyzing'?'识别中':!state.health.running?'后台未运行':state.resting?'自动休息':'观察中');q('.sq-dot').style.background=state.paused||!state.health.running?'var(--sq-gold)':'var(--sq-green)';updateHealthView();
    const pause=q('[data-action=pause]');pause.setAttribute('aria-pressed',String(state.paused));pause.setAttribute('aria-label',state.paused?'继续观察':'暂停观察');pause.dataset.tooltip=state.paused?'继续观察':'暂停观察';buttonIcon(pause,state.paused||!state.health.running?'play':'pause');pause.disabled=state.serviceBusy;pause.dataset.tooltip=state.serviceBusy?'后台切换中':!state.health.running?'启动后台':state.paused?'继续观察':'暂停观察';pause.setAttribute('aria-label',pause.dataset.tooltip);
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
  const healthView=el('details','sq-health'),healthHeading=el('summary','','后台状态'),healthText=el('p','');healthView.append(healthHeading,healthText);q('.sq-settings').insertBefore(healthView,q('.sq-settings .sq-return'));
  const engineNotice=el('p','sq-engine-notice');engineNotice.hidden=true;q('.sq-main-view').insertBefore(engineNotice,q('.sq-feedback'));
  function updateHealthView(){
    const h=state.health||{},status=role=>h.workers?.[role]?.length?'运行中':'未运行或待核验';
    const success=h.lastSuccess?new Date(h.lastSuccess).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'暂无成功识别记录';
    const lines=['窗口监测：'+status('win_watch'),'任务识别：'+status('llm_engine'),'最近成功识别：'+success+(h.successSource==='engine-log'?'（日志记录）':''),h.busy?'正在'+(h.operation||'切换后台'):'',h.error?'状态核验：'+h.error:'',h.lastEngineError?'识别提示：'+h.lastEngineError:''].filter(Boolean).join('\n');
    if(healthText.textContent!==lines)healthText.textContent=lines;engineNotice.hidden=state.paused||!h.lastEngineError;if(!engineNotice.hidden)engineNotice.textContent=h.lastEngineError;
  }

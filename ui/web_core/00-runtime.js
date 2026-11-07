  'use strict';
  const root=document.getElementById('sidequest-app-main'), q=s=>root.querySelector(s);
  const win=q('.sq-window'), viewport=q('.sq-viewport'), toolbar=q('.sq-toolbar'), grip=q('.sq-resize-handle');
  const reduced=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
  const state={expanded:true,stepsOpen:false,settings:false,timeline:false,history:false,more:false,current:null,others:[],historyRows:[],prefs:{},desktop:{},paused:false,health:{},serviceBusy:false};
  const skins={glass:['#14171f','#232a38','#f1f5fc','#a8b7cc','#ffd166','#7de3f4','#5be3a2','#38465c'],transparent:['#182330','#2b3c4e','#ffffff','#cfdaea','#ffe1a0','#b3efff','#92efc3','#506479'],journal:['#f4efe3','#eae1ce','#342e29','#6b6054','#96623b','#396c73','#3c7052','#c6b9a2','#c6b9a2'],night:['#101b25','#1c2e3c','#edf8ff','#abc4d6','#8ae8ff','#c0b3ff','#68edb8','#3e566a']};
  const priorityPalettes={glass:['#9bbce8','#cbbfa3','#94a6be','#8bc8c2','#92cbb1'],transparent:['#a7c6ed','#d5c6a8','#a4b3c7','#a0d4ce','#9dcfb8'],journal:['#365d8a','#735b35','#526d7b','#386d69','#3f7056'],night:['#9ebee8','#c9c0aa','#9aaec5','#93cac4','#98cbb7']};
  function taskLevel(task){if(!task)return 'unknown';if(task.status==='done')return 'done';if(task.status==='waiting')return 'wait';const priority=String(task.priority||'').trim().toLowerCase();return ['high','mid','low'].includes(priority)?priority:'unknown';}
  function levelLabel(task){return {high:'高优先级',mid:'中优先级',low:'低优先级',wait:'等待回复',done:'已完成',unknown:'未分级'}[taskLevel(task)];}
  const holds=new Set(), detailOpen=new Set();
  let bridge=null, pollBusy=false, pending=false, undoToken=null, initialized=false,dataEpoch=0;
  let cardDrag=null,cardOrderSaving=false,cardPress=null,cardTouchScroll=null,cardClickUntil=0;
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
  let uncertainOperation=null,savingNode=null;
  const reconcileButton=el('button','sq-text-button','核对保存结果');reconcileButton.type='button';reconcileButton.hidden=true;q('.sq-feedback').append(reconcileButton);
  function resultOrError(result){if(!result||!result.ok)throw Error(result?.error||'操作未完成，请核对');return result;}
  function deadline(promise,ms){return new Promise((resolve,reject)=>{const timer=setTimeout(()=>{const error=Error('操作等待超时，请核对状态；没有自动重发');error.code='TIMEOUT';reject(error);},ms);Promise.resolve(promise).then(value=>{clearTimeout(timer);resolve(value);},error=>{clearTimeout(timer);reject(error);});});}
  async function call(method,...args){
    if(!bridge)throw Error('桌面连接尚未就绪');
    if(method!=='task_action'&&method!=='undo')return resultOrError(await deadline(bridge[method](...args),8000));
    const kind=method==='task_action'?'task':'undo',id=kind==='task'?args[0].request_id:String(args[0]);
    return new Promise((resolve,reject)=>{
      let settled=false,timedOut=false;
      const finish=(result,error)=>{
        if(settled)return;settled=true;clearTimeout(timer);
        if(uncertainOperation?.id===id){uncertainOperation=null;reconcileButton.hidden=true;q('.sq-feedback').append(reconcileButton);}
        if(error){reject(error);return;}
        try{const value=resultOrError(result);if(timedOut)value.lateConfirmed=true;resolve(value);}catch(error){reject(error);}
      };
      const timer=setTimeout(()=>{
        timedOut=true;uncertainOperation={kind,id,finish};
        feedback('保存结果待核对，不会自动重复提交',true);reconcileButton.hidden=false;
        if(savingNode?.isConnected){localTaskError(savingNode,'保存仍在等待，请点“核对保存结果”。');savingNode.append(reconcileButton);}
      },12000);
      Promise.resolve().then(()=>bridge[method](...args)).then(result=>finish(result),error=>finish(null,error));
    });
  }
  reconcileButton.addEventListener('click',async()=>{
    const operation=uncertainOperation;if(!operation)return;reconcileButton.disabled=true;
    try{
      const response=resultOrError(await deadline(bridge.resolve_operation(operation.kind,operation.id),8000));
      if(response.state==='committed')operation.finish(response.result);
      else if(response.state==='cancelled')operation.finish(null,Error(response.error||'该操作已取消，可以重新操作'));
    }catch(error){feedback(error.message,true);reconcileButton.hidden=false;}
    finally{reconcileButton.disabled=false;}
  });
  let feedbackTimer=null,feedbackAnimation=null,feedbackVersion=0;
  function feedback(message,error=false,token=null){
    feedbackVersion++;clearTimeout(feedbackTimer);feedbackTimer=null;
    if(feedbackAnimation){feedbackAnimation.cancel();feedbackAnimation=null;}
    const panel=q('.sq-feedback');panel.style.overflow='';panel.classList.remove('sq-completed-leaving');panel.hidden=false;panel.dataset.error=String(error);
    panel.setAttribute('role',error?'alert':'status');text('[data-message]',message);
    undoToken=token;q('[data-action=undo]').hidden=!token;feedbackKind=error?'error':'action';requestFit(true);
    if(!error&&(token||String(message).startsWith('已'))){
      const version=feedbackVersion;
      async function dismiss(){
        if(version!==feedbackVersion||panel.hidden)return;
        if(pending||cardDrag||cardOrderSaving){feedbackTimer=setTimeout(dismiss,700);return;}
        let cleanup=()=>{};try{cleanup=await retireTask(panel,animation=>{feedbackAnimation=animation;});}catch(error){}
        if(version===feedbackVersion){panel.hidden=true;undoToken=null;q('[data-action=undo]').hidden=true;feedbackKind='';feedbackAnimation=null;}
        cleanup();requestFit(true);
      }
      feedbackTimer=setTimeout(dismiss,10000);
    }
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

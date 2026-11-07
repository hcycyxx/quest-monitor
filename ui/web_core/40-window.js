  // Coalesce pointer updates; release commits only after the latest move reaches the native host.
  let geometryPayload=null,geometryBusy=false,geometryEnded=false;
  async function pumpGeometry(){if(geometryBusy||!geometryPayload)return;geometryBusy=true;while(geometryPayload){const payload=geometryPayload;geometryPayload=null;try{await call('window_action','geometry',payload);}catch(error){feedback(error.message,true);}}geometryBusy=false;if(geometryEnded){geometryEnded=false;await call('window_action','geometry',{phase:'end',dock:geometry?.kind==='move'}).catch(error=>feedback(error.message,true));geometry=null;setHold('gesture',false);requestFit(true);}}
  function beginGeometry(event,kind){if(cardDrag||cardOrderSaving||geometry||geometryBusy||geometryEnded||event.button!==0||(kind==='move'&&event.target.closest('button,input,summary,a')))return;event.preventDefault();stopScroll();menu(false);setHold('gesture',true);const d=state.desktop;geometry={kind,id:event.pointerId,element:event.currentTarget,startX:event.screenX,startY:event.screenY,x:d.x,y:d.y,width:innerWidth,height:innerHeight};event.currentTarget.setPointerCapture(event.pointerId);}
  function moveGeometry(event){if(!geometry||geometry.id!==event.pointerId)return;const dx=event.screenX-geometry.startX,dy=event.screenY-geometry.startY;geometryPayload=geometry.kind==='move'?{phase:'move',x:geometry.x+dx,y:geometry.y+dy}:{phase:'resize',x:geometry.x,y:geometry.y,width:geometry.width+dx,height:geometry.height+dy};geometry.lastPayload=geometryPayload;pumpGeometry();}
  function endGeometry(event){if(geometryEnded||!geometry||(event.pointerId!==undefined&&event.pointerId!==geometry.id))return;const g=geometry;geometryEnded=true;if(g.element.hasPointerCapture(g.id))g.element.releasePointerCapture(g.id);if(!geometryPayload)geometryPayload=g.lastPayload||{phase:g.kind==='move'?'move':'resize',x:g.x,y:g.y,width:g.width,height:g.height};pumpGeometry();}
  toolbar.addEventListener('pointerdown',event=>beginGeometry(event,'move'));grip.addEventListener('pointerdown',event=>beginGeometry(event,'resize'));
  [toolbar,grip].forEach(target=>{target.addEventListener('pointermove',moveGeometry);target.addEventListener('pointerup',endGeometry);target.addEventListener('pointercancel',endGeometry);target.addEventListener('lostpointercapture',event=>{if(!geometryEnded)endGeometry(event);});});
  grip.addEventListener('keydown',async event=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key))return;event.preventDefault();const amount=event.shiftKey?24:8;try{await call('window_action','geometry',{phase:'resize',width:innerWidth+({'ArrowLeft':-amount,'ArrowRight':amount}[event.key]||0),height:innerHeight+({'ArrowUp':-amount,'ArrowDown':amount}[event.key]||0)});await call('window_action','geometry',{phase:'end',dock:false});requestFit();}catch(error){feedback(error.message,true);}});
  root.addEventListener('click',async event=>{const button=event.target.closest('[data-action]');if(!button)return;try{switch(button.dataset.action){
    case 'pause':if(state.serviceBusy)break;dataEpoch++;state.serviceBusy=true;button.disabled=true;try{const response=await call('pause',state.paused||!state.health.running?false:true);if(response.snapshot)applySnapshot(response.snapshot);else feedback(response.message||'后台正在切换');}catch(error){state.serviceBusy=false;button.disabled=false;throw error;}break;
    case 'pin':await savePrefs({pinned:state.prefs.pinned===false});break;
    case 'menu':menu(q('#sq-menu').hidden);break;
    case 'expand':stopScroll();state.expanded=!state.expanded;renderChrome();syncTaskList();await savePrefs({expanded:state.expanded});break;
    case 'complete':if(state.current)await changeTask(state.current,{kind:'task',done:true},{event,control:button,node:q('.sq-focus')});break;
    case 'undo':if(undoToken&&!pending&&!cardDrag&&!cardOrderSaving){pending=true;dataEpoch++;setSaving(true);setHold('save',true);try{const result=await call('undo',undoToken);applySnapshot(result.snapshot);feedback('已撤销');}finally{pending=false;setSaving(false);setHold('save',false);}}break;
    case 'history':state.history=!state.history;button.setAttribute('aria-expanded',String(state.history));renderChrome();requestFit();break;
    case 'settings':menu(false);state.timeline=false;state.settings=true;setHold('settings',true);renderChrome();requestFit();break;
    case 'back':state.timeline=false;state.settings=false;setHold('settings',false);renderChrome();requestFit();break;
    case 'timeline':menu(false);state.settings=false;setHold('settings',false);state.timeline=true;renderChrome();requestFit(true);loadTimeline();break;
    case 'cardreset':menu(false);await commitCardOrder([]);break;
    case 'details':await call('open_detail_settings');break;
    case 'summary':{const result=await call('summary');if(result.message)feedback(result.message);break;}
    case 'dock':menu(false);await savePrefs({autoHide:state.prefs.autoHide===false});break;
    case 'dockleft':case 'dockright':menu(false);applyDesktop((await call('window_action','dock',{side:button.dataset.action==='dockleft'?'left':'right'})).desktop);break;
    case 'resetgeometry':menu(false);applyDesktop((await call('window_action','reset')).desktop);requestFit();break;
    case 'minimize':applyDesktop((await call('window_action','minimize')).desktop);requestFit();break;
    case 'hide':menu(false);await call('window_action','hide');break;
    case 'close':{const result=await call('window_action','quit');if(result.queued)feedback('正在停止后台并退出…');break;}
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


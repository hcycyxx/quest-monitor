  function orderedCards(){
    const order=Array.isArray(state.prefs.cardOrder)?state.prefs.cardOrder:[],ranks=new Map(order.map((key,index)=>[key,index]));
    return state.others.map((task,index)=>({task,index})).sort((a,b)=>(ranks.get(idOf(a.task))??order.length+a.index)-(ranks.get(idOf(b.task))??order.length+b.index)).map(item=>item.task);
  }
  async function commitCardOrder(order){
    if(cardOrderSaving||pending||cardDrag||prefsPending)return;cardOrderSaving=true;dataEpoch++;prefsPending++;setHold('reorder',true);
    const old=state.prefs.cardOrder||[];state.prefs.cardOrder=order;
    try{const result=await call('preferences',{cardOrder:order});applyPrefs(result.prefs);feedback('已保存卡片顺序');}
    catch(error){state.prefs.cardOrder=old;feedback(error.message,true);}
    finally{cardOrderSaving=false;prefsPending--;setHold('reorder',false);othersSignature='';renderOthers();requestFit(true);}
  }
  function attachCardGrip(article,task){
    const grip=el('button','sq-card-grip');grip.type='button';grip.setAttribute('aria-label','调整“'+task.title+'”的位置');grip.title='长按文字或拖动把手排序；Alt＋上下键调整位置';grip.append(icon('grip-vertical'));article.append(grip);
    grip.addEventListener('pointerdown',event=>beginCardDrag(event,article));
    grip.addEventListener('pointermove',event=>{if(cardDrag&&cardDrag.pointer===event.pointerId){cardDrag.y=event.clientY;moveCardGhost();placeCardPlaceholder();}});
    grip.addEventListener('pointerup',event=>finishCardDrag(event,false));grip.addEventListener('pointercancel',event=>finishCardDrag(event,true));
    grip.addEventListener('lostpointercapture',event=>{if(cardDrag&&cardDrag.pointer===event.pointerId)finishCardDrag(event,true);});
    grip.addEventListener('keydown',async event=>{
      if(!event.altKey||!['ArrowUp','ArrowDown'].includes(event.key)||pending||cardOrderSaving||cardDrag)return;
      event.preventDefault();event.stopPropagation();const order=orderedCards().map(idOf),index=order.indexOf(idOf(task)),next=index+(event.key==='ArrowUp'?-1:1);
      if(next<0||next>=order.length)return;[order[index],order[next]]=[order[next],order[index]];await commitCardOrder(order);
    });
  }

  // CRM card-sort behavior: 300ms pickup, 8px pre-pickup cancellation, 250ms click swallowing.
  function cancelCardPress(){
    if(cardPress){clearTimeout(cardPress.timer);cardPress.article.classList.remove('sq-card-press');cardPress=null;}
    setHold('cardpress',false);
  }
  function attachTextPress(article){
    article.querySelector('.sq-task-name').title='单击展开详情；长按0.3秒拖动卡片';
    article.addEventListener('pointerdown',event=>{
      if(event.button!==0||pending||prefsPending||cardDrag||cardOrderSaving||geometry)return;
      if(event.target.closest('input,label,select,textarea,a,[contenteditable=true],.sq-card-grip,.sq-check'))return;
      const button=event.target.closest('button');if(button&&!button.classList.contains('sq-task-name'))return;
      cancelCardPress();stopScroll();event.stopPropagation();dataEpoch++;setHold('cardpress',true);
      const capture=article.querySelector('.sq-task-name');
      const press={article,capture,pointer:event.pointerId,x:event.clientX,y:event.clientY,lastX:event.clientX,lastY:event.clientY,touch:event.pointerType==='touch',timer:null};
      article.classList.add('sq-card-press');cardPress=press;
      press.timer=setTimeout(()=>{
        if(cardPress!==press)return;if(!article.isConnected){cancelCardPress();return;}
        cancelCardPress();globalThis.getSelection?.()?.removeAllRanges();
        beginCardDrag({button:0,pointerId:press.pointer,clientX:press.lastX,clientY:press.lastY,currentTarget:capture,preventDefault(){},stopPropagation(){}},article);
        if(cardDrag){cardDrag.fromText=true;cardClickUntil=performance.now()+250;}
      },300);
    });
  }
  window.addEventListener('pointerdown',()=>{cancelCardPress();cardTouchScroll=null;},{capture:true});
  window.addEventListener('pointermove',event=>{
    if(cardTouchScroll&&cardTouchScroll.pointer===event.pointerId){
      viewport.scrollTop+=cardTouchScroll.y-event.clientY;cardTouchScroll.y=event.clientY;
      if(event.cancelable)event.preventDefault();return;
    }
    if(cardPress&&cardPress.pointer===event.pointerId){
      const press=cardPress;press.lastX=event.clientX;press.lastY=event.clientY;
      if(Math.hypot(event.clientX-press.x,event.clientY-press.y)>8){
        const touch=press.touch,lastY=press.y;cancelCardPress();
        if(touch){cardTouchScroll={pointer:event.pointerId,y:event.clientY};viewport.scrollTop+=lastY-event.clientY;cardClickUntil=performance.now()+250;if(event.cancelable)event.preventDefault();}
      }
    }
    if(cardDrag&&cardDrag.fromText&&cardDrag.pointer===event.pointerId){cardDrag.y=event.clientY;moveCardGhost();placeCardPlaceholder();if(event.cancelable)event.preventDefault();}
  },{passive:false});
  window.addEventListener('pointerup',event=>{
    cancelCardPress();if(cardTouchScroll?.pointer===event.pointerId){cardTouchScroll=null;cardClickUntil=performance.now()+250;}
    if(cardDrag&&cardDrag.fromText&&cardDrag.pointer===event.pointerId)finishCardDrag(event,false);
  });
  window.addEventListener('pointercancel',event=>{cancelCardPress();cardTouchScroll=null;if(cardDrag?.pointer===event.pointerId)finishCardDrag(event,true);});
  window.addEventListener('blur',()=>{cancelCardPress();cardTouchScroll=null;});
  window.addEventListener('keydown',event=>{if(event.key==='Escape')cancelCardPress();},{capture:true});
  window.addEventListener('wheel',event=>{
    cancelCardPress();
    if(cardDrag){event.preventDefault();event.stopImmediatePropagation();viewport.scrollTop+=event.deltaY*(event.deltaMode===1?16:event.deltaMode===2?viewport.clientHeight:1);placeCardPlaceholder();}
  },{passive:false,capture:true});
  document.addEventListener('click',event=>{if(performance.now()<cardClickUntil){event.preventDefault();event.stopImmediatePropagation();}},{capture:true});
  function beginCardDrag(event,article){
    if(event.button!==0||pending||prefsPending||cardOrderSaving||cardDrag||geometry)return;
    event.preventDefault();event.stopPropagation();stopScroll();menu(false);dataEpoch++;setHold('reorder',true);setSaving(true);
    const box=article.getBoundingClientRect(),style=getComputedStyle(article),placeholder=el('div','sq-card-placeholder');
    placeholder.style.height=box.height+'px';placeholder.setAttribute('aria-hidden','true');
    cardDrag={article,placeholder,pointer:event.pointerId,grip:event.currentTarget,startOffset:event.clientY-box.top,y:event.clientY,oldStyle:article.style.cssText,fullOrder:orderedCards().map(idOf),raf:0,time:performance.now()};
    const fontSize=style.fontSize;article.replaceWith(placeholder);root.append(article);article.classList.add('sq-card-dragging');
    Object.assign(article.style,{position:'fixed',left:box.left+'px',top:box.top+'px',width:box.width+'px',height:box.height+'px',margin:'0',fontSize,zIndex:'60'});
    try{event.currentTarget.setPointerCapture(event.pointerId);}catch(error){finishCardDrag({pointerId:event.pointerId},true);return;}event.currentTarget.focus({preventScroll:true});
    function scrollFrame(now){
      if(!cardDrag)return;const d=cardDrag,dt=Math.min((now-d.time)/1000,.04);d.time=now;const area=viewport.getBoundingClientRect();
      const velocity=d.y<area.top+45?-300*Math.min(1,(area.top+45-d.y)/45):d.y>area.bottom-45?300*Math.min(1,(d.y-area.bottom+45)/45):0;
      if(velocity){viewport.scrollTop+=velocity*dt;placeCardPlaceholder();}moveCardGhost();d.raf=requestAnimationFrame(scrollFrame);
    }
    cardDrag.raf=requestAnimationFrame(scrollFrame);
  }
  function moveCardGhost(){if(cardDrag)cardDrag.article.style.top=(cardDrag.y-cardDrag.startOffset)+'px';}
  const cardShiftAnimations=new WeakMap();
  function placeCardPlaceholder(){
    if(!cardDrag)return;const d=cardDrag,cards=[...listInner.querySelectorAll(':scope > .sq-task')],before=new Map(cards.map(card=>[card,card.getBoundingClientRect().top]));
    const target=cards.find(card=>d.y<card.getBoundingClientRect().top+card.getBoundingClientRect().height/2);
    const more=[...listInner.children].find(node=>node.tagName==='BUTTON');
    const next=target||more||null;if(d.placeholder.nextElementSibling===next)return;
    listInner.insertBefore(d.placeholder,next);
    if(!reduced())cards.forEach(card=>{const delta=before.get(card)-card.getBoundingClientRect().top;if(Math.abs(delta)<.5)return;cardShiftAnimations.get(card)?.cancel();const animation=card.animate([{transform:'translateY('+delta+'px)'},{transform:'translateY(0)'}],{duration:240,easing:'cubic-bezier(.16,1,.3,1)'});cardShiftAnimations.set(card,animation);});
  }
  async function finishCardDrag(event,cancel){
    if(!cardDrag||(event.pointerId!==undefined&&event.pointerId!==cardDrag.pointer))return;
    const d=cardDrag;cardDrag=null;cardClickUntil=performance.now()+250;cancelAnimationFrame(d.raf);
    if(d.grip.hasPointerCapture(d.pointer))d.grip.releasePointerCapture(d.pointer);
    const floatingTop=d.article.getBoundingClientRect().top;d.placeholder.replaceWith(d.article);d.article.classList.remove('sq-card-dragging');d.article.style.cssText=d.oldStyle;
    setSaving(false);
    if(cancel){setHold('reorder',false);othersSignature='';renderOthers();requestFit(true);return;}
    const visible=[...listInner.querySelectorAll(':scope > .sq-task')].map(card=>card.dataset.cardId),set=new Set(visible);
    if(!reduced()){cardOrderSaving=true;try{const delta=floatingTop-d.article.getBoundingClientRect().top;await d.article.animate([{transform:'translateY('+delta+'px)'},{transform:'translateY(0)'}],{duration:240,easing:'cubic-bezier(.16,1,.3,1)'}).finished;}catch(error){}finally{cardOrderSaving=false;}}
    if(prefsPending)await prefsQueue;
    await commitCardOrder([...visible,...d.fullOrder.filter(key=>!set.has(key))]);
  }
  root.addEventListener('keydown',event=>{if(event.key==='Escape'&&cardDrag){event.preventDefault();event.stopImmediatePropagation();finishCardDrag({pointerId:cardDrag.pointer},true);}},{capture:true});
  window.addEventListener('blur',()=>{if(cardDrag)finishCardDrag({pointerId:cardDrag.pointer},true);});
  const resetCardOrder=el('button','sq-menu-item','恢复优先级排序');resetCardOrder.type='button';resetCardOrder.dataset.action='cardreset';q('#sq-menu').append(resetCardOrder);

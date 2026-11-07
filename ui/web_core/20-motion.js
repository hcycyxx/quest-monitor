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


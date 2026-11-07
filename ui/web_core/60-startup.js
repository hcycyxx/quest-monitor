  new ResizeObserver(requestFit).observe(timelineView);
  new ResizeObserver(requestFit).observe(q('.sq-main-view'));new ResizeObserver(requestFit).observe(q('.sq-settings'));window.addEventListener('resize',requestFit);
  async function poll(){if(!bridge||pollBusy||pending||prefsPending||cardPress||cardDrag||cardOrderSaving)return;pollBusy=true;const epoch=dataEpoch;try{const snapshot=await call('snapshot');if(epoch===dataEpoch&&!pending&&!cardDrag&&!cardOrderSaving)applySnapshot(snapshot);}catch(error){if(epoch===dataEpoch&&!pending)feedback('刷新失败，保留现有内容：'+error.message,true);}finally{pollBusy=false;}}
  async function ready(){if(bridge)return;bridge=window.pywebview?.api;if(!bridge)return;icons();await poll();setInterval(poll,2000);setInterval(()=>{if(state.timeline&&!state.desktop.minimized)loadTimeline(false);},2000);}
  window.addEventListener('pywebviewready',ready);if(window.pywebview?.api)ready();

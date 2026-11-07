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
  let timelineBusy=false,timelineSequence=0,timelineData=null,timelineCursor=null,timelineWatermark=0;
  const timelineCache=new Map(),timelineNodes=new Map();let moreButton=null;
  const timelineTime=value=>new Date(value*1000).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit'});
  function duration(seconds){if(seconds===null||seconds===undefined)return '时长未记录';const n=Math.round(seconds);if(n<60)return n+'秒';if(n<3600)return Math.floor(n/60)+'分'+(n%60?n%60+'秒':'');return Math.floor(n/3600)+'小时'+Math.floor(n%3600/60)+'分';}
  function setText(node,value){if(node.textContent!==value)node.textContent=value;}
  function makeTimelineNode(row){
    const item=el('article','sq-timeline-row'),when=el('time','sq-timeline-time'),content=el('div','sq-timeline-content'),title=el('div','sq-timeline-title');content.append(title);item.append(when,content);
    const node={item,when,content,title};
    if(row.kind==='activity'){
      node.meta=el('p','sq-timeline-meta');node.track=el('div','sq-timeline-track');node.track.setAttribute('role','img');node.fill=el('span','sq-timeline-fill');node.track.append(node.fill);node.duration=el('p','sq-timeline-duration');content.append(node.meta,node.track,node.duration);
    }else{item.dataset.kind=row.kind;node.event=el('p','sq-timeline-event');content.append(node.event);}
    return node;
  }
  function drawTimeline(){
    if(!timelineData)return;const rows=[...timelineCache.values()].sort((a,b)=>b.start-a.start||b.id.localeCompare(a.id));const maximum=Math.max(1,timelineData.maxSeconds||1),live=new Set();
    rows.forEach((row,index)=>{
      let node=timelineNodes.get(row.id);if(!node){node=makeTimelineNode(row);timelineNodes.set(row.id,node);}live.add(row.id);
      setText(node.when,timelineTime(row.start));node.when.dateTime=new Date(row.start*1000).toISOString();setText(node.title,row.title);
      if(row.kind==='activity'){
        setText(node.meta,row.active?'正在停留 · 开始 '+timelineTime(row.start):'开始 '+timelineTime(row.start)+' · 至 '+timelineTime(row.end));
        const width=(row.seconds||0)/maximum*100+'%';if(node.fill.style.width!==width)node.fill.style.width=width;
        node.track.setAttribute('aria-label','窗口停留时长：'+duration(row.seconds));setText(node.duration,'停留 '+duration(row.seconds));
      }else{const labels={completed:'完成于 ',created:'任务建立于 ',reopened:'恢复为进行中 ',undone:'撤销任务操作 '};setText(node.event,(labels[row.kind]||'记录于 ')+timelineTime(row.start));}
      if(timelineRows.children[index]!==node.item)timelineRows.insertBefore(node.item,timelineRows.children[index]||null);
    });
    timelineNodes.forEach((node,id)=>{if(!live.has(id)){node.item.remove();timelineNodes.delete(id);}});
    timelineRows.querySelector('.sq-empty')?.remove();
    if(!rows.length)timelineRows.append(el('p','sq-empty','这一天暂无可用记录。'));
    if(timelineData.hasMore){if(!moreButton){moreButton=el('button','sq-text-button','显示更早的记录');moreButton.addEventListener('click',()=>loadTimeline(false,true));}timelineRows.append(moreButton);}else if(moreButton)moreButton.remove();
    requestFit();
  }
  async function loadTimeline(explicit=true,append=false){
    const selected=timelineDate.value;if(!selected||!bridge||(!explicit&&timelineBusy))return;
    const sequence=++timelineSequence;timelineBusy=true;
    if(explicit){timelineCache.clear();timelineCursor=null;timelineWatermark=0;timelineData=null;timelineRows.replaceChildren();timelineNodes.clear();timelineSummary.textContent='正在读取记录…';}
    try{
      const result=explicit||append?await call('timeline',selected,append?timelineCursor:null):await call('timeline_delta',selected,timelineWatermark);
      if(sequence!==timelineSequence||selected!==timelineDate.value)return;
      if(explicit||append){result.rows.forEach(row=>timelineCache.set(row.id,row));timelineCursor=result.nextCursor;if(explicit)timelineWatermark=result.watermark;timelineData={...timelineData,...result};}
      else{
        const existing=[...timelineCache.values()],oldest=existing.length?Math.min(...existing.map(row=>row.start)):0;
        result.rows.forEach(row=>{if(timelineCache.has(row.id)||!timelineData?.hasMore||row.start>=oldest)timelineCache.set(row.id,row);});
        timelineWatermark=result.watermark;timelineData={...timelineData,...result,hasMore:timelineData?.hasMore};
      }
      setText(timelineSummary,'窗口停留 '+duration(result.totalSeconds)+' · 完成记录 '+result.completedCount+' 条 · 最近在上方');setText(timelineNote,(result.error?result.error+'。':'')+result.note);drawTimeline();
    }catch(error){if(sequence===timelineSequence)setText(timelineSummary,error.message);}
    finally{if(sequence===timelineSequence)timelineBusy=false;requestFit();}
  }
  timelineDate.addEventListener('change',()=>loadTimeline());

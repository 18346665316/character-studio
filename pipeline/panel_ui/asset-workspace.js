'use strict';
(() => {
 const $=id=>document.getElementById(id),query=new URLSearchParams(location.search);
 const family=$('prop-result')?'prop':$('component-result')?'component':$('transition-result')?'transition':$('kit-result')?'terrain':null;
 if(!family)return;
 const detail=query.has('kit'),task=query.has('task'),results=document.querySelector('.terrain-results'),aside=document.querySelector('.terrain-layout>aside');
 const result=$({prop:'prop-result',component:'component-result',transition:'transition-result',terrain:'kit-result'}[family]);
 const create=(tag,text,cls)=>{const n=document.createElement(tag);if(text)n.textContent=text;if(cls)n.className=cls;return n;};
 const card=(title,text)=>{const n=create('section',null,'terrain-card');n.append(create('h2',title));if(text)n.append(create('p',text,'terrain-hint'));return n;};
 document.body.classList.add('asset-workspace');if(detail||task)document.body.classList.add('asset-context');
 const feedback=create('p',null,'asset-feedback');feedback.id='asset-feedback';feedback.setAttribute('role','status');feedback.hidden=true;results.prepend(feedback);
 const tabs=create('div',null,'asset-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','素材工作区');
 const labels={preview:'预览',...(detail&&family!=='component'?{adjust:'调整'}:{}),records:'来源与记录'},panels={},buttons={};
 const original=[...result.children];
 for(const [key,label]of Object.entries(labels)){
  const panel=create('section');panel.id='asset-panel-'+key;panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby','asset-tab-'+key);panels[key]=panel;
  const b=create('button',label);b.id='asset-tab-'+key;b.type='button';b.setAttribute('role','tab');b.setAttribute('aria-controls',panel.id);b.onclick=()=>select(key,true);buttons[key]=b;tabs.append(b);
 }
 // Records stay available when a task has not produced an asset.
 result.replaceChildren(panels.preview,...(panels.adjust?[panels.adjust]:[]));panels.preview.append(...original);result.before(tabs);result.after(panels.records);
 const historyId={prop:'prop-history',component:'component-history',transition:'transition-history',terrain:'kit-picker'}[family];
 const historyCard=card('相关版本','仅展示有明确来源关系的版本；其他素材请回素材库查看。'),historyLabel=create('label','相关版本');historyLabel.htmlFor=historyId;historyCard.append(historyLabel,$(historyId));panels.records.append(historyCard);
 if($('prop-filter'))$('prop-filter').hidden=true;
 const sourceCard=card('当前成果来源'),sourceInfo=create('dl',null,'asset-source');sourceCard.append(sourceInfo);panels.records.append(sourceCard);
 const jobs=$({prop:'prop-jobs',component:'component-jobs',terrain:'terrain-jobs'}[family]);
 if(jobs)panels.records.append(family==='terrain'?jobs.closest('details'):jobs.parentElement);
 const allTasks=create('a','查看全部生产任务 →');allTasks.href='/?view=tasks';panels.records.append(allTasks);
 const delivery=card('下载与接入','下载当前选中成果，包含图片、规格和接入说明。');delivery.id='asset-delivery';
 const download=$({prop:'prop-download',component:'component-download',transition:'transition-download',terrain:'download-kit'}[family]);delivery.append(download);panels.preview.append(delivery);
 const exportInfo=create('p',null,'terrain-hint');delivery.prepend(exportInfo);
 for(const id of ['prop-sprite','prop-integrity','component-meta','component-integrity','kit-meta','delivery-hint','transition-meta'])if($(id))delivery.append($(id));
 const waterLink=$('water-shore-link');if(waterLink){const next=card('后续制作','水面外观确认后，可使用当前水面制作水岸。');next.append(waterLink);panels.preview.append(next);const old=aside.querySelector('.terrain-card');if(old&&!old.querySelector('form'))old.remove();}
 if(family==='component'){
  const another=create('a','制作新围栏 →');another.href='/components.html';delivery.append(another);
  // Collision suggestions are a preview; no current-fence editing is offered.
 }else if(family==='prop'){
  if(panels.adjust){panels.adjust.append(original[1]);aside.hidden=true;original[1].querySelector('h2').after(create('p','场景与素材工作台共用同一锚点、碰撞编辑器和素材版本。','terrain-hint')); }
  else original[1].hidden=true;
 }else if(panels.adjust){
  panels.adjust.append(aside);aside.classList.add('asset-adjust-form');
  if(family==='terrain'){aside.classList.add('asset-remake-form');aside.querySelector('h2').textContent='用原材质制作新版本';$('reuse-materials').textContent='另存调整版本（不调用 AI）';$('reuse-materials').classList.add('primary');}
  else aside.querySelector('h2').textContent='调整来源，另存过渡素材';
 }
 for(const id of ['prop-status','component-status','form-status','transition-status'])if($(id))$(id).hidden=true;
 const adjustmentBoundary=panels.adjust?.querySelector('p:last-child');if(family==='prop'&&adjustmentBoundary?.textContent.includes('包含透明图片'))delivery.append(adjustmentBoundary);
 const draftForm=detail?$(family==='prop'?'prop-adjust':family==='terrain'?'kit-form':'transition-form'):null;
 const draftNote=create('p',null,'asset-draft-note');draftNote.setAttribute('role','status');draftNote.hidden=true;if(panels.adjust)panels.adjust.prepend(draftNote);
 for(const id of ['base-kit','overlay-kit'])$(id)?.addEventListener('change',()=>{if($('asset-source-warning')&&$('base-kit').value&&$('overlay-kit').value)$('asset-source-warning').hidden=true;});
 let activeId=null,restoring=false,currentKit=null,baseValues=null;
 const key=id=>'studio-asset-draft:'+location.pathname+':'+id;
 const fields=()=>draftForm?[...draftForm.querySelectorAll('input[id],select[id],textarea[id]')].filter(n=>!['file','submit','button'].includes(n.type)):[];
 const values=()=>Object.fromEntries(fields().map(n=>[n.id,n.type==='checkbox'?n.checked:n.value]));
 const storage={get(id){try{return JSON.parse(sessionStorage.getItem(key(id))||'null');}catch{return null;}},set(id,v){try{sessionStorage.setItem(key(id),JSON.stringify(v));return true;}catch{return false;}},remove(id){try{sessionStorage.removeItem(key(id));}catch{}}};
 function dirty(){if(!activeId||restoring||!draftForm)return;const v=values(),changed=JSON.stringify(v)!==JSON.stringify(baseValues);const stored=changed&&storage.set(activeId,v);if(!changed)storage.remove(activeId);draftNote.hidden=!changed;draftNote.textContent=stored?'有未保存修改 · 草稿已暂存在当前浏览器，另存后生效。':'有未保存修改 · 另存后生效。';}
 draftForm?.addEventListener('input',dirty);draftForm?.addEventListener('change',dirty);
 function status(message,error=false){feedback.textContent=message;feedback.className='asset-feedback'+(error?' terrain-error':'');feedback.hidden=!message;}
 function select(keyName,updateURL=false){
  if(!panels[keyName])keyName='preview';
  for(const name of Object.keys(panels)){panels[name].hidden=name!==keyName;buttons[name].setAttribute('aria-selected',String(name===keyName));buttons[name].tabIndex=name===keyName?0:-1;}
  document.body.dataset.assetTab=keyName;
  if(updateURL){const url=new URL(location.href);url.searchParams.set('tab',keyName);history.replaceState(null,'',url);}
 }
 const parent=k=>k.provenance?.parent_kit||k.source_kit;
 function versions(kits,id){if(!id)return[];const ids=new Set([id]);let changed=true;while(changed){changed=false;for(const k of kits){const p=parent(k);if(p&&(ids.has(k.id)||ids.has(p))){if(!ids.has(k.id)||!ids.has(p))changed=true;ids.add(k.id);ids.add(p);}}}return kits.filter(k=>ids.has(k.id));}
 function historyOptions(kits,id){const input=$(historyId),list=versions(kits,id);input.replaceChildren();for(const k of list){const o=create('option',(k.title||k.id)+' · '+k.id);o.value=k.id;input.append(o);}input.value=id||'';historyCard.hidden=!id||list.length<2;sourceCard.hidden=!id;}
 function saved(){if(activeId)storage.remove(activeId);draftNote.hidden=true;baseValues=values();}
 function openKit(id){location.assign(window.StudioProjectURL?.(location.pathname+'?kit='+encodeURIComponent(id))||location.pathname+'?kit='+encodeURIComponent(id));}
 function trackJob(id){saved();location.assign(window.StudioProjectURL?.(location.pathname+'?task='+encodeURIComponent(id))||location.pathname+'?task='+encodeURIComponent(id));}
 let lastJobState=null;
 function jobRow(row,job,kits,id){
  const requested=query.get('task'),related=versions(kits,id);
  row.hidden=task?job.id!==requested:detail?!related.some(k=>k.id===(job.kit_id||job.kit||job.id)):true;
  if(task&&job.id===requested){const state=JSON.stringify([job.id,job.status,job.stage,job.error]);if(state!==lastJobState){lastJobState=state;status((job.spec?.title?job.spec.title+'：':'')+(job.stage||job.status)+(job.error?'\n'+job.error:''),['failed','interrupted'].includes(job.status));}}
 }
 function jobsLoaded(items){if(task&&!items.some(j=>j.id===query.get('task')))status('此任务不在当前可用记录中，请回任务中心查看。',true);}
 window.StudioAssets={status,versions,historyOptions,openKit,trackJob,saved,select,jobRow,jobsLoaded};
 document.addEventListener('studio:asset',event=>{
  const k=event.detail;if(!k?.id)return;
  tabs.hidden=false;currentKit=k;exportInfo.textContent='当前成果：'+(k.title||k.id);
  const rows=[['编号',k.id],['名称',k.title||k.id],['投影',k.view==='isometric_2_1'?'等距 2:1':k.view==='top_down'?'正俯视':k.view==='orthographic_three_quarter'?'斜俯视':'按原素材规格'],['尺寸',k.canvas_px?k.canvas_px.join(' × ')+' px':k.tile_size?k.tile_size+' px 地格':'64 px 地面单元']];
  if(parent(k))rows.push(['原版本',parent(k)]);for(const source of k.sources||[])rows.push(['来源素材',source.kit]);
  sourceInfo.replaceChildren();for(const [label,value]of rows)sourceInfo.append(create('dt',label),create('dd',value));
  if(activeId===k.id)return;activeId=k.id;restoring=true;
  if(detail&&family==='terrain'){
   for(const [id,value]of Object.entries({'kit-title':k.title,'asset-type':k.asset_type||'terrain','material-kind':k.material_kind||'generic','tile-size':k.tile_size,'road-width':k.road_width,'finish':k.finish||'classic','terrain-projection':k.projection||k.view||'top_down','description':k.description}))if($(id)&&value!==undefined)$(id).value=String(value);
   $('asset-type').dispatchEvent(new Event('change'));
  }
  if(detail&&family==='transition'){
   $('transition-title').value=k.title;let unavailable=false;
   for(const [i,id]of ['base-kit','overlay-kit'].entries()){
    const input=$(id),sourceId=k.sources?.[i]?.kit;
    if([...input.options].some(o=>o.value===sourceId))input.value=sourceId;
    else {unavailable=true;const placeholder=create('option','请选择兼容来源');placeholder.value='';placeholder.disabled=true;input.prepend(placeholder);input.value='';}
   }
   let warning=$('asset-source-warning');if(!warning){warning=create('p',null,'callout');warning.id='asset-source-warning';$('transition-form').prepend(warning);}
   warning.textContent='此成果包含已不可用或当前流程不支持的来源。请重新选择兼容素材后另存，原成果仍可下载。';warning.hidden=!unavailable;$('base-kit').dispatchEvent(new Event('change'));
  }
  baseValues=values();const draft=storage.get(activeId);if(draft)for(const n of fields())if(Object.hasOwn(draft,n.id)){if(n.type==='checkbox')n.checked=!!draft[n.id];else if(n.tagName!=='SELECT'||[...n.options].some(o=>o.value===draft[n.id]))n.value=draft[n.id];}
  if(draft)for(const id of ['asset-type','base-kit','prop-result-usage'])$(id)?.dispatchEvent(new Event('change'));
  restoring=false;dirty();
  if(detail){const url=new URL(location.href);url.searchParams.set('kit',k.id);history.replaceState(null,'',url);}
 });
 tabs.onkeydown=event=>{const keys=Object.keys(labels),i=keys.findIndex(k=>buttons[k]===document.activeElement);if(i<0)return;const k=event.key==='ArrowRight'?keys[(i+1)%keys.length]:event.key==='ArrowLeft'?keys[(i+keys.length-1)%keys.length]:event.key==='Home'?keys[0]:event.key==='End'?keys.at(-1):null;if(k){event.preventDefault();select(k,true);buttons[k].focus();}};
 tabs.hidden=!detail&&!task;historyCard.hidden=true;sourceCard.hidden=true;select(task?'records':query.get('tab')||'preview');if(task)status('正在读取任务记录…');else if(!detail)status('设置本次生成，完成后挑选结果。');
})();

'use strict';
(() => {
 const $=id=>document.getElementById(id);
 let state,selected=new URLSearchParams(location.search).get('kit'),pending,busy=false,refreshing=false,kindsLoaded=false,previousKind='rock';
 let shownId=null;
 const nodes=new Map();
 const status=(text,error=false)=>{ $('prop-status').textContent=text;$('prop-status').className=error?'terrain-error':'terrain-hint';StudioAssets.status(text,error); };
 const active=()=>state?.jobs.some(job=>['queued','running'].includes(job.status));
 const label=kind=>state?.kinds?.[kind]?.label||'石头';
 const visibleKits=()=>state.kits.filter(kit=>$('prop-filter').value==='all'||(kit.asset_kind||'rock')===$('prop-filter').value);
 function applyKind(){
  const kind=$('prop-kind').value,profile=state.kinds[kind],previous=state.kinds[previousKind];
  if($('prop-description').value===previous.description)$('prop-description').value=profile.description;
  if([defaultTitle(previousKind),'手绘石头'].includes($('prop-title').value))$('prop-title').value=defaultTitle(kind);
  $('prop-kind-hint').textContent=profile.hint;$('prop-collision-usage').value=profile.collision_usage;previousKind=kind;
 }
 function defaultTitle(kind){return label(kind)+'素材';}
 async function api(path,data){
  const response=await fetch(path,data?{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Token':state.token},body:JSON.stringify(data)}:{});
  const value=await response.json();if(!response.ok)throw Error(value.error||'请求失败');return value;
 }
 async function fileData(file){
  if(!file||file.size>8*1024*1024)throw Error('请选择不超过8MB的图片');
  return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error('图片读取失败'));reader.readAsDataURL(file);});
 }
 function controls(){
  const ai=$('prop-mode').value==='ai';$('prop-ai').hidden=!ai;$('prop-import').hidden=ai;
  $('prop-description').required=ai;$('prop-description').disabled=!ai;$('prop-reference').disabled=!ai;$('prop-image').required=!ai;
  $('prop-projection-label').textContent=ai?'生成图片的视角':'原图片的视角';
  $('prop-projection-hint').textContent=ai?'视角要求会写入生成提示，生成后仍需检查实际画面。':'请选择原图已有的视角，用于接入规格与占地建议；程序不会旋转图片或转换视角。';
  $('prop-generate').disabled=!state||busy||active()||(ai&&!state.image_api_configured);
  const kit=state?.kits.find(k=>k.id===selected);
  $('prop-remake').disabled=busy||active()||!kit||!kit.integrity.passed;
  const noCollision=$('prop-result-usage').value==='none';$('prop-width').disabled=noCollision;$('prop-depth').disabled=noCollision;
  for(const node of nodes.values())node.querySelector('button').disabled=busy||active();
 }
 function show(kit,force=false){
  if(!kit){selected=null;$('prop-result').hidden=true;$('prop-result-title').textContent='此类型暂无素材';return;}
  // Integrity can change independently of selection; keep it fresh without erasing edits.
  $('prop-download').hidden=!kit.integrity.passed;
  $('prop-integrity').textContent=kit.integrity.passed?'文件完整性通过；外观、锚点与游戏接入仍待验收。':'完整性失败：'+kit.integrity.error;
  // Background refresh must not erase the user's unsaved anchor edits.
  if(shownId===kit.id&&!force)return;shownId=kit.id;
  selected=kit.id;$('prop-history').value=kit.id;$('prop-result').hidden=false;
  const base='/prop-asset/'+encodeURIComponent(kit.id)+'/';
  $('prop-result-title').textContent=label(kit.asset_kind||'rock')+' · '+kit.title;
  $('prop-origin').textContent=(kit.provenance.art_source==='procedural_projection_fixture'?'来源：程序几何验证样本，非AI美术。':kit.provenance.art_source==='ai_complete_object'?'来源：AI生成完整物件，程序抠图与规格化。':'来源：导入完整物件，程序处理。未调用AI。')+(kit.provenance.parent_kit?' 此版本复用原图调整锚点与碰撞，无新增生图。':'');
  $('prop-origin').textContent+=' 投影：'+(kit.view==='isometric_2_1'?'等距2:1（角度待人工验收，锚点为占地中心建议）':'斜俯视')+'。';
  $('prop-preview').src=base+'preview.png';$('prop-overlay').src=base+'anchor_collision.png';
  $('prop-sprite').href=base+'sprite.png';$('prop-download').href=base+'kit.zip';
  $('prop-result-usage').value=kit.suggested_collision.usage||state.kinds[kit.asset_kind||'rock'].collision_usage;
  const values={'prop-anchor-x':kit.anchor_px[0],'prop-anchor-y':kit.anchor_px[1],'prop-width':kit.suggested_collision.width_px,'prop-depth':kit.suggested_collision.depth_px};
  for(const [id,value] of Object.entries(values)){$(id).value=value;$(id).min=id.includes('anchor')?0:1;$(id).max=id.includes('anchor')?kit.canvas_px[0]-1:kit.canvas_px[0];}
  document.dispatchEvent(new CustomEvent('studio:asset',{detail:kit}));
 }
 function jobs(){
  for(const job of state.jobs){
   let node=nodes.get(job.id);
   if(!node){
    node=document.createElement('div');node.className='terrain-job';
    node.innerHTML='<p></p><button type="button">继续任务（可能产生费用）</button> <a target="_blank" rel="noopener">查看原图</a><details><summary>请求日志</summary><button type="button">读取 / 更新</button><pre class="terrain-request-log"></pre></details>';
    nodes.set(job.id,node);$('prop-jobs').append(node);
    node.querySelector('a').href='/api/props/job-image?id='+encodeURIComponent(job.id);
    const result=document.createElement('a');result.className='job-result-link';result.textContent='查看成果 →';node.append(result);
    node.querySelector('button').onclick=async()=>{
     busy=true;controls();try{await api('/api/props/generate',{resume:job.id});pending=job.id;await refresh();status('已继续任务，成功图片会复用；服务端失败任务可能重新付费生成。');}catch(e){status(e.message,true);}finally{busy=false;controls();}
    };
    node.querySelector('details button').onclick=async()=>{try{const log=await api('/api/props/job-log?id='+encodeURIComponent(job.id));node.querySelector('pre').textContent=JSON.stringify(log.events,null,2);}catch(e){status(e.message,true);}};
   }
   node.querySelector('p').textContent=label(job.spec?.kind||'rock')+' · '+job.id+' · '+job.stage+(job.error?' · '+job.error:'');
   const result=node.querySelector('.job-result-link');result.hidden=job.status!=='complete'||!state.kits.some(k=>k.id===job.kit_id);if(!result.hidden)result.href='/props.html?kit='+encodeURIComponent(job.kit_id);
   node.querySelector('button').hidden=!['failed','interrupted'].includes(job.status);
   node.querySelector('a').hidden=!job.original_available;StudioAssets.jobRow(node,job,state.kits,selected);
   if(pending===job.id&&job.status==='complete'){pending=null;const kit=state.kits.find(k=>k.id===job.kit_id);if(kit)status('任务已完成，点击该记录的“查看成果”检查物件。');status('物件已完成，请检查透明边缘与落地锚点。');}
   if(pending===job.id&&job.status==='failed'){pending=null;status(job.error,true);}
  }
 }
 async function refresh(){
  if(refreshing)return;refreshing=true;
  try{state=await api('/api/props/state');
   if(!kindsLoaded){
    $('prop-kind').replaceChildren();for(const [kind,profile] of Object.entries(state.kinds)){
     for(const id of ['prop-kind','prop-filter']){const option=document.createElement('option');option.value=kind;option.textContent=profile.label;$(id).append(option);}
    }
    $('prop-kind').disabled=false;$('prop-kind-hint').textContent=state.kinds.rock.hint;kindsLoaded=true;
   }
   $('prop-api').textContent=state.image_api_configured?'图片服务已配置。参考图不超过8MB。':'尚未配置图片服务密钥，可先导入物件验证流程。';
   jobs();StudioAssets.jobsLoaded(state.jobs);$('prop-history').replaceChildren();const kits=visibleKits();for(const kit of kits){const option=document.createElement('option');option.value=kit.id;option.textContent=label(kit.asset_kind||'rock')+' · '+(kit.view==='isometric_2_1'?'等距 · ':'')+kit.title+' · '+kit.id;$('prop-history').append(option);}
   StudioAssets.historyOptions(state.kits,selected);const kit=kits.find(k=>k.id===selected);if(kit)show(kit);else if(selected)status('指定物件不存在或已不可用，请返回素材库。',true);controls();
  }finally{refreshing=false;}
 }
 $('prop-mode').onchange=controls;
 $('prop-kind').onchange=()=>{applyKind();controls();};
 $('prop-result-usage').onchange=controls;
 $('prop-filter').onchange=()=>{selected=null;refresh().catch(e=>status(e.message,true));};
 $('prop-history').onchange=()=>{show(state.kits.find(k=>k.id===$('prop-history').value),true);controls();};
 $('prop-form').onsubmit=async event=>{
  event.preventDefault();if(busy||!state||active())return;busy=true;controls();
  try{const data={kind:$('prop-kind').value,collision_usage:$('prop-collision-usage').value,mode:$('prop-mode').value,title:$('prop-title').value,size:Number($('prop-size').value),projection:$('prop-projection').value};
   if(data.mode==='import')data.image=await fileData($('prop-image').files[0]);
   else {data.description=$('prop-description').value;if($('prop-reference').files[0])data.reference=await fileData($('prop-reference').files[0]);}
   const job=await api('/api/props/generate',data);StudioAssets.trackJob(job.id);
  }catch(e){status(e.message,true);}finally{busy=false;controls();}
 };
 $('prop-adjust').onsubmit=async event=>{
  event.preventDefault();if(busy||active())return;busy=true;controls();
  try{const data={source_kit:selected,collision_usage:$('prop-result-usage').value,anchor_x:Number($('prop-anchor-x').value),anchor_y:Number($('prop-anchor-y').value),collision_width:Number($('prop-width').value),collision_depth:Number($('prop-depth').value)};
   const kit=await api('/api/props/remake',data);StudioAssets.saved();StudioAssets.openKit(kit.id);
  }catch(e){status(e.message,true);}finally{busy=false;controls();}
 };
 setInterval(()=>{if(!busy)refresh().catch(e=>status(e.message,true));},4000);
 refresh().catch(e=>status(e.message,true));
 window.addEventListener('studio-image-provider-changed',()=>{if(!busy)Promise.resolve(refresh()).catch(()=>{});});
})();

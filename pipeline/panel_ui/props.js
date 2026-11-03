'use strict';
(() => {
 const $=id=>document.getElementById(id);
 let state,selected=new URLSearchParams(location.search).get('kit'),pending,busy=false,refreshing=false,kindsLoaded=false,previousKind='rock';
 let shownId=null;const editor=new StudioSpriteEditor();
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
  $('prop-edit-settings').disabled=busy||active()||!kit||!kit.integrity.passed;
  $('prop-cleanup').disabled=busy||active()||!kit||!kit.integrity.passed;
  for(const node of nodes.values())node.querySelector('button').disabled=busy||active();
 }
 function show(kit,force=false){
  if(!kit){selected=null;$('prop-result').hidden=true;$('prop-result-title').textContent='此类型暂无素材';return;}
  // Integrity can change independently of selection; keep it fresh without erasing edits.
  $('prop-cleanup').hidden=kit.provenance.art_source!=='ai_complete_object';
  $('prop-cleanup-info').textContent=kit.provenance.art_source==='ai_complete_object'?(kit.processing?.reserved_magenta_cleanup?'已自动清理品红背景、封闭孔洞和匹配残色；请检查主体是否完整。':'可复用原图重新处理透明背景，另存新版本，不调用生图服务。'):'';
  $('prop-download').hidden=!kit.integrity.passed;
  $('prop-integrity').textContent=kit.integrity.passed?'文件完整性通过；外观、锚点与游戏接入仍待验收。':'完整性失败：'+kit.integrity.error;
  // Background refresh must not erase the user's unsaved anchor edits.
  if(shownId===kit.id&&!force)return;shownId=kit.id;
  selected=kit.id;$('prop-history').value=kit.id;$('prop-result').hidden=false;
  const base='/prop-asset/'+encodeURIComponent(kit.id)+'/';
  $('prop-result-title').textContent=label(kit.asset_kind||'rock')+' · '+kit.title;
  $('prop-origin').textContent=(kit.provenance.art_source==='procedural_projection_fixture'?'来源：程序几何验证样本，非AI美术。':kit.provenance.art_source==='ai_complete_object'?'来源：AI生成完整物件，程序抠图与规格化。':'来源：导入完整物件，程序处理。未调用AI。')+(kit.provenance.parent_kit?' 此版本复用原图调整锚点与碰撞，无新增生图。':'');
  const wallOrigins={ai_long_wall_repeat:'来源：AI一体生成长墙，Studio自动选点、检查并切片。',ai_long_wall_slice:'来源：AI一体生成长墙，程序按截面切片。',ai_whole_wall:'来源：AI一体生成整段墙，程序处理透明背景。',ai_surface_sampling:'来源：AI外观采样，程序投射到固定墙体结构。',ai_line_constrained_wall:'来源：AI参考线框生成整段墙。'};
  wallOrigins.ai_corner_wall_slice='来源：AI一体生成转角长墙，Studio从同一原图切出转角及两轴直墙。';
  wallOrigins.ai_courtyard_ring='来源：AI一体生成闭合院墙，Studio检查闭合并切分四角四边；固定尺寸组合。';
  wallOrigins.ai_courtyard_expansion='来源：AI院墙原图，Studio寻找相对墙共同重复切口；同一套四角与直墙用于不同尺寸院落。';
  wallOrigins.program_wall_passage='来源：程序重复同源墙段并切出开放门洞，保留原瓦顶；未生成门框或门扇。';
  if(wallOrigins[kit.provenance.art_source])$('prop-origin').textContent=wallOrigins[kit.provenance.art_source];
  $('prop-origin').textContent+=' 投影：'+(kit.view==='isometric_2_1'?'等距2:1（角度待人工验收，锚点为占地中心建议）':'斜俯视')+'。';
  $('prop-preview').src=base+(kit.processing?.method==='automatic_wall_repeat'?'repeat-preview.png':'preview.png');$('prop-overlay').src=base+'anchor_collision.png';
  $('prop-sprite').href=base+'sprite.png';$('prop-download').href=base+'kit.zip';
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
 $('prop-cleanup').onclick=async()=>{
  if(busy||active()||!selected)return;busy=true;controls();
  try{const kit=await api('/api/props/remake',{source_kit:selected,transparency_only:true});StudioAssets.saved();StudioAssets.openKit(kit.id);}
  catch(e){status(e.message,true);}finally{busy=false;controls();}
 };
 $('prop-edit-settings').onclick=async()=>{
  try{
   const kit=state.kits.find(k=>k.id===selected);if(!kit)throw Error('素材不存在');
   const response=await api('/api/props/settings?kit='+encodeURIComponent(kit.id));
   const image=new Image();image.src='/prop-asset/'+encodeURIComponent(kit.id)+'/sprite.png';await image.decode();
   const config={...response.settings,source:{id:kit.id}};
   editor.open(config,image,async values=>{
    const saved=await api('/api/props/annotate',{source_kit:kit.id,source_sha256:response.sha256,...values});
    setTimeout(()=>{StudioAssets.saved();StudioAssets.openKit(saved.id);},0);
    return {...values,source:{id:saved.id}};
   });
  }catch(e){status(e.message,true);}
 };
 setInterval(()=>{if(!busy)refresh().catch(e=>status(e.message,true));},4000);
 refresh().catch(e=>status(e.message,true));
 window.addEventListener('studio-image-provider-changed',()=>{if(!busy)Promise.resolve(refresh()).catch(()=>{});});
})();

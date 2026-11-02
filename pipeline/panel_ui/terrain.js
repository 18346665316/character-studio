'use strict';
(() => {
 const $ = id => document.getElementById(id);
 let state, selected=new URLSearchParams(location.search).get('kit'), loadedId, atlas, currentKit, grid, submitting=false,  refreshing=false, trackedJob=new URLSearchParams(location.search).get('task');
 const detail=new URLSearchParams(location.search).has('kit');
 const waterArea=document.body?.dataset?.assetArea==='water';
 const isWater=kit=>kit.asset_type==='material'&&kit.material_kind==='water';
 const requestLogs=new Map();
 const requestedType=new URLSearchParams(location.search).get('type');if(['material','terrain'].includes(requestedType))$('asset-type').value=requestedType;
 const modeNames={ai:'AI 生成',import:'导入材质',demo:'程序示例',reuse:'复用材质'};
 const jobError=value=>String(value||'').replace('服务商图片生成失败；','图片接口返回任务失败，尚不能确认请求是否到达生图服务；');
 const canvas=$('terrain-map'), ctx=canvas.getContext('2d');
 function text(tag,value,cls){const n=document.createElement(tag);n.textContent=value;if(cls)n.className=cls;return n;}
 async function api(path,data){const r=await fetch(path,data?{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Token':state.token},body:JSON.stringify(data)}:{});const v=await r.json();if(!r.ok)throw Error(v.error||'请求失败');return v;}
 function status(value,error=false){$('form-status').textContent=value;$('form-status').className=error?'terrain-error':'';StudioAssets.status(value,error);}
 function updateMode(){
  if(waterArea){$('asset-type').value='material';$('material-kind').value='water';}
  const mode=$('source-mode').value,single=$('asset-type').value==='material',ai=mode==='ai'&&!detail;
  $('api-status').textContent=ai?(state?.image_api_configured?'图像 API 已配置':'图像 API 待配置'):'本地图片处理 · 无 AI 调用';
  $('terrain-ai').hidden=!ai;$('description').required=ai;$('description').disabled=!ai;$('style-reference').disabled=!ai;
  if($('terrain-projection')){const allowed=single&&!waterArea;$('terrain-projection-field').hidden=!allowed;$('terrain-projection').disabled=!allowed;if(!allowed)$('terrain-projection').value='top_down';}
  for(const id of ['road-file','road-file-label','road-width-field'])$(id).hidden=single;
  const product=waterArea?'水面素材':single?'地面素材':'地面与道路套件';
  if(!detail&&!trackedJob){$('empty-result').querySelector('h2').textContent=single?'制作可平铺的'+(waterArea?'水面':'地面'):'制作地面与道路连接块';$('empty-result').querySelectorAll('p')[1].textContent=single?'图片会经过平铺与变化块处理；上传后可检查大面积重复效果。':'需要地面和道路表面两种纹理，输出四方向道路连接块。';}
  if(!waterArea)$('description').placeholder=single?'例如：手绘浅绿色草地，低对比度，少量碎石，整张铺满纹理':'例如：手绘浅绿色草地与浅褐色泥土道路，少量碎石，柔和色彩';
  $('output-hint').textContent=(single?'将纹理处理为可平铺地格与变化块。':'将两张纹理制作成正俯视地面与道路连接块。')+(ai?(single?' AI 生成一张纹理图片。':' AI 生成地面、道路两张纹理图片。'):'');
  $('source-mode').options[1].textContent=single?'导入一张纹理图片':'导入地面和道路纹理';
  $('generate').textContent=mode==='import'?'用导入图片制作'+product:'生成'+product;
  $('material-inputs').hidden=mode!=='import'||detail;$('ground-file').required=mode==='import'&&!detail;$('road-file').required=mode==='import'&&!single&&!detail;
  $('api-hint').textContent=ai?(state?.image_api_configured?'按描述生成图片，可用参考图约束画风；调用图像服务会产生费用。':'请在项目 .env 配置图片服务；支持兼容接口或 Google Cloud Vertex AI，保存后刷新。'):detail?'':mode==='import'?'使用上传图片制作地格，不调用 AI，也不改变图片画风。':'程序示例只用于验证拼接。';
  if($('projection-hint'))$('projection-hint').textContent=$('terrain-projection').value==='isometric_2_1'?'程序将俯视纹理制作成透明的 2:1 菱形地格，不生成高度或侧壁。':'输出方形地格，用于正俯视铺设。';
  $('generate').disabled=submitting||!state||(ai&&!state.image_api_configured);$('reuse-materials').disabled=submitting||!currentKit;
 }
 async function fileContent(id){const f=$(id).files[0];if(!f)return null;if(f.size>8*1024*1024)throw Error('每张图片不能超过 8 MB');return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result).split(',')[1]);r.onerror=()=>reject(Error('图片读取失败'));r.readAsDataURL(f);});}
 $('source-mode').onchange=$('asset-type').onchange=updateMode;
 if($('terrain-demo'))$('terrain-demo').onclick=()=>{if($('kit-title').reportValidity())submit('demo');};
 if($('terrain-projection'))$('terrain-projection').onchange=updateMode;
 let refURL;
 $('style-reference').onchange=()=>{if(refURL)URL.revokeObjectURL(refURL);const file=$('style-reference').files[0];$('reference-preview').hidden=!file;if(file){refURL=URL.createObjectURL(file);$('reference-preview').src=refURL;}};
 $('kit-form').onsubmit=event=>{event.preventDefault();if(detail){$('reuse-materials').click();return;}submit($('source-mode').value);};
 async function submit(mode){
  if(submitting||!state)return;submitting=true;updateMode();status('正在保存输入…');
  try{
   const data={asset_type:$('asset-type').value,material_kind:waterArea?'water':'generic',title:$('kit-title').value,mode,tile_size:Number($('tile-size').value),finish:$('finish').value,projection:$('terrain-projection')?.value||'top_down'};
   if(data.asset_type!=='material')data.road_width=Number($('road-width').value);
   if(mode==='ai'){data.description=$('description').value;data.reference=await fileContent('style-reference');}
   if(mode==='import'){data.ground=await fileContent('ground-file');if(data.asset_type!=='material')data.road=await fileContent('road-file');}
   const job=await api('/api/terrain/generate',data);StudioAssets.trackJob(job.id);
  }catch(e){status(e.message,true);}finally{submitting=false;updateMode();}
 }
 function sampleGrid(){const g=Array.from({length:9},()=>Array(12).fill(false));for(let x=2;x<10;x++)g[2][x]=g[6][x]=true;for(let y=2;y<7;y++)g[y][2]=g[y][9]=g[y][6]=true;for(let x=0;x<12;x++)g[4][x]=true;g[0][6]=g[1][6]=g[8][4]=true;return g;}
 function variantAt(x,y,count,seed=17){let v=((Math.imul(x,374761393))^(Math.imul(y,668265263))^seed)>>>0;v=Math.imul(v^(v>>>13),1274126177)>>>0;return ((v^(v>>>16))>>>0)%count;}
 function draw(){
  if(!atlas||!currentKit||!grid)return;
  if(currentKit.projection_spec){const expected=currentKit.id,preview=new Image();preview.src='/terrain-asset/'+encodeURIComponent(expected)+'/'+currentKit.projection_spec.preview;preview.decode().then(()=>{if(currentKit?.id!==expected)return;canvas.width=preview.width;canvas.height=preview.height;ctx.drawImage(preview,0,0);}).catch(()=>status('等距验收图加载失败',true));return;}
  const s=currentKit.tile_size,variants=currentKit.variants||[{ground_cell:currentKit.ground_cell,tiles:currentKit.tiles}];
  if(currentKit.asset_type==='material')grid=grid.map(row=>row.map(()=>false));
  canvas.width=12*s;canvas.height=9*s;ctx.imageSmoothingEnabled=false;
  for(let y=0;y<9;y++)for(let x=0;x<12;x++){
   let bits=0;if(grid[y][x]){if(grid[y-1]?.[x])bits|=1;if(grid[y][x+1])bits|=2;if(grid[y+1]?.[x])bits|=4;if(grid[y][x-1])bits|=8;}
   const variant=variants[variantAt(x,y,variants.length,currentKit.variant_seed??17)];
   const cell=grid[y][x]?variant.tiles[bits].atlas_cell:variant.ground_cell;
   ctx.drawImage(atlas,cell[0]*s,cell[1]*s,s,s,x*s,y*s,s,s);
  }
 }
 function gallery(index=0){
  const kit=currentKit;if(!kit||!atlas)return;
  if(kit.projection_spec){$('tile-gallery').replaceChildren();const [w,h]=kit.projection_spec.cell_px;for(const item of kit.projection_spec.variants){const f=document.createElement('figure'),c=document.createElement('canvas');c.width=w;c.height=h;c.getContext('2d').drawImage(atlas,...item.atlas_rect_px,0,0,w,h);f.append(c,text('figcaption','等距变化 '+(item.id+1)));$('tile-gallery').append(f);}return;}
  const entries=kit.asset_type==='material'?[{id:index,connections:[],atlas_cell:kit.variants[index].ground_cell}]:(kit.variants?.[index]?.tiles||kit.tiles);
  $('tile-gallery').replaceChildren();
  for(const tile of entries){const f=document.createElement('figure'),c=document.createElement('canvas');c.width=c.height=kit.tile_size;c.getContext('2d').drawImage(atlas,tile.atlas_cell[0]*kit.tile_size,tile.atlas_cell[1]*kit.tile_size,kit.tile_size,kit.tile_size,0,0,kit.tile_size,kit.tile_size);f.append(c,text('figcaption',String(tile.id).padStart(2,'0')+' · '+(tile.connections.length?tile.connections.map(v=>({north:'北',east:'东',south:'南',west:'西'}[v])).join(''):'独立')));$('tile-gallery').append(f);}
 }
 $('variant-picker').onchange=()=>gallery(Number($('variant-picker').value));
 $('reuse-materials').onclick=async()=>{
  if(!currentKit||submitting||!$('kit-title').reportValidity())return;
  const source=currentKit;submitting=true;updateMode();
  try{
   const job=await api('/api/terrain/generate',{title:$('kit-title').value.trim(),description:source.description,mode:'reuse',source_kit:source.id,tile_size:Number($('tile-size').value),road_width:Number($('road-width').value),finish:$('finish').value,projection:$('terrain-projection')?.value||'top_down'});
   StudioAssets.trackJob(job.id);
  }catch(e){status(e.message,true);}finally{submitting=false;updateMode();}
 };
 function updateIntegrity(kit){$('download-kit').hidden=kit.integrity?.passed===false;$('validation').classList.toggle('terrain-error',kit.integrity?.passed===false);$('validation').textContent=kit.integrity?.passed===false?'完整性检查失败：'+kit.integrity.errors.join('；'):`连接检查：${kit.validation.matching_edge_pairs} 对边缘通过，最大通道差 ${kit.validation.max_channel_difference}。`;}
 async function showKit(kit){if(loadedId===kit.id){updateIntegrity(kit);return;}loadedId=kit.id;const expected=kit.id;const base='/terrain-asset/'+encodeURIComponent(kit.id)+'/';const image=new Image();image.src=base+(kit.projection_spec?.atlas||'atlas.png');try{await image.decode();}catch{loadedId=null;status('图集加载失败，请刷新重试。',true);return;}if(loadedId!==expected)return;atlas=image;currentKit=kit;if(waterArea)$('water-shore-link').href='/water-shore.html?water='+encodeURIComponent(kit.id);grid=sampleGrid();$('empty-result').hidden=true;$('kit-result').hidden=false;$('result-title').textContent=kit.title;$('download-kit').href=base+'kit.zip';$('ground-material').src=base+'ground_material.png';$('road-material-figure').hidden=kit.asset_type==='material';if(kit.asset_type!=='material')$('road-material').src=base+'road_material.png';$('preview-hint').textContent=kit.asset_type==='material'?'固定平铺样例，用于检查变化块连接和大面积重复。':'固定铺设样例，用于检查材质重复、道路过渡和连接效果。';$('delivery-hint').textContent=kit.asset_type==='material'?'包含单块 PNG、变化图集、原始输入、来源与接入说明，可用于地表过渡。':'包含道路连接块、透明层、图集、原始输入及接入说明。';$('kit-meta').textContent=(kit.projection_spec?'等距2:1 · ':'')+`${kit.asset_type==='material'?'独立材质':'道路套件'} · ${modeNames[kit.mode]} · ${kit.tile_size}px ${kit.asset_type==='material'?'':'· 道路宽 '+Math.round(kit.road_width*100)+'%'} · ${kit.variants?.length||1}组变化块 · 待美术复核`;updateIntegrity(kit);
 if(kit.projection_spec){$('preview-hint').textContent='固定菱形排列用于检查接缝；无地图编辑、碰撞或高度。';$('delivery-hint').textContent='包含等距透明PNG、等距图集、地格基向量和中心锚点；正俯视纹理作为原始材质一并保留。';}
 $('variant-picker').replaceChildren();for(let i=0;i<(kit.variants?.length||1);i++){const option=text('option','变化组 '+(i+1));option.value=i;$('variant-picker').append(option);}gallery();updateMode();draw();document.dispatchEvent(new CustomEvent('studio:asset',{detail:kit}));}
 $('kit-picker').onchange=()=>{selected=$('kit-picker').value;showKit(state.kits.find(k=>k.id===selected));};
 async function refresh(){if(refreshing)return;refreshing=true;try{state=await api('/api/terrain/state');state.kits=state.kits.filter(kit=>waterArea?isWater(kit):!isWater(kit));state.jobs=state.jobs.filter(job=>waterArea?isWater(job.spec):!isWater(job.spec));$('api-status').textContent=state.image_api_configured?'图像 API 已配置 · '+(state.image_model||'gpt-image-2'):'图像 API 待配置';updateMode();$('kit-picker').replaceChildren();for(const kit of state.kits){const o=document.createElement('option');o.value=kit.id;o.textContent=kit.title+' · '+kit.id;$('kit-picker').append(o);}$('kit-picker').hidden=!state.kits.length;StudioAssets.historyOptions(state.kits,selected);if(selected){const kit=state.kits.find(k=>k.id===selected);if(kit)await showKit(kit);else status('指定素材不存在或已不可用，请返回素材库。',true);}
 const logScroll=new Map([...requestLogs].map(([id,entry])=>[id,entry.log.scrollTop]));
 $('terrain-jobs').replaceChildren();for(const job of state.jobs){const box=text('div','', 'terrain-job');box.append(text('strong',job.spec.title),text('p',job.stage),text('small',job.id));if(job.error)box.append(text('p',jobError(job.error),'terrain-error'));if(job.status==='failed'){const b=text('button','继续任务');b.onclick=async()=>{b.disabled=true;try{await api('/api/terrain/generate',{resume:job.id});trackedJob=job.id;await refresh();status('任务已继续，可在此记录查看进度。');}catch(e){status(e.message,true);b.disabled=false;}};box.append(b);}if(job.status==='complete'){const b=text('button','查看成果');b.onclick=()=>StudioAssets.openKit(job.kit||job.kit_id||job.id);box.append(b);} let entry=requestLogs.get(job.id);if(!entry){const logButton=text('button','查看请求日志'),log=text('pre','');log.hidden=true;log.className='terrain-request-log';entry={button:logButton,log};requestLogs.set(job.id,entry);logButton.onclick=async()=>{if(!log.hidden){log.hidden=true;return;}log.hidden=false;log.textContent='正在读取…';try{const result=await api('/api/terrain/job-log?id='+encodeURIComponent(job.id));log.textContent=result.events.length?result.events.map(e=>JSON.stringify(e,null,2)).join('\n'):'暂无 HTTP 请求记录（导入或历史任务可能没有记录）。';}catch(e){log.textContent=e.message;}};}box.append(entry.button,entry.log);$('terrain-jobs').append(box);StudioAssets.jobRow(box,job,state.kits,selected);entry.log.scrollTop=logScroll.get(job.id)||0;}
 StudioAssets.jobsLoaded(state.jobs);for(const id of requestLogs.keys())if(!state.jobs.some(job=>job.id===id))requestLogs.delete(id);

 if(!state.jobs.length)$('terrain-jobs').append(text('p','尚无生产记录。'));
 }catch(e){status(e.message,true);}finally{refreshing=false;}}
 refresh();setInterval(refresh,4000);
 window.addEventListener('studio-image-provider-changed',()=>refresh());
})();

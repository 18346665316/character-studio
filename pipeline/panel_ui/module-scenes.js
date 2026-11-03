'use strict';
(() => {
 const $=id=>document.getElementById(id), images=new Map(), pixels=new Map();
 let token,scene,selectedModule,selectedInstance;
 let zoom=1,pan=[500,320],drag,dirty=false,space=false;
 let undoStack=[],redoStack=[],saving=false,hover;
 const editor=new StudioSpriteEditor();
 const layer=m=>m.layer==='ground'?0:1;
 const order=(a,b)=>layer(scene.modules.find(m=>m.id===a.module))-layer(scene.modules.find(m=>m.id===b.module))||a.position[1]-b.position[1];
 const sourceHref=m=>m.source?.family==='character'?'/characters.html?character='+m.character_id:['terrain','transition'].includes(m.source?.family)?(m.source.family==='transition'?'/transition.html?kit=':'/terrain.html?kit=')+m.source.id:'/props.html?kit='+m.source.id;
 const moduleTitle=m=>m.source?.family==='transition'?m.title+' · 角点 '+m.source.corners+' / 变化 '+(m.source.variant+1):m.title;
 const scale=m=>m.world_scale??1;
 const module=()=>scene?.modules.find(m=>m.id===selectedModule);
 const instance=()=>scene?.instances.find(v=>v.id===selectedInstance);
 const status=(message,error=false)=>{
  $('status').textContent=message;$('status').style.color=error?'#ae382a':'#326b4c';
  if($('module-dialog').open){$('editor-status').textContent=message;$('editor-status').style.color=error?'#ae382a':'#687c70';}
 };
 async function api(path,data){
  const r=await fetch(path,data?{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Token':token},body:JSON.stringify(data)}:{});
  const v=await r.json();if(!r.ok)throw Error(v.error||'请求失败');return v;
 }
 const run=fn=>async(...args)=>{try{await fn(...args);}catch(e){status(e.message,true);}};
 const requireSavedModule=()=>{if(editor.dirty)throw Error('请先保存素材设置，或取消本次编辑。');};
 async function mutate(data){return api('/api/module-scenes/change',{scene:scene?.id,revision:scene?.revision,...data});}
 async function image(m){
  if(!images.has(m.image)){
   const im=new Image();im.src='/api/module-scenes/image?file='+m.image;await im.decode();images.set(m.image,im);
   const c=document.createElement('canvas');c.width=im.width;c.height=im.height;
   const ctx=c.getContext('2d',{willReadFrequently:true});ctx.drawImage(im,0,0);pixels.set(m.image,ctx.getImageData(0,0,im.width,im.height));
  }return images.get(m.image);
 }
 function snapshot(){return structuredClone({instances:scene.instances,spawn:scene.spawn});}
 function historyState(){return {...snapshot(),selectedInstance};}
 function checkpoint(){undoStack.push(historyState());if(undoStack.length>100)undoStack.shift();redoStack=[];}
 function changed(){dirty=true;drawScene();}
 function undo(redo=false){
  const source=redo?redoStack:undoStack,target=redo?undoStack:redoStack;if(!scene||!source.length)return;
  target.push(historyState());const restored=source.pop();scene.instances=restored.instances;scene.spawn=restored.spawn;selectedInstance=restored.selectedInstance;changed();status(redo?'已重做。':'已撤销。');
 }
 async function refresh(id){
  const s=await api('/api/module-scenes/state'+(id?'?scene='+encodeURIComponent(id):''));token=s.token;scene=s.selected;
  $('scenes').replaceChildren(new Option('选择场景',''),...s.scenes.map(s=>new Option(s.title,s.id)));$('scenes').value=scene?.id||'';
  $('workspace').hidden=!scene;$('export').hidden=!scene;if(!scene)return;
  history.replaceState(null,'','?scene='+scene.id);$('export').href='/api/module-scenes/export?scene='+scene.id;
  await Promise.all(scene.modules.map(image));selectedModule=scene.modules.some(m=>m.id===selectedModule)?selectedModule:scene.modules[0]?.id;
  selectedInstance=null;undoStack=[];redoStack=[];renderModules();dirty=false;resizeCanvas();fitView();
 }
 function renderModules(){
  $('modules').replaceChildren(...scene.modules.map(m=>new Option(moduleTitle(m),m.id)));$('modules').value=selectedModule||'';
  const cards=scene.modules.map(m=>{
   const button=document.createElement('button');button.className='asset-card';button.draggable=true;button.dataset.module=m.id;
   button.setAttribute('aria-pressed',String(m.id===selectedModule));
   const img=document.createElement('img');img.src=images.get(m.image).src;img.alt='';img.draggable=false;
   const text=document.createElement('span');text.textContent=moduleTitle(m);const badge=document.createElement('small');
   badge.textContent=m.source?.family==='character'?'人物 · 动作包':m.layer==='ground'?(m.behavior==='blocking'?'地面 · 阻挡':'地面 · 可通过'):{blocking:'阻挡',opening:'开口',passable:'可通过'}[m.behavior];text.append(badge);button.append(img,text);if(m.source){button.title='素材版本：'+m.source.id;}
   button.onclick=run(()=>{chooseModule(m.id);setTool('place');status('点击画布放置 '+m.title+'；Esc 返回选择。');});
   button.ondblclick=run(()=>{chooseModule(m.id);openEditor();});
   button.ondragstart=e=>{e.dataTransfer.setData('application/studio-module',m.id);e.dataTransfer.effectAllowed='copy';};return button;
  });$('asset-cards').replaceChildren(...cards);editModule();const m=module();$('source-link').hidden=!m?.source;if(m?.source){$('source-link').href=sourceHref(m);$('source-link').textContent='查看当前素材版本 ↗';}
 }
 function chooseModule(id){requireSavedModule();selectedModule=id;$('modules').value=id;editModule();syncCards();const m=module();$('source-link').hidden=!m?.source;if(m?.source)$('source-link').href=sourceHref(m);}
 function syncCards(){for(const card of $('asset-cards').children)card.setAttribute('aria-pressed',String(card.dataset.module===selectedModule));}
 function editModule(){const m=module();if(m&&images.has(m.image))editor.load(m,images.get(m.image),saveModule);}
 function openEditor(){if(module()?.source?.family==='character')return status('人物引用固定版本的动作包；请到人物工作台制作新版本。');if(['terrain','transition'].includes(module()?.source?.family))return status('地面为固定128 × 64地格，可重复铺放；原始设置见地面工作台。');if(!module())return status('请先选择素材。',true);editor.open();}
 function polygon(ctx,points,color){
  if(!points.length)return;ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.closePath();
  ctx.fillStyle=color;ctx.fill();ctx.strokeStyle='#ff9a7c';ctx.stroke();
 }
 function setTool(value){$('tool').value=value;for(const b of document.querySelectorAll('[data-tool]'))b.setAttribute('aria-pressed',String(b.dataset.tool===value));$('scene-canvas').style.cursor=value==='select'?'default':'crosshair';hover=null;drawScene();}
 function drawScene(){
  if(!scene||scene.modules.some(m=>!images.has(m.image)))return;const c=$('scene-canvas'),ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);ctx.save();ctx.translate(...pan);ctx.scale(zoom,zoom);ctx.lineWidth=1/zoom;
  ctx.strokeStyle='#c5e3d522';ctx.beginPath();for(let i=-100;i<=100;i++){
   ctx.moveTo((i+100)*64,(i-100)*32);ctx.lineTo((i-100)*64,(i+100)*32);ctx.moveTo((-100-i)*64,(-100+i)*32);ctx.lineTo((100-i)*64,(100+i)*32);
  }ctx.stroke();
  for(const v of [...scene.instances].sort(order)){
   const m=scene.modules.find(m=>m.id===v.module),[x,y]=v.position;ctx.drawImage(images.get(m.image),x-m.anchor[0]*scale(m),y-m.anchor[1]*scale(m),m.canvas_px[0]*scale(m),m.canvas_px[1]*scale(m));
   if($('show-collision').checked)for(const poly of m.polygons)polygon(ctx,poly.map(p=>[p[0]*scale(m)+x,p[1]*scale(m)+y]),'#ff624a55');
   if(v.id===selectedInstance){ctx.strokeStyle='#ffe194';ctx.strokeRect(x-m.anchor[0]*scale(m),y-m.anchor[1]*scale(m),m.canvas_px[0]*scale(m),m.canvas_px[1]*scale(m));ctx.fillStyle='#ffe194';ctx.fillRect(x-3/zoom,y-3/zoom,6/zoom,6/zoom);}
  }
  if(hover&&$('tool').value==='place'&&module()){
   const m=module(),p=snap(hover);ctx.globalAlpha=.5;ctx.drawImage(images.get(m.image),p[0]-m.anchor[0]*scale(m),p[1]-m.anchor[1]*scale(m),m.canvas_px[0]*scale(m),m.canvas_px[1]*scale(m));ctx.globalAlpha=1;
  }
  ctx.beginPath();ctx.arc(...scene.spawn,8,0,Math.PI*2);ctx.fillStyle='#ffe194';ctx.fill();ctx.restore();
  $('layout-summary').textContent=`${scene.modules.length} 个模块 · ${scene.instances.length} 个实例${dirty?' · 未保存':' · 已保存'}`;
  $('zoom-label').textContent=Math.round(zoom*100)+'%';$('undo').disabled=!undoStack.length;$('redo').disabled=!redoStack.length;
  const v=instance();$('duplicate').disabled=$('delete').disabled=$('edit-selected').disabled=!v;
  $('instance-x').disabled=$('instance-y').disabled=!v;
  if(v){$('selection-label').textContent=scene.modules.find(m=>m.id===v.module).title;$('instance-x').value=v.position[0];$('instance-y').value=v.position[1];}
  else{$('selection-label').textContent=$('tool').value==='place'&&module()?'正在放置：'+module().title:'未选中物件';$('instance-x').value=$('instance-y').value='';}
 }
 function resizeCanvas(){const c=$('scene-canvas');if(c.clientWidth&&c.clientHeight){const old=[c.width,c.height];c.width=Math.round(c.clientWidth);c.height=Math.round(c.clientHeight);pan=[pan[0]+(c.width-old[0])/2,pan[1]+(c.height-old[1])/2];drawScene();}}
 function fitView(){
  if(!scene)return;const c=$('scene-canvas');let minX=scene.spawn[0]-30,maxX=scene.spawn[0]+30,minY=scene.spawn[1]-30,maxY=scene.spawn[1]+30;
  for(const v of scene.instances){const m=scene.modules.find(m=>m.id===v.module);minX=Math.min(minX,v.position[0]-m.anchor[0]*scale(m));maxX=Math.max(maxX,v.position[0]-m.anchor[0]*scale(m)+m.canvas_px[0]*scale(m));minY=Math.min(minY,v.position[1]-m.anchor[1]*scale(m));maxY=Math.max(maxY,v.position[1]-m.anchor[1]*scale(m)+m.canvas_px[1]*scale(m));}
  zoom=scene.instances.length?Math.min(1.5,(c.width-100)/Math.max(1,maxX-minX),(c.height-100)/Math.max(1,maxY-minY)):1;
  zoom=Math.max(.2,zoom);pan=[c.width/2-(minX+maxX)*zoom/2,c.height/2-(minY+maxY)*zoom/2];drawScene();
 }
 function canvasPoint(c,e){const r=c.getBoundingClientRect();return [(e.clientX-r.left)*c.width/r.width,(e.clientY-r.top)*c.height/r.height];}
 function worldPoint(e){const p=canvasPoint($('scene-canvas'),e);return [(p[0]-pan[0])/zoom,(p[1]-pan[1])/zoom];}

 function snap(p){if(!$('snap').checked)return p.map(Math.round);const a=Math.round(p[0]/128+p[1]/64),b=Math.round(p[1]/64-p[0]/128);return [(a-b)*64,(a+b)*32];}
 function hitAt(p){return [...scene.instances].sort((a,b)=>order(b,a)).find(v=>{
  const m=scene.modules.find(m=>m.id===v.module),x=Math.floor((p[0]-v.position[0])/scale(m)+m.anchor[0]),y=Math.floor((p[1]-v.position[1])/scale(m)+m.anchor[1]),data=pixels.get(m.image);
  return x>=0&&y>=0&&x<data.width&&y<data.height&&data.data[(y*data.width+x)*4+3]>20;
 });}
 function place(id,p){requireSavedModule();checkpoint();const v={id:crypto.randomUUID(),module:id,position:snap(p)};scene.instances.push(v);selectedInstance=v.id;changed();}
 function duplicate(){const v=instance();if(!v)return;checkpoint();const copy={...structuredClone(v),id:crypto.randomUUID(),position:[v.position[0]+128,v.position[1]]};scene.instances.push(copy);selectedInstance=copy.id;changed();}
 function remove(){if(!instance())return;checkpoint();scene.instances=scene.instances.filter(v=>v.id!==selectedInstance);selectedInstance=null;changed();}
 async function saveLayout(){
  if(!scene)return;if(saving)throw Error('正在保存，请稍候。');saving=true;
  const sent=snapshot();try{const saved=await mutate({action:'layout',...sent});scene.revision=saved.revision;
   dirty=JSON.stringify(snapshot())!==JSON.stringify(sent);drawScene();status(dirty?'已保存；后续修改尚未保存。':'布局已保存。');
  }finally{saving=false;}
 }
 async function saveModule(config){
  if(dirty)await saveLayout();const saved=await mutate({action:'module',module:selectedModule,...config});
  scene.revision=saved.revision;scene.modules=saved.modules;renderModules();drawScene();
  status('模块设置已保存为素材库新版本，当前场景引用已更新。');return module();
 }
 let library=[],replaceTarget=null;
 function paintLibrary(){
  const term=$('library-search').value.toLowerCase();const shown=library.filter(a=>(a.title+' '+a.id).toLowerCase().includes(term));
  $('library-assets').replaceChildren(...shown.map(asset=>{
   const card=document.createElement('div');card.className='library-item';const img=document.createElement('img');if(asset.image)img.src=asset.image;img.alt=asset.family==='character'?'人物动作包':'';
   const title=document.createElement('strong');title.textContent=asset.title;const version=document.createElement('small');version.textContent=asset.id+(asset.family==='building'?' · 建筑线稿来源，视角需目视复核':'');
   const button=document.createElement('button');button.textContent=asset.view===scene.projection?(replaceTarget?'替换此引用':'加入场景'):'视角不兼容';button.disabled=asset.view!==scene.projection;
   button.onclick=run(async()=>{if(dirty)await saveLayout();const saved=await mutate({action:'adopt',kit:asset.id,family:asset.family||'prop',...(replaceTarget?{module:replaceTarget}:{})});scene=saved;
    selectedModule=replaceTarget||scene.modules.find(m=>m.source?.id===asset.id||(asset.family==='character'&&m.character_id===asset.id)).id;await Promise.all(scene.modules.map(image));renderModules();drawScene();$('library-dialog').close();setTool('place');status('已引用素材库版本；点击画布放置。');});
   card.append(img,title,version,button);return card;
  }));
 }
 async function openLibrary(replace=false){requireSavedModule();replaceTarget=replace?selectedModule:null;if(replace&&!replaceTarget)throw Error('请先选择素材');library=(await api('/api/module-scenes/library')).assets;paintLibrary();$('library-dialog').showModal();}
 $('show-library').onclick=run(()=>openLibrary());$('replace-source').onclick=run(()=>openLibrary(true));
 $('library-search').oninput=paintLibrary;$('close-library').onclick=()=>$('library-dialog').close();
 $('new-scene').onclick=()=>$('new-dialog').showModal();
 $('create').onclick=run(async()=>{requireSavedModule();if(dirty)await saveLayout();const s=await mutate({action:'create',title:$('scene-title').value});$('new-dialog').close();await refresh(s.id);status('场景已创建。');});
 $('scenes').onchange=run(async()=>{const id=$('scenes').value;$('scenes').value=scene?.id||'';requireSavedModule();if(dirty)await saveLayout();await refresh(id);});
 $('show-import').onclick=()=>{if(!scene)return status('请先创建场景。',true);$('import-dialog').showModal();};
 $('cancel-import').onclick=()=>$('import-dialog').close();
 $('image-file').onchange=()=>{if(!$('module-title').value)$('module-title').value=$('image-file').files[0]?.name.replace(/\.png$/i,'')||'';};
 $('import-form').onsubmit=run(async e=>{
  e.preventDefault();requireSavedModule();if(dirty)await saveLayout();const f=$('image-file').files[0];if(!f)throw Error('请选择PNG');
  const data=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(f);});
  const saved=await mutate({action:'import',title:$('module-title').value,image:data});selectedModule=saved.modules.at(-1).id;
  $('import-dialog').close();await refresh(saved.id);openEditor();status('已导入；设置锚点和碰撞后保存。');
 });
 $('modules').onchange=run(()=>chooseModule($('modules').value));
 $('open-editor').onclick=run(openEditor);$('edit-selected').onclick=run(()=>{chooseModule(instance().module);openEditor();});
 for(const b of document.querySelectorAll('[data-tool]'))b.onclick=()=>setTool(b.dataset.tool);
 $('tool').onchange=()=>setTool($('tool').value);
 const c=$('scene-canvas');c.oncontextmenu=e=>e.preventDefault();
 c.onpointerdown=run(e=>{
  if(!scene)return;c.focus();c.setPointerCapture(e.pointerId);hover=null;
  if(e.button===1||e.button===2||space){e.preventDefault();drag={pan:[...pan],start:canvasPoint(c,e)};return;}
  if(e.button!==0)return;const p=worldPoint(e);
  if($('tool').value==='spawn'){checkpoint();scene.spawn=snap(p);changed();return;}
  if($('tool').value==='place'){if(!module())return status('先导入或选择素材。',true);place(selectedModule,p);return;}
  const hit=hitAt(p);selectedInstance=hit?.id;
  if(hit){chooseModule(hit.module);drag={instance:hit,start:p,position:[...hit.position],started:false};}else drag=null;drawScene();
 });
 c.onpointermove=e=>{
  if(!scene)return;if(!drag){hover=worldPoint(e);if($('tool').value==='place')drawScene();return;}
  if(drag.pan){const p=canvasPoint(c,e);pan=[drag.pan[0]+p[0]-drag.start[0],drag.pan[1]+p[1]-drag.start[1]];}
  else{const p=worldPoint(e);if(!drag.started&&Math.hypot(p[0]-drag.start[0],p[1]-drag.start[1])*zoom<3)return;
   if(!drag.started){checkpoint();drag.started=true;}const delta=snap([p[0]-drag.start[0],p[1]-drag.start[1]]);
   drag.instance.position=[drag.position[0]+delta[0],drag.position[1]+delta[1]];dirty=true;
  }drawScene();
 };
 c.onpointerup=c.onpointercancel=()=>{drag=null;};c.onpointerleave=()=>{hover=null;if(!drag)drawScene();};
 c.ondblclick=run(e=>{if($('tool').value!=='select')return;const hit=hitAt(worldPoint(e));if(hit){selectedInstance=hit.id;chooseModule(hit.module);openEditor();}});
 c.ondragover=e=>{e.preventDefault();e.dataTransfer.dropEffect='copy';};
 c.ondrop=run(e=>{e.preventDefault();const id=e.dataTransfer.getData('application/studio-module');if(!scene.modules.some(m=>m.id===id))return;chooseModule(id);place(id,worldPoint(e));setTool('select');c.focus();});
 function zoomAt(factor,p=[c.width/2,c.height/2]){const before=[(p[0]-pan[0])/zoom,(p[1]-pan[1])/zoom];zoom=Math.max(.15,Math.min(5,zoom*factor));pan=[p[0]-before[0]*zoom,p[1]-before[1]*zoom];drawScene();}
 c.addEventListener('wheel',e=>{e.preventDefault();zoomAt(Math.exp(-e.deltaY*.002),canvasPoint(c,e));},{passive:false});
 $('delete-scene').onclick=async()=>{if(!scene)return;if(await window.StudioDelete({kind:'scene',id:scene.id}))location.assign('/module-scenes.html');};
 $('duplicate').onclick=duplicate;$('delete').onclick=remove;$('undo').onclick=()=>undo();$('redo').onclick=()=>undo(true);
 $('save-layout').onclick=run(saveLayout);$('show-collision').onchange=drawScene;
 for(const id of ['instance-x','instance-y'])$(id).onchange=()=>{const v=instance();if(!v)return;const value=Number($(id).value);if(!Number.isFinite(value)||Math.abs(value)>100000)return status('坐标超出范围。',true);checkpoint();v.position[id==='instance-x'?0:1]=value;changed();};
 $('zoom-in').onclick=()=>zoomAt(1.25);$('zoom-out').onclick=()=>zoomAt(1/1.25);$('reset-view').onclick=fitView;
 $('export').onclick=run(async e=>{
  e.preventDefault();requireSavedModule();if(dirty)await saveLayout();const r=await fetch($('export').href);if(!r.ok)throw Error((await r.json()).error);
  const a=document.createElement('a');a.href=URL.createObjectURL(await r.blob());a.download='studio-module-scene.zip';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);status('已导出当前保存版本。');
 });
 window.addEventListener('keydown',e=>{
  const cmd=e.metaKey||e.ctrlKey,key=e.key.toLowerCase();
  if(editor.dialog.open)return;
  if(cmd&&key==='s'&&scene){e.preventDefault();e.target.blur();if(!document.querySelector('dialog[open]'))run(saveLayout)();return;}
  if(/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)||e.target.isContentEditable)return;
  if(document.querySelector('dialog[open]')||!scene)return;
  if(cmd&&key==='s'){e.preventDefault();run(saveLayout)();return;}
  if(cmd&&key==='z'){e.preventDefault();undo(e.shiftKey);return;}
  if(cmd&&key==='d'){e.preventDefault();duplicate();return;}
  if(cmd)return;
  if(e.code==='Space'){e.preventDefault();space=true;c.style.cursor='grab';return;}
  if(key==='v'||e.key==='Escape')setTool('select');else if(key==='b')setTool('place');
  else if(e.key==='Delete'||e.key==='Backspace'){e.preventDefault();remove();}
  else if(e.key.startsWith('Arrow')&&instance()){
   e.preventDefault();checkpoint();const v=instance(),step=e.shiftKey?16:1;
   v.position[0]+=e.key==='ArrowLeft'?-step:e.key==='ArrowRight'?step:0;
   v.position[1]+=e.key==='ArrowUp'?-step:e.key==='ArrowDown'?step:0;changed();
  }
 });
 window.addEventListener('keyup',e=>{if(e.code==='Space'){space=false;c.style.cursor=$('tool').value==='select'?'default':'crosshair';}});
 window.addEventListener('blur',()=>{space=false;drag=null;});
 window.addEventListener('beforeunload',e=>{if(dirty||editor.dirty){e.preventDefault();e.returnValue='';}});
 new ResizeObserver(()=>resizeCanvas()).observe(c);
 setTool('select');run(()=>refresh(new URLSearchParams(location.search).get('scene')))();
})();

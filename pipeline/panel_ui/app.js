'use strict';
const $=id=>document.getElementById(id);
const actionNames={import_model:'导入外部模型',optimize:'模型减面对比',adopt_model:'采用优化模型',reconstruct:'生成模型与贴图',prepare:'准备贴图',rig:'骨骼绑定',download:'导入动画',review:'生成姿态检查',bake:'渲染图集',equipment:'调整武器挂点',weapon:'独立武器重建',sequence:'编排统一渲染',compact:'图集精简',palette:'颜色简化'};
const statusNames={queued:'排队中',running:'执行中',succeeded:'已完成',failed:'失败',interrupted:'已中断'};
let state=null,selected=localStorage.getItem('studio-character')||'',token='',busy=false,refreshId=0,refreshing=false,viewKey='',selection={type:'model'},logTask='',draft=[],animationFrame=0,player=null,uploadUrl;
let preferences={};try{preferences=JSON.parse(localStorage.getItem('studio-preferences')||'{}');}catch{}
function prefs(){return preferences[selected]||(preferences[selected]={frame_size:64,supersample:4,view:'three_quarter'});}
function remember(){localStorage.setItem('studio-preferences',JSON.stringify(preferences));}
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function button(text,fn,cls='',disabled=false){const b=node('button',text,cls);b.type='button';b.disabled=disabled;b.onclick=fn;return b;}
function note(text){return node('p',text,'hint');}
function field(label,element){const box=node('div');const l=node('label',label);element.id='field-'+label;l.htmlFor=element.id;box.append(l,element);return box;}
function select(options,value,onchange){const s=node('select');for(const [v,t]of options){const o=node('option',t);o.value=v;s.append(o);}s.value=String(value??'');if(!s.value&&options.length)s.selectedIndex=0;s.onchange=()=>onchange(s.value);return s;}
function link(text,url,external=false){const a=node('a',text,'download-link');a.href=url;if(external){a.target='_blank';a.rel='noopener noreferrer';}return a;}
function details(title,...children){const d=node('details');d.append(node('summary',title),...children);return d;}
function properties(values){const d=node('dl',undefined,'properties');for(const [key,value]of values){d.append(node('dt',key),node('dd',String(value??'—')));}return d;}
function image(url,alt){const i=node('img');i.src=url;i.alt=alt;i.title='点击放大';i.onclick=()=>{$('large-preview').src=url;$('large-preview').alt=alt;$('image-dialog').showModal();};return i;}
function stageImage(url,alt){const box=node('div',undefined,'image-stage');box.append(image(url,alt));return box;}
function placeholder(title,text){const box=node('div',undefined,'placeholder');box.append(node('h3',title),node('p',text));return box;}
function notify(text,error=false){$('notice').hidden=false;$('notice').className=error?'error':'';$('notice').textContent=text;}
function isRunning(j){return ['queued','running'].includes(j.status);}
function active(){return state?.jobs.some(isRunning);}
function blocked(){return busy||active();}
function readyServer(){return state?.api_version>=22;}
function ownJobs(){return state.jobs.filter(j=>j.character===selected);}
function rendererName(value){return value==='blender'?'Blender · Eevee':'Godot';}
function usageSummary(usage,clip){if(!usage)return '手持';const action=usage.clips?.[clip]||{};const initial=action.initial&&action.initial!=='inherit'?action.initial:usage.default||'hand';return [usageLabels[initial],...(action.events||[]).map(e=>`${Math.round(e.at*100)}% → ${usageLabels[e.state]}`)].join(' · ');}
function comparableDelivery(deliveries,backend,current){const candidates=deliveries.filter(d=>(d.renderer||'godot')===backend);const score=d=>(d.equipment?.id===current.equipment?.id?8:0)+(d.settings?.frame_size===current.settings?.frame_size?4:0)+(d.clips?.[0]?.info?.view===current.clips?.[0]?.info?.view?2:0)+(d.settings?.supersample===current.settings?.supersample?1:0);return candidates.sort((a,b)=>score(b)-score(a))[0];}
function clipName(file){return file.replace(/\.fbx$/i,'');}
function animationTitle(b,file){return b.titles?.[file]||clipName(file);}
function sourceTime(id){return /^\d{8}-\d{6}/.test(id)?`${id.slice(4,6)}/${id.slice(6,8)} ${id.slice(9,11)}:${id.slice(11,13)}`:id;}
function motionApproved(c,b){return c.approvals.motions?.[b.id]?.fingerprint===b.fingerprint;}
function animationApproved(c,b,file){return motionApproved(c,b)||c.approvals.animations?.[b.id]?.[file]?.fingerprint===b.fingerprint;}
function batchApproved(c,b){return motionApproved(c,b)||b.files.every(file=>animationApproved(c,b,file));}
function reviewFor(c,b){return c.reviews.find(r=>r.batch===b.id&&(!b.hashes||Object.keys(b.hashes).length===Object.keys(r.files||{}).length&&Object.entries(b.hashes).every(([file,hash])=>r.files?.[file]===hash))&&b.files.every(file=>Math.abs(Number(r.headings?.[file]?.degrees||0)-Number(b.headings?.[file]?.degrees||0))<0.001));}
// Resource identity includes the import source. Same-named animations never share approval or equipment accidentally.
function animationResources(c){
 const ordered=[...c.batches.filter(b=>b.current_rig),...c.batches.filter(b=>!b.current_rig)];
 const groups=new Map();
 for(const b of ordered)for(const file of b.files){const key=clipName(file);if(!groups.has(key))groups.set(key,[]);groups.get(key).push({key,file,batch:b,id:b.id+'/'+file});}
 return [...groups.values()].map(versions=>({...versions[0],versions}));
}
function chosenAnimation(c){const resources=animationResources(c);const row=resources.find(a=>a.key===selection.key)||resources[0];if(!row)return null;return row.versions.find(v=>v.id===selection.version)||row;}
function chosenBatch(c){if(selection.type==='animation')return chosenAnimation(c)?.batch;return c.batches.find(b=>b.id===prefs().source)||c.batches.find(b=>b.current_rig)||c.batches[0];}
function equipmentFor(c,b){return b?c.equipment.filter(e=>state.api_version>=5?(e.compatible_batches||[]).includes(b.id):e.batch===b.id):[];}
function selectedEquipment(c,b){const items=equipmentFor(c,b);return items.find(e=>e.id===prefs().equipment)||(prefs().equipment===undefined?items[0]:null);}
function choose(value){libraryOpen=false;if(value.type==='equipment'&&value.equipment)prefs().equipment=value.equipment;selection=value;activePage=pageFor(value);prefs().workspacePage=activePage;prefs().editorSelection=value;remember();viewKey='';renderWorkspace();window.scrollTo({top:0});document.querySelector('.inspector-panel')?.scrollTo({top:0});}
function switchCharacter(id){libraryOpen=false;activePage='character';selected=id;state=null;selection={type:'model'};$('jobs').dataset.signature='';logTask='';$('log-box').open=false;$('log').textContent='';stopPlayback();$('workspace').hidden=true;localStorage.setItem('studio-character',id);refresh(true);}
async function api(path,data){const r=await fetch(path,{method:data?'POST':'GET',cache:'no-store',headers:data?{'Content-Type':'application/json','X-Studio-Token':token}:{},body:data?JSON.stringify(data):undefined});const value=await r.json();if(!r.ok)throw Error(value.error||'请求失败');return value;}
async function mutation(path,data,message='已提交。任务会自动保存，可继续浏览已有资源。'){if(blocked())return false;busy=true;renderWorkspace(true);try{const response=await api(path,data);if(['compact','bake','palette'].includes(data.action)&&data.character===selected){prefs().pendingCompact=response.id;remember();}notify(message);await refresh(true);return true;}catch(e){notify(e.message,true);return false;}finally{busy=false;renderWorkspace(true);}}
function start(action,params={}){const run=()=>mutation('/api/tasks',{character:selected,action,params});if(action==='reconstruct'&&state.selected.has_model){$('confirm-regenerate').showModal();$('confirm-regenerate-submit').onclick=()=>{$('confirm-regenerate').close();run();};return;}return run();}
function openTasks(){ $('task-details').hidden=false;$('toggle-tasks').setAttribute('aria-expanded','true'); }
function renderTasks(){const jobs=ownJobs(),current=jobs.find(isRunning)||jobs[0];const other=state.jobs.find(isRunning);$('task-summary').textContent=current?`${actionNames[current.action]} · ${statusNames[current.status]}${isRunning(current)?' · '+(state.selected.progress?.message||'正在启动'):''}`:other?'其他人物正在执行任务，当前人物仍可浏览':'暂无执行任务 · 修改与生成结果自动保存';
 if($('task-details').hidden)return;
 const root=$('jobs');const signature=JSON.stringify(jobs);if(root.dataset.signature===signature){if($('log-box').open)refreshLog();return;}root.dataset.signature=signature;root.replaceChildren();const ordered=current?[current,...jobs.filter(j=>j.id!==current.id)].slice(0,10):[];
 for(const job of ordered){const row=node('div',undefined,'job-row'+(isRunning(job)?' active':'')),body=node('div');body.append(node('strong',`${actionNames[job.action]} · ${statusNames[job.status]}`),node('small',new Date(job.started_at||job.created_at).toLocaleString()));if(job.error)body.append(node('p',job.error,'job-error'));row.append(body,button('日志',()=>{logTask=job.id;$('log-box').open=true;refreshLog();}));if(['failed','interrupted'].includes(job.status))row.append(button('重试',()=>mutation('/api/tasks',{character:selected,retry:job.id}),'',blocked()));root.append(row);}
 if($('log-box').open)refreshLog();
}
async function refreshLog(){if(!logTask){$('log').textContent='选择一个任务查看日志。';return;}try{$('log').textContent=(await api('/api/log?task='+encodeURIComponent(logTask))).text||'等待日志…';}catch(e){$('log').textContent=e.message;}}
function resourceItem(text,status,selectedValue,fn,warning=false){const b=button('',fn,'resource-item'+(selectedValue?' selected':''));b.setAttribute('aria-pressed',String(selectedValue));b.append(node('span',text),node('small',status,warning?'warning':''));return b;}
function resourceSection(title,add){const s=node('section',undefined,'resource-section'),head=node('div',undefined,'resource-section-head');head.append(node('span',title));if(add)head.append(button('＋ 添加',add));s.append(head);return s;}
function setTitles(kind,title,inspector){$('preview-kind').textContent=kind;$('preview-title').textContent=title;$('control-title').textContent=inspector;}
function renderModel(c){setTitles('MODEL','模型与贴图','模型属性');const content=$('preview-content'),controls=$('controls'),p=prefs();if(!c.inputs.some(i=>i.path===p.image))p.image=c.inputs[0]?.path||'';
 if(c.inputs.length)controls.append(field('来源原画',select(c.inputs.map((i,index)=>[i.path,`原画 ${c.inputs.length-index} · ${sourceTime(i.path.split('/').at(-2))}`]),p.image,v=>{p.image=v;remember();renderWorkspace(true);})),button('导入另一张原画',()=>openUpload(c.id),'full',blocked()));
 if(c.prepared){content.append(stageImage(c.prepared.contact,'人物多角度模型检查图'));controls.append(properties([['三角面',c.prepared.info.triangles_after],['贴图尺寸',c.prepared.info.texture_resolution],['外观状态',c.model_approved?'已确认':'待检查']]));controls.append(button(c.model_approved?'✓ 模型外观已确认':'确认模型外观',()=>mutation('/api/approve',{character:selected,kind:'model',fingerprint:c.prepared.fingerprint}),'primary full',blocked()||c.model_approved));controls.append(note('检查四肢分离、背面和悬浮碎片。确认只对应当前模型。'));if(c.model_approved&&!c.rig.ready)controls.append(button('设置骨骼绑定',()=>choose({type:'rig'}),'full'));controls.append(link('下载模型 GLB',c.prepared.glb));renderModelOptimization(c,controls);const advanced=details('重新生成与贴图',button('用所选原画重新生成',()=>start('reconstruct',{image:p.image}),'full',blocked()||!p.image),button('重新准备贴图',()=>start('prepare'),'full',blocked()),note('更新模型后需要重新确认外观和绑定，历史导出保留。'));if(c.prepared.info.origin!=='import_glb')controls.append(advanced);else controls.append(note('来源：直接导入 GLB。原始文件已保留；无需重新建模或烘焙顶点颜色。'));if(p.image)content.append(details('查看来源原画',stageImage(c.inputs.find(i=>i.path===p.image).url,'所选原画')));$('viewport-note').textContent='当前显示已生成的多角度检查图。';}
 else{const input=c.inputs.find(i=>i.path===p.image);content.append(input?stageImage(input.url,'人物原画'):placeholder('导入一张人物原画','全身立姿、轮廓简洁、四肢与躯干分离。'));controls.append(button('生成模型与贴图',()=>start('reconstruct',{image:p.image}),'primary full',blocked()||!p.image),note('生成完成后在这里检查模型，再设置骨骼绑定。'));}
}
function renderRig(c){setTitles('RIG','骨骼绑定','绑定属性');const controls=$('controls'),content=$('preview-content');content.append(c.prepared?stageImage(c.prepared.contact,'待绑定模型'):placeholder('先准备模型','生成模型并确认外观后，才能绑定骨骼。'));controls.append(node('div',c.rig.ready?'✓ 当前模型骨骼绑定可用':c.rig.status==='needs_review'?'Mixamo 人物需要重新确认':'尚未完成绑定',c.rig.ready?'approval-state':'callout'));if(c.rig.error)controls.append(note(c.rig.error));controls.append(button(c.rig.ready?'重新打开 Mixamo 绑定':'打开 Mixamo 绑定',()=>start('rig'),'primary full',blocked()||!c.model_approved),note('1. 在弹出的 Mixamo 窗口登录并放置关节点。\n2. 检查关节变形。\n3. 点击 Mixamo 左下角的 Studio 确认。'));if(!c.model_approved)controls.append(button('前往检查模型',()=>choose({type:'model'}),'full'));if(c.rig.ready)controls.append(button('＋ 添加动画',openAdd,'full'));$('viewport-note').textContent='关节点标注在 Mixamo 窗口完成；执行状态可在下方任务栏查看。';}
function renderPoses(review,key){const content=$('preview-content');const images=review.images.filter(i=>i.name.startsWith(key+'_'));const gallery=node('div',undefined,'gallery');for(const im of images){const f=node('figure');f.append(image(im.url,im.name),node('figcaption',im.name));gallery.append(f);}content.append(images.length?gallery:placeholder('没有此动画的姿态截图','重新生成姿态检查后查看。'));}
function renderEquipment(c){setTitles('EQUIPMENT','装备与挂点','装备属性');const controls=$('controls'),content=$('preview-content');const p=prefs();const sources=c.batches.filter(b=>b.current_rig);const b=chosenBatch(c);let e=c.equipment.find(e=>e.id===selection.equipment);const weapons=(state.weapons||[]).filter(w=>w.confirmed);if(!e&&p.weapon===undefined&&weapons.length)p.weapon=weapons[0].id;
 controls.append(field('检查用动画',select(sources.map(b=>[b.id,b.files.map(file=>animationTitle(b,file)).join(', ')]),b?.id,v=>{prefs().source=v;remember();choose({type:'equipment',equipment:selection.equipment});})),properties([['武器模型',e?.weapon_name||((state.weapons||[]).find(w=>w.id===p.weapon)?.name)||'标准单手剑'],['挂点',e?e.bone.includes('Right')?'右手':'左手':'在握持窗口设置'],['尺寸倍率',e?.scale]]));if(!b||!b.current_rig)controls.append(node('div','先完成绑定并导入动画，再调整挂点。','callout'));
 if(!e){controls.append(field('选择武器',select([['','内置标准剑'],...weapons.map(w=>[w.id,w.name+' · '+w.length_meters+'m'])],p.weapon||'',v=>{p.weapon=v;remember();renderWorkspace(true);})));if((state.weapons||[]).some(w=>!w.confirmed))controls.append(note('独立武器需先在左侧设置总长和握点并确认。'));}
 controls.append(button(e?'编辑武器握持':'装备所选武器并设置挂点',()=>start('equipment',{batch:b?.id,...(e?{equipment_id:e.id}:p.weapon?{weapon_id:p.weapon}:{})}),'primary full',blocked()||!b?.current_rig||!!e&&!equipmentFor(c,b).some(item=>item.id===e.id)),note('在独立 3D 窗口调整握点、朝向与尺寸，再播放动画检查。\n红点调整握点，绿点调整剑尖朝向。'));
 if(e){controls.append(usageEditor(c,e,null));controls.append(note('挂点保存在人物的绑定版本上，新增动作无需重新标注。更换绑定后需要复核。'));content.append(e.preview?stageImage(e.preview,'武器握持检查'):placeholder('握持配置已保存','打开握持窗口检查实际效果。'));controls.append(link('下载握持配置',e.config),button('使用此装备导出…',()=>{prefs().equipment=e.id;remember();openExport(b?.id);},'full'));$('viewport-note').textContent='当前显示已保存的装备检查图。同一人物、同一绑定的动作可直接复用此装备。预览图来自保存时的动作。';}
 else{content.append(c.prepared?stageImage(c.prepared.contact,'人物模型'):placeholder('为人物配置装备','先准备人物模型与动画。'));$('viewport-note').textContent='添加武器后，需要检查穿插和握持姿态。普通动画不会因此变成挥剑动画。';}
}
function stopPlayback(){cancelAnimationFrame(animationFrame);if(player)player.cancelled=true;player=null;$('playback').hidden=true;}
function mountPlayer(item,resume=null){const stage=node('div',undefined,'sprite-stage'),canvas=node('canvas');stage.append(canvas);$('preview-content').append(stage);const info=item.info,count=Number(info.frame_count),w=Number(info.frame_width),h=Number(info.frame_height);if(!(count>0&&w>0&&h>0)){stage.replaceChildren(note('图集缺少帧信息，请重新渲染。'));return;}canvas.width=w;canvas.height=h;if(info.body_height_px){const zoom=Number(prefs().spriteZoom)||1;canvas.style.width=w*zoom+'px';canvas.style.height=h*zoom+'px';}const ctx=canvas.getContext('2d'),img=new Image();const p=player={canvas,ctx,img,count,w,h,frame:0,playing:false,fps:Number(info.fps)||count/Number(info.duration_seconds)||12,timing:clipTiming(info),frameMap:info.preview_source_indices||null,position:0,last:0,cancelled:false};
 img.onload=()=>{if(p.cancelled||player!==p)return;const capacity=Math.floor(img.naturalWidth/w)*Math.floor(img.naturalHeight/h);if(capacity<count){stage.replaceChildren(note('图集尺寸与帧数不符，请重新渲染。'));return;}$('timeline').max=count-1;$('timeline').value=0;$('playback').hidden=false;if(resume){p.position=Math.min(Number(resume.position)||0,p.timing.duration);p.frame=heldFrameAt(p.timing,p.position);}drawFrame(p);setPlaying(resume?resume.playing:true);animationFrame=requestAnimationFrame(tick);};img.onerror=()=>{if(!p.cancelled)stage.replaceChildren(note('图集加载失败，可重新选择动画或检查连接。'));};img.src=item.sheet;
}
function drawFrame(p){if(p.plan)return drawSequenceFrame(p);const cols=Math.floor(p.img.naturalWidth/p.w),index=p.frameMap?p.frameMap[p.frame]:p.frame;p.ctx.clearRect(0,0,p.w,p.h);p.ctx.imageSmoothingEnabled=false;p.ctx.drawImage(p.img,(index%cols)*p.w,Math.floor(index/cols)*p.h,p.w,p.h,0,0,p.w,p.h);$('timeline').value=p.frame;$('frame-label').textContent=`${p.frame+1} / ${p.count}`;}
function setPlaying(value){if(!player)return;if(value&&player.plan&&player.position>=player.plan.duration){player.position=0;player.frame=0;}player.playing=value;player.last=performance.now();$('play-pause').textContent=value?'暂停':'播放';$('play-pause').setAttribute('aria-label',value?'暂停动画':'播放动画');}
function tick(time){const p=player;if(!p||p.cancelled)return;if(p.plan){tickSequence(p,time);animationFrame=requestAnimationFrame(tick);return;}if(p.playing){p.position=(p.position+Math.max(0,time-p.last)/1000*Number($('play-speed').value))%p.timing.duration;p.frame=heldFrameAt(p.timing,p.position);drawFrame(p);}p.last=time;animationFrame=requestAnimationFrame(tick);}
$('play-pause').onclick=()=>{if(player)setPlaying(!player.playing);};$('timeline').oninput=()=>{if(player){setPlaying(false);player.frame=Number($('timeline').value);player.position=player.plan?sequenceTime(player.plan,player.frame):player.timing.starts[player.frame];drawFrame(player);}};
const ROLE_LABELS={idle:'待机',walk:'走路',run:'跑步',jump:'跳跃',attack:'攻击'};
let draftRoles={},draftPreset=null;
function presetPayload(){return {actions:[...draft],roles:Object.fromEntries(draft.filter(t=>draftRoles[t]).map(t=>[t,draftRoles[t]])),...(draftPreset?{preset:draftPreset}:{})};}
function applyActionPreset(preset){
 if(!preset)return;
 draft=preset.actions.map(a=>a.title);draftRoles=Object.fromEntries(preset.actions.map(a=>[a.title,a.role]));draftPreset={id:preset.id,version:preset.version};renderDraft();
}
function renderActionPresets(){const root=$('action-presets');root.replaceChildren();
 for(const preset of state?.action_presets||[])root.append(button('使用'+preset.name+'预设',()=>applyActionPreset(preset),'full'));
 root.append(note('预设填好常用标题，可替换或移除。Mixamo 同名表演仍需核对；循环用途为建议，下载后须验收。'));
}
function openAdd(){draft=[];draftRoles={};draftPreset=null;$('animation-name').value='';renderActionPresets();renderDraft();$('add-animation-dialog').showModal();}
function replaceDraftTitle(index,value){const previous=draft[index];value=value.trim();
 if(!/^[A-Za-z0-9][A-Za-z0-9 _-]{0,59}$/.test(value)||draft.some((v,i)=>i!==index&&v.toLowerCase().replaceAll(' ','_')===value.toLowerCase().replaceAll(' ','_'))){notify('标题无效或已在清单中。',true);renderDraft();return;}
 const role=draftRoles[previous];delete draftRoles[previous];if(role)draftRoles[value]=role;draft[index]=value;renderDraft();
}
function appendDraft(){const input=$('animation-name'),value=input.value.trim();if(!value)return;if(!/^[A-Za-z0-9][A-Za-z0-9 _-]{0,59}$/.test(value)){notify('按 Mixamo 原标题填写英文、数字、空格或短横线。',true);return;}if(draft.some(v=>v.toLowerCase().replaceAll(' ','_')===value.toLowerCase().replaceAll(' ','_'))){notify('该动画已经在清单中。',true);return;}if(draft.length>=12){notify('每次最多导入 12 个动画。',true);return;}draft.push(value);input.value='';renderDraft();input.focus();}
function renderDraft(){const root=$('animation-draft');root.replaceChildren();for(const [i,name]of draft.entries()){
 const row=node('li',undefined,'preset-action'),label=node('span',draftRoles[name]?ROLE_LABELS[draftRoles[name]]: '自选'),input=node('input');input.value=name;input.maxLength=60;input.setAttribute('aria-label',(ROLE_LABELS[draftRoles[name]]||'自选')+' Mixamo 标题');input.onchange=()=>replaceDraftTitle(i,input.value);
 const preview=link('Mixamo 预览 ↗','https://www.mixamo.com/#/?page=1&type=Motion%2CMotionPack&query='+encodeURIComponent(name),true);
 const key=name.toLowerCase().replaceAll(' ','_'),existing=state?.selected?.deliveries?.flatMap(d=>d.clips).find(c=>c.name===key);
 if(existing){const img=node('img');img.src=existing.gif;img.alt=name+' 已有渲染示例';row.append(img);}
 row.append(label,input,preview,button('移除',()=>{delete draftRoles[name];draft.splice(i,1);renderDraft();}));root.append(row);}
 const c=state?.selected;let reason=!c?.rig.ready?'请先完成当前模型的骨骼绑定。':!readyServer()?'请先重启面板服务。':active()?'当前有任务执行中，完成后再导入。':'导入后逐个检查动画姿态。同名标题可能有不同表演，请核对实际结果。';$('add-animation-reason').textContent=reason;$('import-animation').disabled=blocked()||!c?.rig.ready||!readyServer()||!draft.length;$('import-animation').textContent=`导入动画${draft.length?'（'+draft.length+'）':''}`;}
$('append-animation').onclick=appendDraft;$('animation-name').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();appendDraft();}};$('close-add').onclick=()=>$('add-animation-dialog').close();$('add-animation-form').onsubmit=async e=>{e.preventDefault();if($('animation-name').value.trim())appendDraft();if(!draft.length||!state.selected.rig.ready||!readyServer())return;const ok=await start('download',presetPayload());if(ok)$('add-animation-dialog').close();else renderDraft();};
function openExport(source,files){const c=state?.selected;if(!c)return;const b=c.batches.find(b=>b.id===source)||chosenBatch(c);prefs().exportSource=b?.id||'';prefs().exportFiles=files||b?.files.filter(f=>animationApproved(c,b,f))||[];remember();renderExport();$('export-dialog').showModal();}
$('open-export').onclick=()=>goPage('sheets');$('close-export').onclick=()=>$('export-dialog').close();
function applyCompactResult(){
 const pending=prefs().pendingCompact;if(!pending)return;const job=ownJobs().find(j=>j.id===pending);if(!job||isRunning(job))return;
 delete prefs().pendingCompact;
 if(job.status==='succeeded'&&job.outputs?.delivery){const id=job.outputs.delivery.split('/').at(-1),d=state.selected.deliveries.find(d=>d.id===id);prefs().previewDelivery=id;prefs().frameVariant='game';if(d?.clips.length){libraryOpen=false;selection={type:'sheet',delivery:id,clip:d.clips.find(i=>i.name===selection.clip)?.name||d.clips[0].name};activePage='sheets';prefs().editorSelection=selection;prefs().workspacePage='sheets';}notify('处理完成，已打开新生成的图集记录。');}else notify(job.error||'任务未完成，请查看详情。',true);
 remember();
}
async function refresh(force=false){if(refreshing&&!force)return;const id=++refreshId,requested=selected;refreshing=true;try{let data=await api('/api/state');if(id!==refreshId||requested!==selected)return;if(!data.characters.some(c=>c.id===selected)){selected=data.characters[0]?.id||'';state=null;selection={type:'model'};viewKey='';logTask='';stopPlayback();$('jobs').dataset.signature='';localStorage.setItem('studio-character',selected);}if(selected)data=await api('/api/state?character='+encodeURIComponent(selected));if(id!==refreshId)return;const first=!state;state=data;token=data.token;if(first){selection=prefs().editorSelection||{type:'model'};activePage=pageFor(selection);}applyCompactResult();const picker=$('character-picker');const options=data.characters.map(c=>[c.id,c.display_name||c.id]);if(JSON.stringify(options)!==picker.dataset.options){picker.replaceChildren();for(const [value,label]of options){const option=node('option',label);option.value=value;picker.append(option);}picker.dataset.options=JSON.stringify(options);}picker.value=selected;
 renderCharacterLibrary();$('server-update').hidden=readyServer();$('connection').textContent=active()?'任务执行中 · 本机已连接':'本机已连接';if(data.selected&&!libraryOpen)renderWorkspace(force);else{$('empty').hidden=false;$('workspace').hidden=true;$('open-export').disabled=true;}if($('add-animation-dialog').open)renderDraft();if($('export-dialog').open&&!$('export-dialog').contains(document.activeElement))renderExport();
 }catch(e){$('connection').textContent='连接中断';if(force)notify(e.message,true);}finally{if(id===refreshId)refreshing=false;}}
function openUpload(id=''){$('character-id').value=id;$('character-name').value=id?(state.selected.display_name||id):'';$('upload-preview').hidden=true;$('upload-file').value='';$('upload-submit').disabled=!readyServer();$('upload-submit').textContent=readyServer()?'导入原画':'请先重启面板服务';$('upload-dialog').querySelector('h2').textContent=id?'导入人物原画':'新建人物';$('upload-dialog').showModal();}
$('upload-file').onchange=()=>{if(uploadUrl)URL.revokeObjectURL(uploadUrl);const file=$('upload-file').files[0],root=$('upload-preview');root.replaceChildren();root.hidden=!file;if(file){uploadUrl=URL.createObjectURL(file);const img=node('img');img.src=uploadUrl;img.alt='待导入原画';root.append(img);}};
$('upload-form').onsubmit=async event=>{event.preventDefault();if(!readyServer())return;const file=$('upload-file').files[0];if(!file)return;if(file.size>12*1024*1024){notify('图片不能超过 12 MB。',true);return;}const submit=$('upload-submit');submit.disabled=true;try{const content=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result).split(',')[1]);r.onerror=reject;r.readAsDataURL(file);});const result=await api('/api/upload',{character:$('character-id').value||null,display_name:$('character-name').value,content});$('upload-dialog').close();selected=result.character;state=null;libraryOpen=false;activePage='character';selection={type:'model'};prefs().image=result.image;prefs().editorSelection=selection;remember();localStorage.setItem('studio-character',selected);notify('原画已保存。检查后点击“生成模型与贴图”。');await refresh(true);}catch(e){notify(e.message,true);}finally{submit.disabled=!readyServer();}};
$('character-picker').onchange=e=>switchCharacter(e.target.value);$('new-character').onclick=()=>openUpload();$('empty-create').onclick=()=>openUpload();$('close-upload').onclick=()=>$('upload-dialog').close();$('close-image').onclick=()=>$('image-dialog').close();$('cancel-regenerate').onclick=()=>$('confirm-regenerate').close();$('toggle-tasks').onclick=()=>{const hidden=!$('task-details').hidden;$('task-details').hidden=hidden;$('toggle-tasks').setAttribute('aria-expanded',String(!hidden));if(!hidden)renderTasks();};$('log-box').ontoggle=()=>{if($('log-box').open)refreshLog();};
refresh(true);setInterval(()=>refresh(),2500);

function renderWeapon(){
 const w=(state.weapons||[]).find(w=>w.id===selection.weapon),content=$('preview-content'),controls=$('controls');if(!w){content.append(placeholder('武器资产不可用','刷新后重新选择。'));return;}
 setTitles('WEAPON',w.name,'武器设置');const grip=[...w.grip];let length=w.length_meters;
 const stage=node('div',undefined,'weapon-calibration'),img=node('img');img.src=w.front;img.alt='标准朝向武器，点击握柄设置握点';const marker=node('span','●','weapon-grip');stage.append(img,marker);content.append(stage);
 function markerPosition(){marker.style.left=((150+grip[0]*490)/300*100)+'%';marker.style.top=((550-grip[1]*490)/600*100)+'%';}
 const value=node('div',undefined,'approval-state');function update(){markerPosition();value.textContent=`握点：距底端 ${(grip[1]*100).toFixed(1)}% · 总长 ${length.toFixed(2)}m`;}
 img.onclick=e=>{const rect=img.getBoundingClientRect();grip[0]=Math.max(-.3,Math.min(.3,((e.clientX-rect.left)/rect.width*300-150)/490));grip[1]=Math.max(0,Math.min(1,(550-(e.clientY-rect.top)/rect.height*600)/490));update();};
 const len=node('input');len.type='number';len.min='.1';len.max='2';len.step='.01';len.value=length;len.oninput=()=>{length=Number(len.value);update();};
 const depth=node('input');depth.type='number';depth.min='-.3';depth.max='.3';depth.step='.005';depth.value=grip[2];depth.oninput=()=>{grip[2]=Number(depth.value);};
 controls.append(properties([['剑尖方向','向上（+Y）'],['刃面方向','正面（+Z）'],['三角面',w.triangles],['状态',w.confirmed?'已确认':'待确认']]),field('总长（米）',len),value,note('点击左侧剑柄中心设置红色握点。剑尖朝上、刃面朝前；人物上的朝向可在握持窗口调整。总长是你设定的值，不由图片推断。'),details('握点深度',field('深度（相对总长）',depth),note('0 表示武器中心平面。正值向前，负值向后。')));
 controls.append(button(w.confirmed?'保存为新的武器设置':'确认武器设置',async()=>{if(blocked())return;busy=true;try{const result=await api('/api/weapon/calibrate',{weapon:w.id,length,grip});selection={type:'weapon',weapon:result.id};prefs().editorSelection=selection;prefs().weapon=result.id;remember();notify('武器设置已保存。可将它装备到人物。');await refresh(true);}catch(e){notify(e.message,true);}finally{busy=false;renderWorkspace(true);}},'primary full',blocked()||state.api_version<4));
 if(w.confirmed)controls.append(button('装备到当前人物',()=>{prefs().weapon=w.id;remember();choose({type:'equipment'});},'full',!state.selected.rig.ready));
 content.append(details('八方向模型检查',stageImage(w.contact,'武器八方向检查')));controls.append(link('下载武器 GLB', '/asset/weapons/'+w.id+'/model.glb'));$('viewport-note').textContent='红点表示武器自身的握持原点。保存会创建新版本，不改变已经装备的配置。';update();
}

function openWeaponGenerate(){$('weapon-generate-form').reset();$('weapon-upload-preview').replaceChildren();$('weapon-generate-submit').disabled=blocked()||state.api_version<4;$('weapon-generate-dialog').showModal();}
$('close-weapon-generate').onclick=()=>$('weapon-generate-dialog').close();
let weaponUploadURL;
$('weapon-image').onchange=()=>{if(weaponUploadURL)URL.revokeObjectURL(weaponUploadURL);const file=$('weapon-image').files[0],root=$('weapon-upload-preview');root.replaceChildren();if(file){weaponUploadURL=URL.createObjectURL(file);const img=node('img');img.src=weaponUploadURL;img.alt='武器原画';img.style.maxHeight='220px';img.style.maxWidth='100%';root.append(img);}};
$('weapon-generate-form').onsubmit=async event=>{event.preventDefault();if(blocked()||state.api_version<4)return;const file=$('weapon-image').files[0];if(!file)return;if(file.size>12*1024*1024){notify('图片不能超过12MB。',true);return;}const submit=$('weapon-generate-submit');submit.disabled=true;try{const content=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file);});const upload=await api('/api/weapon/upload',{name:$('weapon-name').value,content});const ok=await start('weapon',upload);if(ok)$('weapon-generate-dialog').close();}catch(e){notify(e.message,true);}finally{submit.disabled=blocked();}};

const usageLabels={hand:'手持',back:'背部',waist:'腰间',hidden:'隐藏',inherit:'继承人物默认'};
function stateSelect(value,change,inherit=false){return select((inherit?['inherit',...Object.keys(usageLabels).filter(k=>k!=='inherit')]:Object.keys(usageLabels).filter(k=>k!=='inherit')).map(k=>[k,usageLabels[k]]),value,change);}
function usageEditor(c,e,animation){
 const box=node('div',undefined,'usage-editor');if(!e.usage){box.append(note('持用配置不可用，请检查装备来源。'));return box;}
 const sha=animation?.batch.hashes?.[animation.file];
 const draftKey=e.id+'/'+(sha||'default'),baseline=JSON.stringify(e.usage),drafts=prefs().usageDrafts||(prefs().usageDrafts={});
 const saved=drafts[draftKey]?.baseline===baseline?drafts[draftKey]:null;
 const data=JSON.parse(JSON.stringify(saved?.data||e.usage));const action=JSON.parse(JSON.stringify(saved?.action||data.actions[sha]||{initial:'inherit',events:[]}));
 const status=node('p',saved?'有未保存的修改，已保留草稿。':'持用设置已保存。','hint');
 const capture=()=>{drafts[draftKey]={baseline,data,action};remember();status.textContent='有未保存的修改，已保留草稿。';};
 box.addEventListener('input',capture);box.addEventListener('change',capture);
 box.append(status,button('放弃未保存修改',()=>{delete drafts[draftKey];remember();renderWorkspace(true);},'full'));
 box.append(node('h3',animation?'此动作的武器状态':'武器持用默认设置'));
 if(animation){
  box.append(field('使用装备',select(equipmentFor(c,animation.batch).map(item=>[item.id,item.weapon_name||'标准单手剑']),e.id,v=>{prefs().equipment=v;remember();renderWorkspace(true);})),field('动作开始时',stateSelect(action.initial,v=>{action.initial=v;},true)),note(`人物默认：${usageLabels[data.default]}。保存设置后重新渲染才能看到变化，已有图集保留原效果。`));
  const events=node('div');function drawEvents(){events.replaceChildren();for(const [i,event]of action.events.entries()){const row=node('div',undefined,'usage-event');const input=node('input');input.type='number';input.min='1';input.max='99';input.step='1';input.value=Math.round(event.at*100);input.setAttribute('aria-label',`切换 ${i+1} 的动作百分比`);input.oninput=()=>{event.at=Number(input.value)/100;};row.append(input,node('span','% 时'),stateSelect(event.state,v=>{event.state=v;}),button('移除',()=>{action.events.splice(i,1);capture();drawEvents();}));events.append(row);}}
  drawEvents();box.append(events,button('＋ 添加切换',()=>{if(action.events.length>=16)return;action.events.push({at:action.events.length?Math.min(.99,action.events.at(-1).at+.1):.5,state:'hand'});capture();drawEvents();},'full',blocked()),note('切换发生在动作时长的指定百分比。需要原动画提供取剑或收剑姿态；切换挂点不会自动生成这些动作。'));
 }else{
  box.append(field('默认武器状态',stateSelect(data.default,v=>{data.default=v;})),note('未单独设置的动作继承此状态。背部和腰间挂点各设置一次，位置为相对对应骨骼的米数。'));
  for(const [key,title]of [['back','背部收纳挂点'],['waist','腰间收纳挂点']]){
   const mount=data.mounts[key],fields=[];
   for(const [property,label,step]of [['position','位置（米）','.01'],['rotation','旋转（度）','1']]){
    const row=node('div',undefined,'mount-vector');for(const [i,axis]of ['X','Y','Z'].entries()){const input=node('input');input.type='number';input.step=step;input.min=property==='position'? '-.6':'-180';input.max=property==='position'?'.6':'180';input.value=mount[property][i];input.oninput=()=>{mount[property][i]=Number(input.value);};row.append(field(axis,input));}fields.push(node('p',label,'hint'),row);
   }
   box.append(details(title,note(key==='back'?'跟随胸部 Spine2；默认位置和角度仅为起点，请渲染检查穿插。':'跟随骨盆 Hips；默认位置和角度仅为起点，请渲染检查穿插。'),...fields));
  }
 }
 box.append(button('保存持用设置',async()=>{action.events.sort((a,b)=>a.at-b.at);const ok=await mutation('/api/equipment/usage',{character:selected,equipment:e.id,default:data.default,mounts:data.mounts,...(animation?{batch:animation.batch.id,file:animation.file,action}:{})},'持用设置已保存。重新渲染后可查看新效果。');if(ok){delete drafts[draftKey];remember();renderWorkspace(true);}},'primary full',blocked()||state.api_version<7));return box;
}

function renderQuality(c){
 setTitles('QUALITY','批量质量检查','筛选');const controls=$('controls'),content=$('preview-content');
 const reports=[...ownJobs().filter(j=>j.status==='failed'&&j.quality_report).map(j=>({id:j.id,batch:j.params.batch,renderer:j.params.renderer,clips:[],quality_report:{...j.quality_report,summary:j.quality_report.summary||{passed:0,review:0,failed:j.quality_report.results.length}},task:j})),...c.deliveries.filter(d=>d.quality_report)];if(!reports.length){content.append(placeholder('尚无批量质检记录','新生成的图集将自动检查，并汇总通过、需复核及失败动作。历史图集仍可查看。'));return;}
 const delivery=reports.find(d=>d.id===prefs().qualityDelivery)||reports[0],report=delivery.quality_report;
 controls.append(field('质检记录',select(reports.map(d=>[d.id,`${sourceTime(d.id)} · ${rendererName(d.renderer)}`]),delivery.id,v=>{prefs().qualityDelivery=v;remember();renderWorkspace(true);})),note('“通过”表示自动检查未发现已知异常，仍需美术验收。循环首尾差异单独标记，仅在需要循环时检查。'),delivery.manifest?link('下载质检清单',delivery.manifest):button('查看失败日志',()=>{logTask=delivery.id;openTasks();$('log-box').open=true;refreshLog();}));
 const showAll=prefs().qualityAll===true;controls.append(button(showAll?'仅看异常':'显示全部动作',()=>{prefs().qualityAll=!showAll;remember();renderWorkspace(true);},'full'));
 const labels={passed:'通过',review:'需复核',failed:'失败'};content.append(properties(Object.entries(report.summary).map(([k,n])=>[labels[k],n])));
 const visible=report.results.filter(r=>showAll||r.status!=='passed'||r.loop?.status==='review');
 if(!visible.length)content.append(note('此次自动检查未发现异常。'));
 for(const r of visible){const card=node('section',undefined,'quality-card '+r.status);const batch=c.batches.find(b=>b.id===delivery.batch);card.append(node('h3',`${batch?animationTitle(batch,r.name+'.fbx'):r.name} · ${labels[r.status]}`));
 if(r.reason)card.append(node('p',r.reason));for(const w of r.warnings||[])card.append(node('p',w.message+(w.frames?.length?'（帧 '+w.frames.slice(0,10).join(', ')+(w.frames.length>10?'…':'')+'）':'')));
 if(r.game_frame_count)card.append(note(`游戏精简版：${r.frame_count} → ${r.game_frame_count} 帧，时长不变`));if(r.loop?.status==='review')card.append(note('循环复核：'+r.loop.message));if(r.frame_count)card.append(note(`${Number(r.duration_seconds).toFixed(2)} 秒 · ${r.frame_count} 帧 · ${Number(r.fps).toFixed(2)} FPS${r.source_fps?' · 源关键帧约 '+Number(r.source_fps).toFixed(2)+' FPS':''}`));
 const clip=delivery.clips.find(i=>i.name===r.name);if(clip)card.append(button('查看动画',()=>{prefs().previewDelivery=delivery.id;prefs().animationView='sprite';if(delivery.kind==='sequence')choose({type:'sequence'});else choose({type:'sheet',delivery:delivery.id,clip:r.name});},''));else card.append(note('失败图集已隔离，未加入交付文件。请检查原因后重新生成。'));content.append(card);}
 $('viewport-note').textContent='异常来自自动规则，快速攻击、蹲伏、武器显隐也可能触发需复核提示。不会自动修改原动作。';
}

function renderModelOptimization(c,controls){
 const box=node('div',undefined,'usage-editor');box.append(node('h3','模型优化 · Blender'),note('保留原版，比较约 3 万面与 1.5 万面候选。只检查静态画面，不保证关节变形；采用后需重新验收与绑定。'));
 box.append(button('生成减面对照',()=>start('optimize',{fingerprint:c.prepared.fingerprint}),'full',blocked()||state.api_version<15));
 const experiment=c.optimizations?.[0];if(experiment){
  box.append(image(experiment.comparison,'原版与减面候选四视图对比'),note('从上到下：'+experiment.report.variants.map(v=>v.id==='original'?'原版':v.triangles.toLocaleString()+' 面').join('、')+'。候选仍待外观及新绑定动作验收。'));for(const size of [64,128])if(experiment.pixel_comparisons?.[size])box.append(button('查看 '+size+'px 对照',()=>{$('large-preview').src=experiment.pixel_comparisons[size];$('large-preview').alt=size+'px 减面对照';$('image-dialog').showModal();},'full'));box.append(link('下载优化评估清单',experiment.report_url));
  for(const variant of experiment.variants){const active=c.prepared.info.optimization?.experiment===experiment.id&&String(c.prepared.info.optimization?.target)===variant.id;
   const metric=experiment.report.variants.find(v=>v.id===variant.id)?.metrics?.['64'];if(metric)box.append(note('64px 四视图最低轮廓重合度：'+(metric.minimum_silhouette_iou*100).toFixed(2)+'%'));box.append(node('strong',variant.triangles.toLocaleString()+' 三角面'),link('下载候选 GLB',variant.glb),button(active?'当前使用此版本':'采用此版本（需重新绑定）',()=>start('adopt_model',{experiment:experiment.id,variant:variant.id}),'full',blocked()||active||state.api_version<15));
  }
 }
 controls.append(box);
}

$('import-model').onclick=()=>{$('model-dialog').showModal();};
$('close-model').onclick=()=>$('model-dialog').close();
$('model-form').onsubmit=async event=>{
 event.preventDefault();if(blocked()||!readyServer())return;
 const file=$('model-file').files[0];if(!file)return;if(file.size>100*1024*1024){notify('GLB 不能超过100MB',true);return;}
 const submit=$('model-submit');submit.disabled=true;submit.textContent='正在上传模型…';
 try{
  const content=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file);});
  const result=await api('/api/model/upload',{display_name:$('model-name').value,content,up:$('model-up').value,yaw:Number($('model-yaw').value)});
  selected=result.character;state=null;selection={type:'model'};libraryOpen=false;prefs().editorSelection=selection;remember();localStorage.setItem('studio-character',selected);await refresh(true);
  if(await start('import_model',{source:result.source,up:result.up,yaw:result.yaw}))$('model-dialog').close();
 }catch(e){notify(e.message,true);}finally{submit.disabled=false;submit.textContent='导入并准备模型';}
};

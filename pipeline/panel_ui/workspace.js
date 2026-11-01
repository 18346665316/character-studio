'use strict';
// Task-oriented presentation. Rendering, validation and durable jobs stay in the pipeline.
let libraryOpen=true,activePage='character';
const pageLabels={character:'人物',actions:'动作',equipment:'装备',sheets:'图集',sequence:'编排'};
const pageDescriptions={character:'确认人物外观与骨骼，建立可复用的角色。',actions:'管理 Mixamo 原动作，检查姿态与变形。',equipment:'管理武器模型，设置人物握持与动作中的持用状态。',sheets:'生成、检查、精简和下载游戏图集。',sequence:'组织原动作，生成统一取景的连续预览。'};
function pageFor(value){return ({model:'character',rig:'character',animation:'actions',equipment:'equipment',weapon:'equipment',sheet:'sheets',quality:'sheets',sequence:'sequence',actions:'actions',sheets:'sheets',weapons:'equipment'})[value.type]||'character';}
function goPage(page){
 const types={character:'model',actions:'actions',equipment:'equipment',sheets:'sheets',sequence:'sequence'};
 choose({type:types[page]});
}
function showLibrary(){libraryOpen=true;stopPlayback();$('workspace').hidden=true;$('empty').hidden=false;renderCharacterLibrary();}
function renderCharacterLibrary(){
 const root=$('character-library');if(!root||!state)return;const signature=JSON.stringify([state.characters,state.selected?.prepared?.contact]);if(root.dataset.signature===signature)return;root.dataset.signature=signature;root.replaceChildren();
 for(const c of state.characters){const card=node('button',undefined,'character-card');card.type='button';card.setAttribute('aria-label','打开人物 '+c.display_name);const art=node('div',undefined,'character-art');
 if(state.selected?.id===c.id&&state.selected.prepared?.contact){const img=node('img');img.src=state.selected.prepared.contact;img.alt=c.display_name+'模型预览';art.append(img);}else art.append(node('span',c.display_name.slice(0,1),'character-initial'));
 const copy=node('div',undefined,'character-copy');copy.append(node('h2',c.display_name),node('p','人物 · 动作 · 装备 · 图集','muted'),node('span','进入工作区 →','card-link'));card.append(art,copy);card.onclick=()=>switchCharacter(c.id);root.append(card);}
 if(!state.characters.length)root.append(placeholder('创建你的第一个人物','上传完整人物原画，开始制作。'));
}
function contextNext(c){
 const running=ownJobs().find(isRunning);if(running)return {label:'查看当前任务',text:c.progress?.message||actionNames[running.action],run:()=>{openTasks();renderTasks();}};
 if(!c.prepared)return {label:'准备人物',text:'先导入原画并生成模型。',run:()=>goPage('character')};
 if(!c.model_approved)return {label:'确认模型外观',text:'检查轮廓、四肢和背面后继续绑定。',run:()=>choose({type:'model'})};
 if(!c.rig.ready)return {label:'完成骨骼绑定',text:c.rig.error||'在 Mixamo 完成摆点与变形验收。',run:()=>choose({type:'rig'})};
 const pending=animationResources(c).find(a=>a.batch.current_rig&&!animationApproved(c,a.batch,a.file));
 if(pending)return {label:'检查待确认动作',text:animationTitle(pending.batch,pending.file)+' 等待姿态验收。',run:()=>choose({type:'animation',key:pending.key,version:pending.id})};
 if(!c.batches.some(b=>b.current_rig))return {label:'添加第一个动作',text:'从 Mixamo 查找表演，填写原始英文标题。',run:openAdd};
 if(!c.deliveries.length)return {label:'生成游戏图集',text:'动作已确认，选择视角、尺寸与装备。',run:()=>openExport()};
 return {label:'查看图集结果',text:'已有结果可预览、精简或直接下载。',run:()=>goPage('sheets')};
}
function renderSetup(c){
 $('setup-bar')?.remove();
 const nav=$('workspace-nav');nav.replaceChildren();for(const [i,[page,title]]of Object.entries(pageLabels).entries()){const b=button('',()=>goPage(page),'page-nav'+(activePage===page?' selected':''));b.setAttribute('aria-current',activePage===page?'page':'false');b.append(node('span',String(i+1).padStart(2,'0'),'nav-number'),node('span',title));nav.append(b);}
 $('home-link').onclick=showLibrary;$('back-library').onclick=showLibrary;
}
function detail(){ $('detail-layout').hidden=false; }
function tab(label,onClick,selectedTab){const b=button(label,onClick,selectedTab?'selected':'');$('page-tabs').append(b);}
function sectionHeading(title,description,...actions){const row=node('div',undefined,'section-heading'),copy=node('div');copy.append(node('h2',title));if(description)copy.append(node('p',description,'muted'));row.append(copy);const tools=node('div',undefined,'toolbar-actions');tools.append(...actions);row.append(tools);return row;}
function tag(text,tone=''){return node('span',text,'status-tag '+tone);}
function renderWorkspace(force=false){
 if(!state?.selected||libraryOpen)return;const c=state.selected;activePage=pageFor(selection);$('empty').hidden=true;$('workspace').hidden=false;$('character-title').textContent=c.display_name;$('open-export').disabled=false;
 const {progress,...assets}=c;const signature=JSON.stringify([assets,state.jobs.map(j=>[j.id,j.status,j.attempts]),state.weapons,selection,busy]);
 renderSetup(c);renderTasks();if(!force&&viewKey===signature)return;
 // Keep focused form controls intact during background polling.
 if(!force&&$('controls').contains(document.activeElement)&&['INPUT','SELECT'].includes(document.activeElement?.tagName))return;
 viewKey=signature;stopPlayback();$('page-library').replaceChildren();$('page-tabs').replaceChildren();$('preview-content').replaceChildren();$('controls').replaceChildren();$('preview-meta').textContent='';$('viewport-note').textContent='';$('detail-layout').hidden=true;
 if(activePage==='character'){detail();tab('模型与外观',()=>choose({type:'model'}),selection.type!=='rig');tab('骨骼绑定',()=>choose({type:'rig'}),selection.type==='rig');if(selection.type==='rig')renderRig(c);else renderModel(c);}
 else if(activePage==='actions'){if(selection.type==='animation'){detail();tab('← 动作库',()=>goPage('actions'),false);renderAnimation(c);}else renderActionLibrary(c);}
 else if(activePage==='equipment')renderEquipmentWorkspace(c);
 else if(activePage==='sheets'){tab('全部图集',()=>goPage('sheets'),selection.type==='sheets');tab('质量与异常',()=>choose({type:'quality'}),selection.type==='quality');if(selection.type==='quality'){detail();renderQuality(c);}else if(selection.type==='sheet'){detail();renderSheet(c);}else renderSheetLibrary(c);}
 else{detail();renderSequence(c);}
}
function renderActionLibrary(c){
 const root=$('page-library'),rows=animationResources(c),query=prefs().actionQuery||'';
 root.append(sectionHeading('动作库',`${rows.length} 个动作 · 原动作与生成的图集分别管理。`,button('＋ 添加 Mixamo 动作',openAdd,'primary',blocked()||!c.rig.ready)));
 const search=node('input');search.type='search';search.placeholder='搜索动作标题';search.value=query;search.setAttribute('aria-label','搜索动作');const grid=node('div',undefined,'asset-grid');
 const paint=()=>{grid.replaceChildren();for(const a of rows.filter(a=>animationTitle(a.batch,a.file).toLowerCase().includes(search.value.toLowerCase()))){const card=node('article',undefined,'asset-card'),approved=animationApproved(c,a.batch,a.file),review=reviewFor(c,a.batch),pose=review?.images.find(i=>i.name.startsWith(a.key+'_'));const art=node('button',undefined,'asset-art');art.type='button';art.setAttribute('aria-label','检查动作 '+animationTitle(a.batch,a.file));if(pose){const img=node('img');img.src=pose.url;img.alt=animationTitle(a.batch,a.file)+'姿态检查';img.loading='lazy';art.append(img);}else art.append(node('span','▷','asset-symbol'));art.onclick=()=>choose({type:'animation',key:a.key,version:a.id});
 const body=node('div',undefined,'asset-copy');body.append(tag(!a.batch.current_rig?'历史绑定':approved?'已确认':'待检查',approved?'good':'warning'),node('h3',animationTitle(a.batch,a.file)),node('p',`来源 ${sourceTime(a.batch.id)}${a.versions.length>1?' · '+a.versions.length+' 个来源版本':''}`,'muted'));const actions=node('div',undefined,'card-actions');actions.append(button('检查动作',art.onclick),button('生成图集',()=>openExport(a.batch.id,[a.file]),'primary',blocked()||!a.batch.current_rig||!approved));body.append(actions);card.append(art,body);grid.append(card);}if(!grid.childElementCount)grid.append(placeholder('没有匹配的动作','尝试其他标题，或添加 Mixamo 原动作。'));};
 search.oninput=()=>{prefs().actionQuery=search.value;remember();paint();};root.append(search,grid);paint();
 if(!rows.length)root.append(note('先完成人物绑定，再到 Mixamo 选择表演并填写完整英文标题。'));
 const batches=c.batches.filter(b=>b.current_rig);if(batches.length)root.append(sectionHeading('批量生成','在生成配置中勾选同次导入的动作，共享镜头与人物比例。',button('选择多个动作生成',()=>openExport(batches[0].id),'full',blocked())));
}
function renderAnimation(c){
 const a=chosenAnimation(c);if(!a){goPage('actions');return;}const b=a.batch,controls=$('controls'),content=$('preview-content'),review=reviewFor(c,b),approved=animationApproved(c,b,a.file);
 setTitles('SOURCE ANIMATION',animationTitle(b,a.file),'原动作检查');controls.append(tag(b.current_rig?'当前绑定':'历史绑定',b.current_rig?'good':'warning'),field('原动作来源',select(animationResources(c).find(r=>r.key===a.key).versions.map(v=>[v.id,sourceTime(v.batch.id)+' · '+(v.batch.current_rig?'当前绑定':'历史绑定')]),a.id,v=>choose({type:'animation',key:a.key,version:v}))));
 const heading=b.headings?.[a.file];controls.append(node('h3','朝向校准'),note(heading?.status==='confirmed'?`${Number(heading.degrees).toFixed(1)}° · 已确认。修改后需重新生成图集。`:'保留原动作朝向（0°）。自动估计仅供参考，预览确认后才应用。'),button('预览与校准朝向',()=>start('review',{batch:b.id,heading_file:a.file}),'full',blocked()||!b.current_rig),note('在人物检查窗口中试用参考角度或手动调整，确认保存后关闭窗口。'));
 if(review)renderPoses(review,a.key);else content.append(placeholder('检查动作姿态','生成肩肘、髋膝与衣服变形的检查画面，再确认原动作。'));
 controls.append(note('此处验收原动作。连续图集播放、精简和下载位于「图集」。'),button(review?'重新生成检查画面':'生成姿态检查',()=>start('review',{batch:b.id}),'full',blocked()||!b.current_rig),button(approved?'✓ 此动作已确认':'确认此动作',()=>mutation('/api/approve',{character:selected,kind:'animation',batch:b.id,file:a.file,fingerprint:b.fingerprint},'原动作已确认，可以生成游戏图集。'),'primary full',blocked()||!review||approved||!b.current_rig),button('为此动作生成图集',()=>openExport(b.id,[a.file]),'full',blocked()||!approved||!b.current_rig));
 const outputs=c.deliveries.filter(d=>d.kind!=='sequence'&&d.batch===b.id&&d.clips.some(i=>i.name===a.key));if(outputs.length)controls.append(button(`查看已有图集（${outputs.length}）`,()=>choose({type:'sheet',delivery:outputs[0].id,clip:a.key}),'full'));
 const equipped=selectedEquipment(c,b);if(equipped)controls.append(usageEditor(c,equipped,a));else controls.append(button('前往配置人物装备',()=>{prefs().source=b.id;goPage('equipment');},'full'));
 $('viewport-note').textContent=`原动作 ${animationTitle(b,a.file)} · 来源 ${sourceTime(b.id)} · ${approved?'人工已确认':'等待人工确认'}。检查画面来自原动作，不是实时图集预览。`;
}
function renderEquipmentWorkspace(c){
 tab('人物装备',()=>goPage('equipment'),selection.type==='equipment');tab('武器库',()=>choose({type:'weapons'}),['weapon','weapons'].includes(selection.type));
 if(selection.type==='weapon'){detail();renderWeapon();return;}
 if(selection.type==='weapons'){
 const root=$('page-library');root.append(sectionHeading('武器库','独立武器可以复用于不同人物；人物握持关系单独保存。',button('＋ 从原画生成武器',openWeaponGenerate,'primary',blocked())));const grid=node('div',undefined,'asset-grid');
 const parents=new Set((state.weapons||[]).map(w=>w.parent).filter(Boolean));for(const w of (state.weapons||[]).filter(w=>!parents.has(w.id))){const card=node('article',undefined,'asset-card'),art=node('div',undefined,'asset-art weapon-art'),img=node('img');img.src=w.front;img.alt=w.name;img.loading='lazy';art.append(img);const copy=node('div',undefined,'asset-copy');copy.append(tag(w.confirmed?'已确认':'待设置',w.confirmed?'good':'warning'),node('h3',w.name),button('尺寸与握点',()=>choose({type:'weapon',weapon:w.id}),'full'));card.append(art,copy);grid.append(card);}root.append(grid);if(!grid.childElementCount)root.append(placeholder('还没有独立武器','也可以在人物装备中使用内置标准剑。'));return;}
 const root=$('page-library');root.append(sectionHeading('人物装备','握持配置绑定当前人物的骨骼版本，新动作可直接复用。',button('＋ 配置新装备',()=>choose({type:'equipment',create:true}),'primary',blocked())));
 const strip=node('div',undefined,'equipment-strip');for(const e of c.equipment)strip.append(button((e.weapon_name||'标准单手剑')+' · '+(e.bone.includes('Right')?'右手':'左手'),()=>choose({type:'equipment',equipment:e.id}),selection.equipment===e.id?'selected':''));root.append(strip);
 if(!selection.equipment&&!selection.create&&c.equipment.length)selection.equipment=c.equipment[0].id;
 detail();renderEquipment(c);
}
function deliveryTitle(d){return `${d.operation?.type==='compact'?'精简结果':'渲染结果'} · ${rendererName(d.renderer)} · ${sourceTime(d.id)}`;}
function sheetGroups(c){
 const groups=new Map();
 for(const delivery of c.deliveries.filter(d=>d.kind!=='sequence'))for(const item of delivery.clips){
  if(!groups.has(item.name))groups.set(item.name,{key:item.name,title:animationTitle(c.batches.find(b=>b.id===delivery.batch)||{},item.name+'.fbx'),versions:[]});
  groups.get(item.name).versions.push({delivery,item});
 }
 return [...groups.values()].sort((a,b)=>a.title.localeCompare(b.title,'en',{numeric:true,sensitivity:'base'}));
}
function sheetVersionRow(delivery,item,latest=false){
 const row=node('button',undefined,'sheet-row');row.type='button';const img=node('img');img.src=item.game?.gif||item.gif;img.alt='';img.loading='lazy';
 const copy=node('span',undefined,'sheet-row-copy');copy.append(node('strong',`${latest?'最新版本 · ':''}${rendererName(delivery.renderer)} · ${item.info.body_height_px?'人物 '+item.info.body_height_px+'px':'画布 '+(delivery.settings.frame_size||item.info.frame_width||'?')+'px'} · ${viewName(item.info.view)} · ${delivery.equipment?.config?.weapon_name||(delivery.equipment?'标准单手剑':'空手')}`),node('small',`${Number(item.info.duration_seconds).toFixed(2)} 秒 · ${item.info.frame_count} 帧${item.game?' → 精简 '+item.game.info.frame_count+' 帧':''} · ${deliveryTitle(delivery)}`));
 const status=item.info.quality?.status;row.append(img,copy,tag(status==='review'?'需复核':status==='failed'?'检查失败':status==='passed'?'检查通过':'历史结果',['review','failed'].includes(status)?'warning':''),node('span','预览 →','card-link'));
 row.onclick=()=>choose({type:'sheet',delivery:delivery.id,clip:item.name});return row;
}
function renderSheetLibrary(c){
 const root=$('page-library'),groups=sheetGroups(c);
 root.append(sectionHeading('动作图集',`${groups.length} 个动作 · 同一动作的渲染与精简版本集中查看。`,button('生成新图集',()=>openExport(),'primary',blocked()||!c.batches.some(b=>b.current_rig))));
 if(!groups.length){root.append(placeholder('还没有游戏图集','先在动作页检查并确认原动作，然后生成。'));return;}
 for(const group of groups){const record=node('section',undefined,'delivery-record');record.append(sectionHeading(group.title,`${group.versions.length} 个版本`));
  const [latest,...history]=group.versions;record.append(sheetVersionRow(latest.delivery,latest.item,true));
  if(history.length)record.append(details(`其他版本（${history.length}）`,...history.map(v=>sheetVersionRow(v.delivery,v.item))));
  root.append(record);
 }
}
function viewName(view){return ({front:'正面',side:'侧面',three_quarter:'四分之三'})[view]||view||'未记录视角';}
function renderSheet(c){
 const d=c.deliveries.find(d=>d.id===selection.delivery),item=d?.clips.find(i=>i.name===selection.clip);if(!item){goPage('sheets');return;}
 const controls=$('controls'),content=$('preview-content'),title=animationTitle(c.batches.find(b=>b.id===d.batch)||{},item.name+'.fbx');setTitles('RENDERED ASSET',title,'结果与下载');
 const toolbar=node('div',undefined,'tabs');toolbar.append(button('← 返回图集记录',()=>goPage('sheets')));if(item.game)for(const [value,label]of [['game','游戏精简版'],['source','完整采样版']])toolbar.append(button(label,()=>{prefs().frameVariant=value;remember();renderWorkspace(true);},(prefs().frameVariant||'game')===value?'selected':''));content.append(toolbar);
 const chosen=item.game&&prefs().frameVariant!=='source'?gameItem(item):item;mountPlayer(chosen);
 if(item.info.body_height_px)controls.append(field('预览倍率',select([[1,'1× 实际像素'],[2,'2×'],[3,'3×']],prefs().spriteZoom||1,v=>{prefs().spriteZoom=Number(v);remember();renderWorkspace(true);})));
 controls.append(note('正在预览固定的生成结果。装备和原动作上的后续编辑不会改变这份图集。'),properties([['记录',deliveryTitle(d)],['装备',d.equipment?.config?.weapon_name||(d.equipment?'标准单手剑':'空手')],['视角',viewName(item.info.view)],['时长',Number(item.info.duration_seconds).toFixed(2)+' 秒'],['帧数',item.info.frame_count+(item.game?' → '+item.game.info.frame_count:'')]]));
 const siblings=c.deliveries.filter(x=>x.kind!=='sequence'&&x.clips.some(i=>i.name===item.name));controls.append(field('此动作的图集版本',select(siblings.map(x=>[x.id,deliveryTitle(x)]),d.id,id=>choose({type:'sheet',delivery:id,clip:item.name}))));
 if(item.info.body_height_px)controls.append(properties([['标准站姿高度',item.info.body_height_px+'px'],['自动画布',item.info.frame_width+' × '+item.info.frame_height],['脚底锚点',item.info.anchor_px?.map(v=>Number(v).toFixed(1)).join(', ')]]));
 controls.append(properties([['朝向补偿',Number(item.info.heading?.degrees||0).toFixed(1)+'°']]));if(d.heading_stale)controls.append(note('动作朝向已更新；这份历史图集保留旧角度，请重新生成以应用校准。'));
 const quality=item.info.quality;if(quality){controls.append(tag(quality.status==='review'?'自动检查：需复核':'自动检查：通过',quality.status==='review'?'warning':'good'));for(const w of quality.warnings||[])controls.append(note(w.message));if(quality.loop?.status==='review')controls.append(note('循环复核：'+quality.loop.message));}
 controls.append(node('h3','下载'),link('下载此记录完整包（ZIP）',d.export),link('完整采样 PNG',item.sheet),link('完整采样 GIF',item.gif));if(item.game)controls.append(link('游戏精简 PNG',item.game.sheet),link('游戏精简 GIF',item.game.gif),link('Godot SpriteFrames（随 PNG 使用）',item.game.spriteframes));controls.append(link('时序与质量清单',d.manifest));
 controls.append(node('h3','精简已有图集'),note('从完整图集减少冗余帧，保持时长。无需重新渲染，结果保存为新记录。'),button(item.game?'重新生成此动作精简版':'生成此动作精简版',()=>{selection.clip=item.name;prefs().frameVariant='game';remember();start('compact',{delivery:d.id,clips:[item.name]});},'primary full',blocked()||!readyServer()));if(d.clips.length>1)controls.append(button(`精简此记录全部 ${d.clips.length} 个动作`,()=>start('compact',{delivery:d.id,clips:d.clips.map(i=>i.name)}),'full',blocked()||!readyServer()));
 $('viewport-note').textContent=`${chosen===item?'完整采样版':'游戏精简版 · 按逐帧时长播放'} · ${chosen.info.frame_count} 帧 · ${Number(chosen.info.duration_seconds).toFixed(2)} 秒 · ${chosen.info.frame_width}px · ${d.equipment?usageSummary(d.equipment.usage,item.name):'空手'}。`;
}
function renderExport(){
 const c=state.selected,p=prefs(),root=$('export-controls');root.replaceChildren();const sources=c.batches.filter(b=>b.current_rig);let b=sources.find(b=>b.id===p.exportSource)||sources[0];
 if(!b){root.append(placeholder('先准备可用动作','在动作页导入并检查当前绑定的动作。'),button('前往动作',()=>{$('export-dialog').close();goPage('actions');}));return;}
 root.append(note('选择原动作，生成共享取景与比例的图集。已有结果请在「图集」页面直接下载。'),field('原动作来源',select(sources.map(b=>[b.id,sourceTime(b.id)+' · '+b.files.map(f=>animationTitle(b,f)).join(', ')]),b.id,id=>{p.exportSource=id;const batch=sources.find(b=>b.id===id);p.exportFiles=batch.files.filter(f=>animationApproved(c,batch,f));remember();renderExport();})));
 let chosen=(p.exportFiles||[]).filter(f=>b.files.includes(f));p.exportSource=b.id;p.exportFiles=chosen;
 const list=node('div',undefined,'render-checklist');list.setAttribute('aria-label','本次生成的动作');let submit;
 for(const file of b.files){const label=node('label',undefined,'check-row'),input=node('input');input.type='checkbox';input.checked=chosen.includes(file);input.disabled=!animationApproved(c,b,file);input.setAttribute('aria-label','生成 '+animationTitle(b,file));input.onchange=()=>{chosen=b.files.filter(f=>f===file?input.checked:chosen.includes(f));p.exportFiles=chosen;remember();submit.textContent=`生成 ${chosen.length} 个动作的图集`;submit.disabled=blocked()||!readyServer()||!chosen.length;};label.append(input,node('span',animationTitle(b,file)),tag(input.disabled?'需先确认':'已确认',input.disabled?'warning':'good'));list.append(label);}root.append(list,note('本次只处理勾选动作。同次导入的动作可一起生成；跨来源的统一取景请使用编排。'));
 root.append(field('渲染器',select([['godot','Godot'],['blender','Blender · Eevee']],p.renderer||'godot',v=>{p.renderer=v;remember();})),field('视角',select([['three_quarter','四分之三'],['front','正面'],['side','侧面']],p.view||'three_quarter',v=>{p.view=v;remember();})),field('人物像素高度',select([[48,'48px'],[64,'64px'],[96,'96px（推荐）'],[128,'128px']],p.body_height||96,v=>{p.body_height=Number(v);remember();})));
 const equipment=equipmentFor(c,b),value=equipment.some(e=>e.id===p.equipment)?p.equipment:'';p.equipment=value;root.append(field('人物装备',select([['','空手'],...equipment.map(e=>[e.id,e.weapon_name||'标准单手剑'])],value,v=>{p.equipment=v;remember();})),details('高级渲染参数',field('超采样',select([[4,'4 倍'],[2,'2 倍'],[1,'关闭']],p.supersample||4,v=>{p.supersample=Number(v);remember();}))));
 root.append(note('以标准站姿高度确定像素密度，自动扩大画布容纳动作与武器，人物不会因此缩小。保留贴图细节，不自动减色或描边。'));
 root.append(note('输出完整采样版、游戏精简版、GIF、时序与质检清单。完成后自动打开结果。'));
 submit=button(`生成 ${chosen.length} 个动作的图集`,async()=>{const ok=await start('bake',{batch:b.id,files:chosen,renderer:p.renderer||'godot',view:p.view||'three_quarter',body_height:p.body_height||96,supersample:p.supersample||4,equipment_id:p.equipment||null});if(ok)$('export-dialog').close();},'primary full',blocked()||!readyServer()||!chosen.length);root.append(submit);
}

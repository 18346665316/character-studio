'use strict';
// Task-oriented presentation. Rendering, validation and durable jobs stay in the pipeline.
let libraryOpen=true,activePage='character';
const pageLabels={character:'人物',actions:'动作',equipment:'装备',sheets:'交付',sequence:'编排'};
const pageDescriptions={character:'确认人物外观与骨骼，建立可复用的角色。',actions:'管理 Mixamo 原动作，检查姿态与变形。',equipment:'管理武器模型，设置人物握持与动作中的持用状态。',sheets:'生成、检查、精简和下载游戏图集。',sequence:'组织原动作，生成统一取景的连续预览。'};
function pageFor(value){return ({model:'character',rig:'character',animation:'actions',equipment:'equipment',weapon:'equipment',sheet:'sheets',quality:'sheets',sequence:'sequence',actions:'actions',sheets:'sheets',action_set_advanced:'sheets',weapons:'equipment'})[value.type]||'character';}
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
 const {progress,...assets}=c;const signature=JSON.stringify([assets,state.jobs.map(j=>[j.id,j.status,j.attempts,j.action==='produce'?[j.outputs?.production?.stage,j.outputs?.production?.roles]:null]),state.weapons,selection,busy]);
 renderSetup(c);renderTasks();const liveProgress=$('production-live-progress');if(liveProgress)liveProgress.textContent=progress?.message||'正在启动整套生产任务…';if(!force&&viewKey===signature)return;
 // Keep focused form controls intact during background polling.
 if(!force&&$('controls').contains(document.activeElement)&&['INPUT','SELECT'].includes(document.activeElement?.tagName))return;
 viewKey=signature;stopPlayback();$('delivery-action-list')?.remove();$('detail-layout').classList.remove('delivery-layout');$('page-library').replaceChildren();$('page-tabs').replaceChildren();$('preview-content').replaceChildren();$('controls').replaceChildren();$('preview-meta').textContent='';$('viewport-note').textContent='';$('detail-layout').hidden=true;
 if(activePage==='character'){detail();tab('模型与外观',()=>choose({type:'model'}),selection.type!=='rig');tab('骨骼绑定',()=>choose({type:'rig'}),selection.type==='rig');if(selection.type==='rig')renderRig(c);else renderModel(c);}
 else if(activePage==='actions'){if(selection.type==='animation'){detail();tab('← 动作库',()=>goPage('actions'),false);renderAnimation(c);}else renderActionLibrary(c);}
 else if(activePage==='equipment')renderEquipmentWorkspace(c);
 else if(activePage==='sheets'){if(selection.type==='quality')tab('← 返回交付',()=>goPage('sheets')); if(selection.type==='quality'){detail();renderQuality(c);}else if(selection.type==='action_set_advanced'){tab('← 整套生产',()=>goPage('sheets'));renderActionSetAdvanced(c);}else if(selection.type==='sheet'){tab('← 角色动作集',()=>goPage('sheets'));detail();renderSheet(c);}else renderActionSet(c);}
 else{detail();renderSequence(c);}
}
function renderActionLibrary(c){
 const root=$('page-library'),rows=animationResources(c),query=prefs().actionQuery||'';
 root.append(sectionHeading('动作库',`${rows.length} 个动作 · 原动作与生成的图集分别管理。`,button('＋ 添加 Mixamo 动作',openAdd,'primary',blocked()||!c.rig.ready)));
 const search=node('input');search.type='search';search.placeholder='搜索动作标题';search.value=query;search.setAttribute('aria-label','搜索动作');const grid=node('div',undefined,'asset-grid');
 const paint=()=>{grid.replaceChildren();for(const a of rows.filter(a=>animationTitle(a.batch,a.file).toLowerCase().includes(search.value.toLowerCase()))){const card=node('article',undefined,'asset-card'),approved=animationApproved(c,a.batch,a.file),review=reviewFor(c,a.batch),pose=review?.images.find(i=>i.name.startsWith(a.key+'_'));const art=node('button',undefined,'asset-art');art.type='button';art.setAttribute('aria-label','检查动作 '+animationTitle(a.batch,a.file));if(pose){const img=node('img');img.src=pose.url;img.alt=animationTitle(a.batch,a.file)+'姿态检查';img.loading='lazy';art.append(img);}else art.append(node('span','▷','asset-symbol'));art.onclick=()=>choose({type:'animation',key:a.key,version:a.id});
 const body=node('div',undefined,'asset-copy');body.append(tag(!a.batch.current_rig?'历史绑定':approved?'已确认':'待检查',approved?'good':'warning'),node('h3',animationTitle(a.batch,a.file)),...(a.batch.action_roles?.[a.file]?[tag(ROLE_LABELS[a.batch.action_roles[a.file]]||a.batch.action_roles[a.file])]:[]),node('p',`来源 ${sourceTime(a.batch.id)}${a.versions.length>1?' · '+a.versions.length+' 个来源版本':''}`,'muted'));const actions=node('div',undefined,'card-actions');actions.append(button('检查动作',art.onclick),button('生成图集',()=>openExport(a.batch.id,[a.file]),'primary',blocked()||!a.batch.current_rig||!approved));body.append(actions);card.append(art,body);grid.append(card);}if(!grid.childElementCount)grid.append(placeholder('没有匹配的动作','尝试其他标题，或添加 Mixamo 原动作。'));};
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
function deliveryTitle(d){return `${d.operation?.type==='palette'?'颜色简化':d.operation?.type==='compact'?'精简结果':'渲染结果'} · ${rendererName(d.renderer)} · ${sourceTime(d.id)}`;}
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
 const groups=sheetGroups(c);
 if(!groups.length){const root=$('page-library');root.append(sectionHeading('交付','从已确认动作生成第一套成果。',button('生成成果',()=>openExport(),'primary',blocked()||!c.batches.some(b=>b.current_rig))));root.append(placeholder('还没有交付成果','先在动作页完成检查，再生成图集。'));return;}
 const group=groups.find(g=>g.key===prefs().deliveryClip)||groups[0],preferred=prefs().deliveryVersions?.[group.key],version=group.versions.find(v=>v.delivery.id===preferred)||group.versions[0];
 selection={type:'sheet',delivery:version.delivery.id,clip:version.item.name};detail();renderSheet(c);
}
function deliveryRaw(c,delivery){let current=delivery;const seen=new Set();while(current?.operation?.source_delivery&&!seen.has(current.id)){seen.add(current.id);const parent=c.deliveries.find(d=>d.id===current.operation.source_delivery);if(!parent)break;current=parent;}return current;}
function selectDelivery(delivery,clip){prefs().deliveryClip=clip;prefs().deliveryVersions={...(prefs().deliveryVersions||{}),[clip]:delivery};remember();choose({type:'sheet',delivery,clip});}
function viewName(view){return ({front:'正面',side:'侧面',three_quarter:'四分之三'})[view]||view||'未记录视角';}
function renderSheet(c){
 const d=c.deliveries.find(d=>d.id===selection.delivery),item=d?.clips.find(i=>i.name===selection.clip);if(!item){goPage('sheets');return;}
 const controls=$('controls'),content=$('preview-content'),title=animationTitle(c.batches.find(b=>b.id===d.batch)||{},item.name+'.fbx');setTitles('DELIVERY',title,'输出方案');
 prefs().deliveryClip=item.name;
 const list=node('aside',undefined,'delivery-action-list');list.id='delivery-action-list';list.append(node('h3','动作成果'));
 for(const group of sheetGroups(c)){const preferred=prefs().deliveryVersions?.[group.key],entry=group.key===item.name?{delivery:d,item}:group.versions.find(v=>v.delivery.id===preferred)||group.versions[0];const row=button('',()=>selectDelivery(entry.delivery.id,entry.item.name),'delivery-action'+(group.key===item.name?' selected':''));row.setAttribute('aria-label','预览 '+group.title);const img=node('img');img.src=entry.item.game?.gif||entry.item.gif;img.alt='';const copy=node('span');copy.append(node('strong',group.title),node('small',`${entry.item.game?.info.frame_count||entry.item.info.frame_count} 帧 · ${entry.item.info.quality?.status==='review'?'需复核':'可预览'}`));row.append(img,copy);list.append(row);}
 list.append(button('＋ 生成其他动作',()=>openExport(),'full',blocked()));$('detail-layout').classList.add('delivery-layout');$('detail-layout').prepend(list);
 const raw=deliveryRaw(c,d),rawItem=raw?.clips.find(i=>i.name===item.name),resume=selection.previewResume;
 const toolbar=node('div',undefined,'delivery-preview-tools');
 if(item.game)toolbar.append(select([['game','精简成果'],['source','完整采样']],prefs().frameVariant||'game',value=>{selection.previewResume=player?{position:player.position,playing:player.playing}:null;prefs().frameVariant=value;remember();renderWorkspace(true);}));
 toolbar.append(select([[1,'1× 实际像素'],[2,'2×'],[3,'3×']],prefs().spriteZoom||1,value=>{selection.previewResume=player?{position:player.position,playing:player.playing}:null;prefs().spriteZoom=Number(value);remember();renderWorkspace(true);}));
 if(d.color_processing&&rawItem)toolbar.append(button(selection.compareRaw?'查看处理成果':'对照原色',()=>{selection.previewResume=player?{position:player.position,playing:player.playing}:null;selection.compareRaw=!selection.compareRaw;renderWorkspace(true);},selection.compareRaw?'selected':''));
 content.append(toolbar);
 const comparisonGame=item.comparison||(item.game?.info.source_frame_indices?{...item.game,sheet:rawItem?.sheet,info:{...item.game.info,preview_source_indices:item.game.info.source_frame_indices}}:null);const alignedRaw=rawItem&&comparisonGame?{...rawItem,game:comparisonGame}:rawItem;const baseItem=selection.compareRaw&&alignedRaw?alignedRaw:item,chosen=baseItem.game&&prefs().frameVariant!=='source'?gameItem(baseItem):baseItem;mountPlayer(chosen,resume);delete selection.previewResume;
 const quality=item.info.quality;
 if(d.heading_stale)content.append(node('div','此成果的朝向设置已过期，请重新渲染。','callout'));
 if(quality?.status==='review')content.append(node('div','存在需复核画面，请查看右侧质量详情。','callout'));
 const compression=item.game?.info.compression;content.append(node('div',`${selection.compareRaw?'正在对照原色 · ':''}${item.info.frame_count} → ${item.game?.info.frame_count||item.info.frame_count} 帧 · ${Number(item.info.duration_seconds).toFixed(2)} 秒${compression?.output_bytes?' · '+(compression.output_bytes/1024).toFixed(1)+' KB':''}`,'delivery-result-summary'));
 controls.append(node('div',`${item.info.body_height_px||'?'}px · ${viewName(item.info.view)} · ${d.equipment?.config?.weapon_name||(d.equipment?'已装备':'空手')}`,'delivery-recipe-summary'));
 const colorOptions=[['original','保留原色'],['new:32','简化为 32 色'],['new:64','简化为 64 色'],['new:128','简化为 128 色']];
 const appliedPalette=d.color_processing?.palette_id,appliedColors=d.color_processing?.colors;
 let color=appliedPalette||'original',profile=item.game?.info.compression?.profile||'balanced';if(!['balanced','smooth','compact'].includes(profile))profile='balanced';
 const basicValue=appliedColors?'new:'+appliedColors:'original';
 const currentColor=color,currentProfile=profile;
 const apply=button('成果已就绪',async()=>{
  prefs().frameVariant='game';remember();
  if(color!==currentColor){if(!rawItem){notify('找不到原色来源，请选择原色记录。',true);return;}
   if(color==='original')await start('palette',{delivery:raw.id,clips:[item.name],colors:0,profile,timing_delivery:d.id,preserve_timing:profile===currentProfile});
   else await start('palette',{delivery:raw.id,clips:[item.name],profile,timing_delivery:d.id,preserve_timing:profile===currentProfile,...(color.startsWith('new:')?{colors:Number(color.split(':')[1])}:{palette_id:color})});
  }else await start('compact',{delivery:d.id,clips:[item.name],profile});
 },'primary full',true);
 apply.hidden=true;const update=()=>{const changed=color!==currentColor||profile!==currentProfile;apply.hidden=!changed;apply.textContent=changed?'更新当前动作':'成果已就绪';apply.disabled=!changed||blocked()||!readyServer();download.style.display=changed?'none':'';};
 const basicColor=select(colorOptions,basicValue,value=>{paletteReuse.value='';color=value===basicValue?currentColor:value;update();});
 const paletteReuse=select([['','自动处理配色'],...(state.palettes||[]).map(p=>[p.id,p.name+' · '+p.rgb.length+' 色'])],'',value=>{if(value){color=value;const palette=(state.palettes||[]).find(p=>p.id===value);basicColor.value='new:'+palette.rgb.length;}else{basicColor.value=basicValue;color=currentColor;}update();});
 controls.append(field('颜色',basicColor),field('帧精简',select([['balanced','推荐'],['smooth','更多细节'],['compact','更少帧']],profile,value=>{profile=value;update();})),note('修改颜色或精简程度后更新当前动作，无需重新渲染。'));
 controls.append(details('高级配色设置',note('仅在需要跨人物或跨动作复用指定配色时使用。一般保持自动处理即可。'),field('复用调色板',paletteReuse),...(appliedPalette?[note('当前成果已保存配色；只调整帧精简时会继续使用。')]:[])));

 const download=link(selection.compareRaw?'导出原色对照动作':'导出当前动作',(selection.compareRaw&&!(item.comparison&&chosen!==baseItem)?raw:d).export+'&clip='+encodeURIComponent(item.name)+'&variant='+(selection.compareRaw&&item.comparison&&chosen!==baseItem?'comparison':chosen===baseItem?'source':'game'));download.classList.add('delivery-export');
 controls.append(apply,download,button('用于角色动作集',()=>adoptSetCandidate(d,item),'full',!readyServer()));
 const siblings=c.deliveries.filter(x=>x.kind!=='sequence'&&x.clips.some(i=>i.name===item.name));controls.append(details(`版本历史 · ${siblings.length}`,field('查看版本',select(siblings.map(x=>[x.id,deliveryTitle(x)]),d.id,id=>selectDelivery(id,item.name))),note('切换版本会保留该动作的浏览选择；历史产物不会覆盖。')));
 const qualityDetails=details('质量与使用限制',note('自动检查不代表动作语义、美术或循环接缝已验收。'));for(const w of quality?.warnings||[])qualityDetails.append(note(w.message));if(quality?.loop?.status==='review')qualityDetails.append(note('循环：'+quality.loop.message));controls.append(qualityDetails);
 controls.append(details('渲染设置与来源',properties([['渲染器',rendererName(d.renderer)],['画布',item.info.frame_width+' × '+item.info.frame_height],['脚底锚点',item.info.anchor_px?.map(v=>Number(v).toFixed(1)).join(', ')],['记录',deliveryTitle(d)]]),note('改变尺寸、视角或装备需要重新渲染。'),button('重新配置渲染',()=>openExport(d.batch,[item.name+'.fbx']),'full',blocked()),button('查看全部质量记录',()=>choose({type:'quality'}),'full')));
 const files=details('单项文件与完整记录',link('完整记录 ZIP',d.export),link('完整采样 PNG',item.sheet),link('完整采样 GIF',item.gif),link('时序与质量清单',d.manifest));if(item.game)files.append(link('精简 PNG',item.game.sheet),link('精简 GIF',item.game.gif),link('Godot SpriteFrames',item.game.spriteframes));controls.append(files);
 $('viewport-note').textContent=`${selection.compareRaw?'原色对照':'当前成果'} · ${chosen.info.frame_count} 帧 · ${Number(chosen.info.duration_seconds).toFixed(2)} 秒 · 操作只创建新版本。`;
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

function openGamePackage(){
 $('game-package-dialog')?.remove();const dialog=node('dialog');dialog.id='game-package-dialog';const top=node('div',undefined,'dialog-top');top.append(node('h2','导出 Godot 人物包'),button('关闭',()=>dialog.close()));dialog.append(top,note('为四个用途选择图集。默认使用推荐精简版；根节点固定为脚底锚点。素材包包含人物场景和动作预览。'));
 const c=state.selected,options=c.deliveries.filter(d=>!d.heading_stale).flatMap(d=>d.clips.map(item=>({id:d.id+'/'+item.name,d,item}))),choices={};let variant='game';
 dialog.append(field('图集版本',select([['game','游戏精简版（推荐）'],['source','完整采样版']],variant,v=>{variant=v;})));
 for(const role of ['idle','walk','run','jump']){const aliases={idle:['breathing_idle','idle'],walk:['walking','walk'],run:['running','run','fast_run'],jump:['standing_jump','jump']};
  const match=options.find(o=>c.batches.find(b=>b.id===o.d.batch)?.action_roles?.[o.item.name+'.fbx']===role)||options.find(o=>aliases[role].includes(o.item.name));choices[role]=match?.id||'';
  const preview=node('img');preview.style.width='60px';preview.style.height='60px';preview.style.objectFit='contain';preview.alt=ROLE_LABELS[role]+' 所选图集预览';if(match)preview.src=match.item.game?.gif||match.item.gif;else preview.hidden=true;
  const row=node('div',undefined,'package-role-row');row.append(field(ROLE_LABELS[role],select([['','请选择图集'],...options.map(o=>[o.id,o.item.name+' · '+(o.item.info.body_height_px||'?')+'px · '+deliveryTitle(o.d)])],choices[role],v=>{choices[role]=v;const option=options.find(o=>o.id===v);preview.hidden=!option;if(option)preview.src=option.item.game?.gif||option.item.gif;})),preview);dialog.append(row);
 }
 const status=note('导出前检查比例、视角、绑定与时序；循环接缝仍需目视检查。');dialog.append(status,button('下载人物包',async()=>{if(Object.values(choices).some(v=>!v)){status.textContent='请先选齐四个动作用途。';return;}
  const selections=Object.fromEntries(Object.entries(choices).map(([role,id])=>{const [delivery,clip]=id.split('/');return [role,{delivery,clip}];}));
  try{status.textContent='正在检查并打包…';const urlBase='/api/game-package?character='+encodeURIComponent(selected)+'&variant='+variant+'&selections='+encodeURIComponent(JSON.stringify(selections));const check=await fetch(urlBase+'&inspect=1'),report=await check.json();if(!check.ok)throw Error(report.error||'检查失败');const response=await fetch(urlBase);if(!response.ok){const data=await response.json();throw Error(data.error||'导出失败');}const blob=await response.blob(),url=URL.createObjectURL(blob),a=node('a');a.href=url;a.download=selected+'-godot.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);status.textContent='已导出。解压后打开 project.godot 预览；已有项目复制 character_assets 文件夹。'+(report.warnings.length?' 需复核：'+report.warnings.join('；'):'');}catch(e){status.textContent=e.message;}
 },'primary full'));document.body.append(dialog);dialog.showModal();
}

// Adopted actions are project data; browsing candidates never replaces them.
const actionSetDrafts=new Map();
function actionSetDraft(c){
 if(!actionSetDrafts.has(c.id))actionSetDrafts.set(c.id,JSON.parse(JSON.stringify(c.action_set||{title:'角色动作集',revision:0,actions:{idle:{loop:true},walk:{loop:true},run:{loop:true},jump:{loop:false}}})));
 return actionSetDrafts.get(c.id);
}
function setRecipeKey(recipe){return JSON.stringify({title:recipe.title,actions:Object.fromEntries(Object.entries(recipe.actions).map(([role,a])=>[role,{delivery:a.delivery,clip:a.clip,variant:a.variant||'game',loop:!!a.loop,reviewed:!!a.reviewed}]))});}
function setOptions(c){return sequenceOptions(c).filter(o=>!o.delivery.heading_stale);}
function setEntry(c,choice){if(!choice?.delivery)return null;const option=setOptions(c).find(o=>o.id===choice.delivery+'/'+choice.clip);if(!option)return null;return {...option,shown:choice.variant==='source'?option.item:option.item.game?gameItem(option.item):null};}
function setPreviewBounds(c,draft){
 const entries=Object.values(draft.actions).map(a=>setEntry(c,a)?.shown?.info).filter(i=>i?.anchor_px?.length===2);
 const left=Math.max(48,...entries.map(i=>i.anchor_px[0])),right=Math.max(48,...entries.map(i=>i.frame_width-i.anchor_px[0]));
 const top=Math.max(110,...entries.map(i=>i.anchor_px[1])),bottom=Math.max(20,...entries.map(i=>i.frame_height-i.anchor_px[1]));
 return {width:Math.ceil(left+right+16),height:Math.ceil(top+bottom+16),ground:[Math.ceil(left+8),Math.ceil(top+8)]};
}
async function saveActionSet(){
 const c=state.selected,draft=actionSetDraft(c);if(blocked())return;busy=true;
 try{const result=await api('/api/action-set',{character:c.id,...draft});actionSetDrafts.set(c.id,result.recipe);notify(result.validation.complete?'动作集已保存。':'动作集已保存为草稿，请补齐检查项。');await refresh(true);}catch(e){notify(e.message,true);}finally{busy=false;renderWorkspace(true);}
}
function adoptSetCandidate(delivery,item){
 const c=state.selected,draft=actionSetDraft(c);const roles=Object.keys(draft.actions);let role=prefs().setRole;if(!roles.includes(role))role=roles[0];
 const dialog=node('dialog');dialog.append(node('h2','采用动作成果'),note(item.name+' · '+deliveryTitle(delivery)),field('动作槽位',select(roles.map(r=>[r,ROLE_LABELS[r]?r+' · '+ROLE_LABELS[r]:r]),role,v=>role=v)),button('放入动作集草稿',()=>{draft.actions[role]={delivery:delivery.id,clip:item.name,variant:prefs().frameVariant==='source'?'source':'game',loop:!!draft.actions[role].loop,reviewed:false};prefs().setRole=role;remember();dialog.close();choose({type:'action_set_advanced'});},'primary'),button('取消',()=>dialog.close()));dialog.onclose=()=>dialog.remove();document.body.append(dialog);dialog.showModal();
}
function renderActionSetAdvanced(c){
 detail();const draft=actionSetDraft(c),roles=Object.keys(draft.actions);let role=prefs().setRole;if(!roles.includes(role))role=roles[0];
 const choice=draft.actions[role],entry=setEntry(c,choice),controls=$('controls'),content=$('preview-content');
 const dirty=!c.action_set||setRecipeKey(draft)!==setRecipeKey(c.action_set),validation=c.action_set_validation;
 setTitles('ACTION SET',draft.title,'当前动作');
 const list=node('aside',undefined,'delivery-action-list');list.id='delivery-action-list';list.append(node('h3','角色动作集'));
 for(const r of roles){const a=draft.actions[r],e=setEntry(c,a),row=button('',()=>{prefs().setRole=r;remember();renderWorkspace(true);},'delivery-action'+(r===role?' selected':''));
 const copy=node('span');copy.append(node('strong',r),node('small',!e?.shown?'待选择成果':(a.reviewed?'已人工验收':'待验收')+' · '+e.shown.info.frame_count+' 帧'));if(e?.shown?.gif){const img=node('img');img.src=e.shown.gif;img.alt='';row.append(img);}row.append(copy);list.append(row);}
 list.append(button('浏览候选成果',()=>{const groups=sheetGroups(c);if(groups.length){const v=groups[0].versions[0];choose({type:'sheet',delivery:v.delivery.id,clip:v.item.name});}else openExport();},'full'));
 const add=node('input');add.placeholder='attack / 自定义英文标识';add.setAttribute('aria-label','新动作标识');list.append(add,button('＋ 添加动作槽位',()=>{const r=add.value.trim();if(!/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$/.test(r)||draft.actions[r]||roles.length>=32){notify('请输入不重复的英文动作标识，最多32个。',true);return;}draft.actions[r]={loop:false,reviewed:false};prefs().setRole=r;remember();renderWorkspace(true);},'full'));
 $('detail-layout').classList.add('delivery-layout');$('detail-layout').prepend(list);
 const toolbar=node('div',undefined,'delivery-preview-tools');toolbar.append(tag(dirty?'有未保存修改':'已保存'),select([[1,'1× 实际像素'],[2,'2×'],[3,'3×']],prefs().spriteZoom||1,v=>{prefs().spriteZoom=Number(v);remember();renderWorkspace(true);}));content.append(toolbar);
 if(entry?.shown){mountPlayer(entry.shown);if(player){player.loop=choice.loop;player.anchorPreview={...setPreviewBounds(c,draft),anchor:entry.shown.info.anchor_px};player.canvas.width=player.anchorPreview.width;player.canvas.height=player.anchorPreview.height;const z=Number(prefs().spriteZoom)||1;player.canvas.style.width=player.canvas.width*z+'px';player.canvas.style.height=player.canvas.height*z+'px';}}
 else content.append(placeholder('为 '+role+' 选择动作成果','从右侧选择已生成的图集。所有动作在同一脚底位置、以相同倍率预览。'));
 content.append(note('十字线是统一脚底原点。切换左侧动作检查比例、位置与风格；单次动作播放结束停在末帧。'));
 const options=setOptions(c);controls.append(node('h3',role),field('采用成果',select([['','请选择成果'],...options.map(o=>[o.id,o.title+' · '+(o.item.info.body_height_px||'?')+'px · '+deliveryTitle(o.delivery)])],choice.delivery?choice.delivery+'/'+choice.clip:'',v=>{const [delivery,clip]=v.split('/');draft.actions[role]={...(delivery?{delivery,clip,variant:choice.variant||'game'}:{}),loop:!!choice.loop,reviewed:false};renderWorkspace(true);})),field('采样版本',select([['game','游戏精简版'],['source','完整采样版']],choice.variant||'game',v=>{choice.variant=v;choice.reviewed=false;renderWorkspace(true);})),field('播放方式',select([['loop','循环播放'],['once','单次播放']],choice.loop?'loop':'once',v=>{choice.loop=v==='loop';choice.reviewed=false;renderWorkspace(true);})));
 if(choice.delivery&&!entry)controls.append(note('采用来源已不可用，请重新选择。'));
 if(entry&&!entry.shown)controls.append(note('此成果没有精简版，请选择完整采样版或先生成精简版。'));
 if(entry)controls.append(button('调整此动作的颜色与精简',()=>choose({type:'sheet',delivery:choice.delivery,clip:choice.clip}),'full'));
 const reviewed=node('input');reviewed.type='checkbox';reviewed.checked=!!choice.reviewed;reviewed.disabled=!entry?.shown;reviewed.onchange=()=>{choice.reviewed=reviewed.checked;renderWorkspace(true);};const label=node('label',undefined,'check-row');label.append(reviewed,node('span','已检查姿态、风格及循环/结束效果'));controls.append(label);
 if(roles.length>1)controls.append(button('移除此槽位',()=>{delete draft.actions[role];renderWorkspace(true);},'full'));
 const title=node('input');title.value=draft.title;title.onchange=()=>{draft.title=title.value;renderWorkspace(true);};controls.append(field('动作集名称',title),button('保存动作集',saveActionSet,'primary full',blocked()||!readyServer()||!dirty));
 if(!dirty&&validation){const report=node('div',undefined,'action-set-validation');report.append(node('strong',validation.complete?'整套结构检查通过':'动作集尚未就绪'));for(const message of [...validation.errors,...validation.warnings])report.append(note(message));controls.append(report);}
 else controls.append(note('保存后检查整套动作的绑定、比例、视角、配色、锚点和时序。'));
 if(!dirty&&validation?.complete)controls.append(link('导出整套 Godot 人物包','/api/action-set/export?character='+encodeURIComponent(c.id)));
 else controls.append(button('导出整套 Godot 人物包',()=>{},'full',true));
 $('viewport-note').textContent=dirty?'当前为动作集草稿；保存后才能整套导出。':'预览与整套导出使用已保存的动作集。生成新版本不会自动替换。';
}

// The primary workflow produces a whole set. Individual adoption remains advanced.
const productionDrafts=new Map();
function productionConfig(value){return {title:value.title||'角色动作集',actions:value.actions,renderer:value.renderer||'godot',view:value.view||'three_quarter',body_height:value.body_height||96,supersample:value.supersample||4,colors:value.colors??64,profile:value.profile||'balanced',equipment_id:value.equipment_id||null};}
function productionDraft(c){
 if(!productionDrafts.has(c.id)){const preset=state.action_presets?.[0];productionDrafts.set(c.id,c.production?.config?JSON.parse(JSON.stringify(productionConfig(c.production.config))):productionConfig({actions:(preset?.actions||[{role:'idle',title:'Breathing Idle',loop_intent:true},{role:'walk',title:'Walking',loop_intent:true},{role:'run',title:'Running',loop_intent:true},{role:'jump',title:'Standing Jump',loop_intent:false}]).map(a=>({role:a.role,title:a.title,loop:a.loop_intent}))}));}
 return productionDrafts.get(c.id);
}
function editProductionActions(c){
 const current=productionDraft(c),actions=JSON.parse(JSON.stringify(current.actions)),dialog=node('dialog');dialog.className='production-actions-dialog';
 const top=node('div',undefined,'dialog-top');top.append(node('h2','整套动作清单'),button('关闭',()=>dialog.close()));dialog.append(top,note('填写 Mixamo 完整英文标题。整套共用输出规格，生成时自动复用已有原动作并下载缺失项。'));
 const rows=node('div');const paint=()=>{rows.replaceChildren();for(const [i,a]of actions.entries()){
  const row=node('div',undefined,'production-action-edit'),role=node('input'),title=node('input');role.value=a.role;role.placeholder='动作标识';role.setAttribute('aria-label','动作标识 '+(i+1));title.value=a.title;title.placeholder='Mixamo title';title.setAttribute('aria-label','Mixamo 标题 '+(i+1));
  role.oninput=()=>a.role=role.value.trim();title.oninput=()=>a.title=title.value.trim();row.append(role,title,select([['loop','循环'],['once','单次']],a.loop?'loop':'once',v=>a.loop=v==='loop'),link('查找','https://www.mixamo.com/#/?page=1&query='+encodeURIComponent(a.title||''),true),button('移除',()=>{actions.splice(i,1);paint();}));rows.append(row);
 }};paint();dialog.append(rows,button('＋ 添加动作',()=>{if(actions.length<12){actions.push({role:'',title:'',loop:false});paint();}}),button('使用基础移动预设',()=>{const preset=state.action_presets?.[0];if(preset){actions.splice(0,actions.length,...preset.actions.map(a=>({role:a.role,title:a.title,loop:a.loop_intent})));paint();}}));
 const status=note('动作标识供游戏使用，例如 idle、attack；标题决定下载哪个表演。');dialog.append(status,button('使用这套清单',()=>{if(!actions.length||actions.some(a=>!a.title||!a.role)||new Set(actions.map(a=>a.role)).size!==actions.length){status.textContent='请填写不重复的标识和完整标题，至少保留一个动作。';return;}current.actions=actions;dialog.close();renderWorkspace(true);},'primary full'));
 dialog.onclose=()=>dialog.remove();document.body.append(dialog);dialog.showModal();
}
function renderActionSet(c){
 detail();const draft=productionDraft(c),controls=$('controls'),content=$('preview-content'),jobs=ownJobs().filter(j=>j.action==='produce'),job=jobs[0];
 const sameJob=job&&JSON.stringify(productionConfig(job.params))===JSON.stringify(draft),running=sameJob&&isRunning(job),failed=sameJob&&['failed','interrupted'].includes(job.status);
 const result=sameJob&&job.outputs?.result&&!job.outputs?.action_set?job.outputs.result:c.action_set;
 const configChanged=!!c.action_set&&(!c.production?.config||JSON.stringify(productionConfig(c.production.config))!==JSON.stringify(draft));
 let role=prefs().productionRole;if(!draft.actions.some(a=>a.role===role))role=draft.actions[0]?.role;
 const entry=setEntry(c,result?.actions?.[role]);
 setTitles('ACTION SET',draft.title,'整套输出方案');
 const list=node('aside',undefined,'delivery-action-list');list.id='delivery-action-list';list.append(node('h3',draft.actions.length+' 个动作'),button('编辑动作清单',()=>editProductionActions(c),'full',blocked()));
 for(const action of draft.actions){const choice=result?.actions?.[action.role],e=setEntry(c,choice),status=sameJob?job.outputs?.production?.roles?.[action.role]:null,row=button('',()=>{prefs().productionRole=action.role;remember();renderWorkspace(true);},'delivery-action'+(role===action.role?' selected':''));
 const text=node('span');text.append(node('strong',action.role),node('small',action.title),node('small',status?.status==='failed'?'生成失败':status?.status==='ready'?'已生成':status?.status==='source_ready'?'原动作就绪':e?.shown?'已有成果':'待生成'));
 if(e?.shown?.gif){const image=node('img');image.src=e.shown.gif;image.alt='';row.append(image);}row.append(text);list.append(row);
 }
 $('detail-layout').classList.add('delivery-layout');$('detail-layout').prepend(list);
 const tools=node('div',undefined,'delivery-preview-tools');tools.append(tag(running?'整套生成中':failed?'部分步骤未完成':configChanged?'方案未生成 · 显示已发布成果':c.action_set?'当前动作集':'尚未生成'),select([[1,'1× 实际像素'],[2,'2×'],[3,'3×']],prefs().spriteZoom||1,v=>{prefs().spriteZoom=Number(v);remember();renderWorkspace(true);}));content.append(tools);
 if(entry?.shown){mountPlayer(entry.shown);if(player){player.loop=!!result.actions[role].loop;player.anchorPreview={...setPreviewBounds(c,result),anchor:entry.shown.info.anchor_px};player.canvas.width=player.anchorPreview.width;player.canvas.height=player.anchorPreview.height;const z=Number(prefs().spriteZoom)||1;player.canvas.style.width=player.canvas.width*z+'px';player.canvas.style.height=player.canvas.height*z+'px';}}
 else content.append(placeholder('一键生成整套角色动作','设置一次规格，Studio 自动准备原动作、渲染、共享配色和精简，无需逐个选择图集版本。'));
 if(running){const live=node('div',c.progress?.message||'正在启动整套生产任务…','callout');live.id='production-live-progress';content.append(live);}
 if(failed){const errors=Object.entries(job.outputs?.production?.roles||{}).filter(([,r])=>r.status==='failed');for(const [r,item]of errors)content.append(node('div',r+'：'+item.error,'callout'));if(!errors.length)content.append(node('div',job.error||'任务中断，可继续。','callout'));}
 if(entry?.shown)content.append(note((running?'生成期间显示上一套已发布成果。':failed?'当前为本次已完成的候选结果，正式动作集保持不变。':configChanged?'当前显示已发布成果，修改后的方案在生成完成后生效。':'切换左侧动作检查整套效果。')+' 十字线是统一脚底位置。'));
 const title=node('input');title.value=draft.title;title.onchange=()=>{draft.title=title.value;renderWorkspace(true);};controls.append(field('动作集名称',title));
 const change=(key,value)=>{draft[key]=value;renderWorkspace(true);};
 controls.append(field('人物像素高度',select([[48,'48px'],[64,'64px'],[96,'96px（推荐）'],[128,'128px']],draft.body_height,v=>change('body_height',Number(v)))),field('视角',select([['three_quarter','四分之三'],['front','正面'],['side','侧面']],draft.view,v=>change('view',v))),field('整套颜色',select([[0,'保留原色'],[32,'共享 32 色'],[64,'共享 64 色'],[128,'共享 128 色']],draft.colors,v=>change('colors',Number(v)))),field('帧精简',select([['balanced','推荐'],['smooth','更多细节'],['compact','更少帧']],draft.profile,v=>change('profile',v))),field('装备',select([['','空手'],...c.equipment.map(e=>[e.id,e.weapon_name||'标准剑'])],draft.equipment_id||'',v=>change('equipment_id',v||null))));
 controls.append(details('高级渲染设置',field('渲染器',select([['godot','Godot'],['blender','Blender · Eevee']],draft.renderer,v=>change('renderer',v))),field('超采样',select([[4,'4 倍'],[2,'2 倍'],[1,'关闭']],draft.supersample,v=>change('supersample',Number(v))))));
 controls.append(button(running?'正在生成整套动作…':failed?'继续生成 · 只补未完成步骤':'生成整套动作',()=>failed?mutation('/api/tasks',{character:selected,retry:job.id}):start('produce',productionConfig(draft)),'primary full',blocked()||!readyServer()||!c.rig.ready||!draft.actions.length));
 controls.append(note(!c.rig.ready?'先完成人物骨骼绑定。绑定后，动作生产可一次完成。':'自动复用已有原动作与本流程的渲染缓存；只下载缺失动作。共享配色后分别精简，全部通过结构检查再发布。'));
 if(c.action_set&&c.action_set_validation?.complete&&!running&&!failed)controls.append(link(configChanged?'导出已发布人物包':'导出整套 Godot 人物包','/api/action-set/export?character='+encodeURIComponent(c.id)));
 if(c.action_set&&!running&&!failed)controls.append(details('整套检查报告',...(c.action_set_validation?.errors||[]).map(note),...(c.action_set_validation?.warnings||[]).map(note)));
 controls.append(details('高级管理',button('管理采用版本与单动作验收',()=>choose({type:'action_set_advanced'}),'full'),button('浏览已有图集',()=>{const groups=sheetGroups(c);if(groups.length){const v=groups[0].versions[0];choose({type:'sheet',delivery:v.delivery.id,clip:v.item.name});}else openExport();},'full')));
 $('viewport-note').textContent='生成完成后仍需整体目视检查。Mixamo 首次登录与人工骨骼绑定不包含在自动生产中。';
}

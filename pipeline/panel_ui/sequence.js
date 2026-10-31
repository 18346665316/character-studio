'use strict';
// Exact delivery references keep equipment, renderer and historical renders explicit.
function sequenceOptions(c){return c.deliveries.filter(d=>d.kind!=='sequence').flatMap(d=>d.clips.filter(i=>i.sheet).map(item=>({id:d.id+'/'+item.name,delivery:d,item,title:animationTitle(c.batches.find(b=>b.id===d.batch)||{},item.name+'.fbx')})));}
function sequenceDraft(c){const p=prefs();if(!p.sequenceDraft)p.sequenceDraft=JSON.parse(JSON.stringify(c.sequence||{title:'动作编排',loop:true,segments:[]}));return p.sequenceDraft;}
function sequenceSettings(draft,options){
 if(!draft.renderSettings){const first=options.find(o=>o.id===draft.segments[0]?.delivery+'/'+draft.segments[0]?.clip);draft.renderSettings={renderer:first?.delivery.renderer||'godot',view:first?.item.info.view||'three_quarter',frame_size:128,supersample:4,equipment_id:first?.delivery.equipment?.id||null};}
 return draft.renderSettings;
}
function sequenceRecipe(draft){const s=draft.renderSettings;return {sources:[...new Set(draft.segments.map(s=>s.delivery+'/'+s.clip))].sort(),renderer:s.renderer,view:s.view,frame_size:s.frame_size,supersample:s.supersample,equipment_id:s.equipment_id||null};}
function sequencePreviewOptions(c,draft,options){
 const preview=c.sequence_preview;if(!preview||JSON.stringify(preview.recipe)!==JSON.stringify(sequenceRecipe(draft)))return null;
 const delivery=c.deliveries.find(d=>d.id===preview.delivery);if(!delivery)return null;
 const mapped=options.map(o=>({...o,delivery,item:gameItem(delivery.clips.find(i=>i.name===preview.clips[o.id])||{})}));
 return draft.segments.every(s=>mapped.some(o=>o.id===s.delivery+'/'+s.clip&&o.item?.sheet))?mapped:null;
}
// One timing model for uniform legacy sheets and variable-duration game sheets.
function clipTiming(info){
 const n=Number(info.frame_count),fps=Number(info.fps)||n/Number(info.duration_seconds)||12;
 const durations=info.frame_durations_seconds||Array.from({length:n},()=>1/fps);
 if(!Number.isInteger(n)||n<1||durations.length!==n||durations.some(v=>!Number.isFinite(v)||v<=0))throw Error('逐帧时长无效');
 const starts=[0];for(const d of durations)starts.push(starts.at(-1)+d);
 if(info.duration_seconds&&Math.abs(starts.at(-1)-Number(info.duration_seconds))>1e-5)throw Error('逐帧时长与总时长不符');
 return {starts,duration:starts.at(-1)};
}
function heldFrameAt(timing,time){
 let lo=0,hi=timing.starts.length-1;
 while(lo+1<hi){const mid=(lo+hi)>>1;if(timing.starts[mid]<=time)lo=mid;else hi=mid;}
 return lo;
}
function gameItem(item){return item.game?{...item,...item.game,name:item.name}:item;}
function buildSequence(segments,options){
 let count=0,duration=0;const spans=[];
 for(const [index,segment]of segments.entries()){
  const source=options.find(o=>o.id===segment.delivery+'/'+segment.clip);
  if(!source)throw Error(`第 ${index+1} 段的图集已不存在，请移除或重新选择。`);
  const info=source.item.info,n=Number(info.frame_count),w=Number(info.frame_width),h=Number(info.frame_height),fps=Number(info.fps)||n/Number(info.duration_seconds)||12;
  if(!Number.isInteger(n)||n<1||!(w>0&&h>0&&fps>0)||!Number.isInteger(segment.repeat)||segment.repeat<1||segment.repeat>20||!(segment.speed>=.25&&segment.speed<=4))throw Error(`第 ${index+1} 段的帧信息或播放设置无效。`);
  const timing=clipTiming(info),frames=n*segment.repeat,seconds=timing.duration*segment.repeat/segment.speed;
  spans.push({source,index,start:count,end:count+frames,time:duration,until:duration+seconds,n,w,h,timing,speed:segment.speed,fps:fps*segment.speed});count+=frames;duration+=seconds;
 }
 return {spans,count,duration};
}
function sequenceFrame(plan,frame){const span=plan.spans.find(s=>frame<s.end)||plan.spans.at(-1);return {span,local:(frame-span.start)%span.n};}
function sequenceTime(plan,frame){const {span}=sequenceFrame(plan,frame);const offset=frame-span.start;return span.time+(Math.floor(offset/span.n)*span.timing.duration+span.timing.starts[offset%span.n])/span.speed;}
function sequenceFrameAt(plan,time){const s=plan.spans.find(s=>time<s.until)||plan.spans.at(-1);const elapsed=Math.max(0,time-s.time)*s.speed,cycle=Math.floor(elapsed/s.timing.duration);return Math.min(s.end-1,s.start+cycle*s.n+heldFrameAt(s.timing,elapsed-cycle*s.timing.duration));}
function renderSequence(c){
 setTitles('SEQUENCE','动作编排','编排设置');const controls=$('controls'),content=$('preview-content'),draft=sequenceDraft(c),options=sequenceOptions(c);
 const changed=()=>{remember();renderWorkspace(true);};
 const renderSettings=sequenceSettings(draft,options);
 const title=node('input');title.value=draft.title;title.maxLength=60;title.oninput=()=>{draft.title=title.value;remember();};title.onchange=()=>{draft.title=title.value.trim()||'动作编排';changed();};controls.append(field('编排名称',title));
 controls.append(field('整段播放',select([['loop','循环播放'],['once','播放一次']],draft.loop?'loop':'once',v=>{draft.loop=v==='loop';changed();})));
 const choice=select(options.map(o=>[o.id,`${o.title} · ${rendererName(o.delivery.renderer)} · ${o.delivery.equipment?.config?.weapon_name||(o.delivery.equipment?'标准单手剑':'空手')} · ${sourceTime(o.delivery.id)}`]),options[0]?.id,()=>{});
 controls.append(field('添加已渲染动画',choice),button('＋ 添加片段',()=>{const o=options.find(v=>v.id===choice.value);if(o){draft.segments.push({delivery:o.delivery.id,clip:o.item.name,repeat:1,speed:1});changed();}},'full',!options.length||draft.segments.length>=64));
 controls.append(button('保存编排',()=>mutation('/api/sequence',{character:selected,...draft},'动作编排已保存到当前人物。'),'primary full',blocked()||state.api_version<10),note(JSON.stringify(draft)===JSON.stringify(c.sequence)?'编排已保存。':'当前编排有未保存的修改。'));
 const rendering=node('div',undefined,'sequence-rendering');rendering.append(node('h3','统一取景'));
 rendering.append(field('编排渲染器',select([['godot','Godot'],['blender','Blender · Eevee']],renderSettings.renderer,v=>{renderSettings.renderer=v;changed();})),field('编排视角',select([['front','正面'],['side','侧面'],['three_quarter','四分之三']],renderSettings.view,v=>{renderSettings.view=v;changed();})),field('编排帧尺寸',select([[64,'64 × 64'],[128,'128 × 128']],renderSettings.frame_size,v=>{renderSettings.frame_size=Number(v);changed();})),field('编排装备',select([['','空手'],...c.equipment.map(e=>[e.id,e.weapon_name||'标准单手剑'])],renderSettings.equipment_id||'',v=>{renderSettings.equipment_id=v||null;changed();})),note('整段动作共用同一相机、画布、装备和调色板。更改顺序、速度与重复次数无需重新渲染。'));
 const previewOptions=sequencePreviewOptions(c,draft,options);
 rendering.append(button(previewOptions?'重新生成统一预览':'生成统一预览',()=>start('sequence',{recipe:sequenceRecipe(draft)}),'primary full',blocked()||!draft.segments.length||state.api_version<10));controls.append(rendering);
 const list=node('ol',undefined,'sequence-list');list.setAttribute('aria-label','动作编排片段');
 draft.segments.forEach((segment,index)=>{
  const source=options.find(o=>o.id===segment.delivery+'/'+segment.clip),row=node('li',undefined,'sequence-segment');row.dataset.segment=index;
  row.append(node('strong',`${index+1}. ${source?.title||'图集已缺失'}`));
  if(source)row.append(note(`原动画来源：${sourceTime(source.delivery.id)}。预览统一使用 ${rendererName(renderSettings.renderer)} · ${renderSettings.frame_size}px · ${renderSettings.view}。`));
  const settings=node('div',undefined,'sequence-settings');
  const repeat=select(Array.from({length:20},(_,i)=>[i+1,`${i+1} 次`]),segment.repeat,v=>{segment.repeat=Number(v);changed();});
  settings.append(field(`第 ${index+1} 段重复次数`,repeat),field(`第 ${index+1} 段速度`,select([[.25,'0.25×'],[.5,'0.5×'],[1,'1×'],[1.5,'1.5×'],[2,'2×'],[4,'4×']],segment.speed,v=>{segment.speed=Number(v);changed();})));
  const actions=node('div',undefined,'sequence-actions');actions.append(button('上移',()=>{[draft.segments[index-1],draft.segments[index]]=[draft.segments[index],draft.segments[index-1]];changed();},'',index===0),button('下移',()=>{[draft.segments[index+1],draft.segments[index]]=[draft.segments[index],draft.segments[index+1]];changed();},'',index===draft.segments.length-1),button('移除',()=>{draft.segments.splice(index,1);changed();}));row.append(settings,actions);list.append(row);
 });controls.append(list);
 if(!draft.segments.length){content.append(placeholder('添加动画，开始编排','在右侧选择已渲染的动画并添加片段，同一动作可添加多次。'));if(!options.length)controls.append(note('暂无可播放图集。请先在动画中导出图集，再回来编排。'));return;}
 try{
  if(!previewOptions){content.append(placeholder('需要生成统一预览','先按编排中的全部动作统一取景，再连续播放，避免跨图集尺寸和位置跳变。'));return;}
  const plan=buildSequence(draft.segments,previewOptions);content.append(node('div',`${draft.segments.length} 个片段 · ${plan.duration.toFixed(2)} 秒`,'sequence-summary'));

  const track=node('div',undefined,'sequence-track');track.setAttribute('aria-label','编排片段时间轴');
  for(const span of plan.spans){const seek=button(`${span.index+1}. ${span.source.title} · ${(span.until-span.time).toFixed(2)}s`,()=>{if(player?.plan&&player.ready){setPlaying(false);player.frame=span.start;player.position=span.time;drawFrame(player);}},'sequence-cue');seek.dataset.segment=span.index;track.append(seek);}content.append(track);
  mountSequencePlayer(plan,draft.loop);
 }catch(e){content.append(node('div',e.message,'callout'));}
 $('viewport-note').textContent='整段共用相机与缩放，保留动作中的跳跃和身体位移；段间姿态直接切换，尚不做骨骼过渡。';
}
function mountSequencePlayer(plan,loop){
 const stage=node('div',undefined,'sprite-stage sequence-stage'),canvas=node('canvas');stage.append(canvas);$('preview-content').append(stage);
 const p=player={plan,loop,canvas,ctx:canvas.getContext('2d'),frame:0,count:plan.count,position:0,playing:false,last:0,cancelled:false,ready:false,images:new Map()};
 const items=[...new Map(plan.spans.map(s=>[s.source.item.sheet,s])).values()];let loaded=0,failed=false;
 const error=message=>{if(p.cancelled||player!==p)return;failed=true;stage.replaceChildren(note(message));};
 for(const s of items){const img=new Image();p.images.set(s.source.item.sheet,img);img.onload=()=>{if(p.cancelled||player!==p||failed)return;if(Math.floor(img.naturalWidth/s.w)*Math.floor(img.naturalHeight/s.h)<s.n)return error('图集尺寸与帧数不符，请重新渲染。');if(++loaded===items.length){p.ready=true;$('timeline').max=p.count-1;$('playback').hidden=false;drawFrame(p);setPlaying(true);animationFrame=requestAnimationFrame(tick);}};img.onerror=()=>error('编排图集加载失败，请检查资源后重新预览。');img.src=s.source.item.sheet;}
}
function drawSequenceFrame(p){
 const {span:s,local}=sequenceFrame(p.plan,p.frame),img=p.images.get(s.source.item.sheet),cols=Math.floor(img.naturalWidth/s.w);
 if(p.canvas.width!==s.w||p.canvas.height!==s.h){p.canvas.width=s.w;p.canvas.height=s.h;}
 p.ctx.clearRect(0,0,s.w,s.h);p.ctx.imageSmoothingEnabled=false;p.ctx.drawImage(img,(local%cols)*s.w,Math.floor(local/cols)*s.h,s.w,s.h,0,0,s.w,s.h);
 $('timeline').value=p.frame;$('frame-label').textContent=`${p.frame+1} / ${p.count}`;$('preview-meta').textContent=`${s.index+1} / ${p.plan.spans.length} · ${s.source.title}`;
 document.querySelectorAll('.sequence-segment, .sequence-cue').forEach(row=>row.classList.toggle('playing',Number(row.dataset.segment)===s.index));
}
function tickSequence(p,time){
 if(p.playing){p.position+=Math.max(0,time-p.last)/1000*Number($('play-speed').value);if(p.position>=p.plan.duration){if(p.loop)p.position%=p.plan.duration;else{p.position=p.plan.duration;setPlaying(false);}}p.frame=sequenceFrameAt(p.plan,p.position);drawFrame(p);}p.last=time;
}

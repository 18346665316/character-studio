'use strict';
(() => {
 const $=id=>document.getElementById(id),q=new URLSearchParams(location.search);
 const task=q.get('task'),kit=q.get('kit'),source=q.get('source');
 let state,job,signature='',busy=false,reviewDirty=false,formLoaded=false;
 const checks={silhouette:'整体轮廓与墙角保持一致',roof_topology:'双坡屋顶与山墙结构正确',openings:'门窗数量、位置与比例正确',scale:'地面接触和建筑比例正确',edges:'透明边缘无残色、缺口或裁断',style:'材质、配色与画风符合要求'};
 const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const draftKey='studio.building.structure.'+(source||'new');
 function stored(key){try{return JSON.parse(localStorage.getItem(key));}catch{return null;}}
 function save(key,value){try{localStorage.setItem(key,JSON.stringify(value));}catch{message('浏览器草稿空间不足，请先保存当前方案。',true);}}
 function message(text,error=false){$('building-message').hidden=!text;$('building-message').textContent=text;$('building-message').className=error?'asset-feedback terrain-error':'asset-feedback';}
 async function api(path,data){const r=await fetch(path,data?{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Token':state.token},body:JSON.stringify(data)}:{});const v=await r.json();if(!r.ok)throw Error(v.error||'请求失败');return v;}
 const number=id=>Number($(id).value);
 function field(label,input){const n=node('label',label);n.append(input);return n;}
 function numeric(value,min,max,step='.01'){const input=node('input');input.type='number';Object.assign(input,{value:String(value),min:String(min),max:String(max),step,required:true});return input;}
 function windowRow(values={facade:'+y',center:.6,width:.5,bottom:.65,height:.47}){
  const row=node('div',undefined,'building-opening terrain-fields');
  const facade=node('select');for(const [v,t]of [['+y','左侧墙面（+Y）'],['+x','右侧墙面（+X）'],['-y','背面（−Y，可能不可见）'],['-x','背面（−X，可能不可见）']]){const o=node('option',t);o.value=v;facade.append(o);}facade.value=values.facade;facade.dataset.key='facade';row.append(field('墙面',facade));
  for(const [key,label]of [['center','中心位置（格）'],['width','宽度（格）'],['bottom','底高（单位）'],['height','高度（单位）']]){const input=numeric(values[key],key==='bottom'?0:.15,8);input.dataset.key=key;row.append(field(label,input));}
  const remove=node('button','移除此窗户');remove.type='button';remove.onclick=()=>{row.remove();persistForm();};row.append(remove);$('building-windows').append(row);
 }
 function formData(){
  const openings=[{type:'door',facade:$('building-door-face').value,center:number('building-door-center'),width:number('building-door-width'),bottom:0,height:number('building-door-height')}];
  for(const row of $('building-windows').children){const o={type:'window'};for(const input of row.querySelectorAll('[data-key]'))o[input.dataset.key]=input.dataset.key==='facade'?input.value:Number(input.value);openings.push(o);}
  return {title:$('building-title').value,structure:{footprint_cells:[number('building-width'),number('building-depth')],cell_px:number('building-cell'),wall_height_units:number('building-height'),roof:{type:'gable',ridge_axis:$('building-ridge').value,rise_units:number('building-rise'),overhang_cells:number('building-overhang')},openings}};
 }
 function persistForm(){if(formLoaded)save(draftKey,formData());}
 function fillForm(data){
  $('building-title').value=data.title||'';const s=data.structure;if(!s)return;
  for(const [id,value]of Object.entries({'building-cell':s.cell_px,'building-width':s.footprint_cells[0],'building-depth':s.footprint_cells[1],'building-height':s.wall_height_units,'building-ridge':s.roof.ridge_axis,'building-rise':s.roof.rise_units,'building-overhang':s.roof.overhang_cells}))$(id).value=value;
  const door=s.openings.find(o=>o.type==='door');if(door)for(const [id,key]of [['building-door-face','facade'],['building-door-center','center'],['building-door-width','width'],['building-door-height','height']])$(id).value=door[key];
  $('building-windows').replaceChildren();s.openings.filter(o=>o.type==='window').forEach(windowRow);
 }
 $('building-add-window').onclick=()=>{windowRow();persistForm();};windowRow();windowRow({facade:'+x',center:.85,width:.55,bottom:.65,height:.47});
 $('building-form').addEventListener('input',persistForm);$('building-form').addEventListener('change',persistForm);
 async function fileData(file){if(!file)return null;if(file.size>8*1024*1024)throw Error('图片不能超过8MB');return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result).split(',')[1]);r.onerror=()=>reject(Error('图片读取失败'));r.readAsDataURL(file);});}
 $('building-form').onsubmit=async event=>{event.preventDefault();if(busy||!state)return;busy=true;const button=event.submitter;button.disabled=true;try{
  const parent=source&&state.jobs.find(j=>j.id===source);if(source&&!parent)throw Error('原结构任务不存在');
  const data=formData();if(parent)Object.assign(data,{source_task:source,source_revision:parent.revision,appearance:parent.spec.appearance});
  const result=await api('/api/buildings/prepare',data);localStorage.removeItem(draftKey);
  location.assign('/building-structure.html?task='+encodeURIComponent(result.id));
 }catch(e){message(e.message,true);}finally{busy=false;button.disabled=false;}};
 const file=(kind,attempt)=>'/api/buildings/file?task='+encodeURIComponent(task)+'&kind='+kind+(attempt?'&attempt='+encodeURIComponent(attempt):'')+'&v='+job.revision;
 function picture(label,url){const f=node('figure');const img=node('img');img.src=url;img.alt=label;img.className='surface-preview';f.append(node('figcaption',label),img);return f;}
 function link(text,url){const a=node('a',text);a.href=url;return a;}
 function button(text,action,disabled=false,reload=true){const b=node('button',text);b.type='button';b.disabled=disabled;b.onclick=async()=>{if(busy)return;busy=true;b.disabled=true;try{await action();if(reload){reviewDirty=false;signature='';await refresh();}}catch(e){message(e.message,true);}finally{busy=false;b.disabled=false;}};return b;}
 function render(){
  const taskRevision=job.revision,attempt=job.current_attempt;
  const adjust=data=>api('/api/buildings/adjust',{task,revision:taskRevision,...data});
  const root=$('building-task');root.hidden=false;root.replaceChildren();
  const heading=node('section',undefined,'terrain-card');heading.append(node('h2',job.spec.title),node('p',job.stage));if(job.error)heading.append(node('p',job.error,'terrain-error'));root.append(heading);
  const structure=node('section',undefined,'terrain-card');structure.append(node('h2','结构与占地'));const grid=node('div',undefined,'building-images');grid.append(picture('AI结构参考（无标记）',file('reference')),picture('占地、原点与入口检查',file('inspection')));structure.append(grid,node('p','橙色为结构占地，红点为地面原点，青色为入口接近方向。占地建议不自动启用碰撞。'),link('载入当前规格修改结构','/building-structure.html?source='+encodeURIComponent(task)));root.append(structure);
  if(!['queued','running'].includes(job.status))fetch(file('structure')).then(r=>r.json()).then(s=>{for(const o of s.opening_visibility||[]){if(o.warning)structure.append(node('p',`${o.type==='door'?'门':'窗户'} ${o.index+1}：可见约${Math.round(o.visible_ratio*100)}%，${o.warning}`,'terrain-error'));}}).catch(()=>{});
  if(job.status==='draft'){
   const section=node('section',undefined,'terrain-card');section.append(node('h2','2 · 外观方案'));const key='studio.building.appearance.'+task;
   const cached=stored(key),appearance=node('textarea');appearance.id='building-appearance';appearance.maxLength=2000;appearance.rows=4;appearance.value=cached?.text??job.spec.appearance;
   appearance.oninput=()=>{reviewDirty=true;save(key,{text:appearance.value});};
   const style=node('input');style.type='file';style.accept='image/png,image/jpeg,image/webp';
   const remove=node('input');remove.type='checkbox';
   section.append(field('材质、配色与画风',appearance),field('风格参考图（可选）',style));
   if(job.has_style)section.append(link('查看已保存风格图',file('style')),field('移除已保存风格图',remove));
   section.append(node('p','结构版本已保存。外观方案保存后保留风格图，刷新也可继续。新选择的文件请先保存。'));
   const saveAppearance=async()=>{const result=await adjust({action:'appearance',appearance:appearance.value,style_reference:await fileData(style.files[0]),remove_style:remove.checked});localStorage.removeItem(key);reviewDirty=false;return result;};
   section.append(button('保存外观方案',saveAppearance));
   const confirmed=node('input');confirmed.type='checkbox';const generate=button('确认结构并生成外观（可能产生费用）',async()=>{const saved=await saveAppearance();await api('/api/buildings/generate',{task,revision:saved.revision});},true);
   confirmed.onchange=()=>generate.disabled=!confirmed.checked||!state.image_api_configured;section.append(field('我已检查占地、门窗和屋顶结构',confirmed),generate);
   if(!state.image_api_configured)section.append(node('p','请先在项目 .env 配置图片服务，再刷新。'));root.append(section);return;
  }
  if(['queued','running'].includes(job.status)){heading.append(node('p','刷新或关闭页面不影响任务。远程编号已记录后，中断可继续查询原任务。'));return;}
  if(job.status==='failed'){
   const labels={unsubmitted:'发起尚未提交的生成（可能产生费用）',query:'继续查询原任务（不重新提交）',process:'重新运行后处理（不调用图片服务）'};
   if(labels[job.recovery])heading.append(button(labels[job.recovery],()=>api('/api/buildings/generate',{resume:task,revision:taskRevision,submit_unsubmitted:job.recovery==='unsubmitted'})));
   else heading.append(node('p',job.recovery==='uncertain'?'提交结果不明：请先在服务商核实；已阻止自动重复提交。':'原回执无法继续；请核实错误后明确创建新尝试。'));
  }
  if(job.status==='failed'&&job.recovery==='uncertain'){const remote=node('input');remote.type='text';remote.maxLength=200;heading.append(field('从服务商记录核实的原任务ID',remote),button('补录任务ID（只用于继续查询）',()=>adjust({action:'reconcile',remote_id:remote.value})));}
  if(!attempt)return;
  const candidate=node('section',undefined,'terrain-card');candidate.append(node('h2','当前候选'));
  if(['waiting_review','approved','rejected','complete'].includes(job.status)){
   const images=node('div',undefined,'building-images');images.append(picture('透明背景与深浅底检查',file('preview',attempt)),picture('青色为原结构轮廓',file('comparison',attempt)));candidate.append(images);
  }
  candidate.append(link('查看原始生成图',file('raw',attempt)),document.createTextNode(' · '),link('查看生成回执',file('receipt',attempt)));
  const logs=node('details');logs.append(node('summary','请求日志'));const log=node('pre',undefined,'terrain-request-log');logs.append(button('读取当前尝试的请求日志',async()=>{const result=await api('/api/buildings/job-log?id='+encodeURIComponent(task)+'&attempt='+encodeURIComponent(attempt));log.textContent=result.events.map(e=>JSON.stringify(e)).join('\n')||'暂无请求记录';},false,false),log);candidate.append(logs);
  if(['waiting_review','approved','rejected'].includes(job.status)){
   if(!job.evidence_valid){candidate.append(node('p','检查图缺少当前版本的完整证据，或文件已经变化。需重新制作检查图后复核。','terrain-error'),button('重新制作复核图（不生图）',()=>adjust({action:'recheck'})));}
   else{
    const key='studio.building.review.'+[task,attempt,job.evidence_key,taskRevision].join('.'),local=stored(key),draft=local||job.review||{},fields={};
    if(local)reviewDirty=true;
    candidate.append(node('h3','人工复核'),node('p','可暂存检查，也可重新提交同一候选。改变检查结论会保留旧记录；撤回通过后需再次复核才能导出。'));
    const note=node('textarea');note.maxLength=2000;note.value=draft.note||'';
    const values=()=>({checks:Object.fromEntries(Object.entries(fields).map(([k,i])=>[k,i.checked])),note:note.value});
    let exportButton;
    const persist=()=>{reviewDirty=true;if(exportButton)exportButton.disabled=true;save(key,values());};
    for(const [k,label]of Object.entries(checks)){const input=node('input');input.type='checkbox';input.checked=draft.checks?.[k]===true;input.onchange=persist;fields[k]=input;candidate.append(field(label,input));}
    note.oninput=persist;
    const submit=async action=>{await api('/api/buildings/review',{task,revision:taskRevision,...values(),action});localStorage.removeItem(key);};
    candidate.append(field('复核或修正说明',note),button('暂存检查（不批准）',()=>submit('draft')),button('提交复核结论',()=>submit('decide')));
    if(job.status==='approved'){exportButton=button('导出已复核的建筑候选包',()=>api('/api/buildings/publish',{task,revision:taskRevision}),!!local);candidate.append(button('撤回通过，重新复核',()=>submit('reopen')),exportButton,node('p','修改检查后请先提交复核结论，再导出候选包。'));}
   }
  }
  if(job.kit_id)candidate.append(link('查看并下载候选包 →','/building-structure.html?kit='+encodeURIComponent(job.kit_id)));
  if(['process'].includes(job.recovery)){
   const repair=node('details');repair.append(node('summary','修复透明背景（不生图）'));const upload=node('input');upload.type='file';upload.accept='image/png';
   repair.append(node('p','上传与原始生成图尺寸相同、坐标不变的透明 PNG。保留原图与每次修正输入；重新处理后需重新复核。'),field('同坐标透明修正图',upload),button('导入修正图并重做检查',async()=>{if(!upload.files[0])throw Error('请选择透明PNG');await adjust({action:'repair',image:await fileData(upload.files[0])});}));candidate.append(repair);
  }
  const details=node('details');details.append(node('summary','制作下一版外观（可能产生费用）'));
  const correction=node('textarea'),key='studio.building.correction.'+task+'.'+attempt,localCorrection=stored(key);correction.maxLength=2000;correction.value=localCorrection?.text||'';
  const mode=node('select');for(const [v,t]of [['fresh','按结构重新生成新候选'],['edit','编辑选定候选，保留满意的外观']]){const o=node('option',t);o.value=v;mode.append(o);}
  const selected=node('select');for(const c of job.candidates||[]){if(c.has_raw){const o=node('option',c.id);o.value=c.id;selected.append(o);}}selected.value=localCorrection?.source||attempt;mode.value=localCorrection?.mode||'fresh';
  const persistCorrection=()=>save(key,{text:correction.value,mode:mode.value,source:selected.value});correction.oninput=persistCorrection;mode.onchange=persistCorrection;selected.onchange=persistCorrection;
  const blocked=!state.image_api_configured||['query','uncertain'].includes(job.recovery);
  details.append(field('操作方式',mode),field('编辑来源候选',selected),field('本次要求（编辑会继承来源的历次修正要求）',correction),node('p','重新生成只使用结构和风格；编辑会另附所选候选原图。旧图和回执保留。'),button('提交新的生图尝试（可能产生费用）',async()=>{await api('/api/buildings/generate',{task,revision:taskRevision,correction:correction.value,mode:mode.value,source_attempt:selected.value});localStorage.removeItem(key);},blocked));candidate.append(details);
  if(job.attempts.length>1){const history=node('details');history.append(node('summary','历史候选'));for(const c of job.candidates||[]){const row=node('p',c.id+' ');row.append(link('查看原图',file('raw',c.id)));if(c.has_raw&&c.id!==attempt)row.append(button('选用此候选重新复核',()=>adjust({action:'adopt',attempt:c.id})));history.append(row);}candidate.append(history);}
  root.append(candidate);
 }
 async function refresh(){try{
  state=await api('/api/buildings/state');
  if(!task&&!kit&&!formLoaded){const parent=source&&state.jobs.find(j=>j.id===source);if(parent)fillForm({title:parent.spec.title,structure:parent.structure_spec});const draft=stored(draftKey);if(draft)fillForm(draft);formLoaded=true;if(source)message('已载入原名称、门窗、外观方案和风格图。提交后建立新的结构版本，原记录保留。');}
  if(task){job=state.jobs.find(j=>j.id===task);if(!job){message('建筑任务不存在或已不可用',true);return;}const next=JSON.stringify([job.id,job.revision,job.status,job.evidence_valid]);if(signature!==next){if(signature&&reviewDirty){message('任务已在其他操作中更新。当前未保存的检查暂时保留，请重新载入最新任务后复核。',true);const reload=button('载入最新任务',async()=>{message('');});reload.id='building-reload';$('building-message').append(reload);return;}signature=next;render();}}
  if(kit){const k=state.kits.find(k=>k.id===kit),root=$('building-kit');root.hidden=false;root.replaceChildren();if(!k){message('建筑候选包不存在',true);return;}root.className='terrain-card';root.append(node('h2',k.title),node('p','已通过记录中的人工复核；人物比例、碰撞与四周遮挡尚未通过游戏接入验证。'),picture('候选包预览','/building-asset/'+encodeURIComponent(kit)+'/preview.png'));if(k.integrity?.passed)root.append(link('下载候选包 ZIP','/building-asset/'+encodeURIComponent(kit)+'/kit.zip'));else root.append(node('p','文件完整性异常，禁止下载','terrain-error'));root.append(link('返回生产与尝试记录','/building-structure.html?task='+encodeURIComponent(k.task_id)));}
 }catch(e){message(e.message,true);}}
 if(task||kit)$('building-form').hidden=true;refresh();if(task)setInterval(()=>{if(!document.hidden&&!busy)refresh();},4000);
 window.addEventListener('studio-image-provider-changed',()=>{if(!busy)Promise.resolve(refresh()).catch(()=>{});});
})();

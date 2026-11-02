'use strict';
(() => {
 const $=id=>document.getElementById(id),query=new URLSearchParams(location.search);
 const task=query.get('task'),kit=query.get('kit'),source=query.get('source');
 let state,job,busy=false,signature='',loaded=false,previewURL,templateLibrarySignature='';
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 let fieldCounter=0;
 const field=(text,input)=>{const wrapper=el('div'),label=el('label',text);if(!input.id)input.id='building-field-'+(++fieldCounter);label.htmlFor=input.id;wrapper.append(label,input);return wrapper;};
 const link=(text,url)=>{const a=el('a',text);a.href=url;return a;};
 function message(text,error=false){$('building-message').hidden=!text;$('building-message').textContent=text;$('building-message').className='asset-feedback'+(error?' terrain-error':'');}
 function getDraft(key){try{return JSON.parse(localStorage.getItem(key));}catch{return null;}}
 function setDraft(key,value){try{localStorage.setItem(key,JSON.stringify(value));}catch{message('浏览器草稿空间不足，请先保存生成方案。',true);}}
 async function api(path,data){const response=await fetch(path,data?{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Token':state.token},body:JSON.stringify(data)}:{});const result=await response.json();if(!response.ok)throw Error(result.error||'请求失败');return result;}
 async function fileData(file){if(!file)return null;if(file.size>8*1024*1024)throw Error('框线图不能超过8MB');return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error('图片读取失败'));reader.readAsDataURL(file);});}
 function button(text,action,disabled=false,reload=true){const b=el('button',text);b.type='button';b.disabled=disabled;b.onclick=async()=>{if(busy)return;busy=true;b.disabled=true;try{await action();if(reload){signature='';await refresh();}}catch(error){message(error.message,true);}finally{busy=false;b.disabled=disabled;}};return b;}
 const file=(kind,attempt)=>'/api/buildings/file?task='+encodeURIComponent(task)+'&kind='+kind+(attempt?'&attempt='+encodeURIComponent(attempt):'')+'&v='+job.revision;
 function picture(label,url){const figure=el('figure'),image=el('img');image.src=url;image.alt=label;image.className='surface-preview';figure.append(el('figcaption',label),image);return figure;}
 const formKey='studio.building.drawing.'+(source||'new');
 function persistForm(){if(loaded)setDraft(formKey,{title:$('building-title').value,appearance:$('building-appearance').value,template_id:$('building-template').value});}
 $('building-form').addEventListener('input',persistForm);
 $('building-drawing').onchange=()=>{if(previewURL)URL.revokeObjectURL(previewURL);const chosen=$('building-drawing').files[0];if(chosen){previewURL=URL.createObjectURL(chosen);$('drawing-preview').src=previewURL;$('drawing-preview').hidden=false;}};
 $('building-form').onsubmit=async event=>{
  event.preventDefault();if(!state||busy)return;busy=true;const buttons=[...$('building-form').querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);
  let created;
  try{
   const parent=source&&state.jobs.find(j=>j.id===source);
   created=await api('/api/buildings/prepare',{workflow:'line_drawing',title:$('building-title').value,appearance:$('building-appearance').value,...($('building-template').value?{template_id:$('building-template').value}:{line_drawing:await fileData($('building-drawing').files[0])}),...(parent?{source_task:source,source_revision:parent.revision}:{})});
   localStorage.removeItem(formKey);
   if(event.submitter?.dataset.generate==='true')await api('/api/buildings/generate',{task:created.id,revision:created.revision});
  }catch(error){if(created)sessionStorage.setItem('studio.building.notice.'+created.id,error.message);else message(error.message,true);}
  finally{if(created)location.assign('/buildings.html?task='+encodeURIComponent(created.id));else{busy=false;buttons.forEach(b=>b.disabled=false);$('building-create').disabled=!state.image_api_configured;}}
 };

 function templateChoice(){
  const id=$('building-template').value,template=state?.templates?.find(t=>t.id===id);
  $('building-upload').hidden=!!template;$('building-drawing').required=!template&&!source;
  if(template){$('drawing-preview').src='/api/buildings/template-file?id='+encodeURIComponent(id);$('drawing-preview').hidden=false;$('building-template-info').textContent=template.title+' · '+template.view_label+'。选择模板不会改变风格提示词。';}
  else{const chosen=$('building-drawing').files[0];$('drawing-preview').hidden=!chosen&&!source;if(chosen)$('drawing-preview').src=previewURL;else if(source)$('drawing-preview').src='/api/buildings/file?task='+encodeURIComponent(source)+'&kind=reference';$('building-template-info').textContent='上传本次框线图，或在“建筑设置”保存可复用模板。';}
  persistForm();
 }
 $('building-template').onchange=templateChoice;
 function templateMethod(){const upload=$('template-method').value==='upload';$('template-upload').hidden=!upload;$('template-generation').hidden=upload;$('template-description').required=!upload;$('template-file').required=upload;$('template-confirmed').required=upload;$('template-submit').textContent=upload?'保存建筑模板':'生成线框候选（可能产生费用）';$('template-submit').disabled=!upload&&state&&!state.image_api_configured;}
 const templateDraftKey='studio.building.template-settings',templateDraft=getDraft(templateDraftKey);
 if(templateDraft){$('template-name').value=templateDraft.title||'';$('template-description').value=templateDraft.description||'';$('template-view').value=templateDraft.view||'isometric_2_1';$('template-method').value=templateDraft.method||'generate';}
 function persistTemplate(){setDraft(templateDraftKey,{title:$('template-name').value,description:$('template-description').value,view:$('template-view').value,method:$('template-method').value});}
 $('template-form').addEventListener('input',persistTemplate);$('template-form').addEventListener('change',persistTemplate);
 $('template-method').onchange=templateMethod;templateMethod();
 $('template-form').onsubmit=async event=>{
  event.preventDefault();if(busy||!state)return;busy=true;$('template-submit').disabled=true;let created;
  try{const upload=$('template-method').value==='upload',base={title:$('template-name').value,view:$('template-view').value};
   if(upload){const saved=await api('/api/buildings/templates/save',{...base,line_drawing:await fileData($('template-file').files[0]),confirmed:$('template-confirmed').checked});localStorage.removeItem(templateDraftKey);await refresh();$('building-template').value=saved.id;templateChoice();message('模板已保存，可在下方填写风格并生成建筑。');}
   else{created=await api('/api/buildings/templates/prepare',{...base,description:$('template-description').value});localStorage.removeItem(templateDraftKey);await api('/api/buildings/generate',{task:created.id,revision:created.revision});}
  }catch(error){if(created)sessionStorage.setItem('studio.building.notice.'+created.id,error.message);else message(error.message,true);}
  finally{busy=false;$('template-submit').disabled=false;if(created)location.assign('/buildings.html?task='+encodeURIComponent(created.id));}
 };
 function renderTemplates(){
  const templates=state.templates||[],next=JSON.stringify(templates);if(next===templateLibrarySignature)return;templateLibrarySignature=next;
  const selected=$('building-template').value;$('building-template').replaceChildren();const blank=el('option','本次上传框线图');blank.value='';$('building-template').append(blank);
  for(const t of templates){const option=el('option',t.title+' · '+t.view_label);option.value=t.id;$('building-template').append(option);}$('building-template').value=selected;
  const library=$('building-template-library');library.replaceChildren(el('h3','已保存的模板'));
  if(!templates.length)library.append(el('p','暂无模板。可先生成线框候选或导入已有线框图。'));
  const grid=el('div',undefined,'building-template-grid');for(const t of templates){const card=el('article',undefined,'building-candidate');card.append(picture(t.title,'/api/buildings/template-file?id='+encodeURIComponent(t.id)),el('p',t.view_label),link('使用模板制作建筑','/buildings.html?template='+encodeURIComponent(t.id)));grid.append(card);}library.append(grid);
 }
 function renderTemplateTask(){
  const root=$('building-task');root.hidden=false;root.replaceChildren();const running=['queued','running'].includes(job.status),heading=el('section',undefined,'terrain-card');
  heading.append(el('h2','建筑模板 · '+job.spec.title),el('p',job.stage),el('p',job.spec.description),el('p',job.spec.view==='isometric_2_1'?'目标：2:1等距地格，地面轴线斜率±0.5':'目标：严格等轴测，地面轴线30°'));
  if(job.error)heading.append(el('p',job.error,'terrain-error'));
  heading.append(button('再生成一张线框候选（可能产生费用）',()=>api('/api/buildings/generate',{task,revision:job.revision}),running||!state.image_api_configured||['query','uncertain'].includes(job.recovery)));
  if(job.status==='failed'&&['query','process','unsubmitted'].includes(job.recovery))heading.append(button(job.recovery==='unsubmitted'?'发起未提交的生成（可能产生费用）':'恢复当前线框候选（不重新提交）',()=>api('/api/buildings/generate',{resume:task,revision:job.revision,submit_unsubmitted:job.recovery==='unsubmitted'})));
  if(job.recovery==='uncertain')heading.append(el('p','提交结果不明，请先核实服务商记录，系统不会自动重提。'));
  if(job.template_id)heading.append(link('使用已保存模板制作建筑','/buildings.html?template='+encodeURIComponent(job.template_id)));
  heading.append(link('返回建筑设置','/buildings.html?settings=templates'));root.append(heading);
  const section=el('section',undefined,'terrain-card');section.append(el('h2','选择线框母版'),el('p','检查地面平行线、垂直线、建筑形体和完整留白。目标视角只是生成要求，未经自动测量。'));
  const cards=el('div',undefined,'building-candidates');for(const [i,c]of (job.candidates||[]).entries()){const card=el('article',undefined,'building-candidate');card.append(el('h3','线框候选 '+(i+1)));
   if(c.has_raw)card.append(picture('线框图',file('raw',c.id)));
   if(c.ready){const confirmed=el('input');confirmed.type='checkbox';const save=button('保存为建筑模板',async()=>{const saved=await api('/api/buildings/templates/save',{task,revision:job.revision,attempt:c.id,evidence_key:c.evidence_key,title:job.spec.title,confirmed:confirmed.checked});location.assign('/buildings.html?template='+encodeURIComponent(saved.id));},true);confirmed.onchange=()=>save.disabled=!confirmed.checked||running;card.append(field('我已检查这张线框图的视角与建筑轮廓',confirmed),save);}
   else if(c.error)card.append(el('p',c.error,'terrain-error'));cards.append(card);
  }section.append(cards);root.append(section);
 }
 function render(){
  if(job.purpose==='template'){renderTemplateTask();return;}
  const root=$('building-task');root.hidden=false;root.replaceChildren();const running=['queued','running'].includes(job.status);
  const heading=el('section',undefined,'terrain-card');heading.append(el('h2',job.spec.title),el('p',job.stage));if(job.error)heading.append(el('p',job.error,'terrain-error'));
  const input=el('details');input.append(el('summary','本次使用的框线图与风格'),picture('原始建筑框线图',file('reference')),el('p',job.spec.appearance),link('另存框线图或风格方案','/buildings.html?source='+encodeURIComponent(task)));if(job.template_source)input.append(el('p','来源模板：'+job.template_source.title+' · '+job.template_source.view_label));heading.append(input);
  heading.append(button(job.attempts.length?'使用相同输入再生成一张（可能产生费用）':'生成第一个候选（可能产生费用）',()=>api('/api/buildings/generate',{task,revision:job.revision}),running||!state.image_api_configured||['query','uncertain'].includes(job.recovery)),el('p','每次生成保留独立候选，不覆盖旧图，不会自动连续调用服务。'));
  if(job.status==='failed'){
   const labels={unsubmitted:'提交尚未发起的生成（可能产生费用）',query:'继续查询原任务（不重新提交）',process:'重试自动透明处理（不生图）'};
   if(labels[job.recovery])heading.append(button(labels[job.recovery],()=>api('/api/buildings/generate',{resume:task,revision:job.revision,submit_unsubmitted:job.recovery==='unsubmitted'})));
   if(job.recovery==='uncertain'){
    heading.append(el('p','原提交是否成功尚不明确，已阻止重复生图。请先在服务商核实。'));
    const remote=el('input');remote.maxLength=200;heading.append(field('服务商记录中的原任务ID',remote),button('补录编号后继续查询',()=>api('/api/buildings/adjust',{task,revision:job.revision,action:'reconcile',remote_id:remote.value})));
   }
  }
  if(job.kit_id)heading.append(link('查看最近保存的素材','/buildings.html?kit='+encodeURIComponent(job.kit_id)));
  root.append(heading);
  const gallery=el('section',undefined,'terrain-card');gallery.append(el('h2','候选对比'),el('p','按原始整张画布等比例显示，不单独放大每栋建筑。不满意可继续生成，满意后再标定。'));
  const cards=el('div',undefined,'building-candidates');
  for(const [index,c]of (job.candidates||[]).entries()){
   const card=el('article',undefined,'building-candidate'+(c.id===job.selected_attempt?' selected':''));card.dataset.attempt=c.id;card.append(el('h3','候选 '+(index+1)));
   if(c.has_raw){const image=el('img');image.src=file(c.ready?'sprite':'raw',c.id);image.alt='候选 '+(index+1)+(c.ready?'透明图':'原图');image.className='building-candidate-image';card.append(image,link('查看原图',file('raw',c.id)));}
   else card.append(el('p',c.id===job.current_attempt&&running?'正在生成…':'尚无原图'));
   if(c.ready)card.append(button(c.id===job.selected_attempt?'已选用此候选':'选用此候选',()=>api('/api/buildings/select',{task,revision:job.revision,attempt:c.id}),running||c.id===job.selected_attempt));
   else if(c.error)card.append(el('p',c.has_raw?'自动透明处理未成功，可查看原图或继续生成。':c.error,'terrain-error'));
   cards.append(card);
  }
  if(!job.attempts.length)gallery.append(el('p','尚未生成候选。'));gallery.append(cards);root.append(gallery);
  const selected=job.candidates?.find(c=>c.id===job.selected_attempt&&c.ready);if(selected)calibration(root,selected,running);
  if(job.current_attempt){const records=el('details');records.append(el('summary','任务记录'),link('当前生成回执',file('receipt',job.current_attempt)));const logs=el('pre',undefined,'terrain-request-log');records.append(button('读取请求日志',async()=>{const data=await api('/api/buildings/job-log?id='+encodeURIComponent(task)+'&attempt='+encodeURIComponent(job.current_attempt));logs.textContent=data.events.map(e=>JSON.stringify(e)).join('\n')||'暂无记录';},false,false),logs);root.append(records);}
 }
 function calibration(root,candidate,running){
  const key='studio.building.calibration.'+[task,candidate.id,candidate.evidence_key].join('.');
  const draft=getDraft(key)||{anchor_px:null,footprint_polygon_px:[],entrance_px:null,output_width_px:512,cell_px:128};
  const section=el('section',undefined,'terrain-card');section.id='building-calibration';section.append(el('h2','标定选定的建筑'),el('p','按图片实际位置标记占地轮廓与落地锚点。占地是建议范围，碰撞默认关闭。红点为锚点，橙线为占地，青点为可选入口。'));
  const mode=el('select');for(const [value,text]of [['footprint','点击添加占地顶点'],['anchor','点击设置落地锚点'],['entrance','点击设置入口（可选）']]){const option=el('option',text);option.value=value;mode.append(option);}section.append(field('标记方式',mode));
  const canvas=el('canvas');canvas.id='building-calibration-canvas';canvas.width=candidate.canvas_px[0];canvas.height=candidate.canvas_px[1];canvas.setAttribute('aria-label','建筑占地与锚点标定图');
  const ctx=canvas.getContext('2d'),image=new Image(),status=el('p'),anchorInputs=[];image.onload=draw;image.src=file('sprite',candidate.id);section.append(canvas,status);
  function remember(){setDraft(key,draft);draw();}
  function draw(){
   if(!image.complete||!image.naturalWidth)return;const width=canvas.width,height=canvas.height,unit=width/512;ctx.clearRect(0,0,width,height);ctx.fillStyle='#34404b';ctx.fillRect(0,0,width,height);ctx.drawImage(image,0,0,width,height);
   if(draft.anchor_px){const [x,y]=draft.anchor_px,cell=draft.cell_px*width/draft.output_width_px;ctx.lineWidth=unit;ctx.strokeStyle='#a9c8bb88';ctx.beginPath();ctx.moveTo(x,y-cell/4);ctx.lineTo(x+cell/2,y);ctx.lineTo(x,y+cell/4);ctx.lineTo(x-cell/2,y);ctx.closePath();ctx.stroke();}
   const points=draft.footprint_polygon_px;ctx.lineWidth=2*unit;ctx.strokeStyle='#efaa45';ctx.fillStyle='#efaa4533';if(points.length){ctx.beginPath();ctx.moveTo(...points[0]);for(const p of points.slice(1))ctx.lineTo(...p);if(points.length>=3){ctx.closePath();ctx.fill();}ctx.stroke();}
   for(const [p,color]of [...points.map(p=>[p,'#efaa45']),[draft.anchor_px,'#ef7280'],[draft.entrance_px,'#55d9e0']])if(p){ctx.fillStyle=color;ctx.beginPath();ctx.arc(p[0],p[1],4*unit,0,Math.PI*2);ctx.fill();}
   for(const [axis,input]of anchorInputs.entries())if(draft.anchor_px&&document.activeElement!==input)input.value=String(draft.anchor_px[axis]);
   status.textContent=`已标记 ${points.length} 个占地顶点；${draft.anchor_px?'锚点已设置':'尚未设置锚点'}。浅绿菱形为一个地格，供比例比较。`;
  }
  canvas.onclick=event=>{const box=canvas.getBoundingClientRect(),point=[Math.round((event.clientX-box.left)*canvas.width/box.width),Math.round((event.clientY-box.top)*canvas.height/box.height)];if(mode.value==='footprint'){if(draft.footprint_polygon_px.length>=24){message('最多标记24个占地顶点',true);return;}draft.footprint_polygon_px.push(point);}else draft[mode.value==='anchor'?'anchor_px':'entrance_px']=point;remember();};
  section.append(button('撤销最后一个占地点',async()=>{draft.footprint_polygon_px.pop();remember();},false,false),button('清空占地',async()=>{draft.footprint_polygon_px=[];remember();},false,false),button('清除入口',async()=>{draft.entrance_px=null;remember();},false,false));
  const output=el('input');Object.assign(output,{type:'number',min:'64',max:'2048',step:'1',value:String(draft.output_width_px)});
  const cell=el('select');for(const value of [128,64]){const option=el('option',value+' × '+value/2+' px');option.value=String(value);cell.append(option);}cell.value=String(draft.cell_px);
  output.oninput=()=>{draft.output_width_px=Number(output.value);remember();};cell.onchange=()=>{draft.cell_px=Number(cell.value);remember();};
  section.append(field('成品画布宽度（px，整体等比例缩放）',output),field('用于比例检查的地格',cell));
  const fine=el('details');fine.append(el('summary','精确设置锚点坐标（原图像素）'));for(const [axis,label]of [[0,'锚点 X'],[1,'锚点 Y']]){const input=el('input');Object.assign(input,{type:'number',min:'0',max:String(candidate.canvas_px[axis]),value:String(draft.anchor_px?.[axis]??candidate.canvas_px[axis]/2)});input.onchange=()=>{if(!draft.anchor_px)draft.anchor_px=[...candidate.canvas_px].map(v=>v/2);draft.anchor_px[axis]=Number(input.value);remember();};anchorInputs.push(input);fine.append(field(label,input));}section.append(fine);
  section.append(nodeHint('保存只表示已选用并标定素材；人物比例、碰撞与遮挡仍需游戏内验证。'),button('保存选定建筑素材',async()=>{const result=await api('/api/buildings/save',{task,revision:job.revision,attempt:candidate.id,evidence_key:candidate.evidence_key,calibration:draft});localStorage.removeItem(key);location.assign('/buildings.html?kit='+encodeURIComponent(result.id));},running));root.append(section);
 }
 function nodeHint(text){return el('p',text,'terrain-hint');}
 async function refresh(){try{
  state=await api('/api/buildings/state');renderTemplates();
  if(!task&&!kit&&!loaded){const parent=source&&state.jobs.find(j=>j.id===source);if(source&&(!parent||!parent.has_outline)){message('原框线图方案不存在，请上传框线图创建新方案。',true);return;}const draft=getDraft(formKey);$('building-title').value=draft?.title??parent?.spec.title??'';$('building-appearance').value=draft?.appearance??parent?.spec.appearance??'';
   const chosen=query.get('template')||draft?.template_id||parent?.template_id||'';if([...$('building-template').options].some(o=>o.value===chosen))$('building-template').value=chosen;
   if(parent){$('building-drawing').required=false;$('drawing-preview').src='/api/buildings/file?task='+encodeURIComponent(source)+'&kind=reference';$('drawing-preview').hidden=false;}loaded=true;templateChoice();}
  if(!task&&!kit){$('template-submit').disabled=$('template-method').value==='generate'&&!state.image_api_configured;$('building-create').disabled=!state.image_api_configured;if(state.image_api_configured)$('building-api-hint').textContent=`图片服务：${state.image_provider==='google_cloud'?'Google Cloud Vertex AI':'兼容接口'} · ${state.image_model||'gpt-image-2'}。每次生成一张，可能产生费用。`;else $('building-api-hint').textContent='图片服务未配置，可先保存框线图与风格方案。生成前请在项目 .env 配置服务。';}
  if(task){job=state.jobs.find(j=>j.id===task);if(!job){message('建筑任务不存在',true);return;}if(job.workflow!=='line_drawing'){location.replace('/building-structure.html?task='+encodeURIComponent(task));return;}
   const next=JSON.stringify([job,state.image_api_configured,state.image_provider]);if(next!==signature){signature=next;render();}}
  if(kit){const entry=state.kits.find(k=>k.id===kit),root=$('building-kit');root.hidden=false;root.replaceChildren();if(!entry){message('建筑素材不存在',true);return;}root.className='terrain-card';root.append(el('h2',entry.title),picture('建筑素材预览','/building-asset/'+encodeURIComponent(kit)+'/preview.png'),el('p','素材已保存；人物比例、碰撞与遮挡尚未通过游戏接入验证。'));if(entry.integrity?.passed)root.append(link('下载建筑素材 ZIP','/building-asset/'+encodeURIComponent(kit)+'/kit.zip'));else root.append(el('p','文件完整性异常，禁止下载。','terrain-error'));root.append(link('返回候选与生产记录','/buildings.html?task='+encodeURIComponent(entry.task_id)));}
 }catch(error){message(error.message,true);}}
 if(task||kit){$('building-form').hidden=true;$('building-template-settings').hidden=true;}
 if(query.get('settings')==='templates')$('building-template-settings').open=true;
 if(task){const notice=sessionStorage.getItem('studio.building.notice.'+task);if(notice){message(notice,true);sessionStorage.removeItem('studio.building.notice.'+task);}}
 refresh();if(task)setInterval(()=>{if(!document.hidden&&!busy)refresh();},4000);
 window.addEventListener('studio-image-provider-changed',()=>{if(!busy)Promise.resolve(refresh()).catch(()=>{});});
})();

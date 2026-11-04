'use strict';
(() => {
 const dialog=document.createElement('dialog');dialog.id='prop-recovery-dialog';
 dialog.setAttribute('aria-labelledby','prop-recovery-title');
 dialog.innerHTML=`<h2 id="prop-recovery-title">修正原图背景</h2>
 <p>在原图的纯色背景空洞内点选，例如提手中间。只移除与标记点连通、且颜色接近背景的区域；不会识别或重画物件。</p>
 <div class="prop-recovery-layout"><section><h3>原图与背景标记</h3><canvas id="prop-recovery-source" aria-label="点击纯色背景空洞以添加背景标记"></canvas>
 <p id="prop-recovery-count"></p><button id="prop-recovery-undo" type="button">撤销标记</button> <button id="prop-recovery-clear" type="button">清空标记</button></section>
 <section><h3>处理结果</h3><p>先生成预览，再对照检查提手、孔洞和边缘。另存后仍可调整尺寸、锚点与碰撞。</p>
 <div id="prop-recovery-preview" hidden><div class="recovery-checker"><img alt="棋盘背景上的处理结果"></div><div class="recovery-dark"><img alt="深色背景上的处理结果"></div><div class="recovery-light"><img alt="浅色背景上的处理结果"></div></div></section></div>
 <p id="prop-recovery-status" role="status"></p><div class="prop-recovery-actions"><button id="prop-recovery-run" type="button">预览处理结果</button> <button id="prop-recovery-save" class="primary" type="button" disabled>另存为素材</button> <button id="prop-recovery-close" type="button">关闭</button></div>`;
 document.body.append(dialog);
 const $=id=>dialog.querySelector('#prop-recovery-'+id);
 let original,info,points=[],preview=null,working=false,call,onSave,previewURL=null;
 function clearPreview(){preview=null;$('preview').hidden=true;if(previewURL){URL.revokeObjectURL(previewURL);previewURL=null;}}
 function message(text,error=false){$('status').textContent=text;$('status').className=error?'terrain-error':'terrain-hint';}
 function controls(){
  $('run').disabled=working;$('save').disabled=working||!preview;$('close').disabled=working;
  $('undo').disabled=working||!points.length;$('clear').disabled=working||!points.length;
  $('source').style.pointerEvents=working?'none':'';
 }
 function draw(){
  const canvas=$('source'),ctx=canvas.getContext('2d');canvas.width=original.naturalWidth;canvas.height=original.naturalHeight;ctx.drawImage(original,0,0);
  for(const [x,y] of points){ctx.strokeStyle='#00ffff';ctx.lineWidth=Math.max(2,canvas.width/300);ctx.beginPath();ctx.arc(x,y,canvas.width/85,0,Math.PI*2);ctx.stroke();ctx.beginPath();ctx.moveTo(x-10,y);ctx.lineTo(x+10,y);ctx.moveTo(x,y-10);ctx.lineTo(x,y+10);ctx.stroke();}
  $('count').textContent=`已标记 ${points.length} / 64 个背景点`;
 }
 function invalidate(){clearPreview();message('标记已变化，请重新预览。');draw();controls();}
 $('source').onclick=event=>{
  if(working||!original)return;if(points.length>=64){message('背景标记最多64个点，可先撤销或清空。',true);return;}
  const box=$('source').getBoundingClientRect();
  const x=Math.min(original.naturalWidth-1,Math.max(0,Math.floor((event.clientX-box.left)*original.naturalWidth/box.width)));
  const y=Math.min(original.naturalHeight-1,Math.max(0,Math.floor((event.clientY-box.top)*original.naturalHeight/box.height)));
  if(!points.some(p=>p[0]===x&&p[1]===y)){points.push([x,y]);invalidate();}
 };
 $('undo').onclick=()=>{points.pop();invalidate();};$('clear').onclick=()=>{points=[];invalidate();};
 $('close').onclick=()=>dialog.close();dialog.addEventListener('cancel',event=>{if(working)event.preventDefault();});
 const request=()=>({job:info.job,source_sha256:info.source_sha256,background_points:points.map(p=>[...p])});
 $('run').onclick=async()=>{
  if(working)return;clearPreview();working=true;controls();message('正在复用原图处理，不调用生图服务…');
  try{
   const result=await call('/api/props/recovery-preview',request());
   const bytes=Uint8Array.from(atob(result.image.split(',')[1]),c=>c.charCodeAt(0));
   previewURL=URL.createObjectURL(new Blob([bytes],{type:'image/png'}));
   for(const img of $('preview').querySelectorAll('img')){img.src=previewURL;await img.decode();}
   preview=result;$('preview').hidden=false;message('请对照原图检查是否误删主体、提手与孔洞是否完整；满意后另存为素材。');
  }catch(e){message(e.message,true);}finally{working=false;controls();}
 };
 $('save').onclick=async()=>{
  if(working||!preview)return;working=true;controls();message('正在另存素材…');
  try{const kit=await call('/api/props/recovery-save',{...request(),preview_sha256:preview.preview_sha256});dialog.close();onSave(kit);}
  catch(e){preview=null;message(e.message,true);}finally{working=false;controls();}
 };
 window.StudioPropRecovery={async open(job,api,saved){
  if(working||dialog.open)return;
  call=api;onSave=saved;info=await call('/api/props/recovery-source?id='+encodeURIComponent(job));
  original=new Image();original.src='/api/props/job-image?id='+encodeURIComponent(job)+'&sha256='+info.source_sha256;await original.decode();
  points=[];clearPreview();$('title').textContent='修正背景 · '+info.title;draw();message('点击确认属于背景的空洞，再预览处理结果。原图和失败记录会保留。');controls();dialog.showModal();
 }};
})();

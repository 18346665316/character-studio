'use strict';
/* Shared library annotation UI used by the prop workbench and scene references. */
// Keep existing scene coordinates; the exported reference character is one human high.
window.StudioHumanScale=Object.freeze({sceneUnits:34});
window.StudioSpriteEditor=class {
 constructor(){
  const root=document.createElement('div');root.className='module-workspace sprite-editor-root';
  root.innerHTML=`<dialog id="module-dialog">
 <header class="section-heading"><div><h2>编辑素材 <span id="module-size"></span></h2><p id="editor-status" role="status">调整后保存为素材新版本。</p></div><button id="close-editor" aria-label="关闭素材编辑">关闭</button></header>
 <div class="editor-body">
  <div class="editor-stage"><div class="editor-views" aria-label="预览方式"><button id="view-size" aria-pressed="true">场景大小</button><button id="view-annotation" aria-pressed="false">锚点与碰撞</button><button id="fit-size-preview">适合预览</button></div>
   <div id="annotation-tools" class="module-toolbar" hidden><select id="edit-mode" aria-label="标注工具"><option value="edit">拖动锚点 / 碰撞顶点</option><option value="anchor">点击设置锚点</option><option value="rectangle">拖出矩形碰撞</option><option value="polygon">点击绘制碰撞多边形</option></select><button id="finish-polygon">完成区域</button><button id="undo-point">撤回顶点</button></div>
   <canvas id="module-canvas" width="720" height="480" aria-label="素材场景大小预览"></canvas><p id="canvas-help">拖动右侧滑块，比较素材与地格、测试角色的大小。</p>
  </div>
  <aside><label>名称<input id="edit-title" maxlength="80"></label><label>通行类型<select id="behavior"><option value="passable">可通过</option><option value="blocking">阻挡</option><option value="opening">开口（多块碰撞留出间隙）</option></select></label>
   <section class="size-controls"><h3>场景大小 · 标准人高 = 1</h3><p>主体宽高以标准人高衡量，黄色人物为 1 人高。</p><div class="module-toolbar"><label>主体宽（人高）<input id="subject-width" type="number" min="0.000001" step="any"></label><label>主体高（人高）<input id="subject-height" type="number" min="0.000001" step="any"></label></div><p id="subject-size-help"></p><details><summary>原图比例与画布尺寸</summary><div class="scale-value"><label>比例<input id="world-percent" type="number" min="1" max="10000" step="any" aria-label="素材比例百分比"></label><span>%</span><button id="reset-world-size">重置为 100%</button></div><input id="world-scale-slider" type="range" min="10" max="300" step="1" value="100" aria-label="拖动调整素材大小"><div class="scale-range"><span>缩小</span><span>放大</span></div>
   <div class="module-toolbar"><label>宽<input id="world-width" type="number" min="0.01" step="any"></label><span class="aspect-lock" title="保持宽高比例">↔</span><label>高<input id="world-height" type="number" min="0.01" step="any"></label></div><p>画布宽高等比联动，含图片透明边距。</p><p id="world-scale-label"></p></details></section>
   <section id="annotation-settings" hidden><h3>锚点（原图坐标）</h3><div class="module-toolbar"><label>X<input id="anchor-x" type="number" step="0.5"></label><label>Y<input id="anchor-y" type="number" step="0.5"></label></div><h3>碰撞区域</h3><div id="polygon-list"></div><button id="clear-polygons">清空碰撞</button><p>用多块碰撞留出门洞。</p></section>
  </aside>
 </div>
 <footer class="editor-footer"><div><strong id="editor-save-state">已保存</strong><p>保存为新版本；其他场景保留原版本。</p></div><button id="save-module">保存素材版本</button></footer>
</dialog>`;document.body.append(root);
  this.root=root;this.$=id=>root.querySelector('#'+id);this.dialog=this.$('module-dialog');this.dirty=false;this.polys=[];this.pending=[];this.anchor=[0,0];
  this.view='size';
  this.$('view-size').onclick=()=>this.setView('size');this.$('view-annotation').onclick=()=>this.setView('annotation');
  this.$('fit-size-preview').onclick=()=>{this.fitPreview();this.draw();};
  this.$('edit-mode').onchange=()=>this.draw();
  this.$('close-editor').onclick=()=>this.close();this.dialog.oncancel=e=>{e.preventDefault();this.close();};
  this.$('save-module').onclick=()=>this.save();
  for(const [id,axis] of [['world-width','width'],['world-height','height'],['subject-width','subjectWidth'],['subject-height','subjectHeight'],['world-percent',null],['world-scale-slider',null]]){
   this.$(id).oninput=()=>{const scale=Number(this.$(id).value)*(id.startsWith('subject-')?StudioHumanScale.sceneUnits:1)/(axis?(this.subjectBounds?.[axis]??this.image[axis]):100);if(!this.$(id).value||!Number.isFinite(scale)||scale<.01||scale>100){this.$(id).setCustomValidity('比例须在 1%–10000% 之间');this.$(id).setAttribute('aria-invalid','true');return;}
    this.setScale(scale,id);};
   this.$(id).onchange=()=>{if(!this.$(id).checkValidity())this.$(id).reportValidity();};
  }
  this.$('reset-world-size').onclick=()=>this.setScale(1);
  for(const id of ['anchor-x','anchor-y'])this.$(id).onchange=()=>{this.setAnchor([Number(this.$('anchor-x').value),Number(this.$('anchor-y').value)]);this.draw();};
  for(const id of ['edit-title','behavior'])this.$(id).oninput=()=>{this.dirty=true;this.remember();};
  this.$('finish-polygon').onclick=()=>{if(this.pending.length<3)return this.message('至少标注三个顶点。',true);this.dirty=true;this.polys.push(this.pending);this.pending=[];this.draw();};
  this.$('undo-point').onclick=()=>{this.pending.pop();this.dirty=true;this.draw();};
  this.$('clear-polygons').onclick=()=>{this.polys=[];this.pending=[];this.dirty=true;this.draw();};
  const c=this.$('module-canvas');
  c.onpointerdown=e=>{if(!this.image||this.view==='size'||e.button!==0)return;c.setPointerCapture(e.pointerId);const p=this.point(e),t=this.transform(),mode=this.$('edit-mode').value;
   if(mode==='anchor'){this.setAnchor(p);this.draw();return;}
   if(mode==='polygon'){this.pending.push([p[0]-this.anchor[0],p[1]-this.anchor[1]]);this.dirty=true;this.draw();return;}
   if(mode==='rectangle'){this.drag={rectangle:true,start:p,end:p};return;}
   if(Math.hypot(p[0]-this.anchor[0],p[1]-this.anchor[1])<12/t.s){this.drag={anchor:true};return;}
   for(let i=0;i<this.polys.length;i++)for(let j=0;j<this.polys[i].length;j++)if(Math.hypot(p[0]-this.anchor[0]-this.polys[i][j][0],p[1]-this.anchor[1]-this.polys[i][j][1])<12/t.s){this.drag={poly:i,point:j};return;}
  };
  c.onpointermove=e=>{if(!this.drag)return;const p=this.point(e);if(this.drag.rectangle)this.drag.end=p;else if(this.drag.anchor)this.setAnchor(p);else{this.polys[this.drag.poly][this.drag.point]=[p[0]-this.anchor[0],p[1]-this.anchor[1]];this.dirty=true;}this.draw();};
  c.onpointerup=()=>{const d=this.drag;if(d?.rectangle){const a=d.start,b=d.end;if(Math.abs(a[0]-b[0])>=2&&Math.abs(a[1]-b[1])>=2){const x=Math.min(a[0],b[0])-this.anchor[0],y=Math.min(a[1],b[1])-this.anchor[1],w=Math.abs(a[0]-b[0]),h=Math.abs(a[1]-b[1]);this.polys.push([[x,y],[x+w,y],[x+w,y+h],[x,y+h]]);this.dirty=true;if(this.$('behavior').value==='passable')this.$('behavior').value='blocking';}}this.drag=null;this.draw();};
  c.onpointercancel=()=>{this.drag=null;this.draw();};
  window.addEventListener('keydown',e=>{if(!this.dialog.open)return;if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='s'){e.preventDefault();e.target.blur();this.save();}else if(e.key==='Enter'&&this.pending.length&&!/INPUT|SELECT/.test(e.target.tagName)){e.preventDefault();this.$('finish-polygon').click();}});
  window.addEventListener('beforeunload',e=>{if(this.dirty){e.preventDefault();e.returnValue='';}});
 }
 load(config,image,onSave){this.key=config.source?.id?'studio.sprite-settings.'+config.source.id:null;let draft=null;try{draft=this.key?JSON.parse(localStorage.getItem(this.key)):null;}catch{}this.config=structuredClone(config);config=draft||config;this.image=image;this.measureSubject(image);for(const id of ['world-width','world-height','subject-width','subject-height','world-percent','world-scale-slider']){this.$(id).setCustomValidity('');this.$(id).removeAttribute('aria-invalid');}this.worldScale=config.world_scale??1;this.syncSize();this.fitPreview();this.onSave=onSave;this.polys=structuredClone(config.polygons);this.pending=[];this.anchor=[...config.anchor];this.dirty=!!draft;this.$('edit-title').value=config.title;this.$('behavior').value=config.behavior;this.syncAnchor();this.$('module-size').textContent=image.width+' × '+image.height+'px';this.draw();}
 open(config,image,onSave){if(config)this.load(config,image,onSave);if(!this.dialog.open)this.dialog.showModal();this.$('edit-mode').value='edit';this.setView('size');this.message('拖动滑块可即时比较大小；切换“锚点与碰撞”进行原图标注。');this.draw();}
 remember(){this.$('editor-save-state').textContent=this.dirty?'有未保存的修改':'已保存';if(this.key&&this.dirty){try{localStorage.setItem(this.key,JSON.stringify({title:this.$('edit-title').value,anchor:this.anchor,behavior:this.$('behavior').value,polygons:this.polys,world_scale:this.worldScale}));}catch{}}}
 close(){if(this.saving)return;if(this.dirty&&!confirm('放弃尚未保存的素材设置？'))return;if(this.key)localStorage.removeItem(this.key);this.dirty=false;this.dialog.close();}
 message(text,error=false){this.$('editor-status').textContent=text;this.$('editor-status').style.color=error?'#ae382a':'#687c70';}
 async save(){if(this.saving)return;try{for(const id of ['world-width','world-height','subject-width','subject-height','world-percent'])if(!this.$(id).checkValidity()){this.$(id).reportValidity();throw Error('请先修正尺寸输入，或点击重置。');}if(this.pending.length)throw Error('请先完成当前碰撞区域，或撤回顶点');this.saving=true;this.message('正在保存素材版本…');const previousKey=this.key;this.$('save-module').disabled=true;
   const config={title:this.$('edit-title').value,anchor:this.anchor,behavior:this.$('behavior').value,polygons:this.polys,world_scale:this.worldScale};
   const result=await this.onSave(structuredClone(config));if(previousKey)localStorage.removeItem(previousKey);this.load(result||config,this.image,this.onSave);this.message('模块设置已保存为素材库新版本。');
  }catch(e){this.message(e.message,true);}finally{this.saving=false;this.$('save-module').disabled=false;}}
 setScale(value,source){this.worldScale=value;this.dirty=true;for(const id of ['world-width','world-height','subject-width','subject-height','world-percent','world-scale-slider']){this.$(id).setCustomValidity('');this.$(id).removeAttribute('aria-invalid');}this.syncSize(source);this.draw();}
 measureSubject(image){const c=document.createElement('canvas');c.width=image.width;c.height=image.height;const ctx=c.getContext('2d',{willReadFrequently:true});ctx.drawImage(image,0,0);const data=ctx.getImageData(0,0,c.width,c.height).data;let left=c.width,right=-1,top=c.height,bottom=-1;
  for(let y=0;y<c.height;y++)for(let x=0;x<c.width;x++)if(data[(y*c.width+x)*4+3]){left=Math.min(left,x);right=Math.max(right,x);top=Math.min(top,y);bottom=Math.max(bottom,y);}
  this.subjectBounds=right<left?null:{subjectWidth:right-left+1,subjectHeight:bottom-top+1};
  for(const id of ['subject-width','subject-height'])this.$(id).disabled=!this.subjectBounds;
  this.$('subject-size-help').textContent=this.subjectBounds?'按非透明像素范围计算，1 表示一个标准人高；宽高等比联动，不改变原图。':'图片完全透明，无法计算主体尺寸；可使用画布宽高。';
 }
 syncSize(source){for(const [id,key] of [['subject-width','subjectWidth'],['subject-height','subjectHeight']])if(id!==source)this.$(id).value=this.subjectBounds?Number((this.subjectBounds[key]*this.worldScale/StudioHumanScale.sceneUnits).toFixed(6)):'';for(const [id,axis] of [['world-width','width'],['world-height','height']])if(id!==source)this.$(id).value=Number((this.image[axis]*this.worldScale).toFixed(6));if(source!=='world-percent')this.$('world-percent').value=Number((this.worldScale*100).toFixed(4));const slider=this.$('world-scale-slider');slider.min=Math.min(10,this.worldScale*100);slider.max=Math.max(300,Math.ceil(this.worldScale*100));slider.value=this.worldScale*100;this.$('world-scale-label').textContent='像素表示原图清晰度；标准人高 = 1，内部换算不改变已有素材大小。';}
 setView(view){this.view=view;const edit=view==='annotation';this.$('view-size').setAttribute('aria-pressed',String(!edit));this.$('view-annotation').setAttribute('aria-pressed',String(edit));this.$('annotation-tools').hidden=this.$('annotation-settings').hidden=edit?false:true;this.$('fit-size-preview').hidden=edit;this.$('canvas-help').textContent=edit?'拖动绿色十字调整锚点、红色顶点调整碰撞。这里始终使用原图坐标。':'拖动滑块即时预览；地格和黄色角色保持固定大小。';this.$('module-canvas').setAttribute('aria-label',edit?'模块锚点与碰撞编辑':'素材场景大小预览');this.draw();}
 fitPreview(){if(!this.image)return;const c=this.$('module-canvas'),im=this.image,scale=this.worldScale;this.previewZoom=Math.min((c.width-200)/Math.max(im.width*scale,128),(c.height-110)/Math.max(im.height*scale,96),2);this.previewScale=scale;}
 drawSize(ctx,c){const s=this.previewZoom||1,im=this.image,k=this.worldScale,a=this.anchor;
  const x=c.width*.43+(a[0]-im.width/2)*this.previewScale*s,y=c.height*.48+(a[1]-im.height/2)*this.previewScale*s;
  ctx.save();ctx.translate(x,y);ctx.scale(s,s);ctx.strokeStyle='#a3c9b72e';ctx.lineWidth=1/s;ctx.beginPath();
  const n=Math.ceil((c.width+c.height)/s/64)+4;for(let i=-n;i<=n;i++){ctx.moveTo(i*64-n*64,i*32+n*32);ctx.lineTo(i*64+n*64,i*32-n*32);ctx.moveTo(-i*64-n*64,i*32-n*32);ctx.lineTo(-i*64+n*64,i*32+n*32);}ctx.stroke();
  ctx.drawImage(im,-a[0]*k,-a[1]*k,im.width*k,im.height*k);
  for(const poly of this.polys)this.polygon(ctx,poly.map(p=>[p[0]*k,p[1]*k]),'#ff624a33');
  ctx.strokeStyle='#7affa4';ctx.beginPath();ctx.moveTo(-7/s,0);ctx.lineTo(7/s,0);ctx.moveTo(0,-7/s);ctx.lineTo(0,7/s);ctx.stroke();ctx.restore();
  const rx=c.width-75,ry=y;ctx.save();ctx.translate(rx,ry);ctx.scale(s,s);ctx.beginPath();[[-8,0],[-8,-StudioHumanScale.sceneUnits*24/34],[0,-StudioHumanScale.sceneUnits],[8,-StudioHumanScale.sceneUnits*24/34],[8,0]].forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.closePath();ctx.fillStyle='#f5ce72';ctx.fill();ctx.restore();
  ctx.fillStyle='#c8d8cd';ctx.font='12px sans-serif';ctx.fillText('标准人高 = 1',rx-35,ry+22);ctx.fillText('128 × 64 地格 · 大小对比',18,c.height-18);
  ctx.fillStyle='#eef5ed';ctx.fillText((this.subjectBounds?Number((this.subjectBounds.subjectWidth*k/StudioHumanScale.sceneUnits).toFixed(3))+' × '+Number((this.subjectBounds.subjectHeight*k/StudioHumanScale.sceneUnits).toFixed(3))+' 人高（主体）':'无可见主体'),18,26);
 }
 syncAnchor(){this.$('anchor-x').value=this.anchor[0];this.$('anchor-y').value=this.anchor[1];}
 setAnchor(value){const old=this.anchor;this.anchor=value;this.polys=this.polys.map(poly=>poly.map(p=>[p[0]+old[0]-value[0],p[1]+old[1]-value[1]]));this.pending=this.pending.map(p=>[p[0]+old[0]-value[0],p[1]+old[1]-value[1]]);this.syncAnchor();this.dirty=true;}
 transform(){const c=this.$('module-canvas'),im=this.image;if(!im)return {s:1,x:0,y:0};const s=Math.min((c.width-80)/im.width,(c.height-80)/im.height);return {s,x:(c.width-im.width*s)/2,y:(c.height-im.height*s)/2};}
 point(e){const c=this.$('module-canvas'),r=c.getBoundingClientRect(),t=this.transform();return [Math.round(((e.clientX-r.left)*c.width/r.width-t.x)/t.s),Math.round(((e.clientY-r.top)*c.height/r.height-t.y)/t.s)];}
 polygon(ctx,points,color){if(!points.length)return;ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.closePath();ctx.fillStyle=color;ctx.fill();ctx.strokeStyle='#ff9a7c';ctx.stroke();}
 draw(){this.remember();const c=this.$('module-canvas'),ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);if(!this.image)return;if(this.view==='size'){this.drawSize(ctx,c);this.renderPolygons();return;}const t=this.transform(),a=this.anchor;ctx.save();ctx.translate(t.x,t.y);ctx.scale(t.s,t.s);ctx.drawImage(this.image,0,0);ctx.lineWidth=1.5/t.s;
  for(const poly of this.polys){this.polygon(ctx,poly.map(p=>[p[0]+a[0],p[1]+a[1]]),'#ff624a55');for(const p of poly){ctx.beginPath();ctx.arc(p[0]+a[0],p[1]+a[1],4/t.s,0,Math.PI*2);ctx.fillStyle='#ffad96';ctx.fill();}}
  if(this.pending.length){ctx.beginPath();this.pending.forEach((p,i)=>i?ctx.lineTo(p[0]+a[0],p[1]+a[1]):ctx.moveTo(p[0]+a[0],p[1]+a[1]));ctx.strokeStyle='#ffe28c';ctx.stroke();for(const p of this.pending){ctx.fillStyle='#ffe28c';ctx.fillRect(p[0]+a[0]-3/t.s,p[1]+a[1]-3/t.s,6/t.s,6/t.s);}}
  if(this.drag?.rectangle){const d=this.drag;this.polygon(ctx,[d.start,[d.end[0],d.start[1]],d.end,[d.start[0],d.end[1]]],'#ffce7955');}
  ctx.strokeStyle='#7affa4';ctx.beginPath();ctx.moveTo(a[0]-10/t.s,a[1]);ctx.lineTo(a[0]+10/t.s,a[1]);ctx.moveTo(a[0],a[1]-10/t.s);ctx.lineTo(a[0],a[1]+10/t.s);ctx.stroke();ctx.restore();
  this.renderPolygons();
 }
 renderPolygons(){this.$('polygon-list').replaceChildren(...this.polys.map((poly,i)=>{const row=document.createElement('div');row.className='polygon-row';const text=document.createElement('span');text.textContent=`区域 ${i+1} · ${poly.length} 个顶点`;const button=document.createElement('button');button.textContent='删除';button.onclick=()=>{this.polys.splice(i,1);this.dirty=true;this.draw();};row.append(text,button);return row;}));
 }
};

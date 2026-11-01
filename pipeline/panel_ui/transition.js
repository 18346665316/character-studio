'use strict';
(() => {
 const $=id=>document.getElementById(id);
 let state,current,atlas,selected,busy=false;
 const node=(tag,value)=>{const n=document.createElement(tag);n.textContent=value;return n;};
 function status(message,error=false){$('transition-status').textContent=message;$('transition-status').className=error?'terrain-hint terrain-error':'terrain-hint';}
 async function api(path,data){const response=await fetch(path,data?{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Token':state.token},body:JSON.stringify(data)}:{});const result=await response.json();if(!response.ok)throw Error(result.error||'请求失败');return result;}
 function update(){
 const base=state?.kits.find(k=>k.id===$('base-kit').value),overlay=state?.kits.find(k=>k.id===$('overlay-kit').value);
 const same=base?.id===overlay?.id,mismatch=base&&overlay&&base.tile_size!==overlay.tile_size;
 $('transition-generate').disabled=busy||!base||!overlay||same||mismatch;
 if(base&&overlay&&!mismatch){$('transition-size').value=String(base.tile_size);}
 for(const option of $('transition-size').options)option.disabled=!base||!overlay||mismatch||Number(option.value)!==base.tile_size;
 $('transition-input-note').textContent=mismatch?'来源地表尺寸不一致。请先在地面与道路页重新制作相同尺寸的套件。':base&&overlay?'按来源成品尺寸 '+base.tile_size+'px 生成，保留原地表像素与变化组。':'';
 }
 $('base-kit').onchange=$('overlay-kit').onchange=update;
 function gallery(){if(!current||!atlas)return;const v=Number($('transition-variant').value),s=current.tile_size;const entries=current.tiles.filter(t=>t.variant===v);$('transition-gallery').replaceChildren();for(const tile of entries){const fig=document.createElement('figure'),canvas=document.createElement('canvas');canvas.width=canvas.height=s;canvas.getContext('2d').drawImage(atlas,tile.atlas_cell[0]*s,tile.atlas_cell[1]*s,s,s,0,0,s,s);fig.append(canvas,node('figcaption',tile.corners===0?'第一地表':tile.corners===15?'第二地表':'过渡 '+tile.corners));$('transition-gallery').append(fig);}}
 $('transition-variant').onchange=gallery;
 async function show(kit){if(!kit)return;selected=kit.id;const image=new Image(),base='/transition-asset/'+encodeURIComponent(kit.id)+'/';image.src=base+'atlas.png';await image.decode();if(selected!==kit.id)return;current=kit;atlas=image;$('transition-result-title').textContent=kit.title;$('transition-history').value=kit.id;$('transition-empty').hidden=true;$('transition-result').hidden=false;$('transition-preview').src=base+'preview.png';$('transition-download').href=base+'kit.zip';$('transition-download').hidden=kit.integrity?.passed===false;$('transition-validation').classList.toggle('terrain-error',kit.integrity?.passed===false);$('transition-validation').textContent=kit.integrity?.passed===false?'完整性检查失败：'+kit.integrity.errors.join('；'):kit.validation.matching_edge_pairs+' 对连接边缘检查通过 · 最大通道差 '+kit.validation.max_channel_difference;
 $('transition-meta').textContent=`${kit.transition_mode==='shoreline'?'静态水岸':'普通地表'} · ${kit.tile_size}px · ${kit.variants}组变化 · ${kit.tiles.length}个素材块 · 来源：${kit.sources.map(s=>state.kits.find(k=>k.id===s.kit)?.title||s.kit).join(' / ')}`;$('transition-variant').replaceChildren();for(let i=0;i<kit.variants;i++){const option=node('option','变化组 '+(i+1));option.value=i;$('transition-variant').append(option);}gallery();}
 $('transition-history').onchange=()=>show(state.transitions.find(k=>k.id===$('transition-history').value)).catch(e=>status(e.message,true));
 async function refresh(){state=await api('/api/terrain/state');state.kits=state.kits.filter(k=>k.integrity?.passed!==false);for(const id of ['base-kit','overlay-kit']){const previous=$(id).value;$(id).replaceChildren();for(const kit of state.kits){const option=node('option',kit.title+' · '+kit.id);option.value=kit.id;$(id).append(option);}if(previous&&state.kits.some(k=>k.id===previous))$(id).value=previous;}
 if($('base-kit').value===$('overlay-kit').value&&state.kits.length>1)$('overlay-kit').selectedIndex=1;
 $('transition-history').replaceChildren();for(const kit of state.transitions){const option=node('option',kit.title+' · '+kit.id);option.value=kit.id;$('transition-history').append(option);}$('transition-history').hidden=!state.transitions.length;if(state.transitions.length)await show(state.transitions.find(k=>k.id===selected)||state.transitions[0]);update();}
 $('transition-form').onsubmit=async event=>{event.preventDefault();if(busy||$('transition-generate').disabled)return;busy=true;update();status('正在制作边缘素材并检查连接…');try{const kit=await api('/api/terrain/transition',{title:$('transition-title').value,base_kit:$('base-kit').value,overlay_kit:$('overlay-kit').value,tile_size:Number($('transition-size').value),transition_mode:$('transition-mode').value});selected=kit.id;await refresh();status('套件已生成，可查看并下载。请复核材质风格与边界效果。');}catch(e){status(e.message,true);}finally{busy=false;update();}};
 refresh().then(()=>status(state.kits.length<2?'请先在“地面与道路”中生成至少两套不同地表。':'选择两种地表生成独立素材包，已有成果保留。')).catch(e=>status(e.message,true));
})();

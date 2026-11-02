'use strict';
(() => {
 const path=location.pathname,q=new URLSearchParams(location.search),hub=path==='/'||path==='/index.html';
 const mode=q.has('task')?'tasks':hub?(q.get('view')||'library'):(q.has('kit')||path==='/characters.html'&&!q.has('create')?'library':'create');
 const link=(label,url,current)=>{const a=document.createElement('a');a.textContent=label;a.href=url;if(current)a.setAttribute('aria-current','page');return a;};
 const nav=document.getElementById('studio-navigation');
 nav.className='studio-nav';nav.append(link('S / STUDIO','/',false));
 for(const [id,title,url] of [['library','素材库','/'],['create','制作素材','/?view=create'],['tasks','生产任务','/?view=tasks']])nav.append(link(title,url,mode===id));

 const service=document.createElement('div');service.className='studio-provider';
 const serviceLabel=document.createElement('label');serviceLabel.htmlFor='studio-image-provider';serviceLabel.textContent='图片服务';
 const serviceSelect=document.createElement('select');serviceSelect.id='studio-image-provider';serviceSelect.disabled=true;
 const serviceApply=document.createElement('button');serviceApply.type='button';serviceApply.textContent='切换';serviceApply.disabled=true;
 const serviceMessage=document.createElement('span');serviceMessage.setAttribute('role','status');serviceMessage.className='studio-provider-message';
 service.append(serviceLabel,serviceSelect,serviceApply,serviceMessage);nav.append(service);
 let providerState,switching=false;
 async function providerRequest(data){const response=await fetch('/api/image-provider',data?{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Token':providerState.token},body:JSON.stringify(data)}:{});const value=await response.json();if(!response.ok)throw Error(value.error||'图片服务读取失败');return value;}
 function providerControls(){serviceSelect.disabled=switching||providerState?.environment_override;serviceApply.disabled=switching||providerState?.environment_override||!providerState||serviceSelect.value===providerState.current||!providerState.choices.find(c=>c.id===serviceSelect.value)?.configured;}
 async function loadProvider(){try{providerState=await providerRequest();serviceSelect.replaceChildren();for(const choice of providerState.choices){const option=document.createElement('option');option.value=choice.id;option.textContent=choice.label+' · '+choice.model+(choice.configured?'':'（未配置）');option.disabled=!choice.configured;serviceSelect.append(option);}serviceSelect.value=providerState.current;serviceMessage.textContent=providerState.environment_override?'由启动环境指定':'';providerControls();}catch(error){serviceMessage.textContent=error.message;}}
 serviceSelect.onchange=()=>{serviceMessage.textContent='切换后用于本项目后续生图';providerControls();};
 serviceApply.onclick=async()=>{if(switching||!providerState)return;switching=true;providerControls();try{const result=await providerRequest({provider:serviceSelect.value,revision:providerState.revision});providerState={...result,token:providerState.token};serviceSelect.value=result.current;serviceMessage.textContent='已切换';window.dispatchEvent(new CustomEvent('studio-image-provider-changed',{detail:result}));}catch(error){await loadProvider();serviceMessage.textContent=error.message;}finally{switching=false;providerControls();}};
 loadProvider();window.addEventListener('focus',()=>{if(!switching)loadProvider();});
 if(hub)return;
 const surfaces=['/terrain.html','/transition.html','/water.html','/water-shore.html'];
 const group=surfaces.includes(path)?'地表':['/buildings.html','/building-structure.html'].includes(path)?'建筑':path==='/props.html'?'物件':path==='/components.html'?'连接构件':'人物';
 const sub=document.createElement('nav');sub.className='studio-subnav';sub.setAttribute('aria-label',group+'导航');
 sub.append(link('← '+({library:'素材库',create:'制作素材',tasks:'生产任务'}[mode]),'/?'+(mode==='library'?'':'view='+mode+'&')+'category='+encodeURIComponent(group),false));
 if(group==='地表')for(const [title,url] of [['地面与道路','/terrain.html'],['地表过渡','/transition.html'],['水面','/water.html'],['水岸','/water-shore.html']])sub.append(link(title,url,path===url));
 else {const label=document.createElement('span');label.textContent=group+(group==='连接构件'?' / 围栏':'');sub.append(label);}
 nav.after(sub);
 if(q.has('task')){
  const identity=q.get('task');
  const observer=new MutationObserver(()=>{
   for(const id of ['terrain-jobs','component-jobs','prop-jobs','jobs']){
    const jobs=document.getElementById(id);if(!jobs)continue;
    const match=[...jobs.children].find(row=>row.dataset.taskId===identity||row.textContent.includes(identity));
    if(!match)continue;
    const details=jobs.closest('details');if(details)details.open=true;
    match.classList.add('studio-task-focus');match.scrollIntoView({block:'center'});observer.disconnect();return;
   }
  });
  observer.observe(document.body,{childList:true,subtree:true});
 }
})();

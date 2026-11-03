'use strict';
(() => {
 const path=location.pathname,q=new URLSearchParams(location.search),hub=path==='/'||path==='/index.html';
 const pid=q.get('project')||localStorage.getItem('studio.project'),iid=q.get('item');
 const mode=hub?(['review','projects'].includes(q.get('view'))?q.get('view'):'production'):(path==='/module-scenes.html'?'modules':'production');
 const projectURL=view=>pid?'/?project='+encodeURIComponent(pid)+'&view='+view:'/?view=projects';
 const link=(label,url,current)=>{const a=document.createElement('a');a.textContent=label;a.href=url;if(current)a.setAttribute('aria-current','page');return a;};
 window.StudioDelete=async target=>{
  const dialog=document.createElement('dialog');dialog.className='studio-delete-dialog';
  const title=document.createElement('h2');title.textContent='删除';
  const message=document.createElement('p');message.setAttribute('role','status');message.textContent='正在检查…';
  const uses=document.createElement('ul'),actions=document.createElement('div');actions.className='project-actions';
  const cancel=document.createElement('button');cancel.type='button';cancel.textContent='取消';cancel.onclick=()=>dialog.close();
  const remove=document.createElement('button');remove.type='button';remove.className='danger';remove.textContent='删除';remove.disabled=true;
  actions.append(cancel,remove);dialog.append(title,message,uses,actions);document.body.append(dialog);
  let deleted=false;const closed=new Promise(resolve=>{dialog.onclose=()=>{dialog.remove();resolve(deleted);};});dialog.showModal();
  try{
   const response=await fetch('/api/delete/inspect?'+new URLSearchParams(target)),info=await response.json();
   if(!response.ok)throw Error(info.error||'无法读取删除对象');
   if(!dialog.isConnected)return closed;
   title.textContent='删除「'+info.title+'」？';
   if(info.references.length){message.textContent='正在被以下内容使用。请先移除引用，再删除素材。';for(const text of info.references){const item=document.createElement('li');item.textContent=text;uses.append(item);}remove.hidden=true;cancel.textContent='关闭';}
   else{message.textContent=target.kind==='project'?'将删除项目及其本机文件，共用素材保留。此操作无法撤销。':target.kind==='item'?'将从项目移除这项需求，素材库中的成果保留。':target.kind==='scene'?'将删除这个验证场景，素材库中的成果保留。':'将删除这份素材及其附属文件。此操作无法撤销。';remove.disabled=false;}
   remove.onclick=async()=>{
    remove.disabled=true;cancel.disabled=true;dialog.oncancel=event=>event.preventDefault();
    try{const response=await fetch('/api/delete',{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Token':info.token},body:JSON.stringify({...target,fingerprint:info.fingerprint})});const result=await response.json();if(!response.ok)throw Error(result.error||'删除失败');deleted=true;dialog.close();}
    catch(error){message.textContent=error.message;cancel.disabled=false;cancel.textContent='关闭';remove.hidden=true;dialog.oncancel=null;}
   };
  }catch(error){message.textContent=error.message;cancel.textContent='关闭';remove.hidden=true;}
  return closed;
 };
 const nav=document.getElementById('studio-navigation');
 nav.className='studio-nav';nav.append(link('S / STUDIO','/?view=projects',false));
 for(const [id,title] of [['projects','素材项目'],['production','素材']]){const a=link(title,id==='projects'?'/?view=projects':projectURL(id),mode===id);a.dataset.studioView=id;nav.append(a);}
 const utilities=document.createElement('details');utilities.className='studio-tools';
 const utilitiesTitle=document.createElement('summary');utilitiesTitle.textContent='验证工具';
 const toolsMenu=document.createElement('div');toolsMenu.className='studio-tools-menu';const compositionLink=link('组合预览',projectURL('review'),mode==='review');compositionLink.dataset.studioView='review';toolsMenu.append(compositionLink,link('模块场景','/module-scenes.html',path==='/module-scenes.html'));utilities.append(utilitiesTitle,toolsMenu);nav.append(utilities);
 window.StudioProjectURL=url=>{const u=new URL(url,location.origin);if(pid&&iid){u.searchParams.set('project',pid);u.searchParams.set('item',iid);}return u.pathname+u.search;};
 const service=document.createElement('div');service.className='studio-provider';
 const serviceLabel=document.createElement('label');serviceLabel.htmlFor='studio-image-provider';serviceLabel.textContent='图片服务';
 const serviceSelect=document.createElement('select');serviceSelect.id='studio-image-provider';serviceSelect.disabled=true;
 const serviceApply=document.createElement('button');serviceApply.type='button';serviceApply.textContent='切换';serviceApply.disabled=true;
 const serviceMessage=document.createElement('span');serviceMessage.setAttribute('role','status');serviceMessage.className='studio-provider-message';
 service.append(serviceLabel,serviceSelect,serviceApply,serviceMessage);const settings=document.createElement('details');settings.className='studio-settings';const settingsTitle=document.createElement('summary');settingsTitle.textContent='Studio 设置';settings.append(settingsTitle,service);nav.append(settings);
 let providerState,switching=false;
 async function providerRequest(data){const response=await fetch('/api/image-provider',data?{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Token':providerState.token},body:JSON.stringify(data)}:{});const value=await response.json();if(!response.ok)throw Error(value.error||'图片服务读取失败');return value;}
 function providerControls(){serviceSelect.disabled=switching||providerState?.environment_override;serviceApply.disabled=switching||providerState?.environment_override||!providerState||serviceSelect.value===providerState.current||!providerState.choices.find(c=>c.id===serviceSelect.value)?.configured;}
 async function loadProvider(){try{providerState=await providerRequest();serviceSelect.replaceChildren();for(const choice of providerState.choices){const option=document.createElement('option');option.value=choice.id;option.textContent=choice.label+' · '+choice.model+(choice.configured?'':'（未配置）');option.disabled=!choice.configured;serviceSelect.append(option);}serviceSelect.value=providerState.current;serviceMessage.textContent=providerState.environment_override?'由启动环境指定':'';providerControls();}catch(error){serviceMessage.textContent=error.message;}}
 serviceSelect.onchange=()=>{serviceMessage.textContent='切换后用于 Studio 后续生图';providerControls();};
 serviceApply.onclick=async()=>{if(switching||!providerState)return;switching=true;providerControls();try{const result=await providerRequest({provider:serviceSelect.value,revision:providerState.revision});providerState={...result,token:providerState.token};serviceSelect.value=result.current;serviceMessage.textContent='已切换';window.dispatchEvent(new CustomEvent('studio-image-provider-changed',{detail:result}));}catch(error){await loadProvider();serviceMessage.textContent=error.message;}finally{switching=false;providerControls();}};
 loadProvider();window.addEventListener('focus',()=>{if(!switching)loadProvider();});
 const family=({'/props.html':'prop','/components.html':'component','/buildings.html':'building','/transition.html':'transition','/water-shore.html':'transition','/terrain.html':'terrain','/water.html':'terrain'})[path];
 if(family&&q.has('kit')){
  let identity=q.get('kit');const tools=document.createElement('div');tools.className='studio-asset-management';
  const remove=document.createElement('button');remove.type='button';remove.className='danger';remove.textContent='删除素材';
  remove.onclick=async()=>{if(await window.StudioDelete({kind:'asset',family,id:identity}))location.assign(pid?projectURL('production'):path);};
  tools.append(remove);nav.after(tools);document.addEventListener('studio:asset',event=>{if(event.detail?.id)identity=event.detail.id;});
 }
 if(hub)return;
 const sub=document.createElement('nav');sub.className='studio-subnav';sub.setAttribute('aria-label','项目生产导航');
 sub.append(link('← 返回素材清单',projectURL('production'),false));nav.after(sub);
 if(pid&&iid){document.body.classList.add('project-workbench');
  let projectInfo;
  const ready=fetch('/api/projects/state?project='+encodeURIComponent(pid)).then(async r=>{const s=await r.json();if(!r.ok)throw Error(s.error);const p=s.selected,entry=p.items.find(i=>i.id===iid);if(!entry)throw Error('素材清单项不存在');projectInfo={p,entry,current:s.current?.[iid]};
   sub.append(document.createTextNode(p.title+' / '+entry.title));
   const banner=document.createElement('section');banner.className='studio-project-context';const title=document.createElement('strong');title.textContent=entry.title.split('｜')[0].trim();const shared=document.createElement('details'),summary=document.createElement('summary');summary.textContent='项目风格与基准';const note=document.createElement('p');note.textContent=[p.baseline.style,p.baseline.palette,p.baseline.lighting,p.baseline.camera_rules,p.baseline.orientation_rules].filter(Boolean).join('。');shared.append(summary,note,link('修改共同基准',projectURL('production'),false));banner.append(title,shared);sub.after(banner);
   if(!q.has('task')&&!q.has('kit')){const propView=document.getElementById('prop-projection');if(propView&&[...propView.options].some(o=>o.value===p.baseline.view)){propView.value=p.baseline.view;propView.disabled=true;}const templateView=document.getElementById('template-view');if(templateView&&[...templateView.options].some(o=>o.value===p.baseline.view))templateView.value=p.baseline.view;}
   const appearance=document.getElementById('building-appearance');if(appearance&&!q.has('task')&&!q.has('kit')){appearance.value=[p.baseline.style,p.baseline.palette,p.baseline.lighting].filter(Boolean).join('。');appearance.readOnly=true;appearance.dispatchEvent(new Event('input',{bubbles:true}));}
   if(!q.has('task')&&!q.has('kit'))for(const [id,value]of [['template-name',entry.title],['template-description',[p.baseline.camera_rules,p.baseline.orientation_rules,entry.description].filter(Boolean).join('\n')],['building-title',entry.title],['prop-title',entry.title],['kit-title',entry.title],['fence-title',entry.title],['prop-description',entry.description],['description',entry.description],['component-description',entry.description]]){const input=document.getElementById(id);if(input&&value){input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));}}
   document.addEventListener('click',event=>{const a=event.target.closest('a[href]');if(!a)return;const u=new URL(a.href,location.origin);if(u.origin===location.origin&&/\.html$/.test(u.pathname)){u.searchParams.set('project',pid);u.searchParams.set('item',iid);a.href=u.pathname+u.search;}});
   return projectInfo;
  });
  window.StudioProjectReady=ready;
  // Saving changes to a project material keeps its reference on the edited output.
  // Generation is resolved from the associated task and needs no separate choice.
  let materialUpdates=Promise.resolve(),editingId=q.get('kit');
  document.addEventListener('studio:asset',event=>{
   const asset=event.detail;if(!asset?.id||!editingId)return;
   materialUpdates=materialUpdates.then(async()=>{
    await ready;
    if(asset.id===editingId||projectInfo.current?.id!==editingId)return;
    const response=await fetch('/api/projects/state?project='+encodeURIComponent(pid)),latest=await response.json();
    if(!response.ok)throw Error(latest.error||'项目读取失败');
    if(latest.current?.[iid]?.id!==editingId)return;
    const saved=await fetch('/api/projects/change',{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Token':latest.token},body:JSON.stringify({action:'set_asset',project:pid,revision:latest.selected.revision,item:iid,asset:asset.id})});
    const result=await saved.json();if(!saved.ok)throw Error(result.error||'素材关联更新失败');
    editingId=asset.id;projectInfo.current=asset;
   }).catch(error=>{let warning=sub.querySelector('[role=status]');if(!warning){warning=document.createElement('span');warning.setAttribute('role','status');warning.className='hub-error';sub.append(warning);}warning.textContent=error.message;});
  });
  const originalFetch=window.fetch.bind(window);
  const routes=new Set(['/api/buildings/prepare','/api/terrain/generate','/api/props/generate','/api/components/generate','/api/tasks','/api/terrain/transition']);
  window.fetch=async(resource,options)=>{const url=new URL(typeof resource==='string'?resource:resource.url,location.origin);if(url.origin===location.origin&&routes.has(url.pathname)&&options?.body&&options.method==='POST'){
    const info=await ready,data=JSON.parse(options.body);if(!data.resume){data.studio_context={project:pid,item:iid,baseline_revision:info.p.baseline_revision};options={...options,body:JSON.stringify(data)};}
   }return originalFetch(resource,options);};
  ready.catch(error=>{const warning=document.createElement('p');warning.className='hub-error';warning.textContent=error.message;sub.after(warning);});
 }
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

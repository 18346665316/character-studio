'use strict';
(() => {
 const path=location.pathname,q=new URLSearchParams(location.search),hub=path==='/'||path==='/index.html';
 const mode=q.has('task')?'tasks':hub?(q.get('view')||'library'):(q.has('kit')||path==='/characters.html'&&!q.has('create')?'library':'create');
 const link=(label,url,current)=>{const a=document.createElement('a');a.textContent=label;a.href=url;if(current)a.setAttribute('aria-current','page');return a;};
 const nav=document.getElementById('studio-navigation');
 nav.className='studio-nav';nav.append(link('S / STUDIO','/',false));
 for(const [id,title,url] of [['library','素材库','/'],['create','制作素材','/?view=create'],['tasks','生产任务','/?view=tasks']])nav.append(link(title,url,mode===id));
 if(hub)return;
 const surfaces=['/terrain.html','/transition.html','/water.html','/water-shore.html'];
 const group=surfaces.includes(path)?'地表':path==='/props.html'?'物件':path==='/components.html'?'连接构件':'人物';
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

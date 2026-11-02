'use strict';
(() => {
 const $=id=>document.getElementById(id),params=new URLSearchParams(location.search);
 const view=['library','create','tasks'].includes(params.get('view'))?params.get('view'):'library';
 let category=params.get('category')||'全部',assets=[],jobs=[],loading=false;
 const actionLabels={import_model:'导入模型',optimize:'模型优化',adopt_model:'采用模型',reconstruct:'生成模型',prepare:'准备贴图',rig:'骨骼绑定',download:'导入动画',review:'姿态检查',bake:'渲染图集',equipment:'装备调整',weapon:'武器制作',sequence:'动作编排',compact:'图集精简',palette:'颜色简化',produce:'整套动作生产'};
 const categories=['全部','人物','地表','物件','连接构件','建筑'];if(!categories.includes(category))category='全部';
 const titles={library:['素材库','查看已有素材，继续调整或导出。'],create:['制作素材','选择要制作的产物，再设置来源和规格。'],tasks:['生产任务','集中查看各类生产任务；进入工作台继续处理或查看日志。']};
 const node=(tag,value,cls)=>{const n=document.createElement(tag);if(value!==undefined)n.textContent=value;if(cls)n.className=cls;return n;};
 const link=(title,url)=>{const a=node('a',title);a.href=url;return a;};
 const url=(page,key,id)=>page+'?'+key+'='+encodeURIComponent(id);
 const water=k=>k.asset_type==='material'&&k.material_kind==='water';
 const creations=[
  ['建筑','建筑素材','选择建筑线框模板或上传框线图，设定风格，生成并挑选候选，标定后保存。','/buildings.html','⌂'],
  ['人物','人物','从人物原画或已有 GLB 开始，制作模型、动作与游戏素材。','/characters.html?create=1','人'],
  ['地表','地面材质','制作草地、沙地、石质等可平铺地面。','/terrain.html?type=material','▧'],
  ['地表','道路套件','制作地面和四方向道路连接块。','/terrain.html?type=terrain','╋'],
  ['地表','地表过渡','组合两种已有地表，制作连接边缘。','/transition.html','◩'],
  ['地表','水面材质','制作水面纹理和平铺变化块。','/water.html','≈'],
  ['地表','水岸套件','组合已有陆地和水面，制作静态水岸。','/water-shore.html','◒'],
  ['物件','独立物件','制作石头、木箱、灌木或自定义物件。','/props.html','◇'],
  ['连接构件','围栏套件','使用木纹制作可连接的围栏模块。','/components.html','▥']
 ];
 $('hub-title').textContent=titles[view][0];$('hub-description').textContent=titles[view][1];document.title='Studio · '+titles[view][0];
 $('hub-create').hidden=view==='create';$('hub-status-label').hidden=view!=='tasks';$('hub-content').setAttribute('aria-label',titles[view][0]);
 $('hub-search').placeholder=view==='tasks'?'搜索任务名称或编号':'搜索名称或编号';
 function filters(){const root=$('hub-categories');root.replaceChildren();for(const name of categories){const b=node('button',name);b.type='button';b.setAttribute('aria-pressed',String(category===name));b.onclick=()=>{category=name;const p=new URLSearchParams(location.search);if(name==='全部')p.delete('category');else p.set('category',name);history.replaceState(null,'','/'+(p.size?'?'+p:''));filters();paint();};root.append(b);}}
 function card(item){const article=node('article',undefined,'hub-card');const art=link('',item.href);art.className='hub-art';art.setAttribute('aria-label','打开 '+item.title);if(item.image){const img=node('img');img.src=item.image;img.alt=item.title;img.loading='lazy';art.append(img);}else art.textContent=item.symbol||'▧';
 const body=node('div',undefined,'hub-card-copy');body.append(node('span',item.category+' / '+item.kind,'hub-badge'+(item.invalid?' error':'')),node('h2',item.title),node('p',item.description||'查看成果、调整与导出'));
 if(item.id)body.append(node('small',item.id));const actions=node('div',undefined,'hub-card-links');actions.append(link(view==='create'?'开始制作 →':'打开素材 →',item.href));if(item.next)actions.append(link(item.next[0],item.next[1]));if(item.invalid)body.append(node('p','文件完整性异常，请进入工作台查看。','hub-error'));body.append(actions);article.append(art,body);return article;}
 function taskCard(item){const article=node('article',undefined,'hub-card hub-task'),body=node('div',undefined,'hub-card-copy');body.append(node('span',item.category+' · '+item.statusTitle,'hub-badge'+(item.failed?' error':'')),node('h2',item.title),node('p',item.stage||item.statusTitle),node('small',item.id+(item.time?' · '+new Date(item.time).toLocaleString('zh-CN'):'')));if(item.error)body.append(node('p',item.error,'hub-error'));const actions=node('div',undefined,'hub-card-links');actions.append(link(item.failed?'处理任务与日志 →':item.done&&item.category!=='人物'?'查看成果 →':'查看任务 →',item.href));body.append(actions);article.append(body);return article;}
 function paint(){const query=$('hub-search').value.trim().toLowerCase();let list=view==='create'?creations.map(([category,title,description,href,symbol])=>({category,title,kind:'新建',description,href,symbol})):view==='tasks'?jobs:assets;
 list=list.filter(i=>(category==='全部'||i.category===category)&&[i.title,i.id,i.kind].join(' ').toLowerCase().includes(query));
 if(view==='tasks'){const status=$('hub-status').value;list=list.filter(i=>status==='all'||status==='active'&&i.active||status==='failed'&&i.failed||status==='done'&&i.done);}
 $('hub-count').textContent=list.length+(view==='tasks'?' 项任务':view==='create'?' 种产物':' 项素材');const root=$('hub-content');root.replaceChildren(...list.map(view==='tasks'?taskCard:card));if(!list.length)root.append(node('div',query?'没有匹配的结果，试试其他名称。':view==='tasks'?'此分类下暂无任务。':'此分类下暂无素材，可以从“制作素材”开始。','hub-empty'));}
 function addKits(kits,category,kind,page,prefix,image){for(const k of kits||[]){const target=typeof page==='function'?page(k):page;assets.push({id:k.id,title:k.title||k.id,category,kind:typeof kind==='function'?kind(k):kind,href:url(target,'kit',k.id),image:prefix+encodeURIComponent(k.id)+'/'+(k.projection_spec?.preview||image),invalid:k.integrity?.passed===false,next:water(k)?['制作水岸',url('/water-shore.html','water',k.id)]:null});}}
 function addJobs(items,category,page){for(const j of items||[]){const target=typeof page==='function'?page(j):page;const active=['queued','running'].includes(j.status),failed=['failed','interrupted'].includes(j.status),done=['complete','succeeded'].includes(j.status);jobs.push({id:j.id,title:j.spec?.title||j.title||actionLabels[j.action]||j.action||j.id,category,stage:j.stage,error:j.error,time:j.created_at,active,failed,done,statusTitle:active?'进行中':failed?'需要处理':done?'已完成':(j.workflow==='line_drawing'?({draft:'待生成',waiting_review:'待挑选'}[j.status]||j.status):({draft:'结构待确认',waiting_review:'待人工复核',approved:'待导出',rejected:'待修正'}[j.status]||j.status)),href:done&&category!=='人物'&&(j.kit_id||j.kit)?url(target,'kit',j.kit_id||j.kit):url(target,'task',j.id)+(category==='人物'&&j.character?'&character='+encodeURIComponent(j.character):'')});}}
 async function refresh(){if(loading)return;loading=true;$('hub-refresh').disabled=true;const endpoints=['/api/state','/api/terrain/state','/api/props/state','/api/components/state','/api/buildings/state'];try{
 const responses=await Promise.allSettled(endpoints.map(async endpoint=>{const response=await fetch(endpoint);if(!response.ok)throw Error(endpoint+' 读取失败');return response.json();}));assets=[];jobs=[];const errors=[];
 responses.forEach((result,i)=>{if(result.status==='rejected'){errors.push(['人物','地表','物件','连接构件','建筑'][i]);return;}const s=result.value;
 if(i===0){for(const c of s.characters||[])assets.push({id:c.id,title:c.display_name||c.id,category:'人物',kind:'人物工作区',href:url('/characters.html','character',c.id),symbol:'人',description:'模型、骨骼、动作与游戏素材'});addJobs(s.jobs,'人物','/characters.html');}
 if(i===1){addKits(s.kits,'地表',k=>water(k)?'水面':k.asset_type==='material'?'地面材质':'道路套件',k=>water(k)?'/water.html':'/terrain.html','/terrain-asset/','preview.png');addKits(s.transitions,'地表',k=>k.transition_mode==='shoreline'?'水岸':'地表过渡',k=>k.transition_mode==='shoreline'?'/water-shore.html':'/transition.html','/transition-asset/','preview.png');addJobs(s.jobs,'地表',j=>water(j.spec||{})?'/water.html':'/terrain.html');}
 if(i===2){addKits(s.kits,'物件',k=>s.kinds?.[k.asset_kind]?.label||'独立物件','/props.html','/prop-asset/','sprite.png');addJobs(s.jobs,'物件','/props.html');}
 if(i===4){addKits(s.kits,'建筑',k=>k.workflow==='line_drawing'?'建筑素材':'建筑候选包','/buildings.html','/building-asset/','preview.png');addJobs(s.jobs,'建筑','/buildings.html');}
 if(i===3){addKits(s.kits,'连接构件','围栏','/components.html','/component-asset/','assembly.png');addJobs(s.jobs,'连接构件','/components.html');}
 });jobs.sort((a,b)=>Number(b.active)-Number(a.active)||String(b.time||'').localeCompare(String(a.time||'')));$('hub-message').textContent=errors.length?errors.join('、')+'读取失败，可刷新重试。':' ';$('hub-message').className=errors.length?'hub-error':'';paint();
 }catch(error){$('hub-message').textContent=error.message;}finally{loading=false;$('hub-refresh').disabled=false;}}
 $('hub-search').oninput=paint;$('hub-status').onchange=paint;$('hub-refresh').onclick=refresh;filters();if(view==='create'){$('hub-message').textContent='';$('hub-refresh').hidden=true;paint();}else{refresh();if(view==='tasks')setInterval(()=>{if(!document.hidden)refresh();},10000);}
})();

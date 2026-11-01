/* Regression: poll actual UI source through running/failed/interrupted/complete. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element {
 constructor(){this.children=[];this.options=[{},{}];this.value='';this.hidden=false;this.classList={toggle(){}};this.details={open:false};}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=[...nodes];}
 getContext(){return {drawImage(){}};}
 closest(){return this.details;}
}
const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
let poll,phase='running',broken=false,legacy=false;
const tiles=Array.from({length:16},(_,id)=>({id,connections:[],atlas_cell:[0,0]}));
const kit={id:'kit',title:'测试套件',mode:'demo',tile_size:64,road_width:.5,ground_cell:[0,4],tiles,validation:{matching_edge_pairs:256,max_channel_difference:0}};
const context=vm.createContext({document:{getElementById:get,createElement:()=>new Element()},
 Image:class{decode(){return Promise.resolve();}},URL:{},setInterval:callback=>{poll=callback;},
 fetch:async url=>url.includes('job-log')?({ok:true,json:async()=>({events:[{event:'http_error',response:{error:{message:'invalid parameter'}}}]})}):({ok:true,json:async()=>({token:'fake',image_api_configured:true,kits:[{...kit,integrity:{passed:!broken,errors:broken?['ZIP损坏']:[]}}],jobs:[{id:'job',spec:{title:'测试任务'},status:phase,stage:phase==='running'?'正在生成':'任务结束',error:phase==='failed'?(legacy?'服务商图片生成失败；继续任务可能产生费用':'服务商失败'):null}]})})});
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../panel_ui/terrain.js'),'utf8'),context);
 await flush();assert.match(get('form-status').textContent,/正在生成/);
 phase='failed';await poll();assert.match(get('form-status').textContent,/服务商失败/);assert.equal(get('terrain-jobs').details.open,true);
 assert.equal(get('form-status').className,'terrain-error');
 legacy=true;await poll();assert.match(get('form-status').textContent,/尚不能确认请求是否到达生图服务/);assert.doesNotMatch(get('form-status').textContent,/服务商图片生成失败/);
 const box=get('terrain-jobs').children[0],logButton=box.children.find(n=>n.textContent==='查看请求日志');
 await logButton.onclick();const log=box.children.at(-1);assert.equal(log.hidden,false);assert.match(log.textContent,/invalid parameter/);log.scrollTop=73;
 await poll();const refreshed=get('terrain-jobs').children[0].children.at(-1);assert.equal(refreshed,log);assert.equal(refreshed.hidden,false);assert.equal(refreshed.scrollTop,73);
 await logButton.onclick();await poll();assert.equal(log.hidden,true);
 phase='interrupted';await poll();assert.match(get('form-status').textContent,/任务未完成/);
 phase='complete';await poll();assert.match(get('form-status').textContent,/已完成/);assert.equal(get('form-status').className,'');
 broken=true;await poll();assert.equal(get('download-kit').hidden,true);assert.match(get('validation').textContent,/ZIP损坏/);
 console.log('Terrain running, failure visibility, interruption, completion and corrupt-download UI checks passed');
})().catch(e=>{console.error(e);process.exitCode=1;});

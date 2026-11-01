/* Regression: poll actual UI source through running/failed/interrupted/complete. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Element {
 constructor(){this.children=[];this.value='';this.hidden=false;this.classList={toggle(){}};this.details={open:false};}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=[...nodes];}
 getContext(){return {drawImage(){}};}
 closest(){return this.details;}
}
const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
let poll,phase='running',broken=false;
const tiles=Array.from({length:16},(_,id)=>({id,connections:[],atlas_cell:[0,0]}));
const kit={id:'kit',title:'测试套件',mode:'demo',tile_size:64,road_width:.5,ground_cell:[0,4],tiles,validation:{matching_edge_pairs:256,max_channel_difference:0}};
const context=vm.createContext({document:{getElementById:get,createElement:()=>new Element()},
 Image:class{decode(){return Promise.resolve();}},URL:{},setInterval:callback=>{poll=callback;},
 fetch:async()=>({ok:true,json:async()=>({token:'fake',image_api_configured:true,kits:[{...kit,integrity:{passed:!broken,errors:broken?['ZIP损坏']:[]}}],jobs:[{id:'job',spec:{title:'测试任务'},status:phase,stage:phase==='running'?'正在生成':'任务结束',error:phase==='failed'?'服务商失败':null}]})})});
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../panel_ui/terrain.js'),'utf8'),context);
 await flush();assert.match(get('form-status').textContent,/正在生成/);
 phase='failed';await poll();assert.match(get('form-status').textContent,/服务商失败/);assert.equal(get('terrain-jobs').details.open,true);
 assert.equal(get('form-status').className,'terrain-error');
 phase='interrupted';await poll();assert.match(get('form-status').textContent,/任务未完成/);
 phase='complete';await poll();assert.match(get('form-status').textContent,/已完成/);assert.equal(get('form-status').className,'');
 broken=true;await poll();assert.equal(get('download-kit').hidden,true);assert.match(get('validation').textContent,/ZIP损坏/);
 console.log('Terrain running, failure visibility, interruption, completion and corrupt-download UI checks passed');
})().catch(e=>{console.error(e);process.exitCode=1;});

/* Run with Node: node pipeline/tests/test_editor_ui.cjs */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const elements = new Map();
const document = {getElementById(id) {if (!elements.has(id)) elements.set(id,{});return elements.get(id);}};
const context = vm.createContext({document,localStorage:{getItem(){return null;}},requestAnimationFrame(){return 1;},cancelAnimationFrame(){},performance:{now(){return 0;}},console});
const source = fs.readFileSync(path.join(__dirname,'../panel_ui/app.js'),'utf8').replace('refresh(true);setInterval(()=>refresh(),2500);','');
vm.runInContext(fs.readFileSync(path.join(__dirname,'../panel_ui/workspace.js'),'utf8'),context);
vm.runInContext(source,context);
vm.runInContext(`
const old={id:'old',current_rig:false,files:['jogging.fbx'],fingerprint:'old-fp'};
const current={id:'current',current_rig:true,files:['jogging.fbx','idle.fbx'],fingerprint:'new-fp',hashes:{'jogging.fbx':'j','idle.fbx':'i'},titles:{'jogging.fbx':'Jogging'}};
const c={batches:[old,current],approvals:{animations:{current:{'jogging.fbx':{fingerprint:'new-fp'}}}},reviews:[],equipment:[]};
const resources=animationResources(c);
if(resources.length!==2||resources[0].batch.id!=='current'||resources[0].versions.length!==2)throw Error('Current rig must win over historical same-named animation');
if(animationTitle(current,'jogging.fbx')!=='Jogging')throw Error('Original title must be preserved');
if(!animationApproved(c,current,'jogging.fbx')||animationApproved(c,current,'idle.fbx')||animationApproved(c,old,'jogging.fbx')||batchApproved(c,current))throw Error('Approval leaked to sibling or old source');
c.approvals.animations.current['idle.fbx']={fingerprint:'new-fp'};
if(!batchApproved(c,current))throw Error('Fully reviewed source must export');
c.reviews=[{batch:'current',files:{'idle.fbx':'i','jogging.fbx':'changed'}}];
if(reviewFor(c,current))throw Error('Stale review must be rejected');
c.reviews[0].files['jogging.fbx']='j';
if(!reviewFor(c,current))throw Error('Hash matching must ignore object key ordering');
selection={type:'animation',key:'jogging',version:'old/jogging.fbx'};
if(chosenAnimation(c).batch.id!=='old'||chosenBatch(c).id!=='old')throw Error('Explicit history selection must retain exact source');
state={api_version:5};preferences={};selected='hero';
const equipped={id:'sword',batch:'old',compatible_batches:['current','new']};
c.equipment=[equipped];
if(equipmentFor(c,current).length!==1||equipmentFor(c,old).length!==0)throw Error('Equipment compatibility must follow rig, not review batch');
if(selectedEquipment(c,current)?.id!=='sword')throw Error('New actions must default to existing equipment');
prefs().equipment='';
if(selectedEquipment(c,current)!==null)throw Error('Explicit unarmed selection must be retained');
prefs().source='current';selection={type:'equipment',equipment:'sword'};
if(chosenBatch(c).id!=='current')throw Error('Equipment review provenance must not force the animation source');
const ref={equipment:{id:'gold'},settings:{frame_size:128,supersample:4},clips:[{info:{view:'front'}}]};
const wrong={id:'wrong',renderer:'godot',equipment:{id:'axe'},settings:ref.settings,clips:ref.clips};
const matching={...ref,id:'matching',renderer:'godot'};
if(comparableDelivery([wrong,matching],'godot',ref)?.id!=='matching')throw Error('Renderer switch must prefer matching equipment and render settings');
if(comparableDelivery([wrong],'blender',ref)!==undefined)throw Error('Missing renderer must not select another backend');
if(usageSummary({default:'back',clips:{attack:{initial:'inherit',events:[{at:.3,state:'hand'}]}}},'attack')!=='背部 · 30% → 手持')throw Error('Rendered state summary lost timed events');
let drawArgs;
const p={frame:5,count:12,w:64,h:64,img:{naturalWidth:256,naturalHeight:192},ctx:{clearRect(){},drawImage(...args){drawArgs=args;}}};
drawFrame(p);
if(drawArgs[1]!==64||drawArgs[2]!==64||document.getElementById('timeline').value!==5)throw Error('Timeline must address the correct grid cell');
`,context);
assert.equal(elements.get('frame-label').textContent,'6 / 12');
module.exports={passed:15};
if(require.main===module)console.log('Editor resource, approval, provenance and timeline checks passed');

vm.runInContext(`
for(const [type,page]of Object.entries({model:'character',rig:'character',animation:'actions',actions:'actions',equipment:'equipment',weapons:'equipment',weapon:'equipment',sheet:'sheets',quality:'sheets',sheets:'sheets',sequence:'sequence'})){
 if(pageFor({type})!==page)throw Error('Workspace route mismatch: '+type);
}
if(!deliveryTitle({id:'20261031-165024-copy',operation:{type:'compact'},renderer:'godot'}).startsWith('精简结果'))throw Error('Compression records must be distinguished from renders');
`,context);

vm.runInContext(`
const groupsTest=sheetGroups({batches:[{id:'b',titles:{'idle.fbx':'Idle','attack.fbx':'Attack'}}],deliveries:[
 {id:'new',batch:'b',clips:[{name:'idle'}]},
 {id:'old',batch:'b',clips:[{name:'idle'},{name:'attack'}]},
 {id:'sequence',kind:'sequence',clips:[{name:'idle'}]}
]});
if(groupsTest.length!==2||groupsTest[0].title!=='Attack'||groupsTest[1].title!=='Idle')throw Error('Sheets must be grouped and ordered by action');
if(groupsTest[1].versions.map(v=>v.delivery.id).join(',')!=='new,old')throw Error('Action versions must retain exact record references and exclude sequence outputs');
`,context);
vm.runInContext(`
renderDraft=()=>{};
applyActionPreset({id:'basic_movement',version:1,actions:[{title:'Breathing Idle',role:'idle'},{title:'Running',role:'run'}]});
replaceDraftTitle(1,'Jogging');
const payload=presetPayload();
if(payload.roles.Jogging!=='run'||payload.roles.Running||payload.preset.id!=='basic_movement')throw Error('Preset replacement lost role or source');
if(payload.actions.join(',')!=='Breathing Idle,Jogging')throw Error('Preset request not updated');
`,context);

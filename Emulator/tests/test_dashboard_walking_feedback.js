/* Production dashboard: independent, robot-owned walking setting. No hardware. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map(),calls=[];
function node(id){if(!nodes.has(id))nodes.set(id,{value:'',hidden:false,disabled:false,textContent:'',classList:{toggle(){}},listeners:{},reportValidity(){return true;},addEventListener(t,f){this.listeners[t]=f;}});return nodes.get(id);}
let walking=false,leveling=false;
const context={console,URLSearchParams,document:{getElementById:node},window:{addEventListener(){},clearTimeout(){}},localStorage:{getItem(){return null;}},
 async fetch(url,options){const payload=JSON.parse(options.body);calls.push({url,payload});
  assert.equal(url,'/api/balance');
  if(payload.op==='walking') {assert.deepEqual(Object.keys(payload).sort(),['enabled','op','robot_id']);walking=payload.enabled;}
  else if(payload.op==='save')leveling=payload.enabled;
  const balance={seq:1,enabled:leveling,saved:true,active:false,walking_enabled:walking,walking_saved:true};
  return {ok:true,status:200,json:async()=>({seq:1,balance})};
 }};
let source=fs.readFileSync('Master/gateway/dashboard/static/dashboard.js','utf8');
source=source.replace('  if (!setupLogin()) {',`globalThis.api={operateBalance,renderBalance,select(id,features){selectedRobotId=id;balanceGeneration++;balanceSupported=true;balanceTuningSupported=false;balanceEntry={features,status:{walking_feedback:{active:true,heading_error_rad:.1,turn_percent:25,reduced:false}}};balanceData={enabled:false,saved:true};}};if(false){`);
vm.createContext(context);vm.runInContext(source,context);
(async()=>{
 const a=context.api;a.select('p4',['balance_control_v1','walking_feedback_v1']);a.renderBalance();
 assert.equal(node('walking-feedback-controls').hidden,false);
 assert.match(node('walking-feedback-live').textContent,/5.7°.*25.0%/);
 node('walking-feedback-enabled').value='true';await a.operateBalance('walking');
 assert.equal(walking,true,node('balance-status').textContent);assert.equal(leveling,false);
 assert.equal(node('balance-enabled').value,'false');
 assert.equal(node('walking-feedback-enabled').value,'true');
 node('balance-enabled').value='true';await a.operateBalance('save');
 assert.equal(leveling,true);assert.equal(walking,true);
 assert(!('walking_enabled' in calls.at(-1).payload));
 a.select('legacy',['balance_control_v1']);a.renderBalance();assert.equal(node('walking-feedback-controls').hidden,true);
 console.log('Walking switch: independent saved operation, readback, live correction and older-firmware presentation passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});

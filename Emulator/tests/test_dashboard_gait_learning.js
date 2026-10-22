const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map(),calls=[];
function node(id){if(!nodes.has(id))nodes.set(id,{value:'',hidden:false,disabled:false,textContent:'',classList:{toggle(){}},listeners:{},addEventListener(t,f){this.listeners[t]=f;}});return nodes.get(id);}
let enabled=false;
const context={console,URLSearchParams,Date,document:{getElementById:node},window:{addEventListener(){},clearTimeout(){}},localStorage:{getItem(){return null;}},
 async fetch(url,options={}) {
  const payload=options.body?JSON.parse(options.body):null;calls.push({url,payload});
  assert.equal(url,'/api/robot/gait-learning?robot_id=p4');
  if(payload?.op==='configure')enabled=payload.enabled;
  return {ok:true,status:200,json:async()=>({enabled,amount:.5,model_id:'a'.repeat(64),stride:100,reason:'feedback_unavailable',
    blend:.4,fit:1,valid_legs:7,error_mm:Array(12).fill(1.25)})};
 }};
let source=fs.readFileSync('Master/gateway/dashboard/static/dashboard.js','utf8');
source=source.replace('  if (!setupLogin()) {',`globalThis.api={readLearning,learningOperation,renderBalance,select(id){selectedRobotId=id;balanceSupported=false;balanceEntry={features:['gait_learning_v1']};},candidate(){learnedCandidate={robot:selectedRobotId,result:{model:{schema:'gait_learning_v2',id:'test',coefficients:Array(60).fill(0)}}};}};if(false){`);
vm.createContext(context);vm.runInContext(source,context);
(async()=>{
 const a=context.api;a.select('p4');await a.readLearning(true);
 assert.equal(node('learned-enabled').value,'false');assert.equal(node('learned-amount').value,'50');
 assert.match(node('learned-live').textContent,/feedback unavailable/);
 assert.match(node('learned-live').textContent,/Front right: measurement unavailable/);
 node('learned-enabled').value='true';node('learned-amount').value='50';await a.learningOperation('configure');
 assert.equal(enabled,true);assert.deepEqual(calls.find(c=>c.payload).payload,{op:'configure',enabled:true,amount:.5});
 a.candidate();await a.learningOperation('install');
 assert.equal(calls.find(c=>c.payload?.op==='install').payload.model.coefficients.length,60);
 a.select('different');const before=calls.length;await a.learningOperation('install');
 assert.equal(calls.length,before);assert.match(node('learned-result').textContent,/selected robot/);
 console.log('Learned gait UI: independent configuration, measured-leg presentation, task-space install, selected-robot ownership passed');
})().catch(error=>{console.error(error);process.exitCode=1;});

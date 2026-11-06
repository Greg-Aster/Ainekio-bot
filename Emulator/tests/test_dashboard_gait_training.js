const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const nodes=new Map(),calls=[];
let walkingProfile={source:'native'};
let neuralStatus={runs:[],defaults:{}};
const physicalResponses={};
function node(id){
  if(!nodes.has(id))nodes.set(id,{value:"",checked:false,textContent:"",options:[],
    pause(){this.paused=true;},
    replaceChildren(...items){this.options=items;this.children=items;},appendChild(o){this.options.push(o);},
    classList:{toggle(){}},listeners:new Map(),addEventListener(type,fn){this.listeners.set(type,fn);},
    fire(type){return this.listeners.get(type)?.();}});
  return nodes.get(id);
}
const data={settings:{logging:true,learning:false,radii:{duty:.03}},state:"logging",
  records:123,lost_records:0,coverage:{forward:3,backward:2,turning:4,run:1},
  analysis_running:false,directory:"/private/gait",measurement_reason:"Camera motion unavailable",
  banks:{walk:{incumbent:"a".repeat(64),candidate:"b".repeat(64),generation:2,observations:10,
    converged:false,history:[]},run:{incumbent:"c".repeat(64),generation:1,observations:4,converged:false,history:[]}}};
const ctx={console,URLSearchParams,Date,setInterval(){},document:{getElementById:node,createElement(){return {children:[],listeners:new Map(),addEventListener(type,fn){this.listeners.set(type,fn);},append(...items){this.children.push(...items);}};}},
  window:{addEventListener(){},clearTimeout(){}},localStorage:{getItem(){return null;}},
  async fetch(url,options){const payload=JSON.parse(options.body);calls.push({url,payload});
    if(url==='/api/neural-gait'){
      if(payload.op==='walking-source')walkingProfile=payload.profile;
      if(payload.op==='render' && neuralStatus.render_response)return {ok:true,json:async()=>neuralStatus.render_response};
      if(physicalResponses[payload.op])return {ok:true,json:async()=>physicalResponses[payload.op]};
      return {ok:true,json:async()=>({...neuralStatus,walking_source:walkingProfile})};
    }
    return {ok:true,json:async()=>data};}};
let source=fs.readFileSync("Master/gateway/dashboard/static/dashboard.js","utf8");
source=source.replace("  if (!setupLogin()) {",
  "globalThis.api={renderGaitTraining,gaitTrainingOperation,setupNeuralGait,select(id){selectedRobotId=id;}};if(false){");
vm.createContext(ctx);vm.runInContext(source,ctx);
(async()=>{
  ctx.api.select("p4");
  ctx.api.renderGaitTraining(data,true);
  assert.equal(node("gait-log-enabled").checked,true);
  assert.equal(node("gait-train-enabled").checked,false);
  assert.match(node("gait-training-status").textContent,/backward 2, turning 4, Run 1/);
  assert.match(node("gait-training-status").textContent,/Camera motion unavailable/);
  node("gait-train-enabled").checked=true;
  await ctx.api.gaitTrainingOperation("configure");
  assert.deepEqual(calls[0],{url:"/api/gait-learning/service",payload:{robot_id:"p4",op:"configure",
    settings:{logging:true,learning:true,radii:{duty:.03}}}});
  await ctx.api.gaitTrainingOperation("analyze");
  assert.equal(calls[1].payload.op,"analyze");
  node("gait-training-history").value="run:"+"c".repeat(64);
  await ctx.api.gaitTrainingOperation("restore");
  assert.equal(calls[2].payload.gait,"run");
  assert.equal(calls[2].payload.robot_id,"p4");
  assert.ok(calls.every(c=>!c.url.includes("intent")));
  ctx.api.setupNeuralGait();
  node('neural-gait-refresh').fire('click');await new Promise(resolve=>setImmediate(resolve));
  assert.equal(node('neural-walking-source').value,'native');
  node('neural-walking-source').value='neural';
  node('neural-walking-forward').value='.015';node('neural-walking-lateral').value='.01';node('neural-walking-yaw').value='.12';
  node('neural-walking-forward').fire('input');
  node('neural-gait-refresh').fire('click');await new Promise(resolve=>setImmediate(resolve));
  assert.equal(node('neural-walking-source').value,'neural','Polling must preserve unsaved source edits');
  assert.equal(node('neural-walking-forward').value,'.015');
  await node('neural-walking-save').fire('click');
  assert.deepEqual(calls.at(-1),{url:'/api/neural-gait',payload:{op:'walking-source',robot_id:'p4',
    profile:{source:'neural',forward_m_s:.015,lateral_m_s:.01,yaw_rad_s:.12}}});
  assert.match(node('neural-walking-result').textContent,/No movement started/);
  node('neural-gait-refresh').fire('click');await new Promise(resolve=>setImmediate(resolve));
  assert.equal(node('neural-walking-forward').value,.015);
  neuralStatus={model_id:'abc',defaults:{},runs:[{id:'abc',state:'evaluating',steps:135168,
    evaluation_purpose:'checkpoint',completed_episodes:8,total_episodes:16,rendering:true,
    progress_video:{checkpoint_ids:['initial']},checkpoints:[{steps:135168,
      evaluation:{mean_reward:228.8,mean_forward_m_s:-.02,falls:0,episodes:[{},{}],
        command_results:[{command:[.015,0,0],measured_velocity_command_m_s:[-.00161,0],
          measured_yaw_rate_rad_s:0,seconds:384}]}}]}]};
  node('neural-gait-refresh').fire('click');await new Promise(resolve=>setImmediate(resolve));
  assert.match(node('neural-gait-summary').textContent,/Evaluating checkpoint · 8\/16 trials/);
  assert.match(node('neural-gait-summary').textContent,/video 1\/1 checkpoints \(rendering\)/);
  assert.equal(node('neural-gait-checkpoints').children[0].children[1].textContent,'228.80',
    'Mixed forward and reverse trials must display their task reward, not average signed forward speed');
  assert.equal(node('neural-gait-command-results').children[0].children[0].textContent,'0.015 / 0.000 / 0.000');
  assert.equal(node('neural-gait-command-results').children[0].children[1].textContent,'-0.002 / 0.000 / 0.000',
    'Wrong-direction movement must remain visible alongside the aggregate reward');
  neuralStatus.runs[0].evaluation_purpose='source_policy_baseline';
  node('neural-gait-refresh').fire('click');await new Promise(resolve=>setImmediate(resolve));
  assert.match(node('neural-gait-summary').textContent,/Evaluating starting policy baseline · 8\/16 trials/);
  neuralStatus.runs[0].state='completed';
  neuralStatus.runs[0].rendering=false;
  neuralStatus.runs[0].progress_video={footage_scope:'initial_final_matched_trial',checkpoint_ids:['initial','final']};
  neuralStatus.runs[0].checkpoints=Array(7).fill(neuralStatus.runs[0].checkpoints[0]);
  node('neural-gait-refresh').fire('click');await new Promise(resolve=>setImmediate(resolve));
  assert.match(node('neural-gait-summary').textContent,/before\/after video: 2 matched trials/);
  assert.doesNotMatch(node('neural-gait-summary').textContent,/2\/7 checkpoints/);
  neuralStatus.runs[0].state='training';
  neuralStatus.runs[0].progress_video=null;
  neuralStatus.runs[0].automatic_footage='initial and published final weights; one matched trial each';
  neuralStatus.render_response={state:'comparison_after_training'};
  node('neural-gait-refresh').fire('click');await new Promise(resolve=>setImmediate(resolve));
  assert.match(node('neural-gait-summary').textContent,/before\/after video after training/);
  node('neural-gait-progress').fire('click');await new Promise(resolve=>setImmediate(resolve));
  assert.equal(node('neural-gait-summary').textContent,'The before/after comparison will render when training finishes.');
  const simulation=neuralStatus.runs[0];
  simulation.has_policy=true;
  const physical={id:'physical123',kind:'physical-redq',state:'created',steps:0,has_policy:true,
    checkpoints:[{id:'actor000',policy:'checkpoints/actor000.npz',steps:0}]};
  neuralStatus.runs.push(physical);
  physicalResponses['physical-create']={run_id:physical.id,state:'created'};
  physicalResponses['physical-train']={run_id:physical.id,state:'training'};
  physicalResponses['physical-trial']={state:'submitted',seq:42};
  node('neural-gait-environment').value=JSON.stringify({robot:'v2-12servo',foot_action_scale_mm:30,
    scenarios:[{warm_start_actions:Array(2000).fill(Array(12).fill(0))}],body_mass_kg:.65});
  let before=calls.length;
  node('neural-gait-physical-create').fire('click');await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(calls[before],{url:'/api/neural-gait',payload:{op:'physical-create',robot_id:'p4',
    environment:{robot:'v2-12servo',foot_action_scale_mm:30}}});
  assert.deepEqual(calls.slice(before).map(c=>c.payload.op),['physical-create','status'],
    'Creating a run must neither select an actor nor start movement');
  assert.ok(JSON.stringify(calls[before].payload).length<16384,
    'Physical creation sends only the real robot contract, not large simulation histories');
  assert.equal(node('neural-gait-model').value,physical.id);
  assert.match(node('neural-gait-selection').textContent,/Active model: abc/);
  assert.match(node('neural-gait-physical-result').textContent,/No movement started/);
  assert.match(node('neural-gait-summary').textContent,/Physical learning/);
  assert.doesNotMatch(node('neural-gait-summary').textContent,/Simulation only/);
  assert.equal(node('neural-gait-render').hidden,true);
  assert.equal(node('neural-gait-resume').hidden,true);
  assert.equal(node('neural-gait-progress').hidden,true);
  assert.equal(node('neural-gait-video-note').hidden,true);
  assert.equal(node('neural-gait-physical-train').disabled,false);
  assert.equal(node('neural-gait-load').disabled,false);
  assert.equal(node('neural-gait-checkpoints').children[0].children[1].textContent,'—');
  assert.equal(node('neural-gait-checkpoints').children[0].children[2].textContent,'Not evaluated');
  assert.match(node('neural-gait-physical-measurements').textContent,/No physical evaluation supplied/);
  before=calls.length;
  const checkpointButton=node('neural-gait-checkpoints').children[0].children[3].children[0];
  await checkpointButton.listeners.get('click')();
  assert.deepEqual(calls[before].payload,{op:'load',robot_id:'p4',model_id:physical.id,checkpoint_id:'actor000'});
  node('neural-gait-physical-recordings').value=' /recordings/first \n\n/recordings/second\r\n';
  node('neural-gait-physical-updates').value='1000';
  before=calls.length;
  node('neural-gait-physical-train').fire('click');await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(calls[before],{url:'/api/neural-gait',payload:{op:'physical-train',robot_id:'p4',
    model_id:physical.id,recordings:['/recordings/first','/recordings/second'],updates:1000,device:'cuda'}});
  assert.deepEqual(calls.slice(before).map(c=>c.payload.op),['physical-train','status'],
    'Training recorded data must not load or move the robot');
  assert.match(node('neural-gait-physical-result').textContent,/active actor is unchanged/);
  node('neural-gait-physical-updates').value='0';
  before=calls.length;
  node('neural-gait-physical-train').fire('click');await new Promise(resolve=>setImmediate(resolve));
  assert.equal(calls.length,before,'Invalid update count is not a training request');
  assert.match(node('neural-gait-physical-result').textContent,/positive whole number/);
  node('neural-gait-physical-updates').value='1000';
  node('neural-gait-physical-speed').value='100';
  before=calls.length;
  node('neural-gait-physical-trial').fire('click');await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(calls[before],{url:'/api/neural-gait',payload:{op:'physical-trial',robot_id:'p4',speed:100,dir:'fwd'}});
  assert.deepEqual(calls.slice(before).map(c=>c.payload.op),['physical-trial','status']);
  assert.match(node('neural-gait-physical-result').textContent,/submitted/);
  assert.doesNotMatch(node('neural-gait-physical-result').textContent,/completed|successful/);
  physical.checkpoints[0].evaluation={recordings:2,estimated_displacement_m:.12,metricAccuracyVerified:false};
  node('neural-gait-refresh').fire('click');await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(JSON.parse(node('neural-gait-physical-measurements').textContent),physical.checkpoints[0].evaluation,
    'Show supplied physical evidence without inventing simulation episodes or claiming verified distance');
  before=calls.length;
  node('neural-gait-model').value='abc';node('neural-gait-model').fire('change');
  assert.equal(calls.length,before,'Changing the viewed run only changes its displayed results');
  assert.equal(node('neural-gait-render').hidden,false);
  assert.equal(node('neural-gait-resume').hidden,false);
  assert.equal(node('neural-gait-progress').hidden,false);
  assert.equal(node('neural-gait-physical-evidence').hidden,true);
  assert.match(node('neural-gait-summary').textContent,/Simulation only/);
  node('neural-gait-steps').value='4096';node('neural-gait-workers').value='2';
  before=calls.length;
  node('neural-gait-resume').fire('click');await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(calls[before].payload,{op:'train',robot_id:'p4',steps:4096,resume:'abc'});
  before=calls.length;
  node('neural-gait-environment').value=JSON.stringify({robot:'v2-12servo',foot_action_scale_mm:30});
  node('neural-gait-train').fire('click');await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(calls[before].payload,{op:'train',robot_id:'p4',steps:4096,workers:2,
    environment:{robot:'v2-12servo',foot_action_scale_mm:30}});
  const html=fs.readFileSync('Master/gateway/dashboard/static/dashboard.html','utf8');
  assert.match(html,/id="neural-gait-physical-speed"[^>]*value="100"/);
  assert.match(html,/id="neural-gait-physical-updates"[^>]*value="1000"/);
  console.log("Host gait training UI: physical create/train/trial, actor selection, recorded evidence and simulation controls passed");
})().catch(e=>{console.error(e);process.exitCode=1;});

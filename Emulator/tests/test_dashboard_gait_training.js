const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const nodes=new Map(),calls=[];
let walkingProfile={source:'native'};
let neuralStatus={runs:[],defaults:{}};
function node(id){
  if(!nodes.has(id))nodes.set(id,{value:"",checked:false,textContent:"",options:[],
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
const ctx={console,URLSearchParams,Date,setInterval(){},document:{getElementById:node,createElement(){return {children:[],append(...items){this.children.push(...items);}};}},
  window:{addEventListener(){},clearTimeout(){}},localStorage:{getItem(){return null;}},
  async fetch(url,options){const payload=JSON.parse(options.body);calls.push({url,payload});
    if(url==='/api/neural-gait'){
      if(payload.op==='walking-source')walkingProfile=payload.profile;
      if(payload.op==='render' && neuralStatus.render_response)return {ok:true,json:async()=>neuralStatus.render_response};
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
  console.log("Host gait training UI: selected robot, separate switches, context coverage, analysis and Run restore passed");
})().catch(e=>{console.error(e);process.exitCode=1;});

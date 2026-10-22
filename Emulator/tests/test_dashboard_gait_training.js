const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const nodes=new Map(),calls=[];
function node(id){
  if(!nodes.has(id))nodes.set(id,{value:"",checked:false,textContent:"",options:[],
    replaceChildren(){this.options=[];},appendChild(o){this.options.push(o);},
    classList:{toggle(){}},addEventListener(){}});
  return nodes.get(id);
}
const data={settings:{logging:true,learning:false,radii:{duty:.03}},state:"logging",
  records:123,lost_records:0,coverage:{forward:3,backward:2,turning:4,run:1},
  analysis_running:false,directory:"/private/gait",measurement_reason:"Camera motion unavailable",
  banks:{walk:{incumbent:"a".repeat(64),candidate:"b".repeat(64),generation:2,observations:10,
    converged:false,history:[]},run:{incumbent:"c".repeat(64),generation:1,observations:4,converged:false,history:[]}}};
const ctx={console,URLSearchParams,Date,document:{getElementById:node,createElement(){return {};}},
  window:{addEventListener(){},clearTimeout(){}},localStorage:{getItem(){return null;}},
  async fetch(url,options){calls.push({url,payload:JSON.parse(options.body)});
    return {ok:true,json:async()=>data};}};
let source=fs.readFileSync("Master/gateway/dashboard/static/dashboard.js","utf8");
source=source.replace("  if (!setupLogin()) {",
  "globalThis.api={renderGaitTraining,gaitTrainingOperation,select(id){selectedRobotId=id;}};if(false){");
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
  console.log("Host gait training UI: selected robot, separate switches, context coverage, analysis and Run restore passed");
})().catch(e=>{console.error(e);process.exitCode=1;});

/* Execute the production handlers with delayed transport replies. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const nodes = new Map();
function node(id) {
  if (!nodes.has(id)) nodes.set(id, { value: ({'walk-gait':'walk','walk-mode':'auto','walk-speed':'100','walk-direction':'fwd','walk-cycles':'2'})[id] || '', checked:true,
    options:id==='walk-direction'?['fwd','back','turn_l','turn_r','side_l','side_r'].map(value=>({value,disabled:false})):[],
    listeners:new Map(),addEventListener(type,fn){this.listeners.set(type,fn);},
    fire(type){return this.listeners.get(type)?.({target:this,preventDefault(){}});},
    classList:{remove(){},add(){},toggle(){}},setAttribute(){},reportValidity(){return true;} });
  return nodes.get(id);
}
const requests = [];
const context = { console, URLSearchParams, AbortController, navigator:{getGamepads(){return [];}}, localStorage:{getItem(){return null;}},
  document:{getElementById:node, querySelector:node, querySelectorAll(){return [];}},
  window:{addEventListener(){},clearTimeout(){}},
  fetch(url,opts){return new Promise((resolve,reject)=>requests.push({url,body:JSON.parse(opts.body),resolve:(seq)=>resolve({ok:true,status:200,json:async()=>({seq})}),reject}));}
};
let source=fs.readFileSync(path.join(__dirname,'../../Master/gateway/dashboard/static/dashboard.js'),'utf8');
source=source.replace('  if (!setupLogin()) {', `
  globalThis.motionTest = {
    select(id) { selectedRobotId=id; variableWalking=directionalWalking=true; availableBodyCommands=null; resetWalking(); },
    state() { return {activeWalkSequence,heldRequestPending,walkRequestPending,activeWalkProfile}; },
    range(supported,crab=false) { runningSupported=supported; crabSupported=crab; updateSpeedRange(); },
    beginHeldMotion,applyWalking,stopMotion,setupMotionControls,updateWalkingStatus
  };
  if (false) {`);
vm.createContext(context);vm.runInContext(source,context);
const api=context.motionTest;
async function run() {
  api.select('robot-a');
  const old=api.beginHeldMotion('fwd');
  assert.equal(requests[0].body.robot_id,'robot-a');
  api.select('robot-b');
  const current=api.beginHeldMotion('fwd');
  requests[0].resolve(111);await old;
  assert.equal(api.state().activeWalkSequence,null);
  assert.equal(api.state().heldRequestPending,true);
  requests[1].resolve(222);await current;
  assert.equal(api.state().activeWalkSequence,222);
  const finish=api.applyWalking(true);
  assert.equal(requests[2].body.robot_id,'robot-b');
  assert.equal(requests[2].body.params.update,222);
  requests[2].resolve(223);await finish;

  api.select('robot-a');
  const first=api.applyWalking();
  api.select('robot-b');
  const second=api.applyWalking();
  requests[3].resolve(333);await first;
  assert.equal(api.state().walkRequestPending,true);
  requests[4].resolve(444);await second;
  assert.equal(api.state().activeWalkSequence,444);

  api.select('robot-a');
  const pending=api.beginHeldMotion('fwd');
  const stop=api.stopMotion();
  api.select('robot-b');
  const count=requests.length;
  requests[count-2].resolve(555);requests[count-1].resolve(556);
  await Promise.all([pending,stop]);
  assert.equal(requests.length,count,'late stop must not issue a command to newly selected robot');

  api.select('robot-a');
  const failed=api.beginHeldMotion('fwd');
  api.select('robot-b');
  const live=api.beginHeldMotion('fwd');
  requests[count].reject(new Error('old robot disconnected'));await failed;
  assert.equal(api.state().heldRequestPending,true);
  requests[count+1].resolve(777);await live;
  assert.equal(api.state().activeWalkSequence,777);
  node('walk-speed').value='200';node('walk-gait').value='walk';
  api.range(true);assert.equal(node('walk-speed').max,'200');assert.equal(node('walk-speed').value,'200');
  node('walk-gait').value='crawl';api.range(true);assert.equal(node('walk-speed').value,'100');
  node('walk-gait').value='walk';node('walk-speed').value='150';api.range(false);assert.equal(node('walk-speed').value,'100');
  api.select('robot-run');api.range(true);node('walk-speed').value='100';
  const start=api.applyWalking();requests.at(-1).resolve(800);await start;
  node('walk-speed').value='150';const runUpdate=api.applyWalking();
  assert.equal(requests.at(-1).body.params.speed,150);assert.equal(requests.at(-1).body.params.update,800);assert.equal(requests.at(-1).body.params.gait,'walk');
  requests.at(-1).resolve(801);await runUpdate;
  node('walk-speed').value='75';const walkUpdate=api.applyWalking();assert.equal(requests.at(-1).body.params.update,800);requests.at(-1).resolve(802);await walkUpdate;
  console.log('Negotiated Speed range and same-command Walk/Run threshold updates passed.');
  console.log('Delayed drive replies, failures, Finish, and stop confirmations remain bound to their robot.');

  api.setupMotionControls();
  api.select('robot-fault');api.range(true);
  const idleCount=requests.length;
  node('walk-speed').value='140';await node('walk-speed').fire('change');
  assert.equal(requests.length,idleCount,'idle Speed changes only configure the next Start');
  const configuredStart=api.applyWalking();
  assert.equal(requests.at(-1).body.params.speed,140);
  assert.equal(requests.at(-1).body.params.update,undefined);
  requests.at(-1).resolve(900);await configuredStart;

  // A rejected speed update drops queued changes without automatically starting again.
  node('walk-speed').value='150';const rejectedUpdate=node('walk-speed').fire('change');
  assert.equal(requests.at(-1).body.params.update,900);
  const rejectedRequest=requests.at(-1), rejectedCount=requests.length;
  node('walk-speed').value='160';await node('walk-speed').fire('change');
  rejectedRequest.reject(new Error('walk update does not identify an active walk'));await rejectedUpdate;
  assert.equal(api.state().activeWalkSequence,null);
  assert.equal(api.state().walkRequestPending,false);
  assert.equal(requests.length,rejectedCount,'failed update cannot replay queued speed changes');
  assert.equal(node('walk-speed').value,'160');
  assert.equal(node('walk-apply').textContent,'Start');
  assert.equal(node('walk-finish').disabled,true);
  assert.match(node('command-result').textContent,/walk update does not identify an active walk/);
  node('walk-speed').value='170';await node('walk-speed').fire('change');
  assert.equal(requests.length,rejectedCount);
  const restarted=api.applyWalking();
  assert.equal(requests.at(-1).body.params.update,undefined);
  assert.equal(requests.at(-1).body.params.speed,170);
  requests.at(-1).resolve(901);await restarted;

  // A terminal status outranks an in-flight update; its late reply cannot hide the fault.
  node('walk-speed').value='175';const lateUpdate=node('walk-speed').fire('change');
  const lateRequest=requests.at(-1), beforeTerminal=requests.length;
  node('walk-speed').value='180';await node('walk-speed').fire('change');
  api.updateWalkingStatus({epoch:1,next_sequence:903,active_walk_sequence:null,
    last_terminal:{t:'nak',seq:901,code:'BUSY',msg:'Servo output fault'}});
  assert.equal(api.state().activeWalkSequence,null);
  // renderStatus presents the terminal after reconciliation; model that displayed text.
  node('command-result').textContent='Command 901 rejected: BUSY — Servo output fault';
  lateRequest.resolve(902);await lateUpdate;
  assert.equal(api.state().activeWalkSequence,null);
  assert.equal(requests.length,beforeTerminal);
  assert.match(node('command-result').textContent,/Servo output fault/);

  // A fast start rejection may reach status before the HTTP sequence response.
  api.select('robot-fast-fault');
  const fastStart=api.applyWalking(), fastRequest=requests.at(-1), fastCount=requests.length;
  await api.applyWalking();
  api.updateWalkingStatus({epoch:1,next_sequence:911,active_walk_sequence:null,
    last_terminal:{t:'nak',seq:910,code:'BUSY',msg:'Servo output fault'}});
  fastRequest.resolve(910);await fastStart;
  assert.equal(api.state().activeWalkSequence,null);
  assert.equal(requests.length,fastCount);
  assert.match(node('command-result').textContent,/Command 910 rejected.*Servo output fault/);
  await node('walk-speed').fire('change');
  assert.equal(requests.length,fastCount);

  // Unrelated failures do not cancel a walk; confirmed completion does.
  const healthy=api.applyWalking();requests.at(-1).resolve(920);await healthy;
  api.updateWalkingStatus({epoch:1,next_sequence:922,active_walk_sequence:920,
    active_walk:{dir:'fwd',gait:'walk'},last_terminal:{t:'nak',seq:921,code:'BUSY',msg:'Other command rejected'}});
  assert.equal(api.state().activeWalkSequence,920);
  api.updateWalkingStatus({epoch:1,next_sequence:923,active_walk_sequence:null,last_terminal:{t:'done',seq:920}});
  assert.equal(api.state().activeWalkSequence,null);
  const afterDone=requests.length;await node('walk-speed').fire('change');
  assert.equal(requests.length,afterDone);

  // Completion remains authoritative even when a later terminal replaced its receipt.
  const completedStart=api.applyWalking(), completedRequest=requests.at(-1);
  api.updateWalkingStatus({epoch:1,next_sequence:932,active_walk_sequence:null,last_terminal:{t:'ack',seq:931}});
  node('command-result').textContent='Command 930 rejected: BUSY — Servo output fault';
  completedRequest.resolve(930);await completedStart;
  assert.equal(api.state().activeWalkSequence,null);
  assert.match(node('command-result').textContent,/Servo output fault/);

  // Reconnection invalidates an outstanding start response for the old epoch.
  api.updateWalkingStatus({epoch:1,next_sequence:933,active_walk_sequence:null});
  const oldEpoch=api.beginHeldMotion('fwd'), oldEpochRequest=requests.at(-1);
  api.updateWalkingStatus({epoch:2,next_sequence:1,active_walk_sequence:null});
  oldEpochRequest.resolve(933);await oldEpoch;
  assert.equal(api.state().activeWalkSequence,null);
  assert.equal(api.state().heldRequestPending,false);
  console.log('Idle Speed, rejected/queued updates, fast terminal replies, completed walks, and reconnect races passed.');

  api.select('robot-crab');node('walk-gait').value='crab';node('walk-speed').value='150';
  api.range(true,true);
  const sideways=node('walk-direction').options.filter(option=>option.value.startsWith('side_'));
  assert.equal(node('walk-speed').max,'100');assert.equal(node('walk-speed').value,'100');
  assert.ok(sideways.every(option=>!option.disabled));
  node('walk-direction').value='side_l';
  const crabStart=api.applyWalking();
  assert.equal(requests.at(-1).body.params.gait,'crab');
  assert.equal(requests.at(-1).body.params.dir,'side_l');
  requests.at(-1).resolve(1000);await crabStart;
  const crabFinish=api.applyWalking(true);
  assert.equal(requests.at(-1).body.params.update,1000);
  assert.equal(requests.at(-1).body.params.speed,0);
  requests.at(-1).resolve(1001);await crabFinish;
  node('walk-gait').value='walk';api.range(true,true);
  assert.equal(node('walk-direction').value,'fwd');assert.ok(sideways.every(option=>option.disabled));
  api.select('robot-without-crab');node('walk-gait').value='crab';api.range(true,false);
  const beforeUnsupported=requests.length;await api.applyWalking();
  assert.equal(requests.length,beforeUnsupported);assert.ok(sideways.every(option=>option.disabled));
  console.log('Negotiated Crab directions, Start/Finish, and return to Walk passed.');
}
run().catch(error=>{console.error(error);process.exitCode=1;});

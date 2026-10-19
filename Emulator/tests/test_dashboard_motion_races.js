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
    classList:{remove(){},add(){},toggle(){}},setAttribute(){},setCustomValidity(value){this.validationMessage=value;},reportValidity(){return !this.validationMessage;} });
  return nodes.get(id);
}
const requests = [];
const windowListeners = new Map();
let gamepads = [];
const context = { console, URLSearchParams, AbortController, navigator:{getGamepads(){return gamepads;}}, localStorage:{getItem(){return null;}},
  document:{getElementById:node, querySelector:node, querySelectorAll(){return [];}},
  window:{addEventListener(type,fn){windowListeners.set(type,fn);},clearTimeout(){}},
  fetch(url,opts){return new Promise((resolve,reject)=>requests.push({url,body:JSON.parse(opts.body),resolve:(seq)=>resolve({ok:true,status:200,json:async()=>typeof seq === "object" ? seq : ({seq})}),reject}));}
};
let source=fs.readFileSync(path.join(__dirname,'../../Master/gateway/dashboard/static/dashboard.js'),'utf8');
source=source.replace('  if (!setupLogin()) {', `
  globalThis.motionTest = {
    select(id) { selectedRobotId=id; variableWalking=directionalWalking=true; steeringSupported=false; availableBodyCommands=null; resetWalking(); updateMotionSpeed(null); updateBalance(null); },
    steering() { steeringSupported=true; setSteeringVector(100,0); },
    state() { return {activeWalkSequence,heldRequestPending,walkRequestPending,activeWalkProfile}; },
    range(supported,crab=false) { runningSupported=supported; crabSupported=crab; updateSpeedRange(); },
    updateBalance,operateBalance,beginHeldMotion,applyWalking,stopMotion,setupMotionControls,updateWalkingStatus,updateMotionSpeed,operateMotionSpeed,sendNamedMotion,pollGamepad
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
  const ready={model:'v2-12servo',epoch:1,features:['motion_speed_v1']};
  api.select('speed-a');api.updateMotionSpeed(ready);
  const staleSpeedRead=requests.at(-1);
  api.select('speed-b');api.updateMotionSpeed(ready);
  const liveSpeedRead=requests.at(-1);
  staleSpeedRead.resolve({seq:2000,motion_speed:{seq:2000,rate:3,saved:true}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(node('motion-speed').value,'2');assert.equal(node('motion-speed').disabled,true);
  liveSpeedRead.resolve({seq:2001,motion_speed:{seq:2001,rate:1.25,saved:true}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(node('motion-speed').value,'1.25');assert.equal(node('motion-speed').disabled,false);
  const beforeEdit=requests.length;
  node('motion-speed').value='2';await node('motion-speed').fire('input');
  assert.equal(requests.length,beforeEdit,'editing speed must not send movement or save');
  const wave=api.sendNamedMotion('emote','wave','Wave sent');
  assert.equal(requests.at(-1).body.params.playback_rate,2);
  assert.equal(requests.at(-1).body.robot_id,'speed-b');requests.at(-1).resolve(2002);await wave;
  const save=api.operateMotionSpeed('save'), staleSave=requests.at(-1);
  assert.equal(staleSave.body.rate,2);assert.equal(staleSave.body.op,'save');
  api.select('speed-a');api.updateMotionSpeed(ready);
  const newRead=requests.at(-1);
  staleSave.resolve({seq:2003,motion_speed:{seq:2003,rate:2,saved:true}});await save;
  assert.equal(node('motion-speed').disabled,true,'old save cannot unlock new robot settings');
  newRead.resolve({seq:2004,motion_speed:{seq:2004,rate:.75,saved:true}});
  await new Promise(resolve=>setImmediate(resolve));assert.equal(node('motion-speed').value,'0.75');
  api.updateMotionSpeed({...ready,features:[]});
  assert.equal(node('motion-speed').disabled,true);
  const legacy=api.sendNamedMotion('emote','wave','Wave sent');
  assert.equal(requests.at(-1).body.params.playback_rate,undefined);requests.at(-1).resolve(2005);await legacy;
  console.log('Motion speed preview, saved readback, feature gating and delayed robot-selection replies passed.');
  const jointReady={...ready,features:['motion_speed_v1','joint_speed_limit_v1'],status:{speed_limited:false}};
  api.select('joint-a');api.updateMotionSpeed(jointReady);
  requests.at(-1).resolve({seq:2100,motion_speed:{seq:2100,rate:2,saved:true,joint_speed_limit_deg_s:545.4545,joint_speed_limit_saved:false}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(node('joint-speed-limit').disabled,false);
  assert.equal(node('joint-speed-limit').value,'545.4545');
  const beforeJointEdit=requests.length;
  node('joint-speed-limit').value='900';await node('joint-speed-limit').fire('input');
  assert.equal(requests.length,beforeJointEdit,'editing a limit sends neither movement nor a save');
  node('motion-speed').value='3';await node('motion-speed').fire('input');
  const limitSave=api.operateMotionSpeed('save','joint_speed_limit_deg_s');
  assert.equal(requests.at(-1).body.joint_speed_limit_deg_s,900);
  assert.equal(requests.at(-1).body.rate,undefined);
  requests.at(-1).resolve({seq:2101,motion_speed:{seq:2101,rate:2,saved:true,joint_speed_limit_deg_s:900,joint_speed_limit_saved:true}});
  await limitSave;
  assert.equal(node('motion-speed').value,'3','saving the limit preserves an unsaved multiplier');
  assert.equal(node('motion-speed-save').disabled,false);
  assert.equal(node('joint-speed-save').disabled,true);
  api.updateMotionSpeed({...jointReady,status:{speed_limited:true}});
  assert.match(node('joint-speed-active').textContent,/Speed limit active/);
  api.updateMotionSpeed({...jointReady,status:{speed_limited:true,gait_cadence:{automatic_run:true,cycles_s:.99,requested_cycles_s:2.22,stride_percent:100,requested_stride_percent:100}}});
  assert.match(node('run-cadence-status').textContent,/0.99 \/ 2.22 requested cycles\/s/);
  assert.match(node('run-cadence-status').textContent,/stride 100.0% \(requested 100.0%\)/);
  assert.match(node('joint-speed-active').textContent,/timing is slowed.*stride is preserved/);
  node('joint-speed-limit').value='0';await node('joint-speed-limit').fire('input');
  const beforeInvalid=requests.length;await api.operateMotionSpeed('save','joint_speed_limit_deg_s');
  assert.equal(requests.length,beforeInvalid);
  node('joint-speed-limit').value='100000';await node('joint-speed-limit').fire('input');
  const highSave=api.operateMotionSpeed('save','joint_speed_limit_deg_s'), staleLimit=requests.at(-1);
  assert.equal(staleLimit.body.joint_speed_limit_deg_s,100000,'the UI imposes no fixed maximum');
  api.select('joint-b');api.updateMotionSpeed(jointReady);
  const jointRead=requests.at(-1);
  staleLimit.resolve({seq:2102,motion_speed:{seq:2102,rate:2,saved:true,joint_speed_limit_deg_s:100000,joint_speed_limit_saved:true}});
  await highSave;
  assert.equal(node('joint-speed-limit').disabled,true,'a stale save cannot unlock another robot');
  jointRead.resolve({seq:2103,motion_speed:{seq:2103,rate:1,saved:true,joint_speed_limit_deg_s:700,joint_speed_limit_saved:true}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(node('joint-speed-limit').value,'700');
  api.updateMotionSpeed(ready);
  assert.equal(node('joint-speed-limit').disabled,true);
  assert.match(node('joint-speed-status').textContent,/firmware update/);
  console.log('Joint speed setting, uncapped values, explicit save, edit preservation, active feedback and robot-selection races passed.');

  const tick=()=>new Promise(resolve=>setImmediate(resolve));
  const key=(type,code)=>windowListeners.get(type)({code,repeat:false,target:{tagName:'BODY'},preventDefault(){}});
  api.select('steering');api.steering();node('walk-gait').value='walk';node('walk-mode').value='auto';node('walk-speed').value='50';
  const vectorStart=api.applyWalking();requests.at(-1).resolve(3000);await vectorStart;
  node('walk-turn').value='40';const curve=node('walk-turn').fire('input');
  assert.equal(requests.at(-1).body.params.forward,100);assert.equal(requests.at(-1).body.params.turn,40);
  assert.equal(requests.at(-1).body.params.update,3000);
  const curveRequest=requests.at(-1),curveCount=requests.length;
  node('walk-turn').value='-70';await node('walk-turn').fire('input');
  node('walk-forward').value='-30';await node('walk-forward').fire('input');
  assert.equal(requests.length,curveCount,'rapid steering edits coalesce behind the outstanding request');
  curveRequest.resolve(3001);await curve;
  assert.equal(requests.at(-1).body.params.forward,-30);assert.equal(requests.at(-1).body.params.turn,-70);
  assert.equal(requests.at(-1).body.params.update,3000);requests.at(-1).resolve(3002);await tick();
  node('walk-direction').value='turn_l';const preset=node('walk-direction').fire('change');
  assert.equal(requests.at(-1).body.params.dir,'fwd','updates retain the original protocol direction');
  assert.equal(requests.at(-1).body.params.forward,0);assert.equal(requests.at(-1).body.params.turn,100);
  requests.at(-1).resolve(3003);await preset;

  api.select('keyboard-steering');api.steering();node('walk-direction').value='fwd';
  const keyboardBase=requests.length;
  key('keydown','ArrowUp');const keyStart=requests.at(-1);
  key('keydown','ArrowLeft');assert.equal(requests.length,keyboardBase+1);
  keyStart.resolve(3100);await tick();
  assert.equal(requests.at(-1).body.params.update,3100);assert.equal(requests.at(-1).body.params.turn,100);
  assert.equal(requests.at(-1).body.params.forward,100);requests.at(-1).resolve(3101);await tick();
  key('keyup','ArrowLeft');assert.equal(requests.at(-1).body.params.forward,100);assert.equal(requests.at(-1).body.params.turn,0);
  requests.at(-1).resolve(3102);await tick();
  key('keyup','ArrowUp');assert.equal(requests.at(-1).body.params.speed,0);assert.equal(requests.at(-1).body.params.update,3100);
  requests.at(-1).resolve(3103);await tick();
  assert.ok(requests.slice(keyboardBase).every(r=>r.url==='/api/intent'),'changing held direction does not issue stop/start');

  api.select('released-before-ack');api.steering();
  key('keydown','ArrowUp');const releasedStart=requests.at(-1);
  key('keydown','ArrowRight');key('keyup','ArrowRight');key('keyup','ArrowUp');
  const releaseStop=requests.at(-1);assert.equal(releaseStop.url,'/api/stop');
  releasedStart.resolve(3200);releaseStop.resolve(3201);await tick();
  assert.equal(api.state().activeWalkSequence,null,'late held start cannot restore released steering');
  assert.equal(requests.at(-1).url,'/api/stop');requests.at(-1).resolve(3202);await tick();

  api.select('gamepad-steering');api.steering();
  gamepads=[{axes:[.65,-.9],buttons:[]}];api.pollGamepad();
  assert.equal(requests.at(-1).body.params.forward,90);assert.equal(requests.at(-1).body.params.turn,-65);
  requests.at(-1).resolve(3300);await tick();
  gamepads[0].axes=[-.8,.7];api.pollGamepad();
  assert.equal(requests.at(-1).body.params.update,3300);assert.equal(requests.at(-1).body.params.forward,-70);assert.equal(requests.at(-1).body.params.turn,80);
  requests.at(-1).resolve(3301);await tick();
  gamepads[0].axes=[0,0];api.pollGamepad();assert.equal(requests.at(-1).body.params.speed,0);
  requests.at(-1).resolve(3302);await tick();gamepads=[];

  api.select('legacy-direction');node('walk-gait').value='walk';
  const legacyStart=api.beginHeldMotion('turn_r');assert.equal(requests.at(-1).body.params.forward,undefined);
  assert.equal(requests.at(-1).body.params.dir,'turn_r');requests.at(-1).resolve(3400);await legacyStart;
  api.select('balance-old');
  const balanceEntry={model:'v2-12servo',epoch:1,features:['balance_control_v1']};
  api.updateBalance(balanceEntry);const oldBalance=requests.at(-1);
  api.select('balance-new');api.updateBalance(balanceEntry);const newBalance=requests.at(-1);
  oldBalance.resolve({seq:3500,balance:{seq:3500,enabled:false,saved:true,active:false}});await tick();
  assert.equal(node('balance-enabled').value,'','old robot reply cannot change selected robot setting');
  newBalance.resolve({seq:3501,balance:{seq:3501,enabled:true,saved:false,active:false}});await tick();
  assert.equal(node('balance-enabled').value,'true');
  const balanceWalk=api.beginHeldMotion('fwd');requests.at(-1).resolve(3502);await balanceWalk;
  node('balance-enabled').value='false';node('balance-enabled').fire('change');
  const countBeforeSave=requests.length;const saveBalance=api.operateBalance('save');
  assert.equal(requests.at(-1).url,'/api/balance');
  assert.deepEqual(requests.at(-1).body,{op:'save',robot_id:'balance-new',enabled:false});
  requests.at(-1).resolve({seq:3503,balance:{seq:3503,enabled:false,saved:true,active:false}});await saveBalance;
  assert.equal(requests.length,countBeforeSave+1,'saving balance does not send a Stop or movement command');
  assert.equal(api.state().activeWalkSequence,3502);
  assert.equal(node('balance-enabled').value,'false');
  api.updateBalance({...balanceEntry,status:{balance:{active:false}}});
  assert.match(node('balance-active').textContent,/inactive/);
  api.select('tunable-balance');
  const tunedEntry={...balanceEntry,features:['balance_control_v1','balance_tuning_v1']};
  api.updateBalance(tunedEntry);
  const tuning={strength:1,damping:1,roll_deg:0,pitch_deg:0,tuning_saved:false};
  requests.at(-1).resolve({seq:3600,balance:{seq:3600,enabled:false,saved:true,active:false,...tuning}});await tick();
  node('balance-strength').value='1.75';node('balance-strength').fire('input');
  node('balance-pitch_deg').value='3';node('balance-pitch_deg').fire('input');
  api.updateBalance(tunedEntry);assert.equal(node('balance-strength').value,'1.75','polling preserves unsaved tuning');
  const saveTuned=api.operateBalance('save');
  assert.deepEqual(requests.at(-1).body,{op:'save',robot_id:'tunable-balance',enabled:false,strength:1.75,damping:1,roll_deg:0,pitch_deg:3});
  requests.at(-1).resolve({seq:3601,balance:{seq:3601,enabled:false,saved:true,active:false,...tuning,strength:1.75,pitch_deg:3,tuning_saved:true}});await saveTuned;
  assert.equal(node('balance-strength').value,'1.75');assert.equal(node('balance-save').disabled,true);
  const countBeforeDefaults=requests.length;node('balance-defaults').fire('click');
  assert.equal(node('balance-enabled').value,'false','default response does not turn leveling on');
  assert.equal(node('balance-strength').value,'1');assert.equal(node('balance-pitch_deg').value,'0');
  assert.equal(node('balance-save').disabled,false);assert.equal(requests.length,countBeforeDefaults,'defaults require explicit save');
  console.log('Self-leveling tuning readback, edit preservation and explicit defaults passed.');
  const roll=-2*Math.PI/180,pitch=-3*Math.PI/180;
  const orientation=[Math.cos(roll/2)*Math.cos(pitch/2),Math.sin(roll/2)*Math.cos(pitch/2),
    Math.cos(roll/2)*Math.sin(pitch/2),-Math.sin(roll/2)*Math.sin(pitch/2)];
  const feedbackEntry={...tunedEntry,features:[...tunedEntry.features,'balance_feedback_v1'],status:{
    imu:{available:true,fresh:true,received_at:new Date().toISOString(),calibration_applied:true,orientation_wxyz:orientation},
    balance:{active:false,roll_rad:0,pitch_rad:0,roll_correction_rad:.1,pitch_correction_rad:.2,
      legs_valid:true,extension_mm:[-1,-2,3,4],joint_delta_deg:[0,10,11,0,20,21,0,30,31,0,40,41]}}};
  api.updateBalance(feedbackEntry);
  assert.match(node('balance-tilt').textContent,/-2.00°/,'fresh IMU is displayed even while cached balance angles are zero');
  assert.match(node('balance-tilt').textContent,/\+3.00°/,'pitch uses nose-up sign');
  assert.match(node('balance-correction').textContent,/-11.46°/);
  assert.equal(node('balance-leg-0').textContent,'1.00 mm shorter');
  assert.equal(node('balance-leg-2').textContent,'3.00 mm longer');
  assert.equal(node('balance-carrier-0').textContent,'+30.00°','front left is model joint 7');
  assert.equal(node('balance-crank-3').textContent,'+21.00°','rear right is model joint 5');
  api.updateBalance({...feedbackEntry,status:{...feedbackEntry.status,balance:{...feedbackEntry.status.balance,
    joint_feedback:{available:true,active:true,reduced:false,gain:.5,tolerance_us:120,
      error_deg:[0,1,2,3,4,5,6,7,8,9,10,11],trim_deg:[0,.5,1,1.5,2,2.5,3,3.5,4,4.5,5,5.5]}}}});
  assert.match(node('balance-joint-feedback').textContent,/active.*0.5/);
  assert.match(node('balance-joint-feedback').textContent,/±120 µs/);
  assert.match(node('balance-joint-errors').textContent,/Front left: \+6.00° \/ \+7.00° \/ \+8.00°/);
  assert.match(node('balance-joint-trims').textContent,/Rear right: \+1.50° \/ \+2.00° \/ \+2.50°/);
  api.updateBalance({...feedbackEntry,status:{...feedbackEntry.status,balance:{...feedbackEntry.status.balance,
    joint_feedback:{available:true,active:true,reduced:false,mode:"actuator_tracking",gain:0,tolerance_us:120,
      body_lag_rad:[.02,-.03],error_deg:Array(12).fill(1),trim_deg:Array(12).fill(0)}}}});
  assert.match(node('balance-joint-feedback').textContent,/Measured actuator tracking active/);
  assert.match(node('balance-joint-trims').textContent,/roll \+1.15°.*pitch \+1.72°/);
  api.updateBalance({...feedbackEntry,status:{...feedbackEntry.status,balance:{...feedbackEntry.status.balance,
    active:false,settled:true,settle_deg:.5,wake_deg:1,
    joint_feedback:{available:true,active:false,reduced:false,gain:.5,tolerance_us:120}}}});
  assert.match(node('balance-active').textContent,/Level reached.*monitoring only.*0.5°.*1°/);
  assert.match(node('balance-joint-feedback').textContent,/resting/);
  assert.equal(node('balance-joint-trims').textContent,'');
  api.updateBalance({...feedbackEntry,status:{...feedbackEntry.status,balance:{...feedbackEntry.status.balance,
    joint_feedback:{available:false,active:false,reduced:false,gain:.5}}}});
  assert.match(node('balance-joint-feedback').textContent,/unavailable; gyro-only/);
  assert.equal(node('balance-joint-errors').textContent,'');
  api.updateBalance(feedbackEntry);
  const beforeReference=requests.length;
  node('balance-reference').fire('click');
  assert.equal(Number(node('balance-roll_deg').value),-2);
  assert.equal(Number(node('balance-pitch_deg').value),3);
  assert.equal(node('balance-enabled').value,'false');
  assert.equal(requests.length,beforeReference,'capturing reference is a draft until explicit save');
  const referenceSave=api.operateBalance('save');
  assert.deepEqual(requests.at(-1).body,{op:'save',robot_id:'tunable-balance',enabled:false,strength:1,damping:1,roll_deg:-2,pitch_deg:3});
  requests.at(-1).resolve({seq:3700,balance:{seq:3700,enabled:false,saved:true,active:false,...tuning,roll_deg:-2,pitch_deg:3,tuning_saved:true}});await referenceSave;
  api.updateBalance(feedbackEntry);
  assert.match(node('balance-error').textContent,/roll [+-]0.00° · pitch [+-]0.00°/);
  const gyroRequest=node('balance-gyro-calibrate').fire('click');
  assert.deepEqual(requests.at(-1).body,{op:'calibrate_gyro',robot_id:'tunable-balance'});
  requests.at(-1).resolve({seq:3701,balance:{seq:3701,enabled:false,saved:true,active:false,...tuning}});await gyroRequest;
  assert.equal(requests.length,beforeReference+2,'only explicit save and gyro sampling commands, no motion or Stop');
  const staleEntry={...feedbackEntry,status:{...feedbackEntry.status,imu:{...feedbackEntry.status.imu,received_at:'2000-01-01T00:00:00Z'}}};
  api.updateBalance(staleEntry);
  assert.equal(node('balance-reference').disabled,true);
  assert.match(node('balance-sensor').textContent,/stale/);
  assert.equal(node('balance-tilt').textContent,'');
  api.select('other-feedback-robot');
  assert.equal(node('balance-reference').disabled,true);
  assert.equal(node('balance-leg-0').textContent,'—');
  console.log('Live IMU signs, physical leg order, zero-reference save, stale samples and explicit gyro calibration passed.');
  console.log('Self-leveling readback, selected robot races and saving without interrupting Walk passed.');
  console.log('Combined steering, direction presets, coalesced updates, two-key driving, gamepad curves, release-before-ACK and legacy controls passed.');

}
run().catch(error=>{console.error(error);process.exitCode=1;});

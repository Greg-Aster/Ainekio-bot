/* Real feedback UI handlers with a deferred transport: no robot commands. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = new Map(), requests = [];
function element() {
  return {value:'', checked:false, hidden:false, children:[], listeners:{},
    addEventListener(type, fn){this.listeners[type]=fn;},
    fire(type){this.listeners[type]?.({preventDefault(){}});},
    appendChild(child){this.children.push(child);},
    replaceChildren(){this.children=[];},
    add(option){this.children.push(option);if(this.value==='')this.value=option.value;},
    querySelectorAll(){return [];}, reportValidity(){return true;}};
}
function node(id){if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);}
const config=node('servo-feedback-config'), calibration=node('servo-feedback-calibration');
config.elements=Object.fromEntries(['enabled','stand_enabled','jam_enabled','tolerance_us','arrival_tolerance_us','no_progress_ms','progress_us'].map(k=>[k,element()]));
calibration.elements=Object.fromEntries(['joint','channel','point','pulse_us'].map(k=>[k,element()]));
const context={console,URLSearchParams,Option:function(text,value){this.text=text;this.value=value;},
  document:{getElementById:node,createElement:element},window:{addEventListener(){}},
  fetch(url,options){return new Promise(resolve=>requests.push({url,options,
    resolve(data,ok=true){resolve({ok,status:ok?200:502,json:async()=>data});}}));}};
let source=fs.readFileSync('Master/gateway/dashboard/static/dashboard.js','utf8');
source=source.replace('  if (!setupLogin()) {',`
  globalThis.api={setupServoFeedback,readServoFeedback,
    select(id,epoch=1){selectedRobotId=id;updateServoFeedback({connected:true,model:'v2-12servo',epoch,features:['servo_feedback_v1']});},
    state(){return servoFeedbackData;}};
  if(false){`);
vm.createContext(context);vm.runInContext(source,context);
const api=context.api,tick=()=>new Promise(resolve=>setImmediate(resolve));
const data={enabled:true,stand_enabled:false,jam_enabled:false,tolerance_us:400,arrival_tolerance_us:30,scan:50,scan_us:500,revision:2,
  device_us:100000,error:'ESP_OK',stand_waiting:true,stand_progress:.25,waiting_joints:4,
  channels:Array.from({length:16},(_,channel)=>({channel,valid:true,raw:2000+channel,
    sampled_us:99000,spread:2,millivolts:1700})),
  joints:Array.from({length:12},(_,id)=>({id,channel:id,calibrated:true,command_us:1650,
    measured_us:1600,error_us:50,in_calibrated_range:true,points:[null,null,null]}))};
(async()=>{
  api.setupServoFeedback();api.select('a');
  assert.match(requests.at(-1).url,/robot_id=a/);
  requests.at(-1).resolve(data);await tick();
  assert.equal(node('servo-feedback-rows').children.length,12);
  assert.match(node('servo-feedback-motion').textContent,/Checking commanded joint targets/);
  assert.doesNotMatch(node('servo-feedback-motion').textContent,/Stand:/);
  assert.equal(calibration.elements.channel.value,0);
  let healthRead=api.readServoFeedback();
  requests.at(-1).resolve({...data,health:{enabled:true,usable:false,
    unavailable_mask:0,clipped_mask:0,below_calibration_mask:1,above_calibration_mask:0,
    signal_millivolts:[120,...Array(11).fill(1600)]}});await healthRead;
  assert.match(node('servo-feedback-health').textContent,/Rear left shoulder 0.120 V/);
  assert.match(node('servo-feedback-health').textContent,/Programmed motion continues/);
  assert.match(node('servo-feedback-health').textContent,/supply voltage is not monitored/);
  config.elements.jam_enabled.checked=true;
  config.elements.arrival_tolerance_us.value='75';
  config.elements.no_progress_ms.value='1500';config.elements.progress_us.value='8';
  config.fire('submit');
  assert.equal(JSON.parse(requests.at(-1).options.body).no_progress_ms,1500);
  assert.equal(JSON.parse(requests.at(-1).options.body).progress_us,8);
  assert.equal(JSON.parse(requests.at(-1).options.body).jam_enabled,true);
  assert.equal(JSON.parse(requests.at(-1).options.body).stand_enabled,false);
  assert.equal(JSON.parse(requests.at(-1).options.body).arrival_tolerance_us,75);
  assert.equal(JSON.parse(requests.at(-1).options.body).tolerance_us,400);
  requests.at(-1).resolve({...data,no_progress_ms:1500,progress_us:8});await tick();
  config.elements.stand_enabled.checked=true;config.elements.jam_enabled.checked=false;
  config.fire('submit');
  assert.equal(JSON.parse(requests.at(-1).options.body).jam_enabled,false);
  assert.equal(JSON.parse(requests.at(-1).options.body).stand_enabled,true);
  requests.at(-1).resolve({...data,stand_enabled:true});await tick();
  let legacy=api.readServoFeedback();
  const old={...data};delete old.jam_enabled;delete old.arrival_tolerance_us;
  requests.at(-1).resolve(old);await legacy;
  assert.equal(config.elements.jam_enabled.disabled,true);
  assert.equal(config.elements.arrival_tolerance_us.disabled,true);
  assert.match(node('servo-feedback-jam-support').textContent,/firmware update/);
  config.fire('submit');
  assert.equal('jam_enabled' in JSON.parse(requests.at(-1).options.body),false);
  assert.equal('arrival_tolerance_us' in JSON.parse(requests.at(-1).options.body),false);
  requests.at(-1).resolve(data);await tick();
  assert.equal(config.elements.jam_enabled.disabled,false);
  let fault=api.readServoFeedback();requests.at(-1).resolve({...data,stand_waiting:false,stalled_joints:48,stall_clock_us:12345});await fault;
  assert.match(node('servo-feedback-motion').textContent,/Rear right carrier, Rear right crank/);
  assert.match(node('servo-feedback-motion').textContent,/All servo outputs were released/);
  config.elements.tolerance_us.value='45';config.fire('input');
  let poll=api.readServoFeedback();requests.at(-1).resolve(data);await poll;
  assert.equal(config.elements.tolerance_us.value,'45','poll preserves unsaved settings');
  calibration.elements.point.value='1';calibration.elements.pulse_us.value='1650';
  poll=api.readServoFeedback();const oldPoll=requests.at(-1);
  calibration.fire('submit');const save=requests.at(-1);
  assert.notEqual(save,oldPoll,'calibration click during a poll must not be dropped');
  assert.deepEqual(JSON.parse(save.options.body),{op:'capture',joint:0,point:1,
    pulse_us:1650,raw:2000,scan:50,revision:2});
  save.resolve({...data,revision:3});await tick();oldPoll.resolve(data);await poll;
  assert.equal(api.state().revision,3,'old poll cannot overwrite saved calibration');
  poll=api.readServoFeedback();const oldRobot=requests.at(-1);
  api.select('b');oldRobot.resolve(data);await poll;
  assert.equal(api.state(),null,'old robot measurements cannot appear for a new robot');
  requests.at(-1).resolve(data);await tick();
  poll=api.readServoFeedback();requests.at(-1).resolve({error:'offline'},false);await poll;
  assert.equal(api.state(),null);assert.equal(node('servo-feedback-rows').children.length,0);
  assert.match(node('servo-feedback-result').textContent,/offline/);
  assert(requests.every(r=>r.url.startsWith('/api/robot/servo-feedback?')),
    'feedback controls must not issue motion or raw joint commands');
  console.log('Servo feedback display, calibration, drafts, concurrent polls, robot switching and errors passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});

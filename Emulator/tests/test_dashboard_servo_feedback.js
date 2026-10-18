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
config.elements=Object.fromEntries(['enabled','stand_enabled','tolerance_us'].map(k=>[k,element()]));
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
const data={enabled:true,stand_enabled:false,tolerance_us:30,scan:50,scan_us:500,revision:2,
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
  assert.match(node('servo-feedback-motion').textContent,/waiting for measured arrival/);
  assert.match(node('servo-feedback-motion').textContent,/Stand 25%/);
  assert.equal(calibration.elements.channel.value,0);
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

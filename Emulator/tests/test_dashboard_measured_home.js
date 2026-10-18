/* Production measured-Home capture and existing save owner; no hardware access. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = new Map(), storage = new Map(), calls = [];
function node(id) {
  if (!nodes.has(id)) nodes.set(id, {value:'', classList:{toggle(){}}, reportValidity(){return true;}});
  return nodes.get(id);
}
node('servo-form').elements = {id:{value:'2'}};
const form = node('body-calibration-form');
form.elements = Object.fromEntries(['id','channel','center','home_deg','us_per_degree','invert'].map(k=>[k,{value:'',checked:false}]));
let measured = 2780.4, valid = true, calibrated = true, hold = null, sequence = 0;
let robotMapping;
function feedback() {
  return {enabled:true,device_us:100000,scan:7,
    channels:[{channel:6,valid,raw:3210,millivolts:3150,sampled_us:99000,spread:2}],
    joints:[{id:Number(node('servo-form').elements.id.value),channel:6,calibrated,command_us:2800,measured_us:measured,model_deg:-113.04}]};
}
const context = {console,URLSearchParams,AbortController,
  document:{getElementById:node},window:{addEventListener(){},setTimeout,clearTimeout},
  localStorage:{getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,v)},
  FormData:class {constructor(f){this.f=f;} get(k){return this.f.elements[k].value;}},
  async fetch(url,options) {
    const body = options.body ? JSON.parse(options.body) : null;
    calls.push({url,body});
    let data;
    if (url.startsWith('/api/robot/servo-feedback?')) { if (hold) await hold; data=feedback(); }
    else {
      assert.equal(url,'/api/calibration/body');
      assert(['set','save'].includes(body.op),'Capture/save must not move or Home the robot');
      if (body.op==='set') {
        const {op,robot_id,...fields}=body;
        robotMapping.joints[body.id]={...robotMapping.joints[body.id],...fields};
      }
      const seq=++sequence;
      data={seq,calibration:{...robotMapping,seq,saved:body.op==='save',dirty:body.op!=='save'}};
    }
    return {ok:true,status:200,json:async()=>data};
  }};
let source=fs.readFileSync('Master/gateway/dashboard/static/dashboard.js','utf8');
source=source.replace('  if (!setupLogin()) {',`
  renderCalibration=()=>{}; fillCalibrationFields=()=>{}; showResult=()=>{};
  globalThis.api={captureMeasuredHome,saveBodyCalibration,renderCalibrationFeedback,
    select(robot,mapping){selectedRobotId=robot;calibrationGeneration++;servoFeedbackSession=robot;
      calibrationData=mapping;servoFeedbackSupported=true;
      calibrationEntry={model:'v2-12servo',features:['body_calibration_v2']};},
    feedback(data){servoFeedbackData=data;renderCalibrationFeedback();},
    draft:()=>calibrationDraft(), reference(value){calibrationDraft().homeReference=value;}};
  if(false){`);
vm.createContext(context);vm.runInContext(source,context);
const api=context.api;
function reset(invert=true) {
  valid=true;calibrated=true;measured=2780.4;hold=null;
  robotMapping={joints:Array.from({length:12},(_,id)=>({id,channel:id,home_us:1650,home_cd:0,us_per_degree:10,invert,pulse_us:2800}))};
  api.select('a',robotMapping);node('servo-form').elements.id.value='2';
  Object.entries({id:'2',channel:'2',center:'1650',home_deg:'0',us_per_degree:'10'}).forEach(([k,v])=>form.elements[k].value=v);
  form.elements.invert.checked=invert;api.reference('rearward');
}
(async()=>{
  reset();api.feedback(feedback());
  assert.match(node('calibration-feedback-raw').textContent,/3210.*3.150 V/);
  assert.match(node('calibration-feedback-position').textContent,/2780.4/);
  assert.equal(node('calibration-feedback-error').textContent,'19.6 µs');
  await api.captureMeasuredHome();
  assert.equal(form.elements.center.value,'2780','Use measured position, not 2800 command');
  assert.equal(form.elements.home_deg.value,'-117.68','Use the shared physical reference, not the old inferred angle');
  assert.equal(api.draft().fields.center,'2780');
  assert(calls.every(c=>!c.body),'Capture is read-only');
  const oldOthers=JSON.stringify(robotMapping.joints.filter(j=>j.id!==2));
  await api.saveBodyCalibration();
  assert.equal(robotMapping.joints[2].home_us,2780);
  assert.equal(robotMapping.joints[2].home_cd,-11768);
  assert.equal(JSON.stringify(robotMapping.joints.filter(j=>j.id!==2)),oldOthers,'Save affects only selected joint');
  assert.deepEqual(calls.filter(c=>c.body).map(c=>c.body.op),['set','save']);
  assert.match(node('calibration-feedback').textContent,/saved.*read back successfully/);
  // Every corresponding physical Home must receive the same geometric angle,
  // despite different old mappings, sensor readings and mirrored directions.
  for (const id of [1,2,4,5,7,8,10,11]) {
    reset(id<3 || id===7 || id===8);
    node('servo-form').elements.id.value=String(id);
    api.reference('rearward');
    measured=500+id*157.2;
    form.elements.home_deg.value=String(id*9.3);
    const invert=form.elements.invert.checked;
    await api.captureMeasuredHome();
    const reference=id%3===1?-30.87:-117.68;
    assert.equal(Number(form.elements.home_deg.value),reference);
    assert.equal(Number(form.elements.center.value),Math.round(measured));
    assert.equal(form.elements.invert.checked,invert);
    assert.equal(form.elements.us_per_degree.value,'10');
    // A matching target 10 degrees from Home uses equal travel in mirrored directions.
    const pulse=Number(form.elements.center.value)+(reference+10-Number(form.elements.home_deg.value))*10*(invert?-1:1);
    assert.equal(pulse-Math.round(measured),invert?-100:100);
  }
  reset();api.reference('custom');form.elements.home_deg.value='12.34';
  await api.captureMeasuredHome();
  assert.equal(form.elements.home_deg.value,'12.34','Custom reference is retained, not shifted by measured pulse');
  reset();node('servo-form').elements.id.value='0';api.reference('custom');
  form.elements.home_deg.value='0';await api.captureMeasuredHome();
  assert.equal(form.elements.home_deg.value,'0.00','Shoulder uses its own explicit reference');
  reset();valid=false;await api.captureMeasuredHome();
  assert.equal(form.elements.center.value,'1650');assert.match(node('calibration-feedback').textContent,/Home was not changed/);
  reset();calibrated=false;await api.captureMeasuredHome();assert.equal(form.elements.center.value,'1650');
  reset();measured=null;await api.captureMeasuredHome();assert.equal(form.elements.center.value,'1650');
  for (const change of ['robot','joint','edit','reference']) {
    reset();let resume;hold=new Promise(r=>resume=r);
    const pending=api.captureMeasuredHome();
    if(change==='robot')api.select('b',robotMapping);
    if(change==='joint')node('servo-form').elements.id.value='5';
    if(change==='edit')form.elements.center.value='1700';
    if(change==='reference')api.reference('custom');
    resume();await pending;
    assert.equal(form.elements.center.value,change==='edit'?'1700':'1650','Late response cannot overwrite another robot, joint or new edits');
  }
  reset();api.feedback(null);
  assert.equal(node('calibration-feedback-position').textContent,'—','Clear old measurements on loss of feedback');
  console.log('Measured Home: live wire readings, measured capture, common physical references across mirrored joints, selected-joint save/readback, unavailable data and selection/edit races passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});

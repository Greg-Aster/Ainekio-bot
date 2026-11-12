/* Exercise production gyro-guided calibration without sending robot commands. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map(),storage=new Map(),calls=[];
function node(id){if(!nodes.has(id))nodes.set(id,{value:'',hidden:false,listeners:{},addEventListener(t,f){this.listeners[t]=f;}});return nodes.get(id);}
node('servo-form').elements={id:{value:'2'}};
node('gyro-joint-step').value='60';node('gyro-joint-roll').value='0';node('gyro-joint-pitch').value='0';
const mapping=Array.from({length:12},(_,id)=>({id,channel:id,home_us:1650,home_cd:0,invert:id%2===0,us_per_degree:10,pulse_us:1650}));
let roll=1,pitch=2,mode='normal',pauseStatus=null;
function imu(){const r=roll*Math.PI/360,p=-pitch*Math.PI/360;return {available:true,fresh:true,received_at:new Date().toISOString(),orientation_wxyz:[Math.cos(r)*Math.cos(p),Math.sin(r)*Math.cos(p),Math.cos(r)*Math.sin(p),-Math.sin(r)*Math.sin(p)]};}
function entry(){return {connected:true,epoch:1,model:'v2-12servo',mode,features:['body_calibration_v2'],status:{imu:imu()}};}
const context={console,URLSearchParams,document:{getElementById:node},window:{addEventListener(){}},localStorage:{getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,v)},
 async fetch(url,options){const payload=options.body?JSON.parse(options.body):null;calls.push({url,payload});
  let data;
  if(url==='/api/status'){if(pauseStatus)await pauseStatus;data={robots:{a:entry(),b:entry()}};}
  else if(url.startsWith('/api/robot/servo-feedback'))data={joints:mapping.map(j=>({id:j.id,measured_us:j.pulse_us-3,command_us:j.pulse_us}))};
  else if(url==='/api/calibration/body'){
   if(payload.op==='move')mapping[payload.id].pulse_us=payload.pulse_us;
   data={seq:1,calibration:{joints:mapping.map(j=>({...j}))}};
  }else if(url==='/api/motion-plan'){
   mapping.forEach((j,i)=>j.pulse_us=Math.round(j.home_us+(payload.frames[0][1][i]-j.home_cd)/100*j.us_per_degree*(j.invert?-1:1)));
   data={seq:2};
  }else throw Error(url);
  return {ok:true,status:200,json:async()=>data};
 }};
let source=fs.readFileSync('Master/gateway/dashboard/static/dashboard.js','utf8');
source=source.replace('  if (!setupLogin()) {',`globalThis.api={operateGyroJoint,renderGyroJointGuide,
select(id){selectedRobotId=id;calibrationEntry=${'entryForTest()'};renderGyroJointGuide();}};if(false){`);
context.entryForTest=entry;vm.createContext(context);vm.runInContext(source,context);
(async()=>{
 const a=context.api;a.select('a');
 await a.operateGyroJoint('plus');
 assert.equal(mapping[2].pulse_us,1710);
 assert(mapping.every((j,i)=>i===2||j.pulse_us===1650),'Other joints retain their targets');
 const plan=calls.find(c=>c.url==='/api/motion-plan').payload;
 assert.equal(plan.frames[0][1][2],-600,'Inverted mapping must convert pulse to model angle');
 assert.equal(plan.end,'hold');assert.equal(plan.frames[0][0],20);
 roll=2;pitch=3;await a.operateGyroJoint('capture');
 const saved=JSON.parse(storage.get('ainekio-gyro-joint-v1:a:2'));
 assert.equal(saved.delta,60);assert.equal(saved.measured,60);assert(Math.abs(saved.roll-1)<1e-6);assert(Math.abs(saved.pitch-1)<1e-6);
 await a.operateGyroJoint('restore');assert.equal(mapping[2].pulse_us,1650);
 await a.operateGyroJoint('correct');assert.equal(mapping[2].pulse_us,1590,'Observed slope chooses a negative correction toward zero');
 assert(calls.every(c=>c.payload?.op!=='save'&&c.payload?.op!=='set'),'Trials never change Home calibration');
 a.select('b');await a.operateGyroJoint('correct');assert.match(node('gyro-joint-result').textContent,/Capture a response/);
 mode='calibrate';await a.operateGyroJoint('minus');assert.equal(calls.at(-1).url,'/api/calibration/body');assert.equal(calls.at(-1).payload.op,'move');
 let resume;pauseStatus=new Promise(r=>resume=r);a.select('a');const pending=a.operateGyroJoint('plus');a.select('b');const count=calls.filter(c=>c.url==='/api/motion-plan'||c.payload?.op==='move').length;resume();await pending;
 assert.equal(calls.filter(c=>c.url==='/api/motion-plan'||c.payload?.op==='move').length,count,'Late snapshots cannot move a newly selected robot');
 console.log('Gyro joint trials: mirrored mapping, held joints, measured response, restore, zero-target step, calibration ownership and robot selection passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});

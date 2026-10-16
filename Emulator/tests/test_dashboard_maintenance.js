/* Exercise production maintenance handlers, including delayed selected-robot replies. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = new Map(), requests = [];
function node(id) {
  if (!nodes.has(id)) nodes.set(id, {value:'', files:[], options:[],
    replaceChildren(){this.options=[];this.value='';},
    add(option){this.options.push(option);if(!this.value)this.value=option.value;}});
  return nodes.get(id);
}
const context = {console, URLSearchParams, Option:function(text,value){this.text=text;this.value=value;},
  document:{getElementById:node}, window:{addEventListener(){}},
  fetch(url,opts){return new Promise(resolve=>requests.push({url,opts,resolve(data,ok=true){resolve({ok,status:ok?200:502,json:async()=>data,text:async()=>typeof data === "string" ? data : JSON.stringify(data)});}}));}};
let source = fs.readFileSync('Master/gateway/dashboard/static/dashboard.js','utf8');
source = source.replace('  if (!setupLogin()) {', `
 globalThis.api = {readControllerLogs,refreshMaintenance,refreshRecordings,operateMaintenance,renderMaintenance,
 select(id){selectedRobotId=id;calibrationEntry={model:'v2-12servo',connection_state:'online',features:['storage_control_v1'],capabilities:{storage:true}};recordingData=firmwareData=null;maintenanceError='';},
 state(){return {recordingData,firmwareData};}};
 if (false) {`);
vm.createContext(context); vm.runInContext(source,context);
const api=context.api, tick=()=>new Promise(resolve=>setImmediate(resolve));
const recording={recording:true,frames:42,dropped:0,segments:1,free_bytes:1048576,mounted:true,error:'ESP_OK',storage_error:'ESP_OK'};
const firmware={state:'staged',running:'ota_0',boot:'ota_0',version:'test',error:'ESP_OK'};
(async()=>{
  api.select('robot-a');
  let pending=api.refreshMaintenance();
  assert.match(requests.at(-1).url,/recording\?robot_id=robot-a/);
  requests.at(-1).resolve(recording);await tick();
  api.select('robot-b');requests.at(-1).resolve(firmware);await pending;
  assert.equal(api.state().recordingData,null,'late read must not update another robot');
  pending=api.refreshMaintenance();requests.at(-1).resolve(recording);await tick();requests.at(-1).resolve(firmware);await pending;
  assert.match(node('recording-details').textContent,/Recording.*42 frames/);
  assert.equal(node('recording-start-button').disabled,true);
  assert.equal(node('recording-stop-button').disabled,false);
  assert.equal(node('firmware-restart-button').disabled,false);
  pending=api.refreshMaintenance();requests.at(-1).resolve({error:'Robot unavailable'},false);await pending;
  assert.equal(node('recording-details').textContent,'Robot unavailable','errors must not be replaced by stale status');
  pending=api.refreshRecordings();requests.at(-1).resolve({files:[{name:'video-1234abcd-00000001.avi',bytes:2048,complete:true}]});await pending;
  assert.equal(node('recordings-select').value,'video-1234abcd-00000001.avi');
  assert.equal(node('recording-download-button').disabled,false);
  pending=api.operateMaintenance('recording','stop');
  assert.deepEqual(JSON.parse(requests.at(-1).opts.body),{op:'stop'});
  assert.match(requests.at(-1).url,/robot_id=robot-b/);
  api.select('robot-c');const count=requests.length;requests.at(-1).resolve({...recording,recording:false});await pending;
  assert.equal(requests.length,count,'old operation must not refresh or command a newly selected robot');
  assert.equal(api.state().recordingData,null);
  pending=api.readControllerLogs();requests.at(-1).resolve('Boot accepted; reset reason 3');await pending;
  assert.equal(node('controller-logs-output').textContent,'Boot accepted; reset reason 3');
  pending=api.readControllerLogs();api.select('robot-d');requests.at(-1).resolve('old robot log');await pending;
  assert.notEqual(node('controller-logs-output').textContent,'old robot log');
  console.log('Maintenance status, errors, recording commands, downloads and selected-robot races passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});

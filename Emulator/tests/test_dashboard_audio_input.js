/* Exercise the audio renderer across live status, disconnect and reconnect. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = new Map();
function element() {
  return {value:'', checked:false, disabled:false, textContent:'',
    classList:{toggle(){}}, contains(){return false;}, querySelector(){return element();}};
}
function node(id) {
  if (!nodes.has(id)) nodes.set(id,element());
  return nodes.get(id);
}
for (const [id,fields] of Object.entries({
  'microphone-form':['on','gate','gain_db'],
  'wake-form':['enabled','model','sensitivity'],
  'speaker-form':['volume_percent'],
})) node(id).elements=Object.fromEntries(fields.map(name=>[name,element()]));
const context={console,document:{getElementById:node,querySelectorAll(){return [];},activeElement:null},
  window:{addEventListener(){}},fetch(){throw new Error('Rendering must not send commands');}};
let source=fs.readFileSync('Master/gateway/dashboard/static/dashboard.js','utf8');
source=source.replace('  if (!setupLogin()) {',`
  globalThis.renderAudioInput=renderAudioInput;
  if(false){`);
vm.createContext(context);vm.runInContext(source,context);
const entry={epoch:1,features:['audio_input_v1'],capabilities:{speaker:true},audio_input_age_ms:20,
  audio_input:{on:true,listening:true,gate:'wake',gain_db:30,wake_enabled:true,
    wake_threshold:.65,rms:.05,peak:.1,speaker_volume_percent:100}};
context.renderAudioInput(entry,true,{wake_model:'ainekio'});
assert.match(node('microphone-level-status').textContent,/Listening/);
context.renderAudioInput({...entry,external_speech_error:'link unavailable'},true,{});
assert.match(node('microphone-level-help').textContent,/link unavailable/);
for (const absent of [undefined,null]) {
  context.renderAudioInput(absent,false,undefined);
  assert.equal(node('microphone-level-status').textContent,'Robot offline');
  assert.match(node('microphone-level-help').textContent,/reconnects/);
  assert.equal(node('microphone-level').value,0);
}
context.renderAudioInput({...entry,epoch:2},true,{});
assert.match(node('microphone-level-status').textContent,/Listening/);
assert.doesNotMatch(node('microphone-level-help').textContent,/link unavailable|reconnects/);
console.log('Audio input renders live, disconnected and reconnected robots without sending commands.');

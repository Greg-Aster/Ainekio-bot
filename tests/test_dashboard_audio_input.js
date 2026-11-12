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
  'microphone-form':['on','gate','gain_db','vad_mode','silence_s','max_recording_s'],
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
assert.equal(node('microphone-form').elements.vad_mode.disabled,true);
assert.match(node('speech-settings-state').textContent,/Update.*firmware/);
const upgraded={...entry,audio_input:{...entry.audio_input,vad_mode:2,silence_ms:2000,max_recording_ms:15000}};
context.renderAudioInput(upgraded,true,{});
assert.equal(node('microphone-form').elements.vad_mode.disabled,false);
assert.equal(node('microphone-form').elements.vad_mode.value,2);
assert.equal(node('microphone-form').elements.silence_s.value,2);
assert.equal(node('microphone-form').elements.max_recording_s.value,15);
assert.match(node('speech-settings-state').textContent,/Medium.*2s pause.*15s maximum/);
assert.match(node('microphone-level-status').textContent,/Listening/);
context.renderAudioInput({...entry,external_speech_error:'link unavailable'},true,{});
assert.match(node('microphone-level-help').textContent,/link unavailable/);
for (const absent of [undefined,null]) {
  context.renderAudioInput(absent,false,undefined);
  assert.equal(node('microphone-level-status').textContent,'Robot offline');
  assert.match(node('microphone-level-help').textContent,/reconnects/);
  assert.equal(node('microphone-level').value,0);
  assert.equal(node('microphone-form').elements.silence_s.disabled,true);
}
context.renderAudioInput({...entry,epoch:2},true,{});
assert.match(node('microphone-level-status').textContent,/Listening/);
assert.doesNotMatch(node('microphone-level-help').textContent,/link unavailable|reconnects/);
console.log('Audio input renders live, disconnected and reconnected robots without sending commands.');

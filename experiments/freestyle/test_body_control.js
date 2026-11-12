const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = new Map(), created = [], calls = [];
function node(id) {
  if (!nodes.has(id)) nodes.set(id,{value:'',checked:false,dataset:{},listeners:{},children:[],
    append(child){this.children.push(child);}, replaceChildren(){this.children=[];}, addEventListener(type,handler){this.listeners[type]=handler;},
    after(child){this.nextSibling=child;},click(){this.clicked=true;},scrollIntoView(){this.scrolled=true;},
    querySelector(selector){return node(selector);}});
  return nodes.get(id);
}
const context = {window:{},Blob,URL:{createObjectURL(){return 'blob:test';},revokeObjectURL(){}},document:{getElementById:node,querySelector:node,
  createElement(tag){const item=node(tag+created.length);created.push(item);return item;}},
  async fetch(url, options={}) {
    const payload=options.body ? JSON.parse(options.body) : null;
    calls.push({url,payload,headers:options.headers});
    return {ok:true,json:async()=>url==='/api/session' ? {csrf:'test-csrf'} :
      payload?.operation==='trial' ? {job:{id:'test-job',execute:false}} :
      payload?.operation==='corrections' ? {corrections:[{review_id:'review-1',title:'Wave trial',request:'Wave to an audience'}]} : {job_id:'test-job'}};
  }};
node('motion-system').checked=true;
vm.runInNewContext(fs.readFileSync('experiments/freestyle/body_control.js','utf8'),context);
(async()=>{
  assert.equal(calls.length,0,'Loading the optional workspace must not enable recovery or send commands');
  const panel=created[0];
  assert.equal(panel.dataset.motionSystem,'freestyle');
  assert.equal(panel.dataset.workspacePanel,undefined,'Workspace navigation belongs to the containing Poses panel');
  assert.equal(node('[data-workspace-panel="poses"]').children.includes(panel),true);
  node('robot-select').value='p4';
  node('[data-field="request"]').value='invent a greeting';
  await panel.listeners.click({target:{dataset:{action:'generate'}}});
  assert.deepEqual(calls.at(-1).payload,{robot_id:'p4',request:'invent a greeting',execute:false});
  node('robot-select').value='another-body';
  await panel.listeners.click({target:{dataset:{action:'execute'}}});
  assert.equal(calls.at(-1).payload.robot_id,'another-body');
  assert.equal(calls.at(-1).payload.execute,true);
  assert.equal(calls.at(-1).headers['X-Ainekio-CSRF'],'test-csrf');
  await panel.listeners.click({target:{dataset:{action:'save'}}});
  assert.deepEqual(calls.at(-1).payload,{operation:'trial',robot_id:'another-body',job_id:'test-job'});
  assert.equal(created.at(-1).download,'freestyle-test-job.json');
  assert.equal(created.at(-1).clicked,true);
  await panel.listeners.click({target:{dataset:{action:'corrections'}}});
  assert.deepEqual(calls.at(-1).payload,{operation:'corrections',robot_id:'another-body'});
  assert.equal(node('[data-field="correction"]').children[0].textContent,'Wave trial');
  const beforeOpen=calls.length;
  node('[data-field="trials"]').open=true;
  await node('[data-field="trials"]').listeners.toggle();
  assert.deepEqual(calls.slice(beforeOpen).filter(c=>c.payload).map(c=>c.payload.operation),['corrections'],
    'Expanding saved trials loads evidence without moving or publishing training data');
  assert.equal(panel.innerHTML.indexOf('Requested movement') < panel.innerHTML.indexOf('data-freestyle-training'),true);
  assert.equal(panel.innerHTML.indexOf('data-freestyle-training') < panel.innerHTML.indexOf('Saved motion trials'),true);
  assert.equal(panel.innerHTML.indexOf('Saved motion trials') < panel.innerHTML.indexOf('Freestyle settings'),true);
  node('[data-field="correction"]').value='review-1';
  await panel.listeners.click({target:{dataset:{action:'test-correction'}}});
  assert.deepEqual(calls.at(-1).payload,{operation:'test-correction',robot_id:'another-body',review_id:'review-1'});
  const count=calls.length;
  context.window.renderFreestyleStatus({settings:{p4:{endpoint:'http://localhost:8794',recover_events:true}},jobs:{one:{id:'one',robot_id:'p4',state:'generated',request:'Raise right hand',latest_generation:{program:[{name:'face',arguments:{expr:'wave'}}]}},
    two:{id:'two',robot_id:'another-body',state:'executing'}}},'p4');
  assert.equal(JSON.parse(node('[data-field="result"]').textContent).id,'one');
  assert.equal(node('[data-field="recovery"]').checked,true);
  node('[data-field="endpoint"]').value='http://localhost:9000';
  panel.listeners.input({target:{dataset:{field:'endpoint'}}});
  context.window.renderFreestyleStatus({settings:{p4:{endpoint:'http://localhost:8794',recover_events:true}},jobs:{}},'p4');
  assert.equal(node('[data-field="endpoint"]').value,'http://localhost:9000','Polling must preserve unsaved edits');
  assert.equal(calls.length,count,'Status rendering uses the existing dashboard update without extra requests');
  node('robot-select').value='p4';
  await panel.listeners.change({target:{dataset:{field:'endpoint'}}});
  assert.deepEqual(calls.at(-1).payload,{operation:'configure',robot_id:'p4',endpoint:'http://localhost:9000',recover_events:true});
  assert.equal(node('[data-field="settings-status"]').textContent,'Settings saved.');
  node('[data-field="recovery"]').checked=false;
  await panel.listeners.change({target:{dataset:{field:'recovery'}}});
  assert.deepEqual(calls.at(-1).payload,{operation:'configure',robot_id:'p4',endpoint:'http://localhost:9000',recover_events:false});
  assert.equal(calls.slice(count).filter(call=>call.payload).every(call=>call.payload.operation==='configure'),true,
    'Changing settings saves configuration without generating or executing motion');
  let openedDraft=null;
  context.window.openFreestyleDraftInLibrary=async draft=>{openedDraft=draft;};
  await panel.listeners.click({target:{dataset:{action:'edit-training'}}});
  assert.deepEqual(JSON.parse(JSON.stringify(openedDraft)),{title:'Raise right hand',query:JSON.stringify({request:'Raise right hand'}),program:[{name:'face',arguments:{expr:'wave'}}]});
  assert.doesNotMatch(panel.innerHTML,/data-action="configure"/,'Settings need no Apply button');
  context.window.renderFreestyleStatus({jobs:{}},'third-body');
  assert.equal(node('[data-field="result"]').textContent,'');
  assert.equal(node('[data-field="recovery"]').checked,false,'Settings follow the selected robot');
  console.log('Freestyle UI: inert startup, explicit execution and selected-robot routing passed');
})().catch(error=>{console.error(error);process.exitCode=1;});

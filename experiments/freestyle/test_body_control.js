const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = new Map(), created = [], calls = [];
function node(id) {
  if (!nodes.has(id)) nodes.set(id,{value:'',checked:false,dataset:{},listeners:{},children:[],
    append(child){this.children.push(child);}, addEventListener(type,handler){this.listeners[type]=handler;},
    after(child){this.nextSibling=child;},click(){this.clicked=true;},
    querySelector(selector){return node(selector);}});
  return nodes.get(id);
}
const context = {window:{},Blob,URL:{createObjectURL(){return 'blob:test';},revokeObjectURL(){}},document:{getElementById:node,querySelector:node,
  createElement(tag){const item=node(tag+created.length);created.push(item);return item;}},
  async fetch(url, options={}) {
    const payload=options.body ? JSON.parse(options.body) : null;
    calls.push({url,payload,headers:options.headers});
    return {ok:true,json:async()=>url==='/api/session' ? {csrf:'test-csrf'} :
      payload?.operation==='trial' ? {job:{id:'test-job',execute:false}} : {job_id:'test-job'}};
  }};
vm.runInNewContext(fs.readFileSync('experiments/freestyle/body_control.js','utf8'),context);
(async()=>{
  assert.equal(calls.length,0,'Loading the optional workspace must not enable recovery or send commands');
  const panel=created[0];
  assert.equal(panel.dataset.workspacePanel,'poses');
  assert.equal(node('[data-workspace-panel="poses"]').nextSibling,panel);
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
  const count=calls.length;
  context.window.renderFreestyleStatus({settings:{p4:{endpoint:'http://localhost:8794',recover_events:true}},jobs:{one:{id:'one',robot_id:'p4',state:'generated'},
    two:{id:'two',robot_id:'another-body',state:'executing'}}},'p4');
  assert.equal(JSON.parse(node('[data-field="result"]').textContent).id,'one');
  assert.equal(node('[data-field="recovery"]').checked,true);
  node('[data-field="endpoint"]').value='http://localhost:9000';
  panel.listeners.input({target:{dataset:{field:'endpoint'}}});
  context.window.renderFreestyleStatus({settings:{p4:{endpoint:'http://localhost:8794',recover_events:true}},jobs:{}},'p4');
  assert.equal(node('[data-field="endpoint"]').value,'http://localhost:9000','Polling must preserve unsaved edits');
  assert.equal(calls.length,count,'Status rendering uses the existing dashboard update without extra requests');
  context.window.renderFreestyleStatus({jobs:{}},'third-body');
  assert.equal(node('[data-field="result"]').textContent,'');
  assert.equal(node('[data-field="recovery"]').checked,false,'Settings follow the selected robot');
  console.log('Freestyle UI: inert startup, explicit execution and selected-robot routing passed');
})().catch(error=>{console.error(error);process.exitCode=1;});

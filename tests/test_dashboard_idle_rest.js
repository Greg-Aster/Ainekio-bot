/* Exercise the production handlers, including reconnect and in-flight replies. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map(),requests=[];
function node(id){if(!nodes.has(id))nodes.set(id,{value:'3',hidden:false,disabled:false,listeners:{},
  reportValidity(){return true;},addEventListener(type,fn){this.listeners[type]=fn;}});return nodes.get(id);}
const context={console,URLSearchParams,window:{addEventListener(){}},document:{getElementById:node},
  fetch(url,options){return new Promise(resolve=>requests.push({url,options,
    resolve(data,ok=true){resolve({ok,status:ok?200:502,json:async()=>data});}}));}};
let source=fs.readFileSync('Master/gateway/dashboard/static/dashboard.js','utf8');
source=source.replace('  if (!setupLogin()) {',`globalThis.api={setupIdleRest,readIdleRest,
  select(id,epoch=1,features=['idle_rest_v1']){selectedRobotId=id;updateIdleRest({connected:true,epoch,features});}};if(false){`);
vm.createContext(context);vm.runInContext(source,context);
const api=context.api,tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  api.setupIdleRest();api.select('a');assert.match(requests.at(-1).url,/robot_id=a/);
  requests.at(-1).resolve({seconds:180,saved:false});await tick();
  assert.equal(node('idle-rest-minutes').value,'3');assert.match(node('idle-rest-status').textContent,/Robot default/);
  node('idle-rest-minutes').value='4.5';let p=api.readIdleRest(true);
  assert.deepEqual(JSON.parse(requests.at(-1).options.body),{op:'configure',seconds:270});
  requests.at(-1).resolve({seconds:270,saved:true});await p;
  assert.match(node('idle-rest-status').textContent,/Saved on robot/);
  node('idle-rest-minutes').value='0';p=api.readIdleRest(true);
  assert.equal(JSON.parse(requests.at(-1).options.body).seconds,0);
  requests.at(-1).resolve({seconds:0,saved:true});await p;assert.match(node('idle-rest-status').textContent,/rest off/);
  p=api.readIdleRest();const old=requests.at(-1);api.select('b');
  old.resolve({seconds:3600,saved:true});await p;assert.equal(node('idle-rest-minutes').value,'0');
  requests.at(-1).resolve({seconds:120,saved:true});await tick();assert.equal(node('idle-rest-minutes').value,'2');
  api.select('v1',1,[]);assert.equal(node('idle-rest-form').hidden,true);
  console.log('Idle rest UI: minutes, save, disable, selected robot and stale response handling passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});

const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const fields = new Map(), actions = new Map(), mirrors = new Map(), calls = [], created = [];
function element() {
  return {dataset:{}, attributes:{}, children:[], listeners:{}, value:'', hidden:false, disabled:false,
    scrollIntoView(){}, append(...nodes){this.children.push(...nodes);}, replaceChildren(){this.children=[];},
    setAttribute(k,v){this.attributes[k]=v;}, addEventListener(k,fn){this.listeners[k]=fn;},
    closest(){return this;}, querySelector(selector){
      const match=selector.match(/data-(field|action)="([^"]+)"/);
      const map=match[1]==='field' ? fields : actions;
      if(!map.has(match[2]))map.set(match[2],element());
      return map.get(match[2]);
    }, querySelectorAll(selector){
      if(selector==='[data-action="select"]')return created.filter(n=>n.dataset.action==='select');
      if(!mirrors.has(selector))mirrors.set(selector,element());
      return [this.querySelector(selector),mirrors.get(selector)];
    }};
}
const host=element(), robot=element(); robot.value='robot-a';
const example={id:'one',title:'Happy wiggle',request:'Wiggle',revision:1,physical_qualification:true,
  answers:[['face','happy'],['hold',.16]],query:JSON.stringify({request:'Wiggle',observation:{preserve:true}}),
  example:{query:JSON.stringify({request:'Wiggle',observation:{preserve:true}})}};
let nextSaveError=null, confirmResult=false;
const listeners={};
const context={window:{addEventListener(k,fn){listeners[k]=fn;},confirm(){return confirmResult;}},
 document:{querySelector(){return host;},getElementById(){return robot;},createElement(){const e=element();created.push(e);return e;}},
 async fetch(url, options={}){
   const payload=options.body ? JSON.parse(options.body) : null;
   calls.push({url,payload,headers:options.headers});
   let result;
   if(url==='/api/session')result={csrf:'test-csrf'};
   else if(payload?.operation==='save'){
     if(nextSaveError){const error=nextSaveError;nextSaveError=null;return {ok:false,json:async()=>({error})};}
     result={...example,...payload,revision:payload.revision+1};
   }else if(payload?.operation==='run')result={job_id:'job-'+payload.robot_id};
   else if(url.includes('?id='))result=example;
   else result={items:[{id:'one',title:'Happy wiggle',family:'rear_sway'}],total:51,pages:3,page:Number(new URL(url,'http://test').searchParams.get('page')),page_size:25};
   return {ok:true,json:async()=>result};
 }};
vm.runInNewContext(fs.readFileSync('experiments/freestyle/motion_library.js','utf8'),context);
const panel=host.children[0];
const field=name=>panel.querySelector(`[data-field="${name}"]`);
const click=(action, data={})=>panel.listeners.click({target:{dataset:{action,...data},closest(){return this;},setAttribute(){}}});
(async()=>{
 assert.equal(calls.length,0,'Page load must neither fetch all examples nor move a robot');
 field('browser').hidden=true;
 await click('open');
 assert.equal(field('browser').hidden,false);
 assert.equal(field('page').textContent,'Page 1 of 3');
 await click('next');assert.equal(field('page').textContent,'Page 2 of 3');
 await click('last');assert.equal(field('page').textContent,'Page 3 of 3');
 assert.equal(actions.get('last').disabled,true);
 assert.equal(mirrors.get('[data-action="last"]').disabled,true);
 await click('first');assert.equal(field('page').textContent,'Page 1 of 3');
 assert.equal(actions.get('first').disabled,true);
 assert.equal(mirrors.get('[data-field="page"]').textContent,'Page 1 of 3');
 for(const sort of ['name_desc','added_asc','added_desc','edited_asc','edited_desc']){
   field('sort').value=sort;await field('sort').listeners.change();
   assert.equal(new URL(calls.at(-1).url,'http://test').searchParams.get('sort'),sort);
   assert.equal(field('page').textContent,'Page 1 of 3');
 }
 await click('last');
 assert.equal(new URL(calls.at(-1).url,'http://test').searchParams.get('sort'),'edited_desc');
 await click('select',{id:'one'});
 assert.deepEqual(JSON.parse(field('answers').value),example.answers);
 field('answers').value=JSON.stringify([['face','surprised']]);
 panel.listeners.input({target:{dataset:{field:'answers'}}});
 context.window.renderMotionLibraryStatus({jobs:{}},robot.value);
 assert.equal(JSON.parse(field('answers').value)[0][1],'surprised','Polling preserves draft edits');
 await click('run');
 assert.equal(calls.at(-1).payload.operation,'run');
 assert.equal(calls.at(-1).payload.answers[0][1],'surprised');
 assert.equal(calls.at(-1).payload.robot_id,'robot-a');
 assert.equal(calls.at(-1).headers['X-Ainekio-CSRF'],'test-csrf');
 assert.equal(calls.filter(c=>c.payload?.operation==='save').length,0,'Draft playback must not save');
 robot.value='robot-b';context.window.renderMotionLibraryStatus({jobs:{}},robot.value);
 await click('run');assert.equal(calls.at(-1).payload.robot_id,'robot-b');
 context.window.renderMotionLibraryStatus({jobs:{'job-robot-b':{state:'completed',completed_commands:8}}},'robot-b');
 assert.match(field('play-status').textContent,/completed.*8 commands/);
 const count=calls.length;
 await click('select',{id:'one'});assert.equal(calls.length,count,'Unsaved edit is retained when navigation is declined');
 nextSaveError='Edited elsewhere';
 await click('save');assert.equal(field('edit-status').textContent,'Edited elsewhere');
 assert.equal(JSON.parse(field('answers').value)[0][1],'surprised');
 await click('save');assert.equal(field('edit-status').textContent,'Saved to training data.');
 const saved=calls.findLast(c=>c.payload?.operation==='save').payload;
 assert.equal(saved.revision,1);assert.equal(saved.answers[0][1],'surprised');
 field('answers').value='bad json';
 const before=calls.length;await click('run');assert.equal(calls.length,before,'Invalid JSON never reaches the robot API');
 console.log('Motion library UI: pagination, edits, save failures, draft playback and selected robot passed');
})().catch(error=>{console.error(error);process.exitCode=1;});

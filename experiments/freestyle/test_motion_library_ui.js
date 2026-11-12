const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const fields = new Map(), actions = new Map(), mirrors = new Map(), calls = [], created = [];
function element() {
  return {dataset:{}, attributes:{}, children:[], listeners:{}, value:'', hidden:false, disabled:false,
    scrollIntoView(){}, append(...nodes){for(const node of nodes){if(node.parentElement)node.parentElement.children=node.parentElement.children.filter(child=>child!==node);node.parentElement=this;this.children.push(node);}}, replaceChildren(){this.children=[];},
    setAttribute(k,v){this.attributes[k]=v;}, addEventListener(k,fn){this.listeners[k]=fn;},
    closest(){return this;}, querySelector(selector){
      const match=selector.match(/data-(field|action)="([^"]+)"/);
      const map=match[1]==='field' ? fields : actions;
      if(!map.has(match[2]))map.set(match[2],element());
      return map.get(match[2]);
    }, querySelectorAll(selector){
      if(selector==='details[data-example-id]')return created.filter(n=>n.dataset.exampleId);
      if(selector==='[data-action="play"]')return created.filter(n=>n.dataset.action==='play');
      if(!mirrors.has(selector))mirrors.set(selector,element());
      return [this.querySelector(selector),mirrors.get(selector)];
    }};
}
const host=element(), robot=element(); robot.value='robot-a'; robot.checked=true;
const jointNames=['rear_left_shoulder','rear_left_carrier','rear_left_crank','rear_right_shoulder','rear_right_carrier','rear_right_crank','front_left_shoulder','front_left_carrier','front_left_crank','front_right_shoulder','front_right_carrier','front_right_crank'];
const example={id:'one',title:'Happy wiggle',request:'Wiggle',revision:1,physical_qualification:true,
  answers:[['face','happy'],['hold',.16]],program:[{name:'face',arguments:{expr:'happy'}},{name:'hold',arguments:{seconds:.16}}],joint_names:jointNames,query:JSON.stringify({request:'Wiggle',observation:{preserve:true}}),
  example:{query:JSON.stringify({request:'Wiggle',observation:{preserve:true}})}};
let nextSaveError=null, nextRunError=null, confirmResult=false;
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
   }else if(payload?.operation==='create'){
     result={id:'created-one',title:payload.title,request:payload.query,query:JSON.stringify({request:payload.query}),
       revision:1,program:payload.program,answers:[['face','happy']],joint_names:jointNames};
   }else if(payload?.operation==='run'){
     if(nextRunError){const error=nextRunError;nextRunError=null;return {ok:false,json:async()=>({error})};}
     result={job_id:'job-'+payload.robot_id};
   }
   else if(payload?.operation==='preview'){
     const rows=payload.program ? payload.program.map(operation=>{
       const a=operation.arguments;
       if(operation.name==='face')return ['face',a.expr];
       if(operation.name==='hold')return ['hold',a.seconds];
       if(operation.name==='pose')return ['pose',a.joints.map(name=>jointNames.indexOf(name)),a.angles_deg,a.reference,a.speed_pct];
       throw new Error('Unexpected preview fixture');
     }) : example.answers;
     result={target:JSON.stringify(rows),operations:rows.map(row=>JSON.stringify(row))};
   }
   else if(['pause','release'].includes(payload?.operation))result={pause_state:payload.operation==='release'?'released':'paused',operation_index:1,pause_cursor:{source_us:1000000}};
   else if(url.includes('?meta=1'))result={joint_names:jointNames};
   else if(url.includes('?id='))result=url.includes('created-one') ? {id:'created-one',title:'Created wave',request:'Wave right hand',query:JSON.stringify({request:'Wave right hand'}),revision:1,program:[{name:'face',arguments:{expr:'wave'}}],answers:[['face','wave']],joint_names:jointNames} : example;
   else result={items:[{id:'one',title:'Happy wiggle',family:'rear_sway'},{id:'two',title:'Other wiggle',family:'rear_sway'},{id:'created-one',title:'Created wave',family:'custom_motion'}],total:51,pages:3,page:Number(new URL(url,'http://test').searchParams.get('page')),page_size:25};
   return {ok:true,json:async()=>result};
 }};
vm.runInNewContext(fs.readFileSync('experiments/freestyle/motion_library.js','utf8'),context);
const panel=host.children[0];
assert.equal(panel.dataset.motionSystem,"freestyle");
const field=name=>panel.querySelector(`[data-field="${name}"]`);
const click=(action, data={})=>panel.listeners.click({target:{dataset:{action,...data},closest(){return this;},setAttribute(){}}});
const openExample=async id=>{const branch=created.findLast(n=>n.dataset.exampleId===id);branch.open=true;await branch.listeners.toggle();return branch;};
(async()=>{
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(calls.length,1,'Training data loads one bounded page without an expand button');
 context.window.renderMotionLibraryStatus({jobs:{}},robot.value,{});
 assert.equal(calls[0].payload,null,'Opening the library does not submit commands');
 assert.doesNotMatch(panel.innerHTML,/data-action="(?:open|trials|select)"/,'Buttons perform actions; disclosure arrows expand data');
 assert.equal(field('page').textContent,'Page 1 of 3');
 const rowPlay=id=>field('list').children.flatMap(row=>row.children).find(node=>node.dataset.action==='play' && node.dataset.id===id);
 assert.ok(rowPlay('one'),'Every collapsed list entry has a Play button');
 assert.equal(rowPlay('one').attributes['aria-label'],'Play Happy wiggle');
 assert.equal(field('list').children[0].children[0],rowPlay('one'),'Play precedes the title disclosure in every row');
 assert.equal(field('list').children[0].children[1].dataset.exampleId,'one','The title and editor remain in their disclosure column');
 const collapsed=created.findLast(node=>node.dataset.exampleId==='one');
 const listPlayBefore=calls.length;
 await panel.listeners.click({target:rowPlay('one')});
 assert.equal(calls.at(-1).payload.operation,'run');
 assert.equal(calls.at(-1).payload.id,'one');
 assert.equal(calls.at(-1).payload.robot_id,'robot-a');
 assert.equal(calls.at(-1).headers['X-Ainekio-CSRF'],'test-csrf');
 assert.equal('program' in calls.at(-1).payload,false,'Row Play executes the saved training example');
 assert.equal('query' in calls.at(-1).payload,false,'The server supplies the saved example request');
 assert.ok(!collapsed.open,'Row Play leaves the entry collapsed');
 assert.equal(calls.slice(listPlayBefore).some(call=>call.url.includes('?id=')),false,'Row Play needs no editor fetch');
 assert.match(field('list-status').textContent,/Happy wiggle submitted to robot-a/);
 robot.value='';context.window.renderMotionLibraryStatus({jobs:{}},'',{});
 assert.equal(rowPlay('one').disabled,true);
 robot.value='robot-a';context.window.renderMotionLibraryStatus({jobs:{}},robot.value,{});
 assert.equal(rowPlay('one').disabled,false);

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
 await openExample('one');
 assert.equal(field('editor').parentElement.dataset.exampleId,'one','The editor opens inline inside its file row');
 assert.deepEqual(JSON.parse(field('answers').value),example.program);
 const beforeView=calls.length, draftBeforeView=field('answers').value;
 field('raw-training').checked=true;await field('raw-training').listeners.change();
 assert.equal(field('operations').hidden,true);
 assert.equal(field('raw-code').hidden,false);
 const rawView=field('raw-code').children.map(child=>child.textContent).join('');
 assert.deepEqual(JSON.parse(rawView),example.answers,'Display formatting preserves the actual training arrays');
 assert.match(rawView,/,\n\s+/,'Operations and argument groups are separated onto lines');
 assert.ok(rawView.split('\n').length<25,'Numeric pose arrays do not become vertical columns');

 assert.equal(calls.at(-1).payload.operation,'preview');
 assert.equal('program' in calls.at(-1).payload,false,'Saved target preview reads stored arrays without a numeric reserialization round trip');
 assert.equal(field('answers').value,draftBeforeView,'Changing representation preserves the editable program');
 field('raw-training').checked=false;await field('raw-training').listeners.change();
 const cachedView=calls.length;
 field('raw-training').checked=true;await field('raw-training').listeners.change();
 assert.equal(calls.length,cachedView,'Repeated view changes reuse the same encoded snapshot');
 field('raw-training').checked=false;await field('raw-training').listeners.change();
 assert.equal(calls.slice(beforeView).filter(call=>call.payload).every(call=>call.payload.operation==='preview'),true,
   'The view switch does not save, generate or execute motion');

 field('answers').value=JSON.stringify([{name:'face',arguments:{expr:'surprised'}}]);
 panel.listeners.input({target:{dataset:{field:'answers'}}});
 context.window.renderMotionLibraryStatus({jobs:{}},robot.value);
 assert.equal(JSON.parse(field('answers').value)[0].arguments.expr,'surprised','Polling preserves draft edits');
 const draftBeforeRowPlay=field('answers').value, selectedParent=field('editor').parentElement;
 robot.value='robot-b';context.window.renderMotionLibraryStatus({jobs:{}},robot.value,{});
 const rowPlayBefore=calls.length;
 await panel.listeners.click({target:rowPlay('two')});
 assert.equal(calls.at(-1).payload.id,'two');
 assert.equal(calls.at(-1).payload.robot_id,'robot-b','Row Play uses the currently selected robot');
 assert.equal(field('answers').value,draftBeforeRowPlay,'Playing another row preserves unsaved edits');
 assert.equal(field('editor').parentElement,selectedParent,'Playing another row keeps the editor selection');
 assert.equal(calls.slice(rowPlayBefore).some(call=>call.payload?.operation==='save'),false);
 nextRunError='Robot disconnected';await panel.listeners.click({target:rowPlay('two')});
 assert.equal(field('list-status').textContent,'Robot disconnected','List playback errors stay visible outside the editor');
 assert.equal(rowPlay('two').disabled,false,'A failed playback request restores the row button');
 robot.value='robot-a';context.window.renderMotionLibraryStatus({jobs:{}},robot.value,{});

 await click('run');
 assert.equal(calls.at(-1).payload.operation,'run');
 assert.equal(calls.at(-1).payload.program[0].arguments.expr,'surprised');
 assert.equal(calls.at(-1).payload.robot_id,'robot-a');
 assert.equal(calls.at(-1).headers['X-Ainekio-CSRF'],'test-csrf');
 assert.equal(calls.filter(c=>c.payload?.operation==='save').length,0,'Draft playback must not save');
 robot.value='robot-b';context.window.renderMotionLibraryStatus({jobs:{}},robot.value);
 await click('run');assert.equal(calls.at(-1).payload.robot_id,'robot-b');
 context.window.renderMotionLibraryStatus({jobs:{'job-robot-b':{state:'completed',completed_commands:8}}},'robot-b');
 assert.match(field('play-status').textContent,/completed.*8 receipts/);
 const count=calls.length;
 await openExample('two');assert.equal(calls.length,count,'Unsaved edit is retained when navigation is declined');
 nextSaveError='Edited elsewhere';
 await click('save');assert.equal(field('edit-status').textContent,'Edited elsewhere');
 assert.equal(JSON.parse(field('answers').value)[0].arguments.expr,'surprised');
 await click('save');assert.equal(field('edit-status').textContent,'Saved to training data.');
 assert.equal(field('editor').parentElement.dataset.exampleId,'one','Saving and refreshing the list retains the open editor');
 const saved=calls.findLast(c=>c.payload?.operation==='save').payload;
 assert.equal(saved.revision,1);assert.equal(saved.program[0].arguments.expr,'surprised');
 field('answers').value='bad json';
 const before=calls.length;await click('run');assert.equal(calls.length,before,'Invalid JSON never reaches the robot API');
 const pose={name:'pose',arguments:{joints:jointNames,angles_deg:Array(12).fill(0),reference:'absolute',speed_pct:50}};
 field('answers').value=JSON.stringify([example.program[0],pose]);
 panel.listeners.input({target:{dataset:{field:'answers'}}});
 field('step').value='1';field('step').listeners.change();
 const feedback={raw_adc:Array(12).fill(400),signal_millivolts:Array(12).fill(286),filtered_model_deg:Array.from({length:12},(_,i)=>i+20),commanded_model_deg:Array(12).fill(0),
   usable_mask:4079,below_calibration_mask:16,commanded_mask:0,device_us:100000,sampled_us:Array(12).fill(99000)};
 const entry={connected:true,connection_state:'online',status:{imu:{fresh:true,joint_feedback:feedback,received_at:'test-time'}}};
 await click('run');
 context.window.renderMotionLibraryStatus({jobs:{'job-robot-b':{id:'job-robot-b',state:'executing',operation_index:1}}},'robot-b',entry);
 assert.equal(field('operations').children[1].attributes['aria-current'],'step');
 field('raw-training').checked=true;await field('raw-training').listeners.change();
 assert.equal(field('raw-code').children.find(child=>child.dataset.index==='1').attributes['aria-current'],'step');
 const poseText=field('raw-code').children.find(child=>child.dataset.index==='1').textContent;
 assert.match(poseText,/\[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11\]/,'Joint indices stay together in one readable row');
 assert.match(poseText,/\[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0\]/,'Angle values stay together in one readable row');
 assert.match(field('step-code').value,/"angles_deg": \[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0\]/,'The operation editor also keeps angles on a row');
 assert.equal(JSON.parse(field('raw-code').children.find(child=>child.dataset.index==='1').textContent)[1][7],7,
   'The raw target uses actual numeric joint IDs');
 field('raw-training').checked=false;await field('raw-training').listeners.change();

 assert.equal(field('feedback').children.length,12,'The editor shows all measured joints');
 assert.equal(field('feedback').children[4].children[1].textContent,'400');
 assert.equal(field('feedback').children[4].children[2].textContent,'286');
 assert.equal(field('feedback').children[4].children[3].textContent,'24.00','The measured angle stays visible outside the usable mask');
 assert.equal(field('feedback').children[0].children[4].textContent,'released','Commanded targets are distinct from released outputs');
 await click('pause');assert.equal(calls.at(-1).payload.operation,'pause');assert.match(field('play-status').textContent,/Paused/);
 await click('release');assert.equal(calls.at(-1).payload.operation,'release');assert.match(field('play-status').textContent,/Hand-pose/);
 const capturesBefore=calls.length;
 await click('capture');assert.equal(calls.length,capturesBefore,'Pose capture edits data without sending motion or saving');
 let captured=JSON.parse(field('answers').value);
 assert.equal(captured[1].arguments.angles_deg[4],24,'Pose capture preserves a reading outside the usable mask');
 assert.equal(captured[1].arguments.angles_deg[11],31);assert.equal(captured[1].arguments.speed_pct,50);
 assert.equal(JSON.parse(field('operations').children[1].children[0].textContent).arguments.angles_deg[11],0,'Playback code stays the executed snapshot while the draft is corrected');
 assert.equal(captured[0].arguments.expr,'happy','Capture preserves other operations');
 await click('save');assert.equal(calls.at(-2).payload.operation,'save');
 assert.equal(calls.at(-2).payload.program[1].arguments.angles_deg[11],31);
 await click('run-step');assert.equal(calls.at(-1).payload.start_index,1);
 assert.equal(captured[1].arguments.taper_deg,0);
 robot.value='robot-c';
 context.window.renderMotionLibraryStatus({jobs:{restored:{id:'restored',robot_id:'robot-c',source:{example_id:'one'},owns_motion:true,
   pause_state:'released',operation_index:1,latest_generation:{program:[example.program[0],pose]}}}},'robot-c',entry);
 assert.equal(actions.get('pause').disabled,false,'Reopening the UI can recover the existing example playback identity');
 await click('pause');assert.equal(calls.at(-1).payload.job_id,'restored');
 field('category').value='ordinary';await field('category').listeners.change();
 assert.equal(new URL(calls.at(-1).url,'http://test').searchParams.get('category'),'ordinary');
 confirmResult=true;
 await context.window.openFreestyleDraftInLibrary({title:'Created wave',query:'Wave right hand',program:[{name:'face',arguments:{expr:'wave'}}]});
 assert.equal(actions.get('save').textContent,'Add to training data');
 await click('add-step');
 assert.equal(JSON.parse(field('answers').value).length,2);
 await click('remove-step');
 assert.equal(JSON.parse(field('answers').value).length,1);
 await click('save');
 assert.equal(calls.findLast(c=>c.payload?.operation==='create').payload.title,'Created wave');
 console.log('Motion library UI: pagination, category filter, edits, draft creation, draft playback and selected robot passed');
})().catch(error=>{console.error(error);process.exitCode=1;});

/* Exercise the production navigation owner without any robot transport. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const base = path.join(__dirname, '../../Master/gateway/dashboard/static');
const html = fs.readFileSync(path.join(base, 'dashboard.html'), 'utf8');

function fixture(saved = new Map(), compact = false) {
  const nodes = new Map();
  let activeElement = null;
  function node(id) {
    if (!nodes.has(id)) nodes.set(id, {hidden:false, value:'', scrollTop:0, dataset:{}, attributes:{}, listeners:{},
      classList:{toggle(){}},
      addEventListener(type, fn){(this.listeners[type] ||= []).push(fn);},
      fire(type, event={}){for(const fn of this.listeners[type] || [])fn(event);},
      setAttribute(key,value){this.attributes[key]=value;},
      removeAttribute(key){delete this.attributes[key];},
      focus(){activeElement=this;},reset(){this.value='';},
      querySelector(){return node(id+'-heading');},
    });
    return nodes.get(id);
  }
  const groups = ['operate','perception','storage','maintenance','settings'].map(key => {
    const item=node(key);item.dataset.navigationGroup=key;item.open=key==='operate';return item;
  });
  const buttons = [...html.matchAll(/data-workspace="([^"]+)"/g)].map(([_,key])=>{
    const item=node('nav-'+key);item.dataset.workspace=key;
    item.closest=()=>groups[0];return item;
  });
  const panels = [...html.matchAll(/<[^>]+data-workspace-panel="([^"]+)"[^>]*>/g)].map(([tag,key],i)=>{
    const id=tag.match(/\bid="([^"]+)"/);
    const item=node(id ? id[1] : 'panel-'+i);item.dataset.workspacePanel=key;return item;
  });
  node('tool-sidebar').querySelectorAll=selector=>selector==='[data-workspace]'?buttons:groups;
  node('tool-workspace').querySelectorAll=()=>panels;
  const media={matches:compact, addEventListener(type,fn){this.change=fn;}};
  const context={console,navigator:{},document:{getElementById:node,body:node('body'),querySelectorAll(){return [];}},
    window:{matchMedia(){return media;},addEventListener(){}},
    localStorage:{getItem(key){return saved.get(key)??null;},setItem(key,value){saved.set(key,value);}},
    fetch(){throw new Error('Navigation must not send robot commands');}};
  let source=fs.readFileSync(path.join(base,'dashboard.js'),'utf8');
  source=source.replace('  if (!setupLogin()) {','  globalThis.navigationTest = setupNavigation; globalThis.faceAvailabilityTest = renderFaceAvailability;\n  if (false) {');
  vm.createContext(context);vm.runInContext(source,context);context.navigationTest();
  const select=key=>node('nav-'+key).fire('click');
  return {node,buttons,panels,groups,saved,select,media,renderFaces:context.faceAvailabilityTest,active:()=>activeElement};
}

test('robot status refreshes cannot reveal the expression library in another tool',()=>{
  const f=fixture();
  const faces=f.panels.find(panel=>panel.dataset.workspacePanel==='faces');
  for(const button of f.buttons){
    const key=button.dataset.workspace;f.select(key);
    for(const entry of [{model:'v2-12servo',epoch:1},null,{model:'v1-8servo',epoch:2}]){
      f.renderFaces(entry,entry?.model==='v2-12servo');
      assert.equal(faces.hidden,key!=='faces',`Status refresh must preserve the ${key} tool selection`);
      assert.equal(f.node('faces-section').hidden,Boolean(entry&&entry.model!=='v2-12servo'));
    }
  }
});

test('all tools retain their controls and drafts while navigation only selects visible panels',()=>{
  const f=fixture();
  f.node('camera-form').value='unsaved camera draft';
  f.node('firmware-file').value='selected firmware';
  for(const button of f.buttons){
    const key=button.dataset.workspace;f.select(key);
    assert.equal(f.buttons.filter(b=>b.attributes['aria-current']==='page').length,1);
    for(const panel of f.panels)assert.equal(panel.hidden,!panel.dataset.workspacePanel.split(' ').includes(key));
    assert.equal(f.node('camera-form').value,'unsaved camera draft');
    assert.equal(f.node('firmware-file').value,'selected firmware');
    assert.equal(f.node('camera-view').hidden,false);
    assert.equal(f.node('stop-button').hidden,false);
  }
  f.node('settings-button').fire('click');
  assert.equal(f.node('nav-connections').attributes['aria-current'],'page');
  f.node('settings-close-button').fire('click');
  assert.equal(f.node('nav-overview').attributes['aria-current'],'page');
});

test('selected tool, desktop sidebar and group choices persist; compact navigation closes after selection',()=>{
  const saved=new Map();let f=fixture(saved);f.select('firmware');
  f.node('tool-workspace').scrollTop=150;f.select('camera');f.select('firmware');
  assert.equal(f.node('tool-workspace').scrollTop,150);
  f.node('tools-toggle').fire('click');
  f.groups[1].open=true;f.groups[1].fire('toggle');
  f=fixture(saved);
  assert.equal(f.node('nav-firmware').attributes['aria-current'],'page');
  assert.equal(f.node('tool-sidebar').hidden,true);
  assert.equal(f.groups[1].open,true);
  f=fixture(saved,true);f.node('tools-toggle').fire('click');
  assert.equal(f.node('tool-sidebar').hidden,false);f.select('recordings');
  assert.equal(f.node('tool-sidebar').hidden,true);
});

test('navigation owns Space and arrow presses but preserves release of an already-held drive key',()=>{
  const f=fixture();const sidebar=f.node('tool-sidebar');
  for(const code of ['Space','ArrowUp','ArrowDown','ArrowLeft','ArrowRight']){
    let stopped=false;sidebar.fire('keydown',{code,stopPropagation(){stopped=true;}});assert.equal(stopped,true);
  }
  let stopped=false;sidebar.fire('keyup',{code:'ArrowUp',stopPropagation(){stopped=true;}});
  assert.equal(stopped,false,'Held movement release must still reach its existing owner');
  sidebar.fire('keyup',{code:'Space',stopPropagation(){stopped=true;}});assert.equal(stopped,true);
  sidebar.fire('keydown',{code:'Escape',stopPropagation(){}});
  assert.equal(f.node('tool-sidebar').hidden,true);assert.equal(f.active(),f.node('tools-toggle'));
});

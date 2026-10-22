const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const nodes = new Map(), calls = [];
function node(id) {
  if (!nodes.has(id)) nodes.set(id, { listeners: {}, width: 640, height: 480,
    addEventListener(type, fn) { this.listeners[type] = fn; },
    getBoundingClientRect() { return { left: 0, top: 0, width: 320, height: 240 }; },
    getContext() { return { drawImage() {}, beginPath() {}, arc() {}, fill() {}, fillText() {} }; } });
  return nodes.get(id);
}
let liveFrame = 'frozen';
const values = { pattern: 'rectangle', widthMetres: '.24', heightMetres: '.18', geometryId: 'fixed' };
const context = { byId: node, selectedRobotId: 'robot', JSON, Math,
  text(id, value) { node(id).textContent = value; },
  FormData: class { get(name) { return values[name] ?? ''; } },
  Image: class { naturalWidth = 640; naturalHeight = 480; async decode() {} },
  async request(url, options) {
    const payload = JSON.parse(options.body); calls.push(payload);
    return payload.operation === 'status' ? { frame: { frameId: liveFrame }, image: 'data:image/jpeg;base64,test' } : { samples: 1 };
  }
};
const source = fs.readFileSync('Master/gateway/dashboard/static/dashboard.js', 'utf8');
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('    let groundSelection'), source.indexOf('    byId("camera-form").addEventListener')), context);
const submit = operation => node('ground-calibration-form').listeners.submit({ preventDefault() {}, currentTarget: {}, submitter: { value: operation } });
(async () => {
  await submit('freeze'); liveFrame = 'newer';
  const canvas = node('ground-calibration-image');
  for (const [x, y] of [[10, 10], [100, 10], [100, 100], [10, 100]]) canvas.listeners.click({ currentTarget: canvas, clientX: x, clientY: y });
  await submit('capture');
  assert.equal(calls.length, 2);
  assert.equal(calls[1].frameId, 'frozen');
  assert.deepEqual(calls[1].pixels, [[20, 20], [200, 20], [200, 200], [20, 200]]);
  assert.equal(calls[1].widthMetres, .24);
  context.selectedRobotId = 'other'; await submit('capture');
  assert.equal(calls.at(-1).frameId, null); // backend rejects a missing exact-frame identity
  console.log('Measured rectangle UI: frozen image ownership, pixel scaling and selected robot passed');
})().catch(error => { console.error(error); process.exitCode = 1; });

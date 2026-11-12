const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const flush = () => new Promise(resolve => setImmediate(resolve));

function fixture(t, stream = true) {
  const nodes = new Map(), requests = [], decodes = [], timers = [], revoked = [];
  let urls = 0;
  function element(id) {
    return { id, hidden: true, src: '', textContent: '', children: [], style: {}, elements: {}, listeners: {},
      classList: { toggle() {} },
      addEventListener(type, callback) { this.listeners[type] = callback; },
      fire(type) { return this.listeners[type]?.({currentTarget: this, target: this, preventDefault() {}}); },
      querySelector(selector) { return node(selector); },
      append(child) { this.children.push(child); },
      replaceChildren() { this.children = []; },
      cloneNode() { return Object.assign(element(this.id), { hidden: this.hidden, src: this.src }); },
      replaceWith(next) { nodes.set(this.id, next); },
      decode() { return new Promise((resolve, reject) => decodes.push({ resolve, reject })); },
    };
  }
  function node(id) {
    if (!nodes.has(id)) nodes.set(id, element(id));
    return nodes.get(id);
  }
  node('camera-show-detections').checked = true;
  const context = { console, URLSearchParams, AbortController, Blob, atob,
    FormData: class { constructor(form) { this.form = form; } get(name) { return this.form.elements[name]?.value; } },
    URL: { createObjectURL() { return `blob:${++urls}`; }, revokeObjectURL(url) { revoked.push(url); } },
    document: { body: { dataset: { dashboardPrimary: 'camera' } }, getElementById: node,
      createElement: tag => element(tag) },
    window: { addEventListener() {}, clearTimeout() {}, setTimeout(resolve) { timers.push(resolve); } },
    localStorage: { getItem() { return null; } },
    fetch: (url, options) => new Promise(resolve => requests.push({ url, options, resolve })),
  };
  const source = fs.readFileSync(path.join(__dirname, '../Master/gateway/dashboard/static/dashboard.js'), 'utf8')
    .replace('  if (!setupLogin()) {', `  globalThis.cameraTest = { run: runCameraView, reset: resetCameraView,
      setupCameraSettings, renderCameraMotionExposure, restoreCameraSettings, renderCameraCapture,
      select(id) { selectedRobotId = id; }, stop() { cameraViewActive = false; } };
      if (false) {`);
  vm.createContext(context); vm.runInContext(source, context);
  const api = context.cameraTest;
  api.select('p4');
  const loop = stream ? api.run() : Promise.resolve();
  t.after(async () => {
    api.stop();
    do {
      for (const request of requests.splice(0)) request.resolve({ status: 204 });
      for (const decode of decodes.splice(0)) decode.resolve();
      for (const resolve of timers.splice(0)) resolve();
      await flush();
    } while (requests.length || decodes.length || timers.length);
    await loop;
  });
  return { node, api, requests, decodes, revoked,
    async respond(value) {
      requests.shift().resolve({ status: 200, ok: true, json: async () => value,
        blob: async () => new Blob(['jpeg']), headers: { get: () => '1' } });
      await flush();
    },
    async next() { timers.shift()(); await flush(); },
    async decoded() { decodes.shift().resolve(); await flush(); },
  };
}

function frame(counter) {
  return { id: `p4:${counter}`, jpeg: btoa(`jpeg${counter}`), observation: {
    frameCounter: counter, ageMs: 20, model: 'test', objects: [
      { label: `object${counter}`, box: { x: .1, y: .2, width: .3, height: .4 } },
    ],
  } };
}

test('motion exposure uses its own capability, saves microseconds and displays actual readback', async t => {
  const f = fixture(t, false), form = f.node('camera-form');
  for (const [name, value] of Object.entries({fps: '5', res: 'VGA', snapshot_res: 'VGA', motion_exposure: 'auto',
    max_exposure_ms: '10', exposure_ms: '0', sensor_gain: '0', jpeg_quality: '75'})) {
    form.elements[name] = f.node(name); form.elements[name].value = value;
  }
  form.elements.on = f.node('on'); form.elements.on.checked = true;
  form.elements.snapshot_res.disabled = true;
  const manual = form.querySelector('fieldset[data-camera-controls]'); manual.disabled = true;
  const group = form.querySelector('fieldset[data-camera-motion-exposure]');
  f.api.setupCameraSettings();
  f.api.renderCameraMotionExposure({features: ['camera_controls_v1']}, true);
  assert.equal(group.hidden, true); assert.equal(group.disabled, true);
  form.fire('submit');
  assert.equal(JSON.parse(f.requests[0].options.body).max_exposure_us, undefined);
  await f.respond({seq: 1});
  f.api.renderCameraMotionExposure({features: ['camera_motion_exposure_v1']}, true);
  assert.equal(group.hidden, false); assert.equal(group.disabled, false);
  assert.equal(form.elements.max_exposure_ms.disabled, true);
  form.elements.motion_exposure.value = 'motion'; form.elements.motion_exposure.fire('change');
  assert.equal(form.elements.max_exposure_ms.disabled, false);
  assert.equal(form.elements.max_exposure_ms.value, '10');
  assert.equal(f.requests.length, 0, 'Selecting an exposure mode must not send a command');
  form.elements.max_exposure_ms.value = '7.125'; form.fire('submit');
  assert.equal(f.requests[0].url, '/api/camera');
  assert.deepEqual(JSON.parse(f.requests[0].options.body), {on: true, fps: 5, res: 'VGA', max_exposure_us: 7125, robot_id: 'p4'});
  await f.respond({seq: 2});
  f.api.restoreCameraSettings({on: true, fps: 5, resolution: 'VGA', max_exposure_us: 10000});
  assert.equal(form.elements.motion_exposure.value, 'motion');
  assert.equal(form.elements.max_exposure_ms.value, 10);
  f.api.renderCameraCapture({width: 640, height: 480, exposure_us: 7891, gain_x16: 64,
    max_exposure_us: 9983, settle_ms: 0}, true, false);
  assert.match(f.node('camera-capture-status').textContent, /7.9 ms exposure/);
  assert.match(f.node('camera-capture-status').textContent, /ceiling applied: 9.983 ms; gain automatic/);
  assert.equal(form.elements.max_exposure_ms.value, 10, 'Measured readback must not replace the saved request');
  form.elements.motion_exposure.value = 'auto'; form.elements.motion_exposure.fire('change');
  form.fire('submit'); assert.equal(JSON.parse(f.requests[0].options.body).max_exposure_us, 0);
  await f.respond({seq: 3});
  f.api.restoreCameraSettings({on: true, fps: 5, resolution: 'VGA', max_exposure_us: 0});
  assert.equal(form.elements.motion_exposure.value, 'auto');
  assert.equal(form.elements.max_exposure_ms.disabled, true);
  f.api.renderCameraMotionExposure({features: ['camera_motion_exposure_v1']}, false);
  assert.equal(group.disabled, true);
});

test('recognition gaps retain the source image and boxes, then swap only after decoding', async t => {
  const f = fixture(t);
  await f.respond(null);
  assert.equal(f.node('camera-image-plane').hidden, true);
  assert.match(f.node('camera-view-message').textContent, /Waiting for a recognition result/);
  await f.next();
  await f.respond(frame(1)); await f.decoded();
  const original = f.node('camera-view');
  const boxes = f.node('camera-detections').children;
  await f.next(); await f.respond(null);
  assert.equal(f.node('camera-image-plane').hidden, false);
  assert.equal(f.node('camera-view'), original);
  assert.equal(f.node('camera-detections').children, boxes);
  assert.match(f.node('camera-detection-status').textContent, /previous source image/);
  assert.deepEqual(f.revoked, []);
  await f.next();
  assert.match(f.requests[0].url, /after_id=p4%3A1/);
  await f.respond(frame(2));
  assert.equal(f.node('camera-image-plane').hidden, false);
  assert.equal(f.node('camera-view').src, 'blob:1');
  assert.equal(f.node('camera-detections').children, boxes);
  await f.decoded();
  assert.equal(f.node('camera-view').src, 'blob:2');
  assert.equal(f.node('camera-detections').children[0].children[0].textContent, 'object2');
  assert.match(f.node('camera-detection-status').textContent, /frame 2/);
  assert.deepEqual(f.revoked, ['blob:1']);
  await f.next();
  const sameFrame = frame(2); delete sameFrame.jpeg;
  await f.respond(sameFrame);
  assert.equal(f.node('camera-view').src, 'blob:2');
  assert.equal(f.decodes.length, 0);
});

test('a failed decode retains the displayed image and its detections', async t => {
  const f = fixture(t);
  await f.respond(frame(1)); await f.decoded(); await f.next();
  await f.respond(frame(2));
  f.decodes.shift().reject(new Error('invalid jpeg')); await flush();
  assert.equal(f.node('camera-view').src, 'blob:1');
  assert.equal(f.node('camera-image-plane').hidden, false);
  assert.match(f.node('camera-detection-status').textContent, /frame 1/);
  assert.equal(f.node('camera-detections').children[0].children[0].textContent, 'object1');
  assert.deepEqual(f.revoked, ['blob:2']);
  await f.next(); // Finish the existing error delay before teardown.
});

test('switching view during decode discards the old result; live preview also stays visible while decoding', async t => {
  const f = fixture(t);
  await f.respond(frame(1)); await f.decoded(); await f.next();
  await f.respond(frame(2));
  f.node('camera-show-detections').checked = false;
  f.api.reset();
  await f.decoded();
  assert.equal(f.node('camera-image-plane').hidden, true);
  assert.deepEqual(f.revoked, ['blob:1', 'blob:2']);
  await f.next(); await f.respond(null); await f.decoded();
  assert.equal(f.node('camera-view').src, 'blob:3');
  await f.respond(null);
  assert.equal(f.node('camera-image-plane').hidden, false);
  assert.equal(f.node('camera-view').src, 'blob:3');
  await f.decoded();
  assert.equal(f.node('camera-view').src, 'blob:4');
  assert.equal(f.node('camera-detections').children.length, 0);
});

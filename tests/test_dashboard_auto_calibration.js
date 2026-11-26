/* Exercise production Calibrate servos UI flow without sending real robot commands. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const nodes = new Map();
const calls = [];
let autoStatus = {
  robot_id: 'p4',
  mode: 'floor',
  state: 'idle',
  phase: 'idle',
  progress: 0,
  message: 'Ready to calibrate.',
  before: null,
  after: null,
  joints: [],
  can_apply: false,
  can_restore: false,
};

function makeNode(id) {
  if (!nodes.has(id)) {
    const el = {
      id,
      value: id === 'auto-calibration-mode' ? 'floor' : '',
      hidden: false,
      disabled: false,
      textContent: '',
      classList: { toggle() {}, add() {}, remove() {} },
      children: [],
      listeners: {},
      addEventListener(t, f) { this.listeners[t] = f; },
      replaceChildren(...items) { this.children = items; },
      appendChild(item) { this.children.push(item); return item; },
    };
    nodes.set(id, el);
  }
  return nodes.get(id);
}
makeNode('servo-form').elements = { id: { value: '0' }, deg: { value: '1500', min: '', max: '' }, ms: { value: '300' } };
makeNode('body-calibration-form').elements = {
  id: { value: '0' },
  channel: { value: '0', disabled: false },
  center: { value: '1650', min: '', max: '', disabled: false },
  home_deg: { value: '0', disabled: false },
  us_per_degree: { value: '11.111111', disabled: false },
  invert: { checked: false, disabled: false },
};

const context = {
  console,
  URLSearchParams,
  AbortController,
  document: {
    getElementById: makeNode,
    querySelectorAll: () => [],
    createElement(tag) {
      return { tag, textContent: '', children: [], appendChild(c) { this.children.push(c); return c; } };
    },
  },
  window: {
    addEventListener() {},
    setTimeout(fn) { return fn; },
    clearTimeout() {},
  },
  localStorage: { getItem: () => null, setItem() {} },
  async fetch(url, options) {
    const payload = options?.body ? JSON.parse(options.body) : null;
    calls.push({ url, method: options?.method || 'GET', payload });
    if (url.startsWith('/api/calibration/auto') && (!options || !options.method || options.method === 'GET')) {
      return { ok: true, status: 200, json: async () => autoStatus };
    }
    if (url === '/api/calibration/auto' && options.method === 'POST') {
      if (payload.op === 'start') {
        autoStatus = {
          robot_id: payload.robot_id,
          mode: payload.mode,
          state: 'running',
          phase: 'feedback_sweep',
          progress: 0.25,
          message: 'Phase 1: sweeping rear_left leg…',
          before: null,
          after: null,
          joints: [],
          can_apply: false,
          can_restore: false,
        };
      } else if (payload.op === 'apply') {
        autoStatus = { ...autoStatus, state: 'completed', can_apply: false, message: 'Calibration saved on robot.' };
      } else if (payload.op === 'restore') {
        autoStatus = { ...autoStatus, state: 'aborted', can_apply: false, can_restore: false, message: 'Restored.' };
      }
      return { ok: true, status: 200, json: async () => ({ ok: true, auto_calibration: autoStatus }) };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  },
};

let source = fs.readFileSync('Master/gateway/dashboard/static/dashboard.js', 'utf8');
source = source.replace('  if (!setupLogin()) {', `globalThis.api = {
  renderAutoCalibration, operateAutoCalibration, pollAutoCalibration, setupAutoCalibration,
  select(id) {
    selectedRobotId = id;
    calibrationEntry = { connected: true, connection_state: 'connected', epoch: 1, model: 'v2-12servo', mode: 'normal', features: ['body_calibration_v2'] };
    renderAutoCalibration();
  },
}; if (false) {`);

vm.createContext(context);
vm.runInContext(source, context);

(async () => {
  const api = context.api;
  api.setupAutoCalibration();
  api.select('p4');
  assert.equal(makeNode('auto-calibration-card').hidden, false);
  assert.equal(makeNode('auto-calibration-start').disabled, false);
  assert.equal(makeNode('auto-calibration-apply').disabled, true);

  // Switch to legs_free mode and verify help text updates.
  makeNode('auto-calibration-mode').value = 'legs_free';
  api.renderAutoCalibration();
  assert.match(makeNode('auto-calibration-help').textContent, /off the ground/i);

  // Start floor calibration.
  makeNode('auto-calibration-mode').value = 'floor';
  await api.operateAutoCalibration('start');
  assert.equal(calls.at(-1).payload.op, 'start');
  assert.equal(calls.at(-1).payload.mode, 'floor');
  assert.equal(makeNode('auto-calibration-start').disabled, true);
  assert.equal(makeNode('auto-calibration-stop').disabled, false);

  // Poll ready_to_apply state and verify before/after summary & table rows.
  autoStatus = {
    robot_id: 'p4',
    mode: 'floor',
    state: 'ready_to_apply',
    phase: 'ready_to_apply',
    progress: 1.0,
    message: 'Calibration verified.',
    before: { roll_deg: 3.4, pitch_deg: -1.8 },
    after: { roll_deg: 0.12, pitch_deg: -0.08, calibrated_joints: 12, in_range_joints: 12 },
    joints: [
      {
        id: 0,
        name: 'Rear left shoulder',
        home_us_before: 1760,
        home_us_after: 1705,
        home_delta_us: -55,
        points: [{ pulse_us: 1500, raw: 1700 }, { pulse_us: 1650, raw: 1900 }, { pulse_us: 1800, raw: 2100 }],
        error_us_before: 85,
        error_us_after: 12,
        in_calibrated_range: true,
      },
    ],
    can_apply: true,
    can_restore: true,
  };
  await api.pollAutoCalibration('p4');
  assert.equal(makeNode('auto-calibration-apply').disabled, false);
  assert.equal(makeNode('auto-calibration-restore').disabled, false);
  assert.equal(makeNode('auto-calibration-table-wrap').hidden, false);
  assert.equal(makeNode('auto-calibration-rows').children.length, 1);
  assert.match(makeNode('auto-calibration-summary').textContent, /3\.40° → 0\.12°/);

  // Apply & save.
  await api.operateAutoCalibration('apply');
  assert.equal(calls.some((c) => c.url === '/api/calibration/auto' && c.payload?.op === 'apply'), true);
  assert.equal(calls.some((c) => c.url === '/api/calibration/body' && c.payload?.op === 'get'), true);
  assert.equal(makeNode('auto-calibration-apply').disabled, true);

  // Switching robot clears stale calibration view.
  api.select('p4-other');
  assert.equal(makeNode('auto-calibration-table-wrap').hidden, true);
  console.log('Auto-calibration dashboard UI tests passed.');
})().catch((e) => { console.error(e); process.exitCode = 1; });

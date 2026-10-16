const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

function fixture() {
  const nodes = new Map(), requests = [];
  function node(id) {
    if (!nodes.has(id)) nodes.set(id, { value: '', checked: false, textContent: '', disabled: false,
      listeners: new Map(), addEventListener(type, listener) { this.listeners.set(type, listener); },
      async fire(type) { return this.listeners.get(type)?.({ preventDefault() {}, currentTarget: this }); },
    });
    return nodes.get(id);
  }
  const defaults = { wake_enabled: true, tip_enabled: true, rapid_enabled: true,
    tip_degrees: 60, tip_clear_degrees: 45, tip_hold_ms: 300, rapid_accel_g: .75,
    rapid_clear_accel_g: .35, rapid_rotation_dps: 180, rapid_clear_rotation_dps: 90, rapid_cooldown_s: 10 };
  const elements = Object.entries(defaults).map(([name, value]) => ({ name,
    type: typeof value === 'boolean' ? 'checkbox' : 'number', value: String(value), checked: value === true }));
  elements.namedItem = name => elements.find(item => item.name === name);
  node('body-events-form').elements = elements;
  const context = { console, URL, Headers, document: { getElementById: node },
    window: { addEventListener() {} }, localStorage: { getItem() { return null; } },
    fetch: async (url, options) => {
      requests.push({ url, body: JSON.parse(options.body), options });
      return { ok: true, status: 200, json: async () => ({ submitted: true }) };
    },
  };
  const source = fs.readFileSync(path.join(__dirname, '../../Master/gateway/dashboard/static/dashboard.js'), 'utf8')
    .replace('  if (!setupLogin()) {', `  globalThis.bodyTest = { setup: setupSensingControls, render: renderBodyEvents,
      select(id) { selectedRobotId = id; }, csrf(value) { csrfToken = value; } };
      refreshStatus = async () => {};
      if (false) {`);
  vm.createContext(context); vm.runInContext(source, context);
  context.bodyTest.setup(); context.bodyTest.select('p4'); context.bodyTest.csrf('fixture-csrf');
  const payload = { body_events: { defaults, robots: {}, recent: [] } };
  const entry = { connection_state: 'online', status: {} };
  context.bodyTest.render(payload, entry);
  return { node, requests, api: context.bodyTest, payload, entry };
}

test('body-event GUI saves editable thresholds for the selected robot without movement commands', async () => {
  const f = fixture();
  assert.equal(f.node('body-events-form').elements.namedItem('rapid_cooldown_s').value, 10);
  f.node('body-events-form').elements.namedItem('rapid_cooldown_s').value = '2.5';
  f.node('body-events-form').elements.namedItem('tip_degrees').value = '67';
  await f.node('body-events-form').fire('input');
  f.api.render(f.payload, f.entry);
  assert.equal(f.node('body-events-form').elements.namedItem('tip_degrees').value, '67', 'Polling preserves unsaved edits');
  await f.node('body-events-form').fire('submit');
  assert.equal(f.requests.length, 1);
  assert.equal(f.requests[0].url, '/api/body-events');
  assert.equal(f.requests[0].body.robot_id, 'p4');
  assert.equal(f.requests[0].body.settings.tip_degrees, 67);
  assert.equal(f.requests[0].body.settings.rapid_cooldown_s, 2.5);
  assert.equal(f.requests[0].body.settings.rapid_enabled, true);
});

test('good-morning GUI button reports an event for the selected robot', async () => {
  const f = fixture();
  await f.node('body-events-good-morning').fire('click');
  assert.equal(f.requests.length, 1);
  assert.equal(f.requests[0].url, '/api/body-events/good-morning');
  assert.deepEqual(f.requests[0].body, { robot_id: 'p4' });
});

test('switching robot loads its own event settings and marks disconnected controls', () => {
  const f = fixture();
  f.api.select('other');
  f.payload.body_events.robots.other = { ...f.payload.body_events.defaults, tip_degrees: 70 };
  f.api.render(f.payload, { connection_state: 'offline', status: {} });
  assert.equal(f.node('body-events-form').elements.namedItem('tip_degrees').value, 70);
  assert.equal(f.node('body-events-good-morning').disabled, true);
  assert.match(f.node('body-events-imu').textContent, /No IMU/);
});

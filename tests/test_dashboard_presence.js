const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

function fixture() {
  const nodes = new Map(), requests = [];
  function node(id) {
    if (!nodes.has(id)) nodes.set(id, {
      value: '', checked: false, textContent: '', disabled: false, hidden: false,
      classList: { toggle() {}, add() {}, remove() {} },
      setAttribute() {},
      listeners: new Map(),
      addEventListener(type, listener) { this.listeners.set(type, listener); },
      async fire(type) { return this.listeners.get(type)?.({ preventDefault() {}, currentTarget: this }); },
    });
    return nodes.get(id);
  }
  const defaults = {
    enabled: true,
    self_right_enabled: true,
    chatter_relief_enabled: true,
    social_gaze_enabled: true,
    expressions_enabled: true,
    boredom_interval_s: 25,
    servo_release_s: 180,
    presence_defers_release: true,
    passive_mode: 'calm_then_release',
  };
  const elements = Object.entries(defaults).map(([name, value]) => ({
    name,
    type: typeof value === 'boolean' ? 'checkbox' : typeof value === 'number' ? 'number' : 'select-one',
    value: String(value),
    checked: value === true,
    disabled: false,
  }));
  elements.namedItem = name => elements.find(item => item.name === name);
  node('presence-form').elements = elements;

  const context = {
    console, URL, Headers,
    document: { getElementById: node },
    window: { addEventListener() {} },
    localStorage: { getItem() { return null; } },
    fetch: async (url, options) => {
      requests.push({ url, body: JSON.parse(options.body), options });
      return { ok: true, status: 200, json: async () => ({ ok: true }) };
    },
  };
  const source = fs.readFileSync(path.join(__dirname, '../Master/gateway/dashboard/static/dashboard.js'), 'utf8')
    .replace('  if (!setupLogin()) {', `  globalThis.presenceTest = {
      setup: setupPresenceControls,
      render: renderPresence,
      select(id) { selectedRobotId = id; },
      csrf(value) { csrfToken = value; },
    };
    refreshStatus = async () => {};
    if (false) {`);
  vm.createContext(context);
  vm.runInContext(source, context);
  context.presenceTest.setup();
  context.presenceTest.select('p4');
  context.presenceTest.csrf('fixture-csrf');
  const payload = {
    presence: {
      defaults,
      policy_loaded: true,
      model_footprint: { parameter_count: 56382, int8_bytes: 56382, fp32_bytes: 225528, p4_internal_sram_fit: true },
      robots: {
        p4: {
          settings: defaults,
          mode: 'active',
          passive_reason: null,
          imu_fed_to_policy: true,
          active_expression: 'curious',
          boredom_level: 0.1,
          idle_seconds: 8.2,
          release_idle_seconds: 8.2,
          sympathy_score: 0.92,
          chatter_max_deg: 0.3,
          tracking_error_max_deg: 0.9,
          compliance_trim_max_mm: 4.2,
          person_confidence: 0.88,
          speech_rms: 0.0,
          last_error: null,
        },
      },
    },
  };
  const entry = { connection_state: 'online', status: {} };
  context.presenceTest.render(payload, entry);
  return { node, requests, api: context.presenceTest, payload, entry };
}

test('living presence GUI preserves drafts on poll and saves boredom, servo release, passive & gyro settings', async () => {
  const f = fixture();
  assert.equal(f.node('presence-form').elements.namedItem('boredom_interval_s').value, '25');
  assert.equal(f.node('presence-form').elements.namedItem('servo_release_s').value, '180');
  assert.equal(f.node('cockpit-presence-toggle').checked, true);
  assert.equal(f.node('cockpit-self-right-toggle').checked, true);
  assert.equal(f.node('presence-quick-enabled').checked, true);
  assert.equal(f.node('presence-quick-self-right').checked, true);
  assert.equal(f.node('presence-quick-badge').textContent, 'active · curious');
  assert.equal(f.node('summary-system2-mode').textContent, 'Freestyle neural actor');

  f.node('presence-form').elements.namedItem('boredom_interval_s').value = '45';
  f.node('presence-form').elements.namedItem('servo_release_s').value = '300';
  f.node('presence-form').elements.namedItem('passive_mode').value = 'release';
  await f.node('presence-form').fire('input');

  f.api.render(f.payload, f.entry);
  assert.equal(f.node('presence-form').elements.namedItem('boredom_interval_s').value, '45', 'Polling preserves unsaved edits');
  assert.equal(f.node('presence-form').elements.namedItem('servo_release_s').value, '300');

  await f.node('presence-form').fire('submit');
  assert.equal(f.requests.length, 1);
  assert.equal(f.requests[0].url, '/api/presence');
  assert.equal(f.requests[0].body.op, 'configure');
  assert.equal(f.requests[0].body.robot_id, 'p4');
  assert.equal(f.requests[0].body.settings.boredom_interval_s, 45);
  assert.equal(f.requests[0].body.settings.servo_release_s, 300);
  assert.equal(f.requests[0].body.settings.passive_mode, 'release');
});

test('cockpit self-right toggle turns off gyro feed to System 3 immediately and resume clears passive state', async () => {
  const f = fixture();
  f.node('cockpit-self-right-toggle').checked = false;
  await f.node('cockpit-self-right-toggle').fire('change');
  assert.equal(f.requests.length, 1);
  assert.equal(f.requests[0].url, '/api/presence');
  assert.equal(f.requests[0].body.op, 'configure');
  assert.equal(f.requests[0].body.settings.self_right_enabled, false);

  await f.node('presence-resume-button').fire('click');
  assert.equal(f.requests.length, 2);
  assert.deepEqual(f.requests[1].body, { op: 'resume', robot_id: 'p4', stand: true });

  f.api.render(f.payload, { connection_state: 'online', mode: 'calibrate', status: {} });
  assert.equal(f.node('presence-quick-badge').textContent, 'paused · calibration');
  assert.match(f.node('cockpit-presence-state').textContent, /paused · calibration/);
});

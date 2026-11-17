const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

function fixture() {
  const nodes = new Map(), requests = [];
  const storage = new Map();
  function makeElement(tag = 'div') {
    const classes = new Set();
    return {
      tagName: tag.toUpperCase(),
      id: '',
      className: '',
      dataset: {},
      value: '', checked: false, textContent: '', disabled: false, hidden: false,
      scrollHeight: 120, scrollTop: 120, clientHeight: 100,
      children: [],
      attributes: new Map(),
      classList: {
        toggle(name, force) {
          const next = force === undefined ? !classes.has(name) : Boolean(force);
          if (next) classes.add(name); else classes.delete(name);
          return next;
        },
        add(name) { classes.add(name); },
        remove(name) { classes.delete(name); },
        contains(name) { return classes.has(name); },
      },
      setAttribute(name, val) { this.attributes.set(name, String(val)); },
      getAttribute(name) { return this.attributes.get(name) ?? null; },
      append(...items) { this.children.push(...items); },
      replaceChildren(...items) { this.children = [...items]; },
      listeners: new Map(),
      addEventListener(type, listener) { this.listeners.set(type, listener); },
      async fire(type) { return this.listeners.get(type)?.({ preventDefault() {}, currentTarget: this }); },
    };
  }
  function node(id) {
    if (!nodes.has(id)) nodes.set(id, makeElement());
    return nodes.get(id);
  }
  const defaults = {
    enabled: true,
    self_right_enabled: true,
    chatter_relief_enabled: true,
    social_gaze_enabled: true,
    expressions_enabled: true,
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
    document: { getElementById: node, createElement: makeElement, querySelectorAll: () => [] },
    window: { addEventListener() {} },
    localStorage: {
      getItem(k) { return storage.get(k) ?? null; },
      setItem(k, v) { storage.set(k, String(v)); },
    },
    fetch: async (url, options) => {
      requests.push({ url, body: JSON.parse(options.body), options });
      return { ok: true, status: 200, json: async () => ({ ok: true }) };
    },
  };
  const source = fs.readFileSync(path.join(__dirname, '../Master/gateway/dashboard/static/dashboard.js'), 'utf8')
    .replace('  if (!setupLogin()) {', `  globalThis.presenceTest = {
      setup: setupPresenceControls,
      setupCockpit,
      render: renderPresence,
      renderStream: renderCockpitStream,
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

test('living presence GUI preserves drafts on poll and saves servo release, passive & gyro settings', async () => {
  const f = fixture();
  assert.equal(f.node('presence-form').elements.namedItem('servo_release_s').value, '180');
  assert.equal(f.node('cockpit-presence-toggle').checked, true);
  assert.equal(f.node('cockpit-self-right-toggle').checked, true);
  assert.equal(f.node('presence-quick-enabled').checked, true);
  assert.equal(f.node('presence-quick-self-right').checked, true);
  assert.equal(f.node('presence-quick-badge').textContent, 'active · curious');
  assert.equal(f.node('summary-system2-mode').textContent, 'Freestyle neural actor');

  f.node('presence-form').elements.namedItem('servo_release_s').value = '300';
  f.node('presence-form').elements.namedItem('passive_mode').value = 'release';
  await f.node('presence-form').fire('input');

  f.api.render(f.payload, f.entry);
  assert.equal(f.node('presence-form').elements.namedItem('servo_release_s').value, '300', 'Polling preserves unsaved edits');

  await f.node('presence-form').fire('submit');
  assert.equal(f.requests.length, 1);
  assert.equal(f.requests[0].url, '/api/presence');
  assert.equal(f.requests[0].body.op, 'configure');
  assert.equal(f.requests[0].body.robot_id, 'p4');
  assert.equal(f.requests[0].body.settings.servo_release_s, 300);
  assert.equal(f.requests[0].body.settings.passive_mode, 'release');
  assert.equal('boredom_interval_s' in f.requests[0].body.settings, false);
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

test('cockpit stream panel renders MetaHuman messages on the right HUD, toggles visibility, and clears cleanly', async () => {
  const f = fixture();
  f.api.setupCockpit();
  assert.equal(f.node('cockpit-stream-panel').hidden, false);

  f.api.renderStream({
    connected: true,
    messages: [
      {
        id: 'voice-1',
        role: 'user',
        source: 'voice',
        text: 'Can you see me?',
        timestamp: '2026-11-16T18:10:00Z',
      },
      {
        id: 'reply-1',
        role: 'assistant',
        source: 'voice-turn',
        text: 'Loud and clear in Cockpit.',
        timestamp: '2026-11-16T18:10:02Z',
      },
    ],
  });

  assert.equal(f.node('cockpit-stream-state').textContent, 'Live');
  assert.equal(f.node('cockpit-stream-dot').classList.contains('is-online'), true);
  const rendered = f.node('cockpit-stream-messages').children;
  assert.equal(rendered.length, 2);
  assert.equal(rendered[0].className, 'cockpit-stream-item is-user');
  assert.equal(rendered[0].children[0].children[0].textContent, 'You · voice');
  assert.equal(rendered[0].children[1].textContent, 'Can you see me?');
  assert.equal(rendered[1].className, 'cockpit-stream-item is-assistant');
  assert.equal(rendered[1].children[0].children[0].textContent, 'MetaHuman · voice-turn');
  assert.equal(rendered[1].children[1].textContent, 'Loud and clear in Cockpit.');

  await f.node('cockpit-stream-toggle').fire('click');
  assert.equal(f.node('cockpit-stream-panel').hidden, true);
  await f.node('cockpit-stream-toggle').fire('click');
  assert.equal(f.node('cockpit-stream-panel').hidden, false);

  await f.node('cockpit-stream-clear').fire('click');
  assert.equal(f.node('cockpit-stream-messages').children.length, 1);
  assert.equal(f.node('cockpit-stream-messages').children[0].id, 'cockpit-stream-empty');
  assert.equal(f.requests.at(-1).url, '/api/metahuman-stream');
  assert.deepEqual(f.requests.at(-1).body, { op: 'clear' });
});

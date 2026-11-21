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
    expressions_enabled: true,
  };

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
      policy_path: '/tmp/neural-pose-active/policy.onnx',
      robots: {
        p4: {
          settings: defaults,
          mode: 'speaking',
          active_expression: 'talk_happy',
          speech_rms: 0.62,
          stalled_released: false,
          last_error: null,
        },
      },
    },
  };
  const entry = { connection_state: 'online', status: {} };
  context.presenceTest.render(payload, entry);
  return { node, requests, api: context.presenceTest, payload, entry };
}

test('cockpit talking presence toggle saves enabled state and reflects speaking and calibration modes', async () => {
  const f = fixture();
  assert.equal(f.node('cockpit-presence-toggle').checked, true);
  assert.equal(f.node('cockpit-presence-state').textContent, 'On · mode: speaking');

  f.node('cockpit-presence-toggle').checked = false;
  await f.node('cockpit-presence-toggle').fire('change');
  assert.equal(f.requests.length, 1);
  assert.equal(f.requests[0].url, '/api/presence');
  assert.deepEqual(f.requests[0].body, { op: 'configure', robot_id: 'p4', settings: { enabled: false } });

  f.api.render(f.payload, { connection_state: 'online', mode: 'calibrate', status: {} });
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

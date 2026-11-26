/* Exercise production Virtual simulation UI controls in dashboard.js. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const nodes = new Map();
const calls = [];
const openedTabs = [];
const clipboardWrites = [];

function makeNode(id) {
  if (!nodes.has(id)) {
    const defaults = {
      'sim-model': 'v2',
      'sim-robot-id': 'ainekio-v2-sim',
      'sim-level': 'v2_lab',
      'sim-mp': 'solo',
      'sim-room': '',
      'sim-display-name': '',
      'sim-remote-url': 'https://simulator.ainek.io',
      'sim-remote-ws': 'wss://robot-gateway.ainek.io/robot',
    };
    const el = {
      id,
      value: defaults[id] ?? '',
      hidden: false,
      disabled: false,
      textContent: '',
      classList: { toggle() {}, add() {}, remove() {} },
      setAttribute() {},
      removeAttribute() {},
      querySelectorAll: () => [],
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

let simState = {
  settings: {
    model: 'v2',
    robot_id: 'ainekio-v2-sim',
    level: 'v2_lab',
    mp: 'solo',
    room: '',
    display_name: '',
    remote_simulator_url: 'https://simulator.ainek.io',
    remote_ws_url: 'wss://robot-gateway.ainek.io/robot',
  },
  local_server: { available: true, running: true, port: 8792, url: 'http://127.0.0.1:8792/' },
  headless: { supported: true, chrome_available: true, running: false, pid: null, config: null, error: null },
  robot: { robot_id: 'ainekio-v2-sim', paired: true, connected: false, epoch: null },
  links: {
    local_ws_url: 'ws://127.0.0.1:8790/robot',
    remote_ws_url: 'wss://robot-gateway.ainek.io/robot',
    room_invite_url: null,
  },
};

const context = {
  console,
  URLSearchParams,
  AbortController,
  navigator: {
    clipboard: {
      async writeText(val) { clipboardWrites.push(val); },
    },
  },
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
    open(url) {
      const tab = { initialUrl: url, replacedUrl: null, closed: false, location: { replace(u) { tab.replacedUrl = u; } }, close() { tab.closed = true; } };
      openedTabs.push(tab);
      return tab;
    },
  },
  localStorage: { getItem: () => null, setItem() {} },
  async fetch(url, options) {
    const payload = options?.body ? JSON.parse(options.body) : null;
    calls.push({ url, method: options?.method || 'GET', payload });
    if (url === '/api/simulation' && options?.method === 'POST') {
      simState = {
        ...simState,
        settings: {
          ...simState.settings,
          model: payload.model,
          robot_id: payload.robot_id,
          level: payload.level,
          mp: payload.mp,
          room: payload.room,
        },
        links: {
          ...simState.links,
          room_invite_url: payload.room ? `https://simulator.ainek.io/?room=${payload.room}` : null,
        },
      };
      if (payload.op === 'start_headless') {
        const room = payload.mp === 'host' && !payload.room ? 'ainekio-world' : payload.room;
        simState.headless = { ...simState.headless, running: true, pid: 4242, config: { robot_id: payload.robot_id, model: payload.model, level: payload.level, room: payload.mp !== 'solo' ? room : '' } };
      } else if (payload.op === 'stop_headless') {
        simState.headless = { ...simState.headless, running: false, pid: null, config: null };
      }
      let stoppedSolo = false;
      if (payload.op === 'open_tab' && simState.headless.running && !simState.headless.config?.room && simState.headless.config?.robot_id === payload.robot_id) {
        simState.headless = { ...simState.headless, running: false, pid: null, config: null };
        stoppedSolo = true;
      }
      const viewerMode = Boolean(simState.headless.running && simState.headless.config?.room);
      return {
        ok: true,
        status: 200,
        json: async () => ({
          ...simState,
          launch: {
            robot_id: payload.robot_id,
            viewer_mode: viewerMode,
            stopped_solo_headless: stoppedSolo,
            local_viewer_url: viewerMode ? `http://127.0.0.1:8792/#level=${simState.headless.config.level}&mp=join&room=${simState.headless.config.room}` : null,
            remote_viewer_url: viewerMode ? `https://simulator.ainek.io/#level=${simState.headless.config.level}&mp=join&room=${simState.headless.config.room}` : null,
            local_simulator_url: `http://127.0.0.1:8792/#bc=ws%3A%2F%2F127.0.0.1%3A8790%2Frobot&robotId=${payload.robot_id}&token=tok1`,
            remote_simulator_url: `https://simulator.ainek.io/#bc=wss%3A%2F%2Frobot-gateway.ainek.io%2Frobot&robotId=${payload.robot_id}&token=tok1`,
            pairing_code: 'ainekio-pair:eyJiYyI6IndzcyJ9',
          },
        }),
      };
    }
    return { ok: true, status: 200, json: async () => ({ simulation: simState }) };
  },
};

let source = fs.readFileSync('Master/gateway/dashboard/static/dashboard.js', 'utf8');
source = source.replace('  if (!setupLogin()) {', `globalThis.api = {
  setupSimulationControls, renderSimulationStatus, updateServoFeedback, updateIdleRest, isVirtualBody,
}; if (false) {`);

vm.createContext(context);
vm.runInContext(source, context);

(async () => {
  const api = context.api;
  api.setupSimulationControls();
  api.renderSimulationStatus(simState);

  assert.equal(makeNode('sim-headless-start-button').disabled, false);
  assert.equal(makeNode('sim-headless-stop-button').disabled, true);

  // Virtual body never triggers ESP32 port-80 HTTP maintenance requests (502 prevention)
  const callsBeforeMaint = calls.length;
  const virtualEntry = {
    connected: true,
    connection_state: 'online',
    model: 'v2-12servo',
    firmware: 'virtual-p4-sim',
    virtual: true,
    epoch: 1,
    features: ['servo_feedback_v1', 'idle_rest_v1', 'room_chat_v1'],
  };
  assert.equal(api.isVirtualBody(virtualEntry), true);
  api.updateServoFeedback(virtualEntry);
  api.updateIdleRest(virtualEntry);
  assert.equal(calls.length, callsBeforeMaint);

  // Switching model auto-updates default virtual robot ID
  makeNode('sim-model').value = 'v3';
  makeNode('sim-model').listeners.change();
  assert.equal(makeNode('sim-robot-id').value, 'ainekio-v3-sim');

  // Start headless in observatory hosting room 'wander-lab'
  makeNode('sim-level').value = 'observatory';
  makeNode('sim-mp').value = 'host';
  makeNode('sim-room').value = 'wander-lab';
  await makeNode('sim-headless-start-button').listeners.click();
  assert.equal(makeNode('sim-headless-stop-button').disabled, false);
  assert.match(makeNode('sim-status-summary').textContent, /RUNNING \(PID 4242/);
  assert.match(makeNode('sim-open-local-button').textContent, /Join active room "wander-lab" locally \(viewer\)/);

  // Opening local tab while background room is active opens viewer URL (WITHOUT #bc= collision!)
  await makeNode('sim-open-local-button').listeners.click();
  assert.equal(openedTabs.length, 1);
  assert.equal(openedTabs[0].replacedUrl, 'http://127.0.0.1:8792/#level=observatory&mp=join&room=wander-lab');

  // Copy remote pairing code & room invite link
  await makeNode('sim-copy-pair-button').listeners.click();
  assert.equal(clipboardWrites.at(-1), 'ainekio-pair:eyJiYyI6IndzcyJ9');
  await makeNode('sim-copy-room-button').listeners.click();
  assert.equal(clipboardWrites.at(-1), 'https://simulator.ainek.io/?room=wander-lab');

  // Stop headless -> Open local tab now launches full #bc= robot link
  await makeNode('sim-headless-stop-button').listeners.click();
  assert.equal(makeNode('sim-headless-stop-button').disabled, true);
  assert.equal(makeNode('sim-open-local-button').textContent, 'Open local simulator tab');
  await makeNode('sim-open-local-button').listeners.click();
  assert.equal(openedTabs.length, 2);
  assert.match(openedTabs[1].replacedUrl, /^http:\/\/127\.0\.0\.1:8792\/#bc=/);

  // Starting Solo headless then clicking Open local tab automatically stops Solo headless to prevent /robot collision
  makeNode('sim-mp').value = 'solo';
  makeNode('sim-room').value = '';
  await makeNode('sim-headless-start-button').listeners.click();
  assert.equal(makeNode('sim-headless-stop-button').disabled, false);
  await makeNode('sim-open-local-button').listeners.click();
  assert.equal(makeNode('sim-headless-stop-button').disabled, true);
  assert.match(openedTabs[2].replacedUrl, /^http:\/\/127\.0\.0\.1:8792\/#bc=/);

  console.log('test_dashboard_simulation.js: PASS');
})();

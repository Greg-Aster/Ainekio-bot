/* Production connection controls, with browser navigation and storage simulated. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

function fixture(stored = new Map()) {
  const nodes = new Map(), opened = [];
  function node(id) {
    if (!nodes.has(id)) nodes.set(id, { value: '', textContent: '', listeners: new Map(),
      addEventListener(type, listener) { this.listeners.set(type, listener); },
      fire(type) { this.listeners.get(type)?.({ preventDefault() {} }); },
      classList: { add() {}, remove() {} },
    });
    return nodes.get(id);
  }
  const context = {
    URL, console, navigator: {},
    document: { getElementById: node },
    window: { location: { origin: 'https://current-body.invalid' }, addEventListener() {},
      open(...args) { opened.push(args); } },
    localStorage: { getItem(key) { return stored.get(key) ?? null; }, setItem(key, value) { stored.set(key, value); } },
    fetch() { throw new Error('Connection selector must not send commands or credentials'); },
  };
  let source = fs.readFileSync(path.join(__dirname, '../../Master/gateway/dashboard/static/dashboard.js'), 'utf8');
  source = source.replace('  if (!setupLogin()) {', '  globalThis.connectionsTest = setupConnections;\n  if (false) {');
  vm.createContext(context);
  vm.runInContext(source, context);
  context.connectionsTest();
  return { node, opened, stored };
}

test('local, LAN and Cloudflare retain addresses for arbitrary hosts and open without command requests', () => {
  const { node, opened, stored } = fixture();
  assert.equal(node('body-current-address').textContent, 'https://current-body.invalid');
  for (const [route, url] of [['local', 'http://127.0.0.1:18791/'], ['lan', 'http://workshop-host:8791/'], ['cloudflare', 'https://body.example.invalid/']]) {
    node('body-connection-route').value = route;
    node('body-connection-route').fire('change');
    node('body-connection-address').value = url;
    node('body-connection-form').fire('submit');
    assert.deepEqual(opened.at(-1), [url, '_blank', 'noopener,noreferrer']);
  }
  const reloaded = fixture(stored);
  assert.equal(reloaded.node('body-connection-route').value, 'cloudflare');
  reloaded.node('body-connection-route').value = 'lan';
  reloaded.node('body-connection-route').fire('change');
  assert.equal(reloaded.node('body-connection-address').value, 'http://workshop-host:8791/');
  reloaded.node('body-connection-route').value = 'local';
  reloaded.node('body-connection-route').fire('change');
  assert.equal(reloaded.node('body-connection-address').value, 'http://127.0.0.1:18791/');
});

test('desktop settings open the configured MetaHuman owner page and preserve body addresses', () => {
  const { node, opened, stored } = fixture();
  node('body-connection-address').value = 'http://another-host:8791/';
  node('body-connection-form').fire('submit');
  node('desktop-connection-address').value = 'https://desktop.example.invalid/';
  node('desktop-connection-form').fire('submit');
  assert.deepEqual(opened.at(-1), ['https://desktop.example.invalid/monitor#body-connection', '_blank', 'noopener,noreferrer']);
  const saved = JSON.parse(stored.get('ainekio-connections-v1'));
  assert.equal(saved.local, 'http://another-host:8791/');
  assert.equal(saved.desktop, 'https://desktop.example.invalid');
});

test('invalid and credential-bearing addresses are reported without navigation or storage', () => {
  const { node, opened, stored } = fixture();
  for (const url of ['javascript:alert(1)', 'not a URL', 'https://user:secret@host.invalid']) {
    node('body-connection-address').value = url;
    node('body-connection-form').fire('submit');
    assert.equal(opened.length, 0);
    assert.equal(stored.size, 0);
    assert.ok(node('connections-result').textContent);
  }
});

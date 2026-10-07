import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import http from "node:http";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "../..");
const staticRoot = path.join(repoRoot, "Master/gateway/dashboard/static");
const requests = [];
const requestWaiters = new Set();
let nextSequence = 1;
let calibrationFailure = null;
let calibrationWrongSequence = false;
let delayedCalibrationRobot = null;
let releaseCalibration = null;
const calibrationByRobot = new Map();
const motionSpeedByRobot = new Map();
function calibrationFixture(home = 1300) {
  return {seq: 0, saved: true, dirty: false, ready: true, profile_confirmed: true,
    recommended_reference_us: 1300, pulse_min_us: 1, pulse_max_us: 20000,
    joints: Array.from({length: 12}, (_, id) => ({id, channel: id, home_us: home,
      home_cd: [0,117,-4041][id % 3], recommended_home_cd: [0,117,-4041][id % 3],
      us_per_degree: 11.111111, invert: false, pulse_us: id === 8 ? 1370 : home}))};
}

const statusPayload = {
  profile: "home",
  effective_caps: {
    camera_max_fps: 10,
    camera_default_resolution: "VGA",
    microphone_gates: ["open", "vad", "wake"],
    status_interval_s: 5,
  },
  joint_contract: {
    version: 1,
    joints: ["R1", "R2", "L1", "L2", "R4", "R3", "L3", "L4"].map(
      (label, id) => ({ id, label }),
    ),
  },
  robots: {
    "ainekio-emulator-01": {
      connected: true,
      connection_ssid: "Ainekio-Robot",
      epoch: 7,
      next_sequence: 20,
      pending: 0,
      heartbeat_age_ms: 12,
      last_terminal: { t: "done", seq: 19 },
      last_command: { t: "intent", name: "stand", seq: 19 },
      microphone_level: 0.2,
      status: {
        t: "status",
        vbat: 7.8,
        rssi: -45,
        state: "active",
        uptime: 120,
        heap: 180000,
        sd: false,
        cam_drops: 0,
        spk_underruns: 0,
        mic_drops: 0,
      },
    },
  },
  token_robot_ids: ["ainekio-emulator-01"],
  audit: [],
};

function json(response, status, payload) {
  const body = Buffer.from(JSON.stringify(payload));
  response.writeHead(status, {
    "Content-Type": "application/json",
    "Content-Length": body.length,
    "Cache-Control": "no-store",
  });
  response.end(body);
}

async function readRequestBody(request) {
  const chunks = [];
  let length = 0;
  for await (const chunk of request) {
    length += chunk.length;
    if (length > 64 * 1024) throw new Error("request body is oversized");
    chunks.push(chunk);
  }
  return chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf8")) : {};
}

const server = http.createServer(async (request, response) => {
  try {
    const url = new URL(request.url, "http://127.0.0.1");
    if (request.method === "GET" && (url.pathname === "/" || url.pathname === "/login")) {
      const page = url.pathname === "/login" ? "login.html" : "dashboard.html";
      const body = await readFile(path.join(staticRoot, page));
      response.writeHead(200, { "Content-Type": "text/html", "Content-Length": body.length });
      response.end(body);
      return;
    }
    if (request.method === "GET" && url.pathname.startsWith("/assets/")) {
      const filename = path.basename(url.pathname);
      const body = await readFile(path.join(staticRoot, filename));
      const contentType = filename.endsWith(".js") ? "text/javascript" : "text/css";
      response.writeHead(200, { "Content-Type": contentType, "Content-Length": body.length });
      response.end(body);
      return;
    }
    if (request.method === "GET" && url.pathname === "/api/session") {
      json(response, 200, { csrf: "browser-acceptance-csrf" });
      return;
    }
    if (request.method === "GET" && url.pathname === "/api/status") {
      json(response, 200, statusPayload);
      return;
    }
    if (request.method === "POST" && url.pathname.startsWith("/api/")) {
      const payload = await readRequestBody(request);
      recordRequest({ path: url.pathname, payload });
      if (url.pathname === "/api/motion-speed") {
        const state = motionSpeedByRobot.get(payload.robot_id) || {rate:2,saved:false};
        if (payload.op === "save") {state.rate=payload.rate;state.saved=true;}
        motionSpeedByRobot.set(payload.robot_id,state);
        const seq=nextSequence++;
        json(response,200,{seq,motion_speed:{t:"motion_speed_status",seq,...state}});
        return;
      }
      if (url.pathname === "/api/calibration/body") {
        const state = calibrationByRobot.get(payload.robot_id);
        if (!state) throw new Error("Unknown fixture robot");
        if (calibrationFailure === payload.op) {
          calibrationFailure = null;
          json(response, 409, {error: "Fixture: robot read/save failed"});
          return;
        }
        if (payload.op === "set") {
          const {id, channel, home_us, home_cd, us_per_degree, invert} = payload;
          Object.assign(state.joints[id], {channel, home_us, home_cd, us_per_degree, invert});
          state.dirty = true;
        } else if (payload.op === "save") {
          state.saved = true; state.dirty = false;
        }
        state.seq = nextSequence++;
        const calibration = structuredClone(state);
        const seq = state.seq;
        if (calibrationWrongSequence) {calibrationWrongSequence = false; calibration.seq += 100;}
        const send = () => json(response, 200, {seq, calibration});
        if (payload.robot_id === delayedCalibrationRobot) {delayedCalibrationRobot = null; releaseCalibration = send;}
        else send();
        return;
      }
      json(response, 200, { seq: nextSequence++ });
      return;
    }
    json(response, 404, { error: "not_found" });
  } catch (error) {
    json(response, 500, { error: String(error.message || error) });
  }
});

function listen(target) {
  return new Promise((resolve, reject) => {
    target.once("error", reject);
    target.listen(0, "127.0.0.1", () => resolve(target.address().port));
  });
}

function availablePort() {
  const probe = net.createServer();
  return listen(probe).then((port) => new Promise((resolve) => probe.close(() => resolve(port))));
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function recordRequest(item) {
  requests.push(item);
  for (const waiter of requestWaiters) waiter();
}

function waitForRequests(predicate, message, timeout = 2000) {
  if (predicate(requests)) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      requestWaiters.delete(check);
      reject(new Error(message));
    }, timeout);
    const check = () => {
      if (!predicate(requests)) return;
      clearTimeout(timer);
      requestWaiters.delete(check);
      resolve();
    };
    requestWaiters.add(check);
  });
}

class CdpClient {
  constructor(url) {
    this.socket = new WebSocket(url);
    this.nextId = 1;
    this.pending = new Map();
    this.events = [];
  }

  async open() {
    await new Promise((resolve, reject) => {
      this.socket.addEventListener("open", resolve, { once: true });
      this.socket.addEventListener("error", reject, { once: true });
    });
    this.socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.id) {
        const pending = this.pending.get(message.id);
        if (!pending) return;
        this.pending.delete(message.id);
        if (message.error) pending.reject(new Error(message.error.message));
        else pending.resolve(message.result);
        return;
      }
      this.events.push(message);
    });
  }

  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  close() {
    this.socket.close();
  }
}

async function targetWebSocket(debugPort) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${debugPort}/json`);
      const targets = await response.json();
      const page = targets.find((target) => target.type === "page");
      if (page) return page.webSocketDebuggerUrl;
    } catch (_error) {
      // Chrome has not opened its DevTools listener yet.
    }
    await delay(50);
  }
  throw new Error("Chrome DevTools target did not become ready");
}

async function evaluate(client, expression) {
  const response = await client.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (response.exceptionDetails) {
    throw new Error(response.exceptionDetails.text || "browser evaluation failed");
  }
  return response.result.value;
}

async function waitFor(client, expression, timeout = 5000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await evaluate(client, expression)) return;
    await delay(25);
  }
  throw new Error(`browser condition timed out: ${expression}`);
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const expectedEmotes = [
  "rest", "crouch", "wave", "dance", "swim", "point", "pushup", "bow",
  "cute", "freaky", "worm", "shake", "shrug", "dead", "lay_down", "crab",
  "nod", "celebrate", "stretch",
  "macarena", "salsa", "surprised", "sad", "curious",
  "turn_left_45", "turn_right_45", "turn_left_90", "turn_right_90",
  "turn_left_180", "turn_right_180", "walk_slow", "run",
  "number_one", "number_two",
];

let chrome;
let client;
let profileDirectory;
try {
  const webPort = await listen(server);
  const debugPort = await availablePort();
  profileDirectory = await mkdtemp(path.join(os.tmpdir(), "ainekio-dashboard-chrome-"));
  chrome = spawn(
    process.env.AINEKIO_TEST_BROWSER || "/usr/bin/google-chrome",
    [
      "--headless=new",
      "--no-sandbox",
      "--disable-gpu",
      "--disable-dev-shm-usage",
      `--remote-debugging-port=${debugPort}`,
      `--user-data-dir=${profileDirectory}`,
      "about:blank",
    ],
    { stdio: ["ignore", "ignore", "pipe"] },
  );
  const chromeErrors = [];
  chrome.stderr.on("data", (chunk) => {
    const text = chunk.toString("utf8");
    if (/FATAL|Segmentation fault/i.test(text)) chromeErrors.push(text.trim());
  });

  client = new CdpClient(await targetWebSocket(debugPort));
  await client.open();
  await client.send("Page.enable");
  await client.send("Runtime.enable");
  await client.send("Page.addScriptToEvaluateOnNewDocument", {
    source: `
      globalThis.__ainekioGamepads = [];
      Object.defineProperty(navigator, "getGamepads", {
        configurable: true,
        value: () => globalThis.__ainekioGamepads,
      });
    `,
  });
  await client.send("Page.navigate", { url: `http://127.0.0.1:${webPort}/` });
  await waitFor(client, `document.readyState === "complete" && document.querySelector("#connection-state")?.textContent === "Online · Ainekio-Robot"`);
  statusPayload.robots["ainekio-emulator-01"].connection_ssid = "CenturyLink3059";
  await waitFor(client, `document.querySelector("#connection-state").textContent === "Online · CenturyLink3059"`);
  statusPayload.robots["ainekio-emulator-01"].connection_state = "stale";
  await waitFor(client, `document.querySelector("#connection-state").textContent === "Stale · CenturyLink3059" && document.querySelector("#connection-state").classList.contains("stale")`);
  statusPayload.robots["ainekio-emulator-01"].connection_state = "online";
  delete statusPayload.robots["ainekio-emulator-01"].connection_ssid;
  await waitFor(client, `document.querySelector("#connection-state").textContent === "Online"`);
  statusPayload.robots["ainekio-emulator-01"].connection_ssid = "Ainekio-Robot";
  await waitFor(client, `document.querySelector("#connection-state").textContent === "Online · Ainekio-Robot"`);
  assert(await evaluate(client, `document.querySelector('#servo-form').elements.id.options.length === 8 && document.querySelector('#calibration-settings').hidden`), "V1 calibration was changed by the V2 UI");

  const emotes = await evaluate(
    client,
    `Array.from(document.querySelectorAll("[data-emote]"), element => element.dataset.emote)`,
  );
  assert(JSON.stringify(emotes) === JSON.stringify(expectedEmotes), "full seed emote catalog is not exposed");

  requests.length = 0;
  await evaluate(client, `document.querySelector('[data-intent="sit"]').click()`);
  await waitForRequests(
    (items) => items.some((item) => item.path === "/api/intent" && item.payload.name === "sit"),
    "visible sit control did not issue the semantic sit intent",
  );

  await evaluate(client, `(() => new Promise((resolve) => {
    window.dispatchEvent(new Event("beforeunload"));
    const image = document.querySelector("#camera-view");
    image.addEventListener("load", resolve, { once: true });
    image.src = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='1024' height='768'%3E%3Crect width='1024' height='768' fill='%23111827'/%3E%3C/svg%3E";
    image.hidden = false;
    document.querySelector("#camera-view-message").hidden = true;
  }))()`);
  const cameraLayout = await evaluate(client, `(() => {
    const stage = document.querySelector(".camera-stage").getBoundingClientRect();
    const image = document.querySelector("#camera-view").getBoundingClientRect();
    return {
      stage: { top: stage.top, bottom: stage.bottom },
      image: { top: image.top, bottom: image.bottom, width: image.width, height: image.height },
    };
  })()`);
  assert(Math.abs((cameraLayout.image.width / cameraLayout.image.height) - (4 / 3)) < 0.01, "camera image aspect ratio is distorted");
  assert(cameraLayout.image.top >= cameraLayout.stage.top, "camera image top is clipped");
  assert(cameraLayout.image.bottom <= cameraLayout.stage.bottom, "camera image bottom is clipped");

  requests.length = 0;
  await evaluate(client, `(() => {
    const button = document.querySelector('[data-held-direction="fwd"]');
    button.setPointerCapture = () => {};
    button.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 1 }));
    button.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 1 }));
    button.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, pointerId: 1 }));
  })()`);
  await waitForRequests(
    (items) => items.some((item) => item.path === "/api/stop"),
    "pointer release did not signal stop",
  );
  await delay(50);
  assert(requests.filter((item) => item.path === "/api/intent").length === 1, "held pointer issued more than one walk");
  const pointerIntent = requests.find((item) => item.path === "/api/intent");
  assert(pointerIntent.payload.name === "walk", "held pointer did not issue semantic walk");
  assert(pointerIntent.payload.params.dir === "fwd", "held pointer changed walk direction");
  assert(pointerIntent.payload.params.steps === 10, "held pointer walk was not bounded to ten steps");
  assert(requests.some((item) => item.path === "/api/stop"), "pointer release did not signal stop");
  await waitFor(client, `document.querySelector(".motion-pad").getAttribute("aria-busy") !== "true"`);

  requests.length = 0;
  await evaluate(client, `(() => {
    document.body.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, code: "KeyW" }));
    document.body.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true, code: "KeyW" }));
  })()`);
  await waitForRequests(
    (items) => items.some((item) => item.path === "/api/intent")
      && items.some((item) => item.path === "/api/stop"),
    "keyboard motion lifecycle did not complete",
  );
  assert(requests.some((item) => item.path === "/api/intent"), "keyboard did not issue semantic walk");
  assert(requests.some((item) => item.path === "/api/stop"), "keyboard release did not signal stop");
  await waitFor(client, `document.querySelector(".motion-pad").getAttribute("aria-busy") !== "true"`);

  requests.length = 0;
  await evaluate(client, `(() => {
    globalThis.__ainekioGamepads = [{ axes: [0, -1], buttons: [] }];
    window.dispatchEvent(new Event("gamepadconnected"));
  })()`);
  await waitForRequests(
    (items) => items.some((item) => item.path === "/api/intent"),
    "gamepad did not issue semantic walk",
  );
  await evaluate(client, `globalThis.__ainekioGamepads = [{ axes: [0, 0], buttons: [] }]`);
  await waitForRequests(
    (items) => items.some((item) => item.path === "/api/stop"),
    "gamepad neutral did not signal stop",
  );
  assert(requests.some((item) => item.path === "/api/intent"), "gamepad did not issue semantic walk");
  assert(requests.some((item) => item.path === "/api/stop"), "gamepad neutral did not signal stop");
  await waitFor(client, `document.querySelector(".motion-pad").getAttribute("aria-busy") !== "true"`);

  requests.length = 0;
  await evaluate(client, `(() => {
    const button = document.querySelector('[data-held-direction="turn_l"]');
    button.setPointerCapture = () => {};
    button.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 2 }));
  })()`);
  await waitForRequests(
    (items) => items.some((item) => item.path === "/api/intent"),
    "blur setup did not issue semantic walk",
  );
  await evaluate(client, `window.dispatchEvent(new Event("blur"))`);
  await waitForRequests(
    (items) => items.some((item) => item.path === "/api/stop"),
    "window blur did not signal stop",
  );
  assert(requests.some((item) => item.path === "/api/stop"), "window blur did not signal stop");
  await waitFor(client, `document.querySelector(".motion-pad").getAttribute("aria-busy") !== "true"`);

  requests.length = 0;
  await evaluate(client, `(() => {
    const button = document.querySelector('[data-held-direction="back"]');
    button.setPointerCapture = () => {};
    button.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 3 }));
  })()`);
  await waitForRequests(
    (items) => items.some((item) => item.path === "/api/intent"),
    "page-loss setup did not issue semantic walk",
  );
  await evaluate(client, `window.dispatchEvent(new PageTransitionEvent("pagehide"))`);
  await waitForRequests(
    (items) => items.some((item) => item.path === "/api/stop"),
    "page loss did not signal stop",
  );
  assert(requests.some((item) => item.path === "/api/stop"), "page loss did not signal stop");

  await evaluate(client, `(() => {
    const form = document.querySelector("#controller-mapping-form");
    form.elements.fwd.value = "KeyI";
    form.requestSubmit();
  })()`);
  await delay(50);
  const savedMapping = await evaluate(
    client,
    `JSON.parse(localStorage.getItem("ainekio-controller-mappings")).fwd`,
  );
  assert(savedMapping === "KeyI", "editable controller mapping did not persist");

  for (const item of requests.filter((entry) => entry.path === "/api/intent")) {
    assert(item.payload.name === "walk", "manual control emitted a non-semantic intent");
    assert(item.payload.params.steps === 10, "manual walk was not bounded to ten steps");
  }
  assert(!requests.some((item) => item.path.includes("servo")), "normal controls reached a servo endpoint");

  await client.send("Emulation.setDeviceMetricsOverride", {
    width: 390,
    height: 844,
    deviceScaleFactor: 1,
    mobile: true,
  });
  await delay(100);
  const mobileLayout = await evaluate(client, `({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
    stopWidth: document.querySelector("#stop-button").getBoundingClientRect().width,
  })`);
  assert(mobileLayout.scrollWidth <= mobileLayout.innerWidth, "dashboard has horizontal mobile overflow");
  assert(mobileLayout.stopWidth <= mobileLayout.innerWidth, "stop control overflows mobile viewport");

  const mobileShot = await client.send("Page.captureScreenshot", { format: "png" });
  await writeFile("/tmp/ainekio-dashboard-mobile.png", Buffer.from(mobileShot.data, "base64"));
  await client.send("Emulation.setDeviceMetricsOverride", {
    width: 1440,
    height: 1000,
    deviceScaleFactor: 1,
    mobile: false,
  });
  const desktopShot = await client.send("Page.captureScreenshot", { format: "png" });
  await writeFile("/tmp/ainekio-dashboard-desktop.png", Buffer.from(desktopShot.data, "base64"));

  await client.send("Emulation.setDeviceMetricsOverride", {
    width: 390,
    height: 844,
    deviceScaleFactor: 1,
    mobile: true,
  });
  await client.send("Page.navigate", { url: `http://127.0.0.1:${webPort}/login` });
  await waitFor(client, `document.readyState === "complete" && document.querySelector("#login-form")`);
  const loginLayout = await evaluate(client, `(() => {
    const panel = document.querySelector(".login-panel").getBoundingClientRect();
    const password = document.querySelector("#password").getBoundingClientRect();
    const submit = document.querySelector(".primary-command").getBoundingClientRect();
    return {
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
      panel: { left: panel.left, right: panel.right },
      passwordRight: password.right,
      submitRight: submit.right,
    };
  })()`);
  assert(loginLayout.scrollWidth <= loginLayout.innerWidth, "login has horizontal mobile overflow");
  assert(loginLayout.panel.left >= 0, "login panel begins outside the mobile viewport");
  assert(loginLayout.panel.right <= loginLayout.innerWidth, "login panel exceeds the mobile viewport");
  assert(loginLayout.passwordRight <= loginLayout.panel.right, "login password field exceeds its panel");
  assert(loginLayout.submitRight <= loginLayout.panel.right, "login submit control exceeds its panel");

  const loginMobileShot = await client.send("Page.captureScreenshot", { format: "png" });
  await writeFile(
    "/tmp/ainekio-dashboard-login-mobile.png",
    Buffer.from(loginMobileShot.data, "base64"),
  );

  // V2 calibration runs only against this isolated HTTP fixture, never hardware.
  statusPayload.robots = Object.fromEntries(["p4-a", "p4-b"].map(id => [id, {
    connected: true, connection_state: "online", model: "v2-12servo", mode: "calibrate",
    epoch: 1, next_sequence: 100, pending: 0, heartbeat_age_ms: 10,
    features: ["body_calibration_v2"], capabilities: {motion: false, commands: []},
  }]));
  calibrationByRobot.set("p4-a", calibrationFixture());
  calibrationByRobot.set("p4-b", calibrationFixture(1600));
  await evaluate(client, `localStorage.setItem('ainekio-selected-robot', JSON.stringify('p4-a'))`);
  await client.send("Page.navigate", {url: `http://127.0.0.1:${webPort}/`});
  await waitFor(client, `document.querySelector('#calibration-body-home')?.textContent === '1300 µs' && !document.querySelector('#calibration-read-button').disabled`);
  await evaluate(client, `(() => { const s=document.querySelector('#servo-form').elements.id; s.value='8'; s.dispatchEvent(new Event('change', {bubbles:true})); })()`);
  await waitFor(client, `document.querySelector('#calibration-body-angle').textContent === '-40.41°'`);
  assert(await evaluate(client, `document.querySelector('#servo-form').elements.id.selectedOptions[0].textContent === 'Front left crank'`), "joint label must describe the physical joint without masquerading as an output number");
  assert(await evaluate(client, `document.querySelector('#calibration-joint-help').textContent.includes('Part_005') && document.querySelector('#calibration-body-channel').textContent === 'Output 8'`), "joint-to-part and output mapping are missing");

  const setDraft = async (name, value) => evaluate(client, `(() => {
    const input=document.querySelector('#body-calibration-form').elements[${JSON.stringify(name)}];
    if(input.type==='checkbox') input.checked=${JSON.stringify(value)}; else input.value=${JSON.stringify(value)};
    input.dispatchEvent(new Event('input',{bubbles:true}));
  })()`);
  requests.length = 0;
  await setDraft('home_deg', '0'); await setDraft('invert', true);
  assert(requests.length === 0, "editing calibration sent a robot command");
  await evaluate(client, `document.querySelector('#calibration-read-button').click()`);
  await waitFor(client, `document.querySelector('#calibration-feedback').textContent.startsWith('Read complete.') && !document.querySelector('#calibration-read-button').disabled`);
  const separated = await evaluate(client, `({robotAngle:document.querySelector('#calibration-body-angle').textContent, robotInvert:document.querySelector('#calibration-body-invert').textContent, draftAngle:document.querySelector('#body-calibration-form').elements.home_deg.value, draftInvert:document.querySelector('#body-calibration-form').elements.invert.checked, notice:document.querySelector('#calibration-draft-status').textContent})`);
  assert(separated.robotAngle === '-40.41°' && separated.robotInvert === 'Off', "readback is hidden by local draft settings");
  assert(separated.draftAngle === '0' && separated.draftInvert && separated.notice.includes('Local edits'), "read silently discarded or concealed local edits");
  assert(requests.every(r => r.path === '/api/calibration/body' && r.payload.op === 'get'), "read issued a write or motion");

  const beforeDiscard = requests.length;
  await evaluate(client, `document.querySelector('#calibration-use-body-values').click()`);
  assert(await evaluate(client, `document.querySelector('#body-calibration-form').elements.home_deg.value === '-40.41' && !document.querySelector('#body-calibration-form').elements.invert.checked`), "discard did not restore confirmed settings");
  assert(requests.length === beforeDiscard, "discard sent a command");
  await evaluate(client, `globalThis.__reloadPending = true`);
  await client.send("Page.reload");
  await waitFor(client, `globalThis.__reloadPending !== true && document.readyState === "complete"`);
  await waitFor(client, `document.querySelector('#calibration-body-angle')?.textContent === '-40.41°' && !document.querySelector('#calibration-read-button').disabled`);
  assert(await evaluate(client, `document.querySelector('#body-calibration-form').elements.home_deg.value === '-40.41'`), "discarded local edits returned after reload");

  requests.length = 0;
  await evaluate(client, `document.querySelector('#calibration-use-position-button').click()`);
  assert(await evaluate(client, `document.querySelector('#body-calibration-form').elements.center.value === '1370' && document.querySelector('#calibration-body-home').textContent === '1300 µs'`), "copy pulse did not stay a local edit");
  assert(requests.length === 0, "copying a pulse applied settings without an explicit apply/save");
  await evaluate(client, `document.querySelector('#body-calibration-form').requestSubmit()`);
  await waitFor(client, `document.querySelector('#calibration-feedback').textContent.startsWith('Settings applied temporarily.') && !document.querySelector('#calibration-save-button').disabled`);
  assert(requests.length === 1 && requests[0].payload.op === 'set' && requests[0].payload.id === 8 && requests[0].payload.home_us === 1370, "temporary apply sent the wrong joint or operation");
  assert(await evaluate(client, `document.querySelector('#calibration-readback-status').textContent.includes('not saved after restart')`), "temporary and persistent settings are indistinguishable");

  calibrationFailure = 'save';
  await evaluate(client, `document.querySelector('#calibration-save-button').click()`);
  await waitFor(client, `document.querySelector('#calibration-feedback').classList.contains('error') && document.querySelector('#calibration-feedback').textContent.includes('failed')`);
  assert(!await evaluate(client, `document.querySelector('#calibration-feedback').textContent.includes('successfully')`), "failed save claimed success");
  await evaluate(client, `document.querySelector('#calibration-read-button').click()`);
  await waitFor(client, `document.querySelector('#calibration-feedback').textContent.startsWith('Read complete.') && !document.querySelector('#calibration-save-button').disabled`);
  await evaluate(client, `document.querySelector('#calibration-save-button').click()`);
  await waitFor(client, `document.querySelector('#calibration-feedback').textContent.includes('saved on the robot and read back successfully')`);
  assert(await evaluate(client, `document.querySelector('#calibration-readback-status').textContent.startsWith('Saved on robot.')`), "save readback is not displayed");
  assert(requests.every(r => r.path === '/api/calibration/body' && ['get','set','save'].includes(r.payload.op)), "calibration settings operations moved a servo");

  calibrationFailure = 'get';
  await evaluate(client, `document.querySelector('#calibration-read-button').click()`);
  await waitFor(client, `document.querySelector('#calibration-feedback').classList.contains('error')`);
  assert(await evaluate(client, `document.querySelector('#calibration-body-angle').textContent === '—' && !document.querySelector('#calibration-read-button').disabled`), "failed read left an apparently successful readback or locked retry");
  calibrationWrongSequence = true;
  await evaluate(client, `document.querySelector('#calibration-read-button').click()`);
  await waitFor(client, `document.querySelector('#calibration-feedback').textContent.includes('did not confirm the requested operation')`);

  delayedCalibrationRobot = 'p4-a';
  await evaluate(client, `document.querySelector('#calibration-read-button').click()`);
  await waitFor(client, `document.querySelector('#calibration-feedback').textContent.startsWith('Reading settings') && document.querySelector('#calibration-read-button').disabled`);
  assert(releaseCalibration, "delayed fixture request was not captured");
  await evaluate(client, `(() => {const s=document.querySelector('#robot-select');s.value='p4-b';s.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  await waitFor(client, `document.querySelector('#calibration-body-home').textContent === '1600 µs' && !document.querySelector('#calibration-read-button').disabled`);
  releaseCalibration(); releaseCalibration = null;
  await delay(150);
  assert(await evaluate(client, `document.querySelector('#calibration-body-home').textContent === '1600 µs'`), "old robot readback crossed the robot selection");

  for (const [width,height,name] of [[1440,1300,'desktop'],[390,844,'mobile']]) {
    await client.send('Emulation.setDeviceMetricsOverride', {width,height,deviceScaleFactor:1,mobile:width<500});
    await evaluate(client, `document.querySelector('.calibration-section').scrollIntoView()`);
    const layout = await evaluate(client, `({width:innerWidth,scroll:document.documentElement.scrollWidth,visible:!document.querySelector('#calibration-settings').hidden})`);
    assert(layout.scroll <= layout.width && layout.visible, `V2 calibration ${name} layout overflows or is hidden`);
    const clip = await evaluate(client, `(() => {const r=document.querySelector('.calibration-section').getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1};})()`);
    const shot = await client.send('Page.captureScreenshot', {format:'png',clip,captureBeyondViewport:true});
    await writeFile(`/tmp/ainekio-calibration-${name}.png`, Buffer.from(shot.data,'base64'));
  }

  const exceptions = client.events.filter((event) => event.method === "Runtime.exceptionThrown");
  assert(exceptions.length === 0, `dashboard raised ${exceptions.length} browser exceptions`);
  // Saved named-motion speed uses the isolated robot fixture, never hardware.
  const speedRobot=statusPayload.robots["p4-a"];
  speedRobot.features.push("motion_speed_v1");
  speedRobot.mode="normal";speedRobot.capabilities={motion:true,commands:["stand","sit","wave","stop"]};
  speedRobot.robot_commands=["stand","sit","wave","stop"];
  await evaluate(client, `localStorage.setItem('ainekio-selected-robot', JSON.stringify('p4-a'))`);
  await evaluate(client, `globalThis.__reloadPending = true`);
  await client.send("Page.reload");
  await waitFor(client, `globalThis.__reloadPending !== true && document.readyState === "complete"`);
  await waitFor(client, `document.querySelector('#motion-speed')?.disabled === false`);
  assert(await evaluate(client, `document.querySelector('#motion-speed').value === '2'`), "motion speed default must be 2x");
  assert(await evaluate(client, `document.querySelector('#motion-speed').max === '' && document.querySelector('#motion-speed').min === '' && document.querySelector('#motion-speed').step === 'any'`), "motion speed must not impose a range or step cap");
  requests.length=0;
  await evaluate(client, `(() => {const s=document.querySelector('#motion-speed');s.value='6.125';s.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  assert(requests.length===0,"speed editing must remain local");
  await evaluate(client, `document.querySelector('[data-emote="wave"]').click()`);
  await waitForRequests(() => requests.some(r=>r.path==="/api/intent" && r.payload.params?.asset==="wave"), "Wave request missing");
  assert(requests.at(-1).payload.params.playback_rate===6.125,"Wave omitted selected speed");
  await evaluate(client, `document.querySelector('#motion-speed-save').click()`);
  await waitFor(client, `document.querySelector('#motion-speed-status').textContent.startsWith('Saved on robot: 6.125') && !document.querySelector('#motion-speed-read').disabled`);
  assert(motionSpeedByRobot.get("p4-a").rate===6.125,"save did not reach robot fixture");
  await evaluate(client, `globalThis.__reloadPending = true`);
  await client.send("Page.reload");
  await waitFor(client, `globalThis.__reloadPending !== true && document.readyState === "complete"`);
  await waitFor(client, `document.querySelector('#motion-speed')?.value === '6.125' && document.querySelector('#motion-speed')?.disabled === false`);
  await evaluate(client, `document.querySelector('#motion-speed-controls').scrollIntoView()`);
  const motionLayout=await evaluate(client, `({width:innerWidth,scroll:document.documentElement.scrollWidth})`);
  assert(motionLayout.scroll<=motionLayout.width+1,"motion speed controls overflow mobile view");
  assert(chromeErrors.length === 0, chromeErrors.join("\n"));

  console.log(JSON.stringify({
    result: "passed",
    checks: [
      "connection-header-network-and-stale-state",
      "saved-motion-speed-default-preview-readback",
      "full-emote-catalog",
      "visible-semantic-sit",
      "camera-full-frame",
      "pointer-release-stop",
      "keyboard-release-stop",
      "gamepad-neutral-stop",
      "blur-stop",
      "page-loss-stop",
      "one-bounded-walk-in-flight",
      "editable-mappings",
      "semantic-commands-only",
      "mobile-no-overflow",
      "login-mobile-no-overflow",
      "v1-calibration-preserved",
      "v2-readback-separated-from-drafts",
      "discard-persists-across-reload",
      "copy-home-is-local-only",
      "temporary-apply-and-confirmed-save",
      "read-and-save-errors-inline",
      "mismatched-and-late-readback-rejected",
      "settings-actions-do-not-move-servos",
      "v2-calibration-desktop-mobile-layout",
    ],
    screenshots: [
      "/tmp/ainekio-dashboard-desktop.png",
      "/tmp/ainekio-dashboard-mobile.png",
      "/tmp/ainekio-dashboard-login-mobile.png",
      "/tmp/ainekio-calibration-desktop.png",
      "/tmp/ainekio-calibration-mobile.png",
    ],
  }, null, 2));
} finally {
  if (client) client.close();
  if (chrome) {
    chrome.kill("SIGTERM");
    await new Promise((resolve) => chrome.once("exit", resolve));
  }
  await new Promise((resolve) => server.close(resolve));
  if (profileDirectory) {
    await rm(profileDirectory, {
      recursive: true,
      force: true,
      maxRetries: 5,
      retryDelay: 50,
    });
  }
}

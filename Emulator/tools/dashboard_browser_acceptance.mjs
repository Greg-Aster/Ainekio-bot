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
let nextSequence = 1;

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
      requests.push({ path: url.pathname, payload });
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
  "rest", "stand", "wave", "dance", "swim", "point", "pushup", "bow",
  "cute", "freaky", "worm", "shake", "shrug", "dead", "crab",
];

let chrome;
let client;
let profileDirectory;
try {
  const webPort = await listen(server);
  const debugPort = await availablePort();
  profileDirectory = await mkdtemp(path.join(os.tmpdir(), "ainekio-dashboard-chrome-"));
  chrome = spawn(
    "/usr/bin/google-chrome",
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
  await waitFor(client, `document.readyState === "complete" && document.querySelector("#connection-state")?.textContent === "Online"`);

  const emotes = await evaluate(
    client,
    `Array.from(document.querySelectorAll("[data-emote]"), element => element.dataset.emote)`,
  );
  assert(JSON.stringify(emotes) === JSON.stringify(expectedEmotes), "full seed emote catalog is not exposed");

  requests.length = 0;
  await evaluate(client, `(() => {
    const button = document.querySelector('[data-held-direction="fwd"]');
    button.setPointerCapture = () => {};
    button.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 1 }));
    button.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 1 }));
    button.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, pointerId: 1 }));
  })()`);
  await delay(150);
  assert(requests.filter((item) => item.path === "/api/intent").length === 1, "held pointer issued more than one walk");
  assert(requests.some((item) => item.path === "/api/stop"), "pointer release did not signal stop");

  requests.length = 0;
  await evaluate(client, `(() => {
    document.body.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, code: "KeyW" }));
    document.body.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true, code: "KeyW" }));
  })()`);
  await delay(150);
  assert(requests.some((item) => item.path === "/api/intent"), "keyboard did not issue semantic walk");
  assert(requests.some((item) => item.path === "/api/stop"), "keyboard release did not signal stop");

  requests.length = 0;
  await evaluate(client, `globalThis.__ainekioGamepads = [{ axes: [0, -1], buttons: [] }]`);
  await delay(100);
  await evaluate(client, `globalThis.__ainekioGamepads = [{ axes: [0, 0], buttons: [] }]`);
  await delay(100);
  assert(requests.some((item) => item.path === "/api/intent"), "gamepad did not issue semantic walk");
  assert(requests.some((item) => item.path === "/api/stop"), "gamepad neutral did not signal stop");

  requests.length = 0;
  await evaluate(client, `(() => {
    const button = document.querySelector('[data-held-direction="turn_l"]');
    button.setPointerCapture = () => {};
    button.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 2 }));
    window.dispatchEvent(new Event("blur"));
  })()`);
  await delay(150);
  assert(requests.some((item) => item.path === "/api/stop"), "window blur did not signal stop");

  requests.length = 0;
  await evaluate(client, `(() => {
    const button = document.querySelector('[data-held-direction="back"]');
    button.setPointerCapture = () => {};
    button.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerId: 3 }));
    window.dispatchEvent(new PageTransitionEvent("pagehide"));
  })()`);
  await delay(150);
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
    assert(item.payload.params.steps === 1, "manual walk was not bounded to one step");
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

  const exceptions = client.events.filter((event) => event.method === "Runtime.exceptionThrown");
  assert(exceptions.length === 0, `dashboard raised ${exceptions.length} browser exceptions`);
  assert(chromeErrors.length === 0, chromeErrors.join("\n"));

  console.log(JSON.stringify({
    result: "passed",
    checks: [
      "full-emote-catalog",
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
    ],
    screenshots: [
      "/tmp/ainekio-dashboard-desktop.png",
      "/tmp/ainekio-dashboard-mobile.png",
      "/tmp/ainekio-dashboard-login-mobile.png",
    ],
  }, null, 2));
} finally {
  if (client) client.close();
  if (chrome) {
    chrome.kill("SIGTERM");
    await new Promise((resolve) => chrome.once("exit", resolve));
  }
  await new Promise((resolve) => server.close(resolve));
  if (profileDirectory) await rm(profileDirectory, { recursive: true, force: true });
}

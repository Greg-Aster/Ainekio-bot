(function () {
  "use strict";

  let csrfToken = null;
  let selectedRobotId = null;
  let heldDirection = null;
  let heldRequestPending = false;
  let statusTimer = null;
  let gamepadDirection = null;
  let keyMappings = loadKeyMappings();

  const byId = (id) => document.getElementById(id);

  async function request(path, options = {}) {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    if (csrfToken && options.method && options.method !== "GET") {
      headers["X-Ainekio-CSRF"] = csrfToken;
    }
    const response = await fetch(path, { credentials: "same-origin", ...options, headers });
    let payload = {};
    try {
      payload = await response.json();
    } catch (_error) {
      payload = { error: "invalid server response" };
    }
    if (response.status === 401 && path !== "/api/login") {
      window.location.assign("/login");
      throw new Error("authentication required");
    }
    if (!response.ok) {
      throw new Error(payload.error || `request failed (${response.status})`);
    }
    return payload;
  }

  function withRobot(payload = {}) {
    return selectedRobotId ? { ...payload, robot_id: selectedRobotId } : payload;
  }

  function showResult(message, error = false) {
    const output = byId("command-result");
    if (!output) return;
    output.textContent = message;
    output.classList.toggle("error", error);
  }

  async function command(path, payload = {}, label = "Command sent") {
    try {
      const result = await request(path, {
        method: "POST",
        body: JSON.stringify(withRobot(payload)),
      });
      showResult(result.seq ? `${label} (sequence ${result.seq})` : label);
      return result;
    } catch (error) {
      showResult(error.message, true);
      throw error;
    }
  }

  function setupLogin() {
    const form = byId("login-form");
    if (!form) return false;
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const errorOutput = byId("login-error");
      errorOutput.hidden = true;
      try {
        await request("/api/login", {
          method: "POST",
          body: JSON.stringify({ password: new FormData(form).get("password") }),
        });
        window.location.assign("/");
      } catch (error) {
        errorOutput.textContent = error.message === "rate_limited"
          ? "Too many attempts. Try again shortly."
          : "Authentication failed.";
        errorOutput.hidden = false;
      }
    });
    return true;
  }

  async function stopMotion(label = "Stop sent") {
    heldDirection = null;
    gamepadDirection = null;
    document.querySelectorAll("[data-held-direction]").forEach((button) => button.classList.remove("is-active"));
    try {
      await command("/api/stop", {}, label);
    } catch (_error) {
      return;
    }
  }

  async function beginHeldMotion(direction, element = null) {
    if (heldDirection === direction || heldRequestPending) return;
    if (heldDirection !== null) await stopMotion("Direction changed");
    heldDirection = direction;
    heldRequestPending = true;
    if (element) element.classList.add("is-active");
    try {
      await command("/api/intent", { name: "walk", params: { dir: direction, steps: 1 } }, "Movement sent");
    } catch (_error) {
      heldDirection = null;
      if (element) element.classList.remove("is-active");
    } finally {
      heldRequestPending = false;
    }
  }

  function setupMotionControls() {
    document.querySelectorAll("[data-intent]").forEach((button) => {
      button.addEventListener("click", () => command("/api/intent", { name: button.dataset.intent }, `${button.textContent.trim()} sent`));
    });
    document.querySelectorAll("[data-held-direction]").forEach((button) => {
      button.addEventListener("pointerdown", (event) => {
        event.preventDefault();
        button.setPointerCapture(event.pointerId);
        beginHeldMotion(button.dataset.heldDirection, button);
      });
      const release = (event) => {
        event.preventDefault();
        if (heldDirection === button.dataset.heldDirection) stopMotion("Movement released");
      };
      button.addEventListener("pointerup", release);
      button.addEventListener("pointercancel", release);
      button.addEventListener("lostpointercapture", release);
    });
    byId("stop-button").addEventListener("click", () => stopMotion("Emergency stop sent"));

    window.addEventListener("keydown", (event) => {
      const direction = directionForKey(event.code);
      if (event.repeat || !direction || /INPUT|SELECT|TEXTAREA/.test(event.target.tagName)) return;
      event.preventDefault();
      beginHeldMotion(direction);
    });
    window.addEventListener("keyup", (event) => {
      const direction = directionForKey(event.code);
      if (direction && heldDirection === direction) {
        event.preventDefault();
        stopMotion("Movement released");
      }
      if (event.code === "Space" && !/INPUT|SELECT|TEXTAREA/.test(event.target.tagName)) {
        event.preventDefault();
        stopMotion("Emergency stop sent");
      }
    });
    window.addEventListener("blur", () => { if (heldDirection !== null) stopMotion("Window lost focus"); });
    window.addEventListener("pagehide", releaseOnPageLoss);
    window.addEventListener("gamepaddisconnected", () => { if (gamepadDirection !== null) stopMotion("Controller disconnected"); });
    window.requestAnimationFrame(pollGamepad);
  }

  function releaseOnPageLoss() {
    if (heldDirection === null || !csrfToken) return;
    fetch("/api/stop", {
      method: "POST",
      credentials: "same-origin",
      keepalive: true,
      headers: { "Content-Type": "application/json", "X-Ainekio-CSRF": csrfToken },
      body: JSON.stringify(withRobot()),
    }).catch(() => {});
  }

  function pollGamepad() {
    const gamepad = Array.from(navigator.getGamepads ? navigator.getGamepads() : []).find(Boolean);
    let direction = null;
    if (gamepad) {
      const horizontal = gamepad.axes[0] || 0;
      const vertical = gamepad.axes[1] || 0;
      if (Math.abs(vertical) > 0.55 && Math.abs(vertical) >= Math.abs(horizontal)) direction = vertical < 0 ? "fwd" : "back";
      else if (Math.abs(horizontal) > 0.55) direction = horizontal < 0 ? "turn_l" : "turn_r";
      if (gamepad.buttons[1] && gamepad.buttons[1].pressed) direction = null;
    }
    if (direction !== gamepadDirection) {
      if (gamepadDirection !== null) stopMotion("Controller neutral");
      gamepadDirection = direction;
      if (direction !== null) beginHeldMotion(direction);
    }
    window.requestAnimationFrame(pollGamepad);
  }

  function setupForms() {
    document.querySelectorAll("[data-profile]").forEach((button) => button.addEventListener("click", () => command("/api/profile", { name: button.dataset.profile }, "Profile applied")));
    document.querySelectorAll("[data-emote]").forEach((button) => button.addEventListener("click", () => command("/api/intent", { name: "emote", params: { asset: button.dataset.emote } }, `${button.textContent.trim()} sent`)));
    document.querySelectorAll("[data-state]").forEach((button) => button.addEventListener("click", () => command("/api/state", { name: button.dataset.state, ...(button.dataset.state === "sleep" ? { sleep_s: 60 } : {}) }, "State applied")));
    document.querySelectorAll("[data-calibration-mode]").forEach((button) => button.addEventListener("click", () => command("/api/calibration/mode", { mode: button.dataset.calibrationMode }, "Calibration mode changed")));

    byId("asset-intent-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const submitter = event.submitter;
      const asset = new FormData(event.currentTarget).get("asset");
      const name = submitter.value;
      command("/api/intent", { name, params: name === "face" ? { expr: asset } : { asset } }, `${name} sent`);
    });
    byId("camera-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const values = new FormData(form);
      command("/api/camera", { on: form.elements.on.checked, fps: Number(values.get("fps")), res: values.get("res") }, "Camera setting applied");
    });
    byId("microphone-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const values = new FormData(form);
      command("/api/microphone", { on: form.elements.on.checked, gate: values.get("gate") }, "Microphone setting applied");
    });
    byId("snapshot-button").addEventListener("click", () => command("/api/snap", {}, "Snapshot requested"));
    byId("speaker-test-button").addEventListener("click", () => command("/api/speaker-test", {}, "Speaker test sent"));
    byId("servo-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const values = new FormData(event.currentTarget);
      command("/api/calibration/servo", { id: Number(values.get("id")), deg: Number(values.get("deg")), ms: Number(values.get("ms")) }, "Joint target sent");
    });
    byId("limits-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const values = new FormData(form);
      command("/api/calibration/limits", { id: Number(values.get("id")), min: Number(values.get("min")), center: Number(values.get("center")), max: Number(values.get("max")), invert: form.elements.invert.checked }, "Joint limits staged");
    });
    byId("calibration-save-button").addEventListener("click", () => command("/api/calibration/save", {}, "Calibration saved"));
    byId("calibration-neutral-button").addEventListener("click", () => command("/api/calibration/neutral", {}, "Neutral targets sent"));
    byId("calibration-detach-button").addEventListener("click", () => command("/api/calibration/detach", {}, "Outputs detached"));
    const mappingForm = byId("controller-mapping-form");
    Object.entries(keyMappings).forEach(([name, code]) => { mappingForm.elements[name].value = code; });
    mappingForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const values = new FormData(event.currentTarget);
      keyMappings = Object.fromEntries(["fwd", "back", "turn_l", "turn_r"].map((name) => [name, String(values.get(name))]));
      localStorage.setItem("ainekio-controller-mappings", JSON.stringify(keyMappings));
      showResult("Controller mappings saved");
    });
  }

  function setupSecurity() {
    byId("logout-button").addEventListener("click", async () => {
      try { await request("/api/logout", { method: "POST", body: "{}" }); } finally { window.location.assign("/login"); }
    });
    byId("token-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const robotId = new FormData(event.currentTarget).get("robot_id");
      const action = event.submitter.value;
      try {
        const result = await command(`/api/tokens/${action}`, { robot_id: robotId }, action === "generate" ? "Token generated" : "Token revoked");
        if (result.token) {
          byId("token-value").textContent = result.token;
          byId("token-result").hidden = false;
        }
        await refreshStatus();
      } catch (_error) {
        return;
      }
    });
    byId("token-dismiss-button").addEventListener("click", () => {
      byId("token-value").textContent = "";
      byId("token-result").hidden = true;
    });
  }

  function updateRobotSelect(robotIds) {
    const select = byId("robot-select");
    const previous = selectedRobotId;
    select.replaceChildren();
    if (robotIds.length === 0) {
      const option = new Option("No robot connected", "");
      select.add(option);
      selectedRobotId = null;
      return;
    }
    robotIds.forEach((robotId) => select.add(new Option(robotId, robotId)));
    selectedRobotId = robotIds.includes(previous) ? previous : robotIds[0];
    select.value = selectedRobotId;
  }

  function text(id, value) { byId(id).textContent = value; }

  function renderStatus(payload) {
    const robots = payload.robots || {};
    const robotIds = Object.keys(robots).sort();
    updateRobotSelect(robotIds);
    const entry = selectedRobotId ? robots[selectedRobotId] : null;
    const status = entry && entry.status;
    document.querySelectorAll("[data-joint-select]").forEach((select) => {
      if (select.options.length !== 0) return;
      (payload.joint_contract && payload.joint_contract.joints || []).forEach((joint) => {
        select.add(new Option(`${joint.id}: ${joint.label}`, joint.id));
      });
    });
    const connection = byId("connection-state");
    connection.textContent = entry ? "Online" : "Offline";
    connection.classList.toggle("online", Boolean(entry));
    connection.classList.toggle("offline", !entry);
    const state = status ? status.state : "unknown";
    text("body-state", state);
    byId("body-state").className = `state-chip ${state}`;
    text("status-battery", status ? `${Number(status.vbat).toFixed(2)} V` : "--");
    text("status-rssi", status ? `${status.rssi} dBm` : "--");
    text("status-heap", status ? `${Math.round(status.heap / 1024)} KiB` : "--");
    text("status-uptime", status ? formatDuration(status.uptime) : "--");
    text("status-sd", status ? (status.sd ? "Mounted" : "Unavailable") : "--");
    text("status-session", entry ? `${entry.epoch} / ${entry.next_sequence}` : "--");
    text("status-heartbeat", entry ? `${entry.heartbeat_age_ms} ms` : "--");
    const caps = payload.effective_caps;
    text("status-caps", caps ? `${payload.profile}: ${caps.camera_max_fps} fps` : "--");
    text("status-camera-drops", status ? status.cam_drops : "--");
    text("status-audio-faults", status ? `${status.mic_drops} / ${status.spk_underruns}` : "--");
    text("status-lifecycle", entry ? `${entry.pending} pending / ${entry.last_terminal ? entry.last_terminal.t : "none"}` : "--");
    const lastCommand = entry && entry.last_command;
    text("status-command", lastCommand ? `${lastCommand.t}${lastCommand.name ? `:${lastCommand.name}` : ""} #${lastCommand.seq}` : "--");
    text("status-face", status && status.face ? status.face : "--");
    byId("microphone-level").value = entry ? entry.microphone_level : 0;
    text("sd-state", status && status.sd ? "Mounted" : "Unavailable");
    byId("sd-state").className = `state-chip ${status && status.sd ? "active" : ""}`;

    const tokenList = byId("token-robot-list");
    tokenList.replaceChildren(...(payload.token_robot_ids || []).map((id) => {
      const item = document.createElement("span");
      item.className = "tag";
      item.textContent = id;
      return item;
    }));
    const auditBody = byId("audit-body");
    const rows = (payload.audit || []).slice(-50).reverse().map((entryItem) => {
      const row = document.createElement("tr");
      [new Date(entryItem.timestamp * 1000).toLocaleTimeString(), entryItem.event, entryItem.robot_id || "--"].forEach((value) => {
        const cell = document.createElement("td");
        cell.textContent = value;
        row.appendChild(cell);
      });
      return row;
    });
    auditBody.replaceChildren(...rows);
  }

  function formatDuration(seconds) {
    const total = Math.max(0, Number(seconds) || 0);
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const remainder = Math.floor(total % 60);
    return hours ? `${hours}h ${minutes}m` : `${minutes}m ${remainder}s`;
  }

  function loadKeyMappings() {
    const defaults = { fwd: "KeyW", back: "KeyS", turn_l: "KeyA", turn_r: "KeyD" };
    try {
      const stored = JSON.parse(localStorage.getItem("ainekio-controller-mappings"));
      return stored && typeof stored === "object" ? { ...defaults, ...stored } : defaults;
    } catch (_error) {
      return defaults;
    }
  }

  function directionForKey(code) {
    const fixed = { ArrowUp: "fwd", ArrowDown: "back", ArrowLeft: "turn_l", ArrowRight: "turn_r" };
    if (fixed[code]) return fixed[code];
    return Object.keys(keyMappings).find((direction) => keyMappings[direction] === code) || null;
  }

  async function refreshStatus() {
    try {
      renderStatus(await request("/api/status"));
    } catch (error) {
      showResult(error.message, true);
    }
  }

  async function setupDashboard() {
    const session = await request("/api/session");
    csrfToken = session.csrf;
    byId("robot-select").addEventListener("change", (event) => { selectedRobotId = event.target.value || null; refreshStatus(); });
    setupMotionControls();
    setupForms();
    setupSecurity();
    await refreshStatus();
    statusTimer = window.setInterval(refreshStatus, 1000);
  }

  if (!setupLogin()) {
    setupDashboard().catch((error) => showResult(error.message, true));
  }

  window.addEventListener("beforeunload", () => { if (statusTimer !== null) window.clearInterval(statusTimer); });
})();

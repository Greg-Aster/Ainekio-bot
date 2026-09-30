(function () {
  "use strict";

  const HELD_MOTION_STEPS = 10;

  let robotSettings = null;
  let robotSettingsSession = null;
  let robotSettingsBusy = false;
  let csrfToken = null;
  let selectedRobotId = null;
  let preferredRobotId = readLocal("ainekio-selected-robot", null);
  let statusRequest = null;
  let statusGeneration = 0;
  let reportedTerminal = null;
  let availableBodyCommands = [];
  let variableWalking = false;
  let directionalWalking = false;
  let runningSupported = false;
  let crabSupported = false;
  let motionSpeedSupported = false;
  let motionSpeedSession = null;
  let motionSpeedGeneration = 0;
  let motionSpeedData = null;
  let motionSpeedBusy = false;
  let motionSpeedEdited = false;
  let activeWalkProfile = null;
  let calibrationEntry = null;
  let calibrationData = null;
  let calibrationSession = null;
  let calibrationGeneration = 0;
  let calibrationWorkspace = null;
  let calibrationWorkspaceRobot = null;
  let calibrationSliderTimer = null;
  let calibrationSliderView = null;
  let calibrationLoading = false;
  let calibrationAttempted = false;
  let calibrationEdited = false;
  let calibrationReadAt = null;
  let storageData = null;
  let storageLoading = false;
  let storageAttempted = false;
  const bodyJointNames = ["Rear left shoulder", "Rear left carrier", "Rear left crank",
    "Rear right shoulder", "Rear right carrier", "Rear right crank", "Front left shoulder",
    "Front left carrier", "Front left crank", "Front right shoulder", "Front right carrier", "Front right crank"];
  const bodyJointParts = [
    "Shoulder: Part_002 moves the whole Part_003 leg carrier inward/outward.",
    "Carrier: Part_006 drives the Part_023 main arm.",
    "Crank: Part_005 drives the short Part_009 arm."
  ];

  const bodyCalibrationFields = ["channel", "center", "home_deg", "us_per_degree"];
  const bodyCalibrationEnabled = () => Boolean(calibrationEntry && calibrationEntry.model === "v2-12servo" &&
    (calibrationEntry.features || []).includes("body_calibration_v2"));

  let activeWalkSequence = null;
  let walkStatus = null;
  let lastWalkRequestSequence = null;
  let walkRequestPending = false;
  let walkRequest = null;
  let walkGeneration = 0;
  let walkApplyPending = false;
  let walkFinishPending = false;
  const directionCommands = { fwd: "walk", back: "backward", turn_l: "left", turn_r: "right", side_l: "crab", side_r: "crab_right" };

  function bodyCommandAvailable(name) {
    return availableBodyCommands === null || availableBodyCommands.includes(name);
  }
  let heldDirection = null;
  let heldRequestPending = false;
  let heldRequest = null;
  let statusTimer = null;
  let gamepadDirection = null;
  let gamepadSampling = false;
  let gamepadTimer = null;
  let cameraViewActive = false;
  let cameraRequestController = null;
  let cameraFrameCounter = null;
  let cameraFrameRobotId = null;
  let cameraObjectUrl = null;
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

  function resetCameraView(message = "Waiting for camera frames. Turn on the camera below if needed.") {
    cameraFrameCounter = null;
    cameraFrameRobotId = null;
    if (cameraRequestController) cameraRequestController.abort();
    const image = byId("camera-view");
    const output = byId("camera-view-message");
    if (!image || !output) return;
    image.hidden = true;
    output.textContent = message;
    output.hidden = false;
    if (cameraObjectUrl) URL.revokeObjectURL(cameraObjectUrl);
    cameraObjectUrl = null;
  }

  function delay(milliseconds) {
    return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
  }

  function setupPrimaryView() {
    if (document.body.dataset.dashboardPrimary !== "simulator") return;
    const frame = byId("simulator-frame");
    frame.src = frame.dataset.src;
  }

  async function runCameraView() {
    if (document.body.dataset.dashboardPrimary !== "camera" || cameraViewActive) return;
    cameraViewActive = true;
    while (cameraViewActive) {
      const robotId = selectedRobotId;
      if (!robotId) {
        resetCameraView("Waiting for a physical robot to connect.");
        await delay(500);
        continue;
      }
      if (cameraFrameRobotId !== robotId) {
        resetCameraView();
        cameraFrameRobotId = robotId;
      }
      const query = new URLSearchParams({ robot_id: robotId });
      if (cameraFrameCounter !== null) query.set("after", String(cameraFrameCounter));
      const controller = new AbortController();
      cameraRequestController = controller;
      try {
        const response = await fetch(`/api/camera/frame?${query}`, {
          credentials: "same-origin",
          cache: "no-store",
          signal: controller.signal,
        });
        if (response.status === 401) {
          window.location.assign("/login");
          return;
        }
        if (response.status === 204) continue;
        if (!response.ok) throw new Error(`camera request failed (${response.status})`);
        if (robotId !== selectedRobotId) continue;
        const blob = await response.blob();
        const nextUrl = URL.createObjectURL(blob);
        const image = byId("camera-view");
        image.src = nextUrl;
        image.hidden = false;
        byId("camera-view-message").hidden = true;
        if (cameraObjectUrl) URL.revokeObjectURL(cameraObjectUrl);
        cameraObjectUrl = nextUrl;
        cameraFrameCounter = response.headers.get("X-Ainekio-Camera-Counter");
      } catch (error) {
        if (error.name !== "AbortError") {
          if (!cameraObjectUrl) resetCameraView("Camera view is temporarily unavailable.");
          await delay(1000);
        }
      } finally {
        if (cameraRequestController === controller) cameraRequestController = null;
      }
    }
  }

  async function command(path, payload = {}, label = "Command sent", canReport = () => true) {
    cancelCalibrationSlider();
    try {
      const result = await request(path, {
        method: "POST",
        body: JSON.stringify(withRobot(payload)),
      });
      if (canReport(result)) showResult(result.seq ? `${label} (sequence ${result.seq})` : label);
      return result;
    } catch (error) {
      if (canReport()) showResult(error.message, true);
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

  async function stopMotion(label = "Stop sent", detach = false) {
    cancelCalibrationSlider();
    if (!detach && variableWalking && activeWalkSequence !== null && !heldRequestPending) {
      heldDirection = null; gamepadDirection = null;
      document.querySelectorAll("[data-held-direction]").forEach((button) => button.classList.remove("is-active"));
      await applyWalking(true); return;
    }
    if (detach) resetWalking();
    const robotId = selectedRobotId;
    const generation = walkGeneration;
    const pendingRequest = heldRequest || walkRequest;
    const endpoint = detach ? "/api/detach" : "/api/stop";
    heldDirection = null;
    gamepadDirection = null;
    document.querySelectorAll("[data-held-direction]").forEach((button) => button.classList.remove("is-active"));
    const immediateStop = command(endpoint, {}, label);
    if (pendingRequest) {
      await Promise.allSettled([pendingRequest, immediateStop]);
      if (heldDirection === null && robotId === selectedRobotId && generation === walkGeneration) {
        try { await command(endpoint, {}, `${label} (confirmed)`); } catch (_error) { return; }
      }
      return;
    }
    try {
      await immediateStop;
    } catch (_error) {
      return;
    }
  }

  async function beginHeldMotion(direction, element = null) {
    if (!bodyCommandAvailable(directionCommands[direction])) return;
    if (heldDirection === direction || heldRequestPending) return;
    if (directionalWalking && activeWalkSequence !== null) { await stopMotion("Finishing current movement"); return; }
    if (directionalWalking && byId("walk-gait").value === "crawl" && !bodyCommandAvailable("crawl")) return;
    const robotId = selectedRobotId;
    const generation = walkGeneration;
    if (heldDirection !== null) await stopMotion("Direction changed");
    if (robotId !== selectedRobotId || generation !== walkGeneration) return;
    const params = directionalWalking ? walkingParameters(0, direction) : direction === "fwd" ? walkingParameters(HELD_MOTION_STEPS) : { dir: direction, steps: HELD_MOTION_STEPS };
    const tracksSequence = variableWalking && (directionalWalking || direction === "fwd");
    heldDirection = direction;
    heldRequestPending = true;
    document.querySelector(".motion-pad").setAttribute("aria-busy", "true");
    if (element) element.classList.add("is-active");
    const requestPromise = command(
      "/api/intent",
      { name: "walk", params },
      "Movement sent",
      (result) => robotId === selectedRobotId && generation === walkGeneration &&
        (!result || !tracksSequence || !walkReplyEnded(result.seq)),
    );
    heldRequest = requestPromise;
    try {
      const result = await requestPromise;
      if (robotId === selectedRobotId && generation === walkGeneration && tracksSequence && heldDirection === direction) {
        if (walkReplyEnded(result.seq)) resetWalking();
        else {
          activeWalkSequence = lastWalkRequestSequence = result.seq;
          activeWalkProfile = { dir: direction, gait: params.gait || "walk" };
        }
      }
    } catch (_error) {
      if (robotId === selectedRobotId && generation === walkGeneration) {
        heldDirection = null;
        if (element) element.classList.remove("is-active");
      }
    } finally {
      if (heldRequest === requestPromise) {
        heldRequest = null;
        heldRequestPending = false;
        document.querySelector(".motion-pad").setAttribute("aria-busy", "false");
        renderWalkingControls();
      }
    }
  }

  function resetWalking() {
    walkGeneration += 1;
    heldDirection = null; gamepadDirection = null;
    heldRequest = null; heldRequestPending = false;
    walkRequest = null; walkRequestPending = false;
    document.querySelectorAll("[data-held-direction]").forEach((button) => button.classList.remove("is-active"));
    document.querySelector(".motion-pad")?.setAttribute("aria-busy", "false");
    activeWalkSequence = null;
    activeWalkProfile = null;
    walkStatus = null;
    lastWalkRequestSequence = null;
    walkApplyPending = false;
    walkFinishPending = false;
    renderWalkingControls();
  }

  function walkReplyEnded(sequence) {
    const terminal = walkStatus?.last_terminal;
    if (terminal?.seq === sequence && ["nak", "done", "cancelled"].includes(terminal.t)) {
      if (terminal.t === "nak") showResult(`Command ${terminal.seq} rejected: ${[terminal.code, terminal.msg].filter(Boolean).join(" — ")}`, true);
      return true;
    }
    // A snapshot taken after allocation can prove a start already finished,
    // even if another command has since replaced last_terminal.
    return Number.isInteger(walkStatus?.next_sequence) && walkStatus.next_sequence > sequence &&
      walkStatus.active_walk_sequence !== sequence;
  }

  function updateWalkingStatus(entry) {
    const sequence = entry && variableWalking && entry.connection_state !== "stale" ? entry.active_walk_sequence ?? null : null;
    const terminal = entry?.last_terminal;
    const rejected = terminal?.t === "nak" && terminal.seq === lastWalkRequestSequence;
    const ended = activeWalkSequence !== null && (
      terminal?.seq === activeWalkSequence && ["nak", "done", "cancelled"].includes(terminal.t) ||
      Number.isInteger(entry?.next_sequence) && entry.next_sequence > activeWalkSequence && sequence !== activeWalkSequence);
    if (rejected || ended || walkStatus && walkStatus.epoch !== entry?.epoch) resetWalking();
    walkStatus = entry;
    if (!walkRequestPending && !heldRequestPending) {
      activeWalkSequence = rejected ? null : sequence;
      activeWalkProfile = activeWalkSequence !== null && entry?.active_walk ?
        {dir: entry.active_walk.dir, gait: entry.active_walk.gait || "walk"} : null;
    }
    if (activeWalkProfile && directionalWalking) {
      byId("walk-direction").value = activeWalkProfile.dir;
      byId("walk-gait").value = activeWalkProfile.gait;
    }
    renderWalkingControls();
  }

  function renderWalkingControls() {
    const pending = walkRequestPending || heldRequestPending;
    for (const id of ["walk-direction", "walk-gait", "walk-continuous"]) byId(id).disabled = activeWalkSequence !== null || pending;
    byId("walk-apply").textContent = activeWalkSequence === null ? "Start" : "Apply to current movement";
    byId("walk-finish").disabled = activeWalkSequence === null;
    byId("walk-cycles-field").hidden = directionalWalking && byId("walk-continuous").checked;
    byId("walk-cycles").disabled = activeWalkSequence !== null || (directionalWalking && byId("walk-continuous").checked);
  }

  function updateSpeedRange() {
    const gait = byId("walk-gait").value;
    const extended = runningSupported && !["crawl", "crab"].includes(gait);
    for (const option of byId("walk-direction").options) {
      if (option.value.startsWith("side_")) option.disabled = gait !== "crab" || !crabSupported;
    }
    if (gait !== "crab" && byId("walk-direction").value.startsWith("side_")) byId("walk-direction").value = "fwd";
    const slider = byId("walk-speed");
    slider.max = extended ? "200" : "100";
    if (Number(slider.value) > Number(slider.max)) slider.value = slider.max;
    byId("walk-speed-value").textContent = `${slider.value}%`;
    byId("walk-run-hint").hidden = !extended || gait === "run";
  }

  function walkingParameters(steps, direction = byId("walk-direction").value) {
    const params = { dir: directionalWalking ? direction : "fwd", steps };
    if (directionalWalking) params.gait = byId("walk-gait").value;
    if (!variableWalking) return params;
    if (byId("walk-mode").value === "auto") params.speed = Number(byId("walk-speed").value);
    else { params.stride = Number(byId("walk-stride").value); params.rate = Number(byId("walk-rate").value); }
    return params;
  }

  async function applyWalking(finish = false, updateOnly = false) {
    if (!variableWalking) return;
    if (updateOnly && activeWalkSequence === null) return;
    const profile = activeWalkProfile || { dir: directionalWalking ? byId("walk-direction").value : "fwd", gait: byId("walk-gait").value };
    if (!bodyCommandAvailable(directionCommands[profile.dir]) || (directionalWalking && profile.gait === "crawl" && !bodyCommandAvailable("crawl"))) return;
    if (profile.gait === "crab" && !crabSupported) return;
    if (walkRequestPending) { walkApplyPending = true; walkFinishPending ||= finish; return; }
    if (finish && activeWalkSequence === null) return;
    if (!finish && !byId("walk-controls").reportValidity()) return;
    const robotId = selectedRobotId;
    const generation = walkGeneration;
    const steps = directionalWalking && byId("walk-continuous").checked ? 0 : Number(byId("walk-cycles").value);
    const params = finish ? { dir: profile.dir, steps: 1, speed: 0 } : walkingParameters(steps, profile.dir);
    if (directionalWalking) params.gait = profile.gait;
    if (activeWalkSequence !== null) params.update = activeWalkSequence;
    walkRequestPending = true;
    const requestPromise = command("/api/intent", { name: "walk", params }, finish ? "Finishing walk" : "Walking settings sent",
      (result) => robotId === selectedRobotId && generation === walkGeneration &&
        (!result || params.update !== undefined || !walkReplyEnded(result.seq)));
    walkRequest = requestPromise;
    try {
      const result = await requestPromise;
      if (generation === walkGeneration && selectedRobotId === robotId) {
        const rejected = walkStatus?.last_terminal?.seq === result.seq && walkStatus.last_terminal.t === "nak";
        if ((params.update === undefined || rejected) && walkReplyEnded(result.seq)) {
          resetWalking();
        } else {
          lastWalkRequestSequence = result.seq;
          if (params.update === undefined) {
            activeWalkSequence = result.seq; activeWalkProfile = { dir: params.dir, gait: params.gait || "walk" };
          }
        }
      }
    } catch (_error) {
      // command() keeps the real rejection visible; discard stale sequence and
      // queued changes so the next deliberate Start creates a new command.
      if (generation === walkGeneration && selectedRobotId === robotId) {
        statusGeneration++;
        resetWalking();
      }
    }
    finally {
      if (walkRequest !== requestPromise) return;
      walkRequestPending = false;
      walkRequest = null;
      renderWalkingControls();
      if (walkApplyPending) {
        const finishNext = walkFinishPending; walkApplyPending = false; walkFinishPending = false;
        if (generation === walkGeneration && robotId === selectedRobotId) applyWalking(finishNext, true);
      }
    }
  }

  function renderMotionSpeed() {
    byId("motion-speed").disabled = !motionSpeedSupported || !motionSpeedData || motionSpeedBusy;
    byId("motion-speed-read").disabled = !motionSpeedSupported || motionSpeedBusy;
    byId("motion-speed-save").disabled = !motionSpeedSupported || !motionSpeedData || motionSpeedBusy ||
      (!motionSpeedEdited && motionSpeedData.saved);
  }

  async function operateMotionSpeed(op) {
    if (!motionSpeedSupported || motionSpeedBusy) return;
    if (op === "save" && !byId("motion-speed").reportValidity()) return;
    const generation = motionSpeedGeneration;
    const robotId = selectedRobotId;
    const current = () => generation === motionSpeedGeneration && robotId === selectedRobotId;
    motionSpeedBusy = true;
    renderMotionSpeed();
    text("motion-speed-status", op === "save" ? "Saving motion speed on robot…" : "Reading motion speed from robot…");
    try {
      const response = await command("/api/motion-speed", {op, robot_id: robotId,
        ...(op === "save" ? {rate: Number(byId("motion-speed").value)} : {})},
        op === "save" ? "Motion speed saved on robot" : "Motion speed read from robot", current);
      if (!current()) return;
      const state = response.motion_speed;
      if (!state || state.seq !== response.seq || !Number.isFinite(state.rate) ||
          state.rate <= 0 || typeof state.saved !== "boolean")
        throw new Error("Invalid motion speed readback; read from robot again.");
      motionSpeedData = state;
      motionSpeedEdited = false;
      byId("motion-speed").value = String(state.rate);
      text("motion-speed-status", `${state.saved ? "Saved on robot" : "Robot default"}: ${state.rate}×. Adjust, try a named motion, then save to keep it after restart.`);
    } catch (error) {
      if (current()) text("motion-speed-status", error.message);
    } finally {
      if (current()) { motionSpeedBusy = false; renderMotionSpeed(); }
    }
  }

  function updateMotionSpeed(entry) {
    const p4 = entry?.model === "v2-12servo";
    const supported = Boolean(p4 && entry.connection_state !== "stale" && entry.connected !== false &&
      (entry.features || []).includes("motion_speed_v1"));
    const session = entry ? `${selectedRobotId}:${entry.epoch}:${supported}` : null;
    byId("motion-speed-controls").hidden = !p4;
    motionSpeedSupported = supported;
    if (session !== motionSpeedSession) {
      motionSpeedSession = session;
      motionSpeedGeneration++;
      motionSpeedData = null;
      motionSpeedBusy = motionSpeedEdited = false;
      byId("motion-speed").value = "2";
      if (supported) operateMotionSpeed("get");
      else text("motion-speed-status", p4 ? "A firmware update is needed to enable Motion speed." : "Connect a robot to read its motion speed.");
    }
    renderMotionSpeed();
  }

  function sendNamedMotion(name, asset, label) {
    const params = asset ? {asset} : {};
    const ongoing = asset === "run" || (crabSupported && asset?.startsWith("crab"));
    if (motionSpeedSupported && !ongoing && ["sit", "stand", "emote"].includes(name)) {
      if (!motionSpeedData || motionSpeedBusy) { showResult("Read motion speed from robot before starting a motion.", true); return; }
      if (!byId("motion-speed").reportValidity()) return;
      params.playback_rate = Number(byId("motion-speed").value);
    }
    return command("/api/intent", {name, params}, label);
  }

  function setupMotionControls() {
    byId("motion-speed-read").addEventListener("click", () => operateMotionSpeed("get"));
    byId("motion-speed-save").addEventListener("click", () => operateMotionSpeed("save"));
    byId("motion-speed").addEventListener("input", () => {
      motionSpeedEdited = Number(byId("motion-speed").value) !== motionSpeedData?.rate;
      text("motion-speed-status", motionSpeedEdited ? "Unsaved speed — try a named motion, then Save on robot." :
        `${motionSpeedData?.saved ? "Saved on robot" : "Robot default"}: ${motionSpeedData?.rate}×.`);
      renderMotionSpeed();
    });
    byId("walk-continuous").addEventListener("change", () => {
      byId("walk-cycles-field").hidden = directionalWalking && byId("walk-continuous").checked;
      byId("walk-cycles").disabled = activeWalkSequence !== null || (directionalWalking && byId("walk-continuous").checked);
    });
    byId("walk-controls").addEventListener("submit", (event) => { event.preventDefault(); applyWalking(); });
    byId("walk-finish").addEventListener("click", () => applyWalking(true));
    byId("walk-mode").addEventListener("change", () => {
      const manual = byId("walk-mode").value === "manual";
      byId("walk-advanced").hidden = !manual; byId("walk-speed-field").hidden = manual;
      byId("walk-stride").disabled = !manual; byId("walk-rate").disabled = !manual;
    });
    byId("walk-gait").addEventListener("change", updateSpeedRange);
    byId("walk-speed").addEventListener("input", updateSpeedRange);
    byId("walk-speed").addEventListener("change", () => applyWalking(false, true));
    document.querySelectorAll("[data-intent]").forEach((button) => {
      button.addEventListener("click", () => sendNamedMotion(button.dataset.intent, null, `${button.textContent.trim()} sent`));
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
    byId("stop-button").addEventListener("click", () => stopMotion("Emergency stop sent", true));

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
        stopMotion("Emergency stop sent", true);
      }
    });
    window.addEventListener("blur", () => {
      cancelCalibrationSlider();
      if (heldDirection !== null || gamepadDirection !== null || heldRequestPending) {
        stopMotion("Window lost focus");
      }
    });
    window.addEventListener("pagehide", releaseOnPageLoss);
    window.addEventListener("gamepadconnected", startGamepadSampling);
    window.addEventListener("gamepaddisconnected", () => {
      gamepadSampling = false;
      if (gamepadTimer !== null) window.clearTimeout(gamepadTimer);
      gamepadTimer = null;
      if (gamepadDirection !== null) stopMotion("Controller disconnected");
    });
    if (Array.from(navigator.getGamepads ? navigator.getGamepads() : []).some(Boolean)) {
      startGamepadSampling();
    }
  }

  function releaseOnPageLoss() {
    cancelCalibrationSlider();
    if (heldDirection === null || !csrfToken) return;
    fetch("/api/stop", {
      method: "POST",
      credentials: "same-origin",
      keepalive: true,
      headers: { "Content-Type": "application/json", "X-Ainekio-CSRF": csrfToken },
      body: JSON.stringify(withRobot()),
    }).catch(() => {});
  }

  function startGamepadSampling() {
    if (gamepadSampling) return;
    gamepadSampling = true;
    pollGamepad();
  }

  function pollGamepad() {
    const gamepad = Array.from(navigator.getGamepads ? navigator.getGamepads() : []).find(Boolean);
    if (!gamepad) {
      gamepadSampling = false;
      gamepadTimer = null;
      if (gamepadDirection !== null) stopMotion("Controller disconnected");
      return;
    }
    let direction = null;
    const horizontal = gamepad.axes[0] || 0;
    const vertical = gamepad.axes[1] || 0;
    if (Math.abs(vertical) > 0.55 && Math.abs(vertical) >= Math.abs(horizontal)) direction = vertical < 0 ? "fwd" : "back";
    else if (Math.abs(horizontal) > 0.55) direction = horizontal < 0 ? "turn_l" : "turn_r";
    if (gamepad.buttons[1] && gamepad.buttons[1].pressed) direction = null;
    if (direction !== gamepadDirection) {
      if (gamepadDirection !== null) stopMotion("Controller neutral");
      gamepadDirection = direction;
      if (direction !== null) beginHeldMotion(direction);
    }
    if (gamepadSampling) gamepadTimer = window.setTimeout(pollGamepad, 50);
  }

  function showCalibrationResult(message, error = false) {
    const output = byId("calibration-feedback");
    output.textContent = message;
    output.classList.toggle("error", error);
    output.hidden = !message;
    if (message) showResult(message, error);
  }

  function renderCalibrationReadback() {
    const p4 = bodyCalibrationEnabled();
    const joint = selectedCalibrationJoint();
    byId("calibration-settings").hidden = !p4;
    byId("calibration-save-help").hidden = !p4;
    text("calibration-save-button", p4 ? "Apply & save to robot" : "Save calibration");
    text("calibration-read-button", calibrationLoading ? "Waiting for robot…" : "Read settings from robot");
    const id = Number(byId("servo-form").elements.id.value);
    text("calibration-joint-help", p4 ? `${bodyJointParts[id % 3]} Front is the face end; left/right are the robot’s own sides.` : "");
    const values = {
      channel: joint ? (joint.channel < 0 ? "Unassigned" : `Output ${joint.channel}`) : "—",
      home: joint ? `${joint.home_us} µs` : "—",
      angle: Number.isFinite(joint?.home_cd) ? `${(joint.home_cd / 100).toFixed(2)}°` : "—",
      invert: joint ? (joint.invert ? "On" : "Off") : "—",
      scale: Number.isFinite(joint?.us_per_degree) ? `${joint.us_per_degree.toFixed(4)} µs/°` : "—",
      pulse: joint ? (joint.pulse_us ? `${joint.pulse_us} µs` : "Outputs off / no command") : "—",
    };
    for (const [name, value] of Object.entries(values)) text(`calibration-body-${name}`, value);
    const saved = calibrationData?.dirty ? "Applied on robot, not saved after restart" :
      calibrationData?.saved ? "Saved on robot" : "Defaults on robot; not saved";
    const stamp = calibrationReadAt ? ` Last confirmed at ${calibrationReadAt.toLocaleTimeString()}.` : "";
    text("calibration-readback-status", !joint ? "No confirmed settings. Read settings from robot." :
      `${saved}.${stamp}${calibrationEntry?.connection_state === "stale" ? " Robot offline; these are the last reported values." : ""}`);
    const changed = joint && !calibrationDraftMatches(joint, calibrationDraft());
    text("calibration-draft-status", !joint ? "Read the robot’s settings before editing." : changed ?
      "Local edits — not applied to the robot. Reading settings keeps these edits in this column." : "Fields match the robot’s reported settings.");
    byId("calibration-draft-status").classList.toggle("has-edits", Boolean(changed));
    const recommended = Number.isFinite(joint?.recommended_home_cd) && Number.isFinite(calibrationData?.recommended_reference_us);
    text("calibration-reference-help", recommended ?
      `Engraved assembly reference: ${calibrationData.recommended_reference_us} µs at ${(joint.recommended_home_cd / 100).toFixed(2)}° model angle. This marks a physical pose, not the midpoint of servo travel. Home pulse and model angle must describe the installed horn position.` : "");
  }

  function selectedCalibrationJoint() {
    const id = Number(byId("servo-form").elements.id.value);
    return calibrationData && calibrationData.joints.find((joint) => joint.id === id);
  }

  function readLocal(key, fallback) {
    try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch (_error) { return fallback; }
  }

  function writeLocal(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (_error) { /* Keep the in-memory draft. */ }
  }

  function calibrationWorkspaceForRobot() {
    if (calibrationWorkspaceRobot !== selectedRobotId) {
      const saved = readLocal(`ainekio-calibration-v1:${selectedRobotId}`, {});
      calibrationWorkspace = {joint: Number.isInteger(saved?.joint) && saved.joint >= 0 && saved.joint < 12 ? saved.joint : 6,
        resume: saved?.resume === true, joints: {}};
      for (let id = 0; id < 12; id++) {
        const stored = saved?.joints?.[id];
        if (!stored || typeof stored !== "object") continue;
        const draft = {edited: stored.edited === true};
        if (typeof stored.pulse === "string") draft.pulse = stored.pulse;
        if (stored.fields && typeof stored.fields === "object") {
          draft.fields = Object.fromEntries(bodyCalibrationFields.filter((name) => typeof stored.fields[name] === "string")
            .map((name) => [name, stored.fields[name]]));
          draft.fields.invert = stored.fields.invert === true;
        }
        calibrationWorkspace.joints[id] = draft;
      }
      calibrationWorkspaceRobot = selectedRobotId;
      persistCalibrationWorkspace();
    }
    return calibrationWorkspace;
  }

  function persistCalibrationWorkspace() {
    writeLocal(`ainekio-calibration-v1:${calibrationWorkspaceRobot}`, calibrationWorkspace);
  }

  function calibrationDraft(id = Number(byId("servo-form").elements.id.value)) {
    const workspace = calibrationWorkspaceForRobot();
    if (!workspace.joints[id] || typeof workspace.joints[id] !== "object") workspace.joints[id] = {};
    return workspace.joints[id];
  }

  function calibrationDraftMatches(joint, draft) {
    if (!draft.fields) return true;
    const actual = {channel: joint.channel, center: joint.home_us,
      home_deg: joint.home_cd / 100, us_per_degree: joint.us_per_degree};
    return draft.fields.invert === joint.invert && Object.entries(actual).every(([name, value]) =>
      !Number.isFinite(value) || (draft.fields[name] !== "" && Number.isFinite(Number(draft.fields[name])) &&
        Math.abs(Number(draft.fields[name]) - value) <= Math.max(1e-6, Math.abs(value) * 1e-6)));
  }

  function rememberCalibrationSettings() {
    const form = byId("body-calibration-form");
    const draft = calibrationDraft();
    draft.fields = Object.fromEntries(bodyCalibrationFields
      .map((name) => [name, form.elements[name].value]));
    draft.fields.invert = form.elements.invert.checked;
    draft.edited = calibrationEdited = true;
    persistCalibrationWorkspace();
  }

  function rememberCalibrationPulse() {
    calibrationDraft().pulse = byId("servo-form").elements.deg.value;
    persistCalibrationWorkspace();
  }

  function cancelCalibrationSlider() {
    window.clearTimeout(calibrationSliderTimer);
    calibrationSliderTimer = null;
  }

  function renderCalibrationSlider(moving) {
    const p4 = bodyCalibrationEnabled();
    const panel = byId("calibration-slider-panel");
    const slider = byId("calibration-pulse-slider");
    panel.hidden = !p4;
    if (!p4) {
      slider.disabled = true;
      byId("calibration-use-body-values").disabled = true;
      return;
    }
    const joint = selectedCalibrationJoint();
    slider.disabled = !moving || calibrationLoading || !joint;
    byId("calibration-use-body-values").disabled = calibrationLoading || !joint;
    if (!joint) {
      text("calibration-calculated-angle", "Waiting for controller mapping; target retained locally.");
      return;
    }
    const bounds = calibrationPulseBounds();
    const input = byId("servo-form").elements.deg;
    const draft = calibrationDraft();
    // Start with the owner's observed pulse span; this is a view, not a servo limit.
    const candidates = [300, 2900, joint.home_us, joint.pulse_us, input.value, draft.fields?.center]
      .filter((value) => value !== "" && value !== undefined).map(Number).filter((value) => Number.isFinite(value) && value > 0);
    const key = `${selectedRobotId}:${joint.id}`;
    const previous = calibrationSliderView?.key === key ? calibrationSliderView : null;
    calibrationSliderView = {key, min: Math.max(bounds.min, Math.min(previous?.min ?? Infinity, ...candidates)),
      max: Math.min(bounds.max, Math.max(previous?.max ?? -Infinity, ...candidates))};
    slider.min = calibrationSliderView.min;
    slider.max = calibrationSliderView.max;
    if (Number.isFinite(input.valueAsNumber)) slider.value = input.value;
    const angle = joint.home_cd / 100 + (joint.invert ? -1 : 1) * (input.valueAsNumber - joint.home_us) / joint.us_per_degree;
    text("calibration-slider-value", `${input.value || "—"} µs target`);
    text("calibration-calculated-angle", Number.isFinite(angle) ?
      `Calculated model angle: ${angle.toFixed(2)}° from controller mapping; not measured.` : "Calculated angle unavailable until the controller supplies its mapping.");

  }

  function hasJointAngleMapping() {
    const joint = selectedCalibrationJoint();
    return Boolean(joint && Number.isFinite(joint.home_cd) && Number.isFinite(joint.us_per_degree));
  }

  function calibrationPulseBounds() {
    const min = calibrationData?.pulse_min_us;
    const max = calibrationData?.pulse_max_us;
    return Number.isInteger(min) && Number.isInteger(max) && min > 0 && min <= max && max <= 65535 ?
      {min, max} : {min: 1, max: 65535};
  }

  function fillCalibrationFields(force = false) {
    if (!bodyCalibrationEnabled()) return;
    const joint = selectedCalibrationJoint();
    if (!joint) return;
    const servo = byId("servo-form");
    const mapping = byId("body-calibration-form");
    const draft = calibrationDraft(joint.id);
    calibrationEdited = !calibrationDraftMatches(joint, draft);
    if (force || !servo.contains(document.activeElement)) servo.elements.deg.value = draft.pulse ?? (joint.pulse_us || joint.home_us);
    if (force || !mapping.contains(document.activeElement)) {
      mapping.elements.id.value = joint.id;
      mapping.elements.channel.value = joint.channel;
      mapping.elements.center.value = joint.home_us;
      mapping.elements.home_deg.value = Number.isFinite(joint.home_cd) ? joint.home_cd / 100 : "";
      mapping.elements.us_per_degree.value = joint.us_per_degree ?? "";
      mapping.elements.invert.checked = joint.invert;
      if (draft.fields) {
        for (const name of bodyCalibrationFields)
          if (typeof draft.fields[name] === "string") mapping.elements[name].value = draft.fields[name];
        mapping.elements.invert.checked = draft.fields.invert === true;
      }
    }
  }

  function calibrationFields() {
    const form = byId("body-calibration-form");
    rememberCalibrationSettings();
    if (!form.reportValidity()) return null;
    const values = new FormData(form);
    const fields = {id: Number(values.get("id")), channel: Number(values.get("channel")),
      home_us: Number(values.get("center")), invert: form.elements.invert.checked,
      ...(hasJointAngleMapping() ? {home_cd: Math.round(Number(values.get("home_deg")) * 100),
        us_per_degree: Number(values.get("us_per_degree"))} : {})};
    return fields;
  }

  async function calibrateBody(op, fields = {}, label = "Calibration confirmed by body") {
    cancelCalibrationSlider();
    if (!bodyCalibrationEnabled() || calibrationLoading) return false;
    if (op === "move") {
      const bounds = calibrationPulseBounds();
      if (!Number.isInteger(fields.pulse_us) || fields.pulse_us < bounds.min || fields.pulse_us > bounds.max) {
        showCalibrationResult(`Commanded pulse must be an integer from ${bounds.min} to ${bounds.max} µs.`, true);
        return false;
      }
    }
    const session = calibrationGeneration;
    const jointId = Number(byId("servo-form").elements.id.value);
    if (op === "move") {
      calibrationDraft(fields.id).pulse = String(fields.pulse_us);
      persistCalibrationWorkspace();
    }
    calibrationLoading = true;
    const operationLabel = {get: "Reading settings from robot…", set: "Applying this joint’s settings…", save: "Saving settings on robot…", home: "Moving to Home…", move: "Moving selected joint…"};
    showCalibrationResult(operationLabel[op] || "Waiting for robot…");
    renderCalibration();
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    try {
      const response = await request("/api/calibration/body", {
        method: "POST", body: JSON.stringify(withRobot({op, ...fields})), signal: controller.signal,
      });
      if (session !== calibrationGeneration || jointId !== Number(byId("servo-form").elements.id.value)) return false;
      if (!response.calibration || response.calibration.seq !== response.seq)
        throw new Error("Calibration reply did not confirm the requested operation. Read from the body before continuing.");
      if (op === "set") {
        const joint = response.calibration.joints.find((item) => item.id === fields.id);
        const confirmed = joint && Object.entries(fields).every(([key, value]) =>
          key === "us_per_degree" ? Math.abs(joint[key] - value) <= Math.max(1e-6, Math.abs(value) * 1e-6) : joint[key] === value);
        if (!confirmed) throw new Error("The body did not confirm the edited joint settings; calibration was not saved.");
        calibrationEdited = false;
        calibrationDraft(fields.id).edited = false;
      }
      if (op === "save" && (!response.calibration.saved || response.calibration.dirty))
        throw new Error("The body did not confirm saved calibration. Read from the body before continuing.");
      calibrationData = response.calibration;
      calibrationReadAt = new Date();
      if (op === "save") {
        delete calibrationDraft(jointId).fields;
        calibrationDraft(jointId).edited = false;
      }
      if (op === "home") {
        for (const joint of response.calibration.joints)
          if (fields.id === undefined || joint.id === fields.id) calibrationDraft(joint.id).pulse = String(joint.pulse_us || joint.home_us);
      }
      persistCalibrationWorkspace();
      fillCalibrationFields(true);
      const confirmed = op === "get" ? "Read complete. ‘On the robot’ shows the returned settings; local edits remain in ‘Edit selected joint’." :
        op === "set" ? "Settings applied temporarily. Save to keep them after restart. Outputs are off." :
        op === "save" ? "Settings saved on the robot and read back successfully. Outputs are off." : label;
      showCalibrationResult(confirmed);
      return true;
    } catch (error) {
      // A lost reply leaves the commanded position unknown until a fresh read.
      if (session === calibrationGeneration) {
        calibrationData = null;
        showCalibrationResult(error.name === "AbortError" ? "The robot did not reply within 10 seconds. Read settings again before continuing." : error.message, true);
      }
      return false;
    } finally {
      window.clearTimeout(timeout);
      if (session === calibrationGeneration) {
        calibrationLoading = false;
        renderCalibration();
      }
    }
  }

  async function saveBodyCalibration() {
    const fields = calibrationFields();
    if (!fields) return;
    const session = calibrationGeneration;
    if (await calibrateBody("set", fields, "Joint settings staged on body") && session === calibrationGeneration)
      await calibrateBody("save", {}, "Calibration saved and read back from body");
  }

  function renderCalibration() {
    const p4 = bodyCalibrationEnabled();
    const legacy = calibrationEntry && (!calibrationEntry.model || calibrationEntry.model === "v1-8servo");
    const online = calibrationEntry && calibrationEntry.connection_state !== "stale";
    const editing = online && (legacy || (p4 && calibrationEntry.mode === "calibrate" && calibrationData));
    const moving = editing && (!p4 || calibrationData.ready);
    document.querySelectorAll("#servo-form input, #servo-form button, #calibration-neutral-button, #calibration-save-button, [data-calibration-trim], #calibration-joint-home-button, #calibration-use-position-button")
      .forEach((control) => { control.disabled = !editing || calibrationLoading; });
    document.querySelectorAll("#limits-form input, #limits-form button")
      .forEach((control) => { control.disabled = !legacy || !editing || calibrationLoading; });
    document.querySelectorAll("#body-calibration-form input, #body-calibration-form button")
      .forEach((control) => { control.disabled = !p4 || !editing || calibrationLoading; });
    document.querySelectorAll("#servo-form button, #calibration-neutral-button, [data-calibration-trim], #calibration-joint-home-button")
      .forEach((control) => { control.disabled = !moving || calibrationLoading; });
    document.querySelectorAll("[data-calibration-mode]").forEach((button) => {
      button.disabled = !online || !(p4 || legacy) || calibrationLoading;
      if (button.dataset.calibrationMode === "calibrate") button.textContent = p4 && calibrationWorkspaceForRobot().resume && calibrationEntry.mode !== "calibrate" ? "Resume calibration" : "Enable";
    });
    byId("calibration-read-button").disabled = !p4 || !online || calibrationLoading;
    document.querySelectorAll("[data-joint-select]").forEach((select) => {
      const supported = select.closest("#limits-form") ? legacy : select.closest("#body-calibration-form") ? p4 : p4 || legacy;
      select.disabled = !online || !supported || calibrationLoading;
    });
    byId("body-calibration-trim").hidden = !p4;
    byId("calibration-pulse-help").hidden = !p4;
    byId("limits-form").hidden = !legacy;
    byId("body-calibration-form").hidden = !p4;
    const angleMapping = p4 && hasJointAngleMapping();
    for (const id of ["calibration-angle-label", "calibration-scale-label", "calibration-mapping-help"]) byId(id).hidden = !angleMapping;
    for (const name of ["home_deg", "us_per_degree"]) byId("body-calibration-form").elements[name].disabled = !angleMapping || !editing || calibrationLoading;
    byId("servo-duration-label").hidden = p4;
    text("servo-target-label", p4 ? "Target pulse µs" : "Angle");
    text("calibration-neutral-button", p4 ? "Home all assigned joints" : "All neutral");
    const bounds = calibrationPulseBounds();
    const pulse = byId("servo-form").elements.deg;
    pulse.step = p4 ? "1" : "0.1";
    pulse.min = p4 ? bounds.min : "0";
    pulse.max = p4 ? bounds.max : "180";
    const home = byId("body-calibration-form").elements.center;
    home.min = bounds.min;
    home.max = bounds.max;
    const state = !online ? "Connect a robot to calibrate its joints." : !p4 && !legacy ?
      "This body has not advertised joint calibration support." : !p4 ? "Eight-joint angle calibration." :
      calibrationLoading ? "Waiting for the controller's readback…" : !calibrationData ?
      "Read calibration from the body to load its twelve joints." :
      `${calibrationEntry.mode === "calibrate" ? "Calibration enabled" : "Enable calibration to adjust joints"}. ${calibrationEdited ? "Edited settings are not saved" : calibrationData.dirty ? "Unsaved changes" : calibrationData.saved ? "Saved on the body" : "Defaults have not been saved"}. ${calibrationData.ready ? "Pulse values are commands, not measured shaft positions. Home uses µs; staging does not move a servo." : calibrationData.reason || "Servo outputs unavailable."}`;
    text("calibration-availability", state + (p4 && calibrationData?.profile_confirmed === false ? " Review the mounting reference and mapping, then Save before using motion commands." : ""));
    renderCalibrationSlider(moving);
    renderCalibrationReadback();
  }

  function bodyStorageEnabled() {
    return Boolean(calibrationEntry && calibrationEntry.model === "v2-12servo" &&
      (calibrationEntry.features || []).includes("storage_control_v1") &&
      (calibrationEntry.capabilities || {}).storage === true);
  }

  function renderStorage() {
    const online = calibrationEntry && calibrationEntry.connection_state !== "stale";
    const enabled = online && bodyStorageEnabled();
    const mounted = storageData ? storageData.mounted : Boolean(calibrationEntry && calibrationEntry.status && calibrationEntry.status.sd);
    const busy = storageLoading || Boolean(storageData && storageData.busy);
    byId("storage-read-button").disabled = !enabled || storageLoading;
    byId("storage-retry-button").disabled = !enabled || busy;
    byId("storage-clear-button").disabled = !enabled || busy || !storageData || !storageData.available || !mounted;
    text("sd-state", mounted ? "Mounted" : "Unavailable");
    byId("sd-state").className = `state-chip ${mounted ? "active" : ""}`;
    text("storage-details", !online ? "Connect a robot to read storage status." : !enabled ?
      (calibrationEntry.capabilities && calibrationEntry.capabilities.reasons || {}).storage || "Storage controls are unavailable on this body." :
      storageLoading ? "Waiting for storage readback from the body…" : !storageData ? "Read storage status from the body." :
      `${storageData.mounted ? `${(storageData.free_bytes / 1048576).toFixed(1)} MiB free of ${(storageData.total_bytes / 1048576).toFixed(1)} MiB` : "SD card is not mounted"}. ${storageData.dropped_records} dropped records.${storageData.busy ? " Storage is busy." : ""}${storageData.error ? ` ${storageData.error}` : ""}`);
  }

  async function operateStorage(op) {
    if (!bodyStorageEnabled() || storageLoading) return;
    if (op === "clear" && !window.confirm("Delete all Ainekio logs and captures from the robot's SD card? This cannot be undone.")) return;
    const session = calibrationSession;
    storageLoading = true;
    renderStorage();
    try {
      const response = await command("/api/storage", {op, ...(op === "clear" ? {confirmed: true} : {})},
        op === "clear" ? "Logs and captures cleared on body" : "Storage status confirmed by body");
      if (session !== calibrationSession) return;
      storageData = response.storage;
    } catch (_error) {
      if (session === calibrationSession) storageData = null;
    } finally {
      storageLoading = false;
      renderStorage();
    }
  }

  function setupForms() {
    byId("storage-read-button").addEventListener("click", () => operateStorage("get"));
    byId("storage-retry-button").addEventListener("click", () => operateStorage("retry"));
    byId("storage-clear-button").addEventListener("click", () => operateStorage("clear"));
    document.querySelectorAll("[data-profile]").forEach((button) => button.addEventListener("click", () => command("/api/profile", { name: button.dataset.profile }, "Profile applied")));
    byId("motion-catalog").addEventListener("click", (event) => {
      const button = event.target.closest("[data-emote]");
      if (!button || button.disabled || !bodyCommandAvailable(button.dataset.emote)) return;
      sendNamedMotion("emote", button.dataset.emote, `${button.textContent.trim()} sent`);
    });
    document.querySelectorAll("[data-state]").forEach((button) => button.addEventListener("click", () => command("/api/state", { name: button.dataset.state, ...(button.dataset.state === "sleep" ? { sleep_s: 60 } : {}) }, "State applied")));
    document.querySelectorAll("[data-calibration-mode]").forEach((button) => button.addEventListener("click", async () => {
      const generation = calibrationGeneration;
      if (bodyCalibrationEnabled()) {
        calibrationWorkspaceForRobot().resume = button.dataset.calibrationMode === "calibrate";
        persistCalibrationWorkspace();
      }
      try {
        showCalibrationResult(button.dataset.calibrationMode === "calibrate" ? "Enabling calibration…" : "Exiting calibration…");
        await command("/api/calibration/mode", {mode: button.dataset.calibrationMode}, "Calibration mode requested");
        if (generation !== calibrationGeneration) return;
        await refreshStatus();
        if (bodyCalibrationEnabled()) await calibrateBody("get", {}, "Calibration read from body");
      } catch (error) { if (generation === calibrationGeneration) showCalibrationResult(error.message, true); }
    }));

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
    byId("wake-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const values = new FormData(form);
      command("/api/wake", { enabled: form.elements.enabled.checked, model: values.get("model") }, "Wake setting sent");
    });
    byId("snapshot-button").addEventListener("click", () => command("/api/snap", {}, "Snapshot requested"));
    const speakerTestForm = byId("speaker-test-form");
    const speakerTestVolume = byId("speaker-test-volume");
    const speakerTestVolumeOutput = byId("speaker-test-volume-output");
    const updateSpeakerTestVolume = () => {
      speakerTestVolumeOutput.value = `${speakerTestVolume.value}%`;
    };
    speakerTestVolume.addEventListener("input", updateSpeakerTestVolume);
    updateSpeakerTestVolume();
    speakerTestForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const volumePercent = Number(new FormData(speakerTestForm).get("volume_percent"));
      command(
        "/api/speaker-test",
        { volume_percent: volumePercent },
        `Speaker test sent at ${volumePercent}%`,
      );
    });
    byId("servo-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const values = new FormData(event.currentTarget);
      if (bodyCalibrationEnabled()) calibrateBody("move", {id: Number(values.get("id")), pulse_us: Number(values.get("deg"))}, "Joint command confirmed");
      else command("/api/calibration/servo", { id: Number(values.get("id")), deg: Number(values.get("deg")), ms: Number(values.get("ms")) }, "Joint target sent");
    });
    byId("servo-form").elements.deg.addEventListener("input", () => {
      if (!bodyCalibrationEnabled()) return;
      cancelCalibrationSlider();
      rememberCalibrationPulse();
      renderCalibration();
    });
    const slider = byId("calibration-pulse-slider");
    slider.addEventListener("input", () => {
      cancelCalibrationSlider();
      byId("servo-form").elements.deg.value = slider.value;
      rememberCalibrationPulse();
      renderCalibration();
    });
    slider.addEventListener("change", () => {
      cancelCalibrationSlider();
      const generation = calibrationGeneration;
      const robotId = selectedRobotId;
      const id = Number(byId("servo-form").elements.id.value);
      const pulse_us = Number(slider.value);
      calibrationSliderTimer = window.setTimeout(() => {
        calibrationSliderTimer = null;
        if (generation !== calibrationGeneration || robotId !== selectedRobotId ||
            id !== Number(byId("servo-form").elements.id.value) || slider.disabled) return;
        calibrateBody("move", {id, pulse_us}, "Slider target confirmed");
      }, 120);
    });
    slider.addEventListener("pointercancel", cancelCalibrationSlider);
    byId("calibration-use-body-values").addEventListener("click", () => {
      cancelCalibrationSlider();
      calibrationSliderView = null;
      delete calibrationWorkspaceForRobot().joints[Number(byId("servo-form").elements.id.value)];
      persistCalibrationWorkspace();
      persistCalibrationWorkspace();
      fillCalibrationFields(true);
      renderCalibration();
      showCalibrationResult("Local edits discarded. Fields now match the robot’s reported settings. No command was sent.");
    });
    byId("limits-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const values = new FormData(form);
      if (calibrationEntry && (!calibrationEntry.model || calibrationEntry.model === "v1-8servo"))
        command("/api/calibration/limits", { id: Number(values.get("id")), min: Number(values.get("min")), center: Number(values.get("center")), max: Number(values.get("max")), invert: form.elements.invert.checked }, "Joint limits staged");
    });
    byId("body-calibration-form").addEventListener("submit", (event) => {
      event.preventDefault();
      if (!bodyCalibrationEnabled()) return;
      const fields = calibrationFields();
      if (fields) calibrateBody("set", fields, "Joint settings staged on body");
    });
    byId("body-calibration-form").addEventListener("input", () => {
      if (bodyCalibrationEnabled()) { rememberCalibrationSettings(); renderCalibration(); }
    });
    byId("calibration-save-button").addEventListener("click", () => bodyCalibrationEnabled() ? saveBodyCalibration() : command("/api/calibration/save", {}, "Calibration saved"));
    byId("calibration-neutral-button").addEventListener("click", () => bodyCalibrationEnabled() ? calibrateBody("home", {}, "Assigned joints homed") : command("/api/calibration/neutral", {}, "Neutral targets sent"));
    byId("calibration-read-button").addEventListener("click", () => calibrateBody("get", {}, "Calibration read from body"));
    byId("calibration-joint-home-button").addEventListener("click", () => {
      const joint = selectedCalibrationJoint();
      if (joint) calibrateBody("home", {id: joint.id}, "Selected joint homed");
    });
    document.querySelectorAll("[data-calibration-trim]").forEach((button) => button.addEventListener("click", () => {
      const joint = selectedCalibrationJoint();
      if (!joint) return;
      calibrateBody("move", {id: joint.id, pulse_us: (joint.pulse_us || joint.home_us) + Number(button.dataset.calibrationTrim)}, "Joint trim confirmed");
    }));
    byId("calibration-use-position-button").addEventListener("click", () => {
      const joint = selectedCalibrationJoint();
      if (!joint || !joint.pulse_us) { showCalibrationResult("Home or move the joint before using its commanded pulse.", true); return; }
      byId("body-calibration-form").elements.center.value = joint.pulse_us;
      rememberCalibrationSettings();
      renderCalibration();
      showCalibrationResult("Last commanded pulse copied to the Home field. This is a local edit; apply or save when ready.");
    });
    document.querySelectorAll("[data-joint-select]").forEach((select) => select.addEventListener("change", () => {
      if (!bodyCalibrationEnabled()) return;
      cancelCalibrationSlider();
      document.querySelectorAll("[data-joint-select]").forEach((other) => { other.value = select.value; });
      showCalibrationResult("");
      calibrationWorkspaceForRobot().joint = Number(select.value);
      persistCalibrationWorkspace();
      fillCalibrationFields(true);
      renderCalibration();
    }));
    byId("calibration-detach-button").addEventListener("click", () => {
      cancelCalibrationSlider();
      command("/api/calibration/detach", {}, "Outputs detached");
    });
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
    const settings = byId("settings-panel");
    const settingsButton = byId("settings-button");
    function showSettings(open) {
      settings.hidden = !open;
      settingsButton.setAttribute("aria-expanded", String(open));
      if (open) {
        if (selectedRobotId) byId("token-robot-id").value = selectedRobotId;
        settings.scrollIntoView({ block: "start" });
        byId("password-form").elements.current_password.focus({ preventScroll: true });
      } else {
        byId("password-form").reset();
        byId("password-result").hidden = true;
        settingsButton.focus();
      }
    }
    settingsButton.addEventListener("click", () => showSettings(settings.hidden));
    byId("settings-close-button").addEventListener("click", () => showSettings(false));
    byId("password-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const values = Object.fromEntries(new FormData(form));
      const result = byId("password-result");
      const button = form.querySelector("button[type=submit]");
      result.hidden = false;
      result.classList.remove("form-error");
      if (values.new_password !== values.confirm_password) {
        result.textContent = "The new passwords do not match.";
        result.classList.add("form-error");
        return;
      }
      button.disabled = true;
      result.textContent = "Saving password…";
      try {
        await request("/api/settings/password", { method: "POST", body: JSON.stringify(values) });
        form.reset();
        result.textContent = "Password changed. This browser stays signed in; other browsers have been signed out.";
      } catch (error) {
        result.textContent = error.message;
        result.classList.add("form-error");
      } finally {
        button.disabled = false;
      }
    });
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
    if (robotIds.length === 0 && !preferredRobotId) {
      const option = new Option("No robot connected", "");
      select.add(option);
      selectedRobotId = null;
      if (previous !== null) { resetWalking(); resetCameraView("Waiting for a physical robot to connect."); }
      return;
    }
    robotIds.forEach((robotId) => select.add(new Option(robotId, robotId)));
    if (preferredRobotId && !robotIds.includes(preferredRobotId)) select.add(new Option(`${preferredRobotId} (offline)`, preferredRobotId));
    selectedRobotId = preferredRobotId || (robotIds.includes(previous) ? previous : robotIds[0]);
    preferredRobotId = selectedRobotId;
    writeLocal("ainekio-selected-robot", preferredRobotId);
    select.value = selectedRobotId;
    if (selectedRobotId !== previous) { resetCameraView(); resetWalking(); updateMotionSpeed(null); }
  }

  function text(id, value) { byId(id).textContent = value; }

  function renderMotionCatalog(entry, legacyBody) {
    const catalog = byId("motion-catalog");
    const declared = entry && !legacyBody ? (entry.capabilities && entry.capabilities.commands || []) : null;
    const dedicated = new Set(["crab_right", "crab_forward", "crab_backward", "crab_turn_left", "crab_turn_right", "run", "walk", "backward", "left", "right", "crawl", "stop", "say", "face", "look", "stand", "neutral"]);
    // Keep the established labels, and accept newly installed clips from the
    // body's catalog without adding a second hardcoded firmware name list.
    catalog.querySelectorAll("[data-installed-motion]").forEach((button) => {
      if (!declared || !declared.includes(button.dataset.emote)) button.remove();
    });
    const existing = new Set(Array.from(catalog.querySelectorAll("[data-emote], [data-intent]"),
      (button) => button.dataset.emote || button.dataset.intent));
    for (const name of declared || []) {
      if (dedicated.has(name) || existing.has(name)) continue;
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.emote = name;
      button.dataset.installedMotion = "";
      button.textContent = name.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
      catalog.append(button);
      existing.add(name);
    }
    catalog.querySelectorAll("[data-emote], [data-intent]").forEach((button) => {
      button.hidden = (button.dataset.emote === "crab" && (entry?.features || []).includes("crab_gait_v1")) ||
        (declared !== null && !declared.includes(button.dataset.emote || button.dataset.intent));
    });
  }

  function updateRobotSettings(entry) {
    const supported = Boolean(entry && entry.connected && entry.connection_state !== "stale" &&
      (entry.features || []).includes("robot_settings_v1"));
    const session = supported ? `${selectedRobotId}:${entry.epoch}` : null;
    if (session !== robotSettingsSession) {
      robotSettingsSession = session;
      robotSettings = null;
      byId("robot-network-form").reset();
      byId("robot-security-form").reset();
      text("robot-settings-result", "");
    }
    text("robot-settings-availability", !entry || !entry.connected ? "Connect a robot to read its settings." :
      !supported ? "This robot needs the firmware update for settings management." : `Settings for ${selectedRobotId}`);
    byId("robot-settings-read").disabled = !supported || robotSettingsBusy;
    byId("robot-settings-editor").hidden = !robotSettings;
    byId("robot-settings-editor").querySelectorAll("button, input, select").forEach(el => { el.disabled = robotSettingsBusy || !supported; });
    byId("robot-settings-apply").disabled = robotSettingsBusy || !supported || !robotSettings?.pending_restart;
  }

  function loadRobotNetworkSlot() {
    const form = byId("robot-network-form");
    const index = Number(form.elements.index.value);
    const profile = robotSettings?.networks.find(p => p.index === index);
    form.elements.ssid.value = profile?.ssid || "";
    form.elements.endpoint.value = profile?.endpoint || "";
    form.elements.wifi_password.value = "";
    form.elements.change_wifi_password.checked = !profile;
    byId("robot-network-remove").disabled = !profile || robotSettingsBusy;
  }

  async function robotSettingsRequest(op, values = {}) {
    const session = robotSettingsSession;
    const robotId = selectedRobotId;
    if (!session || robotSettingsBusy || (op !== "get" && !robotSettings)) return;
    robotSettingsBusy = true;
    updateRobotSettings(calibrationEntry);
    text("robot-settings-result", "Waiting for the robot…");
    try {
      const payload = {op, robot_id: robotId, ...values};
      if (op !== "get") payload.revision = robotSettings.revision;
      const result = await request("/api/settings/robot", {method: "POST", body: JSON.stringify(payload)});
      if (session !== robotSettingsSession) return;
      robotSettings = result.settings;
      byId("robot-security-form").reset();
      loadRobotNetworkSlot();
      text("robot-settings-state", `Connected slot: ${robotSettings.active_index < 0 ? "none" : robotSettings.active_index + 1}. ` +
        (robotSettings.pending_restart ? "Saved changes are waiting for restart." : "Saved settings are active.") +
        (robotSettings.setup_open ? " The robot setup hotspot is open." : " The robot setup hotspot uses a password."));
      text("robot-settings-result", op === "get" ? "Settings read from the robot." : op === "apply" ?
        "Restart accepted. Waiting for the robot to reconnect; connection is not yet confirmed." : "Saved on the robot. Restart when ready to apply.");
    } catch (error) {
      if (session === robotSettingsSession) text("robot-settings-result", error.message);
    } finally {
      robotSettingsBusy = false;
      updateRobotSettings(calibrationEntry);
    }
  }

  function setupRobotSettings() {
    byId("robot-settings-read").addEventListener("click", () => robotSettingsRequest("get"));
    byId("robot-network-index").addEventListener("change", loadRobotNetworkSlot);
    byId("robot-network-form").addEventListener("submit", event => {
      event.preventDefault();
      const form = event.currentTarget;
      const values = {index: Number(form.elements.index.value), ssid: form.elements.ssid.value, endpoint: form.elements.endpoint.value};
      if (form.elements.change_wifi_password.checked) values.wifi_password = form.elements.wifi_password.value;
      robotSettingsRequest("network", values);
    });
    byId("robot-network-remove").addEventListener("click", () => {
      const index = Number(byId("robot-network-index").value);
      if (window.confirm("Remove this saved network? It remains connected until you restart the robot.")) robotSettingsRequest("remove", {index});
    });
    byId("robot-security-form").addEventListener("submit", event => {
      event.preventDefault();
      const form = event.currentTarget;
      const values = {};
      if (form.elements.change_setup_password.checked) values.setup_password = form.elements.setup_password.value;
      if (form.elements.change_robot_token.checked) values.robot_token = form.elements.robot_token.value;
      if (!Object.keys(values).length) { text("robot-settings-result", "Select the credential you want to change."); return; }
      robotSettingsRequest("security", values);
    });
    byId("robot-settings-apply").addEventListener("click", () => {
      if (window.confirm("Restart the robot and apply saved settings? The connection will drop. Normal startup can move the servos to their saved Home positions."))
        robotSettingsRequest("apply", {confirmed: true});
    });
  }

  function renderStatus(payload) {
    const robots = payload.robots || {};
    const robotIds = Object.keys(robots).sort();
    updateRobotSelect(robotIds);
    const entry = selectedRobotId ? robots[selectedRobotId] : null;
    const status = entry && entry.status;
    const legacyBody = entry && (!entry.model || entry.model === "v1-8servo");
    availableBodyCommands = !entry || entry.connection_state === "stale" ? [] :
      Array.isArray(entry.robot_commands) ? entry.robot_commands :
        legacyBody && (!entry.capabilities || entry.capabilities.motion === true) ? null : [];
    renderMotionCatalog(entry, legacyBody);
    updateMotionSpeed(entry);
    document.querySelectorAll("[data-intent], [data-emote], [data-held-direction]").forEach((button) => {
      const name = button.dataset.intent || button.dataset.emote || directionCommands[button.dataset.heldDirection];
      button.disabled = !bodyCommandAvailable(name) ||
        (availableBodyCommands === null && button.hasAttribute("data-requires-declaration"));
    });
    directionalWalking = Boolean(entry && entry.model === "v2-12servo" && (entry.features || []).includes("walk_controls_v2"));
    variableWalking = directionalWalking || Boolean(entry && entry.model === "v2-12servo" && (entry.features || []).includes("walk_controls_v1"));
    runningSupported = Boolean(directionalWalking && (entry.features || []).includes("run_gait_v1") && bodyCommandAvailable("run"));
    crabSupported = Boolean(directionalWalking && (entry.features || []).includes("crab_gait_v1") && bodyCommandAvailable("crab"));
    byId("walk-gait").querySelector('[value="crab"]').disabled = !crabSupported;
    if (!crabSupported && byId("walk-gait").value === "crab") byId("walk-gait").value = "walk";
    byId("walk-gait").querySelector('[value="run"]').disabled = !runningSupported;
    if (!runningSupported && byId("walk-gait").value === "run") byId("walk-gait").value = "walk";
    byId("locomotion-options").hidden = !directionalWalking;
    byId("walk-gait").querySelector('[value="crawl"]').disabled = !bodyCommandAvailable("crawl");
    Array.from(byId("walk-direction").options).forEach(option => { option.disabled = !bodyCommandAvailable(directionCommands[option.value]); });
    byId("walk-controls").hidden = !variableWalking;
    byId("walk-fields").disabled = !variableWalking || !bodyCommandAvailable("walk");
    updateWalkingStatus(entry);
    updateSpeedRange();
    const installedMotions = (entry && entry.capabilities && entry.capabilities.commands || []).filter((name) => name !== "stop");
    text("motion-availability", !entry ? "Connect a robot to use its motions." :
      `${entry.model || "v1-8servo"}: ${availableBodyCommands === null ? "body motions available" :
        availableBodyCommands.length ? availableBodyCommands.join(", ") :
          installedMotions.length ? `${installedMotions.join(", ")} installed; motion unavailable` : "motion unavailable"}`);
    calibrationEntry = entry;
    updateRobotSettings(entry);
    const session = entry ? `${selectedRobotId}:${entry.epoch}:${entry.model}` : null;
    if (session !== calibrationSession) {
      calibrationGeneration++;
      cancelCalibrationSlider();
      calibrationSession = session;
      calibrationData = null;
      calibrationReadAt = null;
      showCalibrationResult("");
      calibrationAttempted = false;
      calibrationLoading = false;
      calibrationEdited = false;
      storageData = null;
      storageAttempted = false;
      document.querySelectorAll("[data-joint-select]").forEach((select) => select.replaceChildren());
      if (legacyBody) {
        byId("servo-form").elements.deg.value = "90";
        byId("servo-form").elements.deg.min = "0";
        byId("servo-form").elements.deg.max = "180";
        ["min", "center", "max"].forEach((name, index) => { byId("limits-form").elements[name].value = [0, 90, 180][index]; });
      }
    }
    const p4Calibration = bodyCalibrationEnabled();
    if (entry && entry.calibration && !calibrationLoading &&
        (!calibrationData || entry.calibration.seq >= calibrationData.seq)) calibrationData = entry.calibration;
    document.querySelectorAll("[data-joint-select]").forEach((select) => {
      const supported = select.closest("#limits-form") ? legacyBody : select.closest("#body-calibration-form") ? p4Calibration : legacyBody || p4Calibration;
      select.disabled = !supported || calibrationLoading;
      if (!supported) return;
      if (select.options.length) return;
      const joints = p4Calibration ? bodyJointNames.map((label, id) => ({id, label})) :
        legacyBody ? (payload.joint_contract && payload.joint_contract.joints || []) : [];
      joints.forEach((joint) => select.add(new Option(p4Calibration ? joint.label : `${joint.id}: ${joint.label}`, joint.id)));
      if (p4Calibration) select.value = String(calibrationWorkspaceForRobot().joint);
    });
    fillCalibrationFields();
    renderCalibration();
    if (p4Calibration && entry.connection_state !== "stale" && !calibrationAttempted && !calibrationLoading) {
      calibrationAttempted = true;
      calibrateBody("get", {}, "Calibration read from body");
    }
    if (entry && entry.storage && !storageLoading && (!storageData || entry.storage.seq >= storageData.seq)) storageData = entry.storage;
    renderStorage();
    if (bodyStorageEnabled() && entry.connection_state !== "stale" && !storageAttempted && !storageLoading) {
      storageAttempted = true;
      operateStorage("get");
    }
    const online = entry && entry.connection_state !== "stale";
    const capability = (name) => Boolean(online && (legacyBody || (entry.capabilities || {})[name] === true));
    const unavailable = (name) => !online ? "Connect a robot first" :
      (entry.capabilities && entry.capabilities.reasons || {})[name] || `${name} is unavailable on this body`;
    const gates = {"[data-profile]": "profile", "[data-state]": "power", "#camera-form input, #camera-form select, #camera-form button, #snapshot-button": "camera",
      "#microphone-form input, #microphone-form select, #microphone-form button": "microphone", "#speaker-test-form input, #speaker-test-form button": "speaker",
      "#wake-form input, #wake-form select, #wake-form button": "wake", '#asset-intent-form button[value="face"]': "display", '#asset-intent-form button[value="say"]': "speaker"};
    Object.entries(gates).forEach(([selector, name]) => document.querySelectorAll(selector).forEach((control) => {
      control.disabled = !capability(name);
      control.title = capability(name) ? "" : unavailable(name);
    }));
    const connection = byId("connection-state");
    const connectionState = entry ? entry.connection_state || "online" : "offline";
    connection.textContent = connectionState === "stale" ? "Stale" : entry ? "Online" : "Offline";
    connection.classList.toggle("online", connectionState === "online");
    connection.classList.toggle("stale", connectionState === "stale");
    connection.classList.toggle("offline", !entry);
    const state = status ? status.state : "unknown";
    text("body-state", state);
    byId("body-state").className = `state-chip ${state}`;
    text("status-battery", status ? status.power_monitor_ready === false ? "Not monitored" : `${Number(status.vbat).toFixed(2)} V` : "--");
    text("status-rssi", status ? `${status.rssi} dBm` : "--");
    text("status-heap", status ? `${Math.round(status.heap / 1024)} KiB` : "--");
    text("status-uptime", status ? formatDuration(status.uptime) : "--");
    text("status-sd", status ? (status.sd ? "Mounted" : "Unavailable") : "--");
    text("status-session", entry ? `${entry.epoch} / ${entry.next_sequence}` : "--");
    text("status-heartbeat", entry ? `${entry.heartbeat_age_ms} ms` : "--");
    const caps = entry && entry.effective_caps || payload.effective_caps;
    text("status-caps", caps ? `${entry && entry.profile || payload.profile}: ${caps.camera_max_fps} fps` : "--");
    text("status-camera-drops", status ? status.cam_drops : "--");
    text("status-audio-faults", status ? `${status.mic_drops} / ${status.spk_underruns}` : "--");
    const wakeReady = Boolean(status && status.wake_ready);
    const wakeEnabled = Boolean(status && status.wake_enabled);
    const wakeModel = status && status.wake_model ? status.wake_model : "ainekio";
    text("status-wake", status ? `${wakeEnabled ? "On" : "Off"} / ${wakeModel} / ${wakeReady ? "Ready" : "Model unavailable"}` : "--");
    const wakeForm = byId("wake-form");
    if (!wakeForm.contains(document.activeElement)) {
      wakeForm.elements.enabled.checked = wakeEnabled;
      wakeForm.elements.model.value = wakeModel;
    }
    text("wake-capability", wakeReady ? "Wake-word model ready" : "Wake-word model unavailable; enabling is blocked");
    document.querySelectorAll("[data-requires-wake]").forEach((option) => { option.disabled = !wakeReady || !wakeEnabled; });
    const terminal = entry && entry.last_terminal;
    const terminalDetail = terminal ? [terminal.t, terminal.code, terminal.msg].filter(Boolean).join(": ") : "none";
    text("status-lifecycle", entry ? `${entry.pending} pending / ${terminalDetail}` : "--");
    const terminalKey = terminal ? JSON.stringify([selectedRobotId, entry.epoch, terminal.seq, terminal.t, terminal.code, terminal.msg]) : null;
    if (terminalKey !== reportedTerminal) {
      reportedTerminal = terminalKey;
      if (terminal && terminal.t === "nak") {
        showResult(`Command ${terminal.seq} rejected: ${[terminal.code, terminal.msg].filter(Boolean).join(" — ")}`, true);
      }
    }
    const lastCommand = entry && entry.last_command;
    text("status-command", lastCommand ? `${lastCommand.t}${lastCommand.name ? `:${lastCommand.name}` : ""} #${lastCommand.seq}` : "--");
    text("status-face", status && status.face ? status.face : "--");
    byId("microphone-level").value = entry ? entry.microphone_level : 0;

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
    if (statusRequest) return statusRequest;
    const generation = statusGeneration;
    statusRequest = (async () => {
      try {
        const payload = await request("/api/status");
        if (generation === statusGeneration) renderStatus(payload);
      } catch (error) {
        if (generation === statusGeneration) showResult(error.message, true);
      } finally { statusRequest = null; }
    })();
    return statusRequest;
  }

  async function setupDashboard() {
    const session = await request("/api/session");
    csrfToken = session.csrf;
    setupPrimaryView();
    byId("robot-select").addEventListener("change", (event) => {
      availableBodyCommands = [];
      selectedRobotId = event.target.value || null;
      updateMotionSpeed(null);
      preferredRobotId = selectedRobotId;
      writeLocal("ainekio-selected-robot", preferredRobotId);
      statusGeneration++;
      calibrationGeneration++;
      cancelCalibrationSlider();
      calibrationEntry = null;
      calibrationData = null;
      calibrationReadAt = null;
      showCalibrationResult("");
      calibrationSession = null;
      calibrationLoading = false;
      calibrationEdited = false;
      storageData = null;
      renderCalibration();
      renderStorage();
      resetWalking();
      resetCameraView();
      refreshStatus();
    });
    setupMotionControls();
    setupForms();
    setupSecurity();
    setupRobotSettings();
    await refreshStatus();
    runCameraView();
    statusTimer = window.setInterval(refreshStatus, 1000);
  }

  if (!setupLogin()) {
    setupDashboard().catch((error) => showResult(error.message, true));
  }

  window.addEventListener("beforeunload", () => {
    cancelCalibrationSlider();
    if (statusTimer !== null) window.clearInterval(statusTimer);
    cameraViewActive = false;
    if (cameraRequestController) cameraRequestController.abort();
    if (cameraObjectUrl) URL.revokeObjectURL(cameraObjectUrl);
  });
})();

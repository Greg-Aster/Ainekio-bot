(function () {
  "use strict";

  const HELD_MOTION_STEPS = 10;

  let audioSession = null;
  const audioForms = {
    microphone: { edited: false, pending: null, revision: 0 },
    wake: { edited: false, pending: null, revision: 0 },
    speaker: { edited: false, pending: null, revision: 0 },
  };
  let robotSettings = null;
  let robotSettingsSession = null;
  let robotSettingsBusy = false;
  let csrfToken = null;
  let hostNetworkBusy = false;
  let selectedRobotId = null;
  let bodyEventsRobot = null;
  let bodyEventsEdited = false;
  let bodyEventsSaving = false;
  let preferredRobotId = readLocal("ainekio-selected-robot", null);
  let statusRequest = null;
  let statusGeneration = 0;
  let reportedTerminal = null;
  let availableBodyCommands = [];
  let variableWalking = false;
  let directionalWalking = false;
  let steeringSupported = false;
  let runningSupported = false;
  let crabSupported = false;
  const balanceTuningKeys = ["strength", "damping", "roll_deg", "pitch_deg"];
  let balanceTuningSupported = false;
  let balanceSupported = false;
  let balanceSession = null;
  let balanceGeneration = 0;
  let balanceData = null;
  let balanceBusy = false;
  let balanceEdited = false;
  let balanceEntry = null;
  let servoFeedbackSession = null;
  let servoFeedbackSupported = false;
  let servoFeedbackData = null;
  let servoFeedbackBusy = false;
  let servoFeedbackWriting = false;
  let servoFeedbackRequest = 0;
  let servoFeedbackEdited = false;
  let servoFeedbackReadAt = 0;
  let motionSpeedSupported = false;
  let motionSpeedSession = null;
  let motionSpeedGeneration = 0;
  let motionSpeedData = null;
  let motionSpeedBusy = false;
  let motionSpeedEdited = false;
  let jointSpeedSupported = false;
  let jointSpeedEdited = false;
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
  let maintenanceRobot = null;
  let maintenanceBusy = false;
  let maintenanceReading = false;
  let maintenanceReadAt = 0;
  let maintenanceError = "";
  let recordingData = null;
  let firmwareData = null;
  let recordingFiles = [];
  let faceCatalog = [];
  let faceLibraryReady = false;
  let faceRobot = null;
  let faceAvailable = false;
  let faceSelection = "default";
  let faceRequestGeneration = 0;
  const bodyJointNames = ["Rear left shoulder", "Rear left carrier", "Rear left crank",
    "Rear right shoulder", "Rear right carrier", "Rear right crank", "Front left shoulder",
    "Front left carrier", "Front left crank", "Front right shoulder", "Front right carrier", "Front right crank"];
  const bodyJointParts = [
    "Shoulder: Part_002 moves the whole Part_003 leg carrier inward/outward.",
    "Carrier: Part_006 drives the Part_023 main arm.",
    "Crank: Part_005 drives the short Part_009 arm."
  ];

  const bodyCalibrationFields = ["channel", "center", "home_deg", "us_per_degree"];
  // Rearward assembly reference: SERVO_ASSEMBLY.md and the 0.8.59 journal.
  // Common model angles; per-servo measured Home pulses and invert remain individual.
  const rearwardHomeDegrees = [0, -30.87, -117.68];
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
  const heldSteeringInputs = new Map();
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
  let cameraRecognitionFrameId = null;
  let cameraViewGeneration = 0;
  let visionOperations = new Set();
  let visionTargetBusy = false;
  let cameraProfileSession = null;
  let cameraSettingsRobotId = null;
  let recognitionEdited = false;
  let recognitionSaving = false;
  let behaviorEdited = false;
  let behaviorBusy = false;
  let behaviorRevision = 0;
  let behaviorReadAt = 0;
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

  function filterFaces() {
    const query = byId("face-search").value.trim().toLowerCase();
    const group = byId("face-group").value;
    let visible = 0;
    document.querySelectorAll("[data-face-expression]").forEach((button) => {
      button.hidden = Boolean((group && button.dataset.group !== group) ||
        !button.dataset.faceExpression.replaceAll("_", " ").includes(query));
      if (!button.hidden) visible++;
    });
    byId("face-empty").hidden = visible !== 0;
  }

  async function selectFace(face) {
    faceSelection = face.name;
    byId("face-preview").src = `/assets/faces/${face.name}.webp`;
    byId("face-preview").alt = `${face.label} expression preview`;
    text("face-preview-name", face.label);
    document.querySelectorAll("[data-face-expression]").forEach((button) =>
      button.setAttribute("aria-pressed", String(button.dataset.faceExpression === face.name)));
    const robot = selectedRobotId;
    const generation = ++faceRequestGeneration;
    const current = () => robot === selectedRobotId && generation === faceRequestGeneration;
    text("face-library-status", `Sending ${face.label.toLowerCase()}…`);
    try {
      await command("/api/intent", {name: "face", params: {expr: face.name}}, `${face.label} face requested`, current);
      if (current()) text("face-library-status", `${face.label} requested. Only the expression changes.`);
    } catch (error) {
      if (current()) text("face-library-status", error.message);
    }
  }

  function renderFaceAvailability(entry, available) {
    const session = entry ? `${selectedRobotId}:${entry.epoch}` : null;
    const changed = session !== faceRobot || available !== faceAvailable;
    if (session !== faceRobot) {
      faceRobot = session;
      faceRequestGeneration++;
    }
    faceAvailable = available;
    // This gallery previews the P4's wide color library. V1 retains its manual
    // asset control rather than presenting color previews it cannot display.
    byId("faces-section").hidden = Boolean(entry && entry.model !== "v2-12servo");
    document.querySelectorAll("[data-face-expression]").forEach((button) => {
      button.disabled = !available;
    });
    if (!available) text("face-library-status", entry ? "The selected robot's display is unavailable." : "Connect a robot to select an expression.");
    else if (faceLibraryReady && changed)
      text("face-library-status", `${faceCatalog.length} expressions · no movement required`);
  }

  async function setupFaceLibrary() {
    byId("face-search").addEventListener("input", filterFaces);
    byId("face-group").addEventListener("change", filterFaces);
    try {
      faceCatalog = await request("/assets/faces/catalog.json");
      for (const face of faceCatalog) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "face-card";
        button.dataset.faceExpression = face.name;
        button.dataset.group = face.group;
        button.setAttribute("aria-pressed", String(face.name === faceSelection));
        button.disabled = !faceAvailable;
        const image = document.createElement("img");
        image.src = `/assets/faces/${face.name}.png`;
        image.alt = "";
        image.loading = "lazy";
        image.width = 320; image.height = 170;
        const label = document.createElement("span");
        label.textContent = face.label;
        button.append(image, label);
        button.addEventListener("click", () => selectFace(face));
        byId("face-library").append(button);
      }
      faceLibraryReady = true;
      text("face-count", `${faceCatalog.length} expressions`);
      text("face-library-status", faceAvailable ? `${faceCatalog.length} expressions · no movement required` : "Connect a robot to select an expression.");
      filterFaces();
    } catch (error) { text("face-library-status", `Could not load expressions: ${error.message}`); }
  }

  function resetCameraView(message = "Waiting for camera frames. Enable preview in Perception → Camera settings if needed.") {
    cameraViewGeneration++;
    cameraFrameCounter = null;
    cameraFrameRobotId = null;
    cameraRecognitionFrameId = null;
    if (cameraRequestController) cameraRequestController.abort();
    const image = byId("camera-view");
    const output = byId("camera-view-message");
    if (!image || !output) return;
    image.hidden = true;
    byId("camera-image-plane").hidden = true;
    byId("camera-detections").replaceChildren();
    output.textContent = message;
    output.hidden = false;
    if (cameraObjectUrl) URL.revokeObjectURL(cameraObjectUrl);
    cameraObjectUrl = null;
  }

  async function configureVisionTarget(payload) {
    visionTargetBusy = true;
    text("vision-target-result", "Applying target…");
    try {
      const result = await request("/api/vision/target", { method: "POST", body: JSON.stringify(payload) });
      text("vision-target-result", result.operation === "release" ? "Target released." : `Looking for: ${result.classes.join(", ")}`);
      byId("camera-show-detections").checked = true;
      resetCameraView();
    } catch (error) { text("vision-target-result", error.message); }
    finally { visionTargetBusy = false; }
  }

  function renderCameraDetections(observation, sourceFrame) {
    const overlay = byId("camera-detections");
    overlay.replaceChildren();
    for (const item of observation.objects) {
      if (!item.box) continue;
      const box = document.createElement("div");
      box.className = "camera-detection";
      box.style.left = `${item.box.x * 100}%`;
      box.style.top = `${item.box.y * 100}%`;
      box.style.width = `${item.box.width * 100}%`;
      box.style.height = `${item.box.height * 100}%`;
      const label = document.createElement(visionOperations.has("select") ? "button" : "span");
      label.textContent = item.identity?.name ? `${item.identity.name} · ${item.identity.state}` : item.label;
      if (item.score != null) label.textContent += ` · ${Math.round(item.score * 100)}%`;
      if (item.trackId) box.title = `Track ${item.trackId} (continuity estimate)`;
      if (label.tagName === "BUTTON") {
        label.type = "button";
        label.title = "Use this object as a visual reference";
        label.addEventListener("click", () => configureVisionTarget({ operation: "select", description: item.label, box: item.box,
          frame: { id: sourceFrame.id, dataUrl: `data:image/jpeg;base64,${sourceFrame.jpeg}`,
            timestamp: new Date(Date.now() - observation.ageMs).toISOString(),
            metadata: { robotId: observation.robotId, gatewayInstance: observation.gatewayInstance,
              epoch: observation.epoch, counter: observation.frameCounter } } }));
      }
      box.append(label);
      overlay.append(box);
    }
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
      const showDetections = byId("camera-show-detections").checked;
      const generation = cameraViewGeneration;
      if (showDetections) {
        query.set("view", "recognition");
        if (cameraRecognitionFrameId) query.set("after_id", cameraRecognitionFrameId);
      }
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
        if (robotId !== selectedRobotId || generation !== cameraViewGeneration) continue;
        let blob, observation, recognitionFrame;
        if (showDetections) {
          recognitionFrame = await response.json();
          if (generation !== cameraViewGeneration) continue;
          if (!recognitionFrame) {
            if (!cameraObjectUrl) {
              text("camera-view-message", "Waiting for a recognition result. Camera and recognition must be enabled.");
            }
            text("camera-detection-status", cameraObjectUrl
              ? "Waiting for a new recognition result · showing previous source image."
              : "Waiting for the first recognition image.");
            continue;
          }
          observation = recognitionFrame.observation;
          if (!recognitionFrame.jpeg) {
            text("camera-detection-status", `${observation.objects.length} detections · frame ${observation.frameCounter}` +
              ` · ${Math.round(observation.ageMs)} ms since receipt · ${observation.model}`);
            continue;
          }
          blob = new Blob([Uint8Array.from(atob(recognitionFrame.jpeg), char => char.charCodeAt(0))], { type: "image/jpeg" });
        } else {
          blob = await response.blob();
        }
        if (generation !== cameraViewGeneration) continue;
        const nextUrl = URL.createObjectURL(blob);
        const image = byId("camera-view");
        // Decode offscreen so the displayed source image and boxes stay paired.
        const nextImage = image.cloneNode(false);
        nextImage.src = nextUrl;
        try { await nextImage.decode(); }
        catch (error) { URL.revokeObjectURL(nextUrl); throw error; }
        if (generation !== cameraViewGeneration) { URL.revokeObjectURL(nextUrl); continue; }
        nextImage.hidden = false;
        image.replaceWith(nextImage);
        byId("camera-image-plane").hidden = false;
        byId("camera-view-message").hidden = true;
        if (cameraObjectUrl) URL.revokeObjectURL(cameraObjectUrl);
        cameraObjectUrl = nextUrl;
        cameraFrameCounter = response.headers.get("X-Ainekio-Camera-Counter");
        if (observation) {
          cameraRecognitionFrameId = recognitionFrame.id;
          renderCameraDetections(observation, recognitionFrame);
          text("camera-detection-status", `${observation.objects.length} detections · frame ${observation.frameCounter}` +
            ` · ${Math.round(observation.ageMs)} ms since receipt · ${observation.model}`);
        } else {
          byId("camera-detections").replaceChildren();
          text("camera-detection-status", "Live camera view.");
        }
      } catch (error) {
        if (error.name !== "AbortError") {
          if (!cameraObjectUrl) resetCameraView("Camera view is temporarily unavailable.");
          await delay(1000);
        }
      } finally {
        if (cameraRequestController === controller) cameraRequestController = null;
        if (showDetections) await delay(200);
      }
    }
  }

  function updateAudioOutputs() {
    byId("microphone-gain-output").value = `${byId("microphone-gain").value} dB`;
    byId("wake-sensitivity-output").value = `${byId("wake-sensitivity").value}%`;
    byId("speaker-volume-output").value = byId("speaker-volume").disabled ? "—" : `${byId("speaker-volume").value}%`;
  }

  async function submitAudioSettings(kind, payload) {
    const state = audioForms[kind];
    const revision = state.revision;
    const session = audioSession;
    state.edited = true;
    try {
      const result = await command(`/api/${kind}`, payload, `${{wake: "Wake", microphone: "Microphone", speaker: "Speaker volume"}[kind]} settings sent`);
      if (audioSession === session && state.revision === revision) state.pending = { ...payload, seq: result.seq };
    } catch (_) { /* command() displays the error; retain edits for retry. */ }
  }

  function renderAudioInput(entry, online, status) {
    const supported = Boolean(entry && (entry.features || []).includes("audio_input_v1"));
    const session = entry ? `${selectedRobotId}:${entry.epoch}` : null;
    if (audioSession !== session) {
      audioSession = session;
      Object.values(audioForms).forEach((state) => { state.edited = false; state.pending = null; state.revision++; });
    }
    document.querySelectorAll("[data-audio-input]").forEach((element) => { element.hidden = !supported; });
    const micForm = byId("microphone-form");
    const wakeForm = byId("wake-form");
    micForm.elements.gain_db.disabled = !supported || micForm.elements.on.disabled;
    wakeForm.elements.sensitivity.disabled = !supported || wakeForm.elements.enabled.disabled;
    const audio = entry && entry.audio_input;
    const fresh = Boolean(online && audio && entry.audio_input_age_ms < 2000);
    const volumeSupported = Number.isInteger(audio?.speaker_volume_percent);
    const speakerForm = byId("speaker-form");
    speakerForm.elements.volume_percent.disabled = !fresh || !volumeSupported || entry?.capabilities?.speaker !== true;
    speakerForm.querySelector("button").disabled = speakerForm.elements.volume_percent.disabled;
    if (!volumeSupported || !fresh) text("speaker-settings-state", !online ? "Robot offline" :
      !supported || (fresh && !volumeSupported) ? "Update this robot's firmware to save speaker volume." : "Waiting for robot volume");
    if (fresh) {
      const micState = audioForms.microphone;
      const wakeState = audioForms.wake;
      const matches = {
        microphone: (p) => p.on === audio.on && p.gate === audio.gate && (p.gain_db === undefined || p.gain_db === audio.gain_db),
        wake: (p) => p.enabled === audio.wake_enabled && (p.threshold === undefined || Math.abs(p.threshold - audio.wake_threshold) <= 0.5 / 255 + 0.00001),
        speaker: (p) => p.volume_percent === audio.speaker_volume_percent,
      };
      Object.entries(audioForms).forEach(([kind, state]) => {
        if (state.pending && matches[kind](state.pending)) { state.edited = false; state.pending = null; }
        else if (state.pending && entry.last_terminal?.seq === state.pending.seq && entry.last_terminal.t === "nak") state.pending = null;
      });
      if (!micState.edited) {
        micForm.elements.on.checked = audio.on;
        micForm.elements.gate.value = audio.gate;
        micForm.elements.gain_db.value = audio.gain_db;
      }
      if (!wakeState.edited) {
        wakeForm.elements.enabled.checked = audio.wake_enabled;
        wakeForm.elements.model.value = status?.wake_model || "ainekio";
        wakeForm.elements.sensitivity.value = Math.round((1 - audio.wake_threshold) * 100);
      }
      const suffix = (state) => state.pending ? " · Waiting for robot confirmation" : state.edited ? " · Unsaved changes" : "";
      if (volumeSupported) {
        const speakerState = audioForms.speaker;
        if (!speakerState.edited) speakerForm.elements.volume_percent.value = audio.speaker_volume_percent;
        text("speaker-settings-state", `Saved on robot: ${audio.speaker_volume_percent}%${audio.speaker_volume_percent === 0 ? " · Muted" : ""}${suffix(speakerState)}`);
      }
      text("microphone-settings-state", `Saved gain: ${audio.gain_db} dB${suffix(micState)}`);
      text("wake-settings-state", `Saved sensitivity: ${Math.round((1 - audio.wake_threshold) * 100)}% (detection threshold ${(audio.wake_threshold * 100).toFixed(1)}%)${suffix(wakeState)}`);
    } else if (supported) {
      text("microphone-settings-state", "Waiting for current microphone settings");
      text("wake-settings-state", "Waiting for current wake settings");
    } else if (!audioForms.wake.edited && !wakeForm.contains(document.activeElement)) {
      wakeForm.elements.enabled.checked = Boolean(status?.wake_enabled);
      wakeForm.elements.model.value = status?.wake_model || "ainekio";
    }
    updateAudioOutputs();
    const listening = supported ? fresh && audio.listening : Boolean(online);
    const rms = listening ? (supported ? audio.rms : entry.microphone_level) || 0 : 0;
    const db = rms > 0 ? 20 * Math.log10(rms) : -Infinity;
    const clipping = Boolean(fresh && audio.listening && audio.peak >= 0.99);
    const meter = byId("microphone-level");
    meter.value = Math.max(0, Math.min(100, (db + 60) / 60 * 100));
    meter.classList.toggle("clipping", clipping);
    text("microphone-level-status", !online ? "Robot offline" : supported && !fresh ? "Waiting for input level" :
      supported && !audio.on ? "Microphone off" : !listening ? "Listening paused during speaker playback" :
      `${supported ? (audio.capturing ? "Recording" : "Listening") : "Sent audio"} · ${db > -60 ? `${db.toFixed(1)} dBFS` : "below −60 dBFS"}${clipping ? " · Clipping — lower gain" : ""}`);
    text("microphone-level-help", supported ? "Input level before wake detection. The scale runs from −60 to 0 dBFS; near 0 means the input is clipping." : "This firmware reports levels only while audio is being sent. Update the robot firmware for input gain, wake sensitivity and levels before detection.");
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
    heldSteeringInputs.clear();
    if (!detach && variableWalking && activeWalkSequence !== null && !heldRequestPending) {
      heldDirection = null; gamepadDirection = null;
      document.querySelectorAll("[data-held-direction]").forEach((button) => button.classList.remove("is-active"));
      await applyWalking(true); return;
    }
    if (detach) resetWalking();
    const robotId = selectedRobotId;
    const pendingRequest = heldRequest || walkRequest;
    // Invalidate a pending start before its late reply can revive held movement.
    if (pendingRequest && activeWalkSequence === null) resetWalking();
    const generation = walkGeneration;
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
    if (canSteer()) {
      const [forward, turn] = directionVector(direction);
      return driveHeldVector(forward, turn);
    }
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
    heldSteeringInputs.clear();
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
      const adoptedWalk = sequence !== activeWalkSequence;
      activeWalkSequence = rejected ? null : sequence;
      activeWalkProfile = activeWalkSequence !== null && entry?.active_walk ?
        {dir: entry.active_walk.dir, gait: entry.active_walk.gait || "walk"} : null;
      if (adoptedWalk && activeWalkProfile && canSteer()) {
        const defaults = directionVector(activeWalkProfile.dir);
        setSteeringVector(entry.active_walk.forward ?? defaults[0], entry.active_walk.turn ?? defaults[1]);
      }
    }
    if (activeWalkProfile && directionalWalking) {
      if (!canSteer()) byId("walk-direction").value = activeWalkProfile.dir;
      byId("walk-gait").value = activeWalkProfile.gait;
    }
    renderWalkingControls();
  }

  function renderWalkingControls() {
    const pending = walkRequestPending || heldRequestPending;
    for (const id of ["walk-direction", "walk-gait", "walk-continuous"]) byId(id).disabled = activeWalkSequence !== null || pending;
    if (canSteer()) byId("walk-direction").disabled = false;
    byId("walk-steering").hidden = !canSteer();
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
    byId("walk-steering").hidden = !canSteer();
  }

  function canSteer() {
    return steeringSupported && (activeWalkProfile?.gait || byId("walk-gait").value) !== "crab";
  }

  function directionVector(direction) {
    return ({ fwd: [100, 0], back: [-100, 0], turn_l: [0, 100], turn_r: [0, -100] })[direction] || [0, 0];
  }

  function setSteeringVector(forward, turn) {
    byId("walk-forward").value = String(forward);
    byId("walk-turn").value = String(turn);
    byId("walk-forward-value").textContent = `${forward}%`;
    byId("walk-turn-value").textContent = `${turn}%`;
  }

  async function driveHeldVector(forward, turn) {
    if (forward === 0 && turn === 0) {
      if (heldDirection === "steering") await stopMotion("Movement released");
      return;
    }
    heldDirection = "steering";
    setSteeringVector(forward, turn);
    await applyWalking();
  }

  function updateHeldSteering(key, direction = null) {
    if (direction === null) heldSteeringInputs.delete(key);
    else heldSteeringInputs.set(key, direction);
    const directions = new Set(heldSteeringInputs.values());
    document.querySelectorAll("[data-held-direction]").forEach((button) =>
      button.classList.toggle("is-active", directions.has(button.dataset.heldDirection)));
    return driveHeldVector(100 * (Number(directions.has("fwd")) - Number(directions.has("back"))),
      100 * (Number(directions.has("turn_l")) - Number(directions.has("turn_r"))));
  }

  function walkingParameters(steps, direction = byId("walk-direction").value) {
    const params = { dir: directionalWalking ? direction : "fwd", steps };
    if (directionalWalking) params.gait = byId("walk-gait").value;
    if (!variableWalking) return params;
    if (byId("walk-mode").value === "auto") params.speed = Number(byId("walk-speed").value);
    else { params.stride = Number(byId("walk-stride").value); params.rate = 2; } // Legacy wire field; current P4 gaits use fast strokes.
    if (canSteer()) {
      params.forward = Number(byId("walk-forward").value);
      params.turn = Number(byId("walk-turn").value);
    }
    return params;
  }

  async function applyWalking(finish = false, updateOnly = false) {
    if (!variableWalking) return;
    if (updateOnly && activeWalkSequence === null && !walkRequestPending) return;
    const profile = activeWalkProfile || { dir: directionalWalking ? byId("walk-direction").value : "fwd", gait: byId("walk-gait").value };
    if (!bodyCommandAvailable(directionCommands[profile.dir]) || (directionalWalking && profile.gait === "crawl" && !bodyCommandAvailable("crawl"))) return;
    if (profile.gait === "crab" && !crabSupported) return;
    if (walkRequestPending) { walkApplyPending = true; walkFinishPending ||= finish; return; }
    if (finish && activeWalkSequence === null) return;
    if (!finish && !byId("walk-controls").reportValidity()) return;
    const robotId = selectedRobotId;
    const generation = walkGeneration;
    const steps = heldDirection === "steering" || directionalWalking && byId("walk-continuous").checked ? 0 : Number(byId("walk-cycles").value);
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

  function renderServoFeedback() {
    const panel = byId("servo-feedback-panel");
    if (!panel) return;
    panel.querySelectorAll("form input, form select, form button, #servo-feedback-read").forEach(el => {
      el.disabled = !servoFeedbackSupported || servoFeedbackWriting;
    });
    const data = servoFeedbackData;
    if (!servoFeedbackSupported) {
      text("servo-feedback-status", "Connect a P4 with servo feedback firmware.");
      byId("servo-feedback-rows").replaceChildren();
      text("servo-feedback-motion", ""); text("servo-feedback-raw", ""); text("servo-feedback-points", "");
      return;
    }
    if (!data) return;
    text("servo-feedback-status", `${data.enabled ? "Reading enabled" : "Reading off"} · ${data.joints.filter(j => j.calibrated).length}/12 joints calibrated · scan ${data.scan} (${(data.scan_us / 1000).toFixed(2)} ms). ${data.error !== "ESP_OK" ? data.error : ""}`);
    const waiting = bodyJointNames.filter((_, id) => data.waiting_joints & (1 << id));
    text("servo-feedback-motion", data.stand_waiting ?
      `Stand ${(100 * data.stand_progress).toFixed(0)}%: holding a stage target while waiting for measured arrival${waiting.length ? ": " + waiting.join(", ") : "."}` :
      `Measured Stand ${data.stand_enabled ? "enabled" : "off"}.`);
    const rows = byId("servo-feedback-rows"); rows.replaceChildren();
    for (const joint of data.joints) {
      const channel = data.channels[joint.channel];
      const row = document.createElement("tr");
      const age = channel?.valid ? Math.max(0, (data.device_us - channel.sampled_us) / 1000) : null;
      const values = [bodyJointNames[joint.id], joint.channel,
        channel?.valid ? `${channel.raw}${Number.isFinite(channel.millivolts) ? ` / ${(channel.millivolts / 1000).toFixed(3)} V` : ""}` : "—",
        joint.command_us || "Output off", Number.isFinite(joint.measured_us) ?
          `${joint.measured_us.toFixed(1)}${Number.isFinite(joint.filtered_us) ? ` raw / ${joint.filtered_us.toFixed(1)} filtered` : ""}` : "Uncalibrated",
        Number.isFinite(joint.error_us) ? joint.error_us.toFixed(1) : "—",
        channel?.valid ? `${age.toFixed(0)} ms old · spread ${channel.spread}${channel.at_adc_rail ? " · ADC rail" : ""}${joint.in_calibrated_range === false ? " · extrapolated" : ""}` : "No sample"];
      for (const value of values) { const cell = document.createElement("td"); cell.textContent = String(value); row.appendChild(cell); }
      rows.appendChild(row);
    }
    text("servo-feedback-raw", data.channels.map(c => `${c.channel}: ${c.valid ? c.raw : "—"}`).join(" · "));
    const form = byId("servo-feedback-calibration"), joint = data.joints[Number(form.elements.joint.value)];
    if (joint) text("servo-feedback-points", joint.points.map((p, i) => `${["Low", "Middle", "High"][i]}: ${p ? `${p.pulse_us} µs → ADC ${p.raw}` : "not captured"}`).join(" · "));
    if (!servoFeedbackEdited) {
      const config = byId("servo-feedback-config");
      config.elements.enabled.checked = data.enabled;
      config.elements.stand_enabled.checked = data.stand_enabled;
      config.elements.tolerance_us.value = data.tolerance_us;
    }
  }

  async function readServoFeedback(operation = null, force = false) {
    if (!servoFeedbackSupported || servoFeedbackWriting || (servoFeedbackBusy && !operation)) return;
    const session = servoFeedbackSession, robot = selectedRobotId;
    const sequence = ++servoFeedbackRequest;
    const current = () => sequence === servoFeedbackRequest && session === servoFeedbackSession && robot === selectedRobotId;
    servoFeedbackBusy = true; servoFeedbackWriting = Boolean(operation);
    servoFeedbackReadAt = Date.now(); renderServoFeedback();
    try {
      const data = await request(maintenanceUrl("servo-feedback", robot), operation ?
        {method:"POST", body:JSON.stringify(operation)} : {});
      if (!current()) return;
      servoFeedbackData = data;
      if (force || operation?.op === "configure") servoFeedbackEdited = false;
      if (force || operation?.op === "map") {
        const form = byId("servo-feedback-calibration");
        form.elements.channel.value = data.joints[Number(form.elements.joint.value)].channel;
      }
      if (operation) text("servo-feedback-result", "Saved on robot. No movement command was sent.");
    } catch (error) {
      if (current()) {
        servoFeedbackData = null;
        byId("servo-feedback-rows").replaceChildren();
        text("servo-feedback-status", "Feedback read failed; previous measurements cleared.");
        text("servo-feedback-result", error.message);
        text("servo-feedback-motion", ""); text("servo-feedback-raw", "");
      }
    } finally { if (current()) {
      servoFeedbackBusy = false; servoFeedbackWriting = false; renderServoFeedback();
      renderCalibrationFeedback();
    } }
  }

  function updateServoFeedback(entry) {
    const supported = Boolean(entry?.connected && entry.model === "v2-12servo" &&
      entry.connection_state !== "stale" && (entry.features || []).includes("servo_feedback_v1"));
    const session = `${selectedRobotId}:${entry?.epoch}:${supported}`;
    if (session !== servoFeedbackSession) {
      servoFeedbackSession = session; servoFeedbackSupported = supported;
      servoFeedbackData = null; servoFeedbackBusy = false; servoFeedbackWriting = false; servoFeedbackEdited = false;
      servoFeedbackReadAt = 0;
      text("servo-feedback-result", "");
      if (supported) void readServoFeedback(null, true);
    }
    renderServoFeedback();
    const gyroGuideVisible=byId("gyro-joint-guide")?.closest?.('[data-workspace-panel]')?.hidden===false;
    if (supported && (!byId("servo-feedback-panel")?.hidden || gyroGuideVisible) && Date.now() - servoFeedbackReadAt > 500)
      void readServoFeedback();
  }

  function setupServoFeedback() {
    const form = byId("servo-feedback-calibration"), config = byId("servo-feedback-config");
    if (!form || !config) return;
    bodyJointNames.forEach((name, id) => form.elements.joint.add(new Option(name, String(id))));
    form.elements.joint.addEventListener("change", () => {
      const joint = servoFeedbackData?.joints[Number(form.elements.joint.value)];
      form.elements.channel.value = joint?.channel ?? "";
      renderServoFeedback();
    });
    config.addEventListener("input", () => { servoFeedbackEdited = true; });
    config.addEventListener("submit", event => {
      event.preventDefault();
      void readServoFeedback({op:"configure", enabled:config.elements.enabled.checked,
        stand_enabled:config.elements.stand_enabled.checked, tolerance_us:Number(config.elements.tolerance_us.value)});
    });
    byId("servo-feedback-read").addEventListener("click", () => readServoFeedback(null, true));
    byId("servo-feedback-map").addEventListener("click", () => {
      if (!form.elements.channel.reportValidity()) return;
      void readServoFeedback({op:"map", joint:Number(form.elements.joint.value), channel:Number(form.elements.channel.value)});
    });
    byId("servo-feedback-clear").addEventListener("click", () =>
      readServoFeedback({op:"clear", joint:Number(form.elements.joint.value)}));
    form.addEventListener("submit", event => {
      event.preventDefault();
      const joint = Number(form.elements.joint.value), data = servoFeedbackData;
      const channel = data?.channels[data.joints[joint].channel];
      if (!channel?.valid || !data.enabled) { text("servo-feedback-result", "Read a sample from the mapped input before capturing."); return; }
      void readServoFeedback({op:"capture", joint, point:Number(form.elements.point.value),
        pulse_us:Number(form.elements.pulse_us.value), raw:channel.raw, scan:data.scan, revision:data.revision});
    });
    renderServoFeedback();
  }

  function balanceFormEdited() {
    balanceEdited = byId("balance-enabled").value !== String(balanceData?.enabled) ||
      (balanceTuningSupported && balanceTuningKeys.some(key => Number(byId(`balance-${key}`).value) !== balanceData?.[key]));
    text("balance-status", balanceEdited ? "Unsaved change — Save on robot to apply it." :
      `${balanceData?.saved ? "Saved on robot" : "Robot default"}: ${balanceData?.enabled ? "On" : "Off"}.`);
    renderBalance();
  }

  function renderBalance() {
    byId("balance-enabled").disabled = !balanceSupported || !balanceData || balanceBusy;
    byId("balance-read").disabled = !balanceSupported || balanceBusy;
    byId("balance-save").disabled = !balanceSupported || !balanceData || balanceBusy ||
      (!balanceEdited && balanceData.saved && (!balanceTuningSupported || balanceData.tuning_saved));
    for (const key of balanceTuningKeys)
      byId(`balance-${key}`).disabled = !balanceTuningSupported || !balanceData || balanceBusy;
    byId("balance-defaults").disabled = !balanceTuningSupported || !balanceData || balanceBusy;
    byId("balance-reference").disabled = !balanceTuningSupported || !balanceData || balanceBusy || !balanceAttitude(balanceEntry);
    byId("balance-gyro-calibrate").disabled = !balanceSupported || balanceBusy ||
      !(balanceEntry?.features || []).includes("balance_feedback_v1");
  }

  function balanceAttitude(entry) {
    const imu = entry?.status?.imu, q = imu?.orientation_wxyz;
    if (entry?.connected === false || entry?.connection_state === "stale" || !imu?.available || !imu.fresh ||
        !Array.isArray(q) || q.length !== 4 || !q.every(Number.isFinite)) return null;
    // Use transport freshness too: an old sample may retain fresh=true at its source.
    const age = Date.now() - Date.parse(imu.received_at);
    if (!Number.isFinite(age) || age > 3000) return null;
    const norm = Math.hypot(...q);
    if (!norm) return null;
    const [w, x, y, z] = q.map(v => v / norm), deg = 180 / Math.PI;
    return {roll: Math.atan2(2*(w*x+y*z), 1-2*(x*x+y*y))*deg,
      pitch: -Math.asin(Math.max(-1, Math.min(1, 2*(w*y-z*x))))*deg, imu};
  }

  function renderBalanceFeedback() {
    const attitude = balanceAttitude(balanceEntry), imu = balanceEntry?.status?.imu;
    const b = balanceEntry?.status?.balance;
    const online = balanceSupported;
    if (online && b) text("balance-active", b.settled ?
      `Level reached — holding position; tilt monitoring only. Settle ${b.settle_deg}°, wake beyond ${b.wake_deg}°.` :
      b.active ? "Leveling is active." : "Leveling is inactive.");
    const angle = v => `${v >= 0 ? "+" : ""}${v.toFixed(2)}°`;
    text("balance-sensor", attitude ?
      `Live IMU · ${imu.calibration_applied ? "saved mounting/bias applied" : "sensor axes unverified"}` +
      (imu.startup || imu.gyro_recovery || imu.acceleration_recovery ? " · estimator recovering" : "") :
      "IMU unavailable or stale — no live angle.");
    text("balance-tilt", attitude ?
      `Measured: roll ${angle(attitude.roll)} (positive = left up) · pitch ${angle(attitude.pitch)} (positive = nose up).` : "");
    text("balance-error", attitude && balanceData && balanceTuningSupported ?
      `Offset from saved targets: roll ${angle(attitude.roll-balanceData.roll_deg)} · pitch ${angle(attitude.pitch-balanceData.pitch_deg)}. Zero is on target. Moving motions also include their programmed body angle.` : "");
    text("balance-correction", online && Number.isFinite(b?.roll_correction_rad) && Number.isFinite(b?.pitch_correction_rad) ?
      `Commanded correction: roll ${angle(b.roll_correction_rad*180/Math.PI)} · pitch ${angle(-b.pitch_correction_rad*180/Math.PI)}.` +
      (b.reduced ? " Correction cannot fully fit the current linkage or joint-speed setting." : "") : "No correction telemetry.");
    const tracking = online ? b?.joint_feedback : null;
    text("balance-joint-feedback", tracking ?
      b.settled ? "Measured-joint correction resting; the achieved servo targets are held." :
      tracking.active ? (tracking.mode === "actuator_tracking" ?
        "Measured actuator tracking active; accumulated leveling demand follows shaft progress." :
        `Standing position feedback active · tracking gain ${tracking.gain}×.`) +
        (Number.isFinite(tracking.tolerance_us) ? (tracking.mode === "actuator_tracking" ?
          ` Changes in tracking error within ±${tracking.tolerance_us} µs of this correction's starting offset are ignored.` :
          ` Errors within ±${tracking.tolerance_us} µs produce no added correction.`) : "") +
        (tracking.reduced ? " Additional correction reduced to fit the linkage or joint-speed setting." : "") :
      !tracking.available ? "Measured-joint feedback unavailable; gyro-only leveling remains available." :
        "Measured joints available; position tracking engages during active standing self-leveling." :
      "No measured-joint leveling telemetry.");
    const jointValues = values => Array.isArray(values) && values.length === 12 && values.every(Number.isFinite) ?
      ["Rear left", "Rear right", "Front left", "Front right"].map((name,i) =>
        `${name}: ${values.slice(i*3,i*3+3).map(angle).join(" / ")}`).join(" · ") : "";
    text("balance-joint-errors", tracking?.active ?
      `Target minus measured (shoulder / carrier / crank): ${jointValues(tracking.error_deg)}` : "");
    text("balance-joint-trims", tracking?.active ?
      tracking.mode === "actuator_tracking" && tracking.body_lag_rad?.length === 2 ?
        `Joint lag projected into body motion: roll ${angle(tracking.body_lag_rad[0] * 180 / Math.PI)}, pitch ${angle(-tracking.body_lag_rad[1] * 180 / Math.PI)}. No added servo overdrive.` :
        `Added position correction: ${jointValues(tracking.trim_deg)}` : "");
    const legs = online && b?.legs_valid && b.extension_mm?.length === 4 && b.joint_delta_deg?.length === 12;
    for (let l=0; l<4; l++) {
      const joint = (l < 2 ? l+2 : l-2)*3;
      const ext = b?.extension_mm?.[l];
      text(`balance-leg-${l}`, legs && Number.isFinite(ext) ? `${Math.abs(ext).toFixed(2)} mm ${ext < 0 ? "shorter" : "longer"}` : "—");
      for (const [name, offset] of [["carrier",1],["crank",2]]) {
        const v = b?.joint_delta_deg?.[joint+offset];
        text(`balance-${name}-${l}`, legs && Number.isFinite(v) ? angle(v) : "—");
      }
    }
    const c = b?.gyro_calibration;
    const supported = (balanceEntry?.features || []).includes("balance_feedback_v1");
    const vector = values => Array.isArray(values) && values.length === 3 && values.every(Number.isFinite) ?
      values.map(v => (v*180/Math.PI).toFixed(3)).join(", ") : "unavailable";
    text("balance-gyro-status", !supported ? "Firmware update required for gyro calibration and per-leg feedback." :
      !online ? "Robot disconnected; calibration status unavailable." :
      c?.phase === 1 ? `Sampling stationary gyro: ${c.samples}/${c.target}. Keep the robot still.` :
      c?.phase === 2 ? `Gyro bias saved and applied. Sensor X/Y/Z: ${vector(c.bias_rad_s)} °/s. Sample standard deviation: ${vector(c.deviation_rad_s)} °/s.` :
      c?.phase === 3 ? `Gyro calibration failed (error ${c.error}); previous active calibration retained.` :
      "Ready for a stationary gyro measurement.");
  }

  function captureBalanceReference() {
    const attitude = balanceAttitude(balanceEntry);
    if (!attitude || !balanceData || !balanceTuningSupported || balanceBusy) return;
    byId("balance-roll_deg").value = attitude.roll.toFixed(4);
    byId("balance-pitch_deg").value = attitude.pitch.toFixed(4);
    balanceFormEdited();
    text("balance-reference-status", "Current pose copied to the target fields. Save on robot to apply this reference; On/Off and response settings are unchanged.");
  }

  async function calibrateBalanceGyro() {
    const robotId = selectedRobotId, generation = balanceGeneration;
    const current = () => robotId === selectedRobotId && generation === balanceGeneration;
    balanceBusy = true; renderBalance();
    text("balance-gyro-status", "Requesting stationary gyro measurement…");
    try {
      await command("/api/balance", {op:"calibrate_gyro",robot_id:robotId}, "Stationary gyro measurement requested", current);
      if (current()) text("balance-gyro-status", "Sampling requested. Keep still; live feedback will report the saved result.");
    } catch(error) {
      if (current()) text("balance-gyro-status", error.message);
    } finally {
      if (current()) { balanceBusy=false; renderBalance(); }
    }
  }

  async function operateBalance(op) {
    if (!balanceSupported || balanceBusy) return;
    const tuning = {};
    if (op === "save" && balanceTuningSupported) {
      for (const key of balanceTuningKeys) {
        const input = byId(`balance-${key}`);
        if (!input.reportValidity()) return;
        tuning[key] = Number(input.value);
      }
    }
    const generation = balanceGeneration;
    const robotId = selectedRobotId;
    const current = () => generation === balanceGeneration && robotId === selectedRobotId;
    balanceBusy = true;
    renderBalance();
    text("balance-status", op === "save" ? "Saving self-leveling on robot…" : "Reading self-leveling from robot…");
    try {
      const response = await command("/api/balance", {op, robot_id: robotId,
        ...(op === "save" ? {enabled: byId("balance-enabled").value === "true", ...tuning} : {})},
        op === "save" ? "Self-leveling saved on robot" : "Self-leveling read from robot", current);
      if (!current()) return;
      const state = response.balance;
      if (!state || state.seq !== response.seq || typeof state.enabled !== "boolean" ||
          typeof state.saved !== "boolean" || typeof state.active !== "boolean")
        throw new Error("Invalid self-leveling readback; read from robot again.");
      if (balanceTuningSupported && (balanceTuningKeys.some(key => !Number.isFinite(state[key])) ||
          state.strength < 0 || state.damping < 0 || typeof state.tuning_saved !== "boolean"))
        throw new Error("Invalid response settings; read from robot again.");
      balanceData = state;
      if (balanceTuningSupported) {
        for (const key of balanceTuningKeys) byId(`balance-${key}`).value = String(state[key]);
        text("balance-tuning-status", state.tuning_saved ? "Response settings saved on robot." : "Using the original response defaults.");
      }
      balanceEdited = false;
      byId("balance-enabled").value = String(state.enabled);
      text("balance-status", `${state.saved ? "Saved on robot" : "Robot default"}: ${state.enabled ? "On" : "Off"}.`);
      text("balance-active", state.active ? "Leveling is active." : "Leveling is inactive.");
    } catch (error) {
      if (current()) text("balance-status", error.message);
    } finally {
      if (current()) { balanceBusy = false; renderBalanceFeedback(); renderBalance(); }
    }
  }

  function updateBalance(entry) {
    balanceEntry = entry;
    const p4 = entry?.model === "v2-12servo";
    const supported = Boolean(p4 && entry.connection_state !== "stale" && entry.connected !== false &&
      (entry.features || []).includes("balance_control_v1"));
    balanceTuningSupported = supported && (entry.features || []).includes("balance_tuning_v1");
    const session = entry ? `${selectedRobotId}:${entry.epoch}:${supported}:${balanceTuningSupported}` : null;
    byId("balance-controls").hidden = !p4;
    byId("balance-tuning-controls").hidden = !balanceTuningSupported;
    if (!balanceTuningSupported) text("balance-tuning-status", p4 ? "A firmware update enables response and target-angle settings." : "");
    balanceSupported = supported;
    if (session !== balanceSession) {
      balanceSession = session;
      balanceGeneration++;
      balanceData = null;
      balanceBusy = balanceEdited = false;
      byId("balance-enabled").value = "";
      for (const key of balanceTuningKeys) byId(`balance-${key}`).value = "";
      text("balance-reference-status", "");
      text("balance-active", "");
      if (supported) operateBalance("get");
      else text("balance-status", p4 ? "Connect with firmware supporting self-leveling control to change this setting." : "Connect a robot to read self-leveling.");
    }
    if (supported && typeof entry?.status?.balance?.active === "boolean") {
      text("balance-active", entry.status.balance.active ? "Leveling is active." : "Leveling is inactive.");
    }
    renderBalanceFeedback();
    renderBalance();
  }

  function renderMotionSpeed() {
    byId("joint-speed-limit").disabled = !jointSpeedSupported || !motionSpeedData || motionSpeedBusy;
    byId("joint-speed-save").disabled = !jointSpeedSupported || !motionSpeedData || motionSpeedBusy ||
      (!jointSpeedEdited && motionSpeedData.joint_speed_limit_saved);
    byId("motion-speed").disabled = !motionSpeedSupported || !motionSpeedData || motionSpeedBusy;
    byId("motion-speed-read").disabled = !motionSpeedSupported || motionSpeedBusy;
    byId("motion-speed-save").disabled = !motionSpeedSupported || !motionSpeedData || motionSpeedBusy ||
      (!motionSpeedEdited && motionSpeedData.saved);
  }

  async function operateMotionSpeed(op, setting = "rate") {
    if (!motionSpeedSupported || motionSpeedBusy) return;
    if (setting === "joint_speed_limit_deg_s" && !jointSpeedSupported) return;
    const input = byId(setting === "rate" ? "motion-speed" : "joint-speed-limit");
    if (op === "save" && !input.reportValidity()) return;
    const generation = motionSpeedGeneration;
    const robotId = selectedRobotId;
    const current = () => generation === motionSpeedGeneration && robotId === selectedRobotId;
    motionSpeedBusy = true;
    renderMotionSpeed();
    text("motion-speed-status", op === "save" ? "Saving motion speed on robot…" : "Reading motion speed from robot…");
    try {
      const response = await command("/api/motion-speed", {op, robot_id: robotId,
        ...(op === "save" ? {[setting]: Number(input.value)} : {})},
        op === "save" ? "Motion speed saved on robot" : "Motion speed read from robot", current);
      if (!current()) return;
      const state = response.motion_speed;
      if (!state || state.seq !== response.seq || !Number.isFinite(state.rate) ||
          state.rate <= 0 || typeof state.saved !== "boolean")
        throw new Error("Invalid motion speed readback; read from robot again.");
      if (jointSpeedSupported && (!Number.isFinite(state.joint_speed_limit_deg_s) ||
          state.joint_speed_limit_deg_s <= 0 || typeof state.joint_speed_limit_saved !== "boolean"))
        throw new Error("Invalid joint speed limit readback; read from robot again.");
      const keepRate = op === "save" && setting !== "rate" && motionSpeedEdited;
      const keepLimit = op === "save" && setting !== "joint_speed_limit_deg_s" && jointSpeedEdited;
      motionSpeedData = state;
      motionSpeedEdited = keepRate;
      jointSpeedEdited = keepLimit;
      if (!keepRate) byId("motion-speed").value = String(state.rate);
      if (jointSpeedSupported) {
        if (!keepLimit) byId("joint-speed-limit").value = String(state.joint_speed_limit_deg_s);
        text("joint-speed-status", keepLimit ? "Unsaved limit — Save limit on robot to apply it." :
          `${state.joint_speed_limit_saved ? "Saved on robot" : "Robot default"}: ${state.joint_speed_limit_deg_s} °/s.`);
      }
      text("motion-speed-status", keepRate ? "Unsaved speed — try a named motion, then Save on robot." :
        `${state.saved ? "Saved on robot" : "Robot default"}: ${state.rate}×. Adjust, try a named motion, then save to keep it after restart.`);
    } catch (error) {
      if (current()) {
        text("motion-speed-status", error.message);
        if (jointSpeedSupported) text("joint-speed-status", error.message);
      }
    } finally {
      if (current()) { motionSpeedBusy = false; renderMotionSpeed(); }
    }
  }

  function updateMotionSpeed(entry) {
    const p4 = entry?.model === "v2-12servo";
    const supported = Boolean(p4 && entry.connection_state !== "stale" && entry.connected !== false &&
      (entry.features || []).includes("motion_speed_v1"));
    jointSpeedSupported = supported && (entry.features || []).includes("joint_speed_limit_v1");
    const session = entry ? `${selectedRobotId}:${entry.epoch}:${supported}:${jointSpeedSupported}` : null;
    if (p4 && !jointSpeedSupported) text("joint-speed-status", "A firmware update is needed to enable the joint speed limit.");
    const cadence = entry?.status?.gait_cadence;
    text("run-cadence-status", cadence?.automatic_run ?
      `Commanded Run cadence: ${Number(cadence.cycles_s).toFixed(2)} / ${Number(cadence.requested_cycles_s).toFixed(2)} requested cycles/s · stride ${Number(cadence.stride_percent).toFixed(1)}% (requested ${Number(cadence.requested_stride_percent).toFixed(1)}%).` : "");
    const limited = entry?.status?.speed_limited;
    text("joint-speed-active", typeof limited === "boolean" ?
      (limited ? "Speed limit active — motion timing is slowed to meet the saved limit; the requested stride is preserved." : "Speed limit is not reducing the current motion.") : "");
    byId("motion-speed-controls").hidden = !p4;
    motionSpeedSupported = supported;
    if (session !== motionSpeedSession) {
      motionSpeedSession = session;
      motionSpeedGeneration++;
      motionSpeedData = null;
      motionSpeedBusy = motionSpeedEdited = jointSpeedEdited = false;
      byId("joint-speed-limit").value = "";
      byId("joint-speed-limit").setCustomValidity("");
      byId("motion-speed").value = "2";
      if (supported) operateMotionSpeed("get");
      else text("motion-speed-status", p4 ? "A firmware update is needed to enable Motion speed." : "Connect a robot to read its motion speed.");
    }
    renderMotionSpeed();
  }

  let idleRestSession = "", idleRestRequest = 0;
  function updateIdleRest(entry) {
    const supported = Boolean(entry?.connected && entry.features?.includes("idle_rest_v1"));
    byId("idle-rest-form").hidden = !supported;
    const session = supported ? `${selectedRobotId}:${entry.epoch}` : "";
    if (session !== idleRestSession) {
      idleRestSession = session;
      ++idleRestRequest;
      if (supported) readIdleRest();
    }
  }
  async function readIdleRest(save = false) {
    if (!idleRestSession) return;
    const input = byId("idle-rest-minutes");
    if (save && !input.reportValidity()) return;
    const seconds = Math.round(Number(input.value) * 60);
    if (save && (!Number.isFinite(seconds) || seconds < 0 || (Number(input.value) > 0 && seconds === 0) || seconds > 4294967295)) {
      text("idle-rest-status", "Enter at least one second (1/60 minute), or 0 to disable automatic rest.");
      return;
    }
    const session = idleRestSession, requestId = ++idleRestRequest;
    input.disabled = byId("idle-rest-save").disabled = byId("idle-rest-read").disabled = true;
    try {
      const data = await request(maintenanceUrl("idle-rest"), save ?
        {method:"POST", body:JSON.stringify({op:"configure", seconds})} : {});
      if (session !== idleRestSession || requestId !== idleRestRequest) return;
      input.value = String(data.seconds / 60);
      text("idle-rest-status", `${data.saved ? "Saved on robot" : "Robot default"}: ${data.seconds ? `lay down after ${data.seconds / 60} minutes of inactivity` : "automatic rest off"}.`);
    } catch (error) {
      if (session === idleRestSession && requestId === idleRestRequest)
        text("idle-rest-status", error.message);
    } finally {
      if (session === idleRestSession && requestId === idleRestRequest)
        input.disabled = byId("idle-rest-save").disabled = byId("idle-rest-read").disabled = false;
    }
  }
  function setupIdleRest() {
    byId("idle-rest-form").addEventListener("submit", event => {event.preventDefault(); readIdleRest(true);});
    byId("idle-rest-read").addEventListener("click", () => readIdleRest());
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
    byId("balance-reference").addEventListener("click", captureBalanceReference);
    byId("balance-gyro-calibrate").addEventListener("click", calibrateBalanceGyro);
    byId("balance-read").addEventListener("click", () => operateBalance("get"));
    byId("balance-save").addEventListener("click", () => operateBalance("save"));
    byId("balance-enabled").addEventListener("change", balanceFormEdited);
    for (const key of balanceTuningKeys) byId(`balance-${key}`).addEventListener("input", balanceFormEdited);
    byId("balance-defaults").addEventListener("click", () => {
      for (const key of balanceTuningKeys) byId(`balance-${key}`).value = key === "strength" || key === "damping" ? "1" : "0";
      balanceFormEdited();
    });
    byId("joint-speed-save").addEventListener("click", () => operateMotionSpeed("save", "joint_speed_limit_deg_s"));
    byId("joint-speed-limit").addEventListener("input", () => {
      const input = byId("joint-speed-limit");
      const value = Number(input.value);
      input.setCustomValidity(Number.isFinite(value) && value > 0 ? "" : "Enter a positive speed in degrees per second.");
      jointSpeedEdited = value !== motionSpeedData?.joint_speed_limit_deg_s;
      text("joint-speed-status", jointSpeedEdited ? "Unsaved limit — Save limit on robot to apply it." :
        `${motionSpeedData?.joint_speed_limit_saved ? "Saved on robot" : "Robot default"}: ${motionSpeedData?.joint_speed_limit_deg_s} °/s.`);
      renderMotionSpeed();
    });
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
      byId("walk-stride").disabled = !manual;
    });
    byId("walk-gait").addEventListener("change", updateSpeedRange);
    byId("walk-speed").addEventListener("input", updateSpeedRange);
    byId("walk-speed").addEventListener("change", () => applyWalking(false, true));
    byId("walk-direction").addEventListener("change", () => {
      if (!canSteer()) return;
      setSteeringVector(...directionVector(byId("walk-direction").value));
      return applyWalking(false, true);
    });
    for (const id of ["walk-forward", "walk-turn"]) {
      byId(id).addEventListener("input", () => {
        setSteeringVector(Number(byId("walk-forward").value), Number(byId("walk-turn").value));
        return applyWalking(false, true);
      });
    }
    document.querySelectorAll("[data-intent]").forEach((button) => {
      button.addEventListener("click", () => sendNamedMotion(button.dataset.intent, null, `${button.textContent.trim()} sent`));
    });
    document.querySelectorAll("[data-held-direction]").forEach((button) => {
      button.addEventListener("pointerdown", (event) => {
        event.preventDefault();
        button.setPointerCapture(event.pointerId);
        if (canSteer()) updateHeldSteering(`pointer:${event.pointerId}`, button.dataset.heldDirection);
        else beginHeldMotion(button.dataset.heldDirection, button);
      });
      const release = (event) => {
        event.preventDefault();
        if (canSteer() && heldSteeringInputs.has(`pointer:${event.pointerId}`)) updateHeldSteering(`pointer:${event.pointerId}`);
        else if (heldDirection === button.dataset.heldDirection) stopMotion("Movement released");
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
      if (canSteer()) updateHeldSteering(`key:${event.code}`, direction);
      else beginHeldMotion(direction);
    });
    window.addEventListener("keyup", (event) => {
      const direction = directionForKey(event.code);
      if (canSteer() && heldSteeringInputs.has(`key:${event.code}`)) {
        event.preventDefault();
        updateHeldSteering(`key:${event.code}`);
        return;
      }
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
    if (canSteer()) {
      // Keep the existing controller activation threshold; preserve both axes.
      const axis = (value) => Math.abs(value) > 0.55 ? Math.round(value * 100) : 0;
      const released = gamepad.buttons[1] && gamepad.buttons[1].pressed;
      const forward = released ? 0 : axis(-vertical), turn = released ? 0 : axis(-horizontal);
      const vector = forward || turn ? `${forward}:${turn}` : null;
      if (vector !== gamepadDirection) {
        gamepadDirection = vector;
        driveHeldVector(forward, turn);
      }
      if (gamepadSampling) gamepadTimer = window.setTimeout(pollGamepad, 50);
      return;
    }
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

  let gyroJointSession = null;
  let gyroJointTrial = null;
  let gyroJointResponse = null;
  function gyroJointKey(id) { return `ainekio-gyro-joint-v1:${selectedRobotId}:${id}`; }
  function gyroJointMapping(calibration) {
    return JSON.stringify(calibration.joints.map(({id,channel,home_us,home_cd,invert,us_per_degree}) =>
      ({id,channel,home_us,home_cd,invert,us_per_degree})));
  }
  function renderGyroJointGuide() {
    const panel=byId("gyro-joint-guide"); if (!panel) return;
    panel.hidden=!bodyCalibrationEnabled();
    const id=Number(byId("servo-form").elements.id.value);
    const session=`${selectedRobotId}:${calibrationEntry?.epoch}:${id}`;
    if (session!==gyroJointSession) {
      gyroJointSession=session; gyroJointTrial=null;
      gyroJointResponse=readLocal(gyroJointKey(id),null);
      text("gyro-joint-result","");
    }
    const a=balanceAttitude(calibrationEntry), shaft=servoFeedbackData?.joints?.find(j=>j.id===id);
    text("gyro-joint-live", a ? `Body: roll ${a.roll.toFixed(2)}° · pitch ${a.pitch.toFixed(2)}°.`+
      (Number.isFinite(shaft?.measured_us) ? ` ${bodyJointNames[id]} measured ${shaft.measured_us.toFixed(1)} µs; commanded ${shaft.command_us} µs.` : " Read servo feedback for measured shaft position.") : "No current body tilt reading.");
    text("gyro-joint-response", gyroJointResponse ?
      `Saved trial: ${gyroJointResponse.delta} µs command → roll ${gyroJointResponse.roll.toFixed(3)}°, pitch ${gyroJointResponse.pitch.toFixed(3)}°; measured shaft change ${gyroJointResponse.measured.toFixed(1)} µs.` : "No measured response for this joint. Test a step and capture its result.");
  }
  async function gyroJointSnapshot(robotId) {
    const [status,feedback,reply]=await Promise.all([
      request("/api/status"), request(`/api/robot/servo-feedback?robot_id=${encodeURIComponent(robotId)}`),
      request("/api/calibration/body",{method:"POST",body:JSON.stringify({robot_id:robotId,op:"get"})})]);
    const entry=status.robots?.[robotId], attitude=balanceAttitude(entry);
    if (!attitude) throw new Error("Current gyro reading unavailable; trial cannot be measured.");
    return {entry,attitude,feedback,calibration:reply.calibration};
  }
  async function gyroJointMove(snapshot,id,pulse,robotId) {
    if (snapshot.entry.mode==="calibrate") return request("/api/calibration/body",{
      method:"POST",body:JSON.stringify({robot_id:robotId,op:"move",id,pulse_us:pulse})});
    const targets=snapshot.calibration.joints.map(j=>{
      const p=j.id===id ? pulse : j.pulse_us;
      if (!p) throw new Error("A joint has no held target. Establish the starting pose before a Freestyle trial.");
      return Math.round(j.home_cd+100*(p-j.home_us)/j.us_per_degree*(j.invert?-1:1));
    });
    return request("/api/motion-plan",{method:"POST",body:JSON.stringify({robot_id:robotId,frames:[[20,targets]],end:"hold"})});
  }
  async function operateGyroJoint(action) {
    renderGyroJointGuide();
    const session=gyroJointSession, robotId=selectedRobotId;
    const id=Number(byId("servo-form").elements.id.value);
    try {
      const current=await gyroJointSnapshot(robotId);
      if (session!==gyroJointSession || robotId!==selectedRobotId) return;
      const joint=current.calibration.joints.find(j=>j.id===id);
      const measured=current.feedback.joints.find(j=>j.id===id)?.measured_us;
      if (action==="capture") {
        if (!gyroJointTrial) throw new Error("Test a step before capturing its result.");
        const trial=gyroJointTrial;
        if (gyroJointMapping(current.calibration)!==trial.mapping) throw new Error("Joint mapping changed during the trial; start a new trial.");
        const delta=joint.pulse_us-trial.pulse;
        if (!delta || !Number.isFinite(measured)) throw new Error("No commanded step or measured shaft position to compare.");
        gyroJointResponse={delta,roll:current.attitude.roll-trial.roll,pitch:current.attitude.pitch-trial.pitch,
          measured:measured-trial.measured,mapping:trial.mapping,pulse:trial.pulse,when:new Date().toISOString()};
        writeLocal(gyroJointKey(id),gyroJointResponse);
        text("gyro-joint-result","Response captured and saved in this browser. The joint is holding its trial target.");
      } else {
        let pulse;
        if (action==="restore") {
          if (!gyroJointTrial) throw new Error("No trial target to restore.");
          pulse=gyroJointTrial.pulse;
        } else {
          const step=Number(byId("gyro-joint-step").value);
          if (!Number.isInteger(step) || step<=0) throw new Error("Enter a positive whole-number trial step in µs.");
          let delta=action==="minus" ? -step : step;
          if (action==="correct") {
            const r=gyroJointResponse;
            if (!r || r.mapping!==gyroJointMapping(current.calibration)) throw new Error("Capture a response with the current joint mapping first.");
            const roll=Number(byId("gyro-joint-roll").value)-current.attitude.roll;
            const pitch=Number(byId("gyro-joint-pitch").value)-current.attitude.pitch;
            const sr=r.roll/r.delta, sp=r.pitch/r.delta, norm=sr*sr+sp*sp;
            if (!norm || !Number.isFinite(roll+pitch)) throw new Error("A measured response and numeric target are required.");
            delta=Math.round(Math.max(-step,Math.min(step,(roll*sr+pitch*sp)/norm)));
            if (!delta) { text("gyro-joint-result","The measured response predicts less than 1 µs of improvement from this joint."); return; }
          }
          pulse=joint.pulse_us+delta;
          gyroJointTrial={pulse:joint.pulse_us,roll:current.attitude.roll,pitch:current.attitude.pitch,
            measured,mapping:gyroJointMapping(current.calibration)};
        }
        const reply=await gyroJointMove(current,id,pulse,robotId);
        if (session!==gyroJointSession || robotId!==selectedRobotId) return;
        text("gyro-joint-result",`${bodyJointNames[id]}: ${pulse} µs requested (command ${reply.seq}). `+
          (action==="restore" ? "Original trial target restored; compare the live tilt." : "Capture the result after the body settles."));
      }
      if (session===gyroJointSession) renderGyroJointGuide();
    } catch(error) { if (session===gyroJointSession) text("gyro-joint-result",error.message); }
  }
  function setupGyroJointGuide() {
    for (const action of ["minus","plus","capture","restore","correct"])
      byId(`gyro-joint-${action}`).addEventListener("click",()=>void operateGyroJoint(action));
  }

  function renderCalibrationFeedback() {
    if (!byId("calibration-feedback-status") || !bodyCalibrationEnabled()) return;
    const id = Number(byId("servo-form").elements.id.value);
    const data = servoFeedbackSupported ? servoFeedbackData : null;
    const joint = data?.joints?.find(item => item.id === id);
    const channel = data?.channels?.find(item => item.channel === joint?.channel);
    const valid = data?.enabled && channel?.valid;
    const measured = valid && joint?.calibrated && Number.isFinite(joint.measured_us);
    const target = joint?.command_us;
    const values = {
      input: joint ? `C${joint.channel}` : "—",
      raw: valid ? `ADC ${channel.raw}${Number.isFinite(channel.millivolts) ? ` / ${(channel.millivolts / 1000).toFixed(3)} V` : ""}` : "—",
      position: measured ? `${joint.measured_us.toFixed(1)} µs equivalent` : "—",
      angle: measured && Number.isFinite(joint.model_deg) ? `${joint.model_deg.toFixed(2)}°` : "—",
      target: target ? `${target} µs` : "Outputs off / no target",
      error: measured && target ? `${(target - joint.measured_us).toFixed(1)} µs` : "—",
    };
    for (const [name, value] of Object.entries(values)) text(`calibration-feedback-${name}`, value);
    text("calibration-feedback-status", !data ? "No current feedback reading." : !data.enabled ? "Feedback reading is off." :
      !valid ? "No sample from this joint’s feedback input." :
      `Scan ${data.scan} · sample ${Math.max(0, (data.device_us - channel.sampled_us) / 1000).toFixed(0)} ms old · spread ${channel.spread} ADC counts.` +
      (!measured ? " Sensor calibration is needed to convert this reading to a Home position." : "") +
      (joint.in_calibrated_range === false ? " Position is extrapolated beyond the saved sensor points." : ""));
  }

  async function captureMeasuredHome() {
    const joint = selectedCalibrationJoint();
    if (!joint || !servoFeedbackSupported) {
      showCalibrationResult("Read this joint’s settings and connect its calibrated shaft feedback first.", true); return;
    }
    const robot = selectedRobotId, session = calibrationGeneration, feedbackSession = servoFeedbackSession;
    const form = byId("body-calibration-form");
    const fields = () => JSON.stringify(bodyCalibrationFields.map(name => form.elements[name].value)
      .concat(form.elements.invert.checked, calibrationHomeReference()));
    const before = fields();
    showCalibrationResult("Reading the selected joint’s fourth wire…");
    try {
      const data = await request(maintenanceUrl("servo-feedback", robot));
      if (robot !== selectedRobotId || session !== calibrationGeneration || feedbackSession !== servoFeedbackSession ||
          joint.id !== Number(byId("servo-form").elements.id.value)) return;
      if (before !== fields()) throw new Error("Joint fields changed while reading. Capture again to use the updated fields.");
      const feedback = data.joints?.find(item => item.id === joint.id);
      const channel = data.channels?.find(item => item.channel === feedback?.channel);
      if (!data.enabled || !channel?.valid || !feedback?.calibrated || !Number.isFinite(feedback.measured_us))
        throw new Error("No calibrated measured position is available for this joint. Home was not changed.");
      const pulse = Math.round(feedback.measured_us);
      // Establish the known physical pose. Do not infer its angle from the old
      // mapping: doing so preserves exactly the mounting error being calibrated.
      let angle;
      if (hasJointAngleMapping()) {
        angle = calibrationHomeReference() === "rearward" ? rearwardHomeDegrees[joint.id % 3] :
          form.elements.home_deg.value === "" ? NaN : Number(form.elements.home_deg.value);
        if (!Number.isFinite(angle)) throw new Error("Enter the model angle of your custom physical reference pose before capturing Home.");
      }
      form.elements.center.value = String(pulse);
      if (angle !== undefined) form.elements.home_deg.value = angle.toFixed(2);
      rememberCalibrationSettings();
      renderCalibration();
      showCalibrationResult(`Measured ${feedback.measured_us.toFixed(1)} µs (ADC ${channel.raw}, C${feedback.channel}) captured as Home ${pulse} µs. ` +
        (angle !== undefined ? `Physical reference ${angle.toFixed(2)}°; previous angle offset replaced. ` : "") +
        "Local edit only; Apply & save to robot to keep it. No movement command was sent." +
        (feedback.in_calibrated_range === false ? " This position is extrapolated beyond the saved sensor points." : ""));
    } catch (error) {
      if (robot === selectedRobotId && session === calibrationGeneration && joint.id === Number(byId("servo-form").elements.id.value))
        showCalibrationResult(error.message, true);
    }
  }

  function calibrationHomeReference() {
    const id = Number(byId("servo-form").elements.id.value);
    return calibrationDraft(id).homeReference || (id % 3 === 0 ? "custom" : "rearward");
  }

  function renderCalibrationHomeReference() {
    const id = Number(byId("servo-form").elements.id.value);
    const reference = calibrationHomeReference();
    byId("calibration-home-reference").value = reference;
    text("calibration-home-reference-help", reference === "rearward" ?
      `Capture assigns ${rearwardHomeDegrees[id % 3].toFixed(2)}° to this measured shaft position. ` +
      "Use matching rearward carrier/crank poses on all four legs; this is the existing assembly model reference. The crank reference is photo-estimated." :
      "Capture keeps the Model angle at Home entered above and assigns it to the measured shaft position. Enter the angle of your known physical pose.");
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
    const recommended = Number.isFinite(joint?.recommended_home_cd) && Number.isFinite(joint?.recommended_home_us);
    text("calibration-reference-help", recommended ?
      `Original matchmark reference: ${joint.recommended_home_us} µs at ${(joint.recommended_home_cd / 100).toFixed(2)}° model angle. This is not the rearward Home reference; choose that physical reference below when capturing Home.` : "");
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
        if (["rearward", "custom"].includes(stored.homeReference)) draft.homeReference = stored.homeReference;
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
    renderCalibrationFeedback();
    // Capturing a local reference is read-only and does not require releasing PWM.
    byId("calibration-use-position-button").disabled = !p4 || !online || !calibrationData || !servoFeedbackSupported || calibrationLoading;
    byId("calibration-home-reference").disabled = !p4 || !calibrationData || calibrationLoading;
    if (p4) renderCalibrationHomeReference();
    renderGyroJointGuide();
  }

  function bodyStorageEnabled() {
    return Boolean(calibrationEntry && calibrationEntry.model === "v2-12servo" &&
      (calibrationEntry.features || []).includes("storage_control_v1") &&
      (calibrationEntry.capabilities || {}).storage === true);
  }

  function renderStorage() {
    const online = calibrationEntry && calibrationEntry.connection_state !== "stale";
    const enabled = online && bodyStorageEnabled();
    const mounted = recordingData ? recordingData.mounted : storageData ? storageData.mounted : Boolean(calibrationEntry && calibrationEntry.status && calibrationEntry.status.sd);
    const busy = storageLoading || Boolean(storageData && storageData.busy);
    byId("storage-read-button").disabled = !enabled || storageLoading;
    byId("storage-retry-button").disabled = !enabled || busy;
    byId("storage-clear-button").disabled = !enabled || busy || !storageData || !storageData.available || !mounted;
    text("sd-state", mounted ? "Mounted" : "Unavailable");
    byId("sd-state").className = `state-chip ${mounted ? "active" : ""}`;
    text("storage-details", !online ? "Connect a robot to read storage status." : !enabled ?
      (calibrationEntry.capabilities && calibrationEntry.capabilities.reasons || {}).storage || "Storage controls are unavailable on this body." :
      storageLoading ? "Waiting for storage readback from the body…" : !storageData ? "Read storage status from the body." :
      `${mounted ? `${((recordingData?.free_bytes ?? storageData.free_bytes) / 1048576).toFixed(1)} MiB free of ${(storageData.total_bytes / 1048576).toFixed(1)} MiB` : "SD card is not mounted"}. ${storageData.dropped_records} dropped records.${storageData.busy ? " Storage is busy." : ""}${storageData.error ? ` ${storageData.error}` : ""}`);
    renderMaintenance();
  }

  function maintenanceUrl(operation, robot = selectedRobotId) {
    return `/api/robot/${operation}?${new URLSearchParams({robot_id: robot})}`;
  }

  function renderMaintenance() {
    if (!byId("recording-details")) return;
    const online = calibrationEntry?.model === "v2-12servo" && calibrationEntry.connection_state !== "stale";
    const available = online && !maintenanceBusy;
    byId("recording-start-button").disabled = !available || Boolean(recordingData?.recording);
    byId("recording-stop-button").disabled = !available || !recordingData?.recording;
    byId("recordings-refresh-button").disabled = !available;
    byId("recordings-select").disabled = !available || !recordingFiles.length;
    byId("recording-download-button").disabled = !available || !byId("recordings-select").value;
    byId("firmware-upload-button").disabled = !available || !byId("firmware-file").files?.length;
    byId("firmware-file").disabled = maintenanceBusy;
    byId("controller-logs-read-button").disabled = !available;
    byId("controller-logs-download-button").disabled = !available;
    const staged = ["staged", "next_boot"].includes(firmwareData?.state);
    byId("firmware-next-boot-button").disabled = !available || !staged;
    byId("firmware-restart-button").disabled = !available || !staged;
    if (!online) {
      text("recording-details", "Connect the robot to use its internal card.");
      text("firmware-details", "Connect the robot to manage its firmware.");
    } else {
      if (recordingData) text("recording-details", `${recordingData.recording ? "Recording" : "Stopped"} · ${recordingData.frames} frames · ${recordingData.dropped} dropped · ${recordingData.segments} completed segments · ${recordingData.overwrite_oldest ? `rolling overwrite (${recordingData.overwritten || 0} reused)` : "stops when full"} · ${(recordingData.free_bytes / 1048576).toFixed(1)} MiB free.${!recordingData.mounted ? " Card unavailable." : ""}${recordingData.error !== "ESP_OK" ? ` ${recordingData.error}` : ""}${recordingData.storage_error !== "ESP_OK" ? ` ${recordingData.storage_error}` : ""}`);
      if (firmwareData) text("firmware-details", `${firmwareData.version || "P4"} · ${firmwareData.state.replaceAll("_", " ")} · running ${firmwareData.running}${firmwareData.boot !== firmwareData.running ? ` · next boot ${firmwareData.boot}` : ""}${firmwareData.pending_verify ? " · awaiting startup validation" : ""}${firmwareData.error !== "ESP_OK" ? ` · ${firmwareData.error}` : ""}`);
    }
    if (online && maintenanceError) {
      text("recording-details", maintenanceError);
      text("firmware-details", maintenanceError);
    }
  }

  async function refreshMaintenance() {
    if (calibrationEntry?.model !== "v2-12servo" || calibrationEntry.connection_state === "stale" || maintenanceBusy || maintenanceReading) return;
    const robot = selectedRobotId;
    maintenanceReading = true;
    maintenanceReadAt = Date.now();
    try {
      const recording = await request(maintenanceUrl("recording", robot));
      const firmware = await request(maintenanceUrl("firmware", robot));
      if (robot !== selectedRobotId) return;
      recordingData = recording; firmwareData = firmware; maintenanceError = "";
    } catch (error) {
      if (robot === selectedRobotId) {
        maintenanceError = error.message;
      }
    } finally { maintenanceReading = false; renderStorage(); }
  }

  async function readControllerLogs(download = false) {
    const robot = selectedRobotId;
    text("controller-logs-output", "Reading controller logs…");
    try {
      const response = await fetch(maintenanceUrl("logs", robot));
      const output = await response.text();
      if (robot !== selectedRobotId) return;
      if (!response.ok) {
        let message = output; try { message = JSON.parse(output).error || output; } catch (_) {}
        throw new Error(message);
      }
      text("controller-logs-output", output);
      if (download) {
        const url = URL.createObjectURL(new Blob([output], {type: "text/plain"}));
        const link = document.createElement("a");
        link.href = url; link.download = `${robot}-logs.txt`;
        document.body.appendChild(link); link.click(); link.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    } catch (error) { if (robot === selectedRobotId) text("controller-logs-output", error.message); }
  }

  async function refreshRecordings() {
    const robot = selectedRobotId;
    try {
      text("recordings-details", "Reading recordings from the robot…");
      const result = await request(maintenanceUrl("recordings", robot));
      if (robot !== selectedRobotId) return;
      recordingFiles = result.files;
      const select = byId("recordings-select"), previous = select.value;
      select.replaceChildren();
      recordingFiles.forEach(file => select.add(new Option(`${file.name} · ${(file.bytes / 1048576).toFixed(2)} MiB${file.complete ? "" : " · unfinished"}`, file.name)));
      if (recordingFiles.some(file => file.name === previous)) select.value = previous;
      text("recordings-details", `${recordingFiles.length} recordings. Downloads go to this computer; files remain until reused by rolling recording.`);
    } catch (error) { if (robot === selectedRobotId) text("recordings-details", error.message); }
    finally { renderMaintenance(); }
  }

  async function operateMaintenance(operation, op) {
    const robot = selectedRobotId;
    maintenanceBusy = true; renderMaintenance();
    try {
      const result = await request(maintenanceUrl(operation, robot), {method: "POST", body: JSON.stringify({op})});
      if (robot !== selectedRobotId) return;
      if (operation === "recording") recordingData = result;
      else text("firmware-operation", op === "restart" ? "Update selected. Robot restarting; waiting for reconnection and validation." : "Update selected for the next boot. The robot has not restarted.");
    } catch (error) { if (robot === selectedRobotId) showResult(error.message, true); }
    finally {
      maintenanceBusy = false; renderMaintenance();
      if (robot === selectedRobotId) { await refreshMaintenance(); if (operation === "recording" && op === "stop") await refreshRecordings(); }
    }
  }

  async function uploadFirmware() {
    const file = byId("firmware-file").files[0], robot = selectedRobotId;
    if (!file || !robot) return;
    maintenanceBusy = true; renderMaintenance();
    const progress = byId("firmware-upload-progress");
    progress.hidden = false; progress.value = 0;
    text("firmware-operation", "Preparing upload: recording will finish and the robot will enter Doze.");
    try {
      await new Promise((resolve, reject) => {
        const upload = new XMLHttpRequest();
        upload.open("POST", maintenanceUrl("firmware", robot));
        upload.setRequestHeader("Content-Type", "application/octet-stream");
        upload.setRequestHeader("X-Ainekio-CSRF", csrfToken);
        upload.upload.onprogress = event => {
          if (robot !== selectedRobotId) return;
          if (event.lengthComputable) progress.value = 100 * event.loaded / event.total;
          text("firmware-operation", progress.value >= 100 ? "Transfer sent; waiting for the robot to finish writing and validate. Watch its screen." : `Uploading ${Math.floor(progress.value)}%…`);
        };
        upload.onload = () => {
          let result; try { result = JSON.parse(upload.responseText); } catch (_) { reject(new Error("Invalid upload response; refresh firmware status.")); return; }
          if (upload.status >= 200 && upload.status < 300) resolve(result);
          else reject(new Error(result.error || "Upload failed"));
        };
        upload.onerror = () => reject(new Error("Upload interrupted. Refresh firmware status before retrying."));
        upload.send(file);
      });
      if (robot === selectedRobotId) text("firmware-operation", "Firmware validated and staged. Choose next boot or activate and restart. The robot remains in Doze.");
    } catch (error) { if (robot === selectedRobotId) text("firmware-operation", error.message); }
    finally { maintenanceBusy = false; progress.hidden = true; renderMaintenance(); if (robot === selectedRobotId) { await refreshMaintenance(); await refreshRecordings(); } }
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
    byId("controller-logs-read-button").addEventListener("click", () => readControllerLogs());
    byId("controller-logs-download-button").addEventListener("click", () => readControllerLogs(true));
    byId("recording-start-button").addEventListener("click", () => operateMaintenance("recording", "start"));
    byId("recording-stop-button").addEventListener("click", () => operateMaintenance("recording", "stop"));
    byId("recordings-refresh-button").addEventListener("click", refreshRecordings);
    byId("recordings-select").addEventListener("change", renderMaintenance);
    byId("recording-download-button").addEventListener("click", () => {
      const name = byId("recordings-select").value;
      if (!name) return;
      const link = document.createElement("a");
      link.href = maintenanceUrl("recordings") + "&" + new URLSearchParams({name});
      link.download = name; document.body.append(link); link.click(); link.remove();
    });
    byId("firmware-file").addEventListener("change", renderMaintenance);
    byId("firmware-upload-button").addEventListener("click", uploadFirmware);
    byId("firmware-next-boot-button").addEventListener("click", () => operateMaintenance("firmware/activate", "next_boot"));
    byId("firmware-restart-button").addEventListener("click", () => operateMaintenance("firmware/activate", "restart"));
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
    byId("ground-calibration-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const operation = event.submitter?.value || "status";
      try {
        const post = (payload) => request("/api/camera/ground-calibration", { method: "POST", body: JSON.stringify({ robot_id: selectedRobotId, ...payload }) });
        const status = await post({ operation: "status" });
        if (operation === "status") { text("ground-calibration-status", JSON.stringify(status, null, 2)); return; }
        if (operation === "resetSamples") { text("ground-calibration-status", JSON.stringify(await post({ operation }), null, 2)); return; }
        const values = new FormData(form);
        const payload = { operation, frameId: status.frame?.frameId, columns: Number(values.get("columns")), rows: Number(values.get("rows")),
          squareMetres: Number(values.get("squareMetres")), geometryId: values.get("geometryId") };
        if (operation === "fit") payload.cameraToBody = JSON.parse(values.get("cameraToBody"));
        text("ground-calibration-status", JSON.stringify(await post(payload), null, 2));
      } catch (error) { text("ground-calibration-status", error.message); }
    });
    byId("camera-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const values = new FormData(form);
      const payload = { on: form.elements.on.checked, fps: Number(values.get("fps")), res: values.get("res") };
      if (!form.elements.snapshot_res.disabled) payload.snapshot_res = values.get("snapshot_res");
      if (!form.querySelector("fieldset[data-camera-controls]").disabled) {
        payload.exposure_us = Math.round(Number(values.get("exposure_ms")) * 1000);
        payload.gain_x16 = Math.round(Number(values.get("sensor_gain")) * 16);
        payload.jpeg_quality = Number(values.get("jpeg_quality"));
      }
      command("/api/camera", payload, "Camera request sent and settings saved");
    });
    Object.entries(audioForms).forEach(([kind, state]) => {
      byId(`${kind}-form`).addEventListener("input", () => {
        state.edited = true;
        state.pending = null;
        state.revision++;
        updateAudioOutputs();
      });
    });
    byId("speaker-form").addEventListener("submit", (event) => {
      event.preventDefault();
      submitAudioSettings("speaker", {volume_percent: Number(event.currentTarget.elements.volume_percent.value)});
    });
    byId("microphone-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const values = new FormData(form);
      const payload = { on: form.elements.on.checked, gate: values.get("gate") };
      if (!form.elements.gain_db.disabled) payload.gain_db = Number(values.get("gain_db"));
      submitAudioSettings("microphone", payload);
    });
    byId("wake-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const values = new FormData(form);
      const payload = { enabled: form.elements.enabled.checked, model: values.get("model") };
      if (!form.elements.sensitivity.disabled) payload.threshold = (100 - Number(values.get("sensitivity"))) / 100;
      submitAudioSettings("wake", payload);
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
    byId("body-calibration-form").addEventListener("input", (event) => {
      if (bodyCalibrationEnabled()) {
        if (event.target === byId("body-calibration-form").elements.home_deg) calibrationDraft().homeReference = "custom";
        rememberCalibrationSettings(); renderCalibration();
      }
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
    byId("calibration-use-position-button").addEventListener("click", () => void captureMeasuredHome());
    byId("calibration-home-reference").addEventListener("change", () => {
      calibrationDraft().homeReference = byId("calibration-home-reference").value;
      persistCalibrationWorkspace();
      renderCalibrationHomeReference();
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

  function setupConnections() {
    const saved = readLocal("ainekio-connections-v1", {});
    const addresses = { local: saved.local || "", lan: saved.lan || "", cloudflare: saved.cloudflare || "" };
    const route = byId("body-connection-route");
    const address = byId("body-connection-address");
    const desktop = byId("desktop-connection-address");
    const result = byId("connections-result");
    route.value = Object.hasOwn(addresses, saved.route) ? saved.route : "local";
    address.value = addresses[route.value];
    desktop.value = saved.desktop || "";
    text("body-current-address", window.location.origin);
    let previousRoute = route.value;
    route.addEventListener("change", () => {
      addresses[previousRoute] = address.value;
      address.value = addresses[route.value];
      previousRoute = route.value;
    });
    function httpAddress(value) {
      const url = new URL(value.trim());
      if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) {
        throw new Error("Enter an HTTP or HTTPS address without embedded credentials.");
      }
      return url;
    }
    function saveAndOpen(kind) {
      result.classList.remove("form-error");
      try {
        const target = httpAddress(kind === "body" ? address.value : desktop.value);
        if (kind === "body") addresses[route.value] = target.href;
        else desktop.value = target.origin;
        // Persist addresses only, never authentication or live connection state.
        localStorage.setItem("ainekio-connections-v1", JSON.stringify({
          ...addresses, route: route.value, desktop: desktop.value,
        }));
        const href = kind === "body" ? target.href : new URL("/monitor#body-connection", target).href;
        window.open(href, "_blank", "noopener,noreferrer");
        result.textContent = "Address saved. Requested a new tab; allow pop-ups for this site if it did not open. Sign in at the destination as needed.";
      } catch (error) {
        result.textContent = error.message;
        result.classList.add("form-error");
      }
    }
    byId("body-connection-form").addEventListener("submit", (event) => { event.preventDefault(); saveAndOpen("body"); });
    byId("desktop-connection-form").addEventListener("submit", (event) => { event.preventDefault(); saveAndOpen("desktop"); });
  }

  function setupNavigation() {
    const sidebar = byId("tool-sidebar");
    const workspace = byId("tool-workspace");
    const toggle = byId("tools-toggle");
    const buttons = Array.from(sidebar.querySelectorAll("[data-workspace]"));
    const panels = Array.from(workspace.querySelectorAll("[data-workspace-panel]"));
    const groups = Array.from(sidebar.querySelectorAll("[data-navigation-group]"));
    const scrollPositions = new Map();
    let current = null;
    const compact = window.matchMedia("(max-width: 1050px)");
    let expanded = compact.matches ? false : readLocal("ainekio-tools-expanded", true);
    const settingsPages = ["connections", "network", "pairing", "account"];

    function showSidebar(open, remember = true) {
      expanded = open;
      sidebar.hidden = !open;
      document.body.classList.toggle("tools-collapsed", !open);
      toggle.setAttribute("aria-expanded", String(open));
      if (remember && !compact.matches) writeLocal("ainekio-tools-expanded", open);
    }

    function showWorkspace(name, focus = true) {
      const button = buttons.find(item => item.dataset.workspace === name) || buttons[0];
      name = button.dataset.workspace;
      if (current) scrollPositions.set(current, workspace.scrollTop);
      current = name;
      panels.forEach(panel => {
        panel.hidden = !panel.dataset.workspacePanel.split(" ").includes(name);
      });
      buttons.forEach(item => {
        if (item === button) item.setAttribute("aria-current", "page");
        else item.removeAttribute("aria-current");
      });
      button.closest("details").open = true;
      byId("settings-button").setAttribute("aria-expanded", String(settingsPages.includes(name)));
      if (settingsPages.includes(name) && selectedRobotId) byId("token-robot-id").value = selectedRobotId;
      writeLocal("ainekio-workspace", name);
      workspace.scrollTop = scrollPositions.get(name) || 0;
      if (focus) {
        const panel = panels.find(item => !item.hidden && item.dataset.workspacePanel === name);
        const heading = panel.querySelector("h2, h3");
        heading.tabIndex = -1;
        heading.focus({ preventScroll: true });
      }
      if (compact.matches) showSidebar(false, false);
    }

    groups.forEach(group => {
      group.open = readLocal(`ainekio-tools-group-${group.dataset.navigationGroup}`, group.open);
      group.addEventListener("toggle", () => writeLocal(`ainekio-tools-group-${group.dataset.navigationGroup}`, group.open));
    });
    buttons.forEach(button => button.addEventListener("click", () => showWorkspace(button.dataset.workspace)));
    toggle.addEventListener("click", () => showSidebar(!expanded));
    byId("settings-button").addEventListener("click", () => showWorkspace("connections"));
    byId("settings-close-button").addEventListener("click", () => {
      byId("password-form").reset();
      byId("password-result").hidden = true;
      showWorkspace("overview");
    });
    // Navigation keys belong to these UI controls, not to the drive shortcuts.
    // No robot action is sent when selecting, opening or closing a tool.
    [sidebar, toggle, byId("settings-button"), byId("settings-close-button")].forEach(element => {
      for (const type of ["keydown", "keyup"]) element.addEventListener(type, event => {
        if (event.code === "Space" || (type === "keydown" && ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.code))) event.stopPropagation();
        if (event.code === "Escape" && expanded) { showSidebar(false); toggle.focus(); }
      });
    });
    compact.addEventListener("change", () => showSidebar(compact.matches ? false : readLocal("ainekio-tools-expanded", true), false));
    showSidebar(expanded, false);
    showWorkspace(readLocal("ainekio-workspace", "overview"), false);
  }

  function setupSecurity() {
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

  function renderHostNetwork(network) {
    if (!network || hostNetworkBusy) return;
    byId("host-hotspot-toggle").checked = network.hotspot;
    text("host-network-state", network.hotspot ? "Robot hotspot enabled." : "Using the existing Wi-Fi network.");
  }

  function setupHostNetwork() {
    const toggle = byId("host-hotspot-toggle");
    const result = byId("host-network-result");
    toggle.addEventListener("change", async () => {
      hostNetworkBusy = true;
      toggle.disabled = true;
      result.hidden = false;
      result.classList.remove("form-error");
      result.textContent = "Switching connection mode…";
      try {
        const response = await request("/api/settings/network", {
          method: "POST", body: JSON.stringify({hotspot: toggle.checked}),
        });
        hostNetworkBusy = false;
        renderHostNetwork(response.host_network);
        result.textContent = "Connection mode applied and saved.";
      } catch (error) {
        result.textContent = error.message;
        result.classList.add("form-error");
      } finally {
        hostNetworkBusy = false;
        statusGeneration++;
        toggle.disabled = false;
        await refreshStatus();
      }
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
    if (selectedRobotId !== previous) { resetCameraView(); resetWalking(); updateMotionSpeed(null); updateBalance(null); }
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
    text("robot-gateway-help", (entry?.features || []).includes("gateway_switching_v1") ?
      "Save another computer with the same Wi-Fi name, or a separate hotspot. Use ws:// for your private LAN and wss:// for a configured tunnel. The robot keeps its connected computer until that connection ends, then tries other saved addresses and local discovery. Stop Body Control on the current computer to switch." :
      "This firmware supports one computer per Wi-Fi network. Update P4 firmware for automatic computer switching and local discovery.");
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
      text("robot-settings-state", `Wi-Fi slot: ${robotSettings.active_index < 0 ? "none" : robotSettings.active_index + 1}. Connected to this Body Control server. ` +
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
      if (window.confirm("Remove this saved connection? It remains active until you restart the robot.")) robotSettingsRequest("remove", {index});
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

  function renderBodyEvents(payload, entry) {
    const form = byId("body-events-form");
    if (bodyEventsRobot !== selectedRobotId) {
      bodyEventsRobot = selectedRobotId;
      bodyEventsEdited = false;
    }
    const settings = payload.body_events?.robots?.[selectedRobotId] || payload.body_events?.defaults;
    if (settings && !bodyEventsEdited && !bodyEventsSaving) {
      for (const [key, value] of Object.entries(settings)) {
        const input = form.elements.namedItem(key);
        if (!input) continue;
        if (input.type === "checkbox") input.checked = value;
        else input.value = value;
      }
    }
    for (const input of form.elements) input.disabled = !selectedRobotId || bodyEventsSaving;
    byId("body-events-good-morning").disabled = !entry || entry.connection_state !== "online" || bodyEventsSaving;
    const imu = entry?.status?.imu;
    text("body-events-imu", imu ? JSON.stringify({
      connected: entry.connection_state === "online", frame: imu.frame,
      available: imu.available, freshAtSource: imu.fresh, sampleTimeUs: imu.timestamp_us,
      receivedAt: imu.received_at, calibrationApplied: imu.calibration_applied,
      angularRateRadS: imu.angular_rate_rad_s, accelerationMS2: imu.acceleration_m_s2,
      orientationWXYZ: imu.orientation_wxyz, startup: imu.startup,
    }, null, 2) : "No IMU measurement received. V2 needs firmware with IMU reporting.");
    text("body-events-recent", JSON.stringify((payload.body_events?.recent || [])
      .filter(event => event.robot_id === selectedRobotId).map(event => ({
        id: event.event_id, kind: event.data.kind, reason: event.data.reason,
        tiltDegrees: event.data.tilt_degrees, accelerationChangeG: event.data.acceleration_change_g,
        rotationDps: event.data.rotation_dps,
      })), null, 2));
  }

  function renderStatus(payload) {
    const recognition = payload.recognition;
    visionOperations = new Set(recognition?.visionOperations || []);
    byId("vision-target-search").disabled = !visionOperations.has("search") || visionTargetBusy;
    byId("vision-target-release").disabled = !visionOperations.has("release") || visionTargetBusy;
    if (!visionTargetBusy) {
      const target = recognition?.visionTarget;
      text("vision-target-status", target ? `Looking for: ${target.classes.join(", ")}` :
        visionOperations.has("select") || visionOperations.has("search") ? "No selected target." : "Target search needs a prompted YOLOE model.");
    }
    const recognitionStatus = byId("camera-recognition-status");
    byId("recognition-enabled").disabled = !recognition?.configured || recognitionSaving;
    byId("recognition-form").querySelector("button").disabled = !recognition?.configured || recognitionSaving;
    if (!recognitionEdited && !recognitionSaving) byId("recognition-enabled").checked = Boolean(recognition?.enabled);
    if (!recognition?.configured) {
      recognitionStatus.textContent = "Recognition: not configured";
    } else if (!recognition.enabled) {
      recognitionStatus.textContent = "Recognition: off · saved";
    } else {
      const age = recognition.observationAgeMs;
      const freshness = age == null ? "waiting for a usable frame" : age <= recognition.maxAgeMs ? "fresh" : "expired";
      recognitionStatus.textContent = `Recognition: ${freshness} · ${Number(recognition.freshFps).toFixed(1)} results/s` +
        (age == null ? "" : ` · observation age ${Math.round(age)} ms`) +
        ` · ${recognition.receivedFrames} frames received · ${recognition.errors} errors`;
    }
    const robots = payload.robots || {};
    const robotIds = Object.keys(robots).sort();
    updateRobotSelect(robotIds);
    const entry = selectedRobotId ? robots[selectedRobotId] : null;
    renderBodyEvents(payload, entry);
    renderPeople(payload.person_recognition, recognition?.observation);
    if (cameraSettingsRobotId !== selectedRobotId) {
      const saved = payload.camera_settings?.[selectedRobotId];
      if (saved) {
        const form = byId("camera-form");
        form.elements.on.checked = saved.on;
        form.elements.fps.value = saved.fps;
        form.elements.res.value = saved.resolution;
        if (saved.snapshot_resolution) form.elements.snapshot_res.value = saved.snapshot_resolution;
        form.elements.exposure_ms.value = (saved.exposure_us || 0) / 1000;
        form.elements.sensor_gain.value = (saved.gain_x16 || 0) / 16;
        form.elements.jpeg_quality.value = saved.jpeg_quality || 75;
      }
      cameraSettingsRobotId = selectedRobotId;
    }
    if (Date.now() - behaviorReadAt > 5000) void refreshBehaviorControl();
    const status = entry && entry.status;
    const legacyBody = entry && (!entry.model || entry.model === "v1-8servo");
    availableBodyCommands = !entry || entry.connection_state === "stale" ? [] :
      Array.isArray(entry.robot_commands) ? entry.robot_commands :
        legacyBody && (!entry.capabilities || entry.capabilities.motion === true) ? null : [];
    renderMotionCatalog(entry, legacyBody);
    updateIdleRest(entry);
    updateMotionSpeed(entry);
    updateBalance(entry);
    updateServoFeedback(entry);
    document.querySelectorAll("[data-intent], [data-emote], [data-held-direction]").forEach((button) => {
      const name = button.dataset.intent || button.dataset.emote || directionCommands[button.dataset.heldDirection];
      button.disabled = !bodyCommandAvailable(name) ||
        (availableBodyCommands === null && button.hasAttribute("data-requires-declaration"));
    });
    directionalWalking = Boolean(entry && entry.model === "v2-12servo" && (entry.features || []).includes("walk_controls_v2"));
    steeringSupported = Boolean(directionalWalking && (entry.features || []).includes("walk_steering_v1"));
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
    if (maintenanceRobot !== selectedRobotId) {
      maintenanceRobot = selectedRobotId; maintenanceReadAt = 0; maintenanceError = "";
      recordingData = null; firmwareData = null; recordingFiles = [];
      byId("recordings-select").replaceChildren();
      text("recordings-details", ""); text("firmware-operation", "");
      text("controller-logs-output", "Read logs from the selected robot.");
    }
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
    if (entry?.model === "v2-12servo" && Date.now() - maintenanceReadAt >= 5000) refreshMaintenance();
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
    renderFaceAvailability(entry, capability("display"));
    const cameraProfiles = Boolean(entry && (entry.features || []).includes("camera_profiles_v1"));
    document.querySelector("[data-camera-profiles]").hidden = !cameraProfiles;
    byId("camera-form").elements.snapshot_res.disabled = !cameraProfiles || !capability("camera");
    const adaptiveCamera = Boolean(entry && (entry.features || []).includes("camera_adaptive_v1"));
    const cameraControls = Boolean(entry && (entry.features || []).includes("camera_controls_v1"));
    document.querySelectorAll("[data-camera-controls]").forEach(control => {
      control.hidden = !cameraControls;
      control.disabled = !cameraControls || !capability("camera");
    });
    document.querySelectorAll("[data-camera-adaptive]").forEach((option) => {
      option.hidden = !adaptiveCamera;
      option.disabled = !adaptiveCamera;
    });
    const cameraSession = entry ? `${selectedRobotId}:${entry.epoch}:${adaptiveCamera}` : null;
    if (cameraSession !== cameraProfileSession) {
      byId("camera-form").elements.snapshot_res.value = payload.camera_settings?.[selectedRobotId]?.snapshot_resolution || (adaptiveCamera ? "AUTO" : "VGA");
      cameraProfileSession = cameraSession;
    }
    byId("camera-adaptive-help").hidden = !adaptiveCamera;
    const capture = status && status.camera_capture;
    text("camera-capture-status", capture ?
      `Last capture: ${capture.width} × ${capture.height}, ${(capture.exposure_us / 1000).toFixed(1)} ms exposure, ISO ≈${Math.round(capture.gain_x16 * 100 / 16)} (OV5647 scale; ${(capture.gain_x16 / 16).toFixed(1)}× gain).` +
      (adaptiveCamera && !cameraControls ? " Exposure and ISO automatic." : "") +
      (capture.settle_ms ? ` ${capture.settled ? "Exposure settled" : "Exposure still adjusting"} after ${(capture.settle_ms / 1000).toFixed(1)} s.` : "") : "");
    const connection = byId("connection-state");
    const connectionState = entry ? entry.connection_state || "online" : "offline";
    const connectionLabel = connectionState === "stale" ? "Stale" : entry ? "Online" : "Offline";
    const connectionSsid = entry && entry.connection_ssid;
    connection.textContent = connectionSsid ? `${connectionLabel} · ${connectionSsid}` : connectionLabel;
    connection.title = connectionSsid ? `Robot connection through ${connectionSsid}` : "";
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
    if (caps) byId("camera-form").elements.fps.max = caps.camera_max_fps;
    text("status-caps", caps ? `${entry && entry.profile || payload.profile}: ${caps.camera_max_fps} fps` : "--");
    text("status-camera-drops", status ? status.cam_drops : "--");
    text("status-audio-faults", status ? `${status.mic_drops} / ${status.spk_underruns}` : "--");
    const wakeReady = Boolean(status && status.wake_ready);
    const wakeEnabled = Boolean(status && status.wake_enabled);
    const wakeModel = status && status.wake_model ? status.wake_model : "ainekio";
    text("status-wake", status ? `${wakeEnabled ? "On" : "Off"} / ${wakeModel} / ${wakeReady ? "Ready" : "Model unavailable"}` : "--");
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
    renderAudioInput(entry, online, status);

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
        if (generation === statusGeneration) {
          renderStatus(payload);
          renderHostNetwork(payload.host_network);
        }
      } catch (error) {
        if (generation === statusGeneration) showResult(error.message, true);
      } finally { statusRequest = null; }
    })();
    return statusRequest;
  }

  function setupSpeechOutput() {
    const form = byId("speech-output-form");
    const select = byId("speech-output");
    const button = form.querySelector("button");
    let edited = false;
    let saving = false;
    let reading = false;
    let revision = 0;
    function render(settings) {
      select.value = settings.playbackTarget;
      select.disabled = false;
      button.disabled = false;
      const destination = settings.playbackTarget === "robot" ? "Robot speaker" : "Body Control computer";
      text("speech-output-state", `Saved: ${destination}. Select Body Control in MetaHuman to send speech here.`);
    }
    async function refresh() {
      if (saving || reading || edited) return;
      reading = true;
      const currentRevision = revision;
      try {
        const settings = await request("/api/speech-output");
        if (currentRevision === revision) render(settings);
      } catch (error) {
        if (currentRevision === revision) text("speech-output-state", error.message);
      } finally { reading = false; }
    }
    select.addEventListener("change", () => {
      edited = true;
      revision++;
      text("speech-output-state", "Unsaved speech output selection.");
    });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (saving) return;
      saving = true;
      revision++;
      select.disabled = true;
      button.disabled = true;
      try {
        const settings = await request("/api/speech-output", {
          method: "POST", body: JSON.stringify({playbackTarget: select.value}),
        });
        edited = false;
        render(settings);
      } catch (error) { text("speech-output-state", error.message); }
      finally { saving = false; select.disabled = false; button.disabled = false; }
    });
    void refresh();
    const timer = window.setInterval(refresh, 5000);
    window.addEventListener("beforeunload", () => window.clearInterval(timer));
  }

  function renderBehaviorControl(settings) {
    byId("behavior-control-enabled").checked = settings.enabled;
    byId("behavior-control-enabled").disabled = false;
    byId("behavior-control-form").querySelector("button").disabled = false;
    const pending = settings.unresolvedActions?.length || 0;
    const tasks = (settings.executions || []).filter(task => ["running", "waiting"].includes(task.status));
    text("behavior-control-status", `MetaHuman connected · ${settings.enabled ? "On" : "Off"} · saved` +
      (pending ? ` · ${pending} command outcomes unresolved` : "") +
      (tasks.length ? ` · ${tasks.map(task => task.objective).join("; ")}` : " · no active robot task"));
  }

  async function refreshBehaviorControl() {
    if (behaviorBusy || behaviorEdited) return;
    behaviorBusy = true;
    behaviorReadAt = Date.now();
    const revision = behaviorRevision;
    try {
      const settings = await request("/api/behavior-control", {method: "POST", body: "{}"});
      if (revision === behaviorRevision) renderBehaviorControl(settings);
    } catch (error) {
      if (revision === behaviorRevision) {
        text("behavior-control-status", `MetaHuman control unavailable: ${error.message}`);
        byId("behavior-control-enabled").disabled = true;
        byId("behavior-control-form").querySelector("button").disabled = true;
      }
    } finally { behaviorBusy = false; }
  }

  let personEnrollmentBusy = false;
  let enrolledPeopleSignature = "";

  function renderPeople(status, observation) {
    const configured = status?.configured === true;
    byId("person-enrollment-form").querySelector("button").disabled = !configured || personEnrollmentBusy;
    text("person-recognition-status", configured ? "Local face recognition ready" : "Named-person models are not configured on this host.");
    const people = status?.people || [];
    const signature = JSON.stringify(people);
    if (signature !== enrolledPeopleSignature) {
      enrolledPeopleSignature = signature;
      const list = byId("enrolled-people");
      list.replaceChildren();
      for (const person of people) {
        const item = document.createElement("li");
        item.append(document.createTextNode(`${person.name} · ${person.samples}/4 samples `));
        const forget = document.createElement("button");
        forget.type = "button";
        forget.textContent = "Forget";
        forget.addEventListener("click", async () => {
          if (!window.confirm(`Delete saved face features for ${person.name}?`)) return;
          forget.disabled = true;
          try {
            await request("/api/people/forget", {method: "POST", body: JSON.stringify({personId: person.personId})});
            text("person-enrollment-result", "Person forgotten.");
          } catch (error) { text("person-enrollment-result", error.message); }
          finally { forget.disabled = false; void refreshStatus(); }
        });
        item.append(forget);
        list.append(item);
      }
    }
    if (!observation || observation.robotId !== selectedRobotId) {
      text("visible-people", "No fresh person observations.");
      return;
    }
    const visible = observation.objects.filter(item => item.label === "person").map(item => {
      const identity = item.identity;
      return !identity || identity.state === "unknown" ? "Unknown person" :
        `${identity.name} · ${identity.state === "face_match" ? "face match" : `tracked, face last seen ${Math.round(identity.faceAgeMs)} ms ago`}`;
    });
    text("visible-people", `Frame ${observation.frameCounter} · ${Math.round(observation.ageMs)} ms old: ${visible.join("; ") || "No people detected"}`);
  }

  function setupSensingControls() {
    byId("vision-target-form").addEventListener("submit", event => {
      event.preventDefault();
      const labels = byId("vision-target-text").value.split(",").map(value => value.trim()).filter(Boolean);
      if (labels.length) void configureVisionTarget({ operation: "search", labels });
    });
    byId("vision-target-release").addEventListener("click", () => configureVisionTarget({ operation: "release" }));
    byId("camera-show-detections").addEventListener("change", () => {
      resetCameraView();
      text("camera-detection-status", byId("camera-show-detections").checked ? "Waiting for recognition." : "Live camera view.");
    });
    byId("person-enrollment-form").addEventListener("submit", async event => {
      event.preventDefault();
      if (personEnrollmentBusy) return;
      const form = event.currentTarget;
      const file = form.elements.photo.files[0];
      if (!file || file.size > 256 * 1024) { text("person-enrollment-result", "Choose a JPEG photo under 256 KB."); return; }
      personEnrollmentBusy = true;
      form.querySelector("button").disabled = true;
      text("person-enrollment-result", "Processing face on the Body Control host…");
      try {
        const data = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result).split(",")[1]);
          reader.onerror = () => reject(new Error("Cannot read this photo"));
          reader.readAsDataURL(file);
        });
        await request("/api/people/enroll", {method: "POST", body: JSON.stringify({name: form.elements.person_name.value, jpeg: data})});
        form.elements.photo.value = "";
        text("person-enrollment-result", "Face sample saved. Add another angle, or view recognition when the camera is connected.");
      } catch (error) { text("person-enrollment-result", error.message); }
      finally { personEnrollmentBusy = false; void refreshStatus(); }
    });
    byId("body-events-form").addEventListener("input", () => {
      bodyEventsEdited = true;
      text("body-events-result", "Unsaved body event settings.");
    });
    byId("body-events-form").addEventListener("submit", async event => {
      event.preventDefault();
      if (!selectedRobotId || bodyEventsSaving) return;
      const robotId = selectedRobotId;
      const settings = {};
      for (const input of event.currentTarget.elements) {
        if (input.name) settings[input.name] = input.type === "checkbox" ? input.checked : Number(input.value);
      }
      bodyEventsSaving = true;
      try {
        await request("/api/body-events", {method: "POST", body: JSON.stringify({robot_id: robotId, settings})});
        if (robotId === selectedRobotId) {
          bodyEventsEdited = false;
          text("body-events-result", "Settings saved and applied to Body Control.");
        }
      } catch (error) { text("body-events-result", error.message); }
      finally { bodyEventsSaving = false; void refreshStatus(); }
    });
    byId("body-events-good-morning").addEventListener("click", async () => {
      try {
        const result = await request("/api/body-events/good-morning", {
          method: "POST", body: JSON.stringify(withRobot()),
        });
        text("body-events-result", result.submitted ? "Good-morning event reported by Body Control." : result.reason);
      } catch (error) { text("body-events-result", error.message); }
    });
    byId("recognition-enabled").addEventListener("change", () => { recognitionEdited = true; });
    byId("recognition-form").addEventListener("submit", async event => {
      event.preventDefault();
      if (recognitionSaving) return;
      recognitionSaving = true;
      const enabled = byId("recognition-enabled").checked;
      try {
        await request("/api/recognition", {method: "POST", body: JSON.stringify({enabled})});
        recognitionEdited = false;
        showResult(`Recognition ${enabled ? "on" : "off"}; saved`);
      } catch (error) { showResult(error.message, true); }
      finally { recognitionSaving = false; void refreshStatus(); }
    });
    byId("behavior-control-enabled").addEventListener("change", () => {
      behaviorEdited = true;
      behaviorRevision++;
      text("behavior-control-status", "Unsaved robot control selection.");
    });
    byId("behavior-control-form").addEventListener("submit", async event => {
      event.preventDefault();
      if (behaviorBusy) return;
      behaviorBusy = true;
      behaviorRevision++;
      const enabled = byId("behavior-control-enabled").checked;
      byId("behavior-control-enabled").disabled = true;
      byId("behavior-control-form").querySelector("button").disabled = true;
      try {
        const settings = await request("/api/behavior-control", {method: "POST", body: JSON.stringify({enabled})});
        behaviorEdited = false;
        renderBehaviorControl(settings);
      } catch (error) {
        text("behavior-control-status", `${error.message}. The result is unconfirmed; reading current state.`);
        behaviorEdited = false;
      } finally { behaviorBusy = false; behaviorReadAt = 0; }
    });
  }

  async function setupDashboard() {
    setupNavigation();
    const session = await request("/api/session");
    csrfToken = session.csrf;
    setupSensingControls();
    setupPrimaryView();
    byId("robot-select").addEventListener("change", (event) => {
      availableBodyCommands = [];
      selectedRobotId = event.target.value || null;
      updateMotionSpeed(null); updateBalance(null);
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
    setupGyroJointGuide();
    setupIdleRest();
    setupServoFeedback();
    setupForms();
    setupSpeechOutput();
    setupSecurity();
    setupConnections();
    setupHostNetwork();
    setupRobotSettings();
    setupFaceLibrary();
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

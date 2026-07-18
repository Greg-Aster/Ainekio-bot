(function () {
  const SHIM_BASE_URL = "http://127.0.0.1:8788";
  const SHIM_EVENTS_URL = `${SHIM_BASE_URL}/events`;
  const SIMULATOR_COMMANDS = Object.freeze({
    walk: "run walk",
    backward: "rn wb",
    left: "rn tl",
    right: "rn tr",
    stand: "run stand",
    stop: "run stand",
    idle: "run stand",
    rest: "run rest",
    wave: "rn wv",
    point: "rn pt",
    dance: "rn dn",
    swim: "rn sw",
    cute: "rn ct",
    pushup: "rn pu",
    freaky: "rn fk",
    bow: "rn bw",
    worm: "rn wm",
    shake: "rn sk",
    shrug: "rn sg",
    dead: "rn dd",
    crab: "rn cb",
  });
  // Sesame's own reset path addresses the eight servos as joints 1..8.
  // Joint 0 is the floating root and must never receive a servo target.
  const LOGICAL_TO_SESAME_JOINT = Object.freeze([1, 2, 3, 4, 5, 6, 7, 8]);
  const STAND_TARGETS = Object.freeze([135, 45, 45, 135, 0, 180, 0, 180]);
  const NEUTRAL_TARGETS = Object.freeze([90, 90, 90, 90, 90, 90, 90, 90]);
  const state = {
    x: 0,
    y: 0,
    yaw: 0,
    connected: false,
    events: null,
    frameAnimation: null,
    currentTargets: Array.from(STAND_TARGETS),
  };

  function install() {
    if (document.getElementById("ainekio-shim")) return;

    const style = document.createElement("style");
    style.textContent = `
      #ainekio-shim {
        position: fixed;
        right: 16px;
        bottom: 16px;
        width: 260px;
        z-index: 999999;
        color: #f8fafc;
        background: rgba(15, 23, 42, 0.88);
        border: 1px solid rgba(148, 163, 184, 0.35);
        border-radius: 8px;
        font: 12px/1.35 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        box-shadow: 0 14px 38px rgba(0, 0, 0, 0.35);
        overflow: hidden;
      }
      #ainekio-shim .bar {
        display: flex;
        justify-content: space-between;
        gap: 8px;
        padding: 8px 10px;
        background: rgba(30, 41, 59, 0.95);
        font-weight: 700;
      }
      #ainekio-shim .body { padding: 10px; }
      #ainekio-shim .stage {
        position: relative;
        height: 120px;
        border: 1px solid rgba(148, 163, 184, 0.24);
        background:
          linear-gradient(rgba(148, 163, 184, 0.12) 1px, transparent 1px),
          linear-gradient(90deg, rgba(148, 163, 184, 0.12) 1px, transparent 1px);
        background-size: 20px 20px;
        margin-bottom: 8px;
      }
      #ainekio-shim .bot {
        position: absolute;
        left: 50%;
        top: 50%;
        width: 22px;
        height: 28px;
        margin-left: -11px;
        margin-top: -14px;
        border-radius: 6px;
        background: #38bdf8;
        box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.24);
        transition: transform 260ms ease;
      }
      #ainekio-shim .bot:before {
        content: "";
        position: absolute;
        left: 7px;
        top: -8px;
        width: 0;
        height: 0;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-bottom: 8px solid #38bdf8;
      }
      #ainekio-shim .line {
        display: flex;
        justify-content: space-between;
        gap: 8px;
        padding: 2px 0;
      }
      #ainekio-shim .muted { color: #cbd5e1; }
      #ainekio-shim .ok { color: #86efac; }
      #ainekio-shim .warn { color: #fde68a; }
      #ainekio-shim .bad { color: #fca5a5; }
    `;
    document.head.appendChild(style);

    const panel = document.createElement("div");
    panel.id = "ainekio-shim";
    panel.innerHTML = `
      <div class="bar">
        <span>Ainekio Shim</span>
        <span id="ainekio-status" class="bad">offline</span>
      </div>
      <div class="body">
        <div class="stage"><div id="ainekio-bot" class="bot"></div></div>
        <div class="line"><span class="muted">command</span><span id="ainekio-command">none</span></div>
        <div class="line"><span class="muted">simulator</span><span id="ainekio-simulator-command">-</span></div>
        <div class="line"><span class="muted">session</span><span id="ainekio-session">-</span></div>
        <div class="line"><span class="muted">model</span><span id="ainekio-model" class="warn">waiting</span></div>
      </div>
    `;
    document.body.appendChild(panel);
  }

  function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = String(value);
  }

  function setConnected(connected) {
    state.connected = connected;
    const element = document.getElementById("ainekio-status");
    if (!element) return;
    element.textContent = connected ? "online" : "offline";
    element.className = connected ? "ok" : "bad";
  }

  function setModelStatus(text, className) {
    const element = document.getElementById("ainekio-model");
    if (!element) return;
    element.textContent = text;
    element.className = className;
  }

  function getSesameRuntime() {
    const runtime = window.__AINEKIO_SESAME_RUNTIME__;
    const simulator =
      runtime && (runtime.simulator || (typeof runtime.getSimulator === "function" && runtime.getSimulator()));
    const hybrid = runtime && (runtime.hybrid || (simulator && simulator.hybrid));

    if (!simulator || !hybrid || typeof hybrid.send_uart !== "function") {
      return null;
    }

    return { simulator, hybrid };
  }

  async function reportResult(payload, status, detail) {
    if (typeof payload.actionId !== "string" || !payload.actionId) return;
    try {
      await fetch(`${SHIM_BASE_URL}/result`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          actionId: payload.actionId,
          status,
          detail: detail || null,
        }),
      });
    } catch (error) {
      console.warn("[ainekio-shim] could not report renderer result", error);
    }
  }

  function sendSimulatorCommand(payload) {
    const runtime = getSesameRuntime();
    if (!runtime) {
      setModelStatus("unavailable", "bad");
      void reportResult(payload, "rejected", "Sesame runtime unavailable");
      return;
    }

    const simulatorCommand =
      typeof payload.simulatorCommand === "string" && payload.simulatorCommand.trim()
        ? payload.simulatorCommand.trim()
        : SIMULATOR_COMMANDS[String(payload.command || "").toLowerCase()];
    if (!simulatorCommand) {
      setText("ainekio-simulator-command", "unsupported");
      setModelStatus("unsupported", "bad");
      void reportResult(payload, "rejected", "unsupported simulator command");
      return;
    }

    if (window.__AINEKIO_SIM_ACTIVITY__ && typeof window.__AINEKIO_SIM_ACTIVITY__.wake === "function") {
      window.__AINEKIO_SIM_ACTIVITY__.wake(12000, "simulator-command");
    }
    window.dispatchEvent(new CustomEvent("ainekio:simulator-command", {
      detail: { command: payload.command, simulatorCommand },
    }));
    try {
      runtime.hybrid.send_uart(`${simulatorCommand}\n`);
    } catch (error) {
      setModelStatus("failed", "bad");
      void reportResult(payload, "rejected", "simulator UART rejected command");
      return;
    }
    setText("ainekio-simulator-command", simulatorCommand);
    setModelStatus("sent", "ok");
    void reportResult(payload, "accepted", "command sent to Sesame UART");
  }

  function cancelFrameAnimation() {
    if (state.frameAnimation !== null) {
      cancelAnimationFrame(state.frameAnimation);
      state.frameAnimation = null;
    }
  }

  function normalizedFreestyleFrames(payload) {
    if (payload.jointMapVersion !== 1 || !Array.isArray(payload.frames)) return null;
    if (payload.frames.length < 1 || payload.frames.length > 32) return null;
    let totalDurationMs = 0;
    const frames = [];
    for (const frame of payload.frames) {
      if (!frame || !Number.isInteger(frame.duration_ms)) return null;
      if (frame.duration_ms < 100 || frame.duration_ms > 5000) return null;
      if (!Array.isArray(frame.targets) || frame.targets.length !== 8) return null;
      const targets = new Array(8);
      const seen = new Set();
      for (const target of frame.targets) {
        if (!Array.isArray(target) || target.length !== 2) return null;
        const jointId = target[0];
        const degrees = target[1];
        if (!Number.isInteger(jointId) || jointId < 0 || jointId >= 8 || seen.has(jointId)) {
          return null;
        }
        if (typeof degrees !== "number" || !Number.isFinite(degrees) || degrees < 0 || degrees > 180) {
          return null;
        }
        seen.add(jointId);
        targets[jointId] = degrees;
      }
      totalDurationMs += frame.duration_ms;
      if (totalDurationMs > 10000) return null;
      frames.push({ durationMs: frame.duration_ms, targets });
    }
    return frames;
  }

  function applyLogicalTargets(runtime, targets) {
    if (!runtime.hybrid || typeof runtime.hybrid.set_joint_q !== "function") {
      throw new Error("Sesame runtime does not expose eight joints");
    }
    for (let jointId = 0; jointId < 8; jointId += 1) {
      const radians = targets[jointId] * Math.PI / 180;
      runtime.hybrid.set_joint_q(LOGICAL_TO_SESAME_JOINT[jointId], radians);
    }
    state.currentTargets = Array.from(targets);
  }

  function playFreestyle(payload) {
    const runtime = getSesameRuntime();
    const frames = normalizedFreestyleFrames(payload);
    if (!runtime || !frames) {
      setModelStatus("rejected", "bad");
      void reportResult(
        payload,
        "rejected",
        runtime ? "invalid freestyle frame contract" : "Sesame runtime unavailable",
      );
      return;
    }

    cancelFrameAnimation();
    if (window.__AINEKIO_SIM_ACTIVITY__ && typeof window.__AINEKIO_SIM_ACTIVITY__.wake === "function") {
      window.__AINEKIO_SIM_ACTIVITY__.wake(12000, "freestyle-motion");
    }
    setText("ainekio-command", "freestyle");
    setText("ainekio-simulator-command", `${frames.length} generated frames`);
    setText("ainekio-session", payload.sessionId || "-");
    setModelStatus("freestyle", "ok");

    let frameIndex = 0;
    let frameStart = performance.now();
    let startTargets = Array.from(state.currentTargets);
    const tick = (timestamp) => {
      const frame = frames[frameIndex];
      const progress = Math.max(0, Math.min(1, (timestamp - frameStart) / frame.durationMs));
      const interpolated = frame.targets.map(
        (target, jointId) => startTargets[jointId] + (target - startTargets[jointId]) * progress,
      );
      try {
        applyLogicalTargets(runtime, interpolated);
      } catch (error) {
        cancelFrameAnimation();
        setModelStatus("failed", "bad");
        console.warn("[ainekio-shim] freestyle frame application failed", error);
        void reportResult(payload, "rejected", `freestyle frame application failed: ${String(error)}`);
        return;
      }
      if (progress < 1) {
        state.frameAnimation = requestAnimationFrame(tick);
        return;
      }
      frameIndex += 1;
      if (frameIndex < frames.length) {
        startTargets = Array.from(frame.targets);
        frameStart = timestamp;
        state.frameAnimation = requestAnimationFrame(tick);
        return;
      }

      const endTargets = payload.endPose === "stand"
        ? STAND_TARGETS
        : payload.endPose === "neutral"
          ? NEUTRAL_TARGETS
          : frame.targets;
      const hold = () => {
        try {
          applyLogicalTargets(runtime, endTargets);
          state.frameAnimation = requestAnimationFrame(hold);
        } catch (error) {
          cancelFrameAnimation();
          setModelStatus("failed", "bad");
          console.warn("[ainekio-shim] freestyle hold failed", error);
          void reportResult(payload, "rejected", `freestyle hold failed: ${String(error)}`);
        }
      };
      state.frameAnimation = requestAnimationFrame(hold);
    };
    state.frameAnimation = requestAnimationFrame(tick);
    void reportResult(payload, "accepted", "generated frame sequence scheduled");
  }

  function applyMotion(payload) {
    const root = payload.rootMotion || {};
    state.x += Number(root.strafe || 0) * 20;
    state.y -= Number(root.forward || 0) * 24;
    state.yaw += Number(root.yaw || 0) * 25;
    state.x = Math.max(-100, Math.min(100, state.x));
    state.y = Math.max(-46, Math.min(46, state.y));

    const bot = document.getElementById("ainekio-bot");
    if (bot) {
      bot.style.transform = `translate(${state.x}px, ${state.y}px) rotate(${state.yaw}deg)`;
    }

    setText("ainekio-command", payload.command || "unknown");
    setText("ainekio-session", payload.sessionId || "-");
    if (payload.command === "freestyle") {
      playFreestyle(payload);
      return;
    }
    cancelFrameAnimation();
    sendSimulatorCommand(payload);
  }

  function startEventStream() {
    if (state.events) return;
    const events = new EventSource(SHIM_EVENTS_URL);
    state.events = events;
    events.addEventListener("connected", () => setConnected(true));
    events.addEventListener("motion", (event) => {
      setConnected(true);
      try {
        applyMotion(JSON.parse(event.data));
      } catch (error) {
        console.warn("[ainekio-shim] invalid motion payload", error);
      }
    });
    events.onerror = () => setConnected(false);
  }

  function connect() {
    install();
    window.addEventListener("ainekio:sesame-runtime-ready", () => {
      setModelStatus("ready", "ok");
      startEventStream();
    });

    if (getSesameRuntime()) {
      setModelStatus("ready", "ok");
      startEventStream();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", connect, { once: true });
  } else {
    connect();
  }
})();

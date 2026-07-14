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
  const state = {
    x: 0,
    y: 0,
    yaw: 0,
    connected: false,
    pendingCommand: null,
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
      state.pendingCommand = payload;
      setModelStatus("waiting", "warn");
      return;
    }

    const simulatorCommand =
      typeof payload.simulatorCommand === "string" && payload.simulatorCommand.trim()
        ? payload.simulatorCommand.trim()
        : SIMULATOR_COMMANDS[String(payload.command || "").toLowerCase()];
    if (!simulatorCommand) {
      state.pendingCommand = null;
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
      state.pendingCommand = null;
      setModelStatus("failed", "bad");
      void reportResult(payload, "rejected", "simulator UART rejected command");
      return;
    }
    state.pendingCommand = null;
    setText("ainekio-simulator-command", simulatorCommand);
    setModelStatus("sent", "ok");
    void reportResult(payload, "accepted", "command sent to Sesame UART");
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
    sendSimulatorCommand(payload);
  }

  function connect() {
    install();
    window.addEventListener("ainekio:sesame-runtime-ready", () => {
      setModelStatus("ready", "ok");
      if (state.pendingCommand) {
        sendSimulatorCommand(state.pendingCommand);
      }
    });

    if (getSesameRuntime()) {
      setModelStatus("ready", "ok");
    }

    const events = new EventSource(SHIM_EVENTS_URL);
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

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", connect, { once: true });
  } else {
    connect();
  }
})();

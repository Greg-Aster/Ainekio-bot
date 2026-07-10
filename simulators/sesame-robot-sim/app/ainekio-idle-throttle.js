(function () {
  const IDLE_FRAME_MS = 250;
  const STARTUP_ACTIVE_MS = 8000;
  const USER_ACTIVE_MS = 2500;
  const COMMAND_ACTIVE_MS = 12000;

  const nativeRequestAnimationFrame = window.requestAnimationFrame.bind(window);
  const nativeCancelAnimationFrame = window.cancelAnimationFrame.bind(window);
  const nativeSetTimeout = window.setTimeout.bind(window);
  const nativeClearTimeout = window.clearTimeout.bind(window);
  const pendingFrames = new Map();
  let nextToken = 1;
  let activeUntil = performance.now() + STARTUP_ACTIVE_MS;
  let lastFrameAt = 0;

  function wake(durationMs, reason) {
    activeUntil = Math.max(activeUntil, performance.now() + durationMs);
    window.__AINEKIO_SIM_ACTIVITY__.lastReason = reason || "activity";
  }

  function isActive() {
    return document.visibilityState !== "hidden" && performance.now() < activeUntil;
  }

  window.__AINEKIO_SIM_ACTIVITY__ = {
    wake,
    lastReason: "startup",
    activeFrameMs: 0,
    idleFrameMs: IDLE_FRAME_MS,
  };

  window.requestAnimationFrame = function (callback) {
    const token = nextToken++;
    const targetDelay = isActive()
      ? 0
      : Math.max(IDLE_FRAME_MS, IDLE_FRAME_MS - (performance.now() - lastFrameAt));

    const timeoutId = nativeSetTimeout(() => {
      const rafId = nativeRequestAnimationFrame((timestamp) => {
        pendingFrames.delete(token);
        lastFrameAt = timestamp;
        callback(timestamp);
      });
      pendingFrames.set(token, { type: "raf", id: rafId });
    }, targetDelay);

    pendingFrames.set(token, { type: "timeout", id: timeoutId });
    return token;
  };

  window.cancelAnimationFrame = function (token) {
    const pending = pendingFrames.get(token);
    if (!pending) return;
    pendingFrames.delete(token);
    if (pending.type === "raf") {
      nativeCancelAnimationFrame(pending.id);
    } else {
      nativeClearTimeout(pending.id);
    }
  };

  for (const eventName of ["pointerdown", "pointermove", "wheel", "keydown", "touchstart"]) {
    window.addEventListener(eventName, () => wake(USER_ACTIVE_MS, eventName), { passive: true });
  }

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      wake(USER_ACTIVE_MS, "visible");
    }
  });

  window.addEventListener("ainekio:simulator-command", () => {
    wake(COMMAND_ACTIVE_MS, "simulator-command");
  });
})();

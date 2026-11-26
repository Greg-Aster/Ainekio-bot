<script lang="ts">
import { onMount } from "svelte";
import {
	type LocomotionEngineMode,
	ROBOT_MODEL_CATALOG,
	type RobotModelId,
	SIM_FACE_HEIGHT,
	SIM_FACE_WIDTH,
	type SimulatorCameraMode,
	type SimulatorLevelId,
	type SimulatorUiSnapshot,
	V2_FACE_EXPRESSIONS,
	decodeBodyControlPairingCode,
	getRobotModelDescriptor,
	normalizeBodyControlUrl,
} from "../sim/contracts";
import { SIMULATOR_LEVELS } from "../sim/levels";
import {
	AinekioSimulatorController,
	type WalkGaitMode,
} from "../sim/simulatorController";
import MultiplayerMenu from "./MultiplayerMenu.svelte";

type MobileTab = "drive" | "poses" | "servos" | "sandbox" | "none";

const ui = $state<{
	snapshot: SimulatorUiSnapshot;
	gait: WalkGaitMode;
	speed: number;
	balanceEnabled: boolean;
	hudVisible: boolean;
	isMobile: boolean;
	mobileTab: MobileTab;
	rightTab: "telemetry" | "sandbox";
	showConnectModal: boolean;
	showAudioMenu: boolean;
	showMultiplayerMenu: boolean;
	showCommsFeed: boolean;
	mpSeenChatCount: number;
	commsSeenCount: number;
	commsInput: string;
	bcUrl: string;
	bcRobotId: string;
	bcToken: string;
	bcAutoReconnect: boolean;
	bcPairingCode: string;
	bcPairingError: string;
	rolloutLabel: string;
	joyX: number;
	joyY: number;
	joyDragging: boolean;
}>({
	snapshot: {
		ready: false,
		loadingMessage: "Initializing MuJoCo WASM + Neural Gait & Neural Pose...",
		robotModel: "v2",
		levelId: "v2_lab",
		cameraMode: "orbit",
		engineMode: "neural",
		neuralGaitModelId: "microduck-v20-studya-p4",
		neuralPoseModelId: "neural-pose-v8-calibrated",
		neuralMotions: [],
		control: {
			mode: "standalone",
			url: "ws://127.0.0.1:8790/robot",
			robotId: "ainekio-v2-sim",
			connected: false,
			epoch: null,
		},
		micActive: false,
		micSupported: false,
		audio: {
			enabled: true,
			unlocked: false,
			playing: false,
			musicVolume: 0.55,
			sfxVolume: 0.7,
			footstepsEnabled: true,
			activeTrackLabel: "Portal Deck",
		},
		multiplayer: {
			enabled: true,
			mode: "idle",
			status: "idle",
			displayName: "",
			connectedPeers: [],
			remotePlayers: [],
			chatMessages: [],
			logs: [],
		},
		commsMessages: [],
		lastCommandLog: "Booting simulator...",
		availableClips: [
			"stand",
			"neutral",
			"sit",
			"lay",
			"wave",
			"bow",
			"stretch",
			"shake",
			"dance",
		],
	},
	gait: "walk",
	speed: 100,
	balanceEnabled: true,
	hudVisible: true,
	isMobile: false,
	mobileTab: "drive",
	rightTab: "telemetry",
	showConnectModal: false,
	showAudioMenu: false,
	showMultiplayerMenu: false,
	showCommsFeed: true,
	mpSeenChatCount: 0,
	commsSeenCount: 0,
	commsInput: "",
	bcUrl: "ws://127.0.0.1:8790/robot",
	bcRobotId: "ainekio-v2-sim",
	bcToken: "",
	bcAutoReconnect: true,
	bcPairingCode: "",
	bcPairingError: "",
	rolloutLabel: "ainekio_v2_rollout",
	joyX: 0,
	joyY: 0,
	joyDragging: false,
});

let viewportEl: HTMLDivElement | undefined;
let faceCanvasEl: HTMLCanvasElement | undefined;
let joystickEl: HTMLDivElement | undefined;
let controller: AinekioSimulatorController | undefined;
let lastWalkDispatchMs = 0;

const ROBOT_DRIVE_CODES = new Set([
	"KeyW",
	"KeyS",
	"KeyA",
	"KeyD",
	"KeyQ",
	"KeyE",
	"ArrowUp",
	"ArrowDown",
	"ArrowLeft",
	"ArrowRight",
]);
const heldDriveKeys = new Set<string>();
let keyboardDriving = false;
let keyboardLeaseTimer: number | undefined;

function clearKeyboardLeaseTimer(): void {
	if (keyboardLeaseTimer !== undefined) {
		window.clearInterval(keyboardLeaseTimer);
		keyboardLeaseTimer = undefined;
	}
}

function dispatchKeyboardDrive(): void {
	if (
		!ui.snapshot.ready ||
		ui.snapshot.control.mode !== "standalone" ||
		ui.snapshot.cameraMode === "orbit" ||
		ui.joyDragging
	) {
		if (keyboardDriving) {
			keyboardDriving = false;
			clearKeyboardLeaseTimer();
			if (!ui.joyDragging) {
				ui.joyX = 0;
				ui.joyY = 0;
			}
			controller?.sendStop(false);
		}
		return;
	}

	const fwdAxis =
		(heldDriveKeys.has("KeyW") || heldDriveKeys.has("ArrowUp") ? 1 : 0) -
		(heldDriveKeys.has("KeyS") || heldDriveKeys.has("ArrowDown") ? 1 : 0);
	const steerAxis =
		(heldDriveKeys.has("KeyA") || heldDriveKeys.has("ArrowLeft") ? 1 : 0) -
		(heldDriveKeys.has("KeyD") || heldDriveKeys.has("ArrowRight") ? 1 : 0);
	const strafeKeyAxis =
		(heldDriveKeys.has("KeyQ") ? 1 : 0) - (heldDriveKeys.has("KeyE") ? 1 : 0);

	if (fwdAxis === 0 && steerAxis === 0 && strafeKeyAxis === 0) {
		if (keyboardDriving) {
			keyboardDriving = false;
			clearKeyboardLeaseTimer();
			ui.joyX = 0;
			ui.joyY = 0;
			controller?.sendStop(false);
		}
		return;
	}

	keyboardDriving = true;
	const rawX = -(steerAxis !== 0 ? steerAxis : strafeKeyAxis);
	const rawY = -fwdAxis;
	const mag = Math.hypot(rawX, rawY);
	ui.joyX = mag > 1 ? rawX / mag : rawX;
	ui.joyY = mag > 1 ? rawY / mag : rawY;

	const forward = fwdAxis * 100;
	if (ui.gait === "crab") {
		const lateral = (steerAxis !== 0 ? steerAxis : strafeKeyAxis) * 100;
		controller?.sendWalkCommand({
			forward,
			turn: 0,
			lateral,
			speed: Math.min(100, ui.speed),
			gait: "crab",
		});
	} else if (
		strafeKeyAxis !== 0 &&
		fwdAxis === 0 &&
		steerAxis === 0 &&
		ui.snapshot.engineMode === "native"
	) {
		controller?.sendWalkCommand({
			forward: 0,
			turn: 0,
			lateral: strafeKeyAxis * 100,
			speed: Math.min(100, ui.speed),
			gait: "crab",
		});
	} else {
		controller?.sendWalkCommand({
			forward,
			turn: steerAxis * 100,
			lateral: strafeKeyAxis * 100,
			speed: ui.speed,
			gait: ui.gait,
		});
	}

	if (keyboardLeaseTimer === undefined) {
		keyboardLeaseTimer = window.setInterval(() => {
			if (keyboardDriving) {
				dispatchKeyboardDrive();
			}
		}, 400);
	}
}

function releaseAllKeyboardDrive(sendStop = true): void {
	heldDriveKeys.clear();
	clearKeyboardLeaseTimer();
	if (keyboardDriving) {
		keyboardDriving = false;
		if (!ui.joyDragging) {
			ui.joyX = 0;
			ui.joyY = 0;
		}
		if (sendStop) {
			controller?.sendStop(false);
		}
	}
}

function paintFaceToHud(width: number, height: number, rgba: Uint8Array): void {
	if (!faceCanvasEl || width !== SIM_FACE_WIDTH || height !== SIM_FACE_HEIGHT) {
		return;
	}
	const ctx = faceCanvasEl.getContext("2d");
	if (!ctx) {
		return;
	}
	const img = ctx.createImageData(width, height);
	img.data.set(rgba);
	ctx.putImageData(img, 0, 0);
}

onMount(() => {
	if (!viewportEl) {
		return;
	}
	const mobileQuery = window.matchMedia(
		"(max-width: 900px), ((max-height: 520px) and (pointer: coarse))",
	);
	const syncMobileLayout = () => {
		const nextMobile = mobileQuery.matches;
		if (ui.isMobile !== nextMobile) {
			ui.isMobile = nextMobile;
			requestAnimationFrame(() => {
				const cached = controller?.getLastFaceFrame();
				if (cached) {
					paintFaceToHud(cached.width, cached.height, cached.rgba);
				}
			});
		}
	};
	ui.isMobile = mobileQuery.matches;
	mobileQuery.addEventListener("change", syncMobileLayout);

	const ctrl = new AinekioSimulatorController(viewportEl, {
		onSnapshot: (snap) => {
			const prevLen = ui.snapshot.commsMessages.length;
			ui.snapshot = snap;
			if (ui.showMultiplayerMenu) {
				ui.mpSeenChatCount = snap.multiplayer.chatMessages.length;
			}
			if (ui.showCommsFeed) {
				ui.commsSeenCount = snap.commsMessages.length;
				if (snap.commsMessages.length > prevLen) {
					scrollCommsToBottom();
				}
			}
		},
		onFaceRgba: (w, h, rgba) => {
			paintFaceToHud(w, h, rgba);
		},
	});
	controller = ctrl;
	const savedBc = ctrl.getSavedBodyControlSettings();
	ui.bcUrl = savedBc.url;
	ui.bcRobotId = savedBc.robotId;
	ui.bcAutoReconnect = savedBc.autoReconnect;
	if (savedBc.token) {
		ui.bcToken = savedBc.token;
	}

	// Expose clean debug hook for browser verification & power users
	(
		window as unknown as {
			__ainekioSim?: {
				getSnapshot: () => SimulatorUiSnapshot;
				controller: AinekioSimulatorController;
			};
		}
	).__ainekioSim = {
		getSnapshot: () => $state.snapshot(ui.snapshot),
		controller: ctrl,
	};

	void ctrl.start();

	const isEditableTarget = (target: EventTarget | null): boolean => {
		const el = target as HTMLElement | null;
		if (!el) {
			return false;
		}
		return (
			el.tagName === "INPUT" ||
			el.tagName === "TEXTAREA" ||
			el.tagName === "SELECT" ||
			el.isContentEditable
		);
	};

	const onWindowKeyDown = (event: KeyboardEvent) => {
		if (
			event.metaKey ||
			event.ctrlKey ||
			event.altKey ||
			ui.showConnectModal ||
			isEditableTarget(event.target)
		) {
			return;
		}
		if (
			ui.snapshot.cameraMode === "orbit" ||
			!ROBOT_DRIVE_CODES.has(event.code)
		) {
			return;
		}
		if (event.code.startsWith("Arrow")) {
			event.preventDefault();
		}
		if (!heldDriveKeys.has(event.code)) {
			heldDriveKeys.add(event.code);
			dispatchKeyboardDrive();
		}
	};

	const onWindowKeyUp = (event: KeyboardEvent) => {
		if (!heldDriveKeys.has(event.code)) {
			return;
		}
		heldDriveKeys.delete(event.code);
		dispatchKeyboardDrive();
	};

	const onWindowBlur = () => {
		releaseAllKeyboardDrive(true);
	};

	const onVisibilityChange = () => {
		if (document.hidden) {
			releaseAllKeyboardDrive(true);
		}
	};

	const onFirstAudioGesture = (event: Event) => {
		const target = event.target as HTMLElement | null;
		// Let the Audio toggle button handle its own first-click unlock so
		// pointerdown + click never unlocks and immediately mutes in one click.
		if (target?.closest?.('[data-testid="audio-toggle"]')) {
			return;
		}
		ctrl.unlockAudio();
	};

	window.addEventListener("pointerdown", onFirstAudioGesture, {
		capture: true,
		passive: true,
	});
	window.addEventListener("keydown", onFirstAudioGesture, {
		capture: true,
		passive: true,
	});
	window.addEventListener("keydown", onWindowKeyDown);
	window.addEventListener("keyup", onWindowKeyUp);
	window.addEventListener("blur", onWindowBlur);
	document.addEventListener("visibilitychange", onVisibilityChange);

	return () => {
		mobileQuery.removeEventListener("change", syncMobileLayout);
		releaseAllKeyboardDrive(false);
		window.removeEventListener("pointerdown", onFirstAudioGesture, {
			capture: true,
		});
		window.removeEventListener("keydown", onFirstAudioGesture, {
			capture: true,
		});
		window.removeEventListener("keydown", onWindowKeyDown);
		window.removeEventListener("keyup", onWindowKeyUp);
		window.removeEventListener("blur", onWindowBlur);
		document.removeEventListener("visibilitychange", onVisibilityChange);
		ctrl.dispose();
		controller = undefined;
	};
});

function handleRobotChange(event: Event): void {
	const selectEl = event.currentTarget as HTMLSelectElement;
	const value = selectEl.value as RobotModelId;
	releaseAllKeyboardDrive(false);
	selectEl.blur();
	void controller?.setRobotModel(value);
}

function handleLevelChange(event: Event): void {
	const selectEl = event.currentTarget as HTMLSelectElement;
	const value = selectEl.value as SimulatorLevelId;
	releaseAllKeyboardDrive(false);
	selectEl.blur();
	void controller?.setLevel(value);
}

function toggleMultiplayerMenu(): void {
	ui.showMultiplayerMenu = !ui.showMultiplayerMenu;
	if (ui.showMultiplayerMenu) {
		ui.showAudioMenu = false;
		ui.mpSeenChatCount = ui.snapshot.multiplayer.chatMessages.length;
	}
}

const mpUnreadChat = $derived(
	Math.max(0, ui.snapshot.multiplayer.chatMessages.length - ui.mpSeenChatCount),
);
const commsUnreadCount = $derived(
	Math.max(0, ui.snapshot.commsMessages.length - ui.commsSeenCount),
);

function scrollCommsToBottom(): void {
	requestAnimationFrame(() => {
		const el = document.querySelector<HTMLElement>(
			'[data-testid="comms-messages"]',
		);
		if (el) {
			el.scrollTop = el.scrollHeight;
		}
	});
}

function toggleCommsFeed(): void {
	ui.showCommsFeed = !ui.showCommsFeed;
	if (ui.showCommsFeed) {
		ui.commsSeenCount = ui.snapshot.commsMessages.length;
		scrollCommsToBottom();
	}
}

function handleCommsSubmit(event: Event): void {
	event.preventDefault();
	const text = ui.commsInput.trim();
	if (!text) {
		return;
	}
	controller?.sendCommsText(text);
	ui.commsInput = "";
}
const mpPeerTotal = $derived(
	Math.max(
		ui.snapshot.multiplayer.connectedPeers.length,
		ui.snapshot.multiplayer.remotePlayers.length,
	) + 1,
);

function setCamera(mode: SimulatorCameraMode): void {
	if (mode === "orbit") {
		releaseAllKeyboardDrive(true);
	}
	controller?.setCameraMode(mode);
}

function setEngine(mode: LocomotionEngineMode): void {
	releaseAllKeyboardDrive(false);
	controller?.setEngineMode(mode);
}

function handleAudioToggle(): void {
	const audio = ui.snapshot.audio;
	if (!audio.unlocked) {
		controller?.setAudioEnabled(true);
		return;
	}
	controller?.setAudioEnabled(!audio.enabled);
}

function sendWalkFromJoystick(nx: number, ny: number, force = false): void {
	const now = performance.now();
	if (!force && now - lastWalkDispatchMs < 90) {
		return;
	}
	lastWalkDispatchMs = now;
	const forward = Math.round(-ny * 100);
	const steer = Math.round(-nx * 100);
	if (ui.gait === "crab") {
		controller?.sendWalkCommand({
			forward,
			turn: 0,
			lateral: steer,
			speed: Math.min(100, ui.speed),
			gait: "crab",
		});
	} else {
		controller?.sendWalkCommand({
			forward,
			turn: steer,
			speed: ui.speed,
			gait: ui.gait,
		});
	}
}

function updateJoystickPointer(event: PointerEvent, force = false): void {
	if (!joystickEl) {
		return;
	}
	const rect = joystickEl.getBoundingClientRect();
	const cx = rect.left + rect.width / 2;
	const cy = rect.top + rect.height / 2;
	const radius = rect.width * 0.42;
	let dx = (event.clientX - cx) / radius;
	let dy = (event.clientY - cy) / radius;
	const mag = Math.hypot(dx, dy);
	if (mag > 1) {
		dx /= mag;
		dy /= mag;
	}
	ui.joyX = dx;
	ui.joyY = dy;
	sendWalkFromJoystick(dx, dy, force);
}

function onJoystickDown(event: PointerEvent): void {
	if (ui.snapshot.control.mode !== "standalone" || !ui.snapshot.ready) {
		return;
	}
	ui.joyDragging = true;
	try {
		(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
	} catch {
		// Ignore synthetic or non-capturable pointers
	}
	updateJoystickPointer(event, true);
}

function onJoystickMove(event: PointerEvent): void {
	if (!ui.joyDragging) {
		return;
	}
	updateJoystickPointer(event, false);
}

function onJoystickUp(event: PointerEvent): void {
	if (!ui.joyDragging) {
		return;
	}
	ui.joyDragging = false;
	const el = event.currentTarget as HTMLElement;
	try {
		if (el.hasPointerCapture(event.pointerId)) {
			el.releasePointerCapture(event.pointerId);
		}
	} catch {
		// Firefox may auto-release capture before pointerup/pointercancel
	}
	ui.joyX = 0;
	ui.joyY = 0;
	controller?.sendStop(false);
}

function triggerQuickWalk(forward: number, turn: number): void {
	controller?.sendWalkCommand({
		forward,
		turn,
		lateral: ui.gait === "crab" ? turn : 0,
		speed: ui.gait === "crab" ? Math.min(100, ui.speed) : ui.speed,
		gait: ui.gait,
	});
}

function toggleBalance(): void {
	ui.balanceEnabled = !ui.balanceEnabled;
	controller?.setBalanceEnabled(ui.balanceEnabled);
}

function handleConnectBodyControl(): void {
	ui.bcPairingError = "";
	ui.bcUrl = normalizeBodyControlUrl(ui.bcUrl);
	controller?.connectBodyControl(
		ui.bcUrl,
		ui.bcRobotId,
		ui.bcToken,
		ui.bcAutoReconnect,
	);
}

function handleApplyPairingCode(): void {
	ui.bcPairingError = "";
	const bundle = decodeBodyControlPairingCode(ui.bcPairingCode);
	if (!bundle || (!bundle.bc && !bundle.token)) {
		ui.bcPairingError =
			"Paste a valid Pairing Code (ainekio-pair:...) or Launch Link from Body Control.";
		return;
	}
	if (bundle.bc) {
		ui.bcUrl = bundle.bc;
	}
	if (bundle.robotId) {
		ui.bcRobotId = bundle.robotId;
	}
	if (bundle.token) {
		ui.bcToken = bundle.token;
	}
	ui.bcPairingCode = "";
	void controller?.applyPairingBundle(bundle, true);
}

function handleDisconnectBodyControl(): void {
	controller?.disconnectBodyControl(true);
}

function toggleHud(): void {
	ui.hudVisible = !ui.hudVisible;
	if (ui.hudVisible) {
		requestAnimationFrame(() => {
			const cached = controller?.getLastFaceFrame();
			if (cached) {
				paintFaceToHud(cached.width, cached.height, cached.rgba);
			}
		});
	}
}

function setMobileTab(tab: MobileTab): void {
	if (tab !== "none" && ui.mobileTab === tab) {
		ui.mobileTab = "none";
		return;
	}
	ui.mobileTab = tab;
	if (tab === "poses") {
		requestAnimationFrame(() => {
			const cached = controller?.getLastFaceFrame();
			if (cached) {
				paintFaceToHud(cached.width, cached.height, cached.rgba);
			}
		});
	}
}

function cycleCameraMode(): void {
	const order: SimulatorCameraMode[] = ["orbit", "follow", "robot-pov"];
	const idx = order.indexOf(ui.snapshot.cameraMode);
	const next = order[(idx + 1) % order.length] ?? "orbit";
	setCamera(next);
}

function formatDeg(val: number | undefined): string {
	return val === undefined ? "--" : `${val.toFixed(1)}°`;
}

function servoBarPct(deg: number | undefined): number {
	if (deg === undefined) {
		return 50;
	}
	return Math.max(4, Math.min(96, ((deg + 90) / 180) * 100));
}

const activeRobot = $derived(getRobotModelDescriptor(ui.snapshot.robotModel));
const isStandalone = $derived(ui.snapshot.control.mode === "standalone");
const isNeuralEngine = $derived(ui.snapshot.engineMode === "neural");
const telemetry = $derived(ui.snapshot.state);
const mobileCameraLabel = $derived(
	ui.snapshot.cameraMode === "orbit"
		? "Orbit"
		: ui.snapshot.cameraMode === "follow"
			? "Follow"
			: "POV",
);
const waveMotionId = $derived(activeRobot.id === "v2" ? "wave" : "wave_fr");
const clipButtons = $derived(
	ui.snapshot.availableClips.filter(
		(clip) => clip !== "stand" && clip !== "neutral",
	),
);
const neuralMotionButtons = $derived(
	ui.snapshot.neuralMotions.filter((m) => m.id !== "stand"),
);
</script>

<div class="sim-root">
	<!-- Full-viewport Three.js WebGL Stage -->
	<div class="viewport-host" bind:this={viewportEl}></div>

	<!-- Loading Overlay -->
	{#if !ui.snapshot.ready}
		<div class="loading-overlay" data-testid="loading-overlay">
			<div class="loading-card">
				<div class="spinner"></div>
				<h1>AINEKIO {activeRobot.shortName} SIMULATOR</h1>
				<p>{ui.snapshot.loadingMessage || "Booting MuJoCo WASM + ESP32-P4 Firmware..."}</p>
				<div class="loading-sub">
					500 Hz MuJoCo Physics · 50 Hz Compiled C Firmware · 100% Static Web
				</div>
				{#if ui.snapshot.lastError}
					<div class="error-banner">{ui.snapshot.lastError}</div>
				{/if}
			</div>
		</div>
	{/if}

	<!-- Top Navigation Bar -->
	<header class="top-bar" class:mobile={ui.isMobile}>
		{#if !ui.isMobile}
			<div class="brand-group">
				<span class="brand-dot" class:online={ui.snapshot.ready}></span>
				<div>
					<div class="brand-title">AINEKIO {activeRobot.shortName} SIMULATOR</div>
					<div class="brand-sub">
						MuJoCo 500 Hz · {activeRobot.jointCount}-Servo · {isNeuralEngine ? "Neural Gait + Pose" : "Legacy Native"}
						{#if telemetry}
							· {telemetry.stepMs.toFixed(2)} ms/step
						{/if}
					</div>
				</div>
			</div>

			<div class="top-controls">
				<label class="level-picker robot-picker">
					<span class="sr-only">Robot Model</span>
					<select
						data-testid="robot-select"
						value={ui.snapshot.robotModel}
						onchange={handleRobotChange}
					>
						{#each ROBOT_MODEL_CATALOG as robot}
							<option value={robot.id} disabled={!robot.ready}>
								{robot.name}
							</option>
						{/each}
					</select>
				</label>

				<label class="level-picker">
					<span class="sr-only">Arena Level</span>
					<select
						data-testid="level-select"
						value={ui.snapshot.levelId}
						onchange={handleLevelChange}
					>
						{#each SIMULATOR_LEVELS as level}
							<option value={level.id}>{level.name}</option>
						{/each}
					</select>
				</label>

				<div class="segmented" role="group" aria-label="Camera View">
					<button
						type="button"
						data-testid="cam-orbit"
						class:active={ui.snapshot.cameraMode === "orbit"}
						onclick={() => setCamera("orbit")}
					>
						Orbit
					</button>
					<button
						type="button"
						data-testid="cam-follow"
						class:active={ui.snapshot.cameraMode === "follow"}
						onclick={() => setCamera("follow")}
					>
						Follow {activeRobot.shortName}
					</button>
					<button
						type="button"
						data-testid="cam-pov"
						class:active={ui.snapshot.cameraMode === "robot-pov"}
						onclick={() => setCamera("robot-pov")}
					>
						Robot POV
					</button>
					<button
						type="button"
						title={`Recenter orbit camera on Ainekio ${activeRobot.shortName}`}
						onclick={() => controller?.focusRobot()}
					>
						Focus
					</button>
				</div>

				<div class="audio-control">
					<button
						type="button"
						class="audio-btn"
						class:active={ui.snapshot.audio.enabled && ui.snapshot.audio.unlocked}
						class:muted={!ui.snapshot.audio.enabled}
						data-testid="audio-toggle"
						title={ui.snapshot.audio.enabled
							? ui.snapshot.audio.unlocked
								? `Mute audio (${ui.snapshot.audio.activeTrackLabel || "Soundscape"})`
								: "Click to enable level music & sound effects"
							: "Unmute level music & sound effects"}
						onclick={handleAudioToggle}
					>
						<span class="audio-icon" aria-hidden="true">
							{#if !ui.snapshot.audio.enabled}
								🔇
							{:else if ui.snapshot.audio.unlocked}
								🔊
							{:else}
								♪
							{/if}
						</span>
						<span class="audio-label">
							{#if !ui.snapshot.audio.enabled}
								Muted
							{:else if ui.snapshot.audio.unlocked}
								{ui.snapshot.audio.activeTrackLabel || "Audio"}
							{:else}
								Audio
							{/if}
						</span>
					</button>
					<button
						type="button"
						class="audio-caret"
						data-testid="audio-mixer-btn"
						title="Audio mixer (music, SFX, footsteps)"
						aria-expanded={ui.showAudioMenu}
						onclick={() => {
							ui.showAudioMenu = !ui.showAudioMenu;
							if (ui.showAudioMenu) {
								ui.showMultiplayerMenu = false;
							}
						}}
					>
						▾
					</button>
					{#if ui.showAudioMenu}
						<div
							class="audio-popover"
							role="dialog"
							aria-label="Audio Mixer"
							data-testid="audio-popover"
						>
							<div class="audio-pop-head">
								<span>WORLD AUDIO &amp; SFX</span>
								<span class="audio-now-playing">
									♪ {ui.snapshot.audio.activeTrackLabel || "Silent"}
								</span>
							</div>
							<label class="audio-slider-row">
								<span>Music {Math.round(ui.snapshot.audio.musicVolume * 100)}%</span>
								<input
									type="range"
									min="0"
									max="100"
									value={Math.round(ui.snapshot.audio.musicVolume * 100)}
									oninput={(e) =>
										controller?.setMusicVolume(
											Number((e.currentTarget as HTMLInputElement).value) / 100,
										)}
								/>
							</label>
							<label class="audio-slider-row">
								<span>SFX {Math.round(ui.snapshot.audio.sfxVolume * 100)}%</span>
								<input
									type="range"
									min="0"
									max="100"
									value={Math.round(ui.snapshot.audio.sfxVolume * 100)}
									oninput={(e) =>
										controller?.setSfxVolume(
											Number((e.currentTarget as HTMLInputElement).value) / 100,
										)}
								/>
							</label>
							<label class="audio-check-row">
								<input
									type="checkbox"
									checked={ui.snapshot.audio.footstepsEnabled}
									onchange={(e) =>
										controller?.setFootstepsEnabled(
											(e.currentTarget as HTMLInputElement).checked,
										)}
								/>
								<span>MuJoCo foot-contact taps</span>
							</label>
						</div>
					{/if}
				</div>

				{#if ui.snapshot.multiplayer.enabled}
					<div class="mp-control">
						<button
							type="button"
							class="mp-menu-btn"
							class:connected={ui.snapshot.multiplayer.status === "connected"}
							class:connecting={ui.snapshot.multiplayer.status === "connecting"}
							data-testid="multiplayer-menu-btn"
							aria-expanded={ui.showMultiplayerMenu}
							title="Multiplayer rooms (Create or Join a P2P room)"
							onclick={toggleMultiplayerMenu}
						>
							<span class="mp-dot" aria-hidden="true"></span>
							{#if ui.snapshot.multiplayer.status === "connected"}
								<span class="mp-btn-label">
									{ui.snapshot.multiplayer.roomName} · {mpPeerTotal}
								</span>
							{:else if ui.snapshot.multiplayer.status === "connecting"}
								<span class="mp-btn-label">Joining…</span>
							{:else}
								<span class="mp-btn-label">Multiplayer</span>
							{/if}
							{#if mpUnreadChat > 0 && !ui.showMultiplayerMenu}
								<span class="mp-unread-badge">{mpUnreadChat}</span>
							{/if}
							<span class="mp-caret" aria-hidden="true">▾</span>
						</button>
						{#if ui.showMultiplayerMenu}
							<MultiplayerMenu
								snapshot={ui.snapshot.multiplayer}
								localLevelId={ui.snapshot.levelId}
								isMobile={false}
								onCreateRoom={(room, name) =>
									void controller?.hostMultiplayerRoom(room, name)}
								onJoinRoom={(room, name) =>
									void controller?.joinMultiplayerRoom(room, name)}
								onLeaveRoom={() => controller?.leaveMultiplayerRoom()}
								onSendChat={(text) => controller?.sendMultiplayerChat(text)}
								onSwitchLevel={(lvl) => void controller?.setLevel(lvl)}
								onClose={() => (ui.showMultiplayerMenu = false)}
							/>
						{/if}
					</div>
				{/if}

				<button
					type="button"
					class="top-talk-btn"
					class:listening={ui.snapshot.micActive}
					data-testid="top-talk-btn"
					title={ui.snapshot.micSupported
						? "Tap to speak directly to Ainekio OS (tap again to send)"
						: "Browser microphone requires https:// or http://127.0.0.1 (typed chat works everywhere)"}
					onclick={() => void controller?.toggleMicrophone()}
				>
					<span class="talk-dot" aria-hidden="true"></span>
					{#if ui.snapshot.micActive}
						<span>Done · Send</span>
					{:else}
						<span>🎤 Tap to Talk</span>
					{/if}
				</button>

				<button
					type="button"
					class="top-comms-btn"
					class:active={ui.showCommsFeed}
					data-testid="top-comms-btn"
					title="Toggle Ainekio OS &amp; Multiplayer Text Feed"
					onclick={toggleCommsFeed}
				>
					<span>💬 Chat</span>
					{#if commsUnreadCount > 0 && !ui.showCommsFeed}
						<span class="mp-unread-badge">{commsUnreadCount}</span>
					{/if}
				</button>

				<button
					type="button"
					class="connect-pill"
					class:connected={ui.snapshot.control.connected}
					data-testid="open-connect-modal"
					onclick={() => (ui.showConnectModal = !ui.showConnectModal)}
				>
					<span class="pill-dot"></span>
					{#if ui.snapshot.control.connected}
						Body Control: {ui.snapshot.control.robotId}
					{:else if ui.snapshot.control.reconnecting}
						Reconnecting...
					{:else if ui.snapshot.control.mode === "body-control"}
						Connecting...
					{:else}
						Standalone · Connect Body Control
					{/if}
				</button>

				<button type="button" class="ghost-btn" onclick={toggleHud}>
					{ui.hudVisible ? "Hide HUD" : "Show Cockpit"}
				</button>
			</div>
		{:else}
			<div class="mobile-top-row">
				<span class="brand-dot" class:online={ui.snapshot.ready}></span>

				<label class="mobile-select-wrap robot">
					<span class="sr-only">Robot Model</span>
					<select
						data-testid="robot-select"
						value={ui.snapshot.robotModel}
						onchange={handleRobotChange}
					>
						{#each ROBOT_MODEL_CATALOG as robot}
							<option value={robot.id} disabled={!robot.ready}>
								{robot.shortName}
							</option>
						{/each}
					</select>
				</label>

				<label class="mobile-select-wrap level">
					<span class="sr-only">Arena Level</span>
					<select
						data-testid="level-select"
						value={ui.snapshot.levelId}
						onchange={handleLevelChange}
					>
						{#each SIMULATOR_LEVELS as level}
							<option value={level.id}>{level.name}</option>
						{/each}
					</select>
				</label>

				<button
					type="button"
					class="mobile-top-btn cam"
					data-testid="mobile-cam-cycle"
					title="Cycle camera view (Orbit / Follow / Robot POV)"
					onclick={cycleCameraMode}
				>
					{mobileCameraLabel}
				</button>

				<button
					type="button"
					class="mobile-top-btn icon"
					data-testid="mobile-cam-focus"
					title={`Focus camera on Ainekio ${activeRobot.shortName}`}
					aria-label="Focus Robot"
					onclick={() => controller?.focusRobot()}
				>
					⌖
				</button>

				<button
					type="button"
					class="mobile-top-btn icon"
					class:active={ui.snapshot.audio.enabled && ui.snapshot.audio.unlocked}
					data-testid="audio-toggle"
					title="Toggle audio"
					aria-label="Toggle audio"
					onclick={handleAudioToggle}
				>
					{#if !ui.snapshot.audio.enabled}
						🔇
					{:else if ui.snapshot.audio.unlocked}
						🔊
					{:else}
						♪
					{/if}
				</button>

				{#if ui.snapshot.multiplayer.enabled}
					<button
						type="button"
						class="mobile-top-btn icon mp-mobile-btn"
						class:active={ui.snapshot.multiplayer.status === "connected" || ui.showMultiplayerMenu}
						class:mp-live={ui.snapshot.multiplayer.status === "connected"}
						data-testid="multiplayer-menu-btn"
						aria-expanded={ui.showMultiplayerMenu}
						title="Multiplayer rooms"
						aria-label="Multiplayer rooms"
						onclick={toggleMultiplayerMenu}
					>
						👥
						{#if mpUnreadChat > 0 && !ui.showMultiplayerMenu}
							<span class="mp-mobile-dot"></span>
						{/if}
					</button>
				{/if}

				<button
					type="button"
					class="mobile-top-btn icon"
					class:active={ui.snapshot.micActive}
					data-testid="mobile-talk-btn"
					title="Tap to Talk"
					aria-label="Tap to Talk"
					onclick={() => void controller?.toggleMicrophone()}
				>
					{ui.snapshot.micActive ? "●" : "🎤"}
				</button>

				<button
					type="button"
					class="mobile-top-btn icon mp-mobile-btn"
					class:active={ui.showCommsFeed}
					data-testid="mobile-comms-btn"
					title="Toggle Text Feed"
					aria-label="Toggle Text Feed"
					onclick={toggleCommsFeed}
				>
					💬
					{#if commsUnreadCount > 0 && !ui.showCommsFeed}
						<span class="mp-mobile-dot"></span>
					{/if}
				</button>
			</div>
			{#if ui.showMultiplayerMenu && ui.snapshot.multiplayer.enabled}
				<MultiplayerMenu
					snapshot={ui.snapshot.multiplayer}
					localLevelId={ui.snapshot.levelId}
					isMobile={true}
					onCreateRoom={(room, name) =>
						void controller?.hostMultiplayerRoom(room, name)}
					onJoinRoom={(room, name) =>
						void controller?.joinMultiplayerRoom(room, name)}
					onLeaveRoom={() => controller?.leaveMultiplayerRoom()}
					onSendChat={(text) => controller?.sendMultiplayerChat(text)}
					onSwitchLevel={(lvl) => void controller?.setLevel(lvl)}
					onClose={() => (ui.showMultiplayerMenu = false)}
				/>
			{/if}
		{/if}
	</header>

	<!-- External Body Control Connection Modal -->
	{#if ui.showConnectModal}
		<div class="modal-backdrop" role="presentation" onclick={() => (ui.showConnectModal = false)}>
			<div
				class="modal-card"
				role="dialog"
				aria-label="Connect External Body Control"
				onclick={(e) => e.stopPropagation()}
			>
				<div class="modal-header">
					<h2>External Body Control Link</h2>
					<button
						type="button"
						class="close-btn"
						onclick={() => (ui.showConnectModal = false)}
					>
						✕
					</button>
				</div>
				<p class="modal-desc">
					Connect this browser-hosted MuJoCo {activeRobot.shortName} robot directly to your
					local or remote Ainekio Body Control server over native <code>protocol-v1</code>
					WebSocket — identical to a physical robot, with no local Python bridge required.
				</p>

				<div class="field-group">
					<label for="bc-pair-code">Quick Pair Code or Launch Link (from Body Control)</label>
					<div class="field-row">
						<input
							id="bc-pair-code"
							data-testid="bc-pair-input"
							type="text"
							bind:value={ui.bcPairingCode}
							placeholder="Paste ainekio-pair:... or simulator launch link"
						/>
						<button
							type="button"
							class="btn primary"
							data-testid="bc-pair-apply-btn"
							disabled={!ui.bcPairingCode.trim()}
							onclick={handleApplyPairingCode}
						>
							Apply &amp; Link
						</button>
					</div>
				</div>

				{#if ui.bcPairingError}
					<div class="error-banner">{ui.bcPairingError}</div>
				{/if}

				<div class="bc-presets">
					<button
						type="button"
						class="chip"
						data-testid="bc-preset-local"
						onclick={() => (ui.bcUrl = "ws://127.0.0.1:8790/robot")}
					>
						Local (127.0.0.1:8790)
					</button>
					<button
						type="button"
						class="chip"
						data-testid="bc-preset-relay"
						onclick={() => (ui.bcUrl = "wss://robot-gateway.ainek.io/robot")}
					>
						Cloudflare Relay (wss://robot-gateway.ainek.io/robot)
					</button>
				</div>

				<div class="field-group">
					<label for="bc-url">Body Control Host or WebSocket URL</label>
					<input
						id="bc-url"
						data-testid="bc-url-input"
						type="text"
						bind:value={ui.bcUrl}
						placeholder="robot-gateway.ainek.io or ws://127.0.0.1:8790/robot"
					/>
				</div>

				<div class="field-row">
					<div class="field-group">
						<label for="bc-id">Robot ID</label>
						<input
							id="bc-id"
							data-testid="bc-id-input"
							type="text"
							bind:value={ui.bcRobotId}
							placeholder="ainekio-v2-sim"
						/>
					</div>
					<div class="field-group">
						<label for="bc-token">Robot Auth Token</label>
						<input
							id="bc-token"
							data-testid="bc-token-input"
							type="password"
							bind:value={ui.bcToken}
							placeholder="Required: token from robot-tokens.json"
						/>
					</div>
				</div>

				<label class="audio-check-row bc-reconnect-row">
					<input
						type="checkbox"
						data-testid="bc-autoreconnect-checkbox"
						bind:checked={ui.bcAutoReconnect}
					/>
					<span>Auto-reconnect on transient disconnect (URL &amp; Robot ID saved locally; token stays in memory only)</span>
				</label>

				{#if ui.snapshot.control.error}
					<div class="error-banner">{ui.snapshot.control.error}</div>
				{/if}

				<div class="modal-note">
					<strong>Local vs Remote:</strong> Same-machine browsers allow
					<code>ws://127.0.0.1:8790/robot</code> from <code>https://simulator.ainek.io</code>.
					From a phone or remote computer, start <code>./Master/start-physical-relay.sh</code>
					and connect to <code>wss://robot-gateway.ainek.io/robot</code>.
				</div>

				<div class="modal-actions">
					{#if ui.snapshot.control.mode === "body-control"}
						<button
							type="button"
							class="btn danger"
							data-testid="bc-disconnect-btn"
							onclick={handleDisconnectBodyControl}
						>
							Disconnect &amp; Return to Standalone
						</button>
					{:else}
						<button
							type="button"
							class="btn primary"
							data-testid="bc-connect-btn"
							onclick={handleConnectBodyControl}
						>
							Connect to Body Control
						</button>
					{/if}
					<button
						type="button"
						class="btn"
						onclick={() => (ui.showConnectModal = false)}
					>
						Close
					</button>
				</div>
			</div>
		</div>
	{/if}

	<!-- Main Floating Cockpit HUD (Desktop) -->
	{#if !ui.isMobile && ui.hudVisible}
		<!-- LEFT DOCK: Body Control Cockpit -->
		<aside class="dock dock-left">
			<!-- Live Face & OV5647 Chin Camera -->
			<section class="panel">
				<div class="panel-header">
					<span>
						{#if activeRobot.id === "v1"}
							OLED FACE &amp; ARDUCAM VISION
						{:else if activeRobot.id === "v3"}
							2.8" ILI9341 FACE &amp; ARDUCAM VISION
						{:else}
							ST7789 FACE &amp; OV5647 VISION
						{/if}
					</span>
					<span class="tag">{telemetry?.face.name ?? "default"}</span>
				</div>
				<div class="media-grid">
					<div class="face-box">
						<canvas
							bind:this={faceCanvasEl}
							width={SIM_FACE_WIDTH}
							height={SIM_FACE_HEIGHT}
							data-testid="face-mirror"
						></canvas>
						<span class="media-label">{activeRobot.displayLabel}</span>
					</div>
					<div class="cam-box">
						{#if ui.snapshot.cameraPreviewDataUrl}
							<img
								src={ui.snapshot.cameraPreviewDataUrl}
								alt="OV5647 Robot Chin Camera"
								data-testid="camera-pip"
							/>
						{:else}
							<div class="cam-placeholder">OV5647 Ready</div>
						{/if}
						<button
							type="button"
							class="snap-btn"
							data-testid="btn-snap"
							onclick={() => void controller?.captureSnapshot()}
						>
							Snap
						</button>
					</div>
				</div>
			</section>

			<!-- Locomotion Cockpit -->
			<section class="panel" class:dimmed={!isStandalone}>
				<div class="panel-header">
					<span>LOCOMOTION COCKPIT</span>
					{#if !isStandalone}
						<span class="tag warn">BODY CONTROL OWNED</span>
					{:else if isNeuralEngine}
						<span class="tag ok" data-testid="engine-badge">NEURAL GAIT</span>
					{:else}
						<span class="tag" data-testid="engine-badge">LEGACY NATIVE</span>
					{/if}
				</div>

				<div class="engine-row">
					<button
						type="button"
						class="chip"
						data-testid="engine-neural"
						class:active={isNeuralEngine}
						disabled={!isStandalone}
						onclick={() => setEngine("neural")}
					>
						Neural (Default)
					</button>
					<button
						type="button"
						class="chip"
						data-testid="engine-native"
						class:active={!isNeuralEngine}
						disabled={!isStandalone}
						onclick={() => setEngine("native")}
					>
						Legacy Native
					</button>
					{#if isNeuralEngine}
						<span class="policy-tag" title="Active MicroDuck neural gait checkpoint">
							{ui.snapshot.neuralGaitModelId}
						</span>
					{/if}
				</div>

				<div class="gait-row">
					{#if isNeuralEngine}
						<button
							type="button"
							class="chip"
							class:active={ui.gait !== "crab"}
							disabled={!isStandalone}
							onclick={() => (ui.gait = "walk")}
						>
							TURN
						</button>
						<button
							type="button"
							class="chip"
							class:active={ui.gait === "crab"}
							disabled={!isStandalone}
							onclick={() => (ui.gait = "crab")}
						>
							STRAFE
						</button>
					{:else}
						{#each ["walk", "run", "crab"] as g}
							<button
								type="button"
								class="chip"
								class:active={ui.gait === g}
								disabled={!isStandalone}
								onclick={() => (ui.gait = g as WalkGaitMode)}
							>
								{g.toUpperCase()}
							</button>
						{/each}
					{/if}
					<label class="speed-slider">
						<span>{ui.speed}%</span>
						<input
							type="range"
							min="25"
							max={ui.gait === "crab" ? 100 : isNeuralEngine ? 150 : 180}
							step="5"
							bind:value={ui.speed}
							disabled={!isStandalone}
						/>
					</label>
				</div>

				<div class="drive-area">
					<div
						class="joystick"
						bind:this={joystickEl}
						onpointerdown={onJoystickDown}
						onpointermove={onJoystickMove}
						onpointerup={onJoystickUp}
						onpointercancel={onJoystickUp}
						role="slider"
						tabindex="0"
						aria-label="Walk and steer joystick"
						aria-valuenow={Math.round(-ui.joyY * 100)}
					>
						<div class="joy-cross-h"></div>
						<div class="joy-cross-v"></div>
						<div
							class="joy-knob"
							style={`transform: translate(${ui.joyX * 42}px, ${ui.joyY * 42}px)`}
						></div>
						<span class="joy-label top">FWD</span>
						<span class="joy-label bottom">REV</span>
						<span class="joy-label left">{ui.gait === "crab" ? "L-CRAB" : "L"}</span>
						<span class="joy-label right">{ui.gait === "crab" ? "R-CRAB" : "R"}</span>
					</div>

					<div class="quick-drive">
						<div class="dpad-row">
							<button
								type="button"
								class="btn sm"
								data-testid="btn-walk-fwd"
								disabled={!isStandalone}
								onclick={() => triggerQuickWalk(85, 0)}
							>
								▲ Walk
							</button>
						</div>
						<div class="dpad-row">
							<button
								type="button"
								class="btn sm"
								disabled={!isStandalone}
								onclick={() => triggerQuickWalk(0, 85)}
							>
								◀ Left
							</button>
							<button
								type="button"
								class="btn sm stop-btn"
								data-testid="btn-stop"
								disabled={!isStandalone}
								onclick={() => controller?.sendStop(false)}
							>
								■ Stop
							</button>
							<button
								type="button"
								class="btn sm"
								disabled={!isStandalone}
								onclick={() => triggerQuickWalk(0, -85)}
							>
								Right ▶
							</button>
						</div>
						<div class="dpad-row">
							<button
								type="button"
								class="btn sm"
								disabled={!isStandalone}
								onclick={() => triggerQuickWalk(-80, 0)}
							>
								▼ Back
							</button>
						</div>

						<div class="posture-row">
							<button
								type="button"
								class="btn primary sm"
								data-testid="btn-stand"
								disabled={!isStandalone}
								onclick={() => controller?.sendClipOrPosture("stand")}
							>
								Stand
							</button>
							<button
								type="button"
								class="btn sm"
								data-testid="btn-neutral"
								disabled={!isStandalone}
								onclick={() => controller?.sendClipOrPosture("neutral")}
							>
								Neutral
							</button>
							<button
								type="button"
								class="btn danger sm"
								data-testid="btn-estop"
								disabled={!isStandalone}
								onclick={() => controller?.sendStop(true)}
							>
								E-Stop
							</button>
						</div>
					</div>
				</div>
			</section>

			<!-- Neural Pose & V2 Motions -->
			<section class="panel" class:dimmed={!isStandalone}>
				<div class="panel-header">
					<span>{isNeuralEngine ? "NEURAL POSE & EMOTES" : "LEGACY FIRMWARE CLIPS"}</span>
					<button
						type="button"
						class="chip mic-chip"
						class:active={ui.snapshot.micActive}
						disabled={!ui.snapshot.micSupported}
						onclick={() => void controller?.toggleMicrophone()}
					>
						{ui.snapshot.micActive ? "● Listening" : "🎤 Tap to Talk"}
					</button>
				</div>
				<div class="chip-grid">
					{#if isNeuralEngine && neuralMotionButtons.length > 0}
						{#each neuralMotionButtons as motion}
							<button
								type="button"
								class="chip"
								class:active={telemetry?.neural.activeMotionId === motion.id}
								data-testid={`clip-${motion.id}`}
								title={motion.sourceTitle}
								disabled={!isStandalone}
								onclick={() => controller?.sendClipOrPosture(motion.id)}
							>
								{motion.label}
							</button>
						{/each}
					{:else}
						{#each clipButtons as clip}
							<button
								type="button"
								class="chip"
								data-testid={`clip-${clip}`}
								disabled={!isStandalone}
								onclick={() => controller?.sendClipOrPosture(clip)}
							>
								{clip}
							</button>
						{/each}
					{/if}
				</div>
			</section>

			<!-- Face Expressions -->
			<section class="panel" class:dimmed={!isStandalone}>
				<div class="panel-header">
					<span>FACE EXPRESSIONS</span>
				</div>
				<div class="chip-grid">
					{#each V2_FACE_EXPRESSIONS as expr}
						<button
							type="button"
							class="chip"
							data-testid={`face-${expr}`}
							class:active={telemetry?.face.name === expr}
							disabled={!isStandalone}
							onclick={() => controller?.sendFaceExpression(expr)}
						>
							{expr}
						</button>
					{/each}
				</div>
			</section>
		</aside>

		<!-- RIGHT DOCK: Telemetry, Servos, Physics Sandbox & RL Recorder -->
		<aside class="dock dock-right">
			<div class="tab-bar">
				<button
					type="button"
					class:active={ui.rightTab === "telemetry"}
					onclick={() => (ui.rightTab = "telemetry")}
				>
					Telemetry &amp; Servos
				</button>
				<button
					type="button"
					data-testid="tab-sandbox"
					class:active={ui.rightTab === "sandbox"}
					onclick={() => (ui.rightTab = "sandbox")}
				>
					Physics &amp; RL
				</button>
			</div>

			{#if ui.rightTab === "telemetry"}
				<section class="panel">
					<div class="panel-header">
						<span>IMU &amp; STATUS</span>
						<span class="tag" class:ok={telemetry?.armed}>
							{telemetry?.armed ? "ARMED" : "IDLE"}
						</span>
					</div>
					<div class="metric-grid">
						<div class="metric">
							<span>Roll</span>
							<strong>{formatDeg(telemetry?.imu.rollDeg)}</strong>
						</div>
						<div class="metric">
							<span>Pitch</span>
							<strong>{formatDeg(telemetry?.imu.pitchDeg)}</strong>
						</div>
						<div class="metric">
							<span>Yaw</span>
							<strong>{formatDeg(telemetry?.imu.yawDeg)}</strong>
						</div>
						<div class="metric">
							<span>Battery</span>
							<strong>{telemetry ? `${telemetry.batteryVoltage.toFixed(2)} V` : "--"}</strong>
						</div>
					</div>
					<div class="foot-row">
						{#each activeRobot.footLabels as label, idx}
							<div
								class="foot-pill"
								class:contact={telemetry?.footContacts[idx] === true}
							>
								{label}
							</div>
						{/each}
					</div>
					{#if telemetry?.neural}
						<div class="neural-meta" data-testid="neural-telemetry">
							<span>Policy: <strong>{telemetry.neural.activeRole.toUpperCase()}</strong></span>
							<span>Infer: <strong>{telemetry.neural.lastInferMs.toFixed(2)} ms</strong></span>
							<span>Host: <strong>{telemetry.neural.hostSamplesSent}</strong> (NAK {telemetry.neural.hostNakCount})</span>
						</div>
					{/if}
				</section>

				<section class="panel">
					<div class="panel-header">
						<span>{activeRobot.jointCount} SERVOS (CLICK TO PIN/JAM)</span>
						{#if (telemetry?.pinnedJoints.length ?? 0) > 0}
							<button
								type="button"
								class="link-btn"
								onclick={() => controller?.clearPins()}
							>
								Clear ({telemetry?.pinnedJoints.length})
							</button>
						{/if}
					</div>
					<div class="servo-list">
						{#each activeRobot.jointLabels as label, idx}
							{@const deg = telemetry?.jointsDeg[idx] ?? 0}
							{@const cmdDeg = telemetry?.commandedDeg[idx] ?? 0}
							{@const pinned = telemetry?.pinnedJoints.includes(idx) ?? false}
							{@const stalled = ((telemetry?.stalledMask ?? 0) & (1 << idx)) !== 0}
							<button
								type="button"
								class="servo-row"
								data-testid={`servo-pin-${idx}`}
								class:pinned
								class:stalled
								onclick={() => controller?.toggleJointPin(idx)}
							>
								<span class="servo-name">J{idx} {label}</span>
								<div class="servo-bar">
									<div
										class="servo-cmd"
										style={`left: ${servoBarPct(cmdDeg)}%`}
									></div>
									<div
										class="servo-fill"
										style={`width: ${servoBarPct(deg)}%`}
									></div>
								</div>
								<span class="servo-val">
									{pinned ? "PIN" : stalled ? "STALL" : `${deg.toFixed(0)}°`}
								</span>
							</button>
						{/each}
					</div>
				</section>
			{:else}
				<section class="panel">
					<div class="panel-header">
						<span>PHYSICAL PERTURBATIONS</span>
					</div>
					<div class="action-grid">
						<button
							type="button"
							class="btn sm"
							data-testid="btn-push-x"
							onclick={() =>
								controller?.applyWrench([4.5, 0, 0.3], [0, 0.12, 0], 240, "Push +X")}
						>
							Push +X
						</button>
						<button
							type="button"
							class="btn sm"
							onclick={() =>
								controller?.applyWrench([0, 4.2, 0.2], [0.15, 0, 0], 240, "Push +Y")}
						>
							Push +Y
						</button>
						<button
							type="button"
							class="btn sm"
							onclick={() =>
								controller?.applyWrench([0, -4.2, 0.2], [-0.15, 0, 0], 240, "Push -Y")}
						>
							Push -Y
						</button>
						<button
							type="button"
							class="btn sm"
							data-testid="btn-shake"
							onclick={() =>
								controller?.applyWrench([0, 0, 9.5], [0.22, -0.18, 0.12], 420, "Pick Up & Shake")}
						>
							Pick Up &amp; Shake
						</button>
						<button
							type="button"
							class="btn sm"
							data-testid="btn-reset-pose"
							onclick={() => controller?.resetPose()}
						>
							Reset Pose
						</button>
						<button
							type="button"
							class="btn sm"
							class:primary={ui.balanceEnabled}
							disabled={!isStandalone}
							onclick={toggleBalance}
						>
							Self-Level: {ui.balanceEnabled ? "ON" : "OFF"}
						</button>
					</div>
				</section>

				<section class="panel">
					<div class="panel-header">
						<span>50 HZ RL ROLLOUT RECORDER</span>
						{#if telemetry?.recording.active}
							<span class="tag warn">REC {telemetry.recording.steps}</span>
						{/if}
					</div>
					<p class="small-note">
						Captures 50 Hz MuJoCo state, IMU, {activeRobot.jointCount}-joint commanded/measured angles,
						foot contacts, and downloads as <code>.jsonl</code> for offline training.
					</p>
					<input
						class="text-input"
						type="text"
						bind:value={ui.rolloutLabel}
						placeholder="rollout_name"
					/>
					<div class="record-row">
						{#if telemetry?.recording.active}
							<button
								type="button"
								class="btn danger sm"
								onclick={() => controller?.stopRecording()}
							>
								■ Stop &amp; Download .jsonl ({telemetry.recording.steps})
							</button>
						{:else}
							<button
								type="button"
								class="btn primary sm"
								onclick={() => controller?.startRecording(ui.rolloutLabel)}
							>
								● Start 50 Hz Recording
							</button>
						{/if}
					</div>
				</section>
			{/if}
		</aside>
	{/if}

	{#if ui.showCommsFeed}
		<aside
			class="comms-hud"
			class:mobile={ui.isMobile}
			data-testid="comms-hud"
			aria-label="Ainekio OS and Multiplayer Text Feed"
		>
			<div class="comms-head">
				<div class="comms-title-group">
					<span
						class="comms-status-dot"
						class:online={ui.snapshot.control.connected ||
							ui.snapshot.multiplayer.status === "connected"}
					></span>
					<strong>COMMS FEED</strong>
					<span class="comms-sub">
						{#if ui.snapshot.control.connected && ui.snapshot.multiplayer.status === "connected"}
							Ainekio OS + {ui.snapshot.multiplayer.roomName}
						{:else if ui.snapshot.control.connected}
							Linked to Ainekio OS
						{:else if ui.snapshot.multiplayer.status === "connected"}
							Room: {ui.snapshot.multiplayer.roomName}
						{:else}
							Standalone
						{/if}
					</span>
				</div>
				<div class="comms-head-actions">
					{#if ui.snapshot.commsMessages.length > 0}
						<button
							type="button"
							class="comms-mini-btn"
							onclick={() => controller?.clearCommsMessages()}
						>
							Clear
						</button>
					{/if}
					<button
						type="button"
						class="comms-mini-btn"
						aria-label="Minimize chat feed"
						onclick={toggleCommsFeed}
					>
						✕
					</button>
				</div>
			</div>

			<div class="comms-messages" data-testid="comms-messages">
				{#if ui.snapshot.commsMessages.length === 0}
					<p class="comms-empty">
						{#if ui.snapshot.control.connected}
							Type a message or click <strong>Tap to Talk</strong> — Ainekio OS replies appear here.
						{:else if ui.snapshot.multiplayer.status === "connected"}
							Connected to room <strong>{ui.snapshot.multiplayer.roomName}</strong>. Say hello!
						{:else}
							Link Body Control or join a Multiplayer Room to chat with Ainekio OS &amp; visitors.
						{/if}
					</p>
				{:else}
					{#each ui.snapshot.commsMessages as msg (msg.id)}
						<div class="comms-line" data-role={msg.role}>
							<span class="comms-sender" data-role={msg.role}>
								{#if msg.channel === "voice"}🎤 {/if}{msg.sender}:
							</span>
							<span class="comms-text">{msg.text}</span>
						</div>
					{/each}
				{/if}
			</div>

			<form class="comms-form" onsubmit={handleCommsSubmit}>
				<button
					type="button"
					class="comms-mic-btn"
					class:listening={ui.snapshot.micActive}
					title={ui.snapshot.micActive
						? "Tap to finish speaking and send"
						: "Tap to Talk"}
					onclick={() => void controller?.toggleMicrophone()}
				>
					{ui.snapshot.micActive ? "●" : "🎤"}
				</button>
				<input
					type="text"
					class="comms-input"
					data-testid="comms-input"
					bind:value={ui.commsInput}
					maxlength="400"
					placeholder={ui.snapshot.control.connected
						? "Message Ainekio OS..."
						: "Type a message..."}
				/>
				<button
					type="submit"
					class="comms-send-btn"
					data-testid="comms-send"
					disabled={ui.commsInput.trim().length === 0}
				>
					Send
				</button>
			</form>
		</aside>
	{/if}

	<!-- Bottom Status Ticker (Desktop) -->
	{#if !ui.isMobile}
		<footer class="bottom-bar">
			<span class="status-log" data-testid="status-log">{ui.snapshot.lastCommandLog}</span>
			<span class="controls-hint">
				{#if ui.snapshot.cameraMode === "orbit"}
					Orbit / Look Up: Drag · Pan: Shift+Drag · Zoom: Wheel · Fly: WASD / Arrows / QE
				{:else}
					Drive Robot: WASD / Arrow Keys · Strafe: Q/E · Stop: Release
				{/if}
			</span>
		</footer>
	{/if}

	<!-- Dedicated Mobile Layout HUD -->
	{#if ui.isMobile}
		<!-- Floating Transparent Thumb Drive Pad -->
		{#if ui.mobileTab === "drive"}
			<div class="mobile-drive-pad" data-testid="mobile-drive-pad">
				<div
					class="joystick mobile-joystick"
					bind:this={joystickEl}
					onpointerdown={onJoystickDown}
					onpointermove={onJoystickMove}
					onpointerup={onJoystickUp}
					onpointercancel={onJoystickUp}
					role="slider"
					tabindex="0"
					aria-label="Walk and steer joystick"
					aria-valuenow={Math.round(-ui.joyY * 100)}
				>
					<div class="joy-cross-h"></div>
					<div class="joy-cross-v"></div>
					<div
						class="joy-knob mobile-joy-knob"
						style={`transform: translate(${ui.joyX * 34}px, ${ui.joyY * 34}px)`}
					></div>
					<span class="joy-label top">FWD</span>
					<span class="joy-label bottom">REV</span>
					<span class="joy-label left">{ui.gait === "crab" ? "L-C" : "L"}</span>
					<span class="joy-label right">{ui.gait === "crab" ? "R-C" : "R"}</span>
				</div>

				<div class="mobile-quick-actions" class:dimmed={!isStandalone}>
					<button
						type="button"
						class="m-act-btn mode"
						class:active={ui.gait === "crab"}
						disabled={!isStandalone}
						onclick={() => (ui.gait = ui.gait === "crab" ? "walk" : "crab")}
					>
						{ui.gait === "crab" ? "Strafe" : "Turn"}
					</button>
					<button
						type="button"
						class="m-act-btn primary"
						data-testid="btn-stand"
						disabled={!isStandalone}
						onclick={() => controller?.sendClipOrPosture("stand")}
					>
						Stand
					</button>
					<button
						type="button"
						class="m-act-btn stop"
						data-testid="btn-stop"
						disabled={!isStandalone}
						onclick={() => controller?.sendStop(false)}
					>
						■ Stop
					</button>
					<button
						type="button"
						class="m-act-btn"
						disabled={!isStandalone}
						onclick={() => controller?.sendClipOrPosture("sit")}
					>
						Sit
					</button>
					<button
						type="button"
						class="m-act-btn"
						disabled={!isStandalone}
						onclick={() => controller?.sendClipOrPosture(waveMotionId)}
					>
						Wave
					</button>
					<button
						type="button"
						class="m-act-btn danger"
						data-testid="btn-estop"
						disabled={!isStandalone}
						onclick={() => controller?.sendStop(true)}
					>
						E-Stop
					</button>
				</div>
			</div>
		{/if}

		<!-- Scrollable Translucent Bottom Sheet (Poses / Servos / Sandbox) -->
		{#if ui.mobileTab === "poses" || ui.mobileTab === "servos" || ui.mobileTab === "sandbox"}
			<section class="mobile-sheet" data-testid="mobile-sheet" aria-label="Mobile Controls">
				<div class="mobile-sheet-head">
					<div class="mobile-sheet-title">
						{#if ui.mobileTab === "poses"}
							<span>POSES, FACE &amp; GAIT</span>
							<span class="tag ok">{isNeuralEngine ? "NEURAL" : "NATIVE"}</span>
						{:else if ui.mobileTab === "servos"}
							<span>{activeRobot.shortName} TELEMETRY &amp; {activeRobot.jointCount} SERVOS</span>
							<span class="tag" class:ok={telemetry?.armed}>
								{telemetry?.armed ? "ARMED" : "IDLE"}
							</span>
						{:else}
							<span>SANDBOX, AUDIO &amp; RL</span>
							{#if telemetry?.recording.active}
								<span class="tag warn">REC {telemetry.recording.steps}</span>
							{/if}
						{/if}
					</div>
					<button
						type="button"
						class="mobile-sheet-close"
						aria-label="Close panel"
						onclick={() => setMobileTab("none")}
					>
						✕
					</button>
				</div>

				<div class="mobile-sheet-body">
					{#if ui.mobileTab === "poses"}
						<div class="mobile-engine-strip" class:dimmed={!isStandalone}>
							<button
								type="button"
								class="chip m-chip"
								data-testid="engine-neural"
								class:active={isNeuralEngine}
								disabled={!isStandalone}
								onclick={() => setEngine("neural")}
							>
								Neural
							</button>
							<button
								type="button"
								class="chip m-chip"
								data-testid="engine-native"
								class:active={!isNeuralEngine}
								disabled={!isStandalone}
								onclick={() => setEngine("native")}
							>
								Native
							</button>
							<label class="mobile-speed-wrap">
								<span>Speed {ui.speed}%</span>
								<input
									type="range"
									min="25"
									max={ui.gait === "crab" ? 100 : isNeuralEngine ? 150 : 180}
									step="5"
									bind:value={ui.speed}
									disabled={!isStandalone}
								/>
							</label>
						</div>

						<div class="mobile-media-row">
							<div class="face-box mobile-media-box">
								<canvas
									bind:this={faceCanvasEl}
									width={SIM_FACE_WIDTH}
									height={SIM_FACE_HEIGHT}
									data-testid="face-mirror"
								></canvas>
								<span class="media-label">{activeRobot.displayLabel}</span>
							</div>
							<div class="cam-box mobile-media-box">
								{#if ui.snapshot.cameraPreviewDataUrl}
									<img
										src={ui.snapshot.cameraPreviewDataUrl}
										alt="Robot Chin Camera"
										data-testid="camera-pip"
									/>
								{:else}
									<div class="cam-placeholder">Chin Cam Ready</div>
								{/if}
								<button
									type="button"
									class="snap-btn"
									data-testid="btn-snap"
									onclick={() => void controller?.captureSnapshot()}
								>
									Snap
								</button>
							</div>
						</div>

						<div class="mobile-section-label">
							<span>{isNeuralEngine ? "NEURAL POSES & EMOTES" : "FIRMWARE CLIPS"}</span>
							<button
								type="button"
								class="chip m-chip mic-chip"
								class:active={ui.snapshot.micActive}
								disabled={!ui.snapshot.micSupported}
								onclick={() => void controller?.toggleMicrophone()}
							>
								{ui.snapshot.micActive ? "● Listening" : "🎤 Talk"}
							</button>
						</div>
						<div class="chip-grid mobile-chip-grid" class:dimmed={!isStandalone}>
							<button
								type="button"
								class="chip m-chip"
								data-testid="btn-stand"
								disabled={!isStandalone}
								onclick={() => controller?.sendClipOrPosture("stand")}
							>
								Stand
							</button>
							{#if isNeuralEngine && neuralMotionButtons.length > 0}
								{#each neuralMotionButtons as motion}
									<button
										type="button"
										class="chip m-chip"
										class:active={telemetry?.neural.activeMotionId === motion.id}
										data-testid={`clip-${motion.id}`}
										title={motion.sourceTitle}
										disabled={!isStandalone}
										onclick={() => controller?.sendClipOrPosture(motion.id)}
									>
										{motion.label}
									</button>
								{/each}
							{:else}
								{#each clipButtons as clip}
									<button
										type="button"
										class="chip m-chip"
										data-testid={`clip-${clip}`}
										disabled={!isStandalone}
										onclick={() => controller?.sendClipOrPosture(clip)}
									>
										{clip}
									</button>
								{/each}
							{/if}
						</div>

						<div class="mobile-section-label">
							<span>FACE EXPRESSIONS</span>
							<span class="tag">{telemetry?.face.name ?? "default"}</span>
						</div>
						<div class="chip-grid mobile-chip-grid" class:dimmed={!isStandalone}>
							{#each V2_FACE_EXPRESSIONS as expr}
								<button
									type="button"
									class="chip m-chip"
									data-testid={`face-${expr}`}
									class:active={telemetry?.face.name === expr}
									disabled={!isStandalone}
									onclick={() => controller?.sendFaceExpression(expr)}
								>
									{expr}
								</button>
							{/each}
						</div>
					{:else if ui.mobileTab === "servos"}
						<div class="mobile-metric-strip">
							<div class="metric">
								<span>Roll</span>
								<strong>{formatDeg(telemetry?.imu.rollDeg)}</strong>
							</div>
							<div class="metric">
								<span>Pitch</span>
								<strong>{formatDeg(telemetry?.imu.pitchDeg)}</strong>
							</div>
							<div class="metric">
								<span>Yaw</span>
								<strong>{formatDeg(telemetry?.imu.yawDeg)}</strong>
							</div>
							<div class="metric">
								<span>Batt</span>
								<strong>{telemetry ? `${telemetry.batteryVoltage.toFixed(1)}V` : "--"}</strong>
							</div>
						</div>

						<div class="foot-row mobile-foot-row">
							{#each activeRobot.footLabels as label, idx}
								<div
									class="foot-pill"
									class:contact={telemetry?.footContacts[idx] === true}
								>
									{label}
								</div>
							{/each}
						</div>

						{#if telemetry?.neural}
							<div class="neural-meta" data-testid="neural-telemetry">
								<span>Policy: <strong>{telemetry.neural.activeRole.toUpperCase()}</strong></span>
								<span>Infer: <strong>{telemetry.neural.lastInferMs.toFixed(2)} ms</strong></span>
								<span>Step: <strong>{telemetry.stepMs.toFixed(2)} ms</strong></span>
							</div>
						{/if}

						<div class="mobile-section-label">
							<span>{activeRobot.jointCount} SERVOS (TAP TO PIN/JAM)</span>
							{#if (telemetry?.pinnedJoints.length ?? 0) > 0}
								<button
									type="button"
									class="link-btn"
									onclick={() => controller?.clearPins()}
								>
									Clear ({telemetry?.pinnedJoints.length})
								</button>
							{/if}
						</div>

						<div class="servo-list">
							{#each activeRobot.jointLabels as label, idx}
								{@const deg = telemetry?.jointsDeg[idx] ?? 0}
								{@const cmdDeg = telemetry?.commandedDeg[idx] ?? 0}
								{@const pinned = telemetry?.pinnedJoints.includes(idx) ?? false}
								{@const stalled = ((telemetry?.stalledMask ?? 0) & (1 << idx)) !== 0}
								<button
									type="button"
									class="servo-row mobile-servo-row"
									data-testid={`servo-pin-${idx}`}
									class:pinned
									class:stalled
									onclick={() => controller?.toggleJointPin(idx)}
								>
									<span class="servo-name">J{idx} {label}</span>
									<div class="servo-bar">
										<div
											class="servo-cmd"
											style={`left: ${servoBarPct(cmdDeg)}%`}
										></div>
										<div
											class="servo-fill"
											style={`width: ${servoBarPct(deg)}%`}
										></div>
									</div>
									<span class="servo-val">
										{pinned ? "PIN" : stalled ? "STALL" : `${deg.toFixed(0)}°`}
									</span>
								</button>
							{/each}
						</div>
					{:else}
						<div class="mobile-section-label">
							<span>PHYSICAL PERTURBATIONS</span>
						</div>
						<div class="action-grid mobile-action-grid">
							<button
								type="button"
								class="btn m-btn"
								data-testid="btn-push-x"
								onclick={() =>
									controller?.applyWrench([4.5, 0, 0.3], [0, 0.12, 0], 240, "Push +X")}
							>
								Push +X
							</button>
							<button
								type="button"
								class="btn m-btn"
								onclick={() =>
									controller?.applyWrench([0, 4.2, 0.2], [0.15, 0, 0], 240, "Push +Y")}
							>
								Push +Y
							</button>
							<button
								type="button"
								class="btn m-btn"
								onclick={() =>
									controller?.applyWrench([0, -4.2, 0.2], [-0.15, 0, 0], 240, "Push -Y")}
							>
								Push -Y
							</button>
							<button
								type="button"
								class="btn m-btn"
								data-testid="btn-shake"
								onclick={() =>
									controller?.applyWrench([0, 0, 9.5], [0.22, -0.18, 0.12], 420, "Pick Up & Shake")}
							>
								Shake
							</button>
							<button
								type="button"
								class="btn m-btn"
								data-testid="btn-reset-pose"
								onclick={() => controller?.resetPose()}
							>
								Reset Pose
							</button>
							<button
								type="button"
								class="btn m-btn"
								class:primary={ui.balanceEnabled}
								disabled={!isStandalone}
								onclick={toggleBalance}
							>
								Balance: {ui.balanceEnabled ? "ON" : "OFF"}
							</button>
						</div>

						<div class="mobile-section-label">
							<span>AUDIO MIXER</span>
							<span class="audio-now-playing">
								♪ {ui.snapshot.audio.activeTrackLabel || "Silent"}
							</span>
						</div>
						<div class="mobile-audio-box">
							<label class="audio-slider-row">
								<span>Music {Math.round(ui.snapshot.audio.musicVolume * 100)}%</span>
								<input
									type="range"
									min="0"
									max="100"
									value={Math.round(ui.snapshot.audio.musicVolume * 100)}
									oninput={(e) =>
										controller?.setMusicVolume(
											Number((e.currentTarget as HTMLInputElement).value) / 100,
										)}
								/>
							</label>
							<label class="audio-slider-row">
								<span>SFX {Math.round(ui.snapshot.audio.sfxVolume * 100)}%</span>
								<input
									type="range"
									min="0"
									max="100"
									value={Math.round(ui.snapshot.audio.sfxVolume * 100)}
									oninput={(e) =>
										controller?.setSfxVolume(
											Number((e.currentTarget as HTMLInputElement).value) / 100,
										)}
								/>
							</label>
							<label class="audio-check-row">
								<input
									type="checkbox"
									checked={ui.snapshot.audio.footstepsEnabled}
									onchange={(e) =>
										controller?.setFootstepsEnabled(
											(e.currentTarget as HTMLInputElement).checked,
										)}
								/>
								<span>MuJoCo foot-contact taps</span>
							</label>
						</div>

						<div class="mobile-section-label">
							<span>BODY CONTROL &amp; 50 HZ RL RECORDER</span>
						</div>
						<div class="mobile-connect-row">
							<button
								type="button"
								class="connect-pill mobile-connect-btn"
								class:connected={ui.snapshot.control.connected}
								data-testid="open-connect-modal"
								onclick={() => (ui.showConnectModal = true)}
							>
								<span class="pill-dot"></span>
								{#if ui.snapshot.control.connected}
									Connected: {ui.snapshot.control.robotId}
								{:else}
									Connect External Body Control
								{/if}
							</button>
						</div>

						<input
							class="text-input"
							type="text"
							bind:value={ui.rolloutLabel}
							placeholder="rollout_name"
						/>
						<div class="record-row">
							{#if telemetry?.recording.active}
								<button
									type="button"
									class="btn danger m-btn"
									onclick={() => controller?.stopRecording()}
								>
									■ Stop &amp; Download .jsonl ({telemetry.recording.steps})
								</button>
							{:else}
								<button
									type="button"
									class="btn primary m-btn"
									onclick={() => controller?.startRecording(ui.rolloutLabel)}
								>
									● Start 50 Hz RL Recording
								</button>
							{/if}
						</div>

						<div class="mobile-status-inline" data-testid="status-log">
							{ui.snapshot.lastCommandLog}
						</div>
					{/if}
				</div>
			</section>
		{/if}

		<!-- Mobile Bottom Navigation Bar -->
		<nav class="mobile-nav" data-testid="mobile-nav" aria-label="Simulator Controls">
			<button
				type="button"
				class="mobile-nav-btn"
				data-testid="mobile-tab-drive"
				class:active={ui.mobileTab === "drive"}
				onclick={() => setMobileTab("drive")}
			>
				<span class="m-nav-icon" aria-hidden="true">🕹️</span>
				<span>Drive</span>
			</button>
			<button
				type="button"
				class="mobile-nav-btn"
				data-testid="mobile-tab-poses"
				class:active={ui.mobileTab === "poses"}
				onclick={() => setMobileTab("poses")}
			>
				<span class="m-nav-icon" aria-hidden="true">✨</span>
				<span>Poses</span>
			</button>
			<button
				type="button"
				class="mobile-nav-btn"
				data-testid="mobile-tab-servos"
				class:active={ui.mobileTab === "servos"}
				onclick={() => setMobileTab("servos")}
			>
				<span class="m-nav-icon" aria-hidden="true">⚙️</span>
				<span>Servos</span>
			</button>
			<button
				type="button"
				class="mobile-nav-btn"
				data-testid="mobile-tab-sandbox"
				class:active={ui.mobileTab === "sandbox"}
				onclick={() => setMobileTab("sandbox")}
			>
				<span class="m-nav-icon" aria-hidden="true">🧪</span>
				<span>Sandbox</span>
			</button>
			<button
				type="button"
				class="mobile-nav-btn"
				data-testid="mobile-tab-none"
				class:active={ui.mobileTab === "none"}
				onclick={() => setMobileTab("none")}
			>
				<span class="m-nav-icon" aria-hidden="true">👁️</span>
				<span>View</span>
			</button>
		</nav>
	{/if}
</div>

<style>
	:global(*) {
		box-sizing: border-box;
	}
	:global(html, body) {
		margin: 0;
		padding: 0;
		width: 100%;
		height: 100%;
		overflow: hidden;
		background: #070b14;
		color: #e2e8f0;
		font-family: "Inter", "Segoe UI", system-ui, -apple-system, sans-serif;
	}

	.sim-root {
		position: fixed;
		inset: 0;
		overflow: hidden;
		user-select: none;
	}
	.viewport-host {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
	}

	.loading-overlay {
		position: fixed;
		inset: 0;
		z-index: 40;
		display: flex;
		align-items: center;
		justify-content: center;
		background: radial-gradient(circle at center, rgba(15, 23, 42, 0.88), rgba(4, 7, 15, 0.97));
		backdrop-filter: blur(8px);
	}
	.loading-card {
		width: min(440px, 90vw);
		padding: 28px;
		border-radius: 16px;
		border: 1px solid rgba(56, 189, 248, 0.35);
		background: rgba(10, 17, 32, 0.92);
		text-align: center;
		box-shadow: 0 24px 60px rgba(0, 0, 0, 0.6);
	}
	.loading-card h1 {
		margin: 14px 0 8px;
		font-size: 18px;
		letter-spacing: 0.14em;
		color: #38bdf8;
	}
	.loading-card p {
		margin: 0 0 8px;
		font-size: 13px;
		color: #cbd5e1;
	}
	.loading-sub {
		font-size: 11px;
		color: #64748b;
	}
	.spinner {
		width: 34px;
		height: 34px;
		margin: 0 auto;
		border: 3px solid rgba(56, 189, 248, 0.22);
		border-top-color: #38bdf8;
		border-radius: 50%;
		animation: spin 0.85s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	.top-bar {
		position: fixed;
		top: 10px;
		left: 12px;
		right: 12px;
		z-index: 20;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 8px 14px;
		border-radius: 12px;
		background: rgba(9, 14, 26, 0.82);
		border: 1px solid rgba(148, 163, 184, 0.18);
		backdrop-filter: blur(12px);
		flex-wrap: wrap;
	}
	.brand-group {
		display: flex;
		align-items: center;
		gap: 10px;
	}
	.brand-dot {
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: #f59e0b;
		box-shadow: 0 0 10px rgba(245, 158, 11, 0.7);
	}
	.brand-dot.online {
		background: #22c55e;
		box-shadow: 0 0 12px rgba(34, 197, 94, 0.8);
	}
	.brand-title {
		font-size: 13px;
		font-weight: 700;
		letter-spacing: 0.1em;
		color: #f8fafc;
	}
	.brand-sub {
		font-size: 10px;
		color: #94a3b8;
	}
	.top-controls {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}
	.level-picker select {
		height: 30px;
		padding: 0 10px;
		border-radius: 8px;
		border: 1px solid rgba(148, 163, 184, 0.25);
		background: rgba(15, 23, 42, 0.92);
		color: #f1f5f9;
		font-size: 12px;
		cursor: pointer;
	}
	.segmented {
		display: inline-flex;
		border-radius: 8px;
		overflow: hidden;
		border: 1px solid rgba(148, 163, 184, 0.22);
		background: rgba(15, 23, 42, 0.75);
	}
	.segmented button {
		height: 30px;
		padding: 0 10px;
		border: none;
		background: transparent;
		color: #cbd5e1;
		font-size: 11px;
		font-weight: 600;
		cursor: pointer;
	}
	.segmented button:hover {
		background: rgba(56, 189, 248, 0.14);
	}
	.segmented button.active {
		background: rgba(14, 165, 233, 0.28);
		color: #7dd3fc;
	}
	.audio-control {
		position: relative;
		display: inline-flex;
		align-items: center;
		border-radius: 8px;
		border: 1px solid rgba(148, 163, 184, 0.22);
		background: rgba(15, 23, 42, 0.72);
	}
	.audio-btn,
	.audio-caret {
		height: 30px;
		border: none;
		background: transparent;
		color: #cbd5e1;
		font-size: 11px;
		cursor: pointer;
		display: inline-flex;
		align-items: center;
		gap: 5px;
	}
	.audio-btn {
		padding: 0 8px 0 9px;
		border-radius: 7px 0 0 7px;
	}
	.audio-btn.active {
		color: #7dd3fc;
		background: rgba(14, 165, 233, 0.16);
	}
	.audio-btn.muted {
		color: #94a3b8;
	}
	.audio-label {
		max-width: 112px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.audio-caret {
		padding: 0 7px;
		border-left: 1px solid rgba(148, 163, 184, 0.18);
		border-radius: 0 7px 7px 0;
		color: #94a3b8;
	}
	.audio-caret:hover,
	.audio-btn:hover {
		background: rgba(56, 189, 248, 0.14);
	}
	.audio-popover {
		position: absolute;
		top: calc(100% + 8px);
		right: 0;
		width: 248px;
		padding: 12px;
		border-radius: 12px;
		background: rgba(9, 14, 26, 0.94);
		border: 1px solid rgba(56, 189, 248, 0.3);
		box-shadow: 0 18px 42px rgba(0, 0, 0, 0.55);
		backdrop-filter: blur(14px);
		display: flex;
		flex-direction: column;
		gap: 10px;
		z-index: 30;
	}
	.audio-pop-head {
		display: flex;
		flex-direction: column;
		gap: 3px;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.08em;
		color: #94a3b8;
	}
	.audio-now-playing {
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0;
		color: #7dd3fc;
	}
	.audio-slider-row {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-size: 11px;
		color: #cbd5e1;
	}
	.audio-slider-row input[type="range"] {
		width: 100%;
		accent-color: #38bdf8;
	}
	.audio-check-row {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 11px;
		color: #cbd5e1;
		cursor: pointer;
	}
	.mp-control {
		position: relative;
		display: inline-flex;
		align-items: center;
	}
	.mp-menu-btn {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		height: 30px;
		padding: 0 10px;
		border-radius: 8px;
		border: 1px solid rgba(148, 163, 184, 0.24);
		background: rgba(15, 23, 42, 0.72);
		color: #cbd5e1;
		font-size: 11px;
		font-weight: 600;
		cursor: pointer;
	}
	.mp-menu-btn:hover {
		background: rgba(56, 189, 248, 0.14);
		border-color: rgba(56, 189, 248, 0.4);
	}
	.mp-menu-btn.connecting {
		border-color: rgba(56, 189, 248, 0.45);
		color: #7dd3fc;
	}
	.mp-menu-btn.connected {
		border-color: rgba(34, 197, 94, 0.52);
		background: rgba(21, 128, 61, 0.28);
		color: #bbf7d0;
	}
	.mp-dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: #64748b;
	}
	.mp-menu-btn.connecting .mp-dot {
		background: #38bdf8;
	}
	.mp-menu-btn.connected .mp-dot {
		background: #22c55e;
		box-shadow: 0 0 8px rgba(34, 197, 94, 0.7);
	}
	.mp-btn-label {
		max-width: 124px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.mp-unread-badge {
		min-width: 16px;
		height: 16px;
		padding: 0 4px;
		border-radius: 999px;
		background: #0ea5e9;
		color: #04121f;
		font-size: 10px;
		font-weight: 800;
		display: inline-flex;
		align-items: center;
		justify-content: center;
	}
	.mp-caret {
		color: #94a3b8;
		font-size: 10px;
	}
	.mp-mobile-btn {
		position: relative;
	}
	.mp-mobile-btn.mp-live {
		border-color: rgba(34, 197, 94, 0.55);
		background: rgba(21, 128, 61, 0.3);
	}
	.mp-mobile-dot {
		position: absolute;
		top: 3px;
		right: 3px;
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: #38bdf8;
	}
	.connect-pill {
		display: inline-flex;
		align-items: center;
		gap: 7px;
		height: 30px;
		padding: 0 12px;
		border-radius: 999px;
		border: 1px solid rgba(56, 189, 248, 0.35);
		background: rgba(14, 116, 144, 0.22);
		color: #bae6fd;
		font-size: 11px;
		font-weight: 600;
		cursor: pointer;
	}
	.connect-pill.connected {
		border-color: rgba(34, 197, 94, 0.5);
		background: rgba(21, 128, 61, 0.28);
		color: #bbf7d0;
	}
	.pill-dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: currentColor;
	}
	.ghost-btn {
		height: 30px;
		padding: 0 10px;
		border-radius: 8px;
		border: 1px solid rgba(148, 163, 184, 0.22);
		background: rgba(15, 23, 42, 0.7);
		color: #cbd5e1;
		font-size: 11px;
		cursor: pointer;
	}

	.dock {
		position: fixed;
		top: 64px;
		bottom: 38px;
		z-index: 15;
		display: flex;
		flex-direction: column;
		gap: 8px;
		overflow-y: auto;
		scrollbar-width: thin;
		pointer-events: auto;
	}
	.dock-left {
		left: 12px;
		width: 318px;
	}
	.dock-right {
		right: 12px;
		width: 286px;
	}

	.panel {
		padding: 10px 12px;
		border-radius: 12px;
		background: rgba(9, 14, 26, 0.8);
		border: 1px solid rgba(148, 163, 184, 0.16);
		backdrop-filter: blur(12px);
	}
	.panel.dimmed {
		opacity: 0.65;
	}
	.panel-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 8px;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.09em;
		color: #94a3b8;
	}
	.tag {
		padding: 2px 6px;
		border-radius: 999px;
		font-size: 9px;
		background: rgba(51, 65, 85, 0.7);
		color: #cbd5e1;
	}
	.tag.ok {
		background: rgba(21, 128, 61, 0.35);
		color: #86efac;
	}
	.tag.warn {
		background: rgba(180, 83, 9, 0.38);
		color: #fde68a;
	}

	.media-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 8px;
	}
	.face-box,
	.cam-box {
		position: relative;
		border-radius: 8px;
		overflow: hidden;
		background: #020617;
		border: 1px solid rgba(148, 163, 184, 0.22);
		aspect-ratio: 16 / 10;
	}
	.face-box canvas,
	.cam-box img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}
	.cam-placeholder {
		width: 100%;
		height: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 10px;
		color: #64748b;
	}
	.media-label {
		position: absolute;
		bottom: 4px;
		left: 5px;
		font-size: 9px;
		padding: 1px 4px;
		border-radius: 4px;
		background: rgba(2, 6, 23, 0.75);
		color: #94a3b8;
	}
	.snap-btn {
		position: absolute;
		bottom: 4px;
		right: 4px;
		padding: 2px 7px;
		border-radius: 5px;
		border: 1px solid rgba(56, 189, 248, 0.45);
		background: rgba(2, 6, 23, 0.8);
		color: #7dd3fc;
		font-size: 10px;
		font-weight: 600;
		cursor: pointer;
	}

	.gait-row {
		display: flex;
		align-items: center;
		gap: 5px;
		margin-bottom: 10px;
	}
	.engine-row {
		display: flex;
		align-items: center;
		gap: 5px;
		margin-bottom: 8px;
		flex-wrap: wrap;
	}
	.policy-tag {
		margin-left: auto;
		font-size: 9px;
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		color: #38bdf8;
		opacity: 0.85;
	}
	.neural-meta {
		display: flex;
		justify-content: space-between;
		gap: 6px;
		margin-top: 8px;
		padding-top: 6px;
		border-top: 1px solid rgba(148, 163, 184, 0.14);
		font-size: 10px;
		color: #94a3b8;
	}
	.neural-meta strong {
		color: #e2e8f0;
		font-weight: 600;
	}
	.speed-slider {
		margin-left: auto;
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: 10px;
		color: #94a3b8;
	}
	.speed-slider input {
		width: 72px;
		accent-color: #38bdf8;
	}

	.drive-area {
		display: grid;
		grid-template-columns: 112px 1fr;
		gap: 10px;
		align-items: center;
	}
	.joystick {
		position: relative;
		width: 110px;
		height: 110px;
		border-radius: 50%;
		background: radial-gradient(circle, rgba(30, 41, 59, 0.85), rgba(15, 23, 42, 0.95));
		border: 1px solid rgba(56, 189, 248, 0.3);
		touch-action: none;
		cursor: crosshair;
	}
	.joy-cross-h,
	.joy-cross-v {
		position: absolute;
		background: rgba(148, 163, 184, 0.16);
		pointer-events: none;
	}
	.joy-cross-h {
		left: 10px;
		right: 10px;
		top: 50%;
		height: 1px;
	}
	.joy-cross-v {
		top: 10px;
		bottom: 10px;
		left: 50%;
		width: 1px;
	}
	.joy-knob {
		position: absolute;
		top: 50%;
		left: 50%;
		width: 28px;
		height: 28px;
		margin-left: -14px;
		margin-top: -14px;
		border-radius: 50%;
		background: linear-gradient(145deg, #38bdf8, #0284c7);
		border: 2px solid #e0f2fe;
		box-shadow: 0 4px 12px rgba(14, 165, 233, 0.5);
		pointer-events: none;
	}
	.joy-label {
		position: absolute;
		font-size: 8px;
		font-weight: 700;
		color: #64748b;
		pointer-events: none;
	}
	.joy-label.top {
		top: 5px;
		left: 50%;
		transform: translateX(-50%);
	}
	.joy-label.bottom {
		bottom: 5px;
		left: 50%;
		transform: translateX(-50%);
	}
	.joy-label.left {
		left: 6px;
		top: 50%;
		transform: translateY(-50%);
	}
	.joy-label.right {
		right: 6px;
		top: 50%;
		transform: translateY(-50%);
	}

	.quick-drive {
		display: flex;
		flex-direction: column;
		gap: 5px;
	}
	.dpad-row,
	.posture-row {
		display: flex;
		justify-content: center;
		gap: 4px;
	}
	.posture-row {
		margin-top: 4px;
	}

	.btn {
		padding: 6px 10px;
		border-radius: 7px;
		border: 1px solid rgba(148, 163, 184, 0.25);
		background: rgba(30, 41, 59, 0.85);
		color: #e2e8f0;
		font-size: 11px;
		font-weight: 600;
		cursor: pointer;
	}
	.btn:hover:not(:disabled) {
		background: rgba(51, 65, 85, 0.95);
		border-color: rgba(56, 189, 248, 0.45);
	}
	.btn:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}
	.btn.sm {
		padding: 4px 7px;
		font-size: 10px;
	}
	.btn.primary {
		background: rgba(14, 165, 233, 0.3);
		border-color: rgba(56, 189, 248, 0.55);
		color: #e0f2fe;
	}
	.btn.danger {
		background: rgba(185, 28, 28, 0.35);
		border-color: rgba(248, 113, 113, 0.55);
		color: #fecaca;
	}
	.stop-btn {
		background: rgba(217, 119, 6, 0.28);
		border-color: rgba(251, 191, 36, 0.45);
		color: #fef3c7;
	}

	.chip-grid {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
	}
	.chip {
		padding: 4px 8px;
		border-radius: 6px;
		border: 1px solid rgba(148, 163, 184, 0.22);
		background: rgba(15, 23, 42, 0.8);
		color: #cbd5e1;
		font-size: 10px;
		font-weight: 600;
		cursor: pointer;
		text-transform: capitalize;
	}
	.chip:hover:not(:disabled) {
		border-color: rgba(56, 189, 248, 0.55);
		color: #f8fafc;
	}
	.chip.active {
		background: rgba(14, 165, 233, 0.32);
		border-color: #38bdf8;
		color: #e0f2fe;
	}
	.mic-chip.active {
		background: rgba(220, 38, 38, 0.35);
		border-color: #f87171;
		color: #fecaca;
	}

	.tab-bar {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 4px;
		padding: 4px;
		border-radius: 10px;
		background: rgba(9, 14, 26, 0.82);
		border: 1px solid rgba(148, 163, 184, 0.16);
	}
	.tab-bar button {
		padding: 6px;
		border-radius: 7px;
		border: none;
		background: transparent;
		color: #94a3b8;
		font-size: 11px;
		font-weight: 600;
		cursor: pointer;
	}
	.tab-bar button.active {
		background: rgba(56, 189, 248, 0.22);
		color: #7dd3fc;
	}

	.metric-grid {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 6px;
		margin-bottom: 8px;
	}
	.metric {
		padding: 6px 8px;
		border-radius: 7px;
		background: rgba(15, 23, 42, 0.72);
		border: 1px solid rgba(148, 163, 184, 0.12);
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		font-size: 11px;
	}
	.metric span {
		color: #94a3b8;
		font-size: 10px;
	}
	.metric strong {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		color: #f1f5f9;
	}
	.foot-row {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 5px;
	}
	.foot-pill {
		padding: 4px 0;
		border-radius: 6px;
		text-align: center;
		font-size: 10px;
		font-weight: 700;
		background: rgba(15, 23, 42, 0.8);
		border: 1px solid rgba(148, 163, 184, 0.16);
		color: #64748b;
	}
	.foot-pill.contact {
		background: rgba(21, 128, 61, 0.35);
		border-color: rgba(74, 222, 128, 0.5);
		color: #86efac;
	}

	.servo-list {
		display: flex;
		flex-direction: column;
		gap: 3px;
	}
	.servo-row {
		display: grid;
		grid-template-columns: 82px 1fr 38px;
		align-items: center;
		gap: 6px;
		padding: 3px 5px;
		border-radius: 5px;
		border: 1px solid transparent;
		background: rgba(15, 23, 42, 0.55);
		color: #cbd5e1;
		font-size: 10px;
		cursor: pointer;
		text-align: left;
	}
	.servo-row:hover {
		border-color: rgba(56, 189, 248, 0.35);
	}
	.servo-row.pinned,
	.servo-row.stalled {
		background: rgba(153, 27, 27, 0.35);
		border-color: rgba(248, 113, 113, 0.5);
		color: #fecaca;
	}
	.servo-name {
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.servo-bar {
		position: relative;
		height: 6px;
		border-radius: 999px;
		background: rgba(51, 65, 85, 0.7);
		overflow: hidden;
	}
	.servo-fill {
		height: 100%;
		background: linear-gradient(90deg, #0284c7, #38bdf8);
	}
	.servo-row.pinned .servo-fill,
	.servo-row.stalled .servo-fill {
		background: #ef4444;
	}
	.servo-cmd {
		position: absolute;
		top: 0;
		bottom: 0;
		width: 2px;
		background: #fde047;
	}
	.servo-val {
		text-align: right;
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 9px;
	}

	.action-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 6px;
	}
	.small-note {
		margin: 0 0 8px;
		font-size: 11px;
		line-height: 1.4;
		color: #94a3b8;
	}
	.text-input {
		width: 100%;
		margin-bottom: 8px;
		padding: 6px 8px;
		border-radius: 7px;
		border: 1px solid rgba(148, 163, 184, 0.25);
		background: rgba(15, 23, 42, 0.9);
		color: #f1f5f9;
		font-size: 11px;
	}
	.record-row {
		display: flex;
	}
	.record-row .btn {
		width: 100%;
	}
	.link-btn {
		border: none;
		background: transparent;
		color: #38bdf8;
		font-size: 10px;
		cursor: pointer;
	}

	.bottom-bar {
		position: fixed;
		left: 12px;
		right: 12px;
		bottom: 8px;
		z-index: 15;
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 5px 12px;
		border-radius: 8px;
		background: rgba(9, 14, 26, 0.78);
		border: 1px solid rgba(148, 163, 184, 0.14);
		font-size: 11px;
		color: #94a3b8;
	}
	.status-log {
		color: #e2e8f0;
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 11px;
	}

	.modal-backdrop {
		position: fixed;
		inset: 0;
		z-index: 35;
		display: flex;
		align-items: center;
		justify-content: center;
		background: rgba(2, 6, 23, 0.72);
		backdrop-filter: blur(5px);
	}
	.modal-card {
		width: min(490px, 92vw);
		max-height: 88dvh;
		overflow-y: auto;
		padding: 20px;
		border-radius: 14px;
		background: #0b1220;
		border: 1px solid rgba(56, 189, 248, 0.35);
		box-shadow: 0 24px 60px rgba(0, 0, 0, 0.65);
		user-select: text;
	}
	.modal-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 10px;
	}
	.modal-header h2 {
		margin: 0;
		font-size: 15px;
		color: #f8fafc;
	}
	.close-btn {
		border: none;
		background: transparent;
		color: #94a3b8;
		font-size: 16px;
		cursor: pointer;
	}
	.modal-desc {
		margin: 0 0 12px;
		font-size: 12px;
		line-height: 1.5;
		color: #94a3b8;
	}
	.bc-presets {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin-bottom: 12px;
	}
	.bc-reconnect-row {
		margin: 2px 0 8px;
	}
	.field-group {
		display: flex;
		flex-direction: column;
		gap: 5px;
		margin-bottom: 10px;
	}
	.field-row {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 10px;
	}
	.field-group label {
		font-size: 11px;
		color: #cbd5e1;
	}
	.field-group input {
		padding: 8px 10px;
		border-radius: 8px;
		border: 1px solid rgba(148, 163, 184, 0.28);
		background: #020617;
		color: #f8fafc;
		font-size: 12px;
	}
	.modal-note {
		margin: 10px 0 14px;
		padding: 9px 11px;
		border-radius: 8px;
		background: rgba(14, 116, 144, 0.16);
		border: 1px solid rgba(56, 189, 248, 0.22);
		font-size: 11px;
		line-height: 1.45;
		color: #bae6fd;
	}
	.modal-actions {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
	}
	.error-banner {
		margin: 8px 0;
		padding: 8px 10px;
		border-radius: 8px;
		background: rgba(185, 28, 28, 0.25);
		border: 1px solid rgba(248, 113, 113, 0.45);
		color: #fecaca;
		font-size: 11px;
	}
	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
	}

	/* === Mobile Layout Styles === */
	.top-bar.mobile {
		top: max(6px, env(safe-area-inset-top));
		left: 8px;
		right: 8px;
		padding: 6px 8px;
		gap: 0;
		flex-wrap: nowrap;
		border-radius: 11px;
		background: rgba(9, 14, 26, 0.76);
	}
	.mobile-top-row {
		width: 100%;
		display: flex;
		align-items: center;
		gap: 6px;
		min-width: 0;
	}
	.mobile-top-row .brand-dot {
		flex: 0 0 auto;
		width: 8px;
		height: 8px;
	}
	.mobile-select-wrap {
		display: flex;
		min-width: 0;
	}
	.mobile-select-wrap.robot {
		flex: 0 0 auto;
	}
	.mobile-select-wrap.level {
		flex: 1 1 auto;
	}
	.mobile-select-wrap select {
		width: 100%;
		height: 32px;
		padding: 0 6px;
		border-radius: 8px;
		border: 1px solid rgba(148, 163, 184, 0.25);
		background: rgba(15, 23, 42, 0.9);
		color: #f1f5f9;
		font-size: 12px;
		font-weight: 600;
		min-width: 0;
		text-overflow: ellipsis;
	}
	.mobile-top-btn {
		flex: 0 0 auto;
		height: 32px;
		border-radius: 8px;
		border: 1px solid rgba(148, 163, 184, 0.24);
		background: rgba(15, 23, 42, 0.85);
		color: #e2e8f0;
		font-size: 11px;
		font-weight: 700;
		cursor: pointer;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: 0 8px;
		-webkit-tap-highlight-color: transparent;
	}
	.mobile-top-btn.icon {
		width: 32px;
		padding: 0;
		font-size: 14px;
	}
	.mobile-top-btn.active {
		border-color: rgba(56, 189, 248, 0.55);
		background: rgba(14, 165, 233, 0.24);
		color: #7dd3fc;
	}

	.mobile-drive-pad {
		position: fixed;
		left: 10px;
		right: 10px;
		bottom: calc(64px + env(safe-area-inset-bottom));
		z-index: 16;
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
		gap: 12px;
		pointer-events: none;
	}
	.mobile-joystick {
		pointer-events: auto;
		width: 104px;
		height: 104px;
		background: radial-gradient(circle, rgba(15, 23, 42, 0.52), rgba(7, 11, 20, 0.72));
		border: 1.5px solid rgba(56, 189, 248, 0.42);
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.42);
		backdrop-filter: blur(6px);
	}
	.mobile-joy-knob {
		width: 30px;
		height: 30px;
		margin-left: -15px;
		margin-top: -15px;
	}
	.mobile-quick-actions {
		pointer-events: auto;
		display: grid;
		grid-template-columns: repeat(2, minmax(66px, auto));
		gap: 6px;
		padding: 7px;
		border-radius: 14px;
		background: rgba(9, 14, 26, 0.64);
		border: 1px solid rgba(148, 163, 184, 0.2);
		backdrop-filter: blur(8px);
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.42);
	}
	.mobile-quick-actions.dimmed {
		opacity: 0.6;
	}
	.m-act-btn {
		min-height: 32px;
		padding: 5px 10px;
		border-radius: 8px;
		border: 1px solid rgba(148, 163, 184, 0.25);
		background: rgba(30, 41, 59, 0.8);
		color: #e2e8f0;
		font-size: 11px;
		font-weight: 700;
		cursor: pointer;
		-webkit-tap-highlight-color: transparent;
	}
	.m-act-btn:disabled {
		opacity: 0.45;
	}
	.m-act-btn.mode.active {
		background: rgba(14, 165, 233, 0.34);
		border-color: #38bdf8;
		color: #e0f2fe;
	}
	.m-act-btn.primary {
		background: rgba(14, 165, 233, 0.32);
		border-color: rgba(56, 189, 248, 0.58);
		color: #e0f2fe;
	}
	.m-act-btn.stop {
		background: rgba(217, 119, 6, 0.3);
		border-color: rgba(251, 191, 36, 0.5);
		color: #fef3c7;
	}
	.m-act-btn.danger {
		background: rgba(185, 28, 28, 0.38);
		border-color: rgba(248, 113, 113, 0.58);
		color: #fecaca;
	}

	.mobile-sheet {
		position: fixed;
		left: 8px;
		right: 8px;
		bottom: calc(64px + env(safe-area-inset-bottom));
		max-height: 40dvh;
		z-index: 18;
		display: flex;
		flex-direction: column;
		border-radius: 14px;
		background: rgba(9, 14, 26, 0.86);
		border: 1px solid rgba(148, 163, 184, 0.22);
		backdrop-filter: blur(14px);
		box-shadow: 0 -10px 32px rgba(0, 0, 0, 0.5);
		overflow: hidden;
	}
	.mobile-sheet-head {
		flex: 0 0 auto;
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 8px 12px;
		border-bottom: 1px solid rgba(148, 163, 184, 0.14);
		background: rgba(15, 23, 42, 0.55);
	}
	.mobile-sheet-title {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.09em;
		color: #cbd5e1;
	}
	.mobile-sheet-close {
		width: 26px;
		height: 26px;
		border-radius: 6px;
		border: 1px solid rgba(148, 163, 184, 0.2);
		background: rgba(30, 41, 59, 0.7);
		color: #cbd5e1;
		font-size: 12px;
		cursor: pointer;
	}
	.mobile-sheet-body {
		flex: 1 1 auto;
		overflow-y: auto;
		-webkit-overflow-scrolling: touch;
		padding: 10px 12px 12px;
		display: flex;
		flex-direction: column;
		gap: 10px;
	}
	.mobile-engine-strip {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-wrap: wrap;
	}
	.mobile-speed-wrap {
		margin-left: auto;
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: 11px;
		color: #cbd5e1;
	}
	.mobile-speed-wrap input {
		width: 86px;
		accent-color: #38bdf8;
	}
	.mobile-media-row {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 8px;
	}
	.mobile-media-box {
		width: 100%;
		aspect-ratio: auto;
		height: 74px;
	}
	.mobile-section-label {
		display: flex;
		align-items: center;
		justify-content: space-between;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.08em;
		color: #94a3b8;
	}
	.mobile-chip-grid {
		gap: 6px;
	}
	.m-chip {
		min-height: 30px;
		padding: 5px 10px;
		font-size: 11px;
	}
	.mobile-metric-strip {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 5px;
	}
	.mobile-metric-strip .metric {
		flex-direction: column;
		align-items: flex-start;
		gap: 2px;
		padding: 5px 7px;
	}
	.mobile-foot-row {
		margin-top: -2px;
	}
	.mobile-servo-row {
		min-height: 30px;
		padding: 5px 7px;
		font-size: 11px;
	}
	.mobile-action-grid {
		grid-template-columns: repeat(3, 1fr);
		gap: 6px;
	}
	.m-btn {
		min-height: 34px;
		padding: 6px 8px;
		font-size: 11px;
	}
	.mobile-audio-box {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 8px 10px;
		border-radius: 9px;
		background: rgba(15, 23, 42, 0.65);
		border: 1px solid rgba(148, 163, 184, 0.14);
	}
	.mobile-connect-row {
		display: flex;
	}
	.mobile-connect-btn {
		width: 100%;
		justify-content: center;
		height: 34px;
	}
	.mobile-status-inline {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 10px;
		color: #94a3b8;
		padding-top: 2px;
	}

	.mobile-nav {
		position: fixed;
		left: 0;
		right: 0;
		bottom: 0;
		z-index: 20;
		display: grid;
		grid-template-columns: repeat(5, 1fr);
		gap: 4px;
		padding: 6px 8px max(8px, env(safe-area-inset-bottom));
		background: rgba(9, 14, 26, 0.88);
		border-top: 1px solid rgba(148, 163, 184, 0.18);
		backdrop-filter: blur(14px);
	}
	.mobile-nav-btn {
		min-height: 44px;
		padding: 4px 2px;
		border-radius: 9px;
		border: 1px solid transparent;
		background: transparent;
		color: #94a3b8;
		font-size: 10px;
		font-weight: 700;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 2px;
		cursor: pointer;
		-webkit-tap-highlight-color: transparent;
	}
	.mobile-nav-btn .m-nav-icon {
		font-size: 14px;
		line-height: 1;
	}
	.mobile-nav-btn.active {
		background: rgba(14, 165, 233, 0.24);
		border-color: rgba(56, 189, 248, 0.45);
		color: #e0f2fe;
	}

	@media (max-width: 520px) {
		.field-row {
			grid-template-columns: 1fr;
		}
	}

	@media (max-height: 520px) and (pointer: coarse) {
		.top-bar.mobile {
			padding: 4px 8px;
		}
		.mobile-select-wrap select,
		.mobile-top-btn {
			height: 28px;
			font-size: 11px;
		}
		.mobile-nav {
			padding: 4px 8px max(4px, env(safe-area-inset-bottom));
		}
		.mobile-nav-btn {
			min-height: 36px;
			flex-direction: row;
			gap: 5px;
		}
		.mobile-drive-pad {
			bottom: calc(48px + env(safe-area-inset-bottom));
		}
		.mobile-joystick {
			width: 88px;
			height: 88px;
		}
		.mobile-sheet {
			bottom: calc(48px + env(safe-area-inset-bottom));
			max-height: 56dvh;
		}
	}

	/* Top-bar Tap to Talk & Comms Feed HUD */
	.top-talk-btn,
	.top-comms-btn {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		height: 30px;
		padding: 0 11px;
		border-radius: 999px;
		border: 1px solid rgba(148, 163, 184, 0.28);
		background: rgba(15, 23, 42, 0.78);
		color: #e2e8f0;
		font-size: 12px;
		font-weight: 600;
		cursor: pointer;
		transition: all 0.15s ease;
	}
	.top-talk-btn:hover,
	.top-comms-btn:hover {
		border-color: rgba(56, 189, 248, 0.55);
		background: rgba(15, 23, 42, 0.94);
	}
	.top-comms-btn.active {
		border-color: rgba(56, 189, 248, 0.6);
		background: rgba(14, 116, 144, 0.28);
		color: #e0f2fe;
	}
	.talk-dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: #94a3b8;
	}
	.top-talk-btn.listening {
		border-color: rgba(248, 113, 113, 0.85);
		background: rgba(153, 27, 27, 0.45);
		color: #fecaca;
	}
	.top-talk-btn.listening .talk-dot {
		background: #ef4444;
		box-shadow: 0 0 8px #ef4444;
	}

	.comms-hud {
		position: fixed;
		left: 50%;
		bottom: 42px;
		transform: translateX(-50%);
		width: min(460px, calc(100vw - 640px));
		min-width: 320px;
		max-height: 240px;
		z-index: 28;
		display: flex;
		flex-direction: column;
		border-radius: 14px;
		background: rgba(8, 13, 24, 0.82);
		border: 1px solid rgba(148, 163, 184, 0.22);
		backdrop-filter: blur(12px);
		box-shadow: 0 12px 32px rgba(0, 0, 0, 0.5);
		overflow: hidden;
		user-select: text;
	}
	.comms-hud.mobile {
		left: 10px;
		right: 10px;
		bottom: calc(64px + env(safe-area-inset-bottom));
		transform: none;
		width: auto;
		min-width: 0;
		max-height: 190px;
	}
	.comms-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		padding: 6px 10px;
		border-bottom: 1px solid rgba(148, 163, 184, 0.14);
		background: rgba(15, 23, 42, 0.65);
		font-size: 11px;
	}
	.comms-title-group {
		display: flex;
		align-items: center;
		gap: 6px;
		min-width: 0;
	}
	.comms-title-group strong {
		letter-spacing: 0.06em;
		color: #e2e8f0;
		font-size: 10.5px;
	}
	.comms-sub {
		color: #94a3b8;
		font-size: 11px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.comms-status-dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: #64748b;
		flex-shrink: 0;
	}
	.comms-status-dot.online {
		background: #22c55e;
		box-shadow: 0 0 6px rgba(34, 197, 94, 0.7);
	}
	.comms-head-actions {
		display: flex;
		align-items: center;
		gap: 4px;
	}
	.comms-mini-btn {
		padding: 2px 7px;
		border-radius: 6px;
		border: 1px solid rgba(148, 163, 184, 0.24);
		background: rgba(15, 23, 42, 0.6);
		color: #cbd5e1;
		font-size: 10.5px;
		cursor: pointer;
	}
	.comms-mini-btn:hover {
		border-color: rgba(56, 189, 248, 0.5);
		color: #f8fafc;
	}
	.comms-messages {
		flex: 1;
		min-height: 74px;
		max-height: 148px;
		overflow-y: auto;
		padding: 8px 10px;
		display: flex;
		flex-direction: column;
		gap: 5px;
		font-size: 12.5px;
		line-height: 1.38;
	}
	.comms-empty {
		margin: auto 0;
		color: #94a3b8;
		font-size: 11.5px;
		text-align: center;
	}
	.comms-line {
		word-break: break-word;
	}
	.comms-sender {
		font-weight: 700;
		margin-right: 5px;
		color: #38bdf8;
	}
	.comms-sender[data-role="robot"] {
		color: #34d399;
	}
	.comms-sender[data-role="peer"] {
		color: #c084fc;
	}
	.comms-sender[data-role="system"] {
		color: #fbbf24;
	}
	.comms-text {
		color: #f1f5f9;
	}
	.comms-line[data-role="system"] .comms-text {
		color: #fde68a;
		font-size: 11.5px;
	}
	.comms-form {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 6px 8px;
		border-top: 1px solid rgba(148, 163, 184, 0.16);
		background: rgba(15, 23, 42, 0.72);
	}
	.comms-mic-btn {
		width: 30px;
		height: 28px;
		border-radius: 7px;
		border: 1px solid rgba(148, 163, 184, 0.28);
		background: rgba(15, 23, 42, 0.85);
		color: #e2e8f0;
		font-size: 13px;
		cursor: pointer;
		flex-shrink: 0;
	}
	.comms-mic-btn.listening {
		border-color: rgba(248, 113, 113, 0.85);
		background: rgba(185, 28, 28, 0.55);
		color: #fecaca;
	}
	.comms-input {
		flex: 1;
		min-width: 0;
		height: 28px;
		padding: 0 9px;
		border-radius: 7px;
		border: 1px solid rgba(148, 163, 184, 0.28);
		background: rgba(7, 11, 20, 0.85);
		color: #f8fafc;
		font-size: 12.5px;
		outline: none;
	}
	.comms-input:focus {
		border-color: rgba(56, 189, 248, 0.7);
	}
	.comms-send-btn {
		height: 28px;
		padding: 0 11px;
		border-radius: 7px;
		border: 1px solid rgba(56, 189, 248, 0.55);
		background: rgba(14, 116, 144, 0.45);
		color: #e0f2fe;
		font-size: 12px;
		font-weight: 600;
		cursor: pointer;
	}
	.comms-send-btn:disabled {
		opacity: 0.45;
		cursor: default;
	}
</style>

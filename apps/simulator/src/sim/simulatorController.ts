/**
 * Main-thread orchestrator for simulator.ainek.io.
 *
 * Bridges:
 *   1. Dedicated MuJoCo WASM + ESP32-P4 Firmware Web Worker (500 Hz physics / 50 Hz firmware)
 *   2. Three.js SimulatorViewport (ainekio-v2.glb four-bar rig, ST7789 face texture, OV5647 chin cam)
 *   3. Dual-mode control transport:
 *      - Standalone Mode (default): built-in Cockpit sends authentic protocol-v1 JSON frames
 *        directly into virtual_body.c (zero local software required).
 *      - External Body Control Mode: browser opens a direct WebSocket to ws:// or wss://
 *        Body Control (/robot) speaking native protocol-v1 JSON + binary frames.
 */

import { BrowserRobotAudioAdapter } from "@ainekio/engine/adapters/browser";
import {
	type BrowserMultiplayerClient,
	type MultiplayerSnapshot,
	createBrowserMultiplayerClient,
	normalizeRoomName,
} from "../multiplayer/index.js";
import { SimulatorViewport } from "../viewport/simulatorViewport";
import { WorldAudioEngine } from "../viewport/worldAudio";
import {
	type BodyControlLaunchBundle,
	type LocomotionEngineMode,
	type NeuralMotionCatalogItem,
	PROTOCOL_BIN_SPEAKER_PCM,
	type RobotModelId,
	type RobotTelemetryState,
	type SimulatorCameraMode,
	type SimulatorCommsMessage,
	type SimulatorLaunchConfig,
	type SimulatorLevelId,
	type SimulatorUiSnapshot,
	V2_CLIP_ACTIONS,
	type WorkerInboundMessage,
	type WorkerOutboundMessage,
	type WorldSfxId,
	cameraResolutionDimensions,
	decodeProtocolBinaryFrame,
	getRobotModelDescriptor,
	isNonRetryableBodyControlCloseCode,
	mujocoPositionToThree,
	mujocoQuaternionToThreeXyzw,
	normalizeBodyControlUrl,
	parseSimulatorLaunchParams,
} from "./contracts";
import { getSimulatorLevel, loadSimulatorLevel } from "./levels";

const DEFAULT_BODY_CONTROL_URL = "ws://127.0.0.1:8790/robot";
const DEFAULT_ROBOT_ID = "ainekio-v2-sim";
const STANDALONE_EPOCH = 1;

export type WalkGaitMode = "walk" | "run" | "crab";

export type SimulatorControllerCallbacks = {
	readonly onSnapshot: (snapshot: SimulatorUiSnapshot) => void;
	readonly onFaceRgba?: (
		width: number,
		height: number,
		rgba: Uint8Array,
	) => void;
};

const BC_STORAGE_KEY = "ainekio.sim.bodyControl.v1";
const BC_SESSION_TOKEN_KEY = "ainekio.sim.bodyControlToken.v1";
const BC_RECONNECT_DELAYS_MS = [1500, 3000, 6000, 10000] as const;

export type SavedBodyControlSettings = {
	readonly url: string;
	readonly robotId: string;
	readonly autoReconnect: boolean;
};

export type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export function loadSavedBodyControlSettings(options?: {
	readonly localStore?: StorageLike | null;
	readonly sessionStore?: StorageLike | null;
	readonly locationSearch?: string;
}): SavedBodyControlSettings & { readonly token: string } {
	let url = DEFAULT_BODY_CONTROL_URL;
	let robotId = DEFAULT_ROBOT_ID;
	let autoReconnect = true;
	let token = "";
	const localStore =
		options && "localStore" in options
			? options.localStore
			: typeof window !== "undefined"
				? window.localStorage
				: null;
	const sessionStore =
		options && "sessionStore" in options
			? options.sessionStore
			: typeof window !== "undefined"
				? window.sessionStorage
				: null;
	const locationSearch =
		options && "locationSearch" in options
			? options.locationSearch
			: typeof window !== "undefined"
				? window.location.search
				: "";

	if (localStore) {
		try {
			const raw = localStore.getItem(BC_STORAGE_KEY);
			if (raw) {
				const parsed = JSON.parse(raw) as Partial<SavedBodyControlSettings>;
				if (typeof parsed.url === "string" && parsed.url.trim()) {
					url = parsed.url.trim();
				}
				if (typeof parsed.robotId === "string" && parsed.robotId.trim()) {
					robotId = parsed.robotId.trim();
				}
				if (typeof parsed.autoReconnect === "boolean") {
					autoReconnect = parsed.autoReconnect;
				}
			}
		} catch {
			// Ignore storage restrictions
		}
	}
	if (sessionStore) {
		try {
			const savedToken = sessionStore.getItem(BC_SESSION_TOKEN_KEY)?.trim();
			if (savedToken) {
				token = savedToken;
			}
		} catch {
			// Ignore storage restrictions
		}
	}
	if (locationSearch) {
		try {
			const params = new URLSearchParams(locationSearch);
			const qUrl = params.get("bc")?.trim();
			const qId = params.get("robotId")?.trim();
			if (qUrl && (qUrl.startsWith("ws://") || qUrl.startsWith("wss://"))) {
				url = qUrl;
			}
			if (qId) {
				robotId = qId;
			}
		} catch {
			// Ignore invalid URL query
		}
	}
	return { url, robotId, autoReconnect, token };
}

export function saveBodyControlSettings(
	settings: SavedBodyControlSettings,
	localStore?: StorageLike | null,
): void {
	const store =
		localStore !== undefined
			? localStore
			: typeof window !== "undefined"
				? window.localStorage
				: null;
	if (!store) {
		return;
	}
	try {
		store.setItem(BC_STORAGE_KEY, JSON.stringify(settings));
	} catch {
		// Ignore storage quota / private mode restrictions
	}
}

export function saveBodyControlSessionToken(
	token: string,
	sessionStore?: StorageLike | null,
): void {
	const store =
		sessionStore !== undefined
			? sessionStore
			: typeof window !== "undefined"
				? window.sessionStorage
				: null;
	if (!store) {
		return;
	}
	try {
		const trimmed = token.trim();
		if (trimmed) {
			store.setItem(BC_SESSION_TOKEN_KEY, trimmed);
		} else {
			store.removeItem(BC_SESSION_TOKEN_KEY);
		}
	} catch {
		// Ignore storage quota / private mode restrictions
	}
}

export function clearBodyControlSessionToken(
	sessionStore?: StorageLike | null,
): void {
	saveBodyControlSessionToken("", sessionStore);
}

export class AinekioSimulatorController {
	readonly #viewport: SimulatorViewport;
	readonly #audio = new BrowserRobotAudioAdapter();
	readonly #worldAudio: WorldAudioEngine;
	readonly #multiplayer: BrowserMultiplayerClient;
	readonly #unsubscribeMultiplayer: () => void;
	readonly #callbacks: SimulatorControllerCallbacks;
	#worker?: Worker;
	#multiplayerSnapshot: MultiplayerSnapshot;
	#lastMpPoseBroadcastMs = 0;
	#mpPoseTick = 0;

	#ready = false;
	#loadingMessage = "Booting MuJoCo WASM + ESP32-P4 firmware...";
	#robotModel: RobotModelId = "v2";
	#levelId: SimulatorLevelId = "v2_lab";
	#cameraMode: SimulatorCameraMode = "orbit";
	#engineMode: LocomotionEngineMode = "neural";
	#neuralGaitModelId = "microduck-v20-studya-p4";
	#neuralPoseModelId = "neural-pose-v8-calibrated";
	#neuralMotions: readonly NeuralMotionCatalogItem[] = [];
	#controlMode: "standalone" | "body-control" = "standalone";
	#bcUrl = DEFAULT_BODY_CONTROL_URL;
	#bcRobotId = DEFAULT_ROBOT_ID;
	#bcToken = "";
	#bcAutoReconnect = true;
	#bcWs: WebSocket | undefined;
	#bcConnected = false;
	#bcReconnecting = false;
	#bcReconnectAttempts = 0;
	#bcReconnectTimer: number | undefined;
	#bcRehandshakeOnRobotReady = false;
	#bcEpoch: number | null = null;
	#bcError: string | undefined;
	#bcGeneration = 1;

	#state: RobotTelemetryState | undefined;
	#cameraPreviewDataUrl: string | undefined;
	#lastCommandLog = "Booting virtual Ainekio V2...";
	#availableClips: readonly string[] = V2_CLIP_ACTIONS;
	#lastError: string | undefined;

	#standaloneSeq = 1;
	#standalonePingTimer?: number;
	#activeWalkSeq: number | null = null;
	#activeWalkDir:
		| "fwd"
		| "back"
		| "turn_l"
		| "turn_r"
		| "side_l"
		| "side_r"
		| null = null;
	#activeWalkGait: WalkGaitMode | null = null;
	#cameraCaptureBusy = false;
	#lastImuBootId = 1;
	#lastImuTimestampUs = 0;
	#speakerVolume = 85;
	#speakerTalkingTimer?: number;
	#lastFaceWidth = 0;
	#lastFaceHeight = 0;
	#lastFaceRgba?: Uint8Array;
	#lastStateUiEmitMs = 0;
	readonly #launchConfig: SimulatorLaunchConfig | undefined;
	readonly #seenMpChatIds = new Set<string>();
	readonly #commsMessages: SimulatorCommsMessage[] = [];
	#commsSeq = 1;
	#wasMpConnected = false;
	#launchAutoConnected = false;
	#disposed = false;
	readonly #onVisibilityChange: (() => void) | undefined;

	constructor(
		viewportContainer: HTMLElement,
		callbacks: SimulatorControllerCallbacks,
	) {
		this.#callbacks = callbacks;
		const saved = loadSavedBodyControlSettings();
		this.#bcUrl = saved.url;
		this.#bcRobotId = saved.robotId;
		this.#bcAutoReconnect = saved.autoReconnect;
		this.#bcToken = saved.token;

		if (typeof window !== "undefined") {
			const launch = parseSimulatorLaunchParams(
				window.location.search,
				window.location.hash,
			);
			this.#launchConfig = launch;
			if (launch.shouldScrubHash && window.location.hash) {
				try {
					window.history.replaceState(
						null,
						"",
						`${window.location.pathname}${window.location.search}`,
					);
				} catch {
					// Ignore restricted history contexts
				}
			}
			if (launch.model) {
				this.#robotModel = launch.model;
			}
			if (launch.level) {
				this.#levelId = launch.level;
			}
			if (launch.bc) {
				this.#bcUrl = launch.bc;
			}
			if (launch.robotId) {
				this.#bcRobotId = launch.robotId;
			}
			if (launch.token) {
				this.#bcToken = launch.token;
				saveBodyControlSessionToken(launch.token);
				saveBodyControlSettings({
					url: this.#bcUrl,
					robotId: this.#bcRobotId,
					autoReconnect: this.#bcAutoReconnect,
				});
			}
			if (typeof document !== "undefined") {
				this.#onVisibilityChange = () => {
					if (
						document.visibilityState === "visible" &&
						!this.#disposed &&
						this.#controlMode === "body-control" &&
						this.#bcReconnecting &&
						!this.#bcConnected
					) {
						this.#openBodyControlSocket();
					}
				};
				document.addEventListener("visibilitychange", this.#onVisibilityChange);
			}
		}

		this.#viewport = new SimulatorViewport(viewportContainer);
		this.#worldAudio = new WorldAudioEngine(() => this.#emitSnapshot());
		this.#multiplayer = createBrowserMultiplayerClient();
		this.#multiplayerSnapshot = this.#multiplayer.snapshot();
		this.#unsubscribeMultiplayer = this.#multiplayer.subscribe((mpSnap) => {
			this.#multiplayerSnapshot = mpSnap;
			this.#viewport.syncRemotePeers(mpSnap.remotePlayers, this.#levelId);
			this.#forwardRemoteRoomChats(mpSnap);
			this.#emitSnapshot();
		});
		this.#emitSnapshot();
	}

	getSavedBodyControlSettings(): SavedBodyControlSettings & {
		readonly token?: string;
	} {
		return {
			url: this.#bcUrl,
			robotId: this.#bcRobotId,
			autoReconnect: this.#bcAutoReconnect,
			...(this.#bcToken ? { token: this.#bcToken } : {}),
		};
	}

	#forwardRemoteRoomChats(mpSnap: MultiplayerSnapshot): void {
		if (mpSnap.status !== "connected") {
			this.#wasMpConnected = false;
			return;
		}
		if (!this.#wasMpConnected) {
			this.#wasMpConnected = true;
			for (const msg of mpSnap.chatMessages) {
				this.#seenMpChatIds.add(msg.id);
			}
			return;
		}
		for (const msg of mpSnap.chatMessages) {
			if (this.#seenMpChatIds.has(msg.id)) {
				continue;
			}
			this.#seenMpChatIds.add(msg.id);
			if (mpSnap.localPeerId && msg.senderId === mpSnap.localPeerId) {
				continue;
			}
			const peerSender = msg.senderName || msg.senderId.slice(0, 8);
			this.#appendCommsMessage({
				id: `mp-${msg.id}`,
				sender: peerSender,
				role: "peer",
				channel: "room",
				text: msg.text,
			});
			if (this.#controlMode === "body-control" && this.#bcConnected) {
				this.#sendBodyControlJson({
					t: "event",
					name: "room_chat",
					id: msg.id,
					room: mpSnap.roomName ?? "",
					sender_id: msg.senderId,
					sender: peerSender,
					text: msg.text,
				});
			}
		}
	}

	async start(): Promise<void> {
		const initialLevel = await loadSimulatorLevel(this.#levelId);
		const initialRobotDesc = getRobotModelDescriptor(this.#robotModel);
		this.#worldAudio.setLevelAudio(initialLevel.audio);
		this.#loadingMessage = `Loading ${initialRobotDesc.name} CAD rig & arena...`;
		this.#emitSnapshot();

		// Boot worker in parallel with Three.js GLB & arena loading
		const worker = new Worker(new URL("./mujocoWorker.ts", import.meta.url), {
			type: "module",
		});
		this.#worker = worker;
		worker.onmessage = (event: MessageEvent<WorkerOutboundMessage>) => {
			this.#handleWorkerMessage(event.data);
		};
		worker.onerror = (event) => {
			this.#lastError = `Simulation worker error: ${event.message || "unknown error"}`;
			this.#emitSnapshot();
		};

		const baseUrl = window.location.origin;
		this.#postWorker({
			type: "init",
			baseUrl,
			obstaclesMj: initialLevel.obstaclesMj,
			collidersMj: initialLevel.collidersMj,
			hfield: initialLevel.hfield,
			useDefaultFloorPlane: initialLevel.useDefaultFloorPlane,
			spawnMj: this.#robotSpawnForLevel(initialLevel.robotSpawnMj),
		});

		await Promise.all([
			this.#viewport.loadRobot(initialRobotDesc.glbUrl, this.#robotModel),
			this.#viewport.loadLevel(initialLevel),
		]);

		// Auto-host or auto-join multiplayer room from launch config or ?room=<name>
		const launchRoom = normalizeRoomName(this.#launchConfig?.room ?? "");
		const launchMp = this.#launchConfig?.mp;
		const launchDisplayName =
			this.#launchConfig?.name ||
			(launchMp === "host" && this.#launchConfig?.token
				? `Ainekio ${initialRobotDesc.shortName}`
				: undefined);
		if (launchMp === "host" && launchRoom.length >= 3) {
			void this.hostMultiplayerRoom(launchRoom, launchDisplayName);
		} else if (launchMp !== "solo" && launchRoom.length >= 3) {
			void this.joinMultiplayerRoom(launchRoom, launchDisplayName);
		}

		// Keep standalone admission alive with 1 Hz protocol-v1 heartbeat.
		// Camera frame cadence is driven by the unthrottled 50 Hz firmware Web Worker
		// (matching ESP32-P4 controller.c even when this browser tab is backgrounded).
		this.#standalonePingTimer = window.setInterval(() => {
			if (this.#ready && this.#controlMode === "standalone") {
				this.#sendStandaloneWire({ t: "ping" });
			}
		}, 1000);
	}

	getLastFaceFrame():
		| {
				readonly width: number;
				readonly height: number;
				readonly rgba: Uint8Array;
		  }
		| undefined {
		if (!this.#lastFaceRgba) {
			return undefined;
		}
		return {
			width: this.#lastFaceWidth,
			height: this.#lastFaceHeight,
			rgba: this.#lastFaceRgba,
		};
	}

	#robotSpawnForLevel(
		levelSpawnMj: readonly [number, number, number],
	): readonly [number, number, number] {
		if (this.#robotModel === "v1") {
			return [levelSpawnMj[0], levelSpawnMj[1], levelSpawnMj[2] - 0.008];
		}
		if (this.#robotModel === "v3") {
			return [levelSpawnMj[0], levelSpawnMj[1], levelSpawnMj[2] + 0.116];
		}
		return levelSpawnMj;
	}

	async setRobotModel(robotModel: RobotModelId): Promise<void> {
		const desc = getRobotModelDescriptor(robotModel);
		if (!desc.ready || desc.id === this.#robotModel) {
			return;
		}
		const targetModel = desc.id;
		this.#robotModel = targetModel;
		if (this.#controlMode === "body-control") {
			this.#bcRehandshakeOnRobotReady = true;
		}
		this.#clearActiveWalk();
		this.#worldAudio.playSfx("portal-activate");
		this.#lastCommandLog = `Loading ${desc.name} on demand...`;
		this.#emitSnapshot();

		const level = await loadSimulatorLevel(this.#levelId);
		if (this.#robotModel !== targetModel) {
			return;
		}

		this.#postWorker({
			type: "set-robot",
			robotModel: targetModel,
			obstaclesMj: level.obstaclesMj,
			collidersMj: level.collidersMj,
			hfield: level.hfield,
			useDefaultFloorPlane: level.useDefaultFloorPlane,
			spawnMj: this.#robotSpawnForLevel(level.robotSpawnMj),
		});
		await this.#viewport.loadRobot(desc.glbUrl, targetModel);
		if (this.#robotModel !== targetModel) {
			return;
		}
		if (this.#lastFaceRgba) {
			this.#viewport.updateFaceRgba(
				this.#lastFaceWidth,
				this.#lastFaceHeight,
				this.#lastFaceRgba,
			);
		}
		this.#worldAudio.playSfx("open");
		this.#lastCommandLog = `Active robot: ${desc.name}`;
		this.#emitSnapshot();
	}

	async setLevel(levelId: SimulatorLevelId): Promise<void> {
		const summary = getSimulatorLevel(levelId);
		this.#levelId = summary.id;
		this.#clearActiveWalk();
		this.#worldAudio.playSfx("portal-activate");
		this.#worldAudio.setLevelAudio(summary.audio);
		this.#lastCommandLog = `Loading ${summary.name} on demand...`;
		this.#emitSnapshot();

		const level = await loadSimulatorLevel(levelId);
		// Abort if user switched to another level while fetching
		if (this.#levelId !== level.id) {
			return;
		}

		// Load MuJoCo physics colliders/heightfield immediately while Three.js streams visuals
		this.#postWorker({
			type: "set-level",
			obstaclesMj: level.obstaclesMj,
			collidersMj: level.collidersMj,
			hfield: level.hfield,
			useDefaultFloorPlane: level.useDefaultFloorPlane,
			spawnMj: this.#robotSpawnForLevel(level.robotSpawnMj),
		});
		await this.#viewport.loadLevel(level);
		if (this.#levelId !== level.id) {
			return;
		}
		this.#worldAudio.setLevelAudio(level.audio);
		this.#worldAudio.playSfx("open");
		this.#viewport.syncRemotePeers(
			this.#multiplayerSnapshot.remotePlayers,
			this.#levelId,
		);
		this.#lastCommandLog = `Active world: ${level.name}`;
		this.#emitSnapshot();
	}

	// ---- PeerJS Multiplayer Room controls (lazy-loaded on demand) ----

	setMultiplayerDisplayName(name: string): void {
		this.#multiplayer.setDisplayName(name);
	}

	async hostMultiplayerRoom(
		roomName: string,
		displayName?: string,
	): Promise<void> {
		if (displayName !== undefined) {
			this.#multiplayer.setDisplayName(displayName);
		}
		this.#worldAudio.playSfx("portal-activate");
		await this.#multiplayer.hostRoom(roomName);
		if (this.#multiplayerSnapshot.status === "connected") {
			this.#worldAudio.playSfx("open");
			this.#lastCommandLog = `Hosting room "${this.#multiplayerSnapshot.roomName ?? roomName}"`;
			this.#publishMultiplayerPose(true);
			this.#emitSnapshot();
		}
	}

	async joinMultiplayerRoom(
		roomName: string,
		displayName?: string,
	): Promise<void> {
		if (displayName !== undefined) {
			this.#multiplayer.setDisplayName(displayName);
		}
		this.#worldAudio.playSfx("portal-activate");
		await this.#multiplayer.joinRoom(roomName);
		if (this.#multiplayerSnapshot.status === "connected") {
			this.#worldAudio.playSfx("open");
			this.#lastCommandLog = `Joined room "${this.#multiplayerSnapshot.roomName ?? roomName}"`;
			this.#publishMultiplayerPose(true);
			this.#emitSnapshot();
		}
	}

	leaveMultiplayerRoom(): void {
		this.#worldAudio.playSfx("back");
		this.#multiplayer.disconnect();
		this.#viewport.syncRemotePeers([], this.#levelId);
		this.#lastCommandLog = "Left multiplayer room";
		this.#emitSnapshot();
	}

	#appendCommsMessage(
		entry: Omit<SimulatorCommsMessage, "id" | "timestampMs"> & {
			readonly id?: string;
		},
	): string {
		const id = entry.id || `sim-msg-${Date.now()}-${this.#commsSeq++}`;
		if (this.#commsMessages.some((m) => m.id === id)) {
			return id;
		}
		this.#commsMessages.push({
			id,
			sender: entry.sender,
			role: entry.role,
			channel: entry.channel,
			text: entry.text,
			timestampMs: Date.now(),
		});
		if (this.#commsMessages.length > 80) {
			this.#commsMessages.splice(0, this.#commsMessages.length - 80);
		}
		return id;
	}

	clearCommsMessages(): void {
		this.#commsMessages.length = 0;
		this.#emitSnapshot();
	}

	sendCommsText(rawText: string): void {
		const text = rawText.trim().slice(0, 400);
		if (!text) {
			return;
		}
		const mpConnected = this.#multiplayerSnapshot.status === "connected";
		const bcLinked = this.#controlMode === "body-control" && this.#bcConnected;
		const sender = this.#multiplayerSnapshot.displayName || "You";
		const id = this.#appendCommsMessage({
			sender,
			role: "self",
			channel: mpConnected ? "room" : "direct",
			text,
		});
		if (mpConnected) {
			this.#multiplayer.sendChat(text);
		}
		if (bcLinked) {
			this.#sendBodyControlJson({
				t: "event",
				name: "room_chat",
				id,
				room: mpConnected ? this.#multiplayerSnapshot.roomName ?? "" : "",
				sender_id: this.#multiplayerSnapshot.localPeerId ?? "operator",
				sender: this.#multiplayerSnapshot.displayName || "",
				text,
			});
			this.#lastCommandLog = "Sent message to Ainekio OS";
		} else if (!mpConnected) {
			this.#appendCommsMessage({
				sender: "System",
				role: "system",
				channel: "direct",
				text: "Link Body Control (or join a Multiplayer Room) to chat with Ainekio OS or other players.",
			});
		}
		this.#emitSnapshot();
	}

	sendMultiplayerChat(text: string): void {
		this.sendCommsText(text);
	}

	#publishMultiplayerPose(force = false): void {
		if (this.#multiplayerSnapshot.status !== "connected" || !this.#state) {
			return;
		}
		const now = performance.now();
		if (!force && now - this.#lastMpPoseBroadcastMs < 100) {
			return;
		}
		this.#lastMpPoseBroadcastMs = now;
		this.#mpPoseTick += 1;

		const [tx, ty, tz] = mujocoPositionToThree(this.#state.rootPosMj);
		const [qx, qy, qz, qw] = mujocoQuaternionToThreeXyzw(
			this.#state.rootQuatMjWxyz,
		);
		const round3 = (n: number) => Math.round(n * 1000) / 1000;
		const round4 = (n: number) => Math.round(n * 10000) / 10000;
		const round1 = (n: number) => Math.round(n * 10) / 10;

		this.#multiplayer.publishLocalPose({
			position: [round3(tx), round3(ty), round3(tz)],
			rotation: [round4(qx), round4(qy), round4(qz), round4(qw)],
			tick: this.#mpPoseTick,
			robotModel: this.#robotModel,
			jointsDeg: this.#state.jointsDeg.map(round1),
			levelId: this.#levelId,
			faceName: this.#state.face.name,
		});
	}

	setCameraMode(mode: SimulatorCameraMode): void {
		if (this.#cameraMode !== mode) {
			this.#worldAudio.playSfx("sweep");
		}
		this.#cameraMode = mode;
		this.#viewport.setCameraMode(mode);
		this.#emitSnapshot();
	}

	focusRobot(): void {
		this.#worldAudio.playSfx("soft");
		this.#viewport.focusRobot();
	}

	unlockAudio(): void {
		this.#worldAudio.unlock();
	}

	setAudioEnabled(enabled: boolean): void {
		this.#worldAudio.setEnabled(enabled);
		if (enabled) {
			this.#worldAudio.playSfx("select");
		}
	}

	setMusicVolume(volume: number): void {
		this.#worldAudio.setMusicVolume(volume);
	}

	setSfxVolume(volume: number): void {
		this.#worldAudio.setSfxVolume(volume);
	}

	setFootstepsEnabled(enabled: boolean): void {
		this.#worldAudio.setFootstepsEnabled(enabled);
	}

	playUiSfx(id: WorldSfxId): void {
		this.#worldAudio.playSfx(id);
	}

	setEngineMode(mode: LocomotionEngineMode): void {
		if (this.#engineMode === mode) {
			return;
		}
		this.#engineMode = mode;
		this.#clearActiveWalk();
		this.#worldAudio.playSfx("select");
		this.#postWorker({ type: "set-engine", engine: mode });
		this.#lastCommandLog =
			mode === "neural"
				? `Engine -> Neural Gait (${this.#neuralGaitModelId}) + Neural Pose (${this.#neuralPoseModelId})`
				: "Engine -> Legacy Firmware Native Gait & Clips";
		this.#emitSnapshot();
	}

	// ---- Standalone Cockpit protocol-v1 commands ----

	sendClipOrPosture(name: string): void {
		if (!this.#ready || this.#controlMode !== "standalone") {
			return;
		}
		this.#clearActiveWalk();
		if (name === "stand") {
			this.#worldAudio.playSfx("portal-awaken");
		} else if (name === "neutral" || name === "sit" || name === "lay") {
			this.#worldAudio.playSfx("select");
		} else {
			this.#worldAudio.playSfx("portal-reveal");
		}
		if (
			this.#engineMode === "neural" &&
			this.#neuralMotions.some((m) => m.id === name)
		) {
			this.#postWorker({ type: "neural-pose", motionId: name });
			this.#lastCommandLog = `Neural Pose -> ${name}`;
			this.#emitSnapshot();
			return;
		}
		const seq = this.#nextSeq();
		if (name === "stand" || name === "neutral" || name === "sit") {
			this.#sendStandaloneWire({
				t: "intent",
				seq,
				epoch: STANDALONE_EPOCH,
				name,
			});
		} else {
			this.#sendStandaloneWire({
				t: "intent",
				seq,
				epoch: STANDALONE_EPOCH,
				name: "emote",
				asset: name,
			});
		}
		this.#lastCommandLog = `Firmware Motion -> ${name}`;
		this.#emitSnapshot();
	}

	sendWalkCommand(options: {
		readonly forward: number; // -100..100
		readonly turn: number; // -100..100
		readonly lateral?: number; // -100..100
		readonly speed: number; // 10..200 (clamped to 100 for crab)
		readonly gait: WalkGaitMode;
	}): void {
		if (!this.#ready || this.#controlMode !== "standalone") {
			return;
		}
		const fwd = Math.max(-100, Math.min(100, Math.round(options.forward)));
		const turn = Math.max(-100, Math.min(100, Math.round(options.turn)));
		const lateral = Math.max(
			-100,
			Math.min(100, Math.round(options.lateral ?? 0)),
		);
		const maxSpeed = options.gait === "crab" ? 100 : 200;
		const speed = Math.max(10, Math.min(maxSpeed, Math.round(options.speed)));

		if (Math.abs(fwd) < 5 && Math.abs(turn) < 5 && Math.abs(lateral) < 5) {
			this.sendStop(false);
			return;
		}

		if (this.#engineMode === "neural") {
			this.#clearActiveWalk();
			this.#postWorker({
				type: "neural-walk",
				forward: fwd,
				lateral,
				turn,
				speed,
			});
			this.#lastCommandLog = `Neural Gait (${this.#neuralGaitModelId}) fwd=${fwd} lat=${lateral} turn=${turn} spd=${speed}%`;
			this.#emitSnapshot();
			return;
		}

		let dir: "fwd" | "back" | "turn_l" | "turn_r" | "side_l" | "side_r" = "fwd";
		if (
			options.gait === "crab" &&
			Math.abs(lateral) >= Math.abs(fwd) &&
			Math.abs(lateral) >= Math.abs(turn)
		) {
			dir = lateral >= 0 ? "side_l" : "side_r";
		} else if (Math.abs(fwd) >= Math.abs(turn)) {
			dir = fwd >= 0 ? "fwd" : "back";
		} else {
			dir = turn >= 0 ? "turn_l" : "turn_r";
		}

		// ainekio_v2_walk_accept() requires dir and gait to remain constant on
		// update frames while forward/turn/lateral steer continuously. If gait
		// changed mid-walk, stop first so the new gait starts cleanly.
		if (this.#activeWalkSeq !== null && this.#activeWalkGait !== options.gait) {
			this.sendStop(false);
		}

		const wireDir =
			this.#activeWalkSeq !== null && this.#activeWalkDir !== null
				? this.#activeWalkDir
				: dir;
		const seq = this.#nextSeq();
		const msg: Record<string, unknown> = {
			t: "intent",
			seq,
			epoch: STANDALONE_EPOCH,
			name: "walk",
			dir: wireDir,
			steps: 0,
			speed,
			gait: options.gait,
			forward: fwd,
			turn,
		};
		if (options.gait === "crab") {
			msg.lateral = lateral;
		}
		if (this.#activeWalkSeq !== null) {
			msg.update = this.#activeWalkSeq;
		} else {
			this.#activeWalkSeq = seq;
			this.#activeWalkDir = wireDir;
			this.#activeWalkGait = options.gait;
		}
		this.#sendStandaloneWire(msg);
		this.#lastCommandLog = `Walk (${options.gait}) fwd=${fwd} turn=${turn} spd=${speed}%`;
		this.#emitSnapshot();
	}

	#clearActiveWalk(): void {
		this.#activeWalkSeq = null;
		this.#activeWalkDir = null;
		this.#activeWalkGait = null;
	}

	sendStop(detach = false): void {
		if (!this.#ready || this.#controlMode !== "standalone") {
			return;
		}
		this.#clearActiveWalk();
		this.#worldAudio.playSfx("back");
		this.#postWorker({ type: "neural-stop", detach });
		this.#lastCommandLog = detach ? "EMERGENCY DETACH" : "Stop motion";
		this.#emitSnapshot();
	}

	sendFaceExpression(expr: string, timeoutMs = 6000): void {
		if (!this.#ready || this.#controlMode !== "standalone") {
			return;
		}
		this.#worldAudio.playSfx("soft");
		const msg: Record<string, unknown> = {
			t: "intent",
			seq: this.#nextSeq(),
			epoch: STANDALONE_EPOCH,
			name: "face",
			expr,
		};
		if (expr !== "default" && timeoutMs > 0) {
			msg.timeout_ms = timeoutMs;
		}
		this.#sendStandaloneWire(msg);
		this.#lastCommandLog = `Face -> ${expr}`;
		this.#emitSnapshot();
	}

	setBalanceEnabled(enabled: boolean): void {
		if (!this.#ready || this.#controlMode !== "standalone") {
			return;
		}
		this.#worldAudio.playSfx("soft");
		this.#sendStandaloneWire({
			t: "balance",
			seq: this.#nextSeq(),
			epoch: STANDALONE_EPOCH,
			op: "save",
			enabled,
		});
		this.#lastCommandLog = `Self-leveling ${enabled ? "ON" : "OFF"}`;
		this.#emitSnapshot();
	}

	async captureSnapshot(): Promise<void> {
		if (!this.#ready) {
			return;
		}
		this.#worldAudio.playSfx("portal-reveal");
		const res = this.#state?.camera.snapshotRes ?? "960P";
		if (this.#controlMode === "standalone") {
			this.#sendStandaloneWire({ t: "snap", seq: this.#nextSeq() });
		} else {
			await this.#captureAndPublishCameraFrame(
				res === "AUTO" ? "960P" : res,
				"stream",
				0,
			);
		}
		this.#lastCommandLog = `OV5647 snapshot (${res})`;
		this.#emitSnapshot();
	}

	// ---- Physical perturbations & RL rollout recording ----

	applyWrench(
		forceMj: readonly [number, number, number],
		torqueMj: readonly [number, number, number],
		durationMs: number,
		label: string,
	): void {
		this.#worldAudio.playSfx("portal-impact");
		this.#postWorker({
			type: "wrench",
			forceMj,
			torqueMj,
			durationMs,
		});
		this.#lastCommandLog = `Physics -> ${label}`;
		this.#emitSnapshot();
	}

	toggleJointPin(jointIndex: number): void {
		const pinned = this.#state?.pinnedJoints.includes(jointIndex) ?? false;
		this.#worldAudio.playServoClick(!pinned);
		this.#postWorker({
			type: "pin-joint",
			jointIndex,
			pinned: !pinned,
		});
		this.#lastCommandLog = `${!pinned ? "Pinned (jammed)" : "Released"} joint J${jointIndex}`;
		this.#emitSnapshot();
	}

	clearPins(): void {
		this.#worldAudio.playSfx("soft");
		this.#postWorker({ type: "clear-pins" });
		this.#lastCommandLog = "Released all joint pins";
		this.#emitSnapshot();
	}

	resetPose(): void {
		const level = getSimulatorLevel(this.#levelId);
		this.#clearActiveWalk();
		this.#worldAudio.playSfx("portal-awaken");
		this.#postWorker({
			type: "reset-pose",
			spawnMj: this.#robotSpawnForLevel(level.robotSpawnMj),
		});
		this.#lastCommandLog = "Reset robot pose";
		this.#emitSnapshot();
	}

	startRecording(label = "sim_rollout"): void {
		this.#postWorker({ type: "record-start", label });
		this.#lastCommandLog = `Recording 50 Hz RL rollout (${label})...`;
		this.#emitSnapshot();
	}

	stopRecording(): void {
		this.#postWorker({ type: "record-stop" });
		this.#lastCommandLog = "Exporting RL rollout (.jsonl)...";
		this.#emitSnapshot();
	}

	// ---- Browser 16 kHz microphone ("Tap to Talk") ----

	#stopMicrophoneCapture(): void {
		if (!this.#audio.micActive) {
			return;
		}
		this.#audio.stopMicrophone();
		this.#postWorker({ type: "mic-gate", open: false });
		this.#lastCommandLog = "Utterance sent to Ainekio OS (microphone closed)";
		this.#emitSnapshot();
	}

	async #startMicrophoneCapture(): Promise<void> {
		if (this.#audio.micActive) {
			return;
		}
		if (!this.#audio.micSupported) {
			this.#lastError =
				"Browser microphone requires https:// or http://127.0.0.1 (use typed chat or open via 127.0.0.1:8792).";
			this.#appendCommsMessage({
				sender: "System",
				role: "system",
				channel: "voice",
				text: this.#lastError,
			});
			this.#emitSnapshot();
			return;
		}
		try {
			let gateOpened = false;
			const ok = await this.#audio.startMicrophone((_counter, pcm) => {
				if (!gateOpened) {
					gateOpened = true;
					this.#postWorker({ type: "mic-gate", open: true });
				}
				const pcmCopy = pcm.slice().buffer;
				this.#postWorker({ type: "mic-frame", pcm: pcmCopy }, [pcmCopy]);
			});
			if (ok) {
				if (!gateOpened) {
					gateOpened = true;
					this.#postWorker({ type: "mic-gate", open: true });
				}
				this.#lastCommandLog = "Listening (16 kHz mic live) — tap Done to send";
			} else {
				this.#lastError =
					"Browser microphone is not available in this context.";
			}
		} catch (err) {
			this.#lastError = `Microphone error: ${err instanceof Error ? err.message : String(err)}`;
		}
		this.#emitSnapshot();
	}

	async toggleMicrophone(): Promise<void> {
		if (this.#audio.micActive) {
			this.#stopMicrophoneCapture();
			return;
		}
		await this.#startMicrophoneCapture();
	}

	// ---- External Body Control direct WebSocket mode ----

	#clearBcReconnectTimer(): void {
		if (this.#bcReconnectTimer !== undefined) {
			window.clearTimeout(this.#bcReconnectTimer);
			this.#bcReconnectTimer = undefined;
		}
	}

	connectBodyControl(
		url: string,
		robotId: string,
		token: string,
		autoReconnect = this.#bcAutoReconnect,
	): void {
		this.#clearBcReconnectTimer();
		this.#bcAutoReconnect = autoReconnect;
		this.#bcReconnectAttempts = 0;
		this.#bcReconnecting = false;
		const normalizedUrl = normalizeBodyControlUrl(url);
		const trimmedId = robotId.trim() || DEFAULT_ROBOT_ID;
		const trimmedToken = token.trim();
		this.#bcUrl = normalizedUrl;
		this.#bcRobotId = trimmedId;
		this.#bcToken = trimmedToken;
		saveBodyControlSettings({
			url: normalizedUrl,
			robotId: trimmedId,
			autoReconnect,
		});
		if (!trimmedToken) {
			this.#bcError =
				"Robot Auth Token is required (paste a Pairing Code from Body Control or enter your robot token).";
			this.#bcConnected = false;
			this.#bcReconnecting = false;
			this.#controlMode = "standalone";
			this.#emitSnapshot();
			return;
		}
		saveBodyControlSessionToken(trimmedToken);
		this.#openBodyControlSocket();
	}

	async applyPairingBundle(
		bundle: BodyControlLaunchBundle,
		autoConnect = true,
	): Promise<void> {
		if (bundle.level && bundle.level !== this.#levelId) {
			await this.setLevel(bundle.level);
		}
		if (bundle.model && bundle.model !== this.#robotModel) {
			await this.setRobotModel(bundle.model);
		}
		const nextUrl = bundle.bc
			? normalizeBodyControlUrl(bundle.bc)
			: this.#bcUrl;
		const nextId = bundle.robotId ?? this.#bcRobotId;
		const nextToken = bundle.token ?? this.#bcToken;
		this.#bcUrl = nextUrl;
		this.#bcRobotId = nextId;
		if (bundle.token) {
			this.#bcToken = bundle.token;
		}
		if (autoConnect && nextUrl && nextToken) {
			this.connectBodyControl(nextUrl, nextId, nextToken, true);
		} else {
			this.#emitSnapshot();
		}
		const normRoom = normalizeRoomName(bundle.room ?? "");
		if (normRoom.length >= 3) {
			if (bundle.mp === "host") {
				await this.hostMultiplayerRoom(normRoom, bundle.name);
			} else if (bundle.mp !== "solo") {
				await this.joinMultiplayerRoom(normRoom, bundle.name);
			}
		}
	}

	#maybeCompleteLaunchAutoConnect(): void {
		if (this.#launchAutoConnected) {
			return;
		}
		this.#launchAutoConnected = true;
		const launch = this.#launchConfig;
		if (launch?.bc && launch?.token) {
			this.connectBodyControl(
				launch.bc,
				launch.robotId || DEFAULT_ROBOT_ID,
				launch.token,
				true,
			);
			return;
		}
		if (this.#bcAutoReconnect && this.#bcUrl && this.#bcToken) {
			this.connectBodyControl(
				this.#bcUrl,
				this.#bcRobotId || DEFAULT_ROBOT_ID,
				this.#bcToken,
				this.#bcAutoReconnect,
			);
		}
	}

	#openBodyControlSocket(): void {
		this.#clearBcReconnectTimer();
		const prev = this.#bcWs;
		this.#bcWs = undefined;
		if (prev) {
			try {
				prev.close(1000, "Reconnecting");
			} catch {
				// ignore
			}
		}
		this.#bcError = undefined;
		this.#bcConnected = false;
		this.#bcEpoch = null;
		this.#controlMode = "body-control";
		this.#clearActiveWalk();
		this.#lastCommandLog = this.#bcReconnecting
			? `Reconnecting to Body Control (${this.#bcUrl})...`
			: `Connecting to Body Control (${this.#bcUrl})...`;
		this.#emitSnapshot();

		let ws: WebSocket;
		try {
			ws = new WebSocket(this.#bcUrl);
		} catch (err) {
			this.#bcError = `Invalid WebSocket URL: ${err instanceof Error ? err.message : String(err)}`;
			this.#bcReconnecting = false;
			this.#controlMode = "standalone";
			this.#emitSnapshot();
			return;
		}
		ws.binaryType = "arraybuffer";
		this.#bcWs = ws;

		ws.onopen = () => {
			if (this.#bcWs !== ws) {
				return;
			}
			this.#lastCommandLog = "Body Control socket open — sending hello...";
			this.#emitSnapshot();
			this.#postWorker({
				type: "request-hello",
				robotId: this.#bcRobotId,
				token: this.#bcToken,
			});
		};

		ws.onmessage = (event) => {
			if (this.#bcWs !== ws) {
				return;
			}
			if (typeof event.data === "string") {
				this.#handleBodyControlText(event.data);
			} else if (event.data instanceof ArrayBuffer) {
				this.#handleBodyControlBinary(event.data);
			}
		};

		ws.onerror = () => {
			if (this.#bcWs !== ws) {
				return;
			}
			this.#bcError =
				"Could not reach Body Control WebSocket. Ensure Body Control (or Cloudflare relay) is running and reachable from this browser.";
			this.#emitSnapshot();
		};

		ws.onclose = (event) => {
			if (this.#bcWs !== ws) {
				return;
			}
			this.#bcWs = undefined;
			const wasConnected = this.#bcConnected;
			this.#bcConnected = false;
			if (this.#controlMode !== "body-control") {
				this.#emitSnapshot();
				return;
			}
			const sessionReplaced = event.code === 4000;
			if (event.code === 4001) {
				clearBodyControlSessionToken();
			}
			const fatalHandshake = isNonRetryableBodyControlCloseCode(event.code);
			this.#bcError =
				this.#bcError ??
				(sessionReplaced
					? `Body Control session taken over by another simulator (${this.#bcRobotId}). Click Link to reclaim control.`
					: wasConnected
						? `Body Control disconnected (code ${event.code})`
						: `Body Control closed during handshake (code ${event.code})`);
			if (this.#bcAutoReconnect && !fatalHandshake && !this.#disposed) {
				const delayIdx = Math.min(
					this.#bcReconnectAttempts,
					BC_RECONNECT_DELAYS_MS.length - 1,
				);
				const delayMs = BC_RECONNECT_DELAYS_MS[delayIdx] ?? 5000;
				this.#bcReconnectAttempts += 1;
				this.#bcReconnecting = true;
				this.#lastCommandLog = `Body Control link dropped — retrying in ${(delayMs / 1000).toFixed(1)}s...`;
				this.#postWorker({ type: "session-close", epoch: this.#bcEpoch ?? 0 });
				this.#emitSnapshot();
				this.#bcReconnectTimer = window.setTimeout(() => {
					if (!this.#disposed && this.#controlMode === "body-control") {
						this.#openBodyControlSocket();
					}
				}, delayMs);
				return;
			}
			this.#bcReconnecting = false;
			this.#restoreStandaloneSession();
			this.#emitSnapshot();
		};
	}

	disconnectBodyControl(restoreStandalone = true): void {
		this.#clearBcReconnectTimer();
		this.#bcReconnecting = false;
		this.#bcReconnectAttempts = 0;
		this.#bcRehandshakeOnRobotReady = false;
		const ws = this.#bcWs;
		this.#bcWs = undefined;
		if (ws) {
			try {
				ws.close(1000, "User disconnected");
			} catch {
				// ignore
			}
		}
		this.#bcConnected = false;
		this.#bcEpoch = null;
		if (restoreStandalone) {
			clearBodyControlSessionToken();
			this.#bcError = undefined;
			this.#restoreStandaloneSession();
			this.#lastCommandLog = "Returned to Standalone Cockpit mode";
			this.#emitSnapshot();
		}
	}

	#restoreStandaloneSession(): void {
		this.#controlMode = "standalone";
		this.#clearActiveWalk();
		this.#standaloneSeq = 1;
		this.#postWorker({
			type: "session-reset",
			epoch: STANDALONE_EPOCH,
		});
	}

	#handleBodyControlText(wire: string): void {
		let parsed: Record<string, unknown> | undefined;
		try {
			parsed = JSON.parse(wire) as Record<string, unknown>;
		} catch {
			return;
		}
		if (!parsed || typeof parsed !== "object") {
			return;
		}
		const msgType = String(parsed.t ?? "");
		if (msgType === "err") {
			this.#bcError = `Body Control rejected handshake: ${String(parsed.code ?? "auth")}`;
			this.#emitSnapshot();
			return;
		}
		if (msgType === "welcome") {
			const epoch = Number(parsed.epoch ?? 1);
			this.#bcEpoch = epoch;
			this.#bcConnected = true;
			this.#bcReconnecting = false;
			this.#bcReconnectAttempts = 0;
			this.#bcError = undefined;
			this.#bcGeneration += 1;
			this.#lastCommandLog = `Connected to Body Control (epoch ${epoch})`;
			this.#postWorker({
				type: "session-reset",
				epoch,
				welcomeJson: wire,
			});
			this.#emitSnapshot();
			return;
		}
		if (msgType === "event" && parsed.name === "assistant_text") {
			const text = typeof parsed.text === "string" ? parsed.text.trim() : "";
			if (text) {
				const robotLabel = `Ainekio ${getRobotModelDescriptor(this.#robotModel).shortName}`;
				this.#appendCommsMessage({
					sender: robotLabel,
					role: "robot",
					channel:
						this.#multiplayerSnapshot.status === "connected"
							? "room"
							: "direct",
					text,
				});
				if (this.#multiplayerSnapshot.status === "connected") {
					this.#multiplayer.sendChat(text);
				}
				this.#emitSnapshot();
			}
			return;
		}
		if (msgType === "event" && parsed.name === "user_transcript") {
			const text = typeof parsed.text === "string" ? parsed.text.trim() : "";
			if (text) {
				this.#appendCommsMessage({
					sender: this.#multiplayerSnapshot.displayName || "You",
					role: "self",
					channel: "voice",
					text,
				});
				this.#emitSnapshot();
			}
			return;
		}
		if (msgType === "mic") {
			if (parsed.on === true && parsed.gate === "open") {
				void this.#startMicrophoneCapture();
			} else if (
				parsed.on === false ||
				(typeof parsed.gate === "string" && parsed.gate !== "open")
			) {
				this.#stopMicrophoneCapture();
			}
		}
		this.#postWorker({
			type: "protocol-rx",
			wire,
			epoch: this.#bcEpoch ?? 1,
		});
	}

	#handleBodyControlBinary(buffer: ArrayBuffer): void {
		const frame = decodeProtocolBinaryFrame(buffer);
		if (!frame) {
			return;
		}
		if (frame.frameType === PROTOCOL_BIN_SPEAKER_PCM) {
			this.#audio.playSpeakerPcm(frame.payload, this.#speakerVolume);
			this.#worldAudio.setRobotSpeechDucking(true);
			this.#postWorker({ type: "set-media", talking: true });
			if (this.#speakerTalkingTimer !== undefined) {
				window.clearTimeout(this.#speakerTalkingTimer);
			}
			this.#speakerTalkingTimer = window.setTimeout(() => {
				this.#worldAudio.setRobotSpeechDucking(false);
				this.#postWorker({ type: "set-media", talking: false });
			}, 320);
		}
	}

	#handleWorkerMessage(msg: WorkerOutboundMessage): void {
		if (this.#disposed) {
			return;
		}
		switch (msg.type) {
			case "ready": {
				this.#ready = true;
				this.#loadingMessage = "";
				this.#lastError = undefined;
				this.#neuralGaitModelId = msg.neuralGaitModelId;
				this.#neuralPoseModelId = msg.neuralPoseModelId;
				this.#neuralMotions = msg.neuralMotions;
				if (msg.helloCommands.length > 0) {
					const knownBase = new Set([
						"stop",
						"say",
						"face",
						"walk",
						"backward",
						"left",
						"right",
						"crawl",
						"run",
						"crab",
						"crab_right",
						"crab_forward",
						"crab_backward",
						"crab_turn_left",
						"crab_turn_right",
					]);
					const clips = msg.helloCommands.filter((c) => !knownBase.has(c));
					if (clips.length > 0) {
						this.#availableClips = clips;
					}
				}
				this.#lastCommandLog = `Neural Gait (${this.#neuralGaitModelId}) + Neural Pose (${this.#neuralPoseModelId}) online`;
				this.#emitSnapshot();
				if (this.#robotModel !== "v2") {
					void loadSimulatorLevel(this.#levelId).then((level) => {
						if (this.#disposed) {
							return;
						}
						this.#postWorker({
							type: "set-robot",
							robotModel: this.#robotModel,
							obstaclesMj: level.obstaclesMj,
							collidersMj: level.collidersMj,
							hfield: level.hfield,
							useDefaultFloorPlane: level.useDefaultFloorPlane,
							spawnMj: this.#robotSpawnForLevel(level.robotSpawnMj),
						});
					});
				} else {
					this.#maybeCompleteLaunchAutoConnect();
				}
				break;
			}
			case "robot-ready": {
				this.#neuralGaitModelId = msg.neuralGaitModelId;
				this.#neuralPoseModelId = msg.neuralPoseModelId;
				this.#neuralMotions = msg.neuralMotions;
				if (msg.availableClips.length > 0) {
					this.#availableClips = msg.availableClips;
				}
				const desc = getRobotModelDescriptor(msg.robotModel);
				this.#lastCommandLog = `${desc.name} online (${this.#neuralGaitModelId} + ${this.#neuralPoseModelId})`;
				this.#emitSnapshot();
				this.#maybeCompleteLaunchAutoConnect();
				if (
					this.#bcRehandshakeOnRobotReady &&
					this.#controlMode === "body-control"
				) {
					this.#bcRehandshakeOnRobotReady = false;
					this.#openBodyControlSocket();
				}
				break;
			}
			case "error": {
				this.#lastError = msg.message;
				this.#emitSnapshot();
				break;
			}
			case "hello": {
				if (this.#bcWs && this.#bcWs.readyState === WebSocket.OPEN) {
					this.#bcWs.send(msg.wire);
				}
				break;
			}
			case "state": {
				this.#state = msg.state;
				this.#viewport.applyRobotPose({
					rootPosMj: msg.state.rootPosMj,
					rootQuatMjWxyz: msg.state.rootQuatMjWxyz,
					jointsDeg: msg.state.jointsDeg,
				});
				const isMoving =
					msg.state.neural.activeRole === "gait" ||
					msg.state.neural.activeRole === "native" ||
					this.#activeWalkSeq !== null;
				this.#worldAudio.updateRobotTelemetry(
					msg.state.rootPosMj,
					msg.state.footContacts,
					isMoving,
				);
				this.#publishMultiplayerPose(false);
				const now = performance.now();
				if (now - this.#lastStateUiEmitMs >= 50) {
					this.#lastStateUiEmitMs = now;
					this.#emitSnapshot();
				}
				break;
			}
			case "face": {
				const rgba = new Uint8Array(msg.rgba);
				this.#lastFaceWidth = msg.width;
				this.#lastFaceHeight = msg.height;
				this.#lastFaceRgba = rgba;
				this.#viewport.updateFaceRgba(msg.width, msg.height, rgba);
				this.#callbacks.onFaceRgba?.(msg.width, msg.height, rgba);
				break;
			}
			case "protocol-tx": {
				for (const wire of msg.messages) {
					if (wire.includes('"name":"imu"')) {
						try {
							const ev = JSON.parse(wire) as {
								data?: { boot_id?: unknown; timestamp_us?: unknown };
							};
							const bootId = Number(ev.data?.boot_id);
							const tsUs = Number(ev.data?.timestamp_us);
							if (Number.isInteger(bootId) && bootId >= 0) {
								this.#lastImuBootId = bootId;
							}
							if (Number.isInteger(tsUs) && tsUs > 0) {
								this.#lastImuTimestampUs = tsUs;
							}
						} catch {
							// ignore
						}
					}
					if (this.#controlMode === "body-control" && this.#bcConnected) {
						this.#sendBodyControlRaw(wire);
					}
				}
				break;
			}
			case "protocol-packet": {
				if (
					this.#controlMode === "body-control" &&
					this.#bcConnected &&
					this.#bcWs &&
					this.#bcWs.readyState === WebSocket.OPEN
				) {
					if (msg.preText) {
						this.#bcWs.send(msg.preText);
					}
					this.#bcWs.send(msg.binary);
					if (msg.postText) {
						this.#bcWs.send(msg.postText);
					}
				}
				break;
			}
			case "media-action": {
				this.#handleMediaAction(msg.action);
				break;
			}
			case "recording-export": {
				this.#downloadRollout(msg.label, msg.jsonl);
				this.#lastCommandLog = `Downloaded ${msg.label}.jsonl (${msg.steps} steps @ 50 Hz)`;
				this.#emitSnapshot();
				break;
			}
		}
	}

	#handleMediaAction(action: Record<string, unknown>): void {
		const kind = String(action.kind ?? "");
		if (kind === "snapshot") {
			const res = String(action.res ?? "960P");
			const origin = action.origin === "audio" ? "audio" : "request";
			const originId = Number(action.origin_id ?? action.seq ?? 0);
			void this.#captureAndPublishCameraFrame(
				res === "AUTO" ? "960P" : res,
				origin,
				originId,
			);
		} else if (kind === "stream_frame") {
			if (!this.#ready) {
				return;
			}
			const res =
				this.#controlMode === "body-control"
					? String(action.res ?? this.#state?.camera.res ?? "VGA")
					: "QVGA";
			void this.#captureAndPublishCameraFrame(res, "stream", 0);
		} else if (kind === "speaker") {
			const vol = Number(action.volume ?? 85);
			if (Number.isFinite(vol)) {
				this.#speakerVolume = vol;
			}
		} else if (kind === "stop_media") {
			this.#audio.stopSpeaker();
			this.#worldAudio.setRobotSpeechDucking(false);
			this.#postWorker({ type: "set-media", talking: false });
		}
	}

	async #captureAndPublishCameraFrame(
		resName: string,
		origin: "stream" | "request" | "audio",
		originId: number,
	): Promise<void> {
		if (this.#cameraCaptureBusy || this.#disposed) {
			return;
		}
		this.#cameraCaptureBusy = true;
		try {
			const dims = cameraResolutionDimensions(resName);
			const capture = await this.#viewport.captureChinCameraJpeg(
				dims.width,
				dims.height,
				origin === "stream" ? 0.72 : 0.85,
			);
			if (!capture) {
				return;
			}
			this.#cameraPreviewDataUrl = capture.dataUrl;
			this.#emitSnapshot();

			if (
				this.#controlMode === "body-control" &&
				this.#bcConnected &&
				this.#bcWs &&
				this.#bcWs.readyState === WebSocket.OPEN
			) {
				const jpegCopy = capture.jpeg.slice().buffer;
				this.#postWorker(
					{
						type: "camera-frame",
						origin,
						originId,
						res: resName.toUpperCase(),
						frameCompletedUs: this.#lastImuTimestampUs,
						bootId: this.#lastImuBootId,
						jpeg: jpegCopy,
					},
					[jpegCopy],
				);
			}
		} finally {
			this.#cameraCaptureBusy = false;
		}
	}

	#downloadRollout(label: string, jsonl: string): void {
		const safeName = label.replace(/[^a-zA-Z0-9_-]+/g, "_") || "rollout";
		const blob = new Blob([jsonl], { type: "application/x-ndjson" });
		const url = URL.createObjectURL(blob);
		const a = document.createElement("a");
		a.href = url;
		a.download = `${safeName}.jsonl`;
		document.body.appendChild(a);
		a.click();
		a.remove();
		window.setTimeout(() => URL.revokeObjectURL(url), 5000);
	}

	#nextSeq(): number {
		const seq = this.#standaloneSeq;
		this.#standaloneSeq += 1;
		return seq;
	}

	#sendStandaloneWire(payload: Record<string, unknown>): void {
		this.#postWorker({
			type: "protocol-rx",
			wire: JSON.stringify(payload),
			epoch: STANDALONE_EPOCH,
		});
	}

	#sendBodyControlJson(payload: Record<string, unknown>): void {
		this.#sendBodyControlRaw(JSON.stringify(payload));
	}

	#sendBodyControlRaw(wire: string): void {
		if (this.#bcWs && this.#bcWs.readyState === WebSocket.OPEN) {
			this.#bcWs.send(wire);
		}
	}

	#postWorker(msg: WorkerInboundMessage, transfer?: Transferable[]): void {
		if (transfer && transfer.length > 0) {
			this.#worker?.postMessage(msg, transfer);
		} else {
			this.#worker?.postMessage(msg);
		}
	}

	#emitSnapshot(): void {
		this.#callbacks.onSnapshot({
			ready: this.#ready,
			loadingMessage: this.#loadingMessage,
			robotModel: this.#robotModel,
			levelId: this.#levelId,
			cameraMode: this.#cameraMode,
			engineMode: this.#engineMode,
			neuralGaitModelId: this.#neuralGaitModelId,
			neuralPoseModelId: this.#neuralPoseModelId,
			neuralMotions: this.#neuralMotions,
			control: {
				mode: this.#controlMode,
				url: this.#bcUrl,
				robotId: this.#bcRobotId,
				connected: this.#bcConnected,
				reconnecting: this.#bcReconnecting,
				autoReconnect: this.#bcAutoReconnect,
				epoch: this.#bcEpoch,
				error: this.#bcError,
			},
			state: this.#state,
			cameraPreviewDataUrl: this.#cameraPreviewDataUrl,
			micActive: this.#audio.micActive,
			micSupported: this.#audio.micSupported,
			audio: this.#worldAudio.getState(),
			multiplayer: this.#multiplayerSnapshot,
			commsMessages: [...this.#commsMessages],
			lastCommandLog: this.#lastCommandLog,
			availableClips: this.#availableClips,
			lastError: this.#lastError,
		});
	}

	dispose(): void {
		if (this.#disposed) {
			return;
		}
		this.#disposed = true;
		if (this.#onVisibilityChange && typeof document !== "undefined") {
			document.removeEventListener(
				"visibilitychange",
				this.#onVisibilityChange,
			);
		}
		if (this.#standalonePingTimer !== undefined) {
			window.clearInterval(this.#standalonePingTimer);
		}
		if (this.#speakerTalkingTimer !== undefined) {
			window.clearTimeout(this.#speakerTalkingTimer);
		}
		this.disconnectBodyControl(false);
		this.#unsubscribeMultiplayer();
		this.#multiplayer.disconnect();
		this.#worker?.terminate();
		this.#audio.dispose();
		this.#worldAudio.dispose();
		this.#viewport.dispose();
	}
}

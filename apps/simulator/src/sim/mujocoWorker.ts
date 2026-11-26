/// <reference lib="webworker" />
/**
 * Dedicated Web Worker running:
 *  - Google DeepMind MuJoCo WASM at 500 Hz (10 substeps / 20 ms tick)
 *  - Compiled ESP32-P4 C firmware (`ainekio-v2-firmware.wasm`: body.c + face.c + face_timeline.c)
 *  - 208 Hz IMU (LSM6DS3) + 50 Hz 4th-wire servo feedback/stall/I2t
 *  - Real-time 320x170 ST7789 face rendering + 50 Hz RL rollout recorder
 */

import {
	type ArenaBoxObstacle,
	type ArenaCollider,
	type ArenaHeightfield,
	type LocomotionEngineMode,
	type NeuralMotionCatalogItem,
	type RobotModelId,
	type RobotTelemetryState,
	SIM_FACE_HEIGHT,
	SIM_FACE_WIDTH,
	type V1PhysicsConfig,
	type V2PhysicsConfig,
	V2_CLIP_ACTIONS,
	type V3PhysicsConfig,
	type WorkerInboundMessage,
	type WorkerOutboundMessage,
} from "./contracts.js";
import {
	type CompiledNeuralPoseMotion,
	type CompiledPoseSegment,
	type NeuralGaitManifest,
	NeuralGaitObservationHistory,
	NeuralGaitPolicy,
	type NeuralPoseLibrary,
	type NeuralPoseManifest,
	NeuralPoseObservationHistory,
	NeuralPosePolicy,
	V1GaitObservationHistory,
	type V1NeuralGaitManifest,
	V1NeuralGaitPolicy,
	type V1NeuralPoseManifest,
	V1NeuralPosePolicy,
	V1PoseObservationHistory,
	V3GaitObservationHistory,
	type V3NeuralGaitManifest,
	V3NeuralGaitPolicy,
	type V3NeuralPoseManifest,
	V3NeuralPosePolicy,
	V3PoseObservationHistory,
	V3ProprioSensorFilter,
	bodyLinearVelocityFromWxyz,
	projectedGravityFromWxyz,
	relativeOrientationWxyz,
	sampleV1NativePostureDeg,
	sampleV1NativeWalkDeg,
	sampleV3NativePostureDeg,
	sampleV3NativeWalkDeg,
	walkingOrientationReference,
} from "./neuralPolicies.js";
import {
	type PoseManifoldConfig,
	PoseManifoldRuntime,
} from "./poseManifold.js";

// Minimal structural types for dynamically imported Emscripten modules
type MujocoModule = {
	FS: {
		mkdir(path: string): void;
		writeFile(path: string, data: string | Uint8Array): void;
		unlink(path: string): void;
	};
	MjModel: {
		loadFromXML(path: string): MujocoModel;
	};
	MjData: new (model: MujocoModel) => MujocoData;
	mj_step(model: MujocoModel, data: MujocoData): void;
	mj_forward(model: MujocoModel, data: MujocoData): void;
};

type MujocoModel = {
	nq: number;
	nv: number;
	nu: number;
	ngeom: number;
	actuator_forcerange: Float64Array;
	delete(): void;
};

type MujocoData = {
	time: number;
	ncon: number;
	qpos: Float64Array;
	qvel: Float64Array;
	ctrl: Float64Array;
	xfrc_applied: Float64Array;
	sensordata: Float64Array;
	contact: {
		size(): number;
		get(
			index: number,
		): { geom1: number; geom2: number; delete(): void } | undefined;
		delete(): void;
	};
	delete(): void;
};

type FirmwareWasm = {
	_malloc(bytes: number): number;
	_free(ptr: number): void;
	_simulation_new(mapping: number, feedback: number, settings: number): number;
	_simulation_free(state: number): void;
	_simulation_imu(
		state: number,
		nowUs: number,
		accel: number,
		gyro: number,
		out: number,
	): void;
	_simulation_feedback(
		state: number,
		raw: number,
		target: number,
		timestamps: number,
		out: number,
	): number;
	_virtual_body_set_full_parity(enabled: number): void;
	_virtual_body_reset(
		sensor: number,
		refDeg: number,
		settings: number,
		nowUs: bigint,
	): number;
	_virtual_body_close(): void;
	_virtual_body_tick(nowUs: bigint, out: number): number;
	_virtual_body_telemetry(nowUs: bigint, buf: number, cap: number): number;
	_virtual_body_open(conn: bigint, nowUs: bigint): void;
	_virtual_body_connection_lost(conn: bigint): void;
	_virtual_body_hello(
		id: number,
		token: number,
		nowUs: bigint,
		buf: number,
		cap: number,
	): number;
	_virtual_body_receive(
		wire: number,
		conn: bigint,
		nowUs: bigint,
		buf: number,
		cap: number,
	): number;
	_virtual_body_events(buf: number, cap: number): number;
	_virtual_body_set_face_style?(style: number): void;
	_virtual_body_set_media_state(
		cameraReady: number,
		microphoneReady: number,
		speakerReady: number,
		wakeReady: number,
		displayReady: number,
		capturing: number,
		speakerBusy: number,
		externalSpeech: number,
		micRms: number,
		micPeak: number,
		batteryVoltage: number,
	): void;
	_virtual_body_status(nowUs: bigint, buf: number, cap: number): number;
	_virtual_body_heartbeat(
		nowUs: bigint,
		pong: number,
		buf: number,
		cap: number,
	): number;
	_virtual_body_feedback_health(
		nowUs: bigint,
		buf: number,
		cap: number,
	): number;
	_virtual_body_media_actions(buf: number, cap: number): number;
	_virtual_body_mic_gate(
		nowUs: bigint,
		open: number,
		wakeWord: number,
		buf: number,
		cap: number,
	): number;
	_virtual_body_mic_frame(
		nowUs: bigint,
		pcm: number,
		pcmLen: number,
		packetOut: number,
		packetCap: number,
	): number;
	_virtual_body_camera_frame(
		nowUs: bigint,
		origin: number,
		originId: number,
		resName: number,
		frameCompletedUs: bigint,
		bootId: number,
		jpeg: number,
		jpegLen: number,
		metaOut: number,
		metaCap: number,
		packetOut: number,
		packetCap: number,
		doneOut: number,
		doneCap: number,
	): number;
	_virtual_body_face_frame(
		nowMs: bigint,
		talking: number,
		capturing: number,
		rgbaOut: number,
		nameOut: number,
		nameCap: number,
		tokenOut: number,
		tokenCap: number,
	): number;
	UTF8ToString(ptr: number, maxBytes?: number): string;
	stringToUTF8(str: string, outPtr: number, maxBytes: number): void;
	lengthBytesUTF8(str: string): number;
	HEAPU8: Uint8Array;
	HEAPF64: Float64Array;
};

const RAD2DEG = 180 / Math.PI;
const DEG2RAD = Math.PI / 180;
const TEXT_BUF_CAP = 32768;
const FACE_RGBA_BYTES = SIM_FACE_WIDTH * SIM_FACE_HEIGHT * 4;

let mujoco: MujocoModule | undefined;
let mjModel: MujocoModel | undefined;
let mjData: MujocoData | undefined;
let fw: FirmwareWasm | undefined;
let config: V2PhysicsConfig | undefined;
let baseXml = "";
let workerBaseUrl = "";
const hfieldCache = new Map<string, Uint8Array>();
let extraWorldGeomCount = 0;

// Lazy-loaded Ainekio V1 (8-Servo) & V3 (12-Servo Komatsu) physics & neural runtime state
let activeRobotModel: RobotModelId = "v2";
let v1BaseXml = "";
let v1Config: V1PhysicsConfig | undefined;
let v1GaitPolicy: V1NeuralGaitPolicy | undefined;
let v1PoseManifest: V1NeuralPoseManifest | undefined;
let v1PosePolicy: V1NeuralPosePolicy | undefined;
let v1PosePolicyLoadPromise:
	| Promise<V1NeuralPosePolicy | undefined>
	| undefined;
const v1GaitHistory = new V1GaitObservationHistory();
const v1PoseHistory = new V1PoseObservationHistory();
let v1ActiveRole: "idle" | "gait" | "pose" | "native" = "idle";
let v1Twist: [number, number, number] = [0, 0, 0];
let v1PhaseRad = 0;
const v1PrevGaitAction = new Float64Array(8);
const v1PrevPoseAction = new Float64Array(8);
const v1TargetDeg = new Float64Array(8);
const v1GoalDeg = new Float64Array(8);
let v1GoalSupport: [number, number, number, number] = [1, 1, 1, 1];
let v1ActiveMotionId: string | undefined;
let v1MotionStartS = 0;
let v1Armed = true;
let v1NativePhase01 = 0;
let v1NativeWalkCmd: [number, number, number, number] = [0, 0, 0, 1];
let v1LastInferMs = 0;
const v1GaitFrameBuf = new Float32Array(38);
const v1PoseFrameBuf = new Float32Array(54);
const V1_CLIP_ACTIONS: readonly string[] = [
	"stand",
	"sit",
	"lay_down",
	"crouch",
	"bow",
	"stretch",
	"wave_fr",
	"wave_fl",
];

let v3BaseXml = "";
let v3Config: V3PhysicsConfig | undefined;
let v3GaitPolicy: V3NeuralGaitPolicy | undefined;
let v3PoseManifest: V3NeuralPoseManifest | undefined;
let v3PosePolicy: V3NeuralPosePolicy | undefined;
let v3PosePolicyLoadPromise:
	| Promise<V3NeuralPosePolicy | undefined>
	| undefined;
let v3GaitHistory = new V3GaitObservationHistory();
const v3PoseHistory = new V3PoseObservationHistory();
const v3Sensors = new V3ProprioSensorFilter();
const v3QTrueBuf = new Float64Array(12);
const v3DelayQueue: Float64Array[] = [];
let v3ActiveRole: "idle" | "gait" | "pose" | "native" = "idle";
let v3Twist: [number, number, number] = [0, 0, 0];
let v3PhaseRad = 0;
const v3PrevGaitAction = new Float64Array(12);
const v3PrevPoseAction = new Float64Array(12);
const v3TargetDeg = new Float64Array(12);
const v3GoalDeg = new Float64Array(12);
let v3GoalSupport: [number, number, number, number] = [1, 1, 1, 1];
let v3ActiveMotionId: string | undefined;
let v3MotionStartS = 0;
let v3Armed = true;
let v3NativePhase01 = 0;
let v3NativeWalkCmd: [number, number, number] = [0, 0, 0];
let v3LastInferMs = 0;
const v3GaitFrameBuf = new Float32Array(50);
const v3PoseFrameBuf = new Float32Array(86);
const V3_CLIP_ACTIONS: readonly string[] = [
	"stand",
	"sit",
	"lay_down",
	"crouch",
	"bow",
	"stretch",
	"wave_fr",
	"wave_fl",
];

let simStatePtr = 0;
let textBufPtr = 0;
let tickOutPtr = 0;
let accelPtr = 0;
let gyroPtr = 0;
let imuOutPtr = 0;
let rawPtr = 0;
let targetPtr = 0;
let tsPtr = 0;
let fbOutPtr = 0;
let faceRgbaPtr = 0;
let faceNamePtr = 0;
let faceTokenPtr = 0;
let micPcmPtr = 0;
let micPktPtr = 0;

let activeConnectionId = 0n;
let simTimeOffsetS = 0;
let emitProtocolTx = false;
let runningTimer: number | undefined;
let nextImuS = 0;
let nextFeedbackS = 0;
let lastFaceRenderMs = 0;
let lastStatusMs = 0;
let lastHeartbeatMs = 0;
let lastFaceHash = 0;

const lastTargetDeg = new Float64Array(12);
const lastLogicalDeg = new Float64Array(12);
const lastMeasuredDeg = new Float64Array(12);
const lastVelocityDegS = new Float64Array(12);
const lastFeedbackUsable: boolean[] = Array.from({ length: 12 }, () => true);
const lastImuSample = new Float64Array(14);
let lastArmed = false;
let lastEnabledMask = 0;
let lastJammedMask = 0;
let lastMotionSeq = 0;
let lastNominalSample = 0;
let lastFaceName = "default";
let lastFaceToken = "";
const batteryVoltage = 8.15;

// Embedded production Neural Gait (MicroDuck) & Neural Pose (v7-hysteresis) runtime
let engineMode: LocomotionEngineMode = "neural";
let gaitPolicy: NeuralGaitPolicy | undefined;
let poseManifest: NeuralPoseManifest | undefined;
let posePolicy: NeuralPosePolicy | undefined;
let posePolicyLoadPromise: Promise<NeuralPosePolicy | undefined> | undefined;
let poseRequestSeq = 0;
let poseManifold: PoseManifoldRuntime | undefined;
let poseLibrary: NeuralPoseLibrary | undefined;
const gaitHistory = new NeuralGaitObservationHistory();
const poseHistory = new NeuralPoseObservationHistory();

// Monotonic standalone sequence allocator (shared across worker neural streams & main-thread protocol-rx)
let standaloneSeq = 1;
const standaloneSeqRemap = new Map<number, number>();
let standaloneEpoch = 1;
let lastStandalonePingUs = 0n;

// Active 50 Hz neural stream state
let activeNeuralRole: "idle" | "gait" | "pose" | "native" = "idle";
let lastNeuralInferMs = 0;
let hostSamplesSent = 0;
let hostNakCount = 0;

// Neural Gait host-walk state
let gaitWalkSeq: number | null = null;
let gaitSampleIdx = 0;
let gaitConsumedSample = 0;
let gaitOrientationRef: readonly [number, number] | undefined;
let gaitTwist: [number, number, number] = [0, 0, 0];
const gaitPrevAction = new Float64Array(12);
const gaitSentActions = new Map<number, number[]>();

// Neural Pose host-program state
type ActivePoseProgram = {
	readonly motion: CompiledNeuralPoseMotion;
	segIndex: number;
	segStartedS: number;
	walkSeq: number;
	sampleIdx: number;
	cmdQRad: Float64Array;
	prevAction: number[];
	holdGoalDeg: number[];
	holdGoalFoot: number[];
	holdSupport: number[];
	settledFrames: number;
	prevCmdDeg: number[] | null;
	prevUsableDeg: Map<number, number>;
	liveStartDeg: number[];
};
let activePose: ActivePoseProgram | undefined;

// Media flags synced from main thread
let mediaTalking = false;
let mediaCapturing = false;
let mediaMicRms = 0;
let mediaMicPeak = 0;
let mediaCameraReady = true;

// Camera runtime state (boots disabled matching P4 camera.c until configured)
let cameraEnabled = false;
let cameraFps = 0;
let cameraRes = "VGA";
let cameraSnapshotRes = "AUTO";
let lastCameraStreamMs = 0;

function maybeEmitCameraStreamTick(nowWallMs: number): void {
	if (!mediaCameraReady) {
		return;
	}
	if (emitProtocolTx) {
		if (!cameraEnabled || cameraFps <= 0) {
			return;
		}
		const targetFps = Math.min(15, cameraFps);
		const intervalMs = Math.max(66, Math.round(1000 / targetFps));
		if (nowWallMs - lastCameraStreamMs >= intervalMs) {
			lastCameraStreamMs = nowWallMs;
			post({
				type: "media-action",
				action: { kind: "stream_frame", res: cameraRes },
			});
		}
		return;
	}
	if (nowWallMs - lastCameraStreamMs >= 500) {
		lastCameraStreamMs = nowWallMs;
		post({
			type: "media-action",
			action: { kind: "stream_frame", res: "QVGA" },
		});
	}
}

// External interactions (wrenches + pinned joints)
const activeWrench = new Float64Array(6);
let wrenchUntilMs = 0;
const pinnedJoints = new Map<number, number>();
let currentSpawnMj: readonly [number, number, number] = [0, 0, 0.066];
const actuatorQueue: Array<{ readonly t: number; readonly q: Float64Array }> =
	[];

// Synchronized 50 Hz RL rollout recorder
let recordingActive = false;
let recordingLabel = "";
let recordingRows: string[] = [];
let recordingStartXy: [number, number] | undefined;
let recordingLastXy: [number, number] | undefined;
let recordingStartedAtMs = 0;

function post(msg: WorkerOutboundMessage, transfer?: Transferable[]): void {
	if (transfer && transfer.length > 0) {
		self.postMessage(msg, transfer);
	} else {
		self.postMessage(msg);
	}
}

function nowDeviceUs(): bigint {
	const t = (mjData ? mjData.time : 0) + simTimeOffsetS;
	const pre = config ? config.imuPrehistoryS : 0.5;
	return BigInt(Math.round((t + pre) * 1_000_000));
}

function gaussNoise(std: number): number {
	if (std <= 0) {
		return 0;
	}
	const u1 = Math.max(1e-7, Math.random());
	const u2 = Math.random();
	return Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2) * std;
}

function writeDoubles(values: ArrayLike<number>): number {
	if (!fw) {
		throw new Error("Firmware WASM not initialized");
	}
	const ptr = fw._malloc(values.length * 8);
	fw.HEAPF64.set(values, ptr >> 3);
	return ptr;
}

function writeCString(text: string): number {
	if (!fw) {
		throw new Error("Firmware WASM not initialized");
	}
	const len = fw.lengthBytesUTF8(text) + 1;
	const ptr = fw._malloc(len);
	fw.stringToUTF8(text, ptr, len);
	return ptr;
}

function buildLevelXml(
	obstacles: readonly ArenaBoxObstacle[],
	colliders: readonly ArenaCollider[],
	hfield: ArenaHeightfield | undefined,
	useDefaultFloorPlane: boolean,
): string {
	let xml =
		activeRobotModel === "v1"
			? v1BaseXml
			: activeRobotModel === "v3"
				? v3BaseXml
				: baseXml;
	if (!useDefaultFloorPlane) {
		xml = xml.replace(
			'<geom name="floor" type="plane"',
			'<geom name="floor" type="plane" pos="0 0 -200"',
		);
	}

	const geoms: string[] = [];
	if (hfield) {
		const [sx, sy, sz, sb] = hfield.sizeMj;
		const [px, py, pz] = hfield.posMj;
		const hfieldAsset = `<hfield name="level_hfield" file="level.hfield" size="${sx} ${sy} ${sz} ${sb}" />`;
		const assetClose = xml.indexOf("</asset>");
		if (assetClose >= 0) {
			xml = `${xml.slice(0, assetClose)}${hfieldAsset}${xml.slice(assetClose)}`;
		} else {
			const wbOpen = xml.indexOf("<worldbody>");
			if (wbOpen >= 0) {
				xml = `${xml.slice(0, wbOpen)}<asset>${hfieldAsset}</asset>${xml.slice(wbOpen)}`;
			}
		}
		geoms.push(
			`<geom name="level_terrain" type="hfield" hfield="level_hfield" pos="${px} ${py} ${pz}" friction="0.85 0.005 0.0001" condim="3" />`,
		);
	}

	for (const obs of obstacles) {
		const [x, y, z] = obs.posMj;
		const [hx, hy, hz] = obs.halfSizeMj;
		const safeName = `obs_${obs.id.replace(/[^a-zA-Z0-9_]/g, "_")}`;
		geoms.push(
			`<geom name="${safeName}" type="box" pos="${x} ${y} ${z}" size="${hx} ${hy} ${hz}" friction="0.85 0.005 0.0001" condim="3" />`,
		);
	}

	for (let i = 0; i < colliders.length; i += 1) {
		const col = colliders[i];
		if (!col) {
			continue;
		}
		const [px, py, pz] = col.posMj;
		const [qw, qx, qy, qz] = col.quatMj;
		const safeName = `col_${i}_${col.id.replace(/[^a-zA-Z0-9_]/g, "_").slice(0, 28)}`;
		if (col.shape === "box") {
			const [hx, hy, hz] = col.sizeMj;
			geoms.push(
				`<geom name="${safeName}" type="box" pos="${px} ${py} ${pz}" quat="${qw} ${qx} ${qy} ${qz}" size="${hx} ${hy} ${hz}" friction="0.85 0.005 0.0001" condim="3" />`,
			);
		} else {
			const [rad, hh] = col.sizeMj;
			geoms.push(
				`<geom name="${safeName}" type="cylinder" pos="${px} ${py} ${pz}" quat="${qw} ${qx} ${qy} ${qz}" size="${rad} ${hh}" friction="0.85 0.005 0.0001" condim="3" />`,
			);
		}
	}

	extraWorldGeomCount = geoms.length;
	if (geoms.length === 0) {
		return xml;
	}
	const marker = "</worldbody>";
	const idx = xml.lastIndexOf(marker);
	if (idx < 0) {
		return xml;
	}
	return `${xml.slice(0, idx)}${geoms.join("")}${xml.slice(idx)}`;
}

async function fetchHfieldBytes(url: string): Promise<Uint8Array> {
	const cached = hfieldCache.get(url);
	if (cached) {
		return cached;
	}
	const fullUrl = url.startsWith("http")
		? url
		: `${workerBaseUrl}${url.startsWith("/") ? "" : "/"}${url}`;
	const resp = await fetch(fullUrl);
	if (!resp.ok) {
		throw new Error(
			`Failed to fetch terrain heightfield ${url} (${resp.status})`,
		);
	}
	const bytes = new Uint8Array(await resp.arrayBuffer());
	hfieldCache.set(url, bytes);
	return bytes;
}

async function loadMujocoModel(
	obstacles: readonly ArenaBoxObstacle[],
	spawnMj: readonly [number, number, number],
	colliders: readonly ArenaCollider[] = [],
	hfield?: ArenaHeightfield,
	useDefaultFloorPlane = true,
): Promise<void> {
	if (!mujoco || !config) {
		return;
	}
	currentSpawnMj = spawnMj;
	try {
		mujoco.FS.mkdir("/working");
	} catch {
		// Directory already exists
	}
	if (hfield) {
		const hfBytes = await fetchHfieldBytes(hfield.url);
		mujoco.FS.writeFile("/working/level.hfield", hfBytes);
	}
	if (mjData) {
		simTimeOffsetS += mjData.time;
		mjData.delete();
		mjData = undefined;
	}
	if (mjModel) {
		mjModel.delete();
		mjModel = undefined;
	}
	const xml = buildLevelXml(obstacles, colliders, hfield, useDefaultFloorPlane);
	const xmlPath = `/working/ainekio-${activeRobotModel}.xml`;
	mujoco.FS.writeFile(xmlPath, xml);
	mjModel = mujoco.MjModel.loadFromXML(xmlPath);
	mjData = new mujoco.MjData(mjModel);
	resetRobotPose(spawnMj);
}

async function ensureV2PosePolicyLoaded(): Promise<
	NeuralPosePolicy | undefined
> {
	if (posePolicy) {
		return posePolicy;
	}
	if (posePolicyLoadPromise) {
		return posePolicyLoadPromise;
	}
	const prefix = workerBaseUrl;
	posePolicyLoadPromise = (async () => {
		const [manifest, binResp] = await Promise.all([
			poseManifest
				? Promise.resolve(poseManifest)
				: fetch(`${prefix}/sim/policies/neural-pose.json`).then((r) => {
						if (!r.ok) {
							throw new Error(`Failed to fetch neural-pose.json (${r.status})`);
						}
						return r.json() as Promise<NeuralPoseManifest>;
					}),
			fetch(`${prefix}/sim/policies/neural-pose.bin`),
		]);
		if (!binResp.ok) {
			throw new Error(`Failed to fetch neural-pose.bin (${binResp.status})`);
		}
		poseManifest = manifest;
		const buf = await binResp.arrayBuffer();
		posePolicy = new NeuralPosePolicy(manifest, new Float32Array(buf));
		return posePolicy;
	})().catch((err) => {
		posePolicyLoadPromise = undefined;
		post({
			type: "error",
			message:
				err instanceof Error
					? err.message
					: "Failed to lazy-load V2 Neural Pose weights.",
		});
		return undefined;
	});
	return posePolicyLoadPromise;
}

async function ensureV1PosePolicyLoaded(): Promise<
	V1NeuralPosePolicy | undefined
> {
	if (v1PosePolicy) {
		return v1PosePolicy;
	}
	if (v1PosePolicyLoadPromise) {
		return v1PosePolicyLoadPromise;
	}
	const prefix = workerBaseUrl;
	v1PosePolicyLoadPromise = (async () => {
		const [manifest, binResp] = await Promise.all([
			v1PoseManifest
				? Promise.resolve(v1PoseManifest)
				: fetch(`${prefix}/sim/policies/v1-neural-pose.json`).then((r) => {
						if (!r.ok) {
							throw new Error(
								`Failed to fetch v1-neural-pose.json (${r.status})`,
							);
						}
						return r.json() as Promise<V1NeuralPoseManifest>;
					}),
			fetch(`${prefix}/sim/policies/v1-neural-pose.bin`),
		]);
		if (!binResp.ok) {
			throw new Error(`Failed to fetch v1-neural-pose.bin (${binResp.status})`);
		}
		v1PoseManifest = manifest;
		const buf = await binResp.arrayBuffer();
		v1PosePolicy = new V1NeuralPosePolicy(manifest, new Float32Array(buf));
		return v1PosePolicy;
	})().catch((err) => {
		v1PosePolicyLoadPromise = undefined;
		post({
			type: "error",
			message:
				err instanceof Error
					? err.message
					: "Failed to lazy-load V1 Neural Pose weights.",
		});
		return undefined;
	});
	return v1PosePolicyLoadPromise;
}

async function ensureV3PosePolicyLoaded(): Promise<
	V3NeuralPosePolicy | undefined
> {
	if (v3PosePolicy) {
		return v3PosePolicy;
	}
	if (v3PosePolicyLoadPromise) {
		return v3PosePolicyLoadPromise;
	}
	const prefix = workerBaseUrl;
	v3PosePolicyLoadPromise = (async () => {
		const [manifest, binResp] = await Promise.all([
			v3PoseManifest
				? Promise.resolve(v3PoseManifest)
				: fetch(`${prefix}/sim/policies/v3-neural-pose.json`).then((r) => {
						if (!r.ok) {
							throw new Error(
								`Failed to fetch v3-neural-pose.json (${r.status})`,
							);
						}
						return r.json() as Promise<V3NeuralPoseManifest>;
					}),
			fetch(`${prefix}/sim/policies/v3-neural-pose.bin`),
		]);
		if (!binResp.ok) {
			throw new Error(`Failed to fetch v3-neural-pose.bin (${binResp.status})`);
		}
		v3PoseManifest = manifest;
		const buf = await binResp.arrayBuffer();
		v3PosePolicy = new V3NeuralPosePolicy(manifest, new Float32Array(buf));
		return v3PosePolicy;
	})().catch((err) => {
		v3PosePolicyLoadPromise = undefined;
		post({
			type: "error",
			message:
				err instanceof Error
					? err.message
					: "Failed to lazy-load V3 Neural Pose weights.",
		});
		return undefined;
	});
	return v3PosePolicyLoadPromise;
}

async function ensureV1AssetsLoaded(): Promise<void> {
	if (v1Config && v1BaseXml && v1GaitPolicy && v1PoseManifest) {
		return;
	}
	const prefix = workerBaseUrl;
	const [cfgResp, xmlResp, gaitJsonResp, gaitBinResp, poseJsonResp] =
		await Promise.all([
			fetch(`${prefix}/sim/v1-physics-config.json`),
			fetch(`${prefix}/sim/ainekio-v1-locomotion.xml`),
			fetch(`${prefix}/sim/policies/v1-neural-gait.json`),
			fetch(`${prefix}/sim/policies/v1-neural-gait.bin`),
			fetch(`${prefix}/sim/policies/v1-neural-pose.json`),
		]);
	if (
		!cfgResp.ok ||
		!xmlResp.ok ||
		!gaitJsonResp.ok ||
		!gaitBinResp.ok ||
		!poseJsonResp.ok
	) {
		throw new Error(
			"Failed to fetch Ainekio V1 physics or neural policy assets.",
		);
	}
	const [cfgData, xmlText, gaitManifest, gaitBuf, loadedPoseManifest] =
		await Promise.all([
			cfgResp.json() as Promise<V1PhysicsConfig>,
			xmlResp.text(),
			gaitJsonResp.json() as Promise<V1NeuralGaitManifest>,
			gaitBinResp.arrayBuffer(),
			poseJsonResp.json() as Promise<V1NeuralPoseManifest>,
		]);
	v1Config = cfgData;
	v1BaseXml = xmlText;
	v1GaitPolicy = new V1NeuralGaitPolicy(
		gaitManifest,
		new Float32Array(gaitBuf),
	);
	v1PoseManifest = loadedPoseManifest;
}

async function ensureV3AssetsLoaded(): Promise<void> {
	if (v3Config && v3BaseXml && v3GaitPolicy && v3PoseManifest) {
		return;
	}
	const prefix = workerBaseUrl;
	const [cfgResp, xmlResp, gaitJsonResp, gaitBinResp, poseJsonResp] =
		await Promise.all([
			fetch(`${prefix}/sim/v3-physics-config.json`),
			fetch(`${prefix}/sim/ainekio-v3-locomotion.xml`),
			fetch(`${prefix}/sim/policies/v3-neural-gait.json`),
			fetch(`${prefix}/sim/policies/v3-neural-gait.bin`),
			fetch(`${prefix}/sim/policies/v3-neural-pose.json`),
		]);
	if (
		!cfgResp.ok ||
		!xmlResp.ok ||
		!gaitJsonResp.ok ||
		!gaitBinResp.ok ||
		!poseJsonResp.ok
	) {
		throw new Error(
			"Failed to fetch Ainekio V3 physics or neural policy assets.",
		);
	}
	const [cfgData, xmlText, gaitManifest, gaitBuf, loadedPoseManifest] =
		await Promise.all([
			cfgResp.json() as Promise<V3PhysicsConfig>,
			xmlResp.text(),
			gaitJsonResp.json() as Promise<V3NeuralGaitManifest>,
			gaitBinResp.arrayBuffer(),
			poseJsonResp.json() as Promise<V3NeuralPoseManifest>,
		]);
	v3Config = cfgData;
	v3BaseXml = xmlText;
	v3GaitPolicy = new V3NeuralGaitPolicy(
		gaitManifest,
		new Float32Array(gaitBuf),
	);
	v3GaitHistory = new V3GaitObservationHistory(
		gaitManifest.featureDim,
		gaitManifest.historySamples,
		false,
	);
	v3PoseManifest = loadedPoseManifest;
}

async function handleSetRobot(
	robotModel: RobotModelId,
	obstacles: readonly ArenaBoxObstacle[],
	spawnMj: readonly [number, number, number],
	colliders: readonly ArenaCollider[] = [],
	hfield?: ArenaHeightfield,
	useDefaultFloorPlane = true,
): Promise<void> {
	poseRequestSeq += 1;
	if (robotModel === "v1") {
		await ensureV1AssetsLoaded();
	} else if (robotModel === "v3") {
		await ensureV3AssetsLoaded();
	}
	activeRobotModel = robotModel;
	fw?._virtual_body_set_face_style?.(robotModel === "v3" ? 1 : 0);
	lastFaceHash = 0;
	await loadMujocoModel(
		obstacles,
		spawnMj,
		colliders,
		hfield,
		useDefaultFloorPlane,
	);
	if (robotModel === "v1" && v1GaitPolicy && v1PoseManifest) {
		const neuralMotions: NeuralMotionCatalogItem[] = v1PoseManifest.motions.map(
			(m) => ({
				id: m.id,
				label: m.label,
				sourceTitle: `V1 Neural Pose (${m.label})`,
			}),
		);
		post({
			type: "robot-ready",
			robotModel: "v1",
			neuralGaitModelId: v1GaitPolicy.manifest.modelId,
			neuralPoseModelId: v1PoseManifest.modelId,
			neuralMotions,
			availableClips: V1_CLIP_ACTIONS,
		});
		return;
	}
	if (robotModel === "v3" && v3GaitPolicy && v3PoseManifest) {
		const neuralMotions: NeuralMotionCatalogItem[] = v3PoseManifest.motions.map(
			(m) => ({
				id: m.id,
				label: m.label,
				sourceTitle: `V3 Neural Pose (${m.label})`,
			}),
		);
		post({
			type: "robot-ready",
			robotModel: "v3",
			neuralGaitModelId: v3GaitPolicy.manifest.modelId,
			neuralPoseModelId: v3PoseManifest.modelId,
			neuralMotions,
			availableClips: V3_CLIP_ACTIONS,
		});
		return;
	}
	const v2Motions: NeuralMotionCatalogItem[] = (poseLibrary?.motions ?? []).map(
		(m) => ({
			id: m.id,
			label: m.label,
			sourceTitle: m.sourceTitle,
		}),
	);
	post({
		type: "robot-ready",
		robotModel: "v2",
		neuralGaitModelId:
			gaitPolicy?.manifest.modelId ?? "microduck-v20-studya-p4",
		neuralPoseModelId:
			posePolicy?.manifest.modelId ??
			poseManifest?.modelId ??
			"neural-pose-v7-hysteresis",
		neuralMotions: v2Motions,
		availableClips: V2_CLIP_ACTIONS,
	});
}

function nextStandaloneSeq(): number {
	const seq = standaloneSeq;
	standaloneSeq += 1;
	return seq;
}

function sendStandaloneFirmwareCommand(
	payload: Record<string, unknown>,
	nowUsOverride?: bigint,
): { readonly seq: number; readonly replies: string[] } {
	if (!fw) {
		return { seq: 0, replies: [] };
	}
	const nowUs = nowUsOverride ?? nowDeviceUs();
	const seq = nextStandaloneSeq();
	const msg: Record<string, unknown> = {
		...payload,
		seq,
		epoch: standaloneEpoch,
	};
	if (msg.t !== "stop" && msg.deadline_ms === undefined) {
		msg.deadline_ms = Number(nowUs / 1000n) + 5000;
	}
	const wirePtr = writeCString(JSON.stringify(msg));
	const n = fw._virtual_body_receive(
		wirePtr,
		activeConnectionId,
		nowUs,
		textBufPtr,
		TEXT_BUF_CAP,
	);
	fw._free(wirePtr);
	const replies: string[] = [];
	if (n > 0) {
		const raw = fw.UTF8ToString(textBufPtr, n);
		try {
			const parsed = JSON.parse(raw) as unknown;
			const items = Array.isArray(parsed) ? parsed : [parsed];
			for (const item of items) {
				const text = typeof item === "string" ? item : JSON.stringify(item);
				replies.push(text);
				if (
					item &&
					typeof item === "object" &&
					(item as { t?: unknown }).t === "nak"
				) {
					hostNakCount += 1;
				}
			}
		} catch {
			replies.push(raw);
		}
	}
	drainMediaActions();
	return { seq, replies };
}

function clearNeuralControllers(): void {
	activeNeuralRole = "idle";
	gaitWalkSeq = null;
	gaitSampleIdx = 0;
	gaitConsumedSample = 0;
	gaitOrientationRef = undefined;
	gaitTwist = [0, 0, 0];
	gaitPrevAction.fill(0);
	gaitSentActions.clear();
	gaitHistory.reset();
	activePose = undefined;
	poseHistory.reset();
}

function currentImuQuatWxyz(): [number, number, number, number] {
	const w = lastImuSample[0] ?? 1;
	const x = lastImuSample[1] ?? 0;
	const y = lastImuSample[2] ?? 0;
	const z = lastImuSample[3] ?? 0;
	const norm = Math.hypot(w, x, y, z);
	if (!Number.isFinite(norm) || norm < 1e-4) {
		return [1, 0, 0, 0];
	}
	return [w / norm, x / norm, y / norm, z / norm];
}

function currentUsableJointAnglesDeg(): number[] {
	const stand = poseManifold?.standAnglesDeg ?? config?.referenceJointDeg ?? [];
	const out: number[] = new Array(12);
	for (let i = 0; i < 12; i += 1) {
		const meas = lastMeasuredDeg[i];
		const cmd = lastLogicalDeg[i];
		if (
			lastFeedbackUsable[i] &&
			typeof meas === "number" &&
			Number.isFinite(meas)
		) {
			out[i] = meas;
		} else if (typeof cmd === "number" && Number.isFinite(cmd)) {
			out[i] = cmd;
		} else {
			out[i] = stand[i] ?? 0;
		}
	}
	return out;
}

function startOrUpdateNeuralWalk(
	forward: number,
	lateral: number,
	turn: number,
	speed: number,
): void {
	if (emitProtocolTx || !fw || !gaitPolicy) {
		return;
	}
	const fwd = Math.max(-100, Math.min(100, forward));
	const lat = Math.max(-100, Math.min(100, lateral));
	const trn = Math.max(-100, Math.min(100, turn));
	const spd = Math.max(10, Math.min(200, speed)) / 100;
	const prof = gaitPolicy.manifest.defaultProfile;
	const twist: [number, number, number] = [
		spd * (fwd / 100) * prof.forwardMS,
		spd * (lat / 100) * prof.lateralMS,
		spd * (trn / 100) * prof.yawRadS,
	];

	if (activeNeuralRole === "gait" && gaitWalkSeq !== null) {
		gaitTwist = twist;
		sendStandaloneFirmwareCommand({
			t: "intent",
			name: "walk",
			dir: "fwd",
			gait: "walk",
			steps: 0,
			speed: 100,
			source: "host",
			twist,
			update: gaitWalkSeq,
		});
		return;
	}

	clearNeuralControllers();
	gaitTwist = twist;
	gaitOrientationRef = walkingOrientationReference(currentImuQuatWxyz());
	const refCd = gaitPolicy.manifest.referenceJointDeg.map((v) =>
		Math.round(v * 100),
	);
	const { seq } = sendStandaloneFirmwareCommand({
		t: "intent",
		name: "walk",
		dir: "fwd",
		gait: "walk",
		steps: 0,
		speed: 100,
		source: "host",
		twist,
		geometry: gaitPolicy.manifest.geometryId,
		reference_cd: refCd,
	});
	gaitWalkSeq = seq;
	gaitSampleIdx = 0;
	gaitConsumedSample = 0;
	activeNeuralRole = "gait";
	stepNeuralGaitTick(nowDeviceUs());
}

function stepNeuralGaitTick(nowUs: bigint): void {
	if (
		emitProtocolTx ||
		activeNeuralRole !== "gait" ||
		gaitWalkSeq === null ||
		!gaitPolicy ||
		!fw
	) {
		return;
	}
	if (lastMotionSeq === gaitWalkSeq && lastNominalSample > gaitConsumedSample) {
		const consumedAct = gaitSentActions.get(lastNominalSample);
		if (consumedAct) {
			for (let i = 0; i < 12; i += 1) {
				gaitPrevAction[i] = consumedAct[i] ?? 0;
			}
			gaitConsumedSample = lastNominalSample;
			for (const key of gaitSentActions.keys()) {
				if (key <= lastNominalSample) {
					gaitSentActions.delete(key);
				}
			}
		}
	}

	const rawQuat = currentImuQuatWxyz();
	if (!gaitOrientationRef) {
		gaitOrientationRef = walkingOrientationReference(rawQuat);
	}
	const relQuat = relativeOrientationWxyz(
		rawQuat,
		gaitOrientationRef[0],
		gaitOrientationRef[1],
	);
	const t0 = performance.now();
	const obs = gaitHistory.pushAndProject({
		observationTimeS: Number(nowUs) / 1e6,
		jointDeg: lastMeasuredDeg,
		jointVelocityDegS: lastVelocityDegS,
		orientationWxyz: relQuat,
		angularRateRadS: [
			lastImuSample[7] ?? 0,
			lastImuSample[8] ?? 0,
			lastImuSample[9] ?? 0,
		],
		accelerationMS2: [
			lastImuSample[4] ?? 0,
			lastImuSample[5] ?? 0,
			lastImuSample[6] ?? 9.81,
		],
		commandTwist: gaitTwist,
		previousAction: gaitPrevAction,
	});
	const action = gaitPolicy.predictAction(obs);
	const feetMm = gaitPolicy.footOffsetsMm(action);
	lastNeuralInferMs = Math.round((performance.now() - t0) * 100) / 100;

	gaitSampleIdx += 1;
	gaitSentActions.set(gaitSampleIdx, action);
	sendStandaloneFirmwareCommand(
		{
			t: "walk_target",
			walk: gaitWalkSeq,
			sample: gaitSampleIdx,
			geometry: gaitPolicy.manifest.geometryId,
			feet_mm: feetMm,
		},
		nowUs,
	);
	hostSamplesSent += 1;
}

function advancePoseFaceSegments(pose: ActivePoseProgram, nowUs: bigint): void {
	while (pose.segIndex < pose.motion.segments.length) {
		const seg = pose.motion.segments[pose.segIndex];
		if (!seg || seg.kind !== "face") {
			break;
		}
		sendStandaloneFirmwareCommand(
			{
				t: "intent",
				name: "face",
				expr: seg.expr,
				timeout_ms: 8000,
			},
			nowUs,
		);
		pose.segIndex += 1;
		pose.segStartedS = Number(nowUs) / 1e6;
	}
}

function startNeuralPoseMotion(motionId: string): void {
	if (emitProtocolTx || !fw || !posePolicy || !poseManifold || !poseLibrary) {
		return;
	}
	const motion = poseLibrary.motions.find((m) => m.id === motionId);
	if (!motion) {
		return;
	}
	clearNeuralControllers();
	const nowUs = nowDeviceUs();
	const curDeg = currentUsableJointAnglesDeg();
	const proj = poseManifold.projectAnglesDeg(curDeg);
	const cmdQRad = new Float64Array(12);
	for (let i = 0; i < 12; i += 1) {
		cmdQRad[i] = (proj.deg[i] ?? 0) * DEG2RAD;
	}
	const refCd = poseManifold.referenceJointDeg.map((v) => Math.round(v * 100));
	const { seq } = sendStandaloneFirmwareCommand(
		{
			t: "intent",
			name: "walk",
			dir: "fwd",
			gait: "walk",
			steps: 0,
			speed: 100,
			source: "host",
			twist: [0, 0, 0],
			geometry: poseManifold.geometryId,
			reference_cd: refCd,
		},
		nowUs,
	);

	// Seed sample 1 at current posture so the P4 never jumps toward reference_cd
	const initFeetMm = poseManifold.feetMmForAnglesRad(cmdQRad);
	sendStandaloneFirmwareCommand(
		{
			t: "walk_target",
			walk: seq,
			sample: 1,
			geometry: poseManifold.geometryId,
			feet_mm: initFeetMm,
		},
		nowUs,
	);
	hostSamplesSent += 1;

	const pose: ActivePoseProgram = {
		motion,
		segIndex: 0,
		segStartedS: Number(nowUs) / 1e6,
		walkSeq: seq,
		sampleIdx: 1,
		cmdQRad,
		prevAction: [...proj.footNorm],
		holdGoalDeg: [...proj.deg],
		holdGoalFoot: [...proj.footNorm],
		holdSupport: [1, 1, 1, 1],
		settledFrames: 0,
		prevCmdDeg: null,
		prevUsableDeg: new Map(),
		liveStartDeg: curDeg,
	};
	activePose = pose;
	activeNeuralRole = "pose";
	advancePoseFaceSegments(pose, nowUs);
}

function stepNeuralPoseTick(nowUs: bigint): void {
	if (
		emitProtocolTx ||
		activeNeuralRole !== "pose" ||
		!activePose ||
		!posePolicy ||
		!poseManifold ||
		!fw
	) {
		return;
	}
	const pose = activePose;
	advancePoseFaceSegments(pose, nowUs);

	if (pose.segIndex >= pose.motion.segments.length) {
		// Lock final posture cleanly in place (matches neural_pose/executor.py line 620)
		sendStandaloneFirmwareCommand({ t: "stop" }, nowUs);
		activePose = undefined;
		activeNeuralRole = "idle";
		return;
	}

	const seg = pose.motion.segments[pose.segIndex] as CompiledPoseSegment;
	const nowS = Number(nowUs) / 1e6;
	const elapsed = Math.max(0, nowS - pose.segStartedS);

	let goalDeg: readonly number[] = pose.holdGoalDeg;
	let goalFoot: readonly number[] = pose.holdGoalFoot;
	let support: readonly number[] = pose.holdSupport;
	let speedScale = 0.5;
	let segComplete = false;

	if (seg.kind === "pose_goal") {
		goalDeg = seg.goalDeg;
		goalFoot = seg.goalFootNorm;
		support = seg.legSupport;
		speedScale = seg.speedScale;
	} else if (seg.kind === "oscillate_goal") {
		const oscDur = seg.cycles / seg.hz;
		support = seg.legSupport;
		speedScale = seg.speedScale;
		if (elapsed < oscDur) {
			const cand = [...seg.baseDeg];
			const phase = 2 * Math.PI * seg.hz * elapsed;
			for (let k = 0; k < seg.jointIndices.length; k += 1) {
				const jIdx = seg.jointIndices[k] ?? 0;
				const center = seg.centersDeg[k] ?? 0;
				const amp = seg.amplitudesDeg[k] ?? 0;
				cand[jIdx] = center + amp * Math.sin(phase);
			}
			const p = poseManifold.projectAnglesDeg(cand);
			goalDeg = p.deg;
			goalFoot = p.footNorm;
		} else {
			const p = poseManifold.projectAnglesDeg(seg.endDeg);
			goalDeg = p.deg;
			goalFoot = p.footNorm;
		}
		if (elapsed >= seg.durationS) {
			segComplete = true;
			const p = poseManifold.projectAnglesDeg(seg.endDeg);
			pose.holdGoalDeg = p.deg;
			pose.holdGoalFoot = p.footNorm;
			pose.holdSupport = [...seg.legSupport];
		}
	} else if (seg.kind === "hold") {
		goalDeg = pose.holdGoalDeg;
		goalFoot = pose.holdGoalFoot;
		support = pose.holdSupport;
		speedScale = 0.5;
		if (elapsed >= Math.max(0.02, seg.seconds)) {
			segComplete = true;
		}
	}

	const trackedCmdDeg: number[] = new Array(12);
	for (let i = 0; i < 12; i += 1) {
		trackedCmdDeg[i] = (pose.cmdQRad[i] ?? 0) * RAD2DEG;
	}

	const t0 = performance.now();
	const obs = poseHistory.pushAndProject({
		observationTimeS: nowS,
		measuredDeg: lastMeasuredDeg,
		commandedDeg: trackedCmdDeg,
		velocityDegS: lastVelocityDegS,
		usableFlags: lastFeedbackUsable,
		orientationWxyz: currentImuQuatWxyz(),
		angularRateRadS: [
			lastImuSample[7] ?? 0,
			lastImuSample[8] ?? 0,
			lastImuSample[9] ?? 0,
		],
		accelerationMS2: [
			lastImuSample[4] ?? 0,
			lastImuSample[5] ?? 0,
			lastImuSample[6] ?? 9.81,
		],
		goalJointDeg: goalDeg,
		goalFootNorm: goalFoot,
		legSupport: support,
		speedScale,
		previousAction: pose.prevAction,
	});
	const rawAction = posePolicy.predictAction(obs);
	const stepped = poseManifold.stepHostCommand(
		rawAction,
		pose.cmdQRad,
		speedScale,
	);
	lastNeuralInferMs = Math.round((performance.now() - t0) * 100) / 100;

	pose.cmdQRad = stepped.nextQRad;
	pose.prevAction = stepped.appliedAction;
	pose.sampleIdx += 1;

	sendStandaloneFirmwareCommand(
		{
			t: "walk_target",
			walk: pose.walkSeq,
			sample: pose.sampleIdx,
			geometry: poseManifold.geometryId,
			feet_mm: stepped.feetMm,
		},
		nowUs,
	);
	hostSamplesSent += 1;

	// Settling check for pose_goal (matches neural_pose/executor.py)
	if (seg.kind === "pose_goal") {
		const cmdDegNow: number[] = new Array(12);
		let maxCmdStep = 0;
		for (let i = 0; i < 12; i += 1) {
			const v = (pose.cmdQRad[i] ?? 0) * RAD2DEG;
			cmdDegNow[i] = v;
			if (pose.prevCmdDeg) {
				maxCmdStep = Math.max(
					maxCmdStep,
					Math.abs(v - (pose.prevCmdDeg[i] ?? v)),
				);
			}
		}
		pose.prevCmdDeg = cmdDegNow;

		const isTerminalMotion = !pose.motion.segments
			.slice(pose.segIndex + 1)
			.some((s) => s.kind !== "face");
		const tightTerminal =
			seg.isStand ||
			(isTerminalMotion && seg.legSupport.every((v) => v >= 0.5));
		let maxLiveDelta = 0;
		for (let i = 0; i < 12; i += 1) {
			maxLiveDelta = Math.max(
				maxLiveDelta,
				Math.abs((seg.goalDeg[i] ?? 0) - (pose.liveStartDeg[i] ?? 0)),
			);
		}
		const largeExcursion = seg.fromNonstanding || maxLiveDelta > 45;
		const hostSlew =
			545.4545454545455 * Math.max(0.25, Math.min(1, speedScale));
		const minSettleS = Math.max(
			largeExcursion
				? seg.isStand
					? 0.85
					: tightTerminal
						? 0.5
						: 0.45
				: seg.isStand
					? 0.35
					: tightTerminal
						? 0.24
						: 0.18,
			maxLiveDelta / hostSlew + (seg.isStand && largeExcursion ? 0.24 : 0.08),
		);
		const maxStanceTol = seg.isStand ? 5.0 : tightTerminal ? 6.0 : 13.0;
		const meanTol = seg.isStand ? 2.5 : tightTerminal ? 3.5 : 7.0;
		const maxStepTol = tightTerminal ? 0.6 : 1.2;
		const reqSettled = seg.isStand ? 4 : tightTerminal ? 3 : 2;
		const maxBudgetS = tightTerminal
			? Math.max(seg.durationS + 2.2, 4.4)
			: seg.durationS;

		const currUsable = new Map<number, number>();
		let usableCount = 0;
		let sumErr = 0;
		let maxFreeErr = 0;
		let maxStanceErr = 0;
		let maxMeasStep = 0;
		let maxCmdMeasGap = 0;
		for (let i = 0; i < 12; i += 1) {
			if (!lastFeedbackUsable[i]) {
				continue;
			}
			const val = lastMeasuredDeg[i] ?? 0;
			currUsable.set(i, val);
			const err = Math.abs(val - (seg.goalDeg[i] ?? 0));
			usableCount += 1;
			sumErr += err;
			if ((seg.legSupport[Math.floor(i / 3)] ?? 1) < 0.5) {
				maxFreeErr = Math.max(maxFreeErr, err);
			} else {
				maxStanceErr = Math.max(maxStanceErr, err);
			}
			const prevVal = pose.prevUsableDeg.get(i);
			if (prevVal !== undefined) {
				maxMeasStep = Math.max(maxMeasStep, Math.abs(val - prevVal));
			}
			maxCmdMeasGap = Math.max(
				maxCmdMeasGap,
				Math.abs((cmdDegNow[i] ?? 0) - val),
			);
		}
		const hadPrev = pose.prevUsableDeg.size > 0;
		pose.prevUsableDeg = currUsable;

		if (elapsed >= minSettleS && hadPrev && usableCount >= 6) {
			const gyroNorm = Math.hypot(
				lastImuSample[7] ?? 0,
				lastImuSample[8] ?? 0,
				lastImuSample[9] ?? 0,
			);
			const meanErr = sumErr / usableCount;
			const cmdSteadyOk =
				!tightTerminal || (maxCmdStep <= maxStepTol && maxCmdMeasGap <= 4.5);
			if (
				maxFreeErr <= 5.5 &&
				maxStanceErr <= maxStanceTol &&
				meanErr <= meanTol &&
				maxMeasStep <= maxStepTol &&
				cmdSteadyOk &&
				gyroNorm <= 0.44
			) {
				pose.settledFrames += 1;
				if (pose.settledFrames >= reqSettled) {
					segComplete = true;
				}
			} else {
				pose.settledFrames = 0;
			}
		} else {
			pose.settledFrames = 0;
		}

		if (!segComplete && elapsed >= seg.durationS) {
			let maxCmdGoalErr = 0;
			for (let i = 0; i < 12; i += 1) {
				maxCmdGoalErr = Math.max(
					maxCmdGoalErr,
					Math.abs((cmdDegNow[i] ?? 0) - (seg.goalDeg[i] ?? 0)),
				);
			}
			const midStepActive = tightTerminal && maxCmdGoalErr > 5.5;
			const effectiveBudget = midStepActive ? maxBudgetS + 2.6 : maxBudgetS;
			if (
				!tightTerminal ||
				(maxStanceErr <= 5.5 && maxCmdMeasGap <= 4.5 && maxCmdGoalErr <= 5.5) ||
				elapsed >= effectiveBudget
			) {
				segComplete = true;
			}
		}

		if (segComplete) {
			pose.holdGoalDeg = [...seg.goalDeg];
			pose.holdGoalFoot = [...seg.goalFootNorm];
			pose.holdSupport = [...seg.legSupport];
		}
	}

	if (segComplete) {
		pose.segIndex += 1;
		pose.segStartedS = nowS;
		pose.settledFrames = 0;
		pose.prevCmdDeg = null;
		pose.prevUsableDeg.clear();
		pose.liveStartDeg = currentUsableJointAnglesDeg();
		advancePoseFaceSegments(pose, nowUs);
		if (pose.segIndex >= pose.motion.segments.length) {
			sendStandaloneFirmwareCommand({ t: "stop" }, nowUs);
			activePose = undefined;
			activeNeuralRole = "idle";
		}
	}
}

function resetVirtualBodyToReference(): void {
	if (!fw || !config || !simStatePtr) {
		return;
	}
	const refPtr = writeDoubles(config.referenceJointDeg);
	const bodySettings = new Float64Array([
		config.jointSpeedDegS,
		1.0, // motion_rate
		config.balanceEnabled ? 1 : 0,
		config.headingFeedbackEnabled ? 1 : 0,
		config.balanceTuning[0],
		config.balanceTuning[1],
		config.balanceTuning[2],
		config.balanceTuning[3],
		0, // idle_rest_seconds (disabled in interactive simulator)
		config.pwmOscillatorHz,
		config.pwmFrequencyHz,
	]);
	const bsPtr = writeDoubles(bodySettings);
	const resetOk = fw._virtual_body_reset(
		simStatePtr,
		refPtr,
		bsPtr,
		nowDeviceUs(),
	);
	fw._free(refPtr);
	fw._free(bsPtr);
	if (!resetOk) {
		throw new Error("virtual_body_reset() failed.");
	}
	fw._virtual_body_set_full_parity(1);
}

function resetRobotPose(spawnMj?: readonly [number, number, number]): void {
	if (!mujoco || !mjModel || !mjData) {
		return;
	}
	const spawn = spawnMj ?? currentSpawnMj;
	if (activeRobotModel === "v1") {
		if (!v1Config) {
			return;
		}
		pinnedJoints.clear();
		activeWrench.fill(0);
		wrenchUntilMs = 0;
		v1ActiveRole = "idle";
		v1ActiveMotionId = undefined;
		v1Twist = [0, 0, 0];
		v1PhaseRad = 0;
		v1NativePhase01 = 0;
		v1NativeWalkCmd = [0, 0, 0, 1];
		v1PrevGaitAction.fill(0);
		v1PrevPoseAction.fill(0);
		v1TargetDeg.fill(0);
		v1GoalDeg.fill(0);
		v1GoalSupport = [1, 1, 1, 1];
		v1GaitHistory.reset();
		v1PoseHistory.reset();
		v1Armed = true;
		mjData.qvel.fill(0);
		mjData.xfrc_applied.fill(0);
		for (
			let i = 0;
			i < v1Config.initQpos.length && i < mjData.qpos.length;
			i += 1
		) {
			mjData.qpos[i] = v1Config.initQpos[i] ?? 0;
		}
		mjData.qpos[0] = spawn[0];
		mjData.qpos[1] = spawn[1];
		mjData.qpos[2] = Math.max(spawn[2], v1Config.standingRootHeightM);
		mjData.qpos[3] = 1;
		mjData.qpos[4] = 0;
		mjData.qpos[5] = 0;
		mjData.qpos[6] = 0;
		for (let j = 0; j < 8; j += 1) {
			const refDeg = v1Config.referenceJointDeg[j] ?? 0;
			mjData.ctrl[j] = refDeg * DEG2RAD;
			v1TargetDeg[j] = refDeg;
		}
		mujoco.mj_forward(mjModel, mjData);
		return;
	}
	if (activeRobotModel === "v3") {
		if (!v3Config) {
			return;
		}
		pinnedJoints.clear();
		activeWrench.fill(0);
		wrenchUntilMs = 0;
		v3ActiveRole = "idle";
		v3ActiveMotionId = undefined;
		v3Twist = [0, 0, 0];
		v3PhaseRad = 0;
		v3NativePhase01 = 0;
		v3NativeWalkCmd = [0, 0, 0];
		v3PrevGaitAction.fill(0);
		v3PrevPoseAction.fill(0);
		v3TargetDeg.fill(0);
		v3GoalDeg.fill(0);
		v3GoalSupport = [1, 1, 1, 1];
		v3GaitHistory.reset();
		v3PoseHistory.reset();
		v3Armed = true;
		mjData.qvel.fill(0);
		mjData.xfrc_applied.fill(0);
		for (
			let i = 0;
			i < v3Config.initQpos.length && i < mjData.qpos.length;
			i += 1
		) {
			mjData.qpos[i] = v3Config.initQpos[i] ?? 0;
		}
		mjData.qpos[0] = spawn[0];
		mjData.qpos[1] = spawn[1];
		mjData.qpos[2] = Math.max(spawn[2], v3Config.standingRootHeightM);
		mjData.qpos[3] = 1;
		mjData.qpos[4] = 0;
		mjData.qpos[5] = 0;
		mjData.qpos[6] = 0;
		for (let j = 0; j < 12; j += 1) {
			const refDeg = v3Config.referenceJointDeg[j] ?? 0;
			const refRad = refDeg * DEG2RAD;
			mjData.ctrl[j] = refRad;
			v3TargetDeg[j] = refDeg;
			v3QTrueBuf[j] = refRad;
		}
		v3Sensors.reset(v3QTrueBuf);
		resetV3DelayQueue(v3QTrueBuf);
		mujoco.mj_forward(mjModel, mjData);
		return;
	}
	if (!config) {
		return;
	}
	clearNeuralControllers();
	pinnedJoints.clear();
	activeWrench.fill(0);
	wrenchUntilMs = 0;
	actuatorQueue.length = 0;
	mjData.qvel.fill(0);
	mjData.xfrc_applied.fill(0);
	for (
		let i = 0;
		i < config.initQpos.length && i < mjData.qpos.length;
		i += 1
	) {
		mjData.qpos[i] = config.initQpos[i] ?? 0;
	}
	mjData.qpos[0] = spawn[0];
	mjData.qpos[1] = spawn[1];
	mjData.qpos[2] = Math.max(spawn[2], config.initQpos[2] ?? 0.066);
	mjData.qpos[3] = 1;
	mjData.qpos[4] = 0;
	mjData.qpos[5] = 0;
	mjData.qpos[6] = 0;
	for (let j = 0; j < 12; j += 1) {
		const refDeg = config.referenceJointDeg[j] ?? 0;
		mjData.ctrl[j] = refDeg * DEG2RAD;
		lastTargetDeg[j] = refDeg;
		lastLogicalDeg[j] = refDeg;
		lastMeasuredDeg[j] = refDeg;
	}
	mujoco.mj_forward(mjModel, mjData);
	// Re-converge the LSM6DS3 IMU attitude estimator to level upright so a prior
	// knockover/roll on another level never causes balance to flip the robot on spawn.
	if (fw && simStatePtr) {
		const ai = accelPtr >> 3;
		const gi = gyroPtr >> 3;
		const startS = mjData.time + simTimeOffsetS;
		for (let k = 1; k <= 832; k += 1) {
			const tS = startS + k / 208;
			const tUs = (tS + config.imuPrehistoryS) * 1_000_000;
			fw.HEAPF64[ai] = 0;
			fw.HEAPF64[ai + 1] = 0;
			fw.HEAPF64[ai + 2] = 9.80665;
			fw.HEAPF64[gi] = 0;
			fw.HEAPF64[gi + 1] = 0;
			fw.HEAPF64[gi + 2] = 0;
			fw._simulation_imu(simStatePtr, tUs, accelPtr, gyroPtr, imuOutPtr);
		}
		simTimeOffsetS += 832 / 208;
		const oi = imuOutPtr >> 3;
		for (let i = 0; i < 14; i += 1) {
			lastImuSample[i] = fw.HEAPF64[oi + i] ?? 0;
		}
	}
	nextImuS = mjData.time + simTimeOffsetS;
	nextFeedbackS = mjData.time + simTimeOffsetS;
	// In standalone mode, cleanly reset virtual_body.c servo targets & balance state
	// to match referenceJointDeg so prior Sit/Wave/Lay postures never kick on spawn.
	if (!emitProtocolTx && fw && activeConnectionId > 0n) {
		resetVirtualBodyToReference();
		startFirmwareSession(standaloneEpoch);
	}
}

function angleToRawAdc(jointIdx: number, angleDeg: number): number {
	if (!config) {
		return 2048;
	}
	const m = config.mapping[jointIdx];
	const curve = config.rawCurve[jointIdx];
	if (!m || !curve || curve.length < 2) {
		return 2048;
	}
	const invert = (m[1] ?? 0) !== 0;
	const homeUs = m[2] ?? 1500;
	const homeCd = m[3] ?? 0;
	const usPerDeg = m[4] ?? 10;
	const pulse =
		homeUs + (invert ? -1 : 1) * (angleDeg - homeCd / 100) * usPerDeg;
	// Linear interpolation over captured calibration curve (pulse_us -> raw ADC)
	const p0 = curve[0] ?? [0, 500];
	const pLast = curve[curve.length - 1] ?? [4095, 2500];
	if (pulse <= p0[1]) {
		const p1 = curve[1] ?? pLast;
		const span = Math.max(1e-6, p1[1] - p0[1]);
		return p0[0] + ((pulse - p0[1]) / span) * (p1[0] - p0[0]);
	}
	for (let k = 0; k < curve.length - 1; k += 1) {
		const a = curve[k] ?? p0;
		const b = curve[k + 1] ?? pLast;
		if (pulse <= b[1] || k === curve.length - 2) {
			const span = Math.max(1e-6, b[1] - a[1]);
			return a[0] + ((pulse - a[1]) / span) * (b[0] - a[0]);
		}
	}
	return pLast[0];
}

function sampleSensorsSubstep(): void {
	if (!fw || !mjData || !config) {
		return;
	}
	const nowS = mjData.time + simTimeOffsetS;
	const nowUsNum = (nowS + config.imuPrehistoryS) * 1_000_000;

	// 208 Hz LSM6DS3 IMU
	if (nowS + 1e-10 >= nextImuS) {
		const ga = config.gyroSensorAdr;
		const aa = config.accelSensorAdr;
		const heap64 = fw.HEAPF64;
		const ai = accelPtr >> 3;
		const gi = gyroPtr >> 3;
		heap64[ai] =
			(mjData.sensordata[aa] ?? 0) + gaussNoise(config.imuAccelNoiseStd);
		heap64[ai + 1] =
			(mjData.sensordata[aa + 1] ?? 0) + gaussNoise(config.imuAccelNoiseStd);
		heap64[ai + 2] =
			(mjData.sensordata[aa + 2] ?? 0) + gaussNoise(config.imuAccelNoiseStd);
		heap64[gi] =
			(mjData.sensordata[ga] ?? 0) + gaussNoise(config.imuGyroNoiseStd);
		heap64[gi + 1] =
			(mjData.sensordata[ga + 1] ?? 0) + gaussNoise(config.imuGyroNoiseStd);
		heap64[gi + 2] =
			(mjData.sensordata[ga + 2] ?? 0) + gaussNoise(config.imuGyroNoiseStd);
		fw._simulation_imu(simStatePtr, nowUsNum, accelPtr, gyroPtr, imuOutPtr);
		const oi = imuOutPtr >> 3;
		for (let i = 0; i < 14; i += 1) {
			lastImuSample[i] = fw.HEAPF64[oi + i] ?? 0;
		}
		nextImuS += 1 / config.imuHz;
	}

	// 50 Hz 4th-wire servo feedback ADC + stall/I2t check
	if (nowS + 1e-10 >= nextFeedbackS) {
		const heap64 = fw.HEAPF64;
		const ri = rawPtr >> 3;
		const ti = targetPtr >> 3;
		const tsi = tsPtr >> 3;
		for (let j = 0; j < 12; j += 1) {
			const qIdx = config.qadr[j] ?? 0;
			const angleDeg = (mjData.qpos[qIdx] ?? 0) * RAD2DEG;
			const raw = Math.round(
				Math.max(
					0,
					Math.min(
						4095,
						angleToRawAdc(j, angleDeg) + gaussNoise(config.feedbackNoiseRawStd),
					),
				),
			);
			heap64[ri + j] = raw;
			heap64[ti + j] = lastTargetDeg[j] ?? 0;
			heap64[tsi + j] = nowUsNum;
		}
		lastJammedMask = fw._simulation_feedback(
			simStatePtr,
			rawPtr,
			targetPtr,
			tsPtr,
			fbOutPtr,
		);
		const foi = fbOutPtr >> 3;
		for (let j = 0; j < 12; j += 1) {
			lastMeasuredDeg[j] = fw.HEAPF64[foi + j] ?? 0;
			lastVelocityDegS[j] = fw.HEAPF64[foi + 12 + j] ?? 0;
			lastFeedbackUsable[j] = (fw.HEAPF64[foi + 24 + j] ?? 0) > 0.5;
		}
		nextFeedbackS += 1 / config.controlHz;
	}
}

function drainFirmwareEvents(): string[] {
	if (!fw) {
		return [];
	}
	const n = fw._virtual_body_events(textBufPtr, TEXT_BUF_CAP);
	if (n <= 0) {
		return [];
	}
	const raw = fw.UTF8ToString(textBufPtr, n);
	try {
		const arr = JSON.parse(raw) as unknown[];
		if (!Array.isArray(arr)) {
			return [];
		}
		return arr.map((item) =>
			typeof item === "string" ? item : JSON.stringify(item),
		);
	} catch {
		return [];
	}
}

function emitExternalProtocolTelemetry(
	nowUs: bigint,
	nowWallMs: number,
	accelAdr: number,
	gyroAdr: number,
): void {
	if (!emitProtocolTx || !fw || !mjData) {
		return;
	}
	const heap64 = fw.HEAPF64;
	const ai = accelPtr >> 3;
	const gi = gyroPtr >> 3;
	heap64[ai] = mjData.sensordata[accelAdr] ?? 0;
	heap64[ai + 1] = mjData.sensordata[accelAdr + 1] ?? 0;
	heap64[ai + 2] = mjData.sensordata[accelAdr + 2] ?? 9.81;
	heap64[gi] = mjData.sensordata[gyroAdr] ?? 0;
	heap64[gi + 1] = mjData.sensordata[gyroAdr + 1] ?? 0;
	heap64[gi + 2] = mjData.sensordata[gyroAdr + 2] ?? 0;
	fw._simulation_imu(simStatePtr, Number(nowUs), accelPtr, gyroPtr, imuOutPtr);
	fw._virtual_body_tick(nowUs, tickOutPtr);
	drainMediaActions();

	const txMessages = drainFirmwareEvents();
	const telemLen = fw._virtual_body_telemetry(nowUs, textBufPtr, TEXT_BUF_CAP);
	if (telemLen > 0) {
		txMessages.push(fw.UTF8ToString(textBufPtr, telemLen));
	}
	if (nowWallMs - lastStatusMs >= 1000) {
		lastStatusMs = nowWallMs;
		const stLen = fw._virtual_body_status(nowUs, textBufPtr, TEXT_BUF_CAP);
		if (stLen > 0) {
			txMessages.push(fw.UTF8ToString(textBufPtr, stLen));
		}
		const fhLen = fw._virtual_body_feedback_health(
			nowUs,
			textBufPtr,
			TEXT_BUF_CAP,
		);
		if (fhLen > 0) {
			txMessages.push(fw.UTF8ToString(textBufPtr, fhLen));
		}
	}
	if (nowWallMs - lastHeartbeatMs >= 1000) {
		lastHeartbeatMs = nowWallMs;
		const hbLen = fw._virtual_body_heartbeat(
			nowUs,
			0,
			textBufPtr,
			TEXT_BUF_CAP,
		);
		if (hbLen > 0) {
			txMessages.push(fw.UTF8ToString(textBufPtr, hbLen));
		}
	}
	if (txMessages.length > 0) {
		post({ type: "protocol-tx", messages: txMessages });
	}
}

function drainMediaActions(): void {
	if (!fw) {
		return;
	}
	const n = fw._virtual_body_media_actions(textBufPtr, TEXT_BUF_CAP);
	if (n <= 0) {
		return;
	}
	const raw = fw.UTF8ToString(textBufPtr, n);
	try {
		const arr = JSON.parse(raw) as Record<string, unknown>[];
		if (!Array.isArray(arr)) {
			return;
		}
		for (const action of arr) {
			if (action.kind === "camera") {
				cameraEnabled = Boolean(action.enabled);
				cameraFps = cameraEnabled ? Number(action.fps ?? 5) : 0;
				if (typeof action.res === "string") {
					cameraRes = action.res;
				}
				if (typeof action.snapshot_res === "string") {
					cameraSnapshotRes = action.snapshot_res;
				}
			}
			post({ type: "media-action", action });
		}
	} catch {
		// ignore malformed action json
	}
}

function applyExternalInteractionsSubstep(nowWallMs: number): void {
	if (!mjData || !config) {
		return;
	}
	const base = config.torsoBodyId * 6;
	if (nowWallMs <= wrenchUntilMs) {
		for (let i = 0; i < 6; i += 1) {
			mjData.xfrc_applied[base + i] = activeWrench[i] ?? 0;
		}
	} else {
		for (let i = 0; i < 6; i += 1) {
			mjData.xfrc_applied[base + i] = 0;
		}
	}

	if (pinnedJoints.size > 0) {
		for (const [j, lockedRad] of pinnedJoints) {
			const qIdx = config.qadr[j];
			const vIdx = config.vadr[j];
			if (qIdx !== undefined) {
				mjData.qpos[qIdx] = lockedRad;
			}
			if (vIdx !== undefined) {
				mjData.qvel[vIdx] = 0;
			}
		}
	}
}

function accumulateFootContacts(
	footGeomIds: readonly number[],
	out: [boolean, boolean, boolean, boolean],
): void {
	if (!mjData) {
		return;
	}
	const ncon = mjData.ncon;
	if (ncon <= 0) {
		return;
	}
	// Embind allocates a C++ wrapper on the WASM heap for both `mjData.contact`
	// and each `contactList.get(c)`. Always delete them immediately so 500 Hz
	// stepping never leaks WASM memory up to the 2 GB heap ceiling.
	const contactList = mjData.contact;
	try {
		for (let c = 0; c < ncon; c += 1) {
			const contact = contactList.get(c);
			if (!contact) {
				continue;
			}
			try {
				const g1 = contact.geom1;
				const g2 = contact.geom2;
				for (let f = 0; f < 4; f += 1) {
					const fg = (footGeomIds[f] ?? -1) + extraWorldGeomCount;
					if (g1 === fg || g2 === fg) {
						out[f] = true;
					}
				}
			} finally {
				contact.delete();
			}
		}
	} finally {
		contactList.delete();
	}
}

function computeFootContacts(): [boolean, boolean, boolean, boolean] {
	const result: [boolean, boolean, boolean, boolean] = [
		false,
		false,
		false,
		false,
	];
	if (config) {
		accumulateFootContacts(config.footGeomIds, result);
	}
	return result;
}

function hashRgba(bytes: Uint8Array): number {
	// Fast FNV-1a stride-4 hash over 320x170 RGBA to skip unchanged face uploads
	let h = 2166136261;
	for (let i = 0; i < bytes.length; i += 16) {
		h ^= bytes[i] ?? 0;
		h = Math.imul(h, 16777619);
		h ^= bytes[i + 1] ?? 0;
		h = Math.imul(h, 16777619);
		h ^= bytes[i + 2] ?? 0;
		h = Math.imul(h, 16777619);
	}
	return h >>> 0;
}

function startOrUpdateV1NeuralWalk(
	forward: number,
	lateral: number,
	turn: number,
	speed: number,
): void {
	if (!v1GaitPolicy) {
		return;
	}
	const fwd = Math.max(-100, Math.min(100, forward));
	const lat = Math.max(-100, Math.min(100, lateral));
	const trn = Math.max(-100, Math.min(100, turn));
	const spd = Math.max(10, Math.min(200, speed)) / 100;
	const prof = v1GaitPolicy.manifest.defaultProfile;
	v1Twist = [
		spd * (fwd / 100) * prof.forwardMS,
		spd * (lat / 100) * prof.lateralMS,
		spd * (trn / 100) * prof.yawRadS,
	];
	v1Armed = true;
	v1ActiveMotionId = undefined;
	if (v1ActiveRole !== "gait") {
		v1GaitHistory.reset();
		v1PrevGaitAction.fill(0);
		v1PhaseRad = 0;
		v1ActiveRole = "gait";
	}
}

function startV1NeuralPoseMotion(motionId: string): void {
	if (!v1PosePolicy || !mjData) {
		return;
	}
	const lookupId = motionId === "neutral" ? "stand" : motionId;
	const spec =
		v1PosePolicy.manifest.motions.find((m) => m.id === lookupId) ??
		v1PosePolicy.manifest.motions[0];
	if (!spec) {
		return;
	}
	for (let j = 0; j < 8; j += 1) {
		v1GoalDeg[j] = spec.goalDeg[j] ?? 0;
	}
	v1GoalSupport = [
		spec.support[0] ?? 1,
		spec.support[1] ?? 1,
		spec.support[2] ?? 1,
		spec.support[3] ?? 1,
	];
	v1ActiveMotionId = spec.id;
	v1MotionStartS = mjData.time;
	v1Armed = true;
	v1Twist = [0, 0, 0];
	v1NativeWalkCmd = [0, 0, 0, 1];
	if (v1ActiveRole !== "pose") {
		v1PoseHistory.reset();
		const norm = v1PosePolicy.degToNorm(v1TargetDeg);
		for (let j = 0; j < 8; j += 1) {
			v1PrevPoseAction[j] = norm[j] ?? 0;
		}
		v1ActiveRole = "pose";
	}
	if (fw && spec.face) {
		sendStandaloneFirmwareCommand({
			t: "intent",
			name: "face",
			expr: spec.face,
			timeout_ms: 8000,
		});
	}
}

function stopV1Motion(detach: boolean): void {
	v1Twist = [0, 0, 0];
	v1NativeWalkCmd = [0, 0, 0, 1];
	v1ActiveMotionId = undefined;
	if (detach) {
		v1Armed = false;
		v1ActiveRole = "idle";
		return;
	}
	v1Armed = true;
	v1GoalDeg.fill(0);
	v1ActiveRole = "native";
}

function stepV1ControlFrame(): void {
	if (!mujoco || !mjModel || !mjData || !v1Config) {
		return;
	}
	const tStart = performance.now();
	const nowWallMs = tStart;
	const dtCtrl = 1 / v1Config.controlHz;

	// Read current 50 Hz proprioceptive state
	const w0 = mjData.qpos[3] ?? 1;
	const x0 = mjData.qpos[4] ?? 0;
	const y0 = mjData.qpos[5] ?? 0;
	const z0 = mjData.qpos[6] ?? 0;
	const projGrav = projectedGravityFromWxyz([w0, x0, y0, z0]);
	const ga = v1Config.gyroSensorAdr;
	const aa = v1Config.accelSensorAdr;
	const gyroX = mjData.sensordata[ga] ?? 0;
	const gyroY = mjData.sensordata[ga + 1] ?? 0;
	const gyroZ = mjData.sensordata[ga + 2] ?? 0;
	const accX = mjData.sensordata[aa] ?? 0;
	const accY = mjData.sensordata[aa + 1] ?? 0;
	const accZ = mjData.sensordata[aa + 2] ?? 9.81;

	if (v1Armed) {
		if (v1ActiveRole === "gait" && v1GaitPolicy) {
			const inferStart = performance.now();
			for (let j = 0; j < 8; j += 1) {
				v1GaitFrameBuf[j] = mjData.qpos[v1Config.qadr[j] ?? 0] ?? 0;
				v1GaitFrameBuf[8 + j] = mjData.qvel[v1Config.vadr[j] ?? 0] ?? 0;
			}
			v1GaitFrameBuf[16] = gyroX;
			v1GaitFrameBuf[17] = gyroY;
			v1GaitFrameBuf[18] = gyroZ;
			v1GaitFrameBuf[19] = Math.max(-4, Math.min(4, accX / 9.81));
			v1GaitFrameBuf[20] = Math.max(-4, Math.min(4, accY / 9.81));
			v1GaitFrameBuf[21] = Math.max(-4, Math.min(4, accZ / 9.81));
			v1GaitFrameBuf[22] = projGrav[0];
			v1GaitFrameBuf[23] = projGrav[1];
			v1GaitFrameBuf[24] = projGrav[2];
			v1GaitFrameBuf[25] = v1Twist[0];
			v1GaitFrameBuf[26] = v1Twist[1];
			v1GaitFrameBuf[27] = v1Twist[2];
			for (let j = 0; j < 8; j += 1) {
				v1GaitFrameBuf[28 + j] = v1PrevGaitAction[j] ?? 0;
			}
			const moving =
				Math.hypot(v1Twist[0], v1Twist[1]) + 0.12 * Math.abs(v1Twist[2]) > 0.02;
			v1GaitFrameBuf[36] = moving ? Math.sin(v1PhaseRad) : 0;
			v1GaitFrameBuf[37] = moving ? Math.cos(v1PhaseRad) : 0;

			const obs = v1GaitHistory.push(v1GaitFrameBuf);
			const action = v1GaitPolicy.predictAction(obs);
			const targets = v1GaitPolicy.actionToJointDeg(action);
			for (let j = 0; j < 8; j += 1) {
				v1PrevGaitAction[j] = action[j] ?? 0;
				v1TargetDeg[j] = targets[j] ?? 0;
			}
			v1PhaseRad =
				(v1PhaseRad + 2 * Math.PI * v1GaitPolicy.manifest.gaitHz * dtCtrl) %
				(2 * Math.PI);
			v1LastInferMs = Math.round((performance.now() - inferStart) * 100) / 100;
			hostSamplesSent += 1;
		} else if (v1ActiveRole === "pose" && v1PosePolicy) {
			const inferStart = performance.now();
			const goalDeg = Array.from(v1GoalDeg);
			const elapsed = Math.max(0, mjData.time - v1MotionStartS);
			if (
				(v1ActiveMotionId === "wave_fr" || v1ActiveMotionId === "wave_fl") &&
				elapsed > 0.35
			) {
				const hipIdx = v1ActiveMotionId === "wave_fr" ? 0 : 2;
				const wave = 12 * Math.sin(2 * Math.PI * 1.6 * (elapsed - 0.35));
				goalDeg[hipIdx] = Math.max(
					-45,
					Math.min(45, (goalDeg[hipIdx] ?? 0) + wave),
				);
			}
			const goalNorm = v1PosePolicy.degToNorm(goalDeg);
			for (let j = 0; j < 8; j += 1) {
				v1PoseFrameBuf[j] = mjData.qpos[v1Config.qadr[j] ?? 0] ?? 0;
				v1PoseFrameBuf[8 + j] = mjData.qvel[v1Config.vadr[j] ?? 0] ?? 0;
				v1PoseFrameBuf[16 + j] = 1.0;
				v1PoseFrameBuf[33 + j] = goalNorm[j] ?? 0;
				v1PoseFrameBuf[46 + j] = v1PrevPoseAction[j] ?? 0;
			}
			v1PoseFrameBuf[24] = gyroX;
			v1PoseFrameBuf[25] = gyroY;
			v1PoseFrameBuf[26] = gyroZ;
			v1PoseFrameBuf[27] = accX / 9.81;
			v1PoseFrameBuf[28] = accY / 9.81;
			v1PoseFrameBuf[29] = accZ / 9.81;
			v1PoseFrameBuf[30] = projGrav[0];
			v1PoseFrameBuf[31] = projGrav[1];
			v1PoseFrameBuf[32] = projGrav[2];
			v1PoseFrameBuf[41] = v1GoalSupport[0];
			v1PoseFrameBuf[42] = v1GoalSupport[1];
			v1PoseFrameBuf[43] = v1GoalSupport[2];
			v1PoseFrameBuf[44] = v1GoalSupport[3];
			v1PoseFrameBuf[45] = 0.75;

			const obs = v1PoseHistory.push(v1PoseFrameBuf);
			const action = v1PosePolicy.predictAction(obs);
			const targets = v1PosePolicy.normToDeg(action);
			for (let j = 0; j < 8; j += 1) {
				v1PrevPoseAction[j] = action[j] ?? 0;
				v1TargetDeg[j] = targets[j] ?? 0;
			}
			v1LastInferMs = Math.round((performance.now() - inferStart) * 100) / 100;
			hostSamplesSent += 1;
		} else if (v1ActiveRole === "native") {
			const [vx, vy, wz, stride] = v1NativeWalkCmd;
			if (Math.hypot(vx, vy) + Math.abs(wz) > 0.04) {
				v1NativePhase01 = (v1NativePhase01 + 2.2 * dtCtrl) % 1;
				const targets = sampleV1NativeWalkDeg(
					v1NativePhase01,
					vx,
					vy,
					wz,
					stride,
				);
				for (let j = 0; j < 8; j += 1) {
					v1TargetDeg[j] = targets[j] ?? 0;
				}
			} else {
				const maxDelta = 3.6; // ~180 deg/s smooth transition
				let settled = true;
				for (let j = 0; j < 8; j += 1) {
					const cur = v1TargetDeg[j] ?? 0;
					const dst = v1GoalDeg[j] ?? 0;
					const diff = dst - cur;
					if (Math.abs(diff) > maxDelta) {
						v1TargetDeg[j] = cur + Math.sign(diff) * maxDelta;
						settled = false;
					} else {
						v1TargetDeg[j] = dst;
					}
				}
				if (settled && !v1ActiveMotionId) {
					v1ActiveRole = "idle";
				}
			}
		}
	}

	const substeps = Math.max(
		1,
		Math.round(v1Config.physicsHz / v1Config.controlHz),
	);
	const footContacts: [boolean, boolean, boolean, boolean] = [
		false,
		false,
		false,
		false,
	];
	const stallTorque = 0.18;
	const maxSpeed = 10.47;
	const en = v1Armed ? 1 : 0;
	const torsoBase = v1Config.torsoBodyId * 6;

	for (let s = 0; s < substeps; s += 1) {
		for (let j = 0; j < 8; j += 1) {
			mjData.ctrl[j] = (v1TargetDeg[j] ?? 0) * DEG2RAD;
			const vel = mjData.qvel[v1Config.vadr[j] ?? 0] ?? 0;
			const lower =
				-stallTorque * Math.max(0, Math.min(1, 1 + vel / maxSpeed)) * en;
			const upper =
				stallTorque * Math.max(0, Math.min(1, 1 - vel / maxSpeed)) * en;
			mjModel.actuator_forcerange[j * 2] = lower;
			mjModel.actuator_forcerange[j * 2 + 1] = upper;
		}
		if (nowWallMs <= wrenchUntilMs) {
			for (let i = 0; i < 6; i += 1) {
				mjData.xfrc_applied[torsoBase + i] = activeWrench[i] ?? 0;
			}
		} else {
			for (let i = 0; i < 6; i += 1) {
				mjData.xfrc_applied[torsoBase + i] = 0;
			}
		}
		if (pinnedJoints.size > 0) {
			for (const [j, lockedRad] of pinnedJoints) {
				const qIdx = v1Config.qadr[j];
				const vIdx = v1Config.vadr[j];
				if (qIdx !== undefined) mjData.qpos[qIdx] = lockedRad;
				if (vIdx !== undefined) mjData.qvel[vIdx] = 0;
			}
		}
		mujoco.mj_step(mjModel, mjData);
		accumulateFootContacts(v1Config.footGeomIds, footContacts);
	}

	if (pinnedJoints.size > 0) {
		for (const [j, lockedRad] of pinnedJoints) {
			const qIdx = v1Config.qadr[j];
			const vIdx = v1Config.vadr[j];
			if (qIdx !== undefined) mjData.qpos[qIdx] = lockedRad;
			if (vIdx !== undefined) mjData.qvel[vIdx] = 0;
		}
		mujoco.mj_forward(mjModel, mjData);
	}

	// Render animated OLED face via existing firmware face engine at up to 20 Hz
	const nowUs = nowDeviceUs();
	emitExternalProtocolTelemetry(
		nowUs,
		nowWallMs,
		v1Config.accelSensorAdr,
		v1Config.gyroSensorAdr,
	);
	if (fw && nowWallMs - lastFaceRenderMs >= 50) {
		lastFaceRenderMs = nowWallMs;
		fw._virtual_body_set_media_state(
			mediaCameraReady ? 1 : 0,
			1,
			1,
			1,
			1,
			mediaCapturing ? 1 : 0,
			mediaTalking ? 1 : 0,
			mediaTalking ? 1 : 0,
			mediaMicRms,
			mediaMicPeak,
			batteryVoltage,
		);
		fw._virtual_body_tick(nowUs, tickOutPtr);
		const ok = fw._virtual_body_face_frame(
			nowUs / 1000n,
			mediaTalking ? 1 : 0,
			mediaCapturing ? 1 : 0,
			faceRgbaPtr,
			faceNamePtr,
			64,
			faceTokenPtr,
			96,
		);
		if (ok) {
			lastFaceName = fw.UTF8ToString(faceNamePtr, 64) || "default";
			lastFaceToken = fw.UTF8ToString(faceTokenPtr, 96) || "";
			const view = fw.HEAPU8.subarray(
				faceRgbaPtr,
				faceRgbaPtr + FACE_RGBA_BYTES,
			);
			const h = hashRgba(view);
			if (h !== lastFaceHash) {
				lastFaceHash = h;
				const copy = new Uint8Array(FACE_RGBA_BYTES);
				copy.set(view);
				post(
					{
						type: "face",
						width: SIM_FACE_WIDTH,
						height: SIM_FACE_HEIGHT,
						rgba: copy.buffer,
					},
					[copy.buffer],
				);
			}
		}
	}

	const w = mjData.qpos[3] ?? 1;
	const x = mjData.qpos[4] ?? 0;
	const y = mjData.qpos[5] ?? 0;
	const z = mjData.qpos[6] ?? 0;
	const rollDeg =
		Math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y)) * RAD2DEG;
	const pitchDeg =
		Math.asin(Math.max(-1, Math.min(1, 2 * (w * y - z * x)))) * RAD2DEG;
	const yawDeg =
		Math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)) * RAD2DEG;

	const jointsDeg: number[] = [];
	const commandedDeg: number[] = [];
	const measuredDeg: number[] = [];
	for (let j = 0; j < 8; j += 1) {
		const qDeg =
			Math.round((mjData.qpos[v1Config.qadr[j] ?? 0] ?? 0) * RAD2DEG * 100) /
			100;
		jointsDeg.push(qDeg);
		commandedDeg.push(Math.round((v1TargetDeg[j] ?? 0) * 100) / 100);
		measuredDeg.push(qDeg);
	}
	const stepMs = Math.round((performance.now() - tStart) * 100) / 100;

	const state: RobotTelemetryState = {
		simTimeS: Math.round(mjData.time * 1000) / 1000,
		stepMs,
		armed: v1Armed,
		enabledMask: v1Armed ? 0xff : 0,
		stalledMask: 0,
		pinnedJoints: [...pinnedJoints.keys()].sort((a, b) => a - b),
		rootPosMj: [
			Math.round((mjData.qpos[0] ?? 0) * 100000) / 100000,
			Math.round((mjData.qpos[1] ?? 0) * 100000) / 100000,
			Math.round((mjData.qpos[2] ?? 0) * 100000) / 100000,
		],
		rootQuatMjWxyz: [
			Math.round(w * 100000) / 100000,
			Math.round(x * 100000) / 100000,
			Math.round(y * 100000) / 100000,
			Math.round(z * 100000) / 100000,
		],
		jointsDeg,
		commandedDeg,
		measuredDeg,
		footContacts,
		imu: {
			rollDeg: Math.round(rollDeg * 10) / 10,
			pitchDeg: Math.round(pitchDeg * 10) / 10,
			yawDeg: Math.round(yawDeg * 10) / 10,
			accel: [
				Math.round((mjData.sensordata[aa] ?? 0) * 1000) / 1000,
				Math.round((mjData.sensordata[aa + 1] ?? 0) * 1000) / 1000,
				Math.round((mjData.sensordata[aa + 2] ?? 9.81) * 1000) / 1000,
			],
			gyro: [
				Math.round((mjData.sensordata[ga] ?? 0) * 1000) / 1000,
				Math.round((mjData.sensordata[ga + 1] ?? 0) * 1000) / 1000,
				Math.round((mjData.sensordata[ga + 2] ?? 0) * 1000) / 1000,
			],
		},
		face: {
			name: lastFaceName,
			token: lastFaceToken,
			talking: mediaTalking,
			listening: mediaCapturing,
		},
		camera: {
			enabled: cameraEnabled,
			fps: cameraFps,
			res: cameraRes,
			snapshotRes: cameraSnapshotRes,
		},
		batteryVoltage,
		recording: {
			active: recordingActive,
			label: recordingLabel,
			steps: recordingRows.length,
		},
		neural: {
			engine: engineMode,
			gaitModelId: v1GaitPolicy?.manifest.modelId ?? "v1-microduck-p4",
			poseModelId:
				v1PosePolicy?.manifest.modelId ??
				v1PoseManifest?.modelId ??
				"neural_pose_v1",
			activeRole: v1ActiveRole,
			activeMotionId: v1ActiveMotionId,
			activeTwist:
				v1ActiveRole === "gait"
					? [
							Math.round(v1Twist[0] * 1000) / 1000,
							Math.round(v1Twist[1] * 1000) / 1000,
							Math.round(v1Twist[2] * 1000) / 1000,
						]
					: undefined,
			lastInferMs: v1LastInferMs,
			hostSamplesSent,
			hostNakCount,
		},
	};

	if (recordingActive) {
		const rx = mjData.qpos[0] ?? 0;
		const ry = mjData.qpos[1] ?? 0;
		if (!recordingStartXy) {
			recordingStartXy = [rx, ry];
		}
		recordingLastXy = [rx, ry];
		recordingRows.push(
			JSON.stringify({
				step: recordingRows.length + 1,
				sim_time_s: state.simTimeS,
				device_us: Number(nowUs),
				root_pos_mj: state.rootPosMj,
				root_quat_wxyz: state.rootQuatMjWxyz,
				qpos_joints_deg: state.jointsDeg,
				commanded_deg: state.commandedDeg,
				measured_deg: state.measuredDeg,
				imu_accel_m_s2: state.imu.accel,
				imu_gyro_rad_s: state.imu.gyro,
				foot_contact: state.footContacts,
				stalled_mask: state.stalledMask,
				armed: state.armed,
				face_name: state.face.name,
			}),
		);
	}

	post({ type: "state", state });
}

function resetV3DelayQueue(seedRad: ArrayLike<number>): void {
	const delayLen = (v3GaitPolicy?.manifest.actuatorDelaySubsteps ?? 15) + 1;
	v3DelayQueue.length = 0;
	for (let k = 0; k < delayLen; k += 1) {
		const slot = new Float64Array(12);
		for (let j = 0; j < 12; j += 1) {
			slot[j] = seedRad[j] ?? 0;
		}
		v3DelayQueue.push(slot);
	}
}

function startOrUpdateV3NeuralWalk(
	forward: number,
	lateral: number,
	turn: number,
	speed: number,
): void {
	if (!v3GaitPolicy) {
		return;
	}
	const fwd = Math.max(-100, Math.min(100, forward));
	const lat = Math.max(-100, Math.min(100, lateral));
	const trn = Math.max(-100, Math.min(100, turn));
	const spd = Math.max(10, Math.min(200, speed)) / 100;
	const prof = v3GaitPolicy.manifest.defaultProfile;
	v3Twist = [
		spd * (fwd / 100) * prof.forwardMS,
		spd * (lat / 100) * prof.lateralMS,
		spd * (trn / 100) * prof.yawRadS,
	];
	v3Armed = true;
	v3ActiveMotionId = undefined;
	if (v3ActiveRole !== "gait") {
		v3GaitHistory.reset();
		v3PrevGaitAction.fill(0);
		v3PhaseRad = 0;
		for (let j = 0; j < 12; j += 1) {
			v3QTrueBuf[j] =
				mjData && v3Config
					? mjData.qpos[v3Config.qadr[j] ?? 0] ?? 0
					: (v3TargetDeg[j] ?? 0) * DEG2RAD;
		}
		v3Sensors.reset(v3QTrueBuf);
		const seedCtrl = new Float64Array(12);
		for (let j = 0; j < 12; j += 1) {
			seedCtrl[j] = (v3TargetDeg[j] ?? 0) * DEG2RAD;
		}
		resetV3DelayQueue(seedCtrl);
		v3ActiveRole = "gait";
	}
}

function startV3NeuralPoseMotion(motionId: string): void {
	if (!v3PosePolicy || !mjData) {
		return;
	}
	const lookupId = motionId === "neutral" ? "stand" : motionId;
	const spec =
		v3PosePolicy.manifest.motions.find((m) => m.id === lookupId) ??
		v3PosePolicy.manifest.motions[0];
	if (!spec) {
		return;
	}
	for (let j = 0; j < 12; j += 1) {
		v3GoalDeg[j] = spec.goalDeg[j] ?? 0;
	}
	v3GoalSupport = [
		spec.support[0] ?? 1,
		spec.support[1] ?? 1,
		spec.support[2] ?? 1,
		spec.support[3] ?? 1,
	];
	v3ActiveMotionId = spec.id;
	v3MotionStartS = mjData.time;
	v3Armed = true;
	v3Twist = [0, 0, 0];
	v3NativeWalkCmd = [0, 0, 0];
	if (v3ActiveRole !== "pose") {
		v3PoseHistory.reset();
		const norm = v3PosePolicy.degToNorm(v3TargetDeg);
		for (let j = 0; j < 12; j += 1) {
			v3PrevPoseAction[j] = norm[j] ?? 0;
		}
		v3ActiveRole = "pose";
	}
	if (fw && spec.face) {
		sendStandaloneFirmwareCommand({
			t: "intent",
			name: "face",
			expr: spec.face,
			timeout_ms: 8000,
		});
	}
}

function stopV3Motion(detach: boolean): void {
	v3Twist = [0, 0, 0];
	v3NativeWalkCmd = [0, 0, 0];
	v3ActiveMotionId = undefined;
	if (detach) {
		v3Armed = false;
		v3ActiveRole = "idle";
		return;
	}
	v3Armed = true;
	v3GoalDeg.fill(0);
	v3ActiveRole = "native";
}

function stepV3ControlFrame(): void {
	if (!mujoco || !mjModel || !mjData || !v3Config) {
		return;
	}
	const tStart = performance.now();
	const nowWallMs = tStart;
	const dtCtrl = 1 / v3Config.controlHz;

	const w0 = mjData.qpos[3] ?? 1;
	const x0 = mjData.qpos[4] ?? 0;
	const y0 = mjData.qpos[5] ?? 0;
	const z0 = mjData.qpos[6] ?? 0;
	const projGrav = projectedGravityFromWxyz([w0, x0, y0, z0]);
	const ga = v3Config.gyroSensorAdr;
	const aa = v3Config.accelSensorAdr;
	const gyroX = mjData.sensordata[ga] ?? 0;
	const gyroY = mjData.sensordata[ga + 1] ?? 0;
	const gyroZ = mjData.sensordata[ga + 2] ?? 0;
	const accX = mjData.sensordata[aa] ?? 0;
	const accY = mjData.sensordata[aa + 1] ?? 0;
	const accZ = mjData.sensordata[aa + 2] ?? 9.81;

	if (v3Armed) {
		if (v3ActiveRole === "gait" && v3GaitPolicy) {
			const inferStart = performance.now();
			for (let j = 0; j < 12; j += 1) {
				v3QTrueBuf[j] = mjData.qpos[v3Config.qadr[j] ?? 0] ?? 0;
			}
			const linVelB = bodyLinearVelocityFromWxyz(
				[w0, x0, y0, z0],
				[mjData.qvel[0] ?? 0, mjData.qvel[1] ?? 0, mjData.qvel[2] ?? 0],
			);
			const gyroBody: readonly [number, number, number] = [
				mjData.qvel[3] ?? gyroX,
				mjData.qvel[4] ?? gyroY,
				mjData.qvel[5] ?? gyroZ,
			];
			v3Sensors.update50Hz(v3QTrueBuf, gyroBody, linVelB, projGrav, dtCtrl);
			v3Sensors.writeFeatures(
				v3Twist,
				v3PrevGaitAction,
				v3PhaseRad,
				v3GaitFrameBuf,
			);

			const obs = v3GaitHistory.push(v3GaitFrameBuf);
			const action = v3GaitPolicy.predictAction(obs);
			const targets = v3GaitPolicy.actionToJointDeg(action);
			for (let j = 0; j < 12; j += 1) {
				v3PrevGaitAction[j] = action[j] ?? 0;
				v3TargetDeg[j] = targets[j] ?? 0;
			}
			const hz = v3GaitPolicy.computeGaitHz(v3Twist);
			const moving =
				Math.hypot(v3Twist[0], v3Twist[1]) + 0.18 * Math.abs(v3Twist[2]) > 0.02;
			if (moving || v3GaitPolicy.manifest.gaitHzMin === undefined) {
				v3PhaseRad = (v3PhaseRad + 2 * Math.PI * hz * dtCtrl) % (2 * Math.PI);
			}
			v3LastInferMs = Math.round((performance.now() - inferStart) * 100) / 100;
			hostSamplesSent += 1;
		} else if (v3ActiveRole === "pose" && v3PosePolicy) {
			const inferStart = performance.now();
			const goalDeg = Array.from(v3GoalDeg);
			const elapsed = Math.max(0, mjData.time - v3MotionStartS);
			if (
				(v3ActiveMotionId === "wave_fr" || v3ActiveMotionId === "wave_fl") &&
				elapsed > 0.35
			) {
				const shIdx = v3ActiveMotionId === "wave_fr" ? 9 : 6;
				const wave = 10 * Math.sin(2 * Math.PI * 1.5 * (elapsed - 0.35));
				goalDeg[shIdx] = Math.max(
					-30,
					Math.min(30, (goalDeg[shIdx] ?? 0) + wave),
				);
			}
			const goalNorm = v3PosePolicy.degToNorm(goalDeg);
			for (let j = 0; j < 12; j += 1) {
				v3PoseFrameBuf[j] = mjData.qpos[v3Config.qadr[j] ?? 0] ?? 0;
				v3PoseFrameBuf[12 + j] = (v3TargetDeg[j] ?? 0) * DEG2RAD;
				v3PoseFrameBuf[24 + j] = mjData.qvel[v3Config.vadr[j] ?? 0] ?? 0;
				v3PoseFrameBuf[36 + j] = 1.0;
				v3PoseFrameBuf[57 + j] = goalNorm[j] ?? 0;
				v3PoseFrameBuf[74 + j] = v3PrevPoseAction[j] ?? 0;
			}
			v3PoseFrameBuf[48] = gyroX;
			v3PoseFrameBuf[49] = gyroY;
			v3PoseFrameBuf[50] = gyroZ;
			v3PoseFrameBuf[51] = Math.max(-4, Math.min(4, accX / 9.81));
			v3PoseFrameBuf[52] = Math.max(-4, Math.min(4, accY / 9.81));
			v3PoseFrameBuf[53] = Math.max(-4, Math.min(4, accZ / 9.81));
			v3PoseFrameBuf[54] = projGrav[0];
			v3PoseFrameBuf[55] = projGrav[1];
			v3PoseFrameBuf[56] = projGrav[2];
			v3PoseFrameBuf[69] = v3GoalSupport[0];
			v3PoseFrameBuf[70] = v3GoalSupport[1];
			v3PoseFrameBuf[71] = v3GoalSupport[2];
			v3PoseFrameBuf[72] = v3GoalSupport[3];
			v3PoseFrameBuf[73] = 0.75;

			const obs = v3PoseHistory.push(v3PoseFrameBuf);
			const action = v3PosePolicy.predictAction(obs);
			const targets = v3PosePolicy.normToDeg(action);
			for (let j = 0; j < 12; j += 1) {
				v3PrevPoseAction[j] = action[j] ?? 0;
				v3TargetDeg[j] = targets[j] ?? 0;
			}
			v3LastInferMs = Math.round((performance.now() - inferStart) * 100) / 100;
			hostSamplesSent += 1;
		} else if (v3ActiveRole === "native") {
			const [vx, vy, wz] = v3NativeWalkCmd;
			if (Math.hypot(vx, vy) + 0.18 * Math.abs(wz) > 0.015) {
				v3NativePhase01 = (v3NativePhase01 + 2.0 * dtCtrl) % 1;
				const targets = sampleV3NativeWalkDeg(v3NativePhase01, vx, vy, wz);
				for (let j = 0; j < 12; j += 1) {
					v3TargetDeg[j] = targets[j] ?? 0;
				}
			} else {
				const maxDelta = 3.2; // ~160 deg/s smooth transition
				let settled = true;
				for (let j = 0; j < 12; j += 1) {
					const cur = v3TargetDeg[j] ?? 0;
					const dst = v3GoalDeg[j] ?? 0;
					const diff = dst - cur;
					if (Math.abs(diff) > maxDelta) {
						v3TargetDeg[j] = cur + Math.sign(diff) * maxDelta;
						settled = false;
					} else {
						v3TargetDeg[j] = dst;
					}
				}
				if (settled && !v3ActiveMotionId) {
					v3ActiveRole = "idle";
				}
			}
		}
	}

	const substeps = Math.max(
		1,
		Math.round(v3Config.physicsHz / v3Config.controlHz),
	);
	const footContacts: [boolean, boolean, boolean, boolean] = [
		false,
		false,
		false,
		false,
	];
	const stallTorque = v3Config.torqueNm;
	const maxSpeed = v3Config.motorNoLoadSpeedRadS;
	const en = v3Armed ? 1 : 0;
	const torsoBase = v3Config.torsoBodyId * 6;

	const useGaitDelay = v3ActiveRole === "gait" && v3DelayQueue.length > 1;
	for (let s = 0; s < substeps; s += 1) {
		let delayedCtrl: Float64Array | undefined;
		if (useGaitDelay) {
			const recycled = v3DelayQueue.shift();
			if (recycled) {
				delayedCtrl = v3DelayQueue[0] ?? recycled;
				for (let j = 0; j < 12; j += 1) {
					recycled[j] = (v3TargetDeg[j] ?? 0) * DEG2RAD;
				}
				v3DelayQueue.push(recycled);
			}
		}
		for (let j = 0; j < 12; j += 1) {
			mjData.ctrl[j] = delayedCtrl
				? delayedCtrl[j] ?? 0
				: (v3TargetDeg[j] ?? 0) * DEG2RAD;
			const vel = mjData.qvel[v3Config.vadr[j] ?? 0] ?? 0;
			const lower =
				-stallTorque * Math.max(0, Math.min(1, 1 + vel / maxSpeed)) * en;
			const upper =
				stallTorque * Math.max(0, Math.min(1, 1 - vel / maxSpeed)) * en;
			mjModel.actuator_forcerange[j * 2] = lower;
			mjModel.actuator_forcerange[j * 2 + 1] = upper;
		}
		if (nowWallMs <= wrenchUntilMs) {
			for (let i = 0; i < 6; i += 1) {
				mjData.xfrc_applied[torsoBase + i] = activeWrench[i] ?? 0;
			}
		} else {
			for (let i = 0; i < 6; i += 1) {
				mjData.xfrc_applied[torsoBase + i] = 0;
			}
		}
		if (pinnedJoints.size > 0) {
			for (const [j, lockedRad] of pinnedJoints) {
				const qIdx = v3Config.qadr[j];
				const vIdx = v3Config.vadr[j];
				if (qIdx !== undefined) mjData.qpos[qIdx] = lockedRad;
				if (vIdx !== undefined) mjData.qvel[vIdx] = 0;
			}
		}
		mujoco.mj_step(mjModel, mjData);
		accumulateFootContacts(v3Config.footGeomIds, footContacts);
	}

	if (pinnedJoints.size > 0) {
		for (const [j, lockedRad] of pinnedJoints) {
			const qIdx = v3Config.qadr[j];
			const vIdx = v3Config.vadr[j];
			if (qIdx !== undefined) mjData.qpos[qIdx] = lockedRad;
			if (vIdx !== undefined) mjData.qvel[vIdx] = 0;
		}
		mujoco.mj_forward(mjModel, mjData);
	}

	const nowUs = nowDeviceUs();
	emitExternalProtocolTelemetry(
		nowUs,
		nowWallMs,
		v3Config.accelSensorAdr,
		v3Config.gyroSensorAdr,
	);
	if (fw && nowWallMs - lastFaceRenderMs >= 50) {
		lastFaceRenderMs = nowWallMs;
		fw._virtual_body_set_media_state(
			mediaCameraReady ? 1 : 0,
			1,
			1,
			1,
			1,
			mediaCapturing ? 1 : 0,
			mediaTalking ? 1 : 0,
			mediaTalking ? 1 : 0,
			mediaMicRms,
			mediaMicPeak,
			batteryVoltage,
		);
		fw._virtual_body_tick(nowUs, tickOutPtr);
		const ok = fw._virtual_body_face_frame(
			nowUs / 1000n,
			mediaTalking ? 1 : 0,
			mediaCapturing ? 1 : 0,
			faceRgbaPtr,
			faceNamePtr,
			64,
			faceTokenPtr,
			96,
		);
		if (ok) {
			lastFaceName = fw.UTF8ToString(faceNamePtr, 64) || "default";
			lastFaceToken = fw.UTF8ToString(faceTokenPtr, 96) || "";
			const view = fw.HEAPU8.subarray(
				faceRgbaPtr,
				faceRgbaPtr + FACE_RGBA_BYTES,
			);
			const h = hashRgba(view);
			if (h !== lastFaceHash) {
				lastFaceHash = h;
				const copy = new Uint8Array(FACE_RGBA_BYTES);
				copy.set(view);
				post(
					{
						type: "face",
						width: SIM_FACE_WIDTH,
						height: SIM_FACE_HEIGHT,
						rgba: copy.buffer,
					},
					[copy.buffer],
				);
			}
		}
	}

	const w = mjData.qpos[3] ?? 1;
	const x = mjData.qpos[4] ?? 0;
	const y = mjData.qpos[5] ?? 0;
	const z = mjData.qpos[6] ?? 0;
	const rollDeg =
		Math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y)) * RAD2DEG;
	const pitchDeg =
		Math.asin(Math.max(-1, Math.min(1, 2 * (w * y - z * x)))) * RAD2DEG;
	const yawDeg =
		Math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)) * RAD2DEG;

	const jointsDeg: number[] = [];
	const commandedDeg: number[] = [];
	const measuredDeg: number[] = [];
	for (let j = 0; j < 12; j += 1) {
		const qDeg =
			Math.round((mjData.qpos[v3Config.qadr[j] ?? 0] ?? 0) * RAD2DEG * 100) /
			100;
		jointsDeg.push(qDeg);
		commandedDeg.push(Math.round((v3TargetDeg[j] ?? 0) * 100) / 100);
		measuredDeg.push(qDeg);
	}
	const stepMs = Math.round((performance.now() - tStart) * 100) / 100;

	const state: RobotTelemetryState = {
		simTimeS: Math.round(mjData.time * 1000) / 1000,
		stepMs,
		armed: v3Armed,
		enabledMask: v3Armed ? 0xfff : 0,
		stalledMask: 0,
		pinnedJoints: [...pinnedJoints.keys()].sort((a, b) => a - b),
		rootPosMj: [
			Math.round((mjData.qpos[0] ?? 0) * 100000) / 100000,
			Math.round((mjData.qpos[1] ?? 0) * 100000) / 100000,
			Math.round((mjData.qpos[2] ?? 0) * 100000) / 100000,
		],
		rootQuatMjWxyz: [
			Math.round(w * 100000) / 100000,
			Math.round(x * 100000) / 100000,
			Math.round(y * 100000) / 100000,
			Math.round(z * 100000) / 100000,
		],
		jointsDeg,
		commandedDeg,
		measuredDeg,
		footContacts,
		imu: {
			rollDeg: Math.round(rollDeg * 10) / 10,
			pitchDeg: Math.round(pitchDeg * 10) / 10,
			yawDeg: Math.round(yawDeg * 10) / 10,
			accel: [
				Math.round((mjData.sensordata[aa] ?? 0) * 1000) / 1000,
				Math.round((mjData.sensordata[aa + 1] ?? 0) * 1000) / 1000,
				Math.round((mjData.sensordata[aa + 2] ?? 9.81) * 1000) / 1000,
			],
			gyro: [
				Math.round((mjData.sensordata[ga] ?? 0) * 1000) / 1000,
				Math.round((mjData.sensordata[ga + 1] ?? 0) * 1000) / 1000,
				Math.round((mjData.sensordata[ga + 2] ?? 0) * 1000) / 1000,
			],
		},
		face: {
			name: lastFaceName,
			token: lastFaceToken,
			talking: mediaTalking,
			listening: mediaCapturing,
		},
		camera: {
			enabled: cameraEnabled,
			fps: cameraFps,
			res: cameraRes,
			snapshotRes: cameraSnapshotRes,
		},
		batteryVoltage,
		recording: {
			active: recordingActive,
			label: recordingLabel,
			steps: recordingRows.length,
		},
		neural: {
			engine: engineMode,
			gaitModelId: v3GaitPolicy?.manifest.modelId ?? "v3-microduck-p4",
			poseModelId:
				v3PosePolicy?.manifest.modelId ??
				v3PoseManifest?.modelId ??
				"neural_pose_v3",
			activeRole: v3ActiveRole,
			activeMotionId: v3ActiveMotionId,
			activeTwist:
				v3ActiveRole === "gait"
					? [
							Math.round(v3Twist[0] * 1000) / 1000,
							Math.round(v3Twist[1] * 1000) / 1000,
							Math.round(v3Twist[2] * 1000) / 1000,
						]
					: undefined,
			lastInferMs: v3LastInferMs,
			hostSamplesSent,
			hostNakCount,
		},
	};

	if (recordingActive) {
		const rx = mjData.qpos[0] ?? 0;
		const ry = mjData.qpos[1] ?? 0;
		if (!recordingStartXy) {
			recordingStartXy = [rx, ry];
		}
		recordingLastXy = [rx, ry];
		recordingRows.push(
			JSON.stringify({
				step: recordingRows.length + 1,
				sim_time_s: state.simTimeS,
				device_us: Number(nowUs),
				root_pos_mj: state.rootPosMj,
				root_quat_wxyz: state.rootQuatMjWxyz,
				qpos_joints_deg: state.jointsDeg,
				commanded_deg: state.commandedDeg,
				measured_deg: state.measuredDeg,
				imu_accel_m_s2: state.imu.accel,
				imu_gyro_rad_s: state.imu.gyro,
				foot_contact: state.footContacts,
				stalled_mask: state.stalledMask,
				armed: state.armed,
				face_name: state.face.name,
			}),
		);
	}

	post({ type: "state", state });
}

function stepControlFrame(): void {
	if (activeRobotModel === "v1") {
		stepV1ControlFrame();
		maybeEmitCameraStreamTick(performance.now());
		return;
	}
	if (activeRobotModel === "v3") {
		stepV3ControlFrame();
		maybeEmitCameraStreamTick(performance.now());
		return;
	}
	if (!mujoco || !mjModel || !mjData || !fw || !config) {
		return;
	}
	const tStart = performance.now();
	const nowWallMs = tStart;

	fw._virtual_body_set_media_state(
		mediaCameraReady ? 1 : 0,
		1,
		1,
		1,
		1,
		mediaCapturing ? 1 : 0,
		mediaTalking ? 1 : 0,
		mediaTalking ? 1 : 0,
		mediaMicRms,
		mediaMicPeak,
		batteryVoltage,
	);

	const substeps = Math.max(1, Math.round(config.physicsHz / config.controlHz));
	const txMessages: string[] = [];
	const footContacts: [boolean, boolean, boolean, boolean] = [
		false,
		false,
		false,
		false,
	];

	// Keep standalone virtual_body.c admission fresh in worker device time even if
	// the main thread stalls during WebGL shader compilation or tab backgrounding.
	if (!emitProtocolTx && activeConnectionId > 0n) {
		const pingNowUs = nowDeviceUs();
		if (pingNowUs - lastStandalonePingUs >= 1_000_000n) {
			lastStandalonePingUs = pingNowUs;
			const pingPtr = writeCString('{"t":"ping"}');
			fw._virtual_body_receive(
				pingPtr,
				activeConnectionId,
				pingNowUs,
				textBufPtr,
				TEXT_BUF_CAP,
			);
			fw._free(pingPtr);
		}
	}

	for (let s = 0; s < substeps; s += 1) {
		const nowUs = nowDeviceUs();
		fw._virtual_body_tick(nowUs, tickOutPtr);
		const ti = tickOutPtr >> 3;
		const physAnglesRad = new Float64Array(12);
		const channelEnabledMask = Math.trunc(fw.HEAPF64[ti + 24] ?? 0);
		let enabledMask = 0;
		for (let j = 0; j < 12; j += 1) {
			const m = config.mapping[j];
			const ch = Math.max(0, Math.min(11, Math.round(m?.[0] ?? j)));
			const sign = (m?.[1] ?? 0) !== 0 ? -1 : 1;
			const homeUs = m?.[2] ?? 1500;
			const homeCd = m?.[3] ?? 0;
			const usPerDeg = m?.[4] || 10;
			const logPulse = fw.HEAPF64[ti + ch] ?? homeUs;
			const physPulse = fw.HEAPF64[ti + 12 + ch] ?? logPulse;
			const logDeg = homeCd / 100 + (logPulse - homeUs) / (sign * usPerDeg);
			const physDeg = homeCd / 100 + (physPulse - homeUs) / (sign * usPerDeg);
			physAnglesRad[j] = physDeg * DEG2RAD;
			lastLogicalDeg[j] = logDeg;
			lastTargetDeg[j] = logDeg;
			if ((channelEnabledMask & (1 << ch)) !== 0) {
				enabledMask |= 1 << j;
			}
		}
		lastArmed = (fw.HEAPF64[ti + 26] ?? 0) > 0.5;
		lastEnabledMask = enabledMask;
		lastMotionSeq = Math.trunc(fw.HEAPF64[ti + 27] ?? 0);
		lastNominalSample = Math.trunc(fw.HEAPF64[ti + 28] ?? 0);

		const evs = drainFirmwareEvents();
		if (evs.length > 0) {
			txMessages.push(...evs);
		}

		// Actuator delay queue
		let appliedTarget: Float64Array<ArrayBufferLike> = physAnglesRad;
		if (config.actuatorDelayS > 0) {
			actuatorQueue.push({ t: mjData.time, q: physAnglesRad });
			const acquired = mjData.time - config.actuatorDelayS;
			while (
				actuatorQueue.length > 1 &&
				(actuatorQueue[1]?.t ?? 0) <= acquired + 1e-12
			) {
				actuatorQueue.shift();
			}
			appliedTarget = actuatorQueue[0]?.q ?? physAnglesRad;
		}

		// Apply targets and MG90S torque-speed envelope
		const stallTorque = config.torqueNm;
		const maxSpeed = config.motorNoLoadSpeedRadS;
		for (let j = 0; j < 12; j += 1) {
			mjData.ctrl[j] = appliedTarget[j] ?? 0;
			const en = (enabledMask & (1 << j)) !== 0 ? 1 : 0;
			const vel = mjData.qvel[config.vadr[j] ?? 0] ?? 0;
			const lower =
				-stallTorque * Math.max(0, Math.min(1, 1 + vel / maxSpeed)) * en;
			const upper =
				stallTorque * Math.max(0, Math.min(1, 1 - vel / maxSpeed)) * en;
			mjModel.actuator_forcerange[j * 2] = lower;
			mjModel.actuator_forcerange[j * 2 + 1] = upper;
		}

		applyExternalInteractionsSubstep(nowWallMs);
		mujoco.mj_step(mjModel, mjData);
		const subContacts = computeFootContacts();
		for (let f = 0; f < 4; f += 1) {
			if (subContacts[f]) {
				footContacts[f] = true;
			}
		}
		sampleSensorsSubstep();
	}

	if (pinnedJoints.size > 0) {
		for (const [j, lockedRad] of pinnedJoints) {
			const qIdx = config.qadr[j];
			const vIdx = config.vadr[j];
			if (qIdx !== undefined) {
				mjData.qpos[qIdx] = lockedRad;
			}
			if (vIdx !== undefined) {
				mjData.qvel[vIdx] = 0;
			}
		}
		mujoco.mj_forward(mjModel, mjData);
	}

	drainMediaActions();

	const nowUs = nowDeviceUs();

	// Drive active 50 Hz Standalone Neural Gait or Neural Pose stream into virtual_body.c
	if (!emitProtocolTx) {
		if (activeNeuralRole === "gait") {
			stepNeuralGaitTick(nowUs);
		} else if (activeNeuralRole === "pose") {
			stepNeuralPoseTick(nowUs);
		}
	}

	// Authentic P4 telemetry + 1 Hz status/heartbeat for external Body Control mode
	if (emitProtocolTx) {
		const telemLen = fw._virtual_body_telemetry(
			nowUs,
			textBufPtr,
			TEXT_BUF_CAP,
		);
		if (telemLen > 0) {
			txMessages.push(fw.UTF8ToString(textBufPtr, telemLen));
		}
		if (nowWallMs - lastStatusMs >= 1000) {
			lastStatusMs = nowWallMs;
			const stLen = fw._virtual_body_status(nowUs, textBufPtr, TEXT_BUF_CAP);
			if (stLen > 0) {
				txMessages.push(fw.UTF8ToString(textBufPtr, stLen));
			}
			const fhLen = fw._virtual_body_feedback_health(
				nowUs,
				textBufPtr,
				TEXT_BUF_CAP,
			);
			if (fhLen > 0) {
				txMessages.push(fw.UTF8ToString(textBufPtr, fhLen));
			}
		}
		if (nowWallMs - lastHeartbeatMs >= 1000) {
			lastHeartbeatMs = nowWallMs;
			const hbLen = fw._virtual_body_heartbeat(
				nowUs,
				0,
				textBufPtr,
				TEXT_BUF_CAP,
			);
			if (hbLen > 0) {
				txMessages.push(fw.UTF8ToString(textBufPtr, hbLen));
			}
		}
		if (txMessages.length > 0) {
			post({ type: "protocol-tx", messages: txMessages });
		}
	}

	// Render exact 320x170 ST7789 face at up to 20 Hz, only transferring when changed
	if (nowWallMs - lastFaceRenderMs >= 50) {
		lastFaceRenderMs = nowWallMs;
		const ok = fw._virtual_body_face_frame(
			nowUs / 1000n,
			mediaTalking ? 1 : 0,
			mediaCapturing ? 1 : 0,
			faceRgbaPtr,
			faceNamePtr,
			64,
			faceTokenPtr,
			96,
		);
		if (ok) {
			lastFaceName = fw.UTF8ToString(faceNamePtr, 64) || "default";
			lastFaceToken = fw.UTF8ToString(faceTokenPtr, 96) || "";
			const view = fw.HEAPU8.subarray(
				faceRgbaPtr,
				faceRgbaPtr + FACE_RGBA_BYTES,
			);
			const h = hashRgba(view);
			if (h !== lastFaceHash) {
				lastFaceHash = h;
				const copy = new Uint8Array(FACE_RGBA_BYTES);
				copy.set(view);
				post(
					{
						type: "face",
						width: SIM_FACE_WIDTH,
						height: SIM_FACE_HEIGHT,
						rgba: copy.buffer,
					},
					[copy.buffer],
				);
			}
		}
	}

	// Build 50 Hz UI & 3D pose state
	const w = mjData.qpos[3] ?? 1;
	const x = mjData.qpos[4] ?? 0;
	const y = mjData.qpos[5] ?? 0;
	const z = mjData.qpos[6] ?? 0;
	const rollDeg =
		Math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y)) * RAD2DEG;
	const pitchDeg =
		Math.asin(Math.max(-1, Math.min(1, 2 * (w * y - z * x)))) * RAD2DEG;
	const yawDeg =
		Math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)) * RAD2DEG;

	const jointsDeg: number[] = [];
	const commandedDeg: number[] = [];
	const measuredDeg: number[] = [];
	for (let j = 0; j < 12; j += 1) {
		jointsDeg.push(
			Math.round((mjData.qpos[config.qadr[j] ?? 0] ?? 0) * RAD2DEG * 100) / 100,
		);
		commandedDeg.push(Math.round((lastLogicalDeg[j] ?? 0) * 100) / 100);
		measuredDeg.push(Math.round((lastMeasuredDeg[j] ?? 0) * 100) / 100);
	}
	const stepMs = Math.round((performance.now() - tStart) * 100) / 100;

	const state: RobotTelemetryState = {
		simTimeS: Math.round(mjData.time * 1000) / 1000,
		stepMs,
		armed: lastArmed,
		enabledMask: lastEnabledMask,
		stalledMask: lastJammedMask,
		pinnedJoints: [...pinnedJoints.keys()].sort((a, b) => a - b),
		rootPosMj: [
			Math.round((mjData.qpos[0] ?? 0) * 100000) / 100000,
			Math.round((mjData.qpos[1] ?? 0) * 100000) / 100000,
			Math.round((mjData.qpos[2] ?? 0) * 100000) / 100000,
		],
		rootQuatMjWxyz: [
			Math.round(w * 100000) / 100000,
			Math.round(x * 100000) / 100000,
			Math.round(y * 100000) / 100000,
			Math.round(z * 100000) / 100000,
		],
		jointsDeg,
		commandedDeg,
		measuredDeg,
		footContacts,
		imu: {
			rollDeg: Math.round(rollDeg * 10) / 10,
			pitchDeg: Math.round(pitchDeg * 10) / 10,
			yawDeg: Math.round(yawDeg * 10) / 10,
			accel: [
				Math.round((lastImuSample[4] ?? 0) * 1000) / 1000,
				Math.round((lastImuSample[5] ?? 0) * 1000) / 1000,
				Math.round((lastImuSample[6] ?? 0) * 1000) / 1000,
			],
			gyro: [
				Math.round((lastImuSample[7] ?? 0) * 1000) / 1000,
				Math.round((lastImuSample[8] ?? 0) * 1000) / 1000,
				Math.round((lastImuSample[9] ?? 0) * 1000) / 1000,
			],
		},
		face: {
			name: lastFaceName,
			token: lastFaceToken,
			talking: mediaTalking,
			listening: mediaCapturing,
		},
		camera: {
			enabled: cameraEnabled,
			fps: cameraFps,
			res: cameraRes,
			snapshotRes: cameraSnapshotRes,
		},
		batteryVoltage,
		recording: {
			active: recordingActive,
			label: recordingLabel,
			steps: recordingRows.length,
		},
		neural: {
			engine: engineMode,
			gaitModelId: gaitPolicy?.manifest.modelId ?? "loading",
			poseModelId:
				posePolicy?.manifest.modelId ?? poseManifest?.modelId ?? "loading",
			activeRole: activeNeuralRole,
			activeMotionId: activePose?.motion.id,
			activeTwist:
				activeNeuralRole === "gait"
					? [
							Math.round(gaitTwist[0] * 1000) / 1000,
							Math.round(gaitTwist[1] * 1000) / 1000,
							Math.round(gaitTwist[2] * 1000) / 1000,
						]
					: undefined,
			lastInferMs: lastNeuralInferMs,
			hostSamplesSent,
			hostNakCount,
		},
	};

	if (recordingActive) {
		const rx = mjData.qpos[0] ?? 0;
		const ry = mjData.qpos[1] ?? 0;
		if (!recordingStartXy) {
			recordingStartXy = [rx, ry];
		}
		recordingLastXy = [rx, ry];
		recordingRows.push(
			JSON.stringify({
				step: recordingRows.length + 1,
				sim_time_s: state.simTimeS,
				device_us: Number(nowUs),
				root_pos_mj: state.rootPosMj,
				root_quat_wxyz: state.rootQuatMjWxyz,
				qpos_joints_deg: state.jointsDeg,
				commanded_deg: state.commandedDeg,
				measured_deg: state.measuredDeg,
				imu_accel_m_s2: state.imu.accel,
				imu_gyro_rad_s: state.imu.gyro,
				foot_contact: state.footContacts,
				stalled_mask: state.stalledMask,
				armed: state.armed,
				face_name: state.face.name,
			}),
		);
	}

	post({ type: "state", state });
	maybeEmitCameraStreamTick(nowWallMs);
}

function startFirmwareSession(epoch: number, welcomeJson?: string): void {
	if (!fw) {
		return;
	}
	clearNeuralControllers();
	cameraEnabled = false;
	cameraFps = 0;
	lastCameraStreamMs = 0;
	emitProtocolTx = welcomeJson !== undefined;
	standaloneEpoch = epoch;
	standaloneSeq = 1;
	standaloneSeqRemap.clear();
	activeConnectionId += 1n;
	const nowUs = nowDeviceUs();
	lastStandalonePingUs = nowUs;
	fw._virtual_body_open(activeConnectionId, nowUs);
	const wire =
		welcomeJson ??
		JSON.stringify({
			t: "welcome",
			ver: 1,
			epoch,
			profile: "home",
			command_deadline_v1: true,
		});
	const wirePtr = writeCString(wire);
	const n = fw._virtual_body_receive(
		wirePtr,
		activeConnectionId,
		nowUs,
		textBufPtr,
		TEXT_BUF_CAP,
	);
	fw._free(wirePtr);
	if (n > 0) {
		post({ type: "protocol-tx", messages: [fw.UTF8ToString(textBufPtr, n)] });
	}
	if (emitProtocolTx) {
		const stLen = fw._virtual_body_status(nowUs, textBufPtr, TEXT_BUF_CAP);
		if (stLen > 0) {
			post({
				type: "protocol-tx",
				messages: [fw.UTF8ToString(textBufPtr, stLen)],
			});
		}
	}
	drainMediaActions();
}

async function handleInit(
	baseUrl: string,
	obstaclesMj: readonly ArenaBoxObstacle[],
	spawnMj: readonly [number, number, number],
	collidersMj: readonly ArenaCollider[] = [],
	hfield?: ArenaHeightfield,
	useDefaultFloorPlane = true,
): Promise<void> {
	const prefix = baseUrl.endsWith("/") ? baseUrl.slice(0, -1) : baseUrl;
	workerBaseUrl = prefix;

	const [
		cfgResp,
		xmlResp,
		mjModImport,
		fwModImport,
		gaitJsonResp,
		gaitBinResp,
		poseJsonResp,
		manifoldResp,
		poseLibResp,
	] = await Promise.all([
		fetch(`${prefix}/sim/v2-physics-config.json`),
		fetch(`${prefix}/sim/ainekio-v2-locomotion.xml`),
		import(/* @vite-ignore */ `${prefix}/sim/mujoco_wasm.js`),
		import(/* @vite-ignore */ `${prefix}/sim/ainekio-v2-firmware.mjs`),
		fetch(`${prefix}/sim/policies/neural-gait.json`),
		fetch(`${prefix}/sim/policies/neural-gait.bin`),
		fetch(`${prefix}/sim/policies/neural-pose.json`),
		fetch(`${prefix}/sim/policies/pose-manifold.json`),
		fetch(`${prefix}/sim/policies/neural-pose-library.json`),
	]);
	if (!cfgResp.ok) {
		throw new Error(
			`Failed to fetch v2-physics-config.json (${cfgResp.status})`,
		);
	}
	if (!xmlResp.ok) {
		throw new Error(
			`Failed to fetch ainekio-v2-locomotion.xml (${xmlResp.status})`,
		);
	}
	if (
		!gaitJsonResp.ok ||
		!gaitBinResp.ok ||
		!poseJsonResp.ok ||
		!manifoldResp.ok ||
		!poseLibResp.ok
	) {
		throw new Error(
			"Failed to fetch embedded Neural Gait / Neural Pose assets.",
		);
	}

	const [
		cfgData,
		xmlText,
		gaitManifest,
		gaitBuf,
		loadedPoseManifest,
		manifoldCfg,
		poseLibData,
	] = await Promise.all([
		cfgResp.json() as Promise<V2PhysicsConfig>,
		xmlResp.text(),
		gaitJsonResp.json() as Promise<NeuralGaitManifest>,
		gaitBinResp.arrayBuffer(),
		poseJsonResp.json() as Promise<NeuralPoseManifest>,
		manifoldResp.json() as Promise<PoseManifoldConfig>,
		poseLibResp.json() as Promise<NeuralPoseLibrary>,
	]);

	config = cfgData;
	baseXml = xmlText;
	gaitPolicy = new NeuralGaitPolicy(gaitManifest, new Float32Array(gaitBuf));
	poseManifest = loadedPoseManifest;
	poseManifold = new PoseManifoldRuntime(manifoldCfg);
	poseLibrary = poseLibData;

	const loadMujoco = mjModImport.default as () => Promise<MujocoModule>;
	const loadFirmware = fwModImport.default as (opts?: {
		locateFile?: (p: string) => string;
	}) => Promise<FirmwareWasm>;

	const [mjInstance, fwInstance] = await Promise.all([
		loadMujoco(),
		loadFirmware({
			locateFile: (file: string) => `${prefix}/sim/${file}`,
		}),
	]);
	mujoco = mjInstance;
	fw = fwInstance;

	// Allocate reusable WASM scratch buffers
	textBufPtr = fw._malloc(TEXT_BUF_CAP);
	tickOutPtr = fw._malloc(40 * 8);
	accelPtr = fw._malloc(3 * 8);
	gyroPtr = fw._malloc(3 * 8);
	imuOutPtr = fw._malloc(14 * 8);
	rawPtr = fw._malloc(12 * 8);
	targetPtr = fw._malloc(12 * 8);
	tsPtr = fw._malloc(12 * 8);
	fbOutPtr = fw._malloc(36 * 8);
	faceRgbaPtr = fw._malloc(FACE_RGBA_BYTES);
	faceNamePtr = fw._malloc(64);
	faceTokenPtr = fw._malloc(96);
	micPcmPtr = fw._malloc(640);
	micPktPtr = fw._malloc(660);

	// Initialize native C sensor state (exact calibration + 4th-wire feedback curve)
	const flatMapping = new Float64Array(60);
	for (let j = 0; j < 12; j += 1) {
		const row = config.mapping[j] ?? [];
		for (let k = 0; k < 5; k += 1) {
			flatMapping[j * 5 + k] = row[k] ?? 0;
		}
	}
	const flatFeedback = new Float64Array(84);
	for (let j = 0; j < 12; j += 1) {
		const row = config.feedbackTable[j] ?? [];
		for (let k = 0; k < 7; k += 1) {
			flatFeedback[j * 7 + k] = row[k] ?? 0;
		}
	}
	const fbSettings = new Float64Array(config.feedbackSettings);

	const mapPtr = writeDoubles(flatMapping);
	const fbPtr = writeDoubles(flatFeedback);
	const fbsPtr = writeDoubles(fbSettings);
	simStatePtr = fw._simulation_new(mapPtr, fbPtr, fbsPtr);
	fw._free(mapPtr);
	fw._free(fbPtr);
	fw._free(fbsPtr);
	if (!simStatePtr) {
		throw new Error("simulation_new() rejected V2 calibration/feedback table.");
	}

	// Build MuJoCo model with level obstacles / colliders / heightfield
	await loadMujocoModel(
		obstaclesMj,
		spawnMj,
		collidersMj,
		hfield,
		useDefaultFloorPlane,
	);

	// Reset virtual_body (11-double settings array matching virtual_body.c)
	resetVirtualBodyToReference();

	// Pre-warm IMU filter for 0.5 s at rest (matching GaitEnvironment)
	for (let k = 0; k < 104; k += 1) {
		const tUs = (k / 208) * 1_000_000;
		const ai = accelPtr >> 3;
		const gi = gyroPtr >> 3;
		fw.HEAPF64[ai] = 0;
		fw.HEAPF64[ai + 1] = 0;
		fw.HEAPF64[ai + 2] = 9.80665;
		fw.HEAPF64[gi] = 0;
		fw.HEAPF64[gi + 1] = 0;
		fw.HEAPF64[gi + 2] = 0;
		fw._simulation_imu(simStatePtr, tUs, accelPtr, gyroPtr, imuOutPtr);
	}

	// Read authentic P4 hello command catalog
	const idPtr = writeCString("ainekio-v2-sim");
	const tokPtr = writeCString("standalone");
	const helloLen = fw._virtual_body_hello(
		idPtr,
		tokPtr,
		nowDeviceUs(),
		textBufPtr,
		TEXT_BUF_CAP,
	);
	fw._free(idPtr);
	fw._free(tokPtr);
	let helloCommands: string[] = [];
	if (helloLen > 0) {
		try {
			const parsed = JSON.parse(fw.UTF8ToString(textBufPtr, helloLen)) as {
				capabilities?: { commands?: string[] };
			};
			if (Array.isArray(parsed.capabilities?.commands)) {
				helloCommands = parsed.capabilities.commands;
			}
		} catch {
			// ignore
		}
	}

	// Open standalone session immediately so built-in Cockpit works out of the box
	startFirmwareSession(1);

	// Run 50 Hz control loop (20 ms period -> 10x 500 Hz MuJoCo substeps)
	if (runningTimer !== undefined) {
		self.clearInterval(runningTimer);
	}
	runningTimer = self.setInterval(() => {
		try {
			stepControlFrame();
		} catch (error) {
			post({
				type: "error",
				message: error instanceof Error ? error.message : "MuJoCo step failed.",
			});
		}
	}, 20);

	const neuralMotions: NeuralMotionCatalogItem[] = (
		poseLibrary?.motions ?? []
	).map((m) => ({
		id: m.id,
		label: m.label,
		sourceTitle: m.sourceTitle,
	}));

	post({
		type: "ready",
		helloCommands,
		neuralGaitModelId: gaitPolicy.manifest.modelId,
		neuralPoseModelId:
			posePolicy?.manifest.modelId ??
			poseManifest?.modelId ??
			"neural-pose-v7-hysteresis",
		neuralMotions,
	});
}

self.addEventListener(
	"message",
	(event: MessageEvent<WorkerInboundMessage>) => {
		const msg = event.data;
		if (msg.type === "init") {
			void handleInit(
				msg.baseUrl,
				msg.obstaclesMj,
				msg.spawnMj,
				msg.collidersMj ?? [],
				msg.hfield,
				msg.useDefaultFloorPlane ?? true,
			).catch((error) => {
				post({
					type: "error",
					message:
						error instanceof Error
							? error.message
							: "Failed to initialize MuJoCo WASM simulator.",
				});
			});
			return;
		}

		if (!fw || !mjData) {
			return;
		}

		switch (msg.type) {
			case "set-robot":
				void handleSetRobot(
					msg.robotModel,
					msg.obstaclesMj,
					msg.spawnMj,
					msg.collidersMj ?? [],
					msg.hfield,
					msg.useDefaultFloorPlane ?? true,
				).catch((error) => {
					post({
						type: "error",
						message:
							error instanceof Error
								? error.message
								: "Failed to switch robot model.",
					});
				});
				return;
			case "set-level":
				void loadMujocoModel(
					msg.obstaclesMj,
					msg.spawnMj,
					msg.collidersMj ?? [],
					msg.hfield,
					msg.useDefaultFloorPlane ?? true,
				).catch((error) => {
					post({
						type: "error",
						message:
							error instanceof Error
								? error.message
								: "Failed to load level physics model.",
					});
				});
				return;
			case "session-reset":
				startFirmwareSession(msg.epoch, msg.welcomeJson);
				return;
			case "session-close":
				if (activeConnectionId > 0n) {
					fw._virtual_body_connection_lost(activeConnectionId);
				}
				return;
			case "request-hello": {
				const idPtr = writeCString(msg.robotId);
				const tokPtr = writeCString(msg.token);
				const n = fw._virtual_body_hello(
					idPtr,
					tokPtr,
					nowDeviceUs(),
					textBufPtr,
					TEXT_BUF_CAP,
				);
				fw._free(idPtr);
				fw._free(tokPtr);
				if (n > 0) {
					let wire = fw.UTF8ToString(textBufPtr, n);
					try {
						const hello = JSON.parse(wire) as Record<string, unknown>;
						const baseFeatures = Array.isArray(hello.features)
							? hello.features.filter((f): f is string => typeof f === "string")
							: [];
						const v2OnlyFeatures = new Set([
							"walk_nominal_v1",
							"motion_targets_v1",
							"motion_curves_v1",
							"body_calibration_v2",
						]);
						const filteredFeatures =
							activeRobotModel === "v1" || activeRobotModel === "v3"
								? baseFeatures.filter((f) => !v2OnlyFeatures.has(f))
								: baseFeatures;
						if (!filteredFeatures.includes("room_chat_v1")) {
							filteredFeatures.push("room_chat_v1");
						}
						hello.features = filteredFeatures;
						if (activeRobotModel === "v1" || activeRobotModel === "v3") {
							hello.model =
								activeRobotModel === "v1" ? "v1-8servo" : "v3-12servo";
							hello.fw =
								activeRobotModel === "v1" ? "virtual-v1-sim" : "virtual-v3-sim";
						}
						wire = JSON.stringify(hello);
					} catch {
						// fall back to base hello string
					}
					post({ type: "hello", wire });
				}
				return;
			}
			case "protocol-rx": {
				const nowUs = nowDeviceUs();
				if (activeRobotModel === "v1" || activeRobotModel === "v3") {
					try {
						const parsed = JSON.parse(msg.wire) as Record<string, unknown>;
						if (parsed && typeof parsed === "object") {
							if (parsed.t === "intent" && parsed.name === "walk") {
								const fwd = Number(parsed.forward ?? 0);
								const lat = Number(parsed.lateral ?? 0);
								const trn = Number(parsed.turn ?? 0);
								const spd = Number(parsed.speed ?? 100);
								if (emitProtocolTx && engineMode === "neural") {
									if (activeRobotModel === "v1") {
										startOrUpdateV1NeuralWalk(fwd, lat, trn, spd);
									} else {
										startOrUpdateV3NeuralWalk(fwd, lat, trn, spd);
									}
								} else {
									const spdScale = Math.max(0.25, Math.min(1.5, spd / 100));
									if (activeRobotModel === "v1") {
										v1NativeWalkCmd = [
											fwd / 100,
											lat / 100,
											trn / 100,
											spdScale,
										];
										v1Armed = true;
										v1ActiveRole = "native";
										v1ActiveMotionId = undefined;
									} else {
										v3NativeWalkCmd = [
											(fwd / 100) * 0.35 * spdScale,
											(lat / 100) * 0.2 * spdScale,
											(trn / 100) * 1.5 * spdScale,
										];
										v3Armed = true;
										v3ActiveRole = "native";
										v3ActiveMotionId = undefined;
									}
								}
								if (!emitProtocolTx) {
									return;
								}
							} else if (
								parsed.t === "intent" &&
								(parsed.name === "stand" ||
									parsed.name === "neutral" ||
									parsed.name === "sit" ||
									parsed.name === "lay" ||
									parsed.name === "bow" ||
									parsed.name === "stretch" ||
									parsed.name === "crouch" ||
									parsed.name === "wave" ||
									parsed.name === "emote")
							) {
								const rawPoseName =
									parsed.name === "emote"
										? String(parsed.asset ?? "stand")
										: String(parsed.name);
								const poseName =
									rawPoseName === "wave" ? "wave_fr" : rawPoseName;
								if (emitProtocolTx && engineMode === "neural") {
									const req = ++poseRequestSeq;
									if (activeRobotModel === "v1") {
										if (v1PosePolicy) {
											startV1NeuralPoseMotion(poseName);
										} else {
											void ensureV1PosePolicyLoaded().then((loaded) => {
												if (
													loaded &&
													req === poseRequestSeq &&
													activeRobotModel === "v1"
												) {
													startV1NeuralPoseMotion(poseName);
												}
											});
										}
									} else {
										if (v3PosePolicy) {
											startV3NeuralPoseMotion(poseName);
										} else {
											void ensureV3PosePolicyLoaded().then((loaded) => {
												if (
													loaded &&
													req === poseRequestSeq &&
													activeRobotModel === "v3"
												) {
													startV3NeuralPoseMotion(poseName);
												}
											});
										}
									}
								} else if (activeRobotModel === "v1") {
									const goal = sampleV1NativePostureDeg(poseName);
									if (goal) {
										for (let j = 0; j < 8; j += 1) {
											v1GoalDeg[j] = goal[j] ?? 0;
										}
										v1NativeWalkCmd = [0, 0, 0, 1];
										v1Armed = true;
										v1ActiveRole = "native";
										v1ActiveMotionId = poseName;
									}
								} else {
									const goal = sampleV3NativePostureDeg(poseName);
									if (goal) {
										for (let j = 0; j < 12; j += 1) {
											v3GoalDeg[j] = goal[j] ?? 0;
										}
										v3NativeWalkCmd = [0, 0, 0];
										v3Armed = true;
										v3ActiveRole = "native";
										v3ActiveMotionId = poseName;
									}
								}
								if (!emitProtocolTx) {
									return;
								}
							} else if (parsed.t === "stop") {
								if (activeRobotModel === "v1") {
									stopV1Motion(Boolean(parsed.detach));
								} else {
									stopV3Motion(Boolean(parsed.detach));
								}
								if (!emitProtocolTx) {
									return;
								}
							} else if (!emitProtocolTx && parsed.t === "balance") {
								return;
							}
						}
					} catch {
						// ignore
					}
				}
				let wireToSend = msg.wire;
				// In standalone mode (emitProtocolTx === false), maintain monotonic seq
				// across worker neural commands + main-thread commands and stamp fresh
				// device-clock deadline_ms so ainekio_admission_accept passes authentically.
				if (!emitProtocolTx) {
					try {
						const parsed = JSON.parse(msg.wire) as Record<string, unknown>;
						if (parsed && typeof parsed === "object") {
							if (typeof parsed.seq === "number") {
								const origSeq = parsed.seq;
								const mappedSeq = nextStandaloneSeq();
								standaloneSeqRemap.set(origSeq, mappedSeq);
								parsed.seq = mappedSeq;
								if (typeof parsed.update === "number") {
									const mappedUpd = standaloneSeqRemap.get(parsed.update);
									if (mappedUpd !== undefined) {
										parsed.update = mappedUpd;
									}
								}
								if (parsed.t !== "stop" && parsed.deadline_ms === undefined) {
									parsed.deadline_ms = Number(nowUs / 1000n) + 5000;
								}
								// If main thread sends native walk/emote/stand/stop, yield neural controller
								if (
									parsed.t === "stop" ||
									(parsed.t === "intent" &&
										parsed.name !== "face" &&
										parsed.name !== "say")
								) {
									clearNeuralControllers();
									if (parsed.t === "intent" && parsed.name === "walk") {
										activeNeuralRole = "native";
									}
								}
								wireToSend = JSON.stringify(parsed);
							}
						}
					} catch {
						// leave untouched
					}
				}
				const wirePtr = writeCString(wireToSend);
				const n = fw._virtual_body_receive(
					wirePtr,
					activeConnectionId,
					nowUs,
					textBufPtr,
					TEXT_BUF_CAP,
				);
				fw._free(wirePtr);
				const out: string[] = [];
				if (n > 0) {
					const raw = fw.UTF8ToString(textBufPtr, n);
					// virtual_body_receive can return either a single JSON object or a JSON array of replies
					try {
						const parsed = JSON.parse(raw) as unknown;
						if (Array.isArray(parsed)) {
							for (const item of parsed) {
								out.push(
									typeof item === "string" ? item : JSON.stringify(item),
								);
							}
						} else {
							out.push(raw);
						}
					} catch {
						out.push(raw);
					}
				}
				if (out.length > 0) {
					post({ type: "protocol-tx", messages: out });
				}
				drainMediaActions();
				return;
			}
			case "set-media":
				if (msg.talking !== undefined) mediaTalking = msg.talking;
				if (msg.capturing !== undefined) mediaCapturing = msg.capturing;
				if (msg.micRms !== undefined) mediaMicRms = msg.micRms;
				if (msg.micPeak !== undefined) mediaMicPeak = msg.micPeak;
				if (msg.cameraReady !== undefined) mediaCameraReady = msg.cameraReady;
				return;
			case "mic-gate": {
				mediaCapturing = msg.open;
				if (!msg.open) {
					mediaMicRms = 0;
					mediaMicPeak = 0;
				}
				const nowUs = nowDeviceUs();
				const n = fw._virtual_body_mic_gate(
					nowUs,
					msg.open ? 1 : 0,
					msg.wakeWord ? 1 : 0,
					textBufPtr,
					TEXT_BUF_CAP,
				);
				if (n > 0 && emitProtocolTx) {
					post({
						type: "protocol-tx",
						messages: [fw.UTF8ToString(textBufPtr, n)],
					});
				}
				drainMediaActions();
				return;
			}
			case "mic-frame": {
				if (msg.pcm.byteLength !== 640 || !micPcmPtr || !micPktPtr) {
					return;
				}
				fw.HEAPU8.set(new Uint8Array(msg.pcm), micPcmPtr);
				const encoded = fw._virtual_body_mic_frame(
					nowDeviceUs(),
					micPcmPtr,
					640,
					micPktPtr,
					660,
				);
				if (encoded > 0 && emitProtocolTx) {
					const pkt = fw.HEAPU8.slice(micPktPtr, micPktPtr + encoded).buffer;
					post({ type: "protocol-packet", binary: pkt }, [pkt]);
				}
				return;
			}
			case "camera-frame": {
				if (!emitProtocolTx) {
					return;
				}
				const jpegBytes = new Uint8Array(msg.jpeg);
				if (jpegBytes.byteLength === 0) {
					return;
				}
				const jpegPtr = fw._malloc(jpegBytes.byteLength);
				const pktCap = jpegBytes.byteLength + 16;
				const pktPtr = fw._malloc(pktCap);
				const metaCap = 512;
				const metaPtr = fw._malloc(metaCap);
				const doneCap = 256;
				const donePtr = fw._malloc(doneCap);
				const resPtr = writeCString(msg.res);
				try {
					fw.HEAPU8.set(jpegBytes, jpegPtr);
					const originCode =
						msg.origin === "request" ? 1 : msg.origin === "audio" ? 3 : 0;
					const encoded = fw._virtual_body_camera_frame(
						nowDeviceUs(),
						originCode,
						msg.originId >>> 0,
						resPtr,
						BigInt(Math.max(0, Math.round(msg.frameCompletedUs))),
						msg.bootId >>> 0,
						jpegPtr,
						jpegBytes.byteLength,
						metaPtr,
						metaCap,
						pktPtr,
						pktCap,
						donePtr,
						doneCap,
					);
					const doneJson = fw.UTF8ToString(donePtr, doneCap);
					if (encoded > 0) {
						const metaJson = fw.UTF8ToString(metaPtr, metaCap);
						const pkt = fw.HEAPU8.slice(pktPtr, pktPtr + encoded).buffer;
						post(
							{
								type: "protocol-packet",
								...(metaJson ? { preText: metaJson } : {}),
								binary: pkt,
								...(doneJson ? { postText: doneJson } : {}),
							},
							[pkt],
						);
					} else if (doneJson) {
						post({ type: "protocol-tx", messages: [doneJson] });
					}
				} finally {
					fw._free(resPtr);
					fw._free(donePtr);
					fw._free(metaPtr);
					fw._free(pktPtr);
					fw._free(jpegPtr);
				}
				return;
			}
			case "wrench":
				activeWrench[0] = msg.forceMj[0];
				activeWrench[1] = msg.forceMj[1];
				activeWrench[2] = msg.forceMj[2];
				activeWrench[3] = msg.torqueMj[0];
				activeWrench[4] = msg.torqueMj[1];
				activeWrench[5] = msg.torqueMj[2];
				wrenchUntilMs =
					performance.now() + Math.max(20, Math.min(5000, msg.durationMs));
				return;
			case "pin-joint": {
				const activeQadr =
					activeRobotModel === "v1"
						? v1Config?.qadr
						: activeRobotModel === "v3"
							? v3Config?.qadr
							: config?.qadr;
				const jointCount = activeRobotModel === "v1" ? 8 : 12;
				if (activeQadr && msg.jointIndex >= 0 && msg.jointIndex < jointCount) {
					if (msg.pinned) {
						const qIdx = activeQadr[msg.jointIndex] ?? 0;
						pinnedJoints.set(msg.jointIndex, mjData.qpos[qIdx] ?? 0);
					} else {
						pinnedJoints.delete(msg.jointIndex);
					}
				}
				return;
			}
			case "clear-pins":
				pinnedJoints.clear();
				return;
			case "reset-pose":
				resetRobotPose(msg.spawnMj);
				return;
			case "record-start":
				recordingActive = true;
				recordingLabel = msg.label || `ainekio_${activeRobotModel}`;
				recordingRows = [];
				recordingStartXy = undefined;
				recordingLastXy = undefined;
				recordingStartedAtMs = performance.now();
				return;
			case "set-engine":
				poseRequestSeq += 1;
				engineMode = msg.engine;
				if (activeRobotModel === "v1") {
					stopV1Motion(false);
				} else if (activeRobotModel === "v3") {
					stopV3Motion(false);
				} else if (!emitProtocolTx && activeNeuralRole !== "idle") {
					clearNeuralControllers();
					sendStandaloneFirmwareCommand({ t: "stop" });
				}
				return;
			case "neural-walk":
				poseRequestSeq += 1;
				if (activeRobotModel === "v1") {
					startOrUpdateV1NeuralWalk(
						msg.forward,
						msg.lateral,
						msg.turn,
						msg.speed,
					);
				} else if (activeRobotModel === "v3") {
					startOrUpdateV3NeuralWalk(
						msg.forward,
						msg.lateral,
						msg.turn,
						msg.speed,
					);
				} else if (!emitProtocolTx) {
					startOrUpdateNeuralWalk(
						msg.forward,
						msg.lateral,
						msg.turn,
						msg.speed,
					);
				}
				return;
			case "neural-pose": {
				const req = ++poseRequestSeq;
				if (activeRobotModel === "v1") {
					if (v1PosePolicy) {
						startV1NeuralPoseMotion(msg.motionId);
					} else {
						void ensureV1PosePolicyLoaded().then((loaded) => {
							if (
								loaded &&
								req === poseRequestSeq &&
								activeRobotModel === "v1"
							) {
								startV1NeuralPoseMotion(msg.motionId);
							}
						});
					}
				} else if (activeRobotModel === "v3") {
					if (v3PosePolicy) {
						startV3NeuralPoseMotion(msg.motionId);
					} else {
						void ensureV3PosePolicyLoaded().then((loaded) => {
							if (
								loaded &&
								req === poseRequestSeq &&
								activeRobotModel === "v3"
							) {
								startV3NeuralPoseMotion(msg.motionId);
							}
						});
					}
				} else if (!emitProtocolTx) {
					if (posePolicy) {
						startNeuralPoseMotion(msg.motionId);
					} else {
						void ensureV2PosePolicyLoaded().then((loaded) => {
							if (
								loaded &&
								req === poseRequestSeq &&
								activeRobotModel === "v2" &&
								!emitProtocolTx
							) {
								startNeuralPoseMotion(msg.motionId);
							}
						});
					}
				}
				return;
			}
			case "neural-stop":
				poseRequestSeq += 1;
				if (activeRobotModel === "v1") {
					stopV1Motion(Boolean(msg.detach));
				} else if (activeRobotModel === "v3") {
					stopV3Motion(Boolean(msg.detach));
				} else if (!emitProtocolTx) {
					clearNeuralControllers();
					const stopPayload: Record<string, unknown> = { t: "stop" };
					if (msg.detach) {
						stopPayload.detach = true;
					}
					sendStandaloneFirmwareCommand(stopPayload);
				}
				return;
			case "record-stop": {
				if (!recordingActive) {
					return;
				}
				recordingActive = false;
				const durationS =
					Math.round(
						((performance.now() - recordingStartedAtMs) / 1000) * 1000,
					) / 1000;
				const displacementM =
					recordingStartXy && recordingLastXy
						? Math.round(
								Math.hypot(
									recordingLastXy[0] - recordingStartXy[0],
									recordingLastXy[1] - recordingStartXy[1],
								) * 10000,
							) / 10000
						: 0;
				post({
					type: "recording-export",
					label: recordingLabel,
					steps: recordingRows.length,
					jsonl: `${recordingRows.join("\n")}\n`,
					summary: {
						label: recordingLabel,
						steps: recordingRows.length,
						duration_s: durationS,
						displacement_m: displacementM,
						model:
							activeRobotModel === "v1"
								? "v1-8servo"
								: activeRobotModel === "v3"
									? "v3-12servo"
									: "v2-12servo",
						physics: "mujoco-wasm-500hz",
					},
				});
				recordingRows = [];
				return;
			}
		}
	},
);

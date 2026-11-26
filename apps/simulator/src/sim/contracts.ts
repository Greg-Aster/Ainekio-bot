import type { MultiplayerSnapshot } from "@ainekio/engine/multiplayer";

/**
 * Canonical pure-TypeScript contracts, coordinate transforms, and protocol-v1
 * binary codecs for the standalone Ainekio V2 MuJoCo WASM Simulator.
 */

export const SIM_FACE_WIDTH = 320;
export const SIM_FACE_HEIGHT = 170;
export const SIM_AUDIO_SAMPLE_RATE = 16000;
export const SIM_AUDIO_FRAME_BYTES = 640; // 20 ms mono 16-bit PCM

// protocol-v1 binary frame types matching Ainekio/Slave/software/protocol/binary_helpers.py
export const PROTOCOL_BIN_MIC_PCM = 1;
export const PROTOCOL_BIN_CAMERA_JPEG = 2;
export const PROTOCOL_BIN_SPEAKER_PCM = 3;

export const V2_JOINT_LABELS = [
	"RL Hip",
	"RL Upper",
	"RL Lower",
	"RR Hip",
	"RR Upper",
	"RR Lower",
	"FL Hip",
	"FL Upper",
	"FL Lower",
	"FR Hip",
	"FR Upper",
	"FR Lower",
] as const;

export const V2_FOOT_LABELS = ["RL", "RR", "FL", "FR"] as const;

export const V1_JOINT_LABELS = [
	"R1 FR Hip",
	"R2 RR Hip",
	"L1 FL Hip",
	"L2 RL Hip",
	"R4 RR Knee",
	"R3 FR Knee",
	"L3 FL Knee",
	"L4 RL Knee",
] as const;

export const V1_FOOT_LABELS = ["FR", "RR", "FL", "RL"] as const;

export const V3_JOINT_LABELS = [
	"RL Shoulder",
	"RL Carrier",
	"RL Crank",
	"RR Shoulder",
	"RR Carrier",
	"RR Crank",
	"FL Shoulder",
	"FL Carrier",
	"FL Crank",
	"FR Shoulder",
	"FR Carrier",
	"FR Crank",
] as const;

export const V3_FOOT_LABELS = ["RL", "RR", "FL", "FR"] as const;

export type RobotModelId = "v1" | "v2" | "v3";

export type RobotModelDescriptor = {
	readonly id: RobotModelId;
	readonly name: string;
	readonly shortName: string;
	readonly ready: boolean;
	readonly jointCount: number;
	readonly jointLabels: readonly string[];
	readonly footLabels: readonly string[];
	readonly displayLabel: string;
	readonly glbUrl: string;
	readonly spawnZ: number;
};

export const ROBOT_MODEL_CATALOG: readonly RobotModelDescriptor[] = [
	{
		id: "v1",
		name: "Ainekio V1 (8-Servo)",
		shortName: "V1",
		ready: true,
		jointCount: 8,
		jointLabels: V1_JOINT_LABELS,
		footLabels: V1_FOOT_LABELS,
		displayLabel: "128×64 OLED",
		glbUrl: "/assets/robots/ainekio-v1.glb",
		spawnZ: 0.058,
	},
	{
		id: "v2",
		name: "Ainekio V2 (12-Servo)",
		shortName: "V2",
		ready: true,
		jointCount: 12,
		jointLabels: V2_JOINT_LABELS,
		footLabels: V2_FOOT_LABELS,
		displayLabel: "320×170 LCD",
		glbUrl: "/assets/robots/ainekio-v2.glb",
		spawnZ: 0.066,
	},
	{
		id: "v3",
		name: "Ainekio V3 (12-Servo)",
		shortName: "V3",
		ready: true,
		jointCount: 12,
		jointLabels: V3_JOINT_LABELS,
		footLabels: V3_FOOT_LABELS,
		displayLabel: '2.8" ILI9341 LCD',
		glbUrl: "/assets/robots/ainekio-v3.glb",
		spawnZ: 0.182,
	},
];

export function getRobotModelDescriptor(
	id: RobotModelId,
): RobotModelDescriptor {
	return (
		ROBOT_MODEL_CATALOG.find((m) => m.id === id) ??
		(ROBOT_MODEL_CATALOG[1] as RobotModelDescriptor)
	);
}

export const V2_FACE_EXPRESSIONS = [
	"default",
	"happy",
	"excited",
	"curious",
	"surprised",
	"love",
	"cute",
	"thinking",
	"sleepy",
	"sad",
	"angry",
	"confused",
	"bored",
	"freaky",
] as const;

export const V2_CLIP_ACTIONS = [
	"stand",
	"neutral",
	"sit",
	"lay",
	"wave",
	"bow",
	"stretch",
	"shake",
	"dance",
] as const;

export type SimulatorLevelId =
	| "v2_lab"
	| "observatory"
	| "yggdrasil"
	| "miranda"
	| "solitude"
	| "sci-fi-room";

export type SimulatorCameraMode = "orbit" | "follow" | "robot-pov";
export type SimulatorControlMode = "standalone" | "body-control";
export type LocomotionEngineMode = "neural" | "native";

export type NeuralMotionCatalogItem = {
	readonly id: string;
	readonly label: string;
	readonly sourceTitle: string;
};

export type ArenaBoxObstacle = {
	readonly id: string;
	readonly posMj: readonly [number, number, number];
	readonly halfSizeMj: readonly [number, number, number];
	readonly color: string;
	readonly label?: string;
};

export type ArenaCollider =
	| {
			readonly id: string;
			readonly shape: "box";
			readonly posMj: readonly [number, number, number];
			readonly quatMj: readonly [number, number, number, number];
			readonly sizeMj: readonly [number, number, number];
	  }
	| {
			readonly id: string;
			readonly shape: "cylinder";
			readonly posMj: readonly [number, number, number];
			readonly quatMj: readonly [number, number, number, number];
			readonly sizeMj: readonly [number, number];
	  };

export type ArenaHeightfield = {
	readonly url: string;
	readonly posMj: readonly [number, number, number];
	readonly sizeMj: readonly [number, number, number, number];
};

export type ScenePrimitiveSpec = {
	readonly id: string;
	readonly shape: string;
	readonly pos: readonly [number, number, number];
	readonly quat: readonly [number, number, number, number];
	readonly scale: readonly [number, number, number];
	readonly args: readonly number[];
	readonly color: string;
	readonly emissive?: string | undefined;
	readonly emissiveIntensity?: number | undefined;
	readonly metalness?: number | undefined;
	readonly roughness?: number | undefined;
	readonly opacity?: number | undefined;
	readonly flatShading?: boolean | undefined;
};

export type SceneGlbInstanceSpec = {
	readonly id: string;
	readonly url: string;
	readonly pos: readonly [number, number, number];
	readonly quat: readonly [number, number, number, number];
	readonly scale: readonly [number, number, number];
};

export type SceneLightSpec = {
	readonly id: string;
	readonly color: string;
	readonly intensity: number;
	readonly distance: number;
	readonly pos: readonly [number, number, number];
};

export type SceneWaterSpec = {
	readonly y: number;
	readonly size: number;
	readonly color: string;
	readonly opacity: number;
};

export type WorldSfxId =
	| "select"
	| "soft"
	| "open"
	| "back"
	| "sweep"
	| "portal-activate"
	| "portal-awaken"
	| "portal-impact"
	| "portal-reveal";

export type LevelAudioRegionSpec = {
	readonly id: string;
	readonly label: string;
	readonly track: string;
	readonly posThree: readonly [number, number, number];
	readonly radius: number;
	readonly falloff: number;
	readonly volume: number;
};

export type LevelAudioSpec = {
	readonly label: string;
	readonly track: string;
	readonly volume: number;
	readonly surfaceAcoustic?: "metal" | "stone" | "meadow" | undefined;
	readonly regions?: readonly LevelAudioRegionSpec[] | undefined;
};

export type SimulatorAudioState = {
	readonly enabled: boolean;
	readonly unlocked: boolean;
	readonly playing: boolean;
	readonly musicVolume: number;
	readonly sfxVolume: number;
	readonly footstepsEnabled: boolean;
	readonly activeTrackLabel: string;
};

export type LazyLevelBundle = {
	readonly schemaVersion: number;
	readonly id: SimulatorLevelId;
	readonly name: string;
	readonly subtitle: string;
	readonly worldOriginThree: readonly [number, number, number];
	readonly skyboxDir: string;
	readonly backgroundHex: string;
	readonly fogHex: string;
	readonly fogDensity: number;
	readonly useDefaultFloorPlane: boolean;
	readonly terrainStyle?: "grassy-plain" | undefined;
	readonly robotSpawnMj: readonly [number, number, number];
	readonly primitives: readonly ScenePrimitiveSpec[];
	readonly glbInstances: readonly SceneGlbInstanceSpec[];
	readonly colliders: readonly ArenaCollider[];
	readonly hfield?: ArenaHeightfield | undefined;
	readonly lights: readonly SceneLightSpec[];
	readonly water?: SceneWaterSpec | undefined;
};

export type LevelDefinition = {
	readonly id: SimulatorLevelId;
	readonly name: string;
	readonly subtitle: string;
	readonly lazyBundleUrl?: string | undefined;
	readonly skyboxDir: string;
	readonly backgroundHex: string;
	readonly fogHex: string;
	readonly fogDensity: number;
	readonly ambientHex: string;
	readonly ambientIntensity: number;
	readonly sunHex: string;
	readonly sunIntensity: number;
	readonly sunPos: readonly [number, number, number];
	readonly floorColor: string;
	readonly floorSize: number;
	readonly showGrid: boolean;
	readonly useDefaultFloorPlane: boolean;
	readonly terrainStyle?: "grassy-plain" | undefined;
	readonly obstaclesMj: readonly ArenaBoxObstacle[];
	readonly collidersMj?: readonly ArenaCollider[] | undefined;
	readonly hfield?: ArenaHeightfield | undefined;
	readonly primitives?: readonly ScenePrimitiveSpec[] | undefined;
	readonly glbInstances?: readonly SceneGlbInstanceSpec[] | undefined;
	readonly lights?: readonly SceneLightSpec[] | undefined;
	readonly water?: SceneWaterSpec | undefined;
	readonly audio?: LevelAudioSpec | undefined;
	readonly robotSpawnMj: readonly [number, number, number];
	readonly defaultCameraPos: readonly [number, number, number];
	readonly defaultCameraTarget: readonly [number, number, number];
};

export type V1PhysicsConfig = {
	readonly schemaVersion: number;
	readonly model: string;
	readonly geometryId: string;
	readonly physicsHz: number;
	readonly controlHz: number;
	readonly standingRootHeightM: number;
	readonly jointNames: readonly string[];
	readonly jointCodes: readonly string[];
	readonly referenceJointDeg: readonly number[];
	readonly jointLimitsMinDeg: readonly number[];
	readonly jointLimitsMaxDeg: readonly number[];
	readonly initQpos: readonly number[];
	readonly qadr: readonly number[];
	readonly vadr: readonly number[];
	readonly torsoBodyId: number;
	readonly floorGeomId: number;
	readonly footGeoms: readonly string[];
	readonly footGeomIds: readonly number[];
	readonly gyroSensorAdr: number;
	readonly accelSensorAdr: number;
	readonly quatSensorAdr: number;
	readonly cameraSiteBodyMm: readonly [number, number, number];
};

export type V2PhysicsConfig = {
	readonly schemaVersion: number;
	readonly model: string;
	readonly collisionProfile: string;
	readonly physicsHz: number;
	readonly controlHz: number;
	readonly imuHz: number;
	readonly imuPrehistoryS: number;
	readonly referenceJointDeg: readonly number[];
	readonly initQpos: readonly number[];
	readonly qadr: readonly number[];
	readonly vadr: readonly number[];
	readonly torsoBodyId: number;
	readonly floorGeomId: number;
	readonly footGeoms: readonly string[];
	readonly footGeomIds: readonly number[];
	readonly gyroSensorAdr: number;
	readonly accelSensorAdr: number;
	readonly torqueNm: number;
	readonly motorNoLoadSpeedRadS: number;
	readonly jointSpeedDegS: number;
	readonly actuatorDelayS: number;
	readonly pwmOscillatorHz: number;
	readonly pwmFrequencyHz: number;
	readonly balanceEnabled: boolean;
	readonly headingFeedbackEnabled: boolean;
	readonly balanceTuning: readonly [number, number, number, number];
	readonly imuAccelNoiseStd: number;
	readonly imuGyroNoiseStd: number;
	readonly feedbackNoiseRawStd: number;
	readonly mapping: readonly (readonly number[])[];
	readonly feedbackTable: readonly (readonly number[])[];
	readonly feedbackSettings: readonly number[];
	readonly rawCurve: readonly (readonly (readonly [number, number])[])[];
};

export type RobotTelemetryState = {
	readonly simTimeS: number;
	readonly stepMs: number;
	readonly armed: boolean;
	readonly enabledMask: number;
	readonly stalledMask: number;
	readonly pinnedJoints: readonly number[];
	readonly rootPosMj: readonly [number, number, number];
	readonly rootQuatMjWxyz: readonly [number, number, number, number];
	readonly jointsDeg: readonly number[];
	readonly commandedDeg: readonly number[];
	readonly measuredDeg: readonly number[];
	readonly footContacts: readonly [boolean, boolean, boolean, boolean];
	readonly imu: {
		readonly rollDeg: number;
		readonly pitchDeg: number;
		readonly yawDeg: number;
		readonly accel: readonly [number, number, number];
		readonly gyro: readonly [number, number, number];
	};
	readonly face: {
		readonly name: string;
		readonly token: string;
		readonly talking: boolean;
		readonly listening: boolean;
	};
	readonly camera: {
		readonly enabled: boolean;
		readonly fps: number;
		readonly res: string;
		readonly snapshotRes: string;
	};
	readonly batteryVoltage: number;
	readonly recording: {
		readonly active: boolean;
		readonly label: string;
		readonly steps: number;
	};
	readonly neural: {
		readonly engine: LocomotionEngineMode;
		readonly gaitModelId: string;
		readonly poseModelId: string;
		readonly activeRole: "idle" | "gait" | "pose" | "native";
		readonly activeMotionId?: string | undefined;
		readonly activeTwist?: readonly [number, number, number] | undefined;
		readonly lastInferMs: number;
		readonly hostSamplesSent: number;
		readonly hostNakCount: number;
	};
};

export type BodyControlConnectionState = {
	readonly mode: SimulatorControlMode;
	readonly url: string;
	readonly robotId: string;
	readonly connected: boolean;
	readonly reconnecting?: boolean | undefined;
	readonly autoReconnect?: boolean | undefined;
	readonly epoch: number | null;
	readonly error?: string | undefined;
};

export type SimulatorCommsMessage = {
	readonly id: string;
	readonly sender: string;
	readonly role: "self" | "robot" | "peer" | "system";
	readonly channel: "direct" | "voice" | "room";
	readonly text: string;
	readonly timestampMs: number;
};

export type SimulatorUiSnapshot = {
	readonly ready: boolean;
	readonly loadingMessage: string;
	readonly robotModel: RobotModelId;
	readonly levelId: SimulatorLevelId;
	readonly cameraMode: SimulatorCameraMode;
	readonly engineMode: LocomotionEngineMode;
	readonly neuralGaitModelId: string;
	readonly neuralPoseModelId: string;
	readonly neuralMotions: readonly NeuralMotionCatalogItem[];
	readonly control: BodyControlConnectionState;
	readonly state?: RobotTelemetryState | undefined;
	readonly cameraPreviewDataUrl?: string | undefined;
	readonly micActive: boolean;
	readonly micSupported: boolean;
	readonly audio: SimulatorAudioState;
	readonly multiplayer: MultiplayerSnapshot;
	readonly commsMessages: readonly SimulatorCommsMessage[];
	readonly lastCommandLog: string;
	readonly availableClips: readonly string[];
	readonly lastError?: string | undefined;
};

export type WorkerInboundMessage =
	| {
			readonly type: "init";
			readonly baseUrl: string;
			readonly obstaclesMj: readonly ArenaBoxObstacle[];
			readonly collidersMj?: readonly ArenaCollider[] | undefined;
			readonly hfield?: ArenaHeightfield | undefined;
			readonly useDefaultFloorPlane?: boolean | undefined;
			readonly spawnMj: readonly [number, number, number];
	  }
	| {
			readonly type: "set-robot";
			readonly robotModel: RobotModelId;
			readonly obstaclesMj: readonly ArenaBoxObstacle[];
			readonly collidersMj?: readonly ArenaCollider[] | undefined;
			readonly hfield?: ArenaHeightfield | undefined;
			readonly useDefaultFloorPlane?: boolean | undefined;
			readonly spawnMj: readonly [number, number, number];
	  }
	| {
			readonly type: "set-level";
			readonly obstaclesMj: readonly ArenaBoxObstacle[];
			readonly collidersMj?: readonly ArenaCollider[] | undefined;
			readonly hfield?: ArenaHeightfield | undefined;
			readonly useDefaultFloorPlane?: boolean | undefined;
			readonly spawnMj: readonly [number, number, number];
	  }
	| {
			readonly type: "session-reset";
			readonly epoch: number;
			readonly welcomeJson?: string;
	  }
	| {
			readonly type: "session-close";
			readonly epoch: number;
	  }
	| {
			readonly type: "protocol-rx";
			readonly wire: string;
			readonly epoch: number;
	  }
	| {
			readonly type: "request-hello";
			readonly robotId: string;
			readonly token: string;
	  }
	| {
			readonly type: "set-media";
			readonly talking?: boolean;
			readonly capturing?: boolean;
			readonly micRms?: number;
			readonly micPeak?: number;
			readonly cameraReady?: boolean;
	  }
	| {
			readonly type: "wrench";
			readonly forceMj: readonly [number, number, number];
			readonly torqueMj: readonly [number, number, number];
			readonly durationMs: number;
	  }
	| {
			readonly type: "pin-joint";
			readonly jointIndex: number;
			readonly pinned: boolean;
	  }
	| { readonly type: "clear-pins" }
	| {
			readonly type: "reset-pose";
			readonly spawnMj?: readonly [number, number, number];
	  }
	| { readonly type: "record-start"; readonly label: string }
	| { readonly type: "record-stop" }
	| { readonly type: "set-engine"; readonly engine: LocomotionEngineMode }
	| {
			readonly type: "neural-walk";
			readonly forward: number;
			readonly lateral: number;
			readonly turn: number;
			readonly speed: number;
	  }
	| { readonly type: "neural-pose"; readonly motionId: string }
	| { readonly type: "neural-stop"; readonly detach?: boolean }
	| {
			readonly type: "mic-gate";
			readonly open: boolean;
			readonly wakeWord?: boolean;
	  }
	| {
			readonly type: "mic-frame";
			readonly pcm: ArrayBuffer;
	  }
	| {
			readonly type: "camera-frame";
			readonly origin: "stream" | "request" | "audio";
			readonly originId: number;
			readonly res: string;
			readonly frameCompletedUs: number;
			readonly bootId: number;
			readonly jpeg: ArrayBuffer;
	  };

export type WorkerOutboundMessage =
	| {
			readonly type: "ready";
			readonly robotModel?: RobotModelId;
			readonly helloCommands: readonly string[];
			readonly neuralGaitModelId: string;
			readonly neuralPoseModelId: string;
			readonly neuralMotions: readonly NeuralMotionCatalogItem[];
	  }
	| {
			readonly type: "robot-ready";
			readonly robotModel: RobotModelId;
			readonly availableClips: readonly string[];
			readonly neuralGaitModelId: string;
			readonly neuralPoseModelId: string;
			readonly neuralMotions: readonly NeuralMotionCatalogItem[];
	  }
	| {
			readonly type: "error";
			readonly message: string;
	  }
	| {
			readonly type: "hello";
			readonly wire: string;
	  }
	| {
			readonly type: "state";
			readonly state: RobotTelemetryState;
	  }
	| {
			readonly type: "face";
			readonly width: number;
			readonly height: number;
			readonly rgba: ArrayBuffer;
	  }
	| {
			readonly type: "protocol-tx";
			readonly messages: readonly string[];
	  }
	| {
			readonly type: "protocol-packet";
			readonly preText?: string;
			readonly binary: ArrayBuffer;
			readonly postText?: string;
	  }
	| {
			readonly type: "media-action";
			readonly action: Record<string, unknown>;
	  }
	| {
			readonly type: "recording-export";
			readonly label: string;
			readonly steps: number;
			readonly jsonl: string;
			readonly summary: Record<string, unknown>;
	  };

export type V3PhysicsConfig = {
	readonly schemaVersion: number;
	readonly model: string;
	readonly geometryId: string;
	readonly physicsHz: number;
	readonly controlHz: number;
	readonly standingRootHeightM: number;
	readonly torqueNm: number;
	readonly motorNoLoadSpeedRadS: number;
	readonly jointNames: readonly string[];
	readonly referenceJointDeg: readonly number[];
	readonly jointLimitsMinDeg: readonly number[];
	readonly jointLimitsMaxDeg: readonly number[];
	readonly initQpos: readonly number[];
	readonly qadr: readonly number[];
	readonly vadr: readonly number[];
	readonly torsoBodyId: number;
	readonly floorGeomId: number;
	readonly footGeoms: readonly string[];
	readonly footGeomIds: readonly number[];
	readonly gyroSensorAdr: number;
	readonly accelSensorAdr: number;
};

/**
 * Exact SO(3) mapping from MuJoCo (+X fwd, +Y left, +Z up)
 * to Three.js (+Z fwd, +X left, +Y up):
 *   (x_mj, y_mj, z_mj) -> (y_mj, z_mj, x_mj)
 */
export function mujocoPositionToThree(
	posMj: readonly [number, number, number],
): readonly [number, number, number] {
	return [posMj[1], posMj[2], posMj[0]];
}

export function mujocoQuaternionToThreeXyzw(
	quatWxyz: readonly [number, number, number, number],
): readonly [number, number, number, number] {
	const [w, x, y, z] = quatWxyz;
	return [y, z, x, w];
}

export function threePositionToMujoco(
	posThree: readonly [number, number, number],
): readonly [number, number, number] {
	return [posThree[2], posThree[0], posThree[1]];
}

export const ORBIT_PITCH_MIN_RAD = -1.42; // ~ -81.4 deg (camera near ground looking straight up)
export const ORBIT_PITCH_MAX_RAD = 1.48; // ~ +84.8 deg (top-down bird's-eye looking down)
export const ORBIT_GROUND_CLEARANCE_M = 0.035;

export type OrbitCameraPose = {
	readonly position: readonly [number, number, number];
	readonly lookTarget: readonly [number, number, number];
};

/**
 * Compute C^0-position and C^inf-orientation continuous Orbit camera pose across
 * both downward (`pitchRad > 0`) and upward (`pitchRad < 0`) angles.
 *
 * When `pitchRad` goes negative near the floor (`rawY < minCamY`), the camera stays
 * grounded at `minCamY` at its floor-touch horizontal radius instead of clipping
 * below the floor or sliding into the robot mesh, while tilting its gaze smoothly
 * upward up to +81.4 deg into the sky.
 */
export function computeOrbitCameraPose(
	target: readonly [number, number, number],
	yawRad: number,
	pitchRad: number,
	distanceM: number,
): OrbitCameraPose {
	const clampedPitch = Math.max(
		ORBIT_PITCH_MIN_RAD,
		Math.min(ORBIT_PITCH_MAX_RAD, pitchRad),
	);
	const d = Math.max(0.22, Math.min(28, distanceM));
	const cosPitch = Math.cos(clampedPitch);
	const sinPitch = Math.sin(clampedPitch);
	const sinYaw = Math.sin(yawRad);
	const cosYaw = Math.cos(yawRad);

	const minCamY = Math.min(ORBIT_GROUND_CLEARANCE_M, target[1]);
	const rawCamY = target[1] + d * sinPitch;

	let horizRadius = d * cosPitch;
	let camY = rawCamY;
	if (rawCamY < minCamY) {
		camY = minCamY;
		const sinTouch = Math.max(-1, Math.min(0, (minCamY - target[1]) / d));
		horizRadius = d * Math.sqrt(Math.max(0, 1 - sinTouch * sinTouch));
	}

	const camX = target[0] + horizRadius * sinYaw;
	const camZ = target[2] + horizRadius * cosYaw;

	return {
		position: [camX, camY, camZ],
		lookTarget: [
			camX - cosPitch * sinYaw,
			camY - sinPitch,
			camZ - cosPitch * cosYaw,
		],
	};
}

export function cameraResolutionDimensions(resName: string): {
	readonly width: number;
	readonly height: number;
} {
	switch (resName.toUpperCase()) {
		case "VGA":
			return { width: 640, height: 480 };
		case "SVGA":
			return { width: 800, height: 600 };
		case "XGA":
			return { width: 1024, height: 768 };
		case "960P":
			return { width: 1280, height: 960 };
		case "FHD":
			return { width: 1920, height: 1080 };
		default:
			return { width: 320, height: 240 };
	}
}

/**
 * Encode a protocol-v1 binary WebSocket frame:
 *   [frame_type: uint8][counter: uint32 LE][payload...]
 */
export function encodeProtocolBinaryFrame(
	frameType: number,
	counter: number,
	payload: Uint8Array,
): Uint8Array {
	const out = new Uint8Array(5 + payload.byteLength);
	const view = new DataView(out.buffer);
	view.setUint8(0, frameType & 0xff);
	view.setUint32(1, counter >>> 0, true);
	out.set(payload, 5);
	return out;
}

export function decodeProtocolBinaryFrame(buffer: ArrayBuffer):
	| {
			readonly frameType: number;
			readonly counter: number;
			readonly payload: Uint8Array;
	  }
	| undefined {
	if (buffer.byteLength < 5) {
		return undefined;
	}
	const view = new DataView(buffer);
	return {
		frameType: view.getUint8(0),
		counter: view.getUint32(1, true),
		payload: new Uint8Array(buffer, 5),
	};
}

export type SimulatorMultiplayerLaunchMode = "solo" | "host" | "join";

export type BodyControlLaunchBundle = {
	readonly bc?: string;
	readonly robotId?: string;
	readonly token?: string;
	readonly model?: RobotModelId;
	readonly level?: SimulatorLevelId;
	readonly mp?: SimulatorMultiplayerLaunchMode;
	readonly room?: string;
	readonly name?: string;
};

export type SimulatorLaunchConfig = BodyControlLaunchBundle & {
	readonly shouldScrubHash: boolean;
};

const VALID_ROBOT_MODELS = new Set<RobotModelId>(["v1", "v2", "v3"]);
const VALID_LEVEL_IDS = new Set<SimulatorLevelId>([
	"v2_lab",
	"observatory",
	"yggdrasil",
	"miranda",
	"solitude",
	"sci-fi-room",
]);

function isPrivateOrLoopbackHost(hostname: string): boolean {
	const h = hostname.toLowerCase();
	if (h === "localhost" || h === "127.0.0.1" || h === "::1" || h === "[::1]") {
		return true;
	}
	if (h.startsWith("10.") || h.startsWith("192.168.")) {
		return true;
	}
	const m = /^172\.(\d{1,3})\./.exec(h);
	if (m) {
		const second = Number(m[1]);
		return second >= 16 && second <= 31;
	}
	return false;
}

/**
 * Normalize a user-supplied or launched Body Control endpoint into a canonical
 * `ws://.../robot` or `wss://.../robot` WebSocket URL.
 */
export function normalizeBodyControlUrl(rawInput: string): string {
	const trimmed = rawInput.trim();
	if (!trimmed) {
		return "";
	}
	let candidate = trimmed;
	if (candidate.startsWith("http://")) {
		candidate = `ws://${candidate.slice("http://".length)}`;
	} else if (candidate.startsWith("https://")) {
		candidate = `wss://${candidate.slice("https://".length)}`;
	} else if (
		!candidate.startsWith("ws://") &&
		!candidate.startsWith("wss://")
	) {
		const slashIdx = candidate.indexOf("/");
		const authority = slashIdx >= 0 ? candidate.slice(0, slashIdx) : candidate;
		const rest = slashIdx >= 0 ? candidate.slice(slashIdx) : "";
		const hostOnly = authority.replace(/:\d+$/, "");
		const hasPort = /:\d+$/.test(authority);
		if (isPrivateOrLoopbackHost(hostOnly)) {
			candidate = `ws://${hasPort ? authority : `${authority}:8790`}${rest}`;
		} else {
			candidate = `wss://${authority}${rest}`;
		}
	}
	try {
		const parsed = new URL(candidate);
		if (parsed.protocol !== "ws:" && parsed.protocol !== "wss:") {
			return trimmed;
		}
		if (!parsed.pathname || parsed.pathname === "/") {
			parsed.pathname = "/robot";
		}
		return parsed.toString();
	} catch {
		return trimmed;
	}
}

function fromBase64UrlUtf8(encoded: string): string | undefined {
	try {
		const padded = encoded
			.replace(/-/g, "+")
			.replace(/_/g, "/")
			.padEnd(Math.ceil(encoded.length / 4) * 4, "=");
		if (typeof Buffer !== "undefined") {
			return Buffer.from(padded, "base64").toString("utf-8");
		}
		const bin = globalThis.atob(padded);
		const bytes = new Uint8Array(bin.length);
		for (let i = 0; i < bin.length; i += 1) {
			bytes[i] = bin.charCodeAt(i);
		}
		return new TextDecoder().decode(bytes);
	} catch {
		return undefined;
	}
}

export function encodeBodyControlPairingCode(
	bundle: BodyControlLaunchBundle,
): string {
	const json = JSON.stringify(bundle);
	let b64: string;
	if (typeof Buffer !== "undefined") {
		b64 = Buffer.from(json, "utf-8").toString("base64");
	} else {
		const bytes = new TextEncoder().encode(json);
		let bin = "";
		for (const byte of bytes) {
			bin += String.fromCharCode(byte);
		}
		b64 = globalThis.btoa(bin);
	}
	const urlSafe = b64
		.replace(/\+/g, "-")
		.replace(/\//g, "_")
		.replace(/=+$/, "");
	return `ainekio-pair:${urlSafe}`;
}

function sanitizeBundleRecord(
	raw: Record<string, unknown>,
): BodyControlLaunchBundle {
	const bc =
		typeof raw.bc === "string" && raw.bc.trim()
			? normalizeBodyControlUrl(raw.bc)
			: undefined;
	const robotId =
		typeof raw.robotId === "string" && raw.robotId.trim()
			? raw.robotId.trim().slice(0, 64)
			: undefined;
	const token =
		typeof raw.token === "string" && raw.token.trim()
			? raw.token.trim()
			: undefined;
	const model =
		typeof raw.model === "string" &&
		VALID_ROBOT_MODELS.has(raw.model as RobotModelId)
			? (raw.model as RobotModelId)
			: undefined;
	const level =
		typeof raw.level === "string" &&
		VALID_LEVEL_IDS.has(raw.level as SimulatorLevelId)
			? (raw.level as SimulatorLevelId)
			: undefined;
	const mpRaw = typeof raw.mp === "string" ? raw.mp.trim().toLowerCase() : "";
	const mp: SimulatorMultiplayerLaunchMode | undefined =
		mpRaw === "host" || mpRaw === "join" || mpRaw === "solo"
			? mpRaw
			: undefined;
	const room =
		typeof raw.room === "string" && raw.room.trim()
			? raw.room.trim()
			: undefined;
	const name =
		typeof raw.name === "string" && raw.name.trim()
			? raw.name.trim().slice(0, 24)
			: undefined;

	return {
		...(bc ? { bc } : {}),
		...(robotId ? { robotId } : {}),
		...(token ? { token } : {}),
		...(model ? { model } : {}),
		...(level ? { level } : {}),
		...(mp ? { mp } : {}),
		...(room ? { room } : {}),
		...(name ? { name } : {}),
	};
}

/**
 * Decode either an `ainekio-pair:<base64url>` string OR a full simulator launch
 * URL containing `#bc=...&token=...` / `?bc=...`.
 */
export function decodeBodyControlPairingCode(
	input: string,
): BodyControlLaunchBundle | undefined {
	const trimmed = input.trim();
	if (!trimmed) {
		return undefined;
	}
	if (trimmed.startsWith("ainekio-pair:")) {
		const decoded = fromBase64UrlUtf8(trimmed.slice("ainekio-pair:".length));
		if (!decoded) {
			return undefined;
		}
		try {
			const parsed = JSON.parse(decoded) as unknown;
			if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
				return undefined;
			}
			const clean = sanitizeBundleRecord(parsed as Record<string, unknown>);
			return Object.keys(clean).length > 0 ? clean : undefined;
		} catch {
			return undefined;
		}
	}
	if (
		trimmed.startsWith("http://") ||
		trimmed.startsWith("https://") ||
		trimmed.startsWith("#")
	) {
		try {
			if (trimmed.startsWith("#")) {
				const cfg = parseSimulatorLaunchParams("", trimmed);
				const { shouldScrubHash: _scrub, ...rest } = cfg;
				return Object.keys(rest).length > 0 ? rest : undefined;
			}
			const u = new URL(trimmed);
			const cfg = parseSimulatorLaunchParams(u.search, u.hash);
			const { shouldScrubHash: _scrub, ...rest } = cfg;
			return Object.keys(rest).length > 0 ? rest : undefined;
		} catch {
			return undefined;
		}
	}
	return undefined;
}

export function parseSimulatorLaunchParams(
	search: string,
	hash: string,
): SimulatorLaunchConfig {
	const qParams = new URLSearchParams(
		search.startsWith("?") ? search.slice(1) : search,
	);
	const hParams = new URLSearchParams(
		hash.startsWith("#") ? hash.slice(1) : hash,
	);

	const merged: Record<string, unknown> = {};
	const pairFromQuery = qParams.get("pair");
	const pairFromHash = hParams.get("pair");
	for (const pairCode of [pairFromQuery, pairFromHash]) {
		if (pairCode) {
			const decoded = decodeBodyControlPairingCode(
				pairCode.startsWith("ainekio-pair:")
					? pairCode
					: `ainekio-pair:${pairCode}`,
			);
			if (decoded) {
				Object.assign(merged, decoded);
			}
		}
	}

	for (const params of [qParams, hParams]) {
		for (const key of [
			"bc",
			"robotId",
			"token",
			"model",
			"level",
			"mp",
			"room",
			"name",
		]) {
			const val = params.get(key);
			if (val !== null && val.trim() !== "") {
				merged[key] = val;
			}
		}
	}

	const clean = sanitizeBundleRecord(merged);
	const shouldScrubHash = Boolean(
		hParams.has("token") || hParams.has("pair") || hParams.has("bc"),
	);
	return {
		...clean,
		shouldScrubHash,
	};
}

declare const __SIM_ASSET_HASHES__:
	| Readonly<Record<string, string>>
	| undefined;

/**
 * Append a build-time per-file content hash (`?v=<sha256>`) to static
 * `/sim/*` and `/assets/robots/*` URLs so browsers and Cloudflare CDN keep
 * long cache lifetimes for unchanged files while invalidating immediately
 * whenever a WASM, policy binary, XML, level bundle, or GLB changes.
 */
export function versionedAssetUrl(
	assetPath: string,
	baseUrl = "",
	hashes?: Readonly<Record<string, string>>,
): string {
	const map =
		hashes ??
		(typeof __SIM_ASSET_HASHES__ !== "undefined"
			? __SIM_ASSET_HASHES__
			: undefined);
	const isAbsolute = /^https?:\/\//i.test(assetPath);
	const normalizedPrefix = baseUrl.endsWith("/")
		? baseUrl.slice(0, -1)
		: baseUrl;
	const fullUrl = isAbsolute
		? assetPath
		: `${normalizedPrefix}${assetPath.startsWith("/") ? "" : "/"}${assetPath}`;

	if (!map) {
		return fullUrl;
	}

	let lookupPath: string;
	if (isAbsolute) {
		try {
			lookupPath = new URL(assetPath).pathname;
		} catch {
			return fullUrl;
		}
	} else {
		const pathOnly = assetPath.split(/[?#]/, 1)[0] ?? assetPath;
		lookupPath = pathOnly.startsWith("/") ? pathOnly : `/${pathOnly}`;
	}

	const hash = map[lookupPath];
	if (!hash || /[?&]v=/.test(fullUrl)) {
		return fullUrl;
	}
	const hashIdx = fullUrl.indexOf("#");
	const basePart = hashIdx >= 0 ? fullUrl.slice(0, hashIdx) : fullUrl;
	const fragPart = hashIdx >= 0 ? fullUrl.slice(hashIdx) : "";
	const sep = basePart.includes("?") ? "&" : "?";
	return `${basePart}${sep}v=${hash}${fragPart}`;
}

/**
 * Returns true when a `/robot` WebSocket close code represents an intentional
 * session takeover (`4000`) or non-recoverable protocol/auth error (`4001`,
 * `4002`, `1002`, `1008`) that must NOT trigger automatic reconnect loops.
 */
export function isNonRetryableBodyControlCloseCode(code: number): boolean {
	return (
		code === 4000 ||
		code === 4001 ||
		code === 4002 ||
		code === 1002 ||
		code === 1008
	);
}

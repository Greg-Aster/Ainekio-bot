import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {
	type MultiplayerTransportPort,
	type MultiplayerWireMessage,
	createMultiplayerSession,
	normalizeRoomName,
} from "../src/multiplayer/index";
import {
	ORBIT_GROUND_CLEARANCE_M,
	ORBIT_PITCH_MAX_RAD,
	ORBIT_PITCH_MIN_RAD,
	PROTOCOL_BIN_CAMERA_JPEG,
	PROTOCOL_BIN_MIC_PCM,
	PROTOCOL_BIN_SPEAKER_PCM,
	cameraResolutionDimensions,
	computeOrbitCameraPose,
	decodeBodyControlPairingCode,
	decodeProtocolBinaryFrame,
	encodeBodyControlPairingCode,
	encodeProtocolBinaryFrame,
	isNonRetryableBodyControlCloseCode,
	mujocoPositionToThree,
	mujocoQuaternionToThreeXyzw,
	normalizeBodyControlUrl,
	parseSimulatorLaunchParams,
	threePositionToMujoco,
	versionedAssetUrl,
} from "../src/sim/contracts";
import { SIMULATOR_LEVELS, getSimulatorLevel } from "../src/sim/levels";
import {
	type NeuralGaitManifest,
	NeuralGaitPolicy,
	type NeuralPoseLibrary,
	type NeuralPoseManifest,
	NeuralPosePolicy,
	type V1NeuralGaitManifest,
	V1NeuralGaitPolicy,
	type V1NeuralPoseManifest,
	V1NeuralPosePolicy,
	type V3NeuralGaitManifest,
	V3NeuralGaitPolicy,
	type V3NeuralPoseManifest,
	V3NeuralPosePolicy,
} from "../src/sim/neuralPolicies";
import {
	type PoseManifoldConfig,
	PoseManifoldRuntime,
} from "../src/sim/poseManifold";
import {
	type StorageLike,
	clearBodyControlSessionToken,
	loadSavedBodyControlSettings,
	saveBodyControlSessionToken,
	saveBodyControlSettings,
} from "../src/sim/simulatorController";
import { WORLD_SFX_CATALOG } from "../src/viewport/worldAudio";

const APP_ROOT = path.resolve(import.meta.dirname, "..");

function testCoordinateTransforms(): void {
	const mjPos: readonly [number, number, number] = [1.25, -0.5, 0.35];
	const threePos = mujocoPositionToThree(mjPos);
	assert.deepEqual(threePos, [-0.5, 0.35, 1.25]);
	assert.deepEqual(threePositionToMujoco(threePos), mjPos);

	const qThree = mujocoQuaternionToThreeXyzw([0.85, 0.1, 0.2, 0.3]);
	assert.deepEqual(qThree, [0.2, 0.3, 0.1, 0.85]);
}

function testProtocolBinaryCodecs(): void {
	for (const frameType of [
		PROTOCOL_BIN_MIC_PCM,
		PROTOCOL_BIN_CAMERA_JPEG,
		PROTOCOL_BIN_SPEAKER_PCM,
	]) {
		const payload = new Uint8Array([0xff, 0xd8, 0x01, 0x02, 0x03]);
		const encoded = encodeProtocolBinaryFrame(frameType, 42, payload);
		assert.equal(encoded.byteLength, 5 + payload.byteLength);
		const decoded = decodeProtocolBinaryFrame(encoded.buffer as ArrayBuffer);
		assert.ok(decoded);
		assert.equal(decoded.frameType, frameType);
		assert.equal(decoded.counter, 42);
		assert.deepEqual(Array.from(decoded.payload), Array.from(payload));
	}
	assert.equal(decodeProtocolBinaryFrame(new ArrayBuffer(3)), undefined);
}

function testCameraResolutions(): void {
	assert.deepEqual(cameraResolutionDimensions("QVGA"), {
		width: 320,
		height: 240,
	});
	assert.deepEqual(cameraResolutionDimensions("VGA"), {
		width: 640,
		height: 480,
	});
	assert.deepEqual(cameraResolutionDimensions("XGA"), {
		width: 1024,
		height: 768,
	});
}

function testDetachedLevelsAndAssets(): void {
	assert.equal(SIMULATOR_LEVELS.length, 6);
	const expectedIds = [
		"v2_lab",
		"observatory",
		"yggdrasil",
		"miranda",
		"solitude",
		"sci-fi-room",
	];
	assert.deepEqual(
		SIMULATOR_LEVELS.map((l) => l.id),
		expectedIds,
	);

	// Verify zero Megameal lore / story links in level catalog or exported level bundles
	const serialized = JSON.stringify(SIMULATOR_LEVELS).toLowerCase();
	assert.equal(serialized.includes("megameal"), false);
	assert.equal(serialized.includes("story_note"), false);
	assert.equal(serialized.includes("/posts/"), false);

	// Verify lazy bundles for all 6 simulator worlds + legacy simple-polygon constraints
	for (const id of [
		"v2_lab",
		"observatory",
		"yggdrasil",
		"miranda",
		"solitude",
		"sci-fi-room",
	] as const) {
		const lvl = getSimulatorLevel(id);
		assert.ok(lvl.lazyBundleUrl, `Expected lazyBundleUrl on ${id}`);
		const bundlePath = path.join(APP_ROOT, "public", lvl.lazyBundleUrl);
		assert.ok(fs.existsSync(bundlePath), `Missing lazy bundle: ${bundlePath}`);
		const raw = fs.readFileSync(bundlePath, "utf8");
		assert.equal(raw.toLowerCase().includes("megameal"), false);
		assert.equal(raw.toLowerCase().includes("story-marker"), false);
		const parsed = JSON.parse(raw) as {
			readonly primitives: unknown[];
			readonly glbInstances: unknown[];
			readonly colliders: unknown[];
			readonly hfield?: { readonly url: string };
		};
		if (id === "yggdrasil" || id === "solitude") {
			// Legacy simple-polygon worlds must use primitives only (zero heavy GLBs)
			assert.equal(
				parsed.glbInstances.length,
				0,
				`${id} Legacy must use simple polygons instead of complex GLBs`,
			);
			assert.ok(
				parsed.primitives.length >= 12,
				`${id} Legacy missing simple-polygon primitives`,
			);
			assert.ok(
				parsed.colliders.length >= 10,
				`${id} Legacy missing MuJoCo colliders`,
			);
		}
		if (id === "solitude") {
			assert.ok(
				parsed.hfield?.url,
				"Solitude missing rolling terrain MuJoCo heightfield",
			);
		}
		if (id === "observatory") {
			assert.ok(parsed.hfield?.url, "Observatory missing MuJoCo heightfield");
			assert.equal(
				parsed.glbInstances.length,
				16,
				"Observatory should reference all 16 terrain chunks",
			);
		}
	}

	// Verify all required static WASM, MJCF, physics config, policies, heightfield, and assets exist and are < 25 MB
	const requiredStaticFiles = [
		"public/sim/mujoco_wasm.js",
		"public/sim/ainekio-v2-firmware.mjs",
		"public/sim/ainekio-v2-firmware.wasm",
		"public/sim/ainekio-v2-locomotion.xml",
		"public/sim/v2-physics-config.json",
		"public/sim/ainekio-v1-locomotion.xml",
		"public/sim/v1-physics-config.json",
		"public/sim/ainekio-v3-locomotion.xml",
		"public/sim/v3-physics-config.json",
		"public/sim/policies/neural-gait.json",
		"public/sim/policies/neural-gait.bin",
		"public/sim/policies/neural-pose.json",
		"public/sim/policies/neural-pose.bin",
		"public/sim/policies/v1-neural-gait.json",
		"public/sim/policies/v1-neural-gait.bin",
		"public/sim/policies/v1-neural-pose.json",
		"public/sim/policies/v1-neural-pose.bin",
		"public/sim/policies/v3-neural-gait.json",
		"public/sim/policies/v3-neural-gait.bin",
		"public/sim/policies/v3-neural-pose.json",
		"public/sim/policies/v3-neural-pose.bin",
		"public/sim/policies/pose-manifold.json",
		"public/sim/policies/neural-pose-library.json",
		"public/favicon.ico",
		"public/favicon.svg",
		"public/sim/levels/v2-lab.level.json",
		"public/sim/levels/observatory.level.json",
		"public/sim/levels/observatory.hfield.bin",
		"public/sim/levels/yggdrasil.level.json",
		"public/sim/levels/miranda.level.json",
		"public/sim/levels/solitude.level.json",
		"public/sim/levels/solitude.hfield.bin",
		"public/sim/levels/sci-fi-room.level.json",
		"public/assets/robots/ainekio-v2.glb",
		"public/assets/robots/ainekio-v1.glb",
		"public/assets/robots/ainekio-v3.glb",
		"public/assets/levels/observatory/chunk_0_0_LOD0.glb",
		"public/assets/skyboxes/classic/px.webp",
		"public/assets/skyboxes/observatory/px.webp",
	];
	const MAX_CF_PAGES_BYTES = 25 * 1024 * 1024;
	// Verify every level soundtrack, spatial audio region, and UI/portal SFX exists on disk
	for (const lvl of SIMULATOR_LEVELS) {
		assert.ok(lvl.audio?.track, `Level ${lvl.id} missing ambient audio track`);
		const trackPath = path.join(APP_ROOT, "public", lvl.audio.track);
		assert.ok(
			fs.existsSync(trackPath),
			`Missing level audio track for ${lvl.id}: ${lvl.audio.track}`,
		);
		const trackStat = fs.statSync(trackPath);
		assert.ok(trackStat.size > 0 && trackStat.size < MAX_CF_PAGES_BYTES);
		for (const region of lvl.audio.regions ?? []) {
			const regPath = path.join(APP_ROOT, "public", region.track);
			assert.ok(
				fs.existsSync(regPath),
				`Missing spatial audio track for ${lvl.id}/${region.id}: ${region.track}`,
			);
		}
	}
	for (const [sfxId, sfx] of Object.entries(WORLD_SFX_CATALOG)) {
		const sfxPath = path.join(APP_ROOT, "public", sfx.src);
		assert.ok(fs.existsSync(sfxPath), `Missing SFX asset ${sfxId}: ${sfx.src}`);
		assert.ok(fs.statSync(sfxPath).size > 0, `Empty SFX asset ${sfxId}`);
	}

	for (const relPath of requiredStaticFiles) {
		const fullPath = path.join(APP_ROOT, relPath);
		assert.ok(fs.existsSync(fullPath), `Missing static asset: ${relPath}`);
		const stat = fs.statSync(fullPath);
		assert.ok(stat.size > 0, `Empty static asset: ${relPath}`);
		assert.ok(
			stat.size < MAX_CF_PAGES_BYTES,
			`Asset exceeds 25 MB Cloudflare Pages limit: ${relPath} (${stat.size} bytes)`,
		);
	}
}

function readFloat32File(relPath: string): Float32Array {
	const buf = fs.readFileSync(path.join(APP_ROOT, relPath));
	const copy = new Uint8Array(buf.byteLength);
	copy.set(buf);
	return new Float32Array(copy.buffer);
}

function testNeuralPoliciesAndManifoldParity(): void {
	const gaitManifest = JSON.parse(
		fs.readFileSync(
			path.join(APP_ROOT, "public/sim/policies/neural-gait.json"),
			"utf8",
		),
	) as NeuralGaitManifest;
	const gaitPolicy = new NeuralGaitPolicy(
		gaitManifest,
		readFloat32File("public/sim/policies/neural-gait.bin"),
	);
	assert.ok((gaitManifest.goldenTests?.length ?? 0) >= 3);
	for (const tc of gaitManifest.goldenTests ?? []) {
		const got = gaitPolicy.predictAction(tc.obs);
		assert.equal(got.length, 12);
		for (let i = 0; i < 12; i += 1) {
			const diff = Math.abs((got[i] ?? 0) - (tc.action[i] ?? 0));
			assert.ok(
				diff < 1e-5,
				`Neural Gait golden test seed=${tc.seed} idx=${i} diff=${diff}`,
			);
		}
	}

	const poseManifest = JSON.parse(
		fs.readFileSync(
			path.join(APP_ROOT, "public/sim/policies/neural-pose.json"),
			"utf8",
		),
	) as NeuralPoseManifest;
	const posePolicy = new NeuralPosePolicy(
		poseManifest,
		readFloat32File("public/sim/policies/neural-pose.bin"),
	);
	assert.ok((poseManifest.goldenTests?.length ?? 0) >= 3);
	for (const tc of poseManifest.goldenTests ?? []) {
		const got = posePolicy.predictAction(tc.obs);
		assert.equal(got.length, 12);
		for (let i = 0; i < 12; i += 1) {
			const diff = Math.abs((got[i] ?? 0) - (tc.action[i] ?? 0));
			assert.ok(
				diff < 1e-5,
				`Neural Pose golden test seed=${tc.seed} idx=${i} diff=${diff}`,
			);
		}
	}

	const manifoldCfg = JSON.parse(
		fs.readFileSync(
			path.join(APP_ROOT, "public/sim/policies/pose-manifold.json"),
			"utf8",
		),
	) as PoseManifoldConfig;
	assert.equal(
		manifoldCfg.geometryId,
		gaitManifest.geometryId,
		"PoseManifold geometryId must match V2 Neural Gait geometryId so firmware WASM accepts both",
	);
	assert.equal(
		poseManifest.geometryId,
		gaitManifest.geometryId,
		"Neural Pose geometryId must match V2 Neural Gait geometryId",
	);
	const manifold = new PoseManifoldRuntime(manifoldCfg);
	assert.ok((manifoldCfg.goldenTests?.length ?? 0) >= 3);
	for (const tc of manifoldCfg.goldenTests ?? []) {
		const proj = manifold.projectAnglesDeg(tc.inputDeg);
		for (let i = 0; i < 12; i += 1) {
			const dDeg = Math.abs((proj.deg[i] ?? 0) - (tc.projectedDeg[i] ?? 0));
			assert.ok(dDeg < 1e-3, `PoseManifold projectAnglesDeg diff=${dDeg}`);
			const dFoot = Math.abs((proj.footNorm[i] ?? 0) - (tc.footNorm[i] ?? 0));
			assert.ok(dFoot < 1e-4, `PoseManifold footNorm diff=${dFoot}`);
		}
		const prevRad = tc.prevQDeg.map((d) => (d * Math.PI) / 180);
		const stepped = manifold.stepHostCommand(
			tc.footNorm,
			prevRad,
			tc.speedScale,
		);
		for (let i = 0; i < 12; i += 1) {
			const nextDeg = ((stepped.nextQRad[i] ?? 0) * 180) / Math.PI;
			const dNext = Math.abs(nextDeg - (tc.nextQDeg[i] ?? 0));
			assert.ok(dNext < 1e-3, `PoseManifold stepHostCommand deg diff=${dNext}`);
			const dMm = Math.abs((stepped.feetMm[i] ?? 0) - (tc.feetMm[i] ?? 0));
			assert.ok(dMm < 1e-3, `PoseManifold stepHostCommand feetMm diff=${dMm}`);
		}
	}

	const poseLib = JSON.parse(
		fs.readFileSync(
			path.join(APP_ROOT, "public/sim/policies/neural-pose-library.json"),
			"utf8",
		),
	) as NeuralPoseLibrary;
	assert.ok(poseLib.motions.length >= 12);
	for (const required of ["stand", "sit", "wave", "bow", "dance", "stretch"]) {
		assert.ok(
			poseLib.motions.some((m) => m.id === required),
			`Missing curated Neural Pose motion: ${required}`,
		);
	}

	// Verify Ainekio V1 (8-Servo) Neural Gait & Neural Pose ONNX parity (< 1e-5)
	const v1GaitManifest = JSON.parse(
		fs.readFileSync(
			path.join(APP_ROOT, "public/sim/policies/v1-neural-gait.json"),
			"utf8",
		),
	) as V1NeuralGaitManifest;
	const v1GaitPolicy = new V1NeuralGaitPolicy(
		v1GaitManifest,
		readFloat32File("public/sim/policies/v1-neural-gait.bin"),
	);
	assert.ok((v1GaitManifest.goldenTests?.length ?? 0) >= 3);
	for (const tc of v1GaitManifest.goldenTests ?? []) {
		const got = v1GaitPolicy.predictAction(tc.obs);
		assert.equal(got.length, 8);
		for (let i = 0; i < 8; i += 1) {
			const diff = Math.abs((got[i] ?? 0) - (tc.action[i] ?? 0));
			assert.ok(
				diff < 1e-5,
				`V1 Neural Gait golden test seed=${tc.seed} idx=${i} diff=${diff}`,
			);
		}
	}

	const v1PoseManifest = JSON.parse(
		fs.readFileSync(
			path.join(APP_ROOT, "public/sim/policies/v1-neural-pose.json"),
			"utf8",
		),
	) as V1NeuralPoseManifest;
	const v1PosePolicy = new V1NeuralPosePolicy(
		v1PoseManifest,
		readFloat32File("public/sim/policies/v1-neural-pose.bin"),
	);
	assert.ok((v1PoseManifest.goldenTests?.length ?? 0) >= 3);
	assert.ok(v1PoseManifest.motions.length >= 8);
	for (const tc of v1PoseManifest.goldenTests ?? []) {
		const got = v1PosePolicy.predictAction(tc.obs);
		assert.equal(got.length, 8);
		for (let i = 0; i < 8; i += 1) {
			const diff = Math.abs((got[i] ?? 0) - (tc.action[i] ?? 0));
			assert.ok(
				diff < 1e-5,
				`V1 Neural Pose golden test seed=${tc.seed} idx=${i} diff=${diff}`,
			);
		}
	}

	// Verify Ainekio V3 (12-Servo Komatsu Option A-1) Neural Gait & Neural Pose ONNX + IK parity (< 1e-5)
	const v3GaitManifest = JSON.parse(
		fs.readFileSync(
			path.join(APP_ROOT, "public/sim/policies/v3-neural-gait.json"),
			"utf8",
		),
	) as V3NeuralGaitManifest;
	assert.equal(
		v3GaitManifest.observationSchema,
		"ainekio-v3-neural-gait-v2-proprio",
	);
	assert.equal(v3GaitManifest.obsDim, 600);
	assert.equal(v3GaitManifest.featureDim, 50);
	assert.equal(v3GaitManifest.historySamples, 12);
	assert.equal(v3GaitManifest.actionSpace, "normalized-foot-offsets-v3-ik");
	assert.equal(v3GaitManifest.footActionScaleMm?.length, 3);
	assert.ok((v3GaitManifest.footActionScaleMm?.[0] ?? 0) > 0);
	const v3GaitPolicy = new V3NeuralGaitPolicy(
		v3GaitManifest,
		readFloat32File("public/sim/policies/v3-neural-gait.bin"),
	);
	assert.ok((v3GaitManifest.goldenTests?.length ?? 0) >= 3);
	for (const tc of v3GaitManifest.goldenTests ?? []) {
		const got = v3GaitPolicy.predictAction(tc.obs);
		assert.equal(got.length, 12);
		for (let i = 0; i < 12; i += 1) {
			const diff = Math.abs((got[i] ?? 0) - (tc.action[i] ?? 0));
			assert.ok(
				diff < 1e-5,
				`V3 Neural Gait golden test seed=${tc.seed} idx=${i} diff=${diff}`,
			);
		}
		if (tc.decodedJointDeg) {
			const decoded = v3GaitPolicy.actionToJointDeg(got);
			assert.equal(decoded.length, 12);
			for (let i = 0; i < 12; i += 1) {
				const dDeg = Math.abs((decoded[i] ?? 0) - (tc.decodedJointDeg[i] ?? 0));
				assert.ok(
					dDeg < 1e-3,
					`V3 Foot-Offset IK decode seed=${tc.seed} idx=${i} diff=${dDeg} deg (got=${decoded[i]}, expected=${tc.decodedJointDeg[i]})`,
				);
			}
		}
	}

	const v3PoseManifest = JSON.parse(
		fs.readFileSync(
			path.join(APP_ROOT, "public/sim/policies/v3-neural-pose.json"),
			"utf8",
		),
	) as V3NeuralPoseManifest;
	const v3PosePolicy = new V3NeuralPosePolicy(
		v3PoseManifest,
		readFloat32File("public/sim/policies/v3-neural-pose.bin"),
	);
	assert.ok((v3PoseManifest.goldenTests?.length ?? 0) >= 3);
	assert.ok(v3PoseManifest.motions.length >= 8);
	for (const tc of v3PoseManifest.goldenTests ?? []) {
		const got = v3PosePolicy.predictAction(tc.obs);
		assert.equal(got.length, 12);
		for (let i = 0; i < 12; i += 1) {
			const diff = Math.abs((got[i] ?? 0) - (tc.action[i] ?? 0));
			assert.ok(
				diff < 1e-5,
				`V3 Neural Pose golden test seed=${tc.seed} idx=${i} diff=${diff}`,
			);
		}
	}
}

function testOrbitCameraLookUpAndContinuity(): void {
	const target: readonly [number, number, number] = [0, 0.12, 0.02];
	const dist = 0.85;
	const yaw = 0.6;

	// 1. Downward / three-quarter orbit looks directly through orbitTarget
	const downPose = computeOrbitCameraPose(target, yaw, 0.36, dist);
	assert.ok(downPose.position[1] > target[1]);
	const toTargetY = target[1] - downPose.position[1];
	const rayY = downPose.lookTarget[1] - downPose.position[1];
	assert.ok(
		Math.abs(toTargetY / dist - rayY) < 1e-9,
		"Above-ground orbit ray must pass directly through orbitTarget",
	);

	// 2. Dragging pitch negative (looking up) tilts gaze upward into the sky (> +75 deg)
	//    while keeping camera height safely above ORBIT_GROUND_CLEARANCE_M
	const lookUpPose = computeOrbitCameraPose(
		target,
		yaw,
		ORBIT_PITCH_MIN_RAD,
		dist,
	);
	assert.equal(lookUpPose.position[1], ORBIT_GROUND_CLEARANCE_M);
	const upDirX = lookUpPose.lookTarget[0] - lookUpPose.position[0];
	const upDirY = lookUpPose.lookTarget[1] - lookUpPose.position[1];
	const upDirZ = lookUpPose.lookTarget[2] - lookUpPose.position[2];
	const upwardElevationDeg =
		(Math.atan2(upDirY, Math.hypot(upDirX, upDirZ)) * 180) / Math.PI;
	assert.ok(
		upwardElevationDeg > 80,
		`Expected >80 deg upward gaze in Orbit mode, got ${upwardElevationDeg}`,
	);

	// 3. Verify C^0 position continuity across the floor-touch pitch boundary
	const sinTouch = (ORBIT_GROUND_CLEARANCE_M - target[1]) / dist;
	const pitchTouch = Math.asin(sinTouch);
	const justAbove = computeOrbitCameraPose(
		target,
		yaw,
		pitchTouch + 1e-5,
		dist,
	);
	const justBelow = computeOrbitCameraPose(
		target,
		yaw,
		pitchTouch - 1e-5,
		dist,
	);
	for (let axis = 0; axis < 3; axis += 1) {
		assert.ok(
			Math.abs(
				(justAbove.position[axis] ?? 0) - (justBelow.position[axis] ?? 0),
			) < 1e-4,
			`Discontinuity on axis ${axis} across floor-touch boundary`,
		);
	}

	// 4. Verify top-down clamp stays below gimbal lock
	const topDown = computeOrbitCameraPose(
		target,
		yaw,
		ORBIT_PITCH_MAX_RAD + 1.0,
		dist,
	);
	assert.ok(topDown.position[1] > target[1] + 0.8);
}

class MockMpHostTransport implements MultiplayerTransportPort {
	readonly role = "host";
	readonly clients = new Map<string, MockMpClientTransport>();
	readonly messageListeners = new Set<
		(message: unknown, peerId?: string) => void
	>();
	readonly peerListListeners = new Set<(peerIds: readonly string[]) => void>();

	constructor(readonly peerId: string) {}

	send(): void {}

	broadcast(message: MultiplayerWireMessage): void {
		for (const client of this.clients.values()) {
			client.receive(message);
		}
	}

	onMessage(listener: (message: unknown, peerId?: string) => void): () => void {
		this.messageListeners.add(listener);
		return () => this.messageListeners.delete(listener);
	}

	onPeerListChanged(
		listener: (peerIds: readonly string[]) => void,
	): () => void {
		this.peerListListeners.add(listener);
		listener(this.connectedPeers());
		return () => this.peerListListeners.delete(listener);
	}

	connectedPeers(): readonly string[] {
		return [...this.clients.keys()].sort();
	}

	connect(client: MockMpClientTransport): void {
		this.clients.set(client.peerId, client);
		this.notifyPeerList();
	}

	disconnectClient(peerId: string): void {
		this.clients.delete(peerId);
		this.notifyPeerList();
	}

	receive(message: MultiplayerWireMessage, peerId: string): void {
		for (const listener of this.messageListeners) {
			listener(message, peerId);
		}
	}

	dispose(): void {
		for (const client of this.clients.values()) {
			client.notifyHostClosed();
		}
		this.clients.clear();
		this.messageListeners.clear();
		this.peerListListeners.clear();
	}

	private notifyPeerList(): void {
		for (const listener of this.peerListListeners) {
			listener(this.connectedPeers());
		}
	}
}

class MockMpClientTransport implements MultiplayerTransportPort {
	readonly role = "client";
	readonly messageListeners = new Set<
		(message: unknown, peerId?: string) => void
	>();
	readonly peerListListeners = new Set<(peerIds: readonly string[]) => void>();
	private connected = true;

	constructor(
		readonly peerId: string,
		readonly host: MockMpHostTransport,
	) {}

	send(message: MultiplayerWireMessage): void {
		if (this.connected) {
			this.host.receive(message, this.peerId);
		}
	}

	broadcast(message: MultiplayerWireMessage): void {
		this.send(message);
	}

	onMessage(listener: (message: unknown, peerId?: string) => void): () => void {
		this.messageListeners.add(listener);
		return () => this.messageListeners.delete(listener);
	}

	onPeerListChanged(
		listener: (peerIds: readonly string[]) => void,
	): () => void {
		this.peerListListeners.add(listener);
		listener(this.connectedPeers());
		return () => this.peerListListeners.delete(listener);
	}

	connectedPeers(): readonly string[] {
		return this.connected ? [this.host.peerId] : [];
	}

	receive(message: MultiplayerWireMessage): void {
		for (const listener of this.messageListeners) {
			listener(message, this.host.peerId);
		}
	}

	notifyHostClosed(): void {
		this.connected = false;
		for (const listener of this.peerListListeners) {
			listener([]);
		}
	}

	dispose(): void {
		this.connected = false;
		this.messageListeners.clear();
		this.peerListListeners.clear();
	}
}

function testMultiplayerSessionAndGameCompat(): void {
	assert.equal(normalizeRoomName("  Ainekio Lab! 01 "), "ainekio-lab-01");

	const hostSession = createMultiplayerSession({
		displayName: "Host-V2",
		timestamp: () => "2026-11-23T00:00:00.000Z",
	});
	const simClient = createMultiplayerSession({
		displayName: "Guest-V3",
		timestamp: () => "2026-11-23T00:00:01.000Z",
	});
	const gameClient = createMultiplayerSession({
		timestamp: () => "2026-11-23T00:00:02.000Z",
	});

	const hostTransport = new MockMpHostTransport("host-peer");
	const simTransport = new MockMpClientTransport("sim-peer", hostTransport);
	const gameTransport = new MockMpClientTransport("game-peer", hostTransport);

	hostSession.attachTransport({
		transport: hostTransport,
		roomName: "Shared Arena",
	});
	hostTransport.connect(simTransport);
	hostTransport.connect(gameTransport);
	simClient.attachTransport({
		transport: simTransport,
		roomName: "Shared Arena",
	});
	gameClient.attachTransport({
		transport: gameTransport,
		roomName: "Shared Arena",
	});

	// 1. In-session host publishes its own articulated robot pose to all clients
	hostSession.publishLocalPose({
		position: [0.5, 0.12, -1.2],
		rotation: [0, 0, 0, 1],
		tick: 1,
		robotModel: "v2",
		jointsDeg: [0, 10, -10, 0, 10, -10, 0, 10, -10, 0, 10, -10],
		levelId: "v2_lab",
	});
	assert.equal(simClient.snapshot().remotePlayers.length, 1);
	assert.equal(simClient.snapshot().remotePlayers[0]?.peerId, "host-peer");
	assert.equal(simClient.snapshot().remotePlayers[0]?.pose.robotModel, "v2");
	assert.equal(
		simClient.snapshot().remotePlayers[0]?.pose.displayName,
		"Host-V2",
	);

	// 2. game.megameal peer publishes a minimal pose (no robotModel) alongside simulator peer
	gameClient.publishLocalPose({
		position: [3, 1.5, 4],
		rotation: [0, 0, 0, 1],
		tick: 2,
	});
	simClient.publishLocalPose({
		position: [-1, 0.18, 2],
		rotation: [0, 0, 0, 1],
		tick: 3,
		robotModel: "v3",
		jointsDeg: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
		levelId: "v2_lab",
	});

	assert.equal(hostSession.snapshot().remotePlayers.length, 2);
	const gamePeerOnSim = simClient
		.snapshot()
		.remotePlayers.find((p) => p.peerId === "game-peer");
	assert.ok(gamePeerOnSim);
	assert.equal(gamePeerOnSim.pose.robotModel, undefined);
	assert.deepEqual(gamePeerOnSim.pose.position, [3, 1.5, 4]);

	// 3. Chat relays across host and both clients without duplication
	simClient.sendChat("hello from V3!");
	assert.equal(hostSession.snapshot().chatMessages.length, 1);
	assert.equal(
		gameClient.snapshot().chatMessages.at(-1)?.text,
		"hello from V3!",
	);
	assert.equal(simClient.snapshot().chatMessages.length, 1);

	// 4. Disconnecting a client prunes it from host and remaining clients
	hostTransport.disconnectClient("game-peer");
	assert.equal(hostSession.snapshot().remotePlayers.length, 1);
	assert.equal(simClient.snapshot().remotePlayers.length, 1);
	assert.equal(simClient.snapshot().remotePlayers[0]?.peerId, "host-peer");

	// 5. Closing the host room transitions connected clients cleanly to disconnected
	hostSession.disconnect();
	assert.equal(simClient.snapshot().status, "disconnected");
	assert.equal(simClient.snapshot().remotePlayers.length, 0);
}

function testBodyControlLaunchAndPairingContracts(): void {
	assert.equal(
		normalizeBodyControlUrl("robot-gateway.ainek.io"),
		"wss://robot-gateway.ainek.io/robot",
	);
	assert.equal(
		normalizeBodyControlUrl("https://robot-gateway.ainek.io/"),
		"wss://robot-gateway.ainek.io/robot",
	);
	assert.equal(
		normalizeBodyControlUrl("127.0.0.1"),
		"ws://127.0.0.1:8790/robot",
	);
	assert.equal(
		normalizeBodyControlUrl("192.168.0.44:8790"),
		"ws://192.168.0.44:8790/robot",
	);
	assert.equal(
		normalizeBodyControlUrl("http://192.168.0.44:8790"),
		"ws://192.168.0.44:8790/robot",
	);

	const code = encodeBodyControlPairingCode({
		bc: "robot-gateway.ainek.io",
		robotId: "ainekio-v3-sim",
		token: "secret-tok-123",
		model: "v3",
		level: "observatory",
		mp: "host",
		room: "wander-world",
		name: "Ainekio V3",
	});
	assert.ok(code.startsWith("ainekio-pair:"));
	const decoded = decodeBodyControlPairingCode(code);
	assert.deepEqual(decoded, {
		bc: "wss://robot-gateway.ainek.io/robot",
		robotId: "ainekio-v3-sim",
		token: "secret-tok-123",
		model: "v3",
		level: "observatory",
		mp: "host",
		room: "wander-world",
		name: "Ainekio V3",
	});

	const fromUrl = decodeBodyControlPairingCode(
		"https://simulator.ainek.io/#bc=127.0.0.1:8790&robotId=ainekio-v2-sim&token=tok99&model=v2&mp=join&room=lab-room",
	);
	assert.deepEqual(fromUrl, {
		bc: "ws://127.0.0.1:8790/robot",
		robotId: "ainekio-v2-sim",
		token: "tok99",
		model: "v2",
		mp: "join",
		room: "lab-room",
	});

	const launch = parseSimulatorLaunchParams(
		"?room=public-room",
		"#bc=ws://127.0.0.1:8790/robot&robotId=ainekio-v1-sim&token=abc&model=v1&level=yggdrasil&mp=host",
	);
	assert.equal(launch.shouldScrubHash, true);
	assert.equal(launch.bc, "ws://127.0.0.1:8790/robot");
	assert.equal(launch.robotId, "ainekio-v1-sim");
	assert.equal(launch.token, "abc");
	assert.equal(launch.model, "v1");
	assert.equal(launch.level, "yggdrasil");
	assert.equal(launch.mp, "host");
	assert.equal(launch.room, "public-room");

	const roomOnly = parseSimulatorLaunchParams("?room=public-room", "");
	assert.equal(roomOnly.shouldScrubHash, false);
	assert.equal(roomOnly.room, "public-room");

	assert.equal(isNonRetryableBodyControlCloseCode(4000), true);
	assert.equal(isNonRetryableBodyControlCloseCode(4001), true);
	assert.equal(isNonRetryableBodyControlCloseCode(4002), true);
	assert.equal(isNonRetryableBodyControlCloseCode(1002), true);
	assert.equal(isNonRetryableBodyControlCloseCode(1008), true);
	assert.equal(isNonRetryableBodyControlCloseCode(1001), false);
	assert.equal(isNonRetryableBodyControlCloseCode(1006), false);

	const makeMemStore = (): StorageLike => {
		const map = new Map<string, string>();
		return {
			getItem: (k) => map.get(k) ?? null,
			setItem: (k, v) => {
				map.set(k, v);
			},
			removeItem: (k) => {
				map.delete(k);
			},
		};
	};
	const localStore = makeMemStore();
	const sessionStore = makeMemStore();
	saveBodyControlSettings(
		{
			url: "ws://127.0.0.1:8790/robot",
			robotId: "ainekio-v2-sim",
			autoReconnect: true,
		},
		localStore,
	);
	saveBodyControlSessionToken("reload-tok-42", sessionStore);

	// Reload after #hash scrub retains tab-scoped sessionStorage token while keeping localStorage clean of secrets
	const reloaded = loadSavedBodyControlSettings({
		localStore,
		sessionStore,
		locationSearch: "",
	});
	assert.deepEqual(reloaded, {
		url: "ws://127.0.0.1:8790/robot",
		robotId: "ainekio-v2-sim",
		autoReconnect: true,
		token: "reload-tok-42",
	});
	assert.equal(
		localStore.getItem("ainekio.sim.bodyControl.v1")?.includes("reload-tok-42"),
		false,
	);

	// Explicit disconnect / 4001 auth rejection clears sessionStorage token
	clearBodyControlSessionToken(sessionStore);
	const afterClear = loadSavedBodyControlSettings({
		localStore,
		sessionStore,
		locationSearch: "",
	});
	assert.equal(afterClear.token, "");
}

function testVersionedAssetUrls(): void {
	const hashes = {
		"/sim/ainekio-v2-firmware.wasm": "ae53b7deb894",
		"/sim/policies/neural-gait.bin": "7c6e2375e030",
		"/assets/robots/ainekio-v2.glb": "a4c883bf2501",
	} as const;

	assert.equal(
		versionedAssetUrl("/sim/ainekio-v2-firmware.wasm", "", hashes),
		"/sim/ainekio-v2-firmware.wasm?v=ae53b7deb894",
	);
	assert.equal(
		versionedAssetUrl(
			"/sim/policies/neural-gait.bin",
			"https://simulator.ainek.io/",
			hashes,
		),
		"https://simulator.ainek.io/sim/policies/neural-gait.bin?v=7c6e2375e030",
	);
	assert.equal(
		versionedAssetUrl(
			"https://simulator.ainek.io/assets/robots/ainekio-v2.glb",
			"",
			hashes,
		),
		"https://simulator.ainek.io/assets/robots/ainekio-v2.glb?v=a4c883bf2501",
	);
	assert.equal(
		versionedAssetUrl(
			"/sim/ainekio-v2-firmware.wasm?v=already",
			"https://simulator.ainek.io",
			hashes,
		),
		"https://simulator.ainek.io/sim/ainekio-v2-firmware.wasm?v=already",
	);
	assert.equal(
		versionedAssetUrl("/sim/unknown.bin", "https://simulator.ainek.io", hashes),
		"https://simulator.ainek.io/sim/unknown.bin",
	);
	assert.equal(
		versionedAssetUrl("/sim/ainekio-v2-firmware.wasm"),
		"/sim/ainekio-v2-firmware.wasm",
	);
}

testCoordinateTransforms();
testOrbitCameraLookUpAndContinuity();
testProtocolBinaryCodecs();
testCameraResolutions();
testDetachedLevelsAndAssets();
testNeuralPoliciesAndManifoldParity();
testMultiplayerSessionAndGameCompat();
testBodyControlLaunchAndPairingContracts();
testVersionedAssetUrls();
console.log(
	"All simulator.ainek.io contract, asset, multiplayer, Body Control launch/pairing, Neural Gait, Neural Pose, and PoseManifold parity checks passed.",
);

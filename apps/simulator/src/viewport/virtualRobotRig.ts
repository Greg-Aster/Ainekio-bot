/**
 * Three.js articulated Ainekio V2 GLB robot rig.
 *
 * Loads /assets/robots/ainekio-v2.glb (Meshopt compressed), solves the exact
 * 28/16/31/37 mm Study A four-bar leg linkages from 12 live MuJoCo joint angles,
 * binds the live 320x170 ST7789 face CanvasTexture onto Ext_Tex_RobotRoot_01,
 * and mounts a virtual OV5647 chin PerspectiveCamera for live JPEG capture
 * and Robot POV rendering.
 */

import * as THREE from "three";
import { MeshoptDecoder } from "three/addons/libs/meshopt_decoder.module.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import {
	type RobotModelId,
	SIM_FACE_HEIGHT,
	SIM_FACE_WIDTH,
} from "../sim/contracts";

const DEG2RAD = Math.PI / 180;

// Exact V2 Study A 28-16-31-37 four-bar linkage constants matching Blender Scene 'v2'.
const V2_A0 = -2.589563330529253;
const V2_T0 = -3.7982594562326515;
const V2_DX0 = 38.74687556847751;
const V2_DZ0 = 55.02816812469001;
const V2_BETA0 = 2.484875110627394;
const V2_PX0 = 37.41523755796805;
const V2_PZ0 = 90.97953218263883;
const V2_PHI0 = -2.695952349746787;

// Neutral torso height in MuJoCo when the robot rests above Z = 0.
const V2_GLB_BASE_HEIGHT_M = 0.065;

// MuJoCo joints_v2 canonical order is RL(0..2), RR(3..5), FL(6..8), FR(9..11).
// In ainekio-v2.glb (Blender CAD export), the node names are inverted front-to-back
// relative to the face (+Z = +105.5mm):
//   - GLB FL_*/FR_* sit at z = -92.98mm (rear)  -> match MuJoCo rear_left(0..2) / rear_right(3..5)
//   - GLB RL_*/RR_* sit at z = +80.45mm (front) -> match MuJoCo front_left(6..8) / front_right(9..11)
const V2_LEG_JOINT_ORDER: readonly (readonly [
	"FL" | "FR" | "RL" | "RR",
	number,
])[] = [
	["FL", 0],
	["FR", 3],
	["RL", 6],
	["RR", 9],
];

export type VirtualRobotPoseInput = {
	readonly rootPosMj: readonly [number, number, number];
	readonly rootQuatMjWxyz: readonly [number, number, number, number];
	readonly jointsDeg: readonly number[];
};

type V2LegNodes = {
	readonly shoulder: THREE.Object3D;
	readonly primary: THREE.Object3D;
	readonly input: THREE.Object3D;
	readonly rod: THREE.Object3D;
	readonly foot: THREE.Object3D;
	readonly restRodPos: THREE.Vector3;
	readonly restFootPos: THREE.Vector3;
	readonly rollSign: 1 | -1;
};

type V1LegNodes = {
	readonly hip: THREE.Object3D;
	readonly knee: THREE.Object3D;
	readonly hipJointIdx: number;
	readonly kneeJointIdx: number;
	readonly neutralYawDeg: number;
	readonly hipSign: 1 | -1;
};

const V1_LEG_DEFS: readonly {
	readonly name: "front_right" | "rear_right" | "front_left" | "rear_left";
	readonly hipJointIdx: number;
	readonly kneeJointIdx: number;
	readonly neutralYawDeg: number;
	readonly hipSign: 1 | -1;
}[] = [
	{
		name: "front_right",
		hipJointIdx: 0,
		kneeJointIdx: 5,
		neutralYawDeg: -45,
		hipSign: 1,
	},
	{
		name: "rear_right",
		hipJointIdx: 1,
		kneeJointIdx: 4,
		neutralYawDeg: -135,
		hipSign: 1,
	},
	{
		name: "front_left",
		hipJointIdx: 2,
		kneeJointIdx: 6,
		neutralYawDeg: 45,
		hipSign: -1,
	},
	{
		name: "rear_left",
		hipJointIdx: 3,
		kneeJointIdx: 7,
		neutralYawDeg: 135,
		hipSign: -1,
	},
];

// Exact V3 Option A-1 54-22-46-56 four-bar + double-parallelogram ankle constants matching geometry.json
const V3_CARRIER_MM = 54.0;
const V3_CRANK_MM = 22.0;
const V3_PICKUP_MM = 46.0;
const V3_ROD_MM = 56.0;
const V3_A0 = -2.202809465985;
const V3_T0 = 3.055204643652;
const V3_ANKLE_LIMIT_RAD = 0.48;

type V3LegNodes = {
	readonly shoulder: THREE.Object3D;
	readonly carrier: THREE.Object3D;
	readonly crank: THREE.Object3D;
	readonly knee: THREE.Object3D;
	readonly rod: THREE.Object3D;
	readonly ankle?: THREE.Object3D;
	readonly ankleS1?: THREE.Object3D;
	readonly ankleIdler?: THREE.Object3D;
	readonly ankleK2?: THREE.Object3D;
	readonly restKneePos: THREE.Vector3;
	readonly restRodPos: THREE.Vector3;
	readonly jointBase: number;
	readonly rollSign: 1 | -1;
	readonly ox: number;
	readonly oz: number;
	readonly cx: number;
	readonly cz: number;
	readonly dx0: number;
	readonly dz0: number;
	readonly px0: number;
	readonly pz0: number;
	readonly beta0: number;
	readonly gamma0: number;
};

const V3_LEG_DEFS: readonly {
	readonly cadLeg: "RL" | "RR" | "FL" | "FR";
	readonly jointBase: number;
	readonly rollSign: 1 | -1;
	readonly ox: number;
	readonly oz: number;
	readonly cx: number;
	readonly cz: number;
}[] = [
	{
		cadLeg: "RL",
		jointBase: 0,
		rollSign: -1,
		ox: 36.05,
		oz: -19.75,
		cx: 16.0,
		cz: 0.25,
	},
	{
		cadLeg: "RR",
		jointBase: 3,
		rollSign: 1,
		ox: 36.05,
		oz: -19.75,
		cx: 16.0,
		cz: 0.25,
	},
	{
		cadLeg: "FL",
		jointBase: 6,
		rollSign: -1,
		ox: -16.0,
		oz: -19.75,
		cx: -36.05,
		cz: 0.25,
	},
	{
		cadLeg: "FR",
		jointBase: 9,
		rollSign: 1,
		ox: -16.0,
		oz: -19.75,
		cx: -36.05,
		cz: 0.25,
	},
];

function solveV3FourBar(
	ox: number,
	oz: number,
	cx: number,
	cz: number,
	aRad: number,
	tRad: number,
): {
	readonly dx: number;
	readonly dz: number;
	readonly px: number;
	readonly pz: number;
	readonly beta: number;
	readonly gamma: number;
} {
	const dx = ox + V3_CARRIER_MM * Math.cos(aRad);
	const dz = oz + V3_CARRIER_MM * Math.sin(aRad);
	const px = cx + V3_CRANK_MM * Math.cos(tRad);
	const pz = cz + V3_CRANK_MM * Math.sin(tRad);
	const wx = px - dx;
	const wz = pz - dz;
	const d = Math.max(1e-9, Math.hypot(wx, wz));
	const along = Math.min(
		V3_PICKUP_MM,
		Math.max(
			-V3_PICKUP_MM,
			(V3_PICKUP_MM * V3_PICKUP_MM - V3_ROD_MM * V3_ROD_MM + d * d) / (2 * d),
		),
	);
	const h = Math.sqrt(Math.max(0, V3_PICKUP_MM * V3_PICKUP_MM - along * along));
	const ex = dx + (along * wx - h * wz) / d;
	const ez = dz + (along * wz + h * wx) / d;
	return {
		dx,
		dz,
		px,
		pz,
		beta: Math.atan2(ez - dz, ex - dx),
		gamma: Math.atan2(ez - pz, ex - px),
	};
}

async function encodeCanvasToJpeg(
	canvas: HTMLCanvasElement,
	quality: number,
): Promise<{ readonly jpeg: Uint8Array; readonly dataUrl: string }> {
	const dataUrl = canvas.toDataURL("image/jpeg", quality);
	const commaIdx = dataUrl.indexOf(",");
	const base64 = commaIdx >= 0 ? dataUrl.slice(commaIdx + 1) : "";
	const binary = atob(base64);
	const jpeg = new Uint8Array(binary.length);
	for (let i = 0; i < binary.length; i += 1) {
		jpeg[i] = binary.charCodeAt(i);
	}
	return { jpeg, dataUrl };
}

export class ThreeVirtualRobotV2Rig {
	readonly #scene: THREE.Scene;
	readonly #renderer: THREE.WebGLRenderer;
	readonly #container = new THREE.Group();
	#activeModelId: RobotModelId = "v2";
	#model: THREE.Group | undefined;
	#robotRoot: THREE.Object3D | undefined;
	#legs: Record<"FL" | "FR" | "RL" | "RR", V2LegNodes> | undefined;
	#v1Legs: readonly V1LegNodes[] | undefined;
	#v3Legs: readonly V3LegNodes[] | undefined;
	#loadGen = 0;

	readonly #faceCanvas: HTMLCanvasElement;
	readonly #faceCtx: CanvasRenderingContext2D | null;
	readonly #faceTexture: THREE.CanvasTexture;

	readonly #chinCamera: THREE.PerspectiveCamera;
	#captureTarget?: THREE.WebGLRenderTarget;
	#captureCanvas?: HTMLCanvasElement;
	#capturePixels?: Uint8Array;
	#captureWidth = 0;
	#captureHeight = 0;
	#disposed = false;
	#loaded = false;

	constructor(scene: THREE.Scene, renderer: THREE.WebGLRenderer) {
		this.#scene = scene;
		this.#renderer = renderer;

		this.#container.name = "AinekioV2VirtualRobot";
		this.#scene.add(this.#container);

		this.#faceCanvas = document.createElement("canvas");
		this.#faceCanvas.width = SIM_FACE_WIDTH;
		this.#faceCanvas.height = SIM_FACE_HEIGHT;
		this.#faceCtx = this.#faceCanvas.getContext("2d");
		this.#paintStandbyFace();

		this.#faceTexture = new THREE.CanvasTexture(this.#faceCanvas);
		this.#faceTexture.colorSpace = THREE.SRGBColorSpace;
		this.#faceTexture.flipY = false;

		// OV5647 chin camera (~50 deg VFOV / ~65 deg HFOV at 4:3) looking along +Z
		this.#chinCamera = new THREE.PerspectiveCamera(50, 4 / 3, 0.02, 80);
		this.#chinCamera.position.set(0, 0.055, 0.115);
		this.#chinCamera.rotation.set(-0.08, Math.PI, 0, "YXZ");
	}

	get loaded(): boolean {
		return this.#loaded;
	}

	#clearLoadedModel(): void {
		if (this.#robotRoot) {
			this.#robotRoot.remove(this.#chinCamera);
		}
		if (this.#model) {
			this.#container.remove(this.#model);
			this.#model.traverse((obj) => {
				if (obj instanceof THREE.Mesh) {
					obj.geometry.dispose();
					if (Array.isArray(obj.material)) {
						for (const mat of obj.material) {
							mat.dispose();
						}
					} else {
						obj.material.dispose();
					}
				}
			});
			this.#model = undefined;
		}
		this.#robotRoot = undefined;
		this.#legs = undefined;
		this.#v1Legs = undefined;
		this.#v3Legs = undefined;
		this.#loaded = false;
	}

	async load(modelUrl: string, modelId: RobotModelId = "v2"): Promise<void> {
		const gen = ++this.#loadGen;
		const loader = new GLTFLoader();
		loader.setMeshoptDecoder(MeshoptDecoder);
		const gltf = await loader.loadAsync(modelUrl);
		if (this.#disposed || gen !== this.#loadGen) {
			return;
		}
		this.#clearLoadedModel();
		this.#activeModelId = modelId;
		const group = gltf.scene;

		if (modelId === "v1") {
			const root = group.getObjectByName("V1_RobotRoot");
			if (!root) {
				throw new Error(`V1_RobotRoot node missing in ${modelUrl}.`);
			}
			const v1Legs: V1LegNodes[] = [];
			for (const def of V1_LEG_DEFS) {
				const hip = group.getObjectByName(`${def.name}_hip_node`);
				const knee = group.getObjectByName(`${def.name}_knee_node`);
				if (!hip || !knee) {
					throw new Error(`Missing V1 leg nodes (${def.name}) in ${modelUrl}.`);
				}
				v1Legs.push({
					hip,
					knee,
					hipJointIdx: def.hipJointIdx,
					kneeJointIdx: def.kneeJointIdx,
					neutralYawDeg: def.neutralYawDeg,
					hipSign: def.hipSign,
				});
			}

			group.traverse((obj) => {
				if (!(obj instanceof THREE.Mesh)) {
					return;
				}
				obj.castShadow = true;
				obj.receiveShadow = true;
				const isFaceMesh =
					obj.name === "V1_FaceDisplay" ||
					(obj.material &&
						!Array.isArray(obj.material) &&
						obj.material.name === "V1_FaceDisplay_Mat");
				if (isFaceMesh) {
					obj.material = new THREE.MeshBasicMaterial({
						map: this.#faceTexture,
						toneMapped: false,
						side: THREE.DoubleSide,
					});
				}
			});

			// Arducam B0066 sits at CAD body [59.59, 0, -6.42] mm -> Three [0, -0.0064, +0.064] m
			this.#chinCamera.position.set(0, -0.0064, 0.064);
			this.#chinCamera.rotation.set(-0.04, Math.PI, 0, "YXZ");
			root.add(this.#chinCamera);
			this.#container.add(group);
			this.#model = group;
			this.#robotRoot = root;
			this.#v1Legs = v1Legs;
			this.#loaded = true;
			return;
		}

		if (modelId === "v3") {
			const root = group.getObjectByName("V3_RobotRoot");
			if (!root) {
				throw new Error(`V3_RobotRoot node missing in ${modelUrl}.`);
			}
			const v3Legs: V3LegNodes[] = [];
			for (const def of V3_LEG_DEFS) {
				const shoulder = group.getObjectByName(`V3_${def.cadLeg}_Shoulder`);
				const carrier = group.getObjectByName(`V3_${def.cadLeg}_Carrier`);
				const crank = group.getObjectByName(`V3_${def.cadLeg}_Crank`);
				const knee = group.getObjectByName(`V3_${def.cadLeg}_Knee`);
				const rod = group.getObjectByName(`V3_${def.cadLeg}_Rod`);
				if (!shoulder || !carrier || !crank || !knee || !rod) {
					throw new Error(
						`Missing V3 leg nodes (${def.cadLeg}) in ${modelUrl}.`,
					);
				}
				const ankle = group.getObjectByName(`V3_${def.cadLeg}_Ankle`);
				const ankleS1 = group.getObjectByName(`V3_${def.cadLeg}_AnkleS1`);
				const ankleIdler = group.getObjectByName(`V3_${def.cadLeg}_AnkleIdler`);
				const ankleK2 = group.getObjectByName(`V3_${def.cadLeg}_AnkleK2`);
				const n0 = solveV3FourBar(def.ox, def.oz, def.cx, def.cz, V3_A0, V3_T0);
				v3Legs.push({
					shoulder,
					carrier,
					crank,
					knee,
					rod,
					...(ankle ? { ankle } : {}),
					...(ankleS1 ? { ankleS1 } : {}),
					...(ankleIdler ? { ankleIdler } : {}),
					...(ankleK2 ? { ankleK2 } : {}),
					restKneePos: knee.position.clone(),
					restRodPos: rod.position.clone(),
					jointBase: def.jointBase,
					rollSign: def.rollSign,
					ox: def.ox,
					oz: def.oz,
					cx: def.cx,
					cz: def.cz,
					dx0: n0.dx,
					dz0: n0.dz,
					px0: n0.px,
					pz0: n0.pz,
					beta0: n0.beta,
					gamma0: n0.gamma,
				});
			}

			group.traverse((obj) => {
				if (!(obj instanceof THREE.Mesh)) {
					return;
				}
				obj.castShadow = true;
				obj.receiveShadow = true;
				const isFaceMesh =
					obj.name === "V3_FaceDisplay" ||
					(obj.material &&
						!Array.isArray(obj.material) &&
						obj.material.name === "V3_FaceDisplay_Mat");
				if (isFaceMesh) {
					obj.material = new THREE.MeshBasicMaterial({
						map: this.#faceTexture,
						toneMapped: false,
						side: THREE.DoubleSide,
					});
				}
			});

			// Arducam B0066 sits above the 2.8in display at CAD body [195, 0, +18] mm -> Three [0, +0.018, +0.196] m
			this.#chinCamera.position.set(0, 0.018, 0.196);
			this.#chinCamera.rotation.set(-0.06, Math.PI, 0, "YXZ");
			root.add(this.#chinCamera);
			this.#container.add(group);
			this.#model = group;
			this.#robotRoot = root;
			this.#v3Legs = v3Legs;
			this.#loaded = true;
			return;
		}

		const root = group.getObjectByName("RobotRoot");
		if (!root) {
			throw new Error(`RobotRoot node missing in ${modelUrl}.`);
		}

		const legs = {} as Record<"FL" | "FR" | "RL" | "RR", V2LegNodes>;
		for (const legKey of ["FL", "FR", "RL", "RR"] as const) {
			const shoulder = group.getObjectByName(`${legKey}_Shoulder`);
			const primary = group.getObjectByName(`${legKey}_Primary`);
			const input = group.getObjectByName(`${legKey}_Input`);
			const rod = group.getObjectByName(`${legKey}_Rod`);
			const foot = group.getObjectByName(`${legKey}_Foot`);
			if (!shoulder || !primary || !input || !rod || !foot) {
				throw new Error(`Missing V2 leg nodes for ${legKey} in ${modelUrl}.`);
			}
			legs[legKey] = {
				shoulder,
				primary,
				input,
				rod,
				foot,
				restRodPos: rod.position.clone(),
				restFootPos: foot.position.clone(),
				rollSign: legKey === "FL" || legKey === "RL" ? -1 : 1,
			};
		}

		group.traverse((obj) => {
			if (!(obj instanceof THREE.Mesh)) {
				return;
			}
			obj.castShadow = true;
			obj.receiveShadow = true;
			const isFaceMesh =
				obj.name === "Int_Tex_RobotRoot_00" ||
				(obj.material &&
					!Array.isArray(obj.material) &&
					obj.material.name === "Mat_Tex_000");
			if (isFaceMesh) {
				obj.material = new THREE.MeshBasicMaterial({
					map: this.#faceTexture,
					toneMapped: false,
					side: THREE.DoubleSide,
				});
			}
		});

		this.#chinCamera.position.set(0, 0.056, 0.119);
		this.#chinCamera.rotation.set(-0.08, Math.PI, 0, "YXZ");
		root.add(this.#chinCamera);
		this.#container.add(group);
		this.#model = group;
		this.#robotRoot = root;
		this.#legs = legs;
		this.#loaded = true;
	}

	applyPose(pose: VirtualRobotPoseInput): void {
		if (!this.#robotRoot) {
			return;
		}
		const [mx, my, mz] = pose.rootPosMj;
		const [qw, qx, qy, qz] = pose.rootQuatMjWxyz;

		if (this.#activeModelId === "v1") {
			if (!this.#v1Legs || pose.jointsDeg.length < 8) {
				return;
			}
			// V1_RobotRoot origin IS MuJoCo torso body frame (0, 0, 0)
			this.#robotRoot.position.set(my, mz, mx);
			this.#robotRoot.quaternion.set(qy, qz, qx, qw);
			for (const leg of this.#v1Legs) {
				const hDeg = pose.jointsDeg[leg.hipJointIdx] ?? 0;
				const kDeg = pose.jointsDeg[leg.kneeJointIdx] ?? 0;
				leg.hip.rotation.set(
					0,
					(leg.neutralYawDeg + leg.hipSign * hDeg) * DEG2RAD,
					0,
				);
				leg.knee.rotation.set(-kDeg * DEG2RAD, 0, 0);
			}
			return;
		}

		if (this.#activeModelId === "v3") {
			if (!this.#v3Legs || pose.jointsDeg.length < 12) {
				return;
			}
			// V3_RobotRoot origin IS MuJoCo torso body frame (shoulder height)
			this.#robotRoot.position.set(my, mz, mx);
			this.#robotRoot.quaternion.set(qy, qz, qx, qw);
			for (const leg of this.#v3Legs) {
				const hDeg = pose.jointsDeg[leg.jointBase] ?? 0;
				const aDeg = pose.jointsDeg[leg.jointBase + 1] ?? 0;
				const tDeg = pose.jointsDeg[leg.jointBase + 2] ?? 0;

				leg.shoulder.rotation.set(0, 0, leg.rollSign * hDeg * DEG2RAD);
				const a = V3_A0 + aDeg * DEG2RAD;
				const t = V3_T0 + tDeg * DEG2RAD;
				const sol = solveV3FourBar(leg.ox, leg.oz, leg.cx, leg.cz, a, t);

				leg.carrier.rotation.set(-(a - V3_A0), 0, 0);
				leg.crank.rotation.set(-(t - V3_T0), 0, 0);
				leg.rod.position.set(
					leg.restRodPos.x,
					leg.restRodPos.y + 0.001 * (sol.pz - leg.pz0),
					leg.restRodPos.z + 0.001 * (sol.px - leg.px0),
				);
				leg.rod.rotation.set(-(sol.gamma - leg.gamma0), 0, 0);
				const kneePitchDelta = sol.beta - leg.beta0;
				leg.knee.position.set(
					leg.restKneePos.x,
					leg.restKneePos.y + 0.001 * (sol.dz - leg.dz0),
					leg.restKneePos.z + 0.001 * (sol.dx - leg.dx0),
				);
				leg.knee.rotation.set(-kneePitchDelta, 0, 0);
				if (leg.ankle) {
					const anklePitch = Math.max(
						-V3_ANKLE_LIMIT_RAD,
						Math.min(V3_ANKLE_LIMIT_RAD, kneePitchDelta),
					);
					leg.ankle.rotation.set(anklePitch, 0, 0);
				}
				if (leg.ankleS1) {
					leg.ankleS1.rotation.set(-(a - V3_A0), 0, 0);
				}
				if (leg.ankleIdler) {
					leg.ankleIdler.rotation.set(kneePitchDelta, 0, 0);
				}
				if (leg.ankleK2) {
					leg.ankleK2.rotation.set(-kneePitchDelta, 0, 0);
				}
			}
			return;
		}

		if (!this.#legs || pose.jointsDeg.length < 12) {
			return;
		}
		// MuJoCo (+X fwd, +Y left, +Z up) -> Three.js (+Z fwd, +X left, +Y up).
		// In ainekio-v2.glb, shoulder nodes sit at local y = +0.08096183 m while
		// MuJoCo's shoulder bodies sit at z = torso_z + 0.01596183 m (exact 0.065 m
		// difference). Setting RobotRoot.position directly to (my, mz - 0.065, mx)
		// without adding the GLB's restRootPos (-0.01415 m) aligns the 3D foot soles
		// flush with MuJoCo's z = 0 floor plane instead of sinking 14.15 mm below it.
		this.#robotRoot.position.set(my, mz - V2_GLB_BASE_HEIGHT_M, mx);
		this.#robotRoot.quaternion.set(qy, qz, qx, qw);

		for (const [legKey, base] of V2_LEG_JOINT_ORDER) {
			const leg = this.#legs[legKey];
			const hDeg = pose.jointsDeg[base] ?? 0;
			const aDeg = pose.jointsDeg[base + 1] ?? 0;
			const tDeg = pose.jointsDeg[base + 2] ?? 0;

			leg.shoulder.rotation.set(0, 0, leg.rollSign * hDeg * DEG2RAD);

			const a = V2_A0 + aDeg * DEG2RAD;
			const t = V2_T0 + tDeg * DEG2RAD;
			const dx = 62.58781342006688 + 28 * Math.cos(a);
			const dz = 69.71182170125783 + 28 * Math.sin(a);
			const px = 50.08774121717073 + 16 * Math.cos(t);
			const pz = 81.2118481681196 + 16 * Math.sin(t);
			const wx = px - dx;
			const wz = pz - dz;
			const d = Math.max(1e-9, Math.hypot(wx, wz));
			const along = Math.min(37, Math.max(-37, (1369 - 961 + d * d) / (2 * d)));
			const height = Math.sqrt(Math.max(0, 1369 - along * along));
			const ex = dx + (along * wx - height * wz) / d;
			const ez = dz + (along * wz + height * wx) / d;
			const beta = Math.atan2(ez - dz, ex - dx);
			const phi = Math.atan2(ez - pz, ex - px);

			leg.primary.rotation.set(-(a - V2_A0), 0, 0);
			leg.input.rotation.set(-(t - V2_T0), 0, 0);
			leg.rod.position.set(
				leg.restRodPos.x,
				leg.restRodPos.y + 0.001 * (pz - V2_PZ0),
				leg.restRodPos.z + 0.001 * (px - V2_PX0),
			);
			leg.rod.rotation.set(-(phi - V2_PHI0), 0, 0);
			leg.foot.position.set(
				leg.restFootPos.x,
				leg.restFootPos.y + 0.001 * (dz - V2_DZ0),
				leg.restFootPos.z + 0.001 * (dx - V2_DX0),
			);
			leg.foot.rotation.set(-(beta - V2_BETA0), 0, 0);
		}
	}

	updateFaceRgba(width: number, height: number, rgba: Uint8Array): void {
		if (
			!this.#faceCtx ||
			width !== SIM_FACE_WIDTH ||
			height !== SIM_FACE_HEIGHT
		) {
			return;
		}
		const imageData = this.#faceCtx.createImageData(width, height);
		imageData.data.set(rgba);
		this.#faceCtx.putImageData(imageData, 0, 0);
		this.#faceTexture.needsUpdate = true;
	}

	getWorldPosition(): THREE.Vector3 {
		const target = new THREE.Vector3();
		if (this.#robotRoot) {
			this.#robotRoot.getWorldPosition(target);
		}
		return target;
	}

	getForwardWorldDirection(): THREE.Vector3 {
		const dir = new THREE.Vector3(0, 0, 1);
		if (this.#robotRoot) {
			const quat = new THREE.Quaternion();
			this.#robotRoot.getWorldQuaternion(quat);
			dir.applyQuaternion(quat).normalize();
		}
		return dir;
	}

	getChinCameraPose(): {
		readonly position: THREE.Vector3;
		readonly quaternion: THREE.Quaternion;
	} {
		const position = new THREE.Vector3();
		const quaternion = new THREE.Quaternion();
		this.#chinCamera.updateMatrixWorld(true);
		this.#chinCamera.getWorldPosition(position);
		this.#chinCamera.getWorldQuaternion(quaternion);
		return { position, quaternion };
	}

	async captureChinCameraJpeg(
		width: number,
		height: number,
		quality = 0.78,
	): Promise<
		{ readonly jpeg: Uint8Array; readonly dataUrl: string } | undefined
	> {
		if (this.#disposed || !this.#loaded) {
			return undefined;
		}
		if (
			!this.#captureTarget ||
			this.#captureWidth !== width ||
			this.#captureHeight !== height
		) {
			this.#captureTarget?.dispose();
			this.#captureTarget = new THREE.WebGLRenderTarget(width, height, {
				minFilter: THREE.LinearFilter,
				magFilter: THREE.LinearFilter,
				format: THREE.RGBAFormat,
				type: THREE.UnsignedByteType,
			});
			this.#captureCanvas = document.createElement("canvas");
			this.#captureCanvas.width = width;
			this.#captureCanvas.height = height;
			this.#capturePixels = new Uint8Array(width * height * 4);
			this.#captureWidth = width;
			this.#captureHeight = height;
		}

		const captureTarget = this.#captureTarget;
		const captureCanvas = this.#captureCanvas;
		const capturePixels = this.#capturePixels;
		if (!captureTarget || !captureCanvas || !capturePixels) {
			return undefined;
		}

		this.#chinCamera.aspect = width / height;
		this.#chinCamera.updateProjectionMatrix();
		this.#scene.updateMatrixWorld(true);
		this.#chinCamera.updateMatrixWorld(true);

		const previousTarget = this.#renderer.getRenderTarget();
		const previousShadowAutoUpdate = this.#renderer.shadowMap.autoUpdate;
		this.#renderer.shadowMap.autoUpdate = false;
		this.#renderer.setRenderTarget(captureTarget);
		this.#renderer.render(this.#scene, this.#chinCamera);
		this.#renderer.readRenderTargetPixels(
			captureTarget,
			0,
			0,
			width,
			height,
			capturePixels,
		);
		this.#renderer.setRenderTarget(previousTarget);
		this.#renderer.shadowMap.autoUpdate = previousShadowAutoUpdate;

		const ctx = captureCanvas.getContext("2d");
		if (!ctx) {
			return undefined;
		}
		const imageData = ctx.createImageData(width, height);
		const rowBytes = width * 4;
		for (let y = 0; y < height; y += 1) {
			const srcOffset = (height - 1 - y) * rowBytes;
			const dstOffset = y * rowBytes;
			imageData.data.set(
				capturePixels.subarray(srcOffset, srcOffset + rowBytes),
				dstOffset,
			);
		}
		ctx.putImageData(imageData, 0, 0);
		return encodeCanvasToJpeg(captureCanvas, quality);
	}

	dispose(): void {
		if (this.#disposed) {
			return;
		}
		this.#disposed = true;
		this.#captureTarget?.dispose();
		this.#faceTexture.dispose();
		if (this.#model) {
			this.#container.remove(this.#model);
		}
		this.#scene.remove(this.#container);
	}

	#paintStandbyFace(): void {
		const ctx = this.#faceCtx;
		if (!ctx) {
			return;
		}
		ctx.fillStyle = "#04080e";
		ctx.fillRect(0, 0, SIM_FACE_WIDTH, SIM_FACE_HEIGHT);
		ctx.fillStyle = "#20cfff";
		ctx.beginPath();
		ctx.arc(108, 92, 12, 0, Math.PI * 2);
		ctx.arc(212, 92, 12, 0, Math.PI * 2);
		ctx.fill();
	}
}

export type ArticulatedRemoteRobotHandle = {
	readonly modelId: RobotModelId;
	readonly group: THREE.Group;
	readonly root: THREE.Object3D;
	readonly v1Legs?: readonly V1LegNodes[];
	readonly v2Legs?: Record<"FL" | "FR" | "RL" | "RR", V2LegNodes>;
	readonly v3Legs?: readonly V3LegNodes[];
};

/**
 * Bind a cloned V1/V2/V3 robot GLB scene for remote multiplayer peers using
 * the exact same four-bar kinematic solver as the local robot.
 */
export function bindArticulatedRobotClone(
	group: THREE.Group,
	modelId: RobotModelId,
	faceTexture: THREE.Texture,
): ArticulatedRemoteRobotHandle | undefined {
	if (modelId === "v1") {
		const root = group.getObjectByName("V1_RobotRoot");
		if (!root) {
			return undefined;
		}
		const v1Legs: V1LegNodes[] = [];
		for (const def of V1_LEG_DEFS) {
			const hip = group.getObjectByName(`${def.name}_hip_node`);
			const knee = group.getObjectByName(`${def.name}_knee_node`);
			if (!hip || !knee) {
				return undefined;
			}
			v1Legs.push({
				hip,
				knee,
				hipJointIdx: def.hipJointIdx,
				kneeJointIdx: def.kneeJointIdx,
				neutralYawDeg: def.neutralYawDeg,
				hipSign: def.hipSign,
			});
		}
		group.traverse((obj) => {
			if (!(obj instanceof THREE.Mesh)) {
				return;
			}
			obj.castShadow = true;
			obj.receiveShadow = true;
			const isFaceMesh =
				obj.name === "V1_FaceDisplay" ||
				(obj.material &&
					!Array.isArray(obj.material) &&
					obj.material.name === "V1_FaceDisplay_Mat");
			if (isFaceMesh) {
				obj.material = new THREE.MeshBasicMaterial({
					map: faceTexture,
					toneMapped: false,
					side: THREE.DoubleSide,
				});
			}
		});
		return { modelId, group, root, v1Legs };
	}

	if (modelId === "v3") {
		const root = group.getObjectByName("V3_RobotRoot");
		if (!root) {
			return undefined;
		}
		const v3Legs: V3LegNodes[] = [];
		for (const def of V3_LEG_DEFS) {
			const shoulder = group.getObjectByName(`V3_${def.cadLeg}_Shoulder`);
			const carrier = group.getObjectByName(`V3_${def.cadLeg}_Carrier`);
			const crank = group.getObjectByName(`V3_${def.cadLeg}_Crank`);
			const knee = group.getObjectByName(`V3_${def.cadLeg}_Knee`);
			const rod = group.getObjectByName(`V3_${def.cadLeg}_Rod`);
			if (!shoulder || !carrier || !crank || !knee || !rod) {
				return undefined;
			}
			const ankle = group.getObjectByName(`V3_${def.cadLeg}_Ankle`);
			const ankleS1 = group.getObjectByName(`V3_${def.cadLeg}_AnkleS1`);
			const ankleIdler = group.getObjectByName(`V3_${def.cadLeg}_AnkleIdler`);
			const ankleK2 = group.getObjectByName(`V3_${def.cadLeg}_AnkleK2`);
			const n0 = solveV3FourBar(def.ox, def.oz, def.cx, def.cz, V3_A0, V3_T0);
			v3Legs.push({
				shoulder,
				carrier,
				crank,
				knee,
				rod,
				...(ankle ? { ankle } : {}),
				...(ankleS1 ? { ankleS1 } : {}),
				...(ankleIdler ? { ankleIdler } : {}),
				...(ankleK2 ? { ankleK2 } : {}),
				restKneePos: knee.position.clone(),
				restRodPos: rod.position.clone(),
				jointBase: def.jointBase,
				rollSign: def.rollSign,
				ox: def.ox,
				oz: def.oz,
				cx: def.cx,
				cz: def.cz,
				dx0: n0.dx,
				dz0: n0.dz,
				px0: n0.px,
				pz0: n0.pz,
				beta0: n0.beta,
				gamma0: n0.gamma,
			});
		}
		group.traverse((obj) => {
			if (!(obj instanceof THREE.Mesh)) {
				return;
			}
			obj.castShadow = true;
			obj.receiveShadow = true;
			const isFaceMesh =
				obj.name === "V3_FaceDisplay" ||
				(obj.material &&
					!Array.isArray(obj.material) &&
					obj.material.name === "V3_FaceDisplay_Mat");
			if (isFaceMesh) {
				obj.material = new THREE.MeshBasicMaterial({
					map: faceTexture,
					toneMapped: false,
					side: THREE.DoubleSide,
				});
			}
		});
		return { modelId, group, root, v3Legs };
	}

	const root = group.getObjectByName("RobotRoot");
	if (!root) {
		return undefined;
	}
	const v2Legs = {} as Record<"FL" | "FR" | "RL" | "RR", V2LegNodes>;
	for (const legKey of ["FL", "FR", "RL", "RR"] as const) {
		const shoulder = group.getObjectByName(`${legKey}_Shoulder`);
		const primary = group.getObjectByName(`${legKey}_Primary`);
		const input = group.getObjectByName(`${legKey}_Input`);
		const rod = group.getObjectByName(`${legKey}_Rod`);
		const foot = group.getObjectByName(`${legKey}_Foot`);
		if (!shoulder || !primary || !input || !rod || !foot) {
			return undefined;
		}
		v2Legs[legKey] = {
			shoulder,
			primary,
			input,
			rod,
			foot,
			restRodPos: rod.position.clone(),
			restFootPos: foot.position.clone(),
			rollSign: legKey === "FL" || legKey === "RL" ? -1 : 1,
		};
	}
	group.traverse((obj) => {
		if (!(obj instanceof THREE.Mesh)) {
			return;
		}
		obj.castShadow = true;
		obj.receiveShadow = true;
		const isFaceMesh =
			obj.name === "Int_Tex_RobotRoot_00" ||
			(obj.material &&
				!Array.isArray(obj.material) &&
				obj.material.name === "Mat_Tex_000");
		if (isFaceMesh) {
			obj.material = new THREE.MeshBasicMaterial({
				map: faceTexture,
				toneMapped: false,
				side: THREE.DoubleSide,
			});
		}
	});
	return { modelId: "v2", group, root, v2Legs };
}

/**
 * Apply Three.js world position, xyzw quaternion, and optional joint angles
 * (degrees) to a bound remote robot clone.
 */
export function applyArticulatedRobotThreePose(
	handle: ArticulatedRemoteRobotHandle,
	positionThree: THREE.Vector3,
	rotationXyzw: THREE.Quaternion,
	jointsDeg?: readonly number[],
): void {
	if (handle.modelId === "v1") {
		handle.root.position.copy(positionThree);
		handle.root.quaternion.copy(rotationXyzw);
		if (handle.v1Legs && jointsDeg && jointsDeg.length >= 8) {
			for (const leg of handle.v1Legs) {
				const hDeg = jointsDeg[leg.hipJointIdx] ?? 0;
				const kDeg = jointsDeg[leg.kneeJointIdx] ?? 0;
				leg.hip.rotation.set(
					0,
					(leg.neutralYawDeg + leg.hipSign * hDeg) * DEG2RAD,
					0,
				);
				leg.knee.rotation.set(-kDeg * DEG2RAD, 0, 0);
			}
		}
		return;
	}

	if (handle.modelId === "v3") {
		handle.root.position.copy(positionThree);
		handle.root.quaternion.copy(rotationXyzw);
		if (handle.v3Legs && jointsDeg && jointsDeg.length >= 12) {
			for (const leg of handle.v3Legs) {
				const hDeg = jointsDeg[leg.jointBase] ?? 0;
				const aDeg = jointsDeg[leg.jointBase + 1] ?? 0;
				const tDeg = jointsDeg[leg.jointBase + 2] ?? 0;
				leg.shoulder.rotation.set(0, 0, leg.rollSign * hDeg * DEG2RAD);
				const a = V3_A0 + aDeg * DEG2RAD;
				const t = V3_T0 + tDeg * DEG2RAD;
				const sol = solveV3FourBar(leg.ox, leg.oz, leg.cx, leg.cz, a, t);
				leg.carrier.rotation.set(-(a - V3_A0), 0, 0);
				leg.crank.rotation.set(-(t - V3_T0), 0, 0);
				leg.rod.position.set(
					leg.restRodPos.x,
					leg.restRodPos.y + 0.001 * (sol.pz - leg.pz0),
					leg.restRodPos.z + 0.001 * (sol.px - leg.px0),
				);
				leg.rod.rotation.set(-(sol.gamma - leg.gamma0), 0, 0);
				const kneePitchDelta = sol.beta - leg.beta0;
				leg.knee.position.set(
					leg.restKneePos.x,
					leg.restKneePos.y + 0.001 * (sol.dz - leg.dz0),
					leg.restKneePos.z + 0.001 * (sol.dx - leg.dx0),
				);
				leg.knee.rotation.set(-kneePitchDelta, 0, 0);
				if (leg.ankle) {
					const anklePitch = Math.max(
						-V3_ANKLE_LIMIT_RAD,
						Math.min(V3_ANKLE_LIMIT_RAD, kneePitchDelta),
					);
					leg.ankle.rotation.set(anklePitch, 0, 0);
				}
				if (leg.ankleS1) {
					leg.ankleS1.rotation.set(-(a - V3_A0), 0, 0);
				}
				if (leg.ankleIdler) {
					leg.ankleIdler.rotation.set(kneePitchDelta, 0, 0);
				}
				if (leg.ankleK2) {
					leg.ankleK2.rotation.set(-kneePitchDelta, 0, 0);
				}
			}
		}
		return;
	}

	handle.root.position.set(
		positionThree.x,
		positionThree.y - V2_GLB_BASE_HEIGHT_M,
		positionThree.z,
	);
	handle.root.quaternion.copy(rotationXyzw);
	if (handle.v2Legs && jointsDeg && jointsDeg.length >= 12) {
		for (const [legKey, base] of V2_LEG_JOINT_ORDER) {
			const leg = handle.v2Legs[legKey];
			const hDeg = jointsDeg[base] ?? 0;
			const aDeg = jointsDeg[base + 1] ?? 0;
			const tDeg = jointsDeg[base + 2] ?? 0;
			leg.shoulder.rotation.set(0, 0, leg.rollSign * hDeg * DEG2RAD);
			const a = V2_A0 + aDeg * DEG2RAD;
			const t = V2_T0 + tDeg * DEG2RAD;
			const dx = 62.58781342006688 + 28 * Math.cos(a);
			const dz = 69.71182170125783 + 28 * Math.sin(a);
			const px = 50.08774121717073 + 16 * Math.cos(t);
			const pz = 81.2118481681196 + 16 * Math.sin(t);
			const wx = px - dx;
			const wz = pz - dz;
			const d = Math.max(1e-9, Math.hypot(wx, wz));
			const along = Math.min(37, Math.max(-37, (1369 - 961 + d * d) / (2 * d)));
			const height = Math.sqrt(Math.max(0, 1369 - along * along));
			const ex = dx + (along * wx - height * wz) / d;
			const ez = dz + (along * wz + height * wx) / d;
			const beta = Math.atan2(ez - dz, ex - dx);
			const phi = Math.atan2(ez - pz, ex - px);

			leg.primary.rotation.set(-(a - V2_A0), 0, 0);
			leg.input.rotation.set(-(t - V2_T0), 0, 0);
			leg.rod.position.set(
				leg.restRodPos.x,
				leg.restRodPos.y + 0.001 * (pz - V2_PZ0),
				leg.restRodPos.z + 0.001 * (px - V2_PX0),
			);
			leg.rod.rotation.set(-(phi - V2_PHI0), 0, 0);
			leg.foot.position.set(
				leg.restFootPos.x,
				leg.restFootPos.y + 0.001 * (dz - V2_DZ0),
				leg.restFootPos.z + 0.001 * (dx - V2_DX0),
			);
			leg.foot.rotation.set(-(beta - V2_BETA0), 0, 0);
		}
	}
}

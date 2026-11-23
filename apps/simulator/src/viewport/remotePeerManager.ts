import * as THREE from "three";
import { MeshoptDecoder } from "three/addons/libs/meshopt_decoder.module.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import type { MultiplayerRemotePlayer } from "../multiplayer/index.js";
import {
	type RobotModelId,
	SIM_FACE_HEIGHT,
	SIM_FACE_WIDTH,
	type SimulatorLevelId,
	getRobotModelDescriptor,
} from "../sim/contracts";
import {
	type ArticulatedRemoteRobotHandle,
	applyArticulatedRobotThreePose,
	bindArticulatedRobotClone,
} from "./virtualRobotRig";

const PEER_ACCENT_COLORS = [
	"#38bdf8",
	"#34d399",
	"#f59e0b",
	"#c084fc",
	"#fb7185",
	"#22d3ee",
] as const;

type RemotePeerVisual = {
	readonly peerId: string;
	readonly container: THREE.Group;
	readonly accentHex: string;
	readonly faceTexture: THREE.CanvasTexture;
	readonly labelSprite: THREE.Sprite;
	readonly labelTexture: THREE.CanvasTexture;
	labelText: string;
	kind: "beacon" | RobotModelId;
	beaconGroup?: THREE.Group | undefined;
	robotHandle?: ArticulatedRemoteRobotHandle | undefined;
	loadingModel?: RobotModelId | undefined;
	readonly currentPos: THREE.Vector3;
	readonly targetPos: THREE.Vector3;
	readonly currentQuat: THREE.Quaternion;
	readonly targetQuat: THREE.Quaternion;
	currentJoints: number[];
	targetJoints: number[];
	initialized: boolean;
};

function peerAccentForId(peerId: string): string {
	let hash = 0;
	for (let i = 0; i < peerId.length; i += 1) {
		hash = (hash * 31 + peerId.charCodeAt(i)) >>> 0;
	}
	return (
		PEER_ACCENT_COLORS[hash % PEER_ACCENT_COLORS.length] ??
		PEER_ACCENT_COLORS[0]
	);
}

function shortPeerLabel(peerId: string): string {
	return peerId.length > 10 ? `${peerId.slice(0, 6)}…` : peerId;
}

function createPeerFaceTexture(accentHex: string): THREE.CanvasTexture {
	const canvas = document.createElement("canvas");
	canvas.width = SIM_FACE_WIDTH;
	canvas.height = SIM_FACE_HEIGHT;
	const ctx = canvas.getContext("2d");
	if (ctx) {
		ctx.fillStyle = "#04080e";
		ctx.fillRect(0, 0, SIM_FACE_WIDTH, SIM_FACE_HEIGHT);
		ctx.fillStyle = accentHex;
		ctx.beginPath();
		ctx.arc(108, 90, 15, 0, Math.PI * 2);
		ctx.arc(212, 90, 15, 0, Math.PI * 2);
		ctx.fill();
		ctx.strokeStyle = accentHex;
		ctx.lineWidth = 6;
		ctx.lineCap = "round";
		ctx.beginPath();
		ctx.arc(160, 112, 24, 0.15 * Math.PI, 0.85 * Math.PI);
		ctx.stroke();
	}
	const tex = new THREE.CanvasTexture(canvas);
	tex.colorSpace = THREE.SRGBColorSpace;
	tex.flipY = false;
	return tex;
}

function paintNameplateTexture(
	canvas: HTMLCanvasElement,
	label: string,
	accentHex: string,
): void {
	const ctx = canvas.getContext("2d");
	if (!ctx) {
		return;
	}
	const w = canvas.width;
	const h = canvas.height;
	ctx.clearRect(0, 0, w, h);

	const padX = 16;
	const boxH = 44;
	const y = (h - boxH) / 2;
	ctx.fillStyle = "rgba(8, 14, 24, 0.84)";
	ctx.strokeStyle = accentHex;
	ctx.lineWidth = 3;
	ctx.beginPath();
	ctx.roundRect(padX, y, w - padX * 2, boxH, 22);
	ctx.fill();
	ctx.stroke();

	ctx.fillStyle = accentHex;
	ctx.beginPath();
	ctx.arc(padX + 22, h / 2, 6, 0, Math.PI * 2);
	ctx.fill();

	ctx.fillStyle = "#f1f5f9";
	ctx.font = "bold 20px system-ui, -apple-system, sans-serif";
	ctx.textAlign = "left";
	ctx.textBaseline = "middle";
	ctx.fillText(label.slice(0, 26), padX + 38, h / 2 + 1);
}

function createBeaconAvatar(accentHex: string): THREE.Group {
	const group = new THREE.Group();
	group.name = "RemoteBeaconAvatar";

	const orb = new THREE.Mesh(
		new THREE.SphereGeometry(0.11, 20, 16),
		new THREE.MeshStandardMaterial({
			color: accentHex,
			emissive: accentHex,
			emissiveIntensity: 0.75,
			roughness: 0.25,
			metalness: 0.2,
		}),
	);
	orb.position.y = 0.22;
	orb.castShadow = true;
	group.add(orb);

	const halo = new THREE.Mesh(
		new THREE.TorusGeometry(0.17, 0.015, 10, 28),
		new THREE.MeshBasicMaterial({
			color: accentHex,
			transparent: true,
			opacity: 0.75,
		}),
	);
	halo.rotation.x = Math.PI / 2;
	halo.position.y = 0.04;
	group.add(halo);

	return group;
}

function disposeGroupResources(obj: THREE.Object3D): void {
	obj.traverse((child) => {
		if (child instanceof THREE.Mesh) {
			child.geometry.dispose();
			if (Array.isArray(child.material)) {
				for (const mat of child.material) {
					mat.dispose();
				}
			} else {
				child.material.dispose();
			}
		}
	});
}

/**
 * Renders live remote multiplayer peers in the Three.js scene:
 *  - Articulated V1 / V2 / V3 robots (cloned from a lazy per-model GLB cache)
 *  - Lightweight glowing beacon avatars for game.megameal non-robot players
 *  - Smooth 60 FPS pose & joint interpolation between 10 Hz WebRTC updates
 */
export class RemotePeerManager {
	readonly #scene: THREE.Scene;
	readonly #root = new THREE.Group();
	readonly #gltfLoader = new GLTFLoader();
	readonly #templateCache = new Map<RobotModelId, Promise<THREE.Group>>();
	readonly #peers = new Map<string, RemotePeerVisual>();
	#disposed = false;

	constructor(scene: THREE.Scene) {
		this.#scene = scene;
		this.#root.name = "RemoteMultiplayerPeers";
		this.#scene.add(this.#root);
		this.#gltfLoader.setMeshoptDecoder(MeshoptDecoder);
	}

	syncPeers(
		remotePlayers: readonly MultiplayerRemotePlayer[],
		localLevelId: SimulatorLevelId,
	): void {
		if (this.#disposed) {
			return;
		}
		const visibleIds = new Set<string>();

		for (const remote of remotePlayers) {
			// Render simulator peers in the same world and game.megameal peers (no levelId)
			if (remote.pose.levelId && remote.pose.levelId !== localLevelId) {
				continue;
			}
			visibleIds.add(remote.peerId);
			let visual = this.#peers.get(remote.peerId);
			if (!visual) {
				visual = this.#createPeerVisual(remote);
				this.#peers.set(remote.peerId, visual);
				this.#root.add(visual.container);
			}
			this.#updatePeerTarget(visual, remote);
		}

		for (const [peerId, visual] of this.#peers) {
			if (!visibleIds.has(peerId)) {
				this.#removePeerVisual(visual);
				this.#peers.delete(peerId);
			}
		}
	}

	update(dt: number): void {
		if (this.#disposed || this.#peers.size === 0) {
			return;
		}
		const alpha = 1 - Math.exp(-Math.min(0.1, Math.max(0.001, dt)) * 14);

		for (const visual of this.#peers.values()) {
			if (!visual.initialized) {
				continue;
			}
			visual.currentPos.lerp(visual.targetPos, alpha);
			visual.currentQuat.slerp(visual.targetQuat, alpha);

			if (visual.targetJoints.length > 0) {
				if (visual.currentJoints.length !== visual.targetJoints.length) {
					visual.currentJoints = [...visual.targetJoints];
				} else {
					for (let i = 0; i < visual.targetJoints.length; i += 1) {
						const cur = visual.currentJoints[i] ?? 0;
						const tgt = visual.targetJoints[i] ?? 0;
						visual.currentJoints[i] = cur + (tgt - cur) * alpha;
					}
				}
			}

			if (visual.robotHandle) {
				applyArticulatedRobotThreePose(
					visual.robotHandle,
					visual.currentPos,
					visual.currentQuat,
					visual.currentJoints,
				);
			} else if (visual.beaconGroup) {
				visual.beaconGroup.position.copy(visual.currentPos);
				visual.beaconGroup.quaternion.copy(visual.currentQuat);
			}

			const labelHeight =
				visual.kind === "v3" ? 0.42 : visual.kind === "beacon" ? 0.5 : 0.3;
			visual.labelSprite.position.set(
				visual.currentPos.x,
				visual.currentPos.y + labelHeight,
				visual.currentPos.z,
			);
		}
	}

	dispose(): void {
		if (this.#disposed) {
			return;
		}
		this.#disposed = true;
		for (const visual of this.#peers.values()) {
			this.#removePeerVisual(visual);
		}
		this.#peers.clear();
		this.#scene.remove(this.#root);
	}

	#createPeerVisual(remote: MultiplayerRemotePlayer): RemotePeerVisual {
		const accentHex = peerAccentForId(remote.peerId);
		const container = new THREE.Group();
		container.name = `RemotePeer_${remote.peerId}`;

		const faceTexture = createPeerFaceTexture(accentHex);

		const labelCanvas = document.createElement("canvas");
		labelCanvas.width = 384;
		labelCanvas.height = 64;
		const labelText = this.#formatLabel(remote);
		paintNameplateTexture(labelCanvas, labelText, accentHex);
		const labelTexture = new THREE.CanvasTexture(labelCanvas);
		labelTexture.colorSpace = THREE.SRGBColorSpace;
		const labelMat = new THREE.SpriteMaterial({
			map: labelTexture,
			transparent: true,
			depthTest: false,
		});
		const labelSprite = new THREE.Sprite(labelMat);
		labelSprite.scale.set(0.46, 0.077, 1);
		labelSprite.renderOrder = 10;
		container.add(labelSprite);

		const beaconGroup = createBeaconAvatar(accentHex);
		container.add(beaconGroup);

		return {
			peerId: remote.peerId,
			container,
			accentHex,
			faceTexture,
			labelSprite,
			labelTexture,
			labelText,
			kind: "beacon",
			beaconGroup,
			currentPos: new THREE.Vector3(),
			targetPos: new THREE.Vector3(),
			currentQuat: new THREE.Quaternion(),
			targetQuat: new THREE.Quaternion(),
			currentJoints: [],
			targetJoints: [],
			initialized: false,
		};
	}

	#updatePeerTarget(
		visual: RemotePeerVisual,
		remote: MultiplayerRemotePlayer,
	): void {
		const [px, py, pz] = remote.pose.position;
		visual.targetPos.set(px, py, pz);
		if (remote.pose.rotation && remote.pose.rotation.length === 4) {
			visual.targetQuat.set(
				remote.pose.rotation[0],
				remote.pose.rotation[1],
				remote.pose.rotation[2],
				remote.pose.rotation[3],
			);
		}
		if (remote.pose.jointsDeg && remote.pose.jointsDeg.length > 0) {
			visual.targetJoints = [...remote.pose.jointsDeg];
		}

		if (!visual.initialized) {
			visual.currentPos.copy(visual.targetPos);
			visual.currentQuat.copy(visual.targetQuat);
			visual.currentJoints = [...visual.targetJoints];
			visual.initialized = true;
		}

		const nextLabel = this.#formatLabel(remote);
		if (nextLabel !== visual.labelText) {
			visual.labelText = nextLabel;
			const canvas = visual.labelTexture.image as HTMLCanvasElement;
			paintNameplateTexture(canvas, nextLabel, visual.accentHex);
			visual.labelTexture.needsUpdate = true;
		}

		const desiredModel = remote.pose.robotModel;
		if (
			(desiredModel === "v1" ||
				desiredModel === "v2" ||
				desiredModel === "v3") &&
			visual.kind !== desiredModel &&
			visual.loadingModel !== desiredModel
		) {
			void this.#upgradeToRobotModel(visual, desiredModel);
		}
	}

	async #upgradeToRobotModel(
		visual: RemotePeerVisual,
		modelId: RobotModelId,
	): Promise<void> {
		visual.loadingModel = modelId;
		try {
			const template = await this.#loadRobotTemplate(modelId);
			if (
				this.#disposed ||
				this.#peers.get(visual.peerId) !== visual ||
				visual.loadingModel !== modelId
			) {
				return;
			}
			const cloned = template.clone(true);
			const handle = bindArticulatedRobotClone(
				cloned,
				modelId,
				visual.faceTexture,
			);
			if (!handle) {
				return;
			}
			if (visual.robotHandle) {
				visual.container.remove(visual.robotHandle.group);
				disposeGroupResources(visual.robotHandle.group);
			}
			if (visual.beaconGroup) {
				visual.container.remove(visual.beaconGroup);
				disposeGroupResources(visual.beaconGroup);
				visual.beaconGroup = undefined;
			}
			visual.container.add(handle.group);
			visual.robotHandle = handle;
			visual.kind = modelId;
			visual.loadingModel = undefined;
			applyArticulatedRobotThreePose(
				handle,
				visual.currentPos,
				visual.currentQuat,
				visual.currentJoints,
			);
		} catch (err) {
			if (visual.loadingModel === modelId) {
				visual.loadingModel = undefined;
			}
			console.warn(
				`[simulator] Failed to load remote robot GLB (${modelId}):`,
				err,
			);
		}
	}

	#loadRobotTemplate(modelId: RobotModelId): Promise<THREE.Group> {
		const cached = this.#templateCache.get(modelId);
		if (cached) {
			return cached;
		}
		const desc = getRobotModelDescriptor(modelId);
		const promise = this.#gltfLoader
			.loadAsync(desc.glbUrl)
			.then((gltf) => gltf.scene)
			.catch((err) => {
				this.#templateCache.delete(modelId);
				throw err;
			});
		this.#templateCache.set(modelId, promise);
		return promise;
	}

	#formatLabel(remote: MultiplayerRemotePlayer): string {
		const baseName =
			remote.pose.displayName?.trim() || shortPeerLabel(remote.peerId);
		const tag = remote.pose.robotModel
			? remote.pose.robotModel.toUpperCase()
			: "PLAYER";
		return `${baseName} · ${tag}`;
	}

	#removePeerVisual(visual: RemotePeerVisual): void {
		this.#root.remove(visual.container);
		if (visual.robotHandle) {
			disposeGroupResources(visual.robotHandle.group);
		}
		if (visual.beaconGroup) {
			disposeGroupResources(visual.beaconGroup);
		}
		visual.labelSprite.material.dispose();
		visual.labelTexture.dispose();
		visual.faceTexture.dispose();
	}
}

/**
 * Standalone Three.js WebGL viewport for simulator.ainek.io.
 *
 * Owns the WebGLRenderer, PerspectiveCamera, Orbit/WASD navigation,
 * Follow V2 tracking camera, Robot POV chin camera mode, LevelSceneBuilder,
 * and ThreeVirtualRobotV2Rig.
 */

import * as THREE from "three";
import type { MultiplayerRemotePlayer } from "../multiplayer/index.js";
import {
	type LevelDefinition,
	ORBIT_PITCH_MAX_RAD,
	ORBIT_PITCH_MIN_RAD,
	type RobotModelId,
	type SimulatorCameraMode,
	type SimulatorLevelId,
	computeOrbitCameraPose,
} from "../sim/contracts";
import { LevelSceneBuilder } from "./levelSceneBuilder";
import { RemotePeerManager } from "./remotePeerManager";
import {
	ThreeVirtualRobotV2Rig,
	type VirtualRobotPoseInput,
} from "./virtualRobotRig";

export class SimulatorViewport {
	readonly #container: HTMLElement;
	readonly #renderer: THREE.WebGLRenderer;
	readonly #scene: THREE.Scene;
	readonly #camera: THREE.PerspectiveCamera;
	readonly #levelBuilder: LevelSceneBuilder;
	readonly #robotRig: ThreeVirtualRobotV2Rig;
	readonly #remotePeers: RemotePeerManager;
	readonly #resizeObserver: ResizeObserver;

	#cameraMode: SimulatorCameraMode = "orbit";
	#orbitTarget = new THREE.Vector3(0, 0.14, 0.12);
	#orbitYaw = 0.72;
	#orbitPitch = 0.36;
	#orbitDistance = 0.92;

	#dragging = false;
	#panMode = false;
	#lastPointerX = 0;
	#lastPointerY = 0;
	readonly #activePointers = new Map<number, { x: number; y: number }>();
	readonly #capturedPointers = new Set<number>();
	#pinchLastDist = 0;
	#pinchLastMidX = 0;
	#pinchLastMidY = 0;
	readonly #keysDown = new Set<string>();
	#lastFrameTime = performance.now();
	#rafId = 0;
	#disposed = false;

	constructor(container: HTMLElement) {
		this.#container = container;
		const width = Math.max(320, container.clientWidth || window.innerWidth);
		const height = Math.max(240, container.clientHeight || window.innerHeight);

		this.#renderer = new THREE.WebGLRenderer({
			antialias: true,
			powerPreference: "high-performance",
			preserveDrawingBuffer: false,
		});
		this.#renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
		this.#renderer.setSize(width, height, false);
		this.#renderer.shadowMap.enabled = true;
		this.#renderer.shadowMap.type = THREE.PCFSoftShadowMap;
		this.#renderer.toneMapping = THREE.ACESFilmicToneMapping;
		this.#renderer.toneMappingExposure = 1.08;
		this.#renderer.outputColorSpace = THREE.SRGBColorSpace;
		this.#renderer.domElement.style.width = "100%";
		this.#renderer.domElement.style.height = "100%";
		this.#renderer.domElement.style.display = "block";
		this.#renderer.domElement.style.cursor = "grab";
		this.#renderer.domElement.style.touchAction = "none";
		container.appendChild(this.#renderer.domElement);

		this.#scene = new THREE.Scene();
		const aspect = width / height;
		this.#camera = new THREE.PerspectiveCamera(
			aspect < 0.78 ? 56 : 48,
			aspect,
			0.015,
			180,
		);

		this.#levelBuilder = new LevelSceneBuilder(this.#scene);
		this.#robotRig = new ThreeVirtualRobotV2Rig(this.#scene, this.#renderer);
		this.#remotePeers = new RemotePeerManager(this.#scene);

		this.#bindInput();
		this.#resizeObserver = new ResizeObserver(() => this.#handleResize());
		this.#resizeObserver.observe(container);
		this.#syncOrbitCamera();
		this.#startRenderLoop();
	}

	async loadRobot(
		modelUrl = "/assets/robots/ainekio-v2.glb",
		modelId: RobotModelId = "v2",
	): Promise<void> {
		await this.#robotRig.load(modelUrl, modelId);
		if (modelId === "v3" && this.#orbitDistance < 0.95) {
			this.#orbitDistance = 1.15;
			this.#orbitTarget.y = Math.max(this.#orbitTarget.y, 0.18);
			this.#syncOrbitCamera();
		}
	}

	async loadLevel(level: LevelDefinition): Promise<void> {
		await this.#levelBuilder.loadLevel(level);
		this.#setOrbitFromVectors(
			new THREE.Vector3(
				level.defaultCameraPos[0],
				level.defaultCameraPos[1],
				level.defaultCameraPos[2],
			),
			new THREE.Vector3(
				level.defaultCameraTarget[0],
				level.defaultCameraTarget[1],
				level.defaultCameraTarget[2],
			),
		);
	}

	setCameraMode(mode: SimulatorCameraMode): void {
		this.#cameraMode = mode;
		this.#keysDown.clear();
		if (this.#dragging) {
			this.#dragging = false;
			this.#renderer.domElement.style.cursor = "grab";
		}
		if (mode === "orbit") {
			this.#camera.fov = this.#camera.aspect < 0.78 ? 56 : 48;
			this.#camera.updateProjectionMatrix();
		} else if (mode === "follow") {
			this.#camera.fov = 50;
			this.#camera.updateProjectionMatrix();
		} else {
			this.#camera.fov = 52;
			this.#camera.updateProjectionMatrix();
		}
	}

	focusRobot(): void {
		const pos = this.#robotRig.getWorldPosition();
		this.#orbitTarget.set(pos.x, Math.max(0.12, pos.y + 0.06), pos.z);
		this.#orbitDistance = 0.85;
		this.#syncOrbitCamera();
	}

	applyRobotPose(pose: VirtualRobotPoseInput): void {
		this.#robotRig.applyPose(pose);
	}

	syncRemotePeers(
		remotePlayers: readonly MultiplayerRemotePlayer[],
		localLevelId: SimulatorLevelId,
	): void {
		this.#remotePeers.syncPeers(remotePlayers, localLevelId);
	}

	updateFaceRgba(width: number, height: number, rgba: Uint8Array): void {
		this.#robotRig.updateFaceRgba(width, height, rgba);
	}

	captureChinCameraJpeg(
		width: number,
		height: number,
		quality = 0.78,
	): Promise<
		{ readonly jpeg: Uint8Array; readonly dataUrl: string } | undefined
	> {
		return this.#robotRig.captureChinCameraJpeg(width, height, quality);
	}

	#setOrbitFromVectors(camPos: THREE.Vector3, target: THREE.Vector3): void {
		this.#orbitTarget.copy(target);
		const offset = camPos.clone().sub(target);
		this.#orbitDistance = Math.max(0.22, Math.min(28, offset.length()));
		this.#orbitYaw = Math.atan2(offset.x, offset.z);
		const horiz = Math.hypot(offset.x, offset.z);
		this.#orbitPitch = Math.max(
			ORBIT_PITCH_MIN_RAD,
			Math.min(ORBIT_PITCH_MAX_RAD, Math.atan2(offset.y, horiz)),
		);
		this.#syncOrbitCamera();
	}

	#syncOrbitCamera(): void {
		const pose = computeOrbitCameraPose(
			[this.#orbitTarget.x, this.#orbitTarget.y, this.#orbitTarget.z],
			this.#orbitYaw,
			this.#orbitPitch,
			this.#orbitDistance,
		);
		this.#camera.position.set(
			pose.position[0],
			pose.position[1],
			pose.position[2],
		);
		this.#camera.lookAt(
			pose.lookTarget[0],
			pose.lookTarget[1],
			pose.lookTarget[2],
		);
	}

	#updateCameraFrame(dt: number): void {
		if (this.#cameraMode === "robot-pov" && this.#robotRig.loaded) {
			const pose = this.#robotRig.getChinCameraPose();
			this.#camera.position.copy(pose.position);
			this.#camera.quaternion.copy(pose.quaternion);
			return;
		}

		if (this.#cameraMode === "follow" && this.#robotRig.loaded) {
			const robotPos = this.#robotRig.getWorldPosition();
			const forward = this.#robotRig.getForwardWorldDirection();
			// Flatten forward vector onto XZ plane for comfortable behind-shoulder chase
			const flatFwd = new THREE.Vector3(forward.x, 0, forward.z);
			if (flatFwd.lengthSq() < 1e-4) {
				flatFwd.set(0, 0, 1);
			} else {
				flatFwd.normalize();
			}
			const desiredPos = new THREE.Vector3(
				robotPos.x - flatFwd.x * 0.72 + flatFwd.z * 0.16,
				Math.max(0.26, robotPos.y + 0.34),
				robotPos.z - flatFwd.z * 0.72 - flatFwd.x * 0.16,
			);
			const alpha = 1 - Math.exp(-dt * 6.5);
			this.#camera.position.lerp(desiredPos, alpha);
			const lookTarget = new THREE.Vector3(
				robotPos.x + flatFwd.x * 0.14,
				robotPos.y + 0.08,
				robotPos.z + flatFwd.z * 0.14,
			);
			this.#camera.lookAt(lookTarget);
			return;
		}

		// Orbit / Free WASD target movement
		if (this.#keysDown.size > 0) {
			const moveSpeed = Math.max(0.5, this.#orbitDistance * 1.1) * dt;
			const forward = new THREE.Vector3(
				-Math.sin(this.#orbitYaw),
				0,
				-Math.cos(this.#orbitYaw),
			);
			const right = new THREE.Vector3(
				Math.cos(this.#orbitYaw),
				0,
				-Math.sin(this.#orbitYaw),
			);
			if (this.#keysDown.has("KeyW") || this.#keysDown.has("ArrowUp")) {
				this.#orbitTarget.addScaledVector(forward, moveSpeed);
			}
			if (this.#keysDown.has("KeyS") || this.#keysDown.has("ArrowDown")) {
				this.#orbitTarget.addScaledVector(forward, -moveSpeed);
			}
			if (this.#keysDown.has("KeyD") || this.#keysDown.has("ArrowRight")) {
				this.#orbitTarget.addScaledVector(right, moveSpeed);
			}
			if (this.#keysDown.has("KeyA") || this.#keysDown.has("ArrowLeft")) {
				this.#orbitTarget.addScaledVector(right, -moveSpeed);
			}
			if (this.#keysDown.has("KeyE")) {
				this.#orbitTarget.y += moveSpeed * 0.7;
			}
			if (this.#keysDown.has("KeyQ")) {
				this.#orbitTarget.y = Math.max(
					0.05,
					this.#orbitTarget.y - moveSpeed * 0.7,
				);
			}
		}

		this.#syncOrbitCamera();
	}

	#startRenderLoop(): void {
		const tick = (now: number) => {
			if (this.#disposed) {
				return;
			}
			const dt = Math.min(
				0.1,
				Math.max(0.001, (now - this.#lastFrameTime) / 1000),
			);
			this.#lastFrameTime = now;
			this.#updateCameraFrame(dt);
			const focusPos =
				this.#cameraMode === "orbit"
					? this.#orbitTarget
					: this.#robotRig.getWorldPosition();
			this.#levelBuilder.update(now * 0.001, focusPos);
			this.#remotePeers.update(dt);
			this.#renderer.render(this.#scene, this.#camera);
			this.#rafId = requestAnimationFrame(tick);
		};
		this.#rafId = requestAnimationFrame(tick);
	}

	#handleResize(): void {
		if (this.#disposed) {
			return;
		}
		const width = Math.max(240, this.#container.clientWidth);
		const height = Math.max(200, this.#container.clientHeight);
		const aspect = width / height;
		this.#camera.aspect = aspect;
		if (this.#cameraMode === "orbit") {
			this.#camera.fov = aspect < 0.78 ? 56 : 48;
		}
		this.#camera.updateProjectionMatrix();
		this.#renderer.setSize(width, height, false);
	}

	#panOrbitBy(dx: number, dy: number): void {
		const panScale = this.#orbitDistance * 0.0018;
		const right = new THREE.Vector3(
			Math.cos(this.#orbitYaw),
			0,
			-Math.sin(this.#orbitYaw),
		);
		const forward = new THREE.Vector3(
			-Math.sin(this.#orbitYaw),
			0,
			-Math.cos(this.#orbitYaw),
		);
		this.#orbitTarget.addScaledVector(right, -dx * panScale);
		this.#orbitTarget.addScaledVector(forward, dy * panScale);
	}

	#onPointerDown = (event: PointerEvent) => {
		if (this.#cameraMode !== "orbit") {
			return;
		}
		this.#activePointers.set(event.pointerId, {
			x: event.clientX,
			y: event.clientY,
		});
		try {
			this.#renderer.domElement.setPointerCapture(event.pointerId);
			this.#capturedPointers.add(event.pointerId);
		} catch {
			// Ignore browsers that reject capture for inactive/synthetic pointers
		}

		if (this.#activePointers.size === 2) {
			const pts = [...this.#activePointers.values()];
			const a = pts[0];
			const b = pts[1];
			if (a && b) {
				this.#pinchLastDist = Math.max(1, Math.hypot(b.x - a.x, b.y - a.y));
				this.#pinchLastMidX = (a.x + b.x) * 0.5;
				this.#pinchLastMidY = (a.y + b.y) * 0.5;
			}
			this.#dragging = true;
			return;
		}

		this.#dragging = true;
		this.#panMode = event.button === 2 || event.shiftKey;
		this.#lastPointerX = event.clientX;
		this.#lastPointerY = event.clientY;
		this.#renderer.domElement.style.cursor = "grabbing";
	};

	#onPointerMove = (event: PointerEvent) => {
		if (!this.#dragging || this.#cameraMode !== "orbit") {
			return;
		}
		if (this.#activePointers.has(event.pointerId)) {
			this.#activePointers.set(event.pointerId, {
				x: event.clientX,
				y: event.clientY,
			});
		}

		// Two-finger pinch zoom + pan for touchscreens
		if (this.#activePointers.size >= 2) {
			const pts = [...this.#activePointers.values()];
			const a = pts[0];
			const b = pts[1];
			if (a && b) {
				const dist = Math.max(1, Math.hypot(b.x - a.x, b.y - a.y));
				const midX = (a.x + b.x) * 0.5;
				const midY = (a.y + b.y) * 0.5;
				if (this.#pinchLastDist > 0) {
					const ratio = this.#pinchLastDist / dist;
					this.#orbitDistance = Math.max(
						0.22,
						Math.min(28, this.#orbitDistance * ratio),
					);
					this.#panOrbitBy(
						midX - this.#pinchLastMidX,
						midY - this.#pinchLastMidY,
					);
				}
				this.#pinchLastDist = dist;
				this.#pinchLastMidX = midX;
				this.#pinchLastMidY = midY;
			}
			return;
		}

		const dx = event.clientX - this.#lastPointerX;
		const dy = event.clientY - this.#lastPointerY;
		this.#lastPointerX = event.clientX;
		this.#lastPointerY = event.clientY;

		if (this.#panMode) {
			this.#panOrbitBy(dx, dy);
		} else {
			this.#orbitYaw -= dx * 0.0065;
			this.#orbitPitch = Math.max(
				ORBIT_PITCH_MIN_RAD,
				Math.min(ORBIT_PITCH_MAX_RAD, this.#orbitPitch + dy * 0.0065),
			);
		}
	};

	#onPointerUp = (event: PointerEvent) => {
		this.#activePointers.delete(event.pointerId);
		if (this.#capturedPointers.delete(event.pointerId)) {
			try {
				if (this.#renderer.domElement.hasPointerCapture(event.pointerId)) {
					this.#renderer.domElement.releasePointerCapture(event.pointerId);
				}
			} catch {
				// Firefox may auto-release pointer capture before pointerup fires
			}
		}
		if (this.#activePointers.size === 1) {
			const remaining = [...this.#activePointers.values()][0];
			if (remaining) {
				this.#lastPointerX = remaining.x;
				this.#lastPointerY = remaining.y;
			}
			this.#pinchLastDist = 0;
			return;
		}
		this.#pinchLastDist = 0;
		if (!this.#dragging) {
			return;
		}
		this.#dragging = false;
		this.#renderer.domElement.style.cursor = "grab";
	};

	#onWheel = (event: WheelEvent) => {
		if (this.#cameraMode !== "orbit") {
			return;
		}
		event.preventDefault();
		const factor = event.deltaY > 0 ? 1.1 : 0.91;
		this.#orbitDistance = Math.max(
			0.22,
			Math.min(28, this.#orbitDistance * factor),
		);
	};

	#onContextMenu = (event: MouseEvent) => {
		event.preventDefault();
	};

	#onKeyDown = (event: KeyboardEvent) => {
		if (this.#cameraMode !== "orbit") {
			return;
		}
		const target = event.target as HTMLElement | null;
		if (
			target &&
			(target.tagName === "INPUT" ||
				target.tagName === "TEXTAREA" ||
				target.tagName === "SELECT" ||
				target.isContentEditable)
		) {
			return;
		}
		this.#keysDown.add(event.code);
	};

	#onKeyUp = (event: KeyboardEvent) => {
		this.#keysDown.delete(event.code);
	};

	#onWindowBlur = () => {
		this.#keysDown.clear();
	};

	#bindInput(): void {
		const el = this.#renderer.domElement;
		el.addEventListener("pointerdown", this.#onPointerDown);
		el.addEventListener("pointermove", this.#onPointerMove);
		el.addEventListener("pointerup", this.#onPointerUp);
		el.addEventListener("pointercancel", this.#onPointerUp);
		el.addEventListener("wheel", this.#onWheel, { passive: false });
		el.addEventListener("contextmenu", this.#onContextMenu);
		window.addEventListener("keydown", this.#onKeyDown);
		window.addEventListener("keyup", this.#onKeyUp);
		window.addEventListener("blur", this.#onWindowBlur);
	}

	dispose(): void {
		if (this.#disposed) {
			return;
		}
		this.#disposed = true;
		cancelAnimationFrame(this.#rafId);
		this.#resizeObserver.disconnect();
		const el = this.#renderer.domElement;
		el.removeEventListener("pointerdown", this.#onPointerDown);
		el.removeEventListener("pointermove", this.#onPointerMove);
		el.removeEventListener("pointerup", this.#onPointerUp);
		el.removeEventListener("pointercancel", this.#onPointerUp);
		el.removeEventListener("wheel", this.#onWheel);
		el.removeEventListener("contextmenu", this.#onContextMenu);
		window.removeEventListener("keydown", this.#onKeyDown);
		window.removeEventListener("keyup", this.#onKeyUp);
		window.removeEventListener("blur", this.#onWindowBlur);
		this.#robotRig.dispose();
		this.#remotePeers.dispose();
		this.#levelBuilder.dispose();
		this.#renderer.dispose();
		el.remove();
	}
}

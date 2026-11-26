/**
 * Detached Three.js level scene builder for simulator.ainek.io.
 *
 * Supports:
 *  - V2 Robotics Lab (default flat proving floor + fine metric grid + obstacles)
 *  - Lazy on-demand scene bundles for all 5 real game worlds:
 *      Observatory, Yggdrasil (Legacy), Miranda Wreck, Solitude (Legacy), Sci Fi Room
 *  - Full Three.js primitive geometry set (box, cylinder, cone, sphere, torus, octahedron)
 *  - URL-deduplicated lazy GLB/GLTF instancing (chunks stream nearest-to-spawn first)
 *  - Zero double-rendering: MuJoCo colliders stay physics-only when authored visuals exist
 */

import * as THREE from "three";
import { MeshoptDecoder } from "three/addons/libs/meshopt_decoder.module.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import {
	type ArenaHeightfield,
	type LevelDefinition,
	type ScenePrimitiveSpec,
	mujocoPositionToThree,
	versionedAssetUrl,
} from "../sim/contracts";

function buildGrassPlainTexture(): THREE.CanvasTexture | undefined {
	if (typeof document === "undefined") {
		return undefined;
	}
	const size = 256;
	const canvas = document.createElement("canvas");
	canvas.width = size;
	canvas.height = size;
	const ctx = canvas.getContext("2d");
	if (!ctx) {
		return undefined;
	}
	// Neutral bright base so Three.js vertexColors drive the exact meadow biome palette
	ctx.fillStyle = "#d8e0d2";
	ctx.fillRect(0, 0, size, size);

	// Deterministic pseudo-random organic grass blades, soil flecks & clover speckles
	let seed = 42197;
	const rand = () => {
		seed = (seed * 1664525 + 1013904223) >>> 0;
		return seed / 4294967296;
	};
	for (let i = 0; i < 2400; i += 1) {
		const x = rand() * size;
		const y = rand() * size;
		const len = 4 + rand() * 10;
		const ang = (rand() - 0.5) * 0.8 - Math.PI / 2;
		const shade = Math.round(175 + rand() * 75);
		const green = Math.min(255, shade + 18);
		ctx.strokeStyle = `rgba(${shade - 18}, ${green}, ${shade - 26}, ${0.28 + rand() * 0.36})`;
		ctx.lineWidth = 1 + rand() * 1.1;
		ctx.beginPath();
		ctx.moveTo(x, y);
		ctx.lineTo(x + Math.cos(ang) * len, y + Math.sin(ang) * len);
		ctx.stroke();
	}
	for (let i = 0; i < 420; i += 1) {
		const x = rand() * size;
		const y = rand() * size;
		const r = 1 + rand() * 2.2;
		ctx.fillStyle =
			i % 3 === 0 ? "rgba(110, 128, 92, 0.22)" : "rgba(225, 240, 200, 0.22)";
		ctx.beginPath();
		ctx.arc(x, y, r, 0, Math.PI * 2);
		ctx.fill();
	}

	const tex = new THREE.CanvasTexture(canvas);
	tex.colorSpace = THREE.SRGBColorSpace;
	tex.wrapS = THREE.RepeatWrapping;
	tex.wrapT = THREE.RepeatWrapping;
	tex.repeat.set(22, 22);
	tex.needsUpdate = true;
	return tex;
}

function buildLabGraphicTexture(
	primId: string,
): THREE.CanvasTexture | undefined {
	if (typeof document === "undefined") {
		return undefined;
	}
	if (primId.startsWith("lab_apriltag_")) {
		const size = 256;
		const canvas = document.createElement("canvas");
		canvas.width = size;
		canvas.height = size;
		const ctx = canvas.getContext("2d");
		if (!ctx) {
			return undefined;
		}
		const tagCode = primId.replace("lab_apriltag_", "").toUpperCase();
		let seed = 0x51a7;
		for (let i = 0; i < tagCode.length; i += 1) {
			seed = (seed * 131 + tagCode.charCodeAt(i)) >>> 0;
		}
		// High-contrast white quiet zone
		ctx.fillStyle = "#f8fafc";
		ctx.fillRect(0, 0, size, size);
		// Outer black fiducial border (8x8 grid with 1-cell border, 6x6 payload)
		const pad = 20;
		const gridPx = size - pad * 2;
		const cell = gridPx / 8;
		ctx.fillStyle = "#090d16";
		ctx.fillRect(pad, pad, gridPx, gridPx);
		for (let r = 1; r <= 6; r += 1) {
			for (let c = 1; c <= 6; c += 1) {
				seed = (seed * 1664525 + 1013904223) >>> 0;
				const white =
					(r === 1 && c === 1) ||
					(r === 6 && c === 6) ||
					((seed >>> 24) & 1) === 1;
				ctx.fillStyle = white ? "#f8fafc" : "#090d16";
				ctx.fillRect(
					pad + c * cell + 0.5,
					pad + r * cell + 0.5,
					cell - 1,
					cell - 1,
				);
			}
		}
		// Accent corner bar & crisp tag caption
		ctx.fillStyle = "#0284c7";
		ctx.fillRect(0, 0, size, 16);
		ctx.fillStyle = "#f8fafc";
		ctx.font = "bold 11px monospace";
		ctx.textAlign = "center";
		ctx.fillText(`AINEKIO FIDUCIAL · TAG-${tagCode}`, size / 2, 12);

		const tex = new THREE.CanvasTexture(canvas);
		tex.colorSpace = THREE.SRGBColorSpace;
		tex.needsUpdate = true;
		return tex;
	}

	if (primId.startsWith("lab_colorchecker_")) {
		const w = 384;
		const h = 256;
		const canvas = document.createElement("canvas");
		canvas.width = w;
		canvas.height = h;
		const ctx = canvas.getContext("2d");
		if (!ctx) {
			return undefined;
		}
		ctx.fillStyle = "#0f172a";
		ctx.fillRect(0, 0, w, h);
		// Header strip
		ctx.fillStyle = "#e2e8f0";
		ctx.font = "bold 14px monospace";
		ctx.textAlign = "left";
		ctx.fillText("VISION CALIBRATION · 24-PATCH TARGET", 16, 22);
		// Classic 6x4 Macbeth-style high-contrast color patches
		const palette = [
			"#735244",
			"#c29682",
			"#627a9d",
			"#576c43",
			"#8580b1",
			"#67bdaa",
			"#d67e2c",
			"#505ba6",
			"#c15a63",
			"#5e3c6c",
			"#9dbc40",
			"#e0a32e",
			"#383d96",
			"#469449",
			"#af363c",
			"#e7c71f",
			"#bb5695",
			"#0885a1",
			"#f3f3f2",
			"#c8c8c8",
			"#a0a0a0",
			"#7a7a79",
			"#555555",
			"#242424",
		];
		const cols = 6;
		const rows = 4;
		const marginX = 16;
		const marginY = 34;
		const gap = 8;
		const pw = (w - marginX * 2 - gap * (cols - 1)) / cols;
		const ph = (h - marginY - 16 - gap * (rows - 1)) / rows;
		for (let r = 0; r < rows; r += 1) {
			for (let c = 0; c < cols; c += 1) {
				ctx.fillStyle = palette[r * cols + c] ?? "#ffffff";
				ctx.fillRect(
					marginX + c * (pw + gap),
					marginY + r * (ph + gap),
					pw,
					ph,
				);
			}
		}
		const tex = new THREE.CanvasTexture(canvas);
		tex.colorSpace = THREE.SRGBColorSpace;
		tex.needsUpdate = true;
		return tex;
	}

	if (primId.startsWith("lab_checkerboard_")) {
		const w = 384;
		const h = 256;
		const canvas = document.createElement("canvas");
		canvas.width = w;
		canvas.height = h;
		const ctx = canvas.getContext("2d");
		if (!ctx) {
			return undefined;
		}
		ctx.fillStyle = "#f8fafc";
		ctx.fillRect(0, 0, w, h);
		const cols = 9;
		const rows = 6;
		const pad = 16;
		const cw = (w - pad * 2) / cols;
		const ch = (h - pad * 2 - 18) / rows;
		for (let r = 0; r < rows; r += 1) {
			for (let c = 0; c < cols; c += 1) {
				ctx.fillStyle = (r + c) % 2 === 0 ? "#0f172a" : "#f8fafc";
				ctx.fillRect(pad + c * cw, pad + 18 + r * ch, cw, ch);
			}
		}
		ctx.fillStyle = "#0f172a";
		ctx.font = "bold 12px monospace";
		ctx.textAlign = "center";
		ctx.fillText("OPTICAL CALIBRATION · 9x6 SLAM CHECKERBOARD", w / 2, 24);
		const tex = new THREE.CanvasTexture(canvas);
		tex.colorSpace = THREE.SRGBColorSpace;
		tex.needsUpdate = true;
		return tex;
	}

	if (primId.startsWith("lab_stopsign_")) {
		const size = 256;
		const canvas = document.createElement("canvas");
		canvas.width = size;
		canvas.height = size;
		const ctx = canvas.getContext("2d");
		if (!ctx) {
			return undefined;
		}
		ctx.fillStyle = "#dc2626";
		ctx.fillRect(0, 0, size, size);
		ctx.strokeStyle = "#f8fafc";
		ctx.lineWidth = 14;
		ctx.strokeRect(14, 14, size - 28, size - 28);
		ctx.fillStyle = "#ffffff";
		ctx.font = "bold 76px sans-serif";
		ctx.textAlign = "center";
		ctx.textBaseline = "middle";
		ctx.fillText("STOP", size / 2, size / 2 + 4);
		const tex = new THREE.CanvasTexture(canvas);
		tex.colorSpace = THREE.SRGBColorSpace;
		tex.needsUpdate = true;
		return tex;
	}

	if (primId.startsWith("lab_caution_")) {
		const size = 256;
		const canvas = document.createElement("canvas");
		canvas.width = size;
		canvas.height = size;
		const ctx = canvas.getContext("2d");
		if (!ctx) {
			return undefined;
		}
		ctx.fillStyle = "#facc15";
		ctx.fillRect(0, 0, size, size);
		ctx.fillStyle = "#111827";
		ctx.fillRect(0, 0, size, 32);
		ctx.fillRect(0, size - 32, size, 32);
		ctx.fillStyle = "#facc15";
		ctx.font = "bold 18px monospace";
		ctx.textAlign = "center";
		ctx.fillText("CAUTION · ROBOT AREA", size / 2, 22);
		// Warning triangle
		ctx.strokeStyle = "#111827";
		ctx.lineWidth = 12;
		ctx.beginPath();
		ctx.moveTo(size / 2, 54);
		ctx.lineTo(size - 48, 178);
		ctx.lineTo(48, 178);
		ctx.closePath();
		ctx.stroke();
		ctx.fillStyle = "#111827";
		ctx.font = "bold 76px sans-serif";
		ctx.fillText("!", size / 2, 162);
		ctx.font = "bold 16px monospace";
		ctx.fillText("AUTONOMOUS TESTING", size / 2, size - 10);
		const tex = new THREE.CanvasTexture(canvas);
		tex.colorSpace = THREE.SRGBColorSpace;
		tex.needsUpdate = true;
		return tex;
	}

	if (primId.startsWith("lab_screen_")) {
		const w = 512;
		const h = 256;
		const canvas = document.createElement("canvas");
		canvas.width = w;
		canvas.height = h;
		const ctx = canvas.getContext("2d");
		if (!ctx) {
			return undefined;
		}
		const isVision = primId.includes("vision");
		const isSlam = primId.includes("slam");
		ctx.fillStyle = "#06101f";
		ctx.fillRect(0, 0, w, h);
		ctx.strokeStyle = isSlam
			? "rgba(250, 204, 21, 0.42)"
			: isVision
				? "rgba(56, 189, 248, 0.35)"
				: "rgba(34, 197, 94, 0.35)";
		ctx.lineWidth = 2;
		ctx.strokeRect(8, 8, w - 16, h - 16);

		// Subtle telemetry grid
		ctx.strokeStyle = "rgba(148, 163, 184, 0.14)";
		ctx.lineWidth = 1;
		for (let gx = 40; gx < w - 16; gx += 40) {
			ctx.beginPath();
			ctx.moveTo(gx, 36);
			ctx.lineTo(gx, h - 18);
			ctx.stroke();
		}
		for (let gy = 56; gy < h - 16; gy += 36) {
			ctx.beginPath();
			ctx.moveTo(16, gy);
			ctx.lineTo(w - 16, gy);
			ctx.stroke();
		}

		ctx.fillStyle = isSlam ? "#facc15" : isVision ? "#38bdf8" : "#4ade80";
		ctx.font = "bold 16px monospace";
		ctx.fillText(
			isSlam
				? "SLAM OCCUPANCY MAP · 19m LAB PATH PLANNER"
				: isVision
					? "AUTONOMOUS VISION · APRILTAG & OBJECT MAP"
					: "AINEKIO PROVING LAB · 500 HZ MUJOCO TELEMETRY",
			20,
			28,
		);

		if (isSlam) {
			// Maze occupancy blocks & glowing A* path trajectory
			ctx.fillStyle = "rgba(56, 189, 248, 0.28)";
			const walls = [
				[46, 56, 14, 150],
				[46, 56, 210, 14],
				[242, 56, 14, 150],
				[108, 96, 14, 110],
				[176, 56, 14, 108],
				[108, 150, 82, 14],
			] as const;
			for (const [wx, wy, ww, wh] of walls) {
				ctx.fillRect(wx, wy, ww, wh);
			}
			ctx.strokeStyle = "#facc15";
			ctx.lineWidth = 3.5;
			ctx.beginPath();
			ctx.moveTo(78, 198);
			ctx.lineTo(78, 80);
			ctx.lineTo(146, 80);
			ctx.lineTo(146, 128);
			ctx.lineTo(212, 128);
			ctx.lineTo(212, 194);
			ctx.stroke();
			const zones = [
				["Z1 AGILITY RUNWAY", "CLEAR", "#38bdf8"],
				["Z2 RAMP & BEAM", "6.5 DEG", "#f59e0b"],
				["Z3 VISION GARDEN", "14 TARGETS", "#14b8a6"],
				["Z4 WAYPOINT MAZE", "TAG 05-08", "#a855f7"],
				["Z5 TERRAIN PIT", "HILL +18cm", "#4ade80"],
			] as const;
			zones.forEach(([name, stat, col], idx) => {
				const ry = 60 + idx * 35;
				ctx.fillStyle = "rgba(15, 23, 42, 0.85)";
				ctx.fillRect(280, ry, 212, 27);
				ctx.fillStyle = col;
				ctx.fillRect(280, ry, 4, 27);
				ctx.font = "bold 11px monospace";
				ctx.fillText(name, 292, ry + 17);
				ctx.fillStyle = "#e2e8f0";
				ctx.fillText(stat, 424, ry + 17);
			});
		} else if (isVision) {
			// Top-down radar map of lab landmarks
			ctx.strokeStyle = "#22d3ee";
			ctx.lineWidth = 2;
			ctx.beginPath();
			ctx.arc(135, 142, 76, 0, Math.PI * 2);
			ctx.stroke();
			ctx.beginPath();
			ctx.arc(135, 142, 42, 0, Math.PI * 2);
			ctx.stroke();
			const blips = [
				[110, 118, "#f43f5e", "BALL"],
				[168, 128, "#38bdf8", "CUBE"],
				[142, 178, "#facc15", "DUCK"],
				[95, 162, "#4ade80", "PLANT"],
				[162, 92, "#a855f7", "GATE"],
			] as const;
			for (const [bx, by, col, label] of blips) {
				ctx.fillStyle = col;
				ctx.beginPath();
				ctx.arc(bx, by, 5, 0, Math.PI * 2);
				ctx.fill();
				ctx.font = "bold 10px monospace";
				ctx.fillText(label, bx + 8, by + 3);
			}
			// Right column bounding-box list
			const rows = [
				["TAG-01 VISION", "CONF 99.4%", "#38bdf8"],
				["TAG-02 BRIDGE", "CONF 98.8%", "#22d3ee"],
				["RUBBER DUCK", "CONF 97.2%", "#facc15"],
				["SLALOM CONE", "CONF 99.1%", "#fb923c"],
				["GOAL PORTAL", "CONF 99.7%", "#4ade80"],
			] as const;
			rows.forEach(([name, conf, col], idx) => {
				const ry = 66 + idx * 34;
				ctx.fillStyle = "rgba(15, 23, 42, 0.85)";
				ctx.fillRect(250, ry, 238, 26);
				ctx.fillStyle = col;
				ctx.fillRect(250, ry, 4, 26);
				ctx.font = "bold 12px monospace";
				ctx.fillText(name, 262, ry + 17);
				ctx.fillStyle = "#cbd5e1";
				ctx.fillText(conf, 402, ry + 17);
			});
		} else {
			// Joint torque & gait phase waveforms
			const waves = [
				["#38bdf8", 0.045, 0, 96],
				["#f59e0b", 0.062, 1.4, 148],
				["#4ade80", 0.036, 2.7, 198],
			] as const;
			for (const [col, freq, phase, baseY] of waves) {
				ctx.strokeStyle = col;
				ctx.lineWidth = 2.5;
				ctx.beginPath();
				for (let x = 22; x <= w - 22; x += 6) {
					const y = baseY + Math.sin(x * freq + phase) * 18;
					if (x === 22) {
						ctx.moveTo(x, y);
					} else {
						ctx.lineTo(x, y);
					}
				}
				ctx.stroke();
			}
		}

		const tex = new THREE.CanvasTexture(canvas);
		tex.colorSpace = THREE.SRGBColorSpace;
		tex.needsUpdate = true;
		return tex;
	}

	return undefined;
}

async function buildHeightfieldTerrainMesh(
	hfield: ArenaHeightfield,
): Promise<THREE.Mesh> {
	const resp = await fetch(versionedAssetUrl(hfield.url));
	if (!resp.ok) {
		throw new Error(
			`Failed to load terrain heightfield ${hfield.url} (${resp.status})`,
		);
	}
	const buf = await resp.arrayBuffer();
	const header = new Int32Array(buf, 0, 2);
	const nrow = header[0] ?? 0;
	const ncol = header[1] ?? 0;
	const data = new Float32Array(buf, 8, nrow * ncol);

	const [posMjX, posMjY, posMjZ] = hfield.posMj;
	const [halfZ, halfX, elev] = hfield.sizeMj;

	const vertCount = nrow * ncol;
	const positions = new Float32Array(vertCount * 3);
	const uvs = new Float32Array(vertCount * 2);
	const colors = new Float32Array(vertCount * 3);

	const cLow = new THREE.Color("#294a2f"); // damp mossy hollow
	const cMeadow = new THREE.Color("#3b6b3a"); // lush twilight meadow grass
	const cSunlit = new THREE.Color("#5c8c49"); // sunlit grassy knoll crest
	const cPath = new THREE.Color("#63754a"); // worn olive-gold sanctuary trail
	const cHighland = new THREE.Color("#4a5f46"); // distant moorland ridge
	const cRock = new THREE.Color("#5d6670"); // upper highland slate
	const tmp = new THREE.Color();

	for (let r = 0; r < nrow; r += 1) {
		const u = nrow > 1 ? r / (nrow - 1) : 0;
		const tx = posMjY + (-1 + 2 * u) * halfX;
		for (let c = 0; c < ncol; c += 1) {
			const v = ncol > 1 ? c / (ncol - 1) : 0;
			const tz = posMjX + (-1 + 2 * v) * halfZ;
			const idx = r * ncol + c;
			const hNorm = data[idx] ?? 0;
			const ty = posMjZ + hNorm * elev;

			positions[idx * 3] = tx;
			positions[idx * 3 + 1] = ty;
			positions[idx * 3 + 2] = tz;
			uvs[idx * 2] = u;
			uvs[idx * 2 + 1] = v;

			// Organic biome color blending
			const dCenter = Math.hypot(tx, tz - posMjX);
			const patch =
				0.5 +
				0.5 * Math.sin(tx * 0.55 + tz * 0.35) * Math.cos(tx * 0.28 - tz * 0.62);

			if (ty < -0.04) {
				tmp.copy(cLow).lerp(cMeadow, Math.max(0, (ty + 0.16) / 0.12));
			} else if (ty > 0.45) {
				const tHigh = Math.min(1, (ty - 0.45) / 1.45);
				tmp.copy(cHighland).lerp(cRock, tHigh * 0.72);
			} else {
				const crest = Math.max(0, Math.min(1, ty / 0.32));
				tmp.copy(cMeadow).lerp(cSunlit, crest * 0.65 + patch * 0.22);
				// Subtle worn path & sanctuary ring tint
				if (dCenter < 4.9 && Math.abs(tx) < 0.7 && tz > -0.5 && tz < 9.8) {
					tmp.lerp(cPath, 0.38);
				} else if (dCenter < 2.2) {
					tmp.lerp(cPath, 0.24);
				}
			}
			colors[idx * 3] = tmp.r;
			colors[idx * 3 + 1] = tmp.g;
			colors[idx * 3 + 2] = tmp.b;
		}
	}

	const indices: number[] = [];
	indices.length = (nrow - 1) * (ncol - 1) * 6;
	let ptr = 0;
	for (let r = 0; r < nrow - 1; r += 1) {
		for (let c = 0; c < ncol - 1; c += 1) {
			const i00 = r * ncol + c;
			const i10 = (r + 1) * ncol + c;
			const i01 = r * ncol + (c + 1);
			const i11 = (r + 1) * ncol + (c + 1);
			// Winding produces +Y upward normals in Three.js right-handed coordinates
			indices[ptr++] = i00;
			indices[ptr++] = i01;
			indices[ptr++] = i11;
			indices[ptr++] = i00;
			indices[ptr++] = i11;
			indices[ptr++] = i10;
		}
	}

	const geom = new THREE.BufferGeometry();
	geom.setAttribute("position", new THREE.BufferAttribute(positions, 3));
	geom.setAttribute("uv", new THREE.BufferAttribute(uvs, 2));
	geom.setAttribute("color", new THREE.BufferAttribute(colors, 3));
	geom.setIndex(indices);
	geom.computeVertexNormals();

	const tex = buildGrassPlainTexture();
	const mat = new THREE.MeshStandardMaterial({
		vertexColors: true,
		map: tex ?? null,
		roughness: 0.94,
		metalness: 0.03,
		flatShading: true,
	});
	const mesh = new THREE.Mesh(geom, mat);
	mesh.receiveShadow = true;
	mesh.castShadow = false;
	mesh.name = "Level_HeightfieldTerrain";
	return mesh;
}

function disposeObject3D(root: THREE.Object3D): void {
	root.traverse((obj) => {
		if (obj instanceof THREE.Mesh) {
			obj.geometry.dispose();
			if (Array.isArray(obj.material)) {
				for (const mat of obj.material) {
					if (mat instanceof THREE.MeshStandardMaterial && mat.map) {
						mat.map.dispose();
					}
					mat.dispose();
				}
			} else {
				if (
					obj.material instanceof THREE.MeshStandardMaterial &&
					obj.material.map
				) {
					obj.material.map.dispose();
				}
				obj.material.dispose();
			}
		}
	});
}

function buildPrimitiveGeometry(
	spec: ScenePrimitiveSpec,
): THREE.BufferGeometry {
	const a = spec.args;
	switch (spec.shape) {
		case "cylinder":
			return new THREE.CylinderGeometry(
				a[0] ?? 0.5,
				a[1] ?? a[0] ?? 0.5,
				a[2] ?? 1,
				Math.max(6, Math.min(48, Math.round(a[3] ?? 16))),
			);
		case "cone":
			return new THREE.ConeGeometry(
				a[0] ?? 1,
				a[1] ?? 2,
				Math.max(6, Math.min(32, Math.round(a[2] ?? 12))),
			);
		case "sphere":
			return new THREE.SphereGeometry(
				a[0] ?? 1,
				Math.max(8, Math.min(28, Math.round(a[1] ?? 16))),
				Math.max(6, Math.min(20, Math.round(a[2] ?? 12))),
			);
		case "torus":
			return new THREE.TorusGeometry(
				a[0] ?? 2,
				a[1] ?? 0.35,
				Math.max(6, Math.min(24, Math.round(a[2] ?? 12))),
				Math.max(12, Math.min(60, Math.round(a[3] ?? 28))),
			);
		case "octahedron":
			return new THREE.OctahedronGeometry(
				a[0] ?? 1,
				Math.max(0, Math.min(2, Math.round(a[1] ?? 0))),
			);
		case "icosahedron":
			return new THREE.IcosahedronGeometry(
				a[0] ?? 1,
				Math.max(0, Math.min(2, Math.round(a[1] ?? 0))),
			);
		case "dodecahedron":
			return new THREE.DodecahedronGeometry(
				a[0] ?? 1,
				Math.max(0, Math.min(2, Math.round(a[1] ?? 0))),
			);
		default:
			return new THREE.BoxGeometry(a[0] ?? 1, a[1] ?? 1, a[2] ?? 1);
	}
}

export class LevelSceneBuilder {
	readonly #scene: THREE.Scene;
	readonly #gltfLoader: GLTFLoader;
	readonly #cubeLoader = new THREE.CubeTextureLoader();
	#levelGroup: THREE.Group | undefined;
	#skyboxTexture: THREE.CubeTexture | undefined;
	#loadGeneration = 0;
	#fireflyMeshes: Array<{
		readonly mesh: THREE.Mesh;
		readonly basePos: THREE.Vector3;
		readonly kind: "core" | "aura" | "wing_l" | "wing_r";
	}> = [];
	#fireflyLights: Array<{
		readonly light: THREE.PointLight;
		readonly basePos: THREE.Vector3;
		readonly baseIntensity: number;
	}> = [];
	#spaceDrifters: Array<{
		readonly mesh: THREE.Mesh;
		readonly basePos: THREE.Vector3;
		readonly baseRot: THREE.Euler;
		readonly seed: number;
		readonly mode:
			| "debris"
			| "star"
			| "holo"
			| "surreal-spin"
			| "surreal-float";
	}> = [];
	#pulsingLights: Array<{
		readonly light: THREE.PointLight;
		readonly baseIntensity: number;
		readonly speed: number;
		readonly depth: number;
	}> = [];
	#pendingChunks: Array<{
		readonly url: string;
		readonly centerX: number;
		readonly centerZ: number;
		readonly halfExtent: number;
		readonly instances: NonNullable<LevelDefinition["glbInstances"]>;
		loading: boolean;
		loaded: boolean;
	}> = [];
	#lastChunkCheckSec = -1;

	constructor(scene: THREE.Scene) {
		this.#scene = scene;
		this.#gltfLoader = new GLTFLoader();
		this.#gltfLoader.setMeshoptDecoder(MeshoptDecoder);
	}

	async loadLevel(level: LevelDefinition): Promise<void> {
		const generation = ++this.#loadGeneration;
		this.#clearCurrent();

		const group = new THREE.Group();
		group.name = `Level_${level.id}`;
		this.#levelGroup = group;
		this.#scene.add(group);

		// Background & fog
		this.#scene.background = new THREE.Color(level.backgroundHex);
		this.#scene.fog = new THREE.FogExp2(level.fogHex, level.fogDensity);

		// Skybox cubemap (non-blocking — falls back gracefully to solid backgroundHex)
		const skyUrls = [
			`${level.skyboxDir}/px.webp`,
			`${level.skyboxDir}/nx.webp`,
			`${level.skyboxDir}/py.webp`,
			`${level.skyboxDir}/ny.webp`,
			`${level.skyboxDir}/pz.webp`,
			`${level.skyboxDir}/nz.webp`,
		];
		this.#cubeLoader.load(
			skyUrls,
			(cubeTex) => {
				if (generation !== this.#loadGeneration) {
					cubeTex.dispose();
					return;
				}
				cubeTex.colorSpace = THREE.SRGBColorSpace;
				this.#skyboxTexture?.dispose();
				this.#skyboxTexture = cubeTex;
				this.#scene.background = cubeTex;
			},
			undefined,
			() => {
				// Solid backgroundHex stays active if skybox fails to load
			},
		);

		// Lighting rig
		const hemi = new THREE.HemisphereLight(
			level.ambientHex,
			"#0b1220",
			level.ambientIntensity,
		);
		group.add(hemi);

		const sun = new THREE.DirectionalLight(level.sunHex, level.sunIntensity);
		sun.position.set(level.sunPos[0], level.sunPos[1], level.sunPos[2]);
		sun.castShadow = true;
		sun.shadow.mapSize.set(1024, 1024);
		sun.shadow.camera.near = 0.5;
		sun.shadow.camera.far = 120;
		const shadowExtent = 14;
		sun.shadow.camera.left = -shadowExtent;
		sun.shadow.camera.right = shadowExtent;
		sun.shadow.camera.top = shadowExtent;
		sun.shadow.camera.bottom = -shadowExtent;
		sun.shadow.bias = -0.0005;
		group.add(sun);

		const rim = new THREE.DirectionalLight("#7dd3fc", 0.35);
		rim.position.set(-level.sunPos[0] * 0.6, 10, -level.sunPos[2] * 0.6);
		group.add(rim);

		// Optional authored point lights (e.g. Miranda Wreck, Sci Fi Room)
		if (level.lights && level.lights.length > 0) {
			for (const lt of level.lights.slice(0, 8)) {
				const pl = new THREE.PointLight(
					lt.color,
					lt.intensity,
					lt.distance,
					1.6,
				);
				pl.position.set(lt.pos[0], lt.pos[1], lt.pos[2]);
				group.add(pl);
				if (lt.id === "light_firefly") {
					this.#fireflyLights.push({
						light: pl,
						basePos: new THREE.Vector3(lt.pos[0], lt.pos[1], lt.pos[2]),
						baseIntensity: lt.intensity,
					});
				} else if (
					lt.id === "light_dying_star" ||
					lt.id === "light_reactor" ||
					lt.id === "light_spine_red"
				) {
					this.#pulsingLights.push({
						light: pl,
						baseIntensity: lt.intensity,
						speed: lt.id === "light_spine_red" ? 2.4 : 0.85,
						depth: lt.id === "light_spine_red" ? 0.35 : 0.18,
					});
				}
			}
		}

		// Optional procedural grassy heightfield terrain mesh (exact 1:1 match to MuJoCo <hfield>)
		if (level.terrainStyle === "grassy-plain" && level.hfield) {
			try {
				const terrainMesh = await buildHeightfieldTerrainMesh(level.hfield);
				if (generation !== this.#loadGeneration) {
					disposeObject3D(terrainMesh);
					return;
				}
				group.add(terrainMesh);
			} catch (err) {
				console.warn("[simulator] Failed to build heightfield terrain:", err);
			}
		}

		// Default flat ground plane (V2 Robotics Lab only; authored worlds supply real floor/terrain)
		if (level.useDefaultFloorPlane && level.floorSize > 0) {
			const floorGeom = new THREE.PlaneGeometry(
				level.floorSize,
				level.floorSize,
			);
			const floorMat = new THREE.MeshStandardMaterial({
				color: level.floorColor,
				roughness: 0.88,
				metalness: 0.08,
			});
			const floorMesh = new THREE.Mesh(floorGeom, floorMat);
			floorMesh.rotation.x = -Math.PI / 2;
			floorMesh.position.y = -0.001;
			floorMesh.receiveShadow = true;
			group.add(floorMesh);
		}

		if (level.showGrid && level.floorSize > 0) {
			const divisions = Math.max(20, Math.round(level.floorSize));
			const grid = new THREE.GridHelper(
				level.floorSize,
				divisions,
				"#38bdf8",
				"#1e293b",
			);
			grid.position.y = 0.001;
			const gridMat = grid.material as THREE.Material;
			gridMat.transparent = true;
			gridMat.opacity = 0.38;
			group.add(grid);

			const fineGrid = new THREE.GridHelper(4, 16, "#22d3ee", "#1e3a5f");
			fineGrid.position.y = 0.002;
			const fineMat = fineGrid.material as THREE.Material;
			fineMat.transparent = true;
			fineMat.opacity = 0.45;
			group.add(fineGrid);
		}

		// Optional ocean / water plane (Observatory & Yggdrasil)
		if (level.water) {
			const waterGeom = new THREE.PlaneGeometry(
				level.water.size,
				level.water.size,
			);
			const waterMat = new THREE.MeshStandardMaterial({
				color: level.water.color,
				roughness: 0.22,
				metalness: 0.45,
				transparent: level.water.opacity < 0.99,
				opacity: level.water.opacity,
			});
			const waterMesh = new THREE.Mesh(waterGeom, waterMat);
			waterMesh.rotation.x = -Math.PI / 2;
			waterMesh.position.y = level.water.y;
			waterMesh.receiveShadow = true;
			waterMesh.name = "Level_Water";
			group.add(waterMesh);
		}

		// Visual meshes for V2 Lab MuJoCo obstacles
		for (const obs of level.obstaclesMj) {
			const [tx, ty, tz] = mujocoPositionToThree(obs.posMj);
			const [hx, hy, hz] = obs.halfSizeMj;
			const geom = new THREE.BoxGeometry(hy * 2, hz * 2, hx * 2);
			const mat = new THREE.MeshStandardMaterial({
				color: obs.color,
				roughness: 0.55,
				metalness: 0.18,
			});
			const mesh = new THREE.Mesh(geom, mat);
			mesh.position.set(tx, ty, tz);
			mesh.castShadow = true;
			mesh.receiveShadow = true;
			mesh.name = `Obstacle_${obs.id}`;
			group.add(mesh);

			const edges = new THREE.EdgesGeometry(geom);
			const edgeLines = new THREE.LineSegments(
				edges,
				new THREE.LineBasicMaterial({
					color: "#e2e8f0",
					transparent: true,
					opacity: 0.22,
				}),
			);
			mesh.add(edgeLines);
		}

		// Scene primitives (Robotics Lab, Yggdrasil, Solitude, Miranda Wreck, Sci Fi Room)
		if (level.primitives && level.primitives.length > 0) {
			for (const prim of level.primitives) {
				const geom = buildPrimitiveGeometry(prim);
				const opacity = prim.opacity ?? 1;
				const labTex = buildLabGraphicTexture(prim.id);
				const mat = new THREE.MeshStandardMaterial({
					color: labTex ? "#ffffff" : prim.color,
					map: labTex ?? null,
					emissive: labTex
						? new THREE.Color(prim.emissive ?? "#ffffff")
						: prim.emissive
							? new THREE.Color(prim.emissive)
							: undefined,
					emissiveMap: labTex ?? null,
					emissiveIntensity: labTex
						? prim.emissiveIntensity ?? 0.42
						: prim.emissive
							? prim.emissiveIntensity ?? 0.35
							: 0,
					roughness: prim.roughness ?? 0.72,
					metalness: prim.metalness ?? 0.2,
					flatShading: prim.flatShading === true,
					transparent: opacity < 0.99,
					opacity,
				});
				const mesh = new THREE.Mesh(geom, mat);
				mesh.position.set(prim.pos[0], prim.pos[1], prim.pos[2]);
				mesh.quaternion.set(
					prim.quat[0],
					prim.quat[1],
					prim.quat[2],
					prim.quat[3],
				);
				mesh.scale.set(prim.scale[0], prim.scale[1], prim.scale[2]);
				mesh.castShadow = opacity >= 0.9;
				mesh.receiveShadow = true;
				mesh.name = prim.id;
				group.add(mesh);

				if (prim.id === "firefly_core") {
					this.#fireflyMeshes.push({
						mesh,
						basePos: mesh.position.clone(),
						kind: "core",
					});
				} else if (prim.id === "firefly_aura") {
					this.#fireflyMeshes.push({
						mesh,
						basePos: mesh.position.clone(),
						kind: "aura",
					});
				} else if (prim.id === "firefly_wing_l") {
					this.#fireflyMeshes.push({
						mesh,
						basePos: mesh.position.clone(),
						kind: "wing_l",
					});
				} else if (prim.id === "firefly_wing_r") {
					this.#fireflyMeshes.push({
						mesh,
						basePos: mesh.position.clone(),
						kind: "wing_r",
					});
				} else if (prim.id.startsWith("space_debris_")) {
					this.#spaceDrifters.push({
						mesh,
						basePos: mesh.position.clone(),
						baseRot: mesh.rotation.clone(),
						seed: this.#spaceDrifters.length * 1.37 + 0.5,
						mode: "debris",
					});
				} else if (prim.id.startsWith("dying_star_")) {
					this.#spaceDrifters.push({
						mesh,
						basePos: mesh.position.clone(),
						baseRot: mesh.rotation.clone(),
						seed: this.#spaceDrifters.length * 0.9,
						mode: "star",
					});
				} else if (prim.id.startsWith("holo_projection_")) {
					this.#spaceDrifters.push({
						mesh,
						basePos: mesh.position.clone(),
						baseRot: mesh.rotation.clone(),
						seed: this.#spaceDrifters.length * 1.1,
						mode: "holo",
					});
				} else if (prim.id.startsWith("surreal_spin_")) {
					this.#spaceDrifters.push({
						mesh,
						basePos: mesh.position.clone(),
						baseRot: mesh.rotation.clone(),
						seed: this.#spaceDrifters.length * 1.23 + 0.4,
						mode: "surreal-spin",
					});
				} else if (prim.id.startsWith("surreal_float_")) {
					this.#spaceDrifters.push({
						mesh,
						basePos: mesh.position.clone(),
						baseRot: mesh.rotation.clone(),
						seed: this.#spaceDrifters.length * 1.47 + 0.7,
						mode: "surreal-float",
					});
				}
			}
		}

		// Lazy on-demand GLB/GLTF instances (URL-deduplicated; nearest-to-spawn batch awaited first,
		// distant background chunks stream asynchronously without blocking controls)
		if (level.glbInstances && level.glbInstances.length > 0) {
			const uniqueUrls: string[] = [];
			for (const inst of level.glbInstances) {
				if (!uniqueUrls.includes(inst.url)) {
					uniqueUrls.push(inst.url);
				}
			}

			const loadBatch = async (urls: readonly string[]): Promise<void> => {
				await Promise.all(
					urls.map(async (url) => {
						try {
							const gltf = await this.#gltfLoader.loadAsync(url);
							if (generation !== this.#loadGeneration) {
								disposeObject3D(gltf.scene);
								return;
							}
							gltf.scene.traverse((obj) => {
								if (obj instanceof THREE.Mesh) {
									obj.castShadow = true;
									obj.receiveShadow = true;
								}
							});
							for (const inst of level.glbInstances ?? []) {
								if (inst.url !== url) {
									continue;
								}
								const clone = gltf.scene.clone(true);
								clone.position.set(inst.pos[0], inst.pos[1], inst.pos[2]);
								clone.quaternion.set(
									inst.quat[0],
									inst.quat[1],
									inst.quat[2],
									inst.quat[3],
								);
								clone.scale.set(inst.scale[0], inst.scale[1], inst.scale[2]);
								clone.name = inst.id;
								group.add(clone);
							}
						} catch (err) {
							console.warn(
								`[simulator] Level asset load warning (${url}):`,
								err,
							);
						}
					}),
				);
			};

			const batchSize = 4;
			// Await the nearest batch immediately so the spawn area is fully rendered
			await loadBatch(uniqueUrls.slice(0, batchSize));

			// For large chunked worlds (e.g. Observatory 4x4 terrain grid), defer distant chunks
			// and stream them on demand as the robot or camera moves within range instead of
			// downloading tens of megabytes of far terrain unconditionally on mobile/desktop.
			if (uniqueUrls.length > batchSize) {
				const remaining = uniqueUrls.slice(batchSize);
				const chunkPattern = /chunk_(\d+)_(\d+)_LOD/i;
				const allChunked = remaining.every((u) => chunkPattern.test(u));
				if (allChunked) {
					for (const url of remaining) {
						const match = chunkPattern.exec(url);
						const cx = Number(match?.[1] ?? 0);
						const cz = Number(match?.[2] ?? 0);
						const matchingInstances = (level.glbInstances ?? []).filter(
							(inst) => inst.url === url,
						);
						const refPos = matchingInstances[0]?.pos ?? [0, 0, 0];
						this.#pendingChunks.push({
							url,
							centerX: refPos[0] + (-150 + cx * 100),
							centerZ: refPos[2] + (-150 + cz * 100),
							halfExtent: 50,
							instances: matchingInstances,
							loading: false,
							loaded: false,
						});
					}
					this.#lastChunkCheckSec = -1;
				} else {
					void (async () => {
						for (let i = batchSize; i < uniqueUrls.length; i += batchSize) {
							if (generation !== this.#loadGeneration) {
								return;
							}
							await loadBatch(uniqueUrls.slice(i, i + batchSize));
						}
					})();
				}
			}
		}
	}

	#streamNearbyChunks(focusPos: THREE.Vector3): void {
		const group = this.#levelGroup;
		if (!group || this.#pendingChunks.length === 0) {
			return;
		}
		const generation = this.#loadGeneration;
		const nav =
			typeof navigator !== "undefined"
				? (navigator as Navigator & {
						connection?: { saveData?: boolean };
					})
				: undefined;
		const isConstrained =
			Boolean(nav?.connection?.saveData) ||
			(typeof window !== "undefined" && window.innerWidth < 768);
		const streamRadius = isConstrained ? 85 : 120;

		let activeLoads = 0;
		for (const chunk of this.#pendingChunks) {
			if (chunk.loading) {
				activeLoads += 1;
			}
		}
		if (activeLoads >= 2) {
			return;
		}

		for (const chunk of this.#pendingChunks) {
			if (chunk.loaded || chunk.loading) {
				continue;
			}
			const dx = Math.max(
				0,
				Math.abs(focusPos.x - chunk.centerX) - chunk.halfExtent,
			);
			const dz = Math.max(
				0,
				Math.abs(focusPos.z - chunk.centerZ) - chunk.halfExtent,
			);
			if (Math.hypot(dx, dz) > streamRadius) {
				continue;
			}
			chunk.loading = true;
			activeLoads += 1;
			void this.#gltfLoader
				.loadAsync(chunk.url)
				.then((gltf) => {
					if (
						generation !== this.#loadGeneration ||
						this.#levelGroup !== group
					) {
						disposeObject3D(gltf.scene);
						return;
					}
					gltf.scene.traverse((obj) => {
						if (obj instanceof THREE.Mesh) {
							obj.castShadow = true;
							obj.receiveShadow = true;
						}
					});
					for (const inst of chunk.instances) {
						const clone = gltf.scene.clone(true);
						clone.position.set(inst.pos[0], inst.pos[1], inst.pos[2]);
						clone.quaternion.set(
							inst.quat[0],
							inst.quat[1],
							inst.quat[2],
							inst.quat[3],
						);
						clone.scale.set(inst.scale[0], inst.scale[1], inst.scale[2]);
						clone.name = inst.id;
						group.add(clone);
					}
					chunk.loaded = true;
					chunk.loading = false;
				})
				.catch((err) => {
					chunk.loading = false;
					console.warn(
						`[simulator] Deferred chunk load warning (${chunk.url}):`,
						err,
					);
				});
			if (activeLoads >= 2) {
				break;
			}
		}
	}

	update(timeSec: number, focusPos?: THREE.Vector3): void {
		if (
			focusPos &&
			this.#pendingChunks.length > 0 &&
			(this.#lastChunkCheckSec < 0 || timeSec - this.#lastChunkCheckSec >= 0.35)
		) {
			this.#lastChunkCheckSec = timeSec;
			this.#streamNearbyChunks(focusPos);
		}
		if (this.#fireflyMeshes.length > 0 || this.#fireflyLights.length > 0) {
			// Serene, lonely floating figure-eight drift + gentle wing flutter & golden pulse
			const dx = Math.sin(timeSec * 0.52) * 0.26;
			const dy =
				Math.sin(timeSec * 1.15) * 0.11 + Math.cos(timeSec * 0.43) * 0.05;
			const dz = Math.sin(timeSec * 0.26) * Math.cos(timeSec * 0.52) * 0.22;
			const pulse = 0.86 + 0.24 * Math.sin(timeSec * 2.1);

			for (const item of this.#fireflyMeshes) {
				item.mesh.position.set(
					item.basePos.x + dx,
					item.basePos.y + dy,
					item.basePos.z + dz,
				);
				if (item.kind === "aura") {
					const s = 0.92 + 0.16 * Math.sin(timeSec * 2.1);
					item.mesh.scale.setScalar(s);
				} else if (item.kind === "wing_l") {
					item.mesh.rotation.z = 0.42 + Math.sin(timeSec * 16.0) * 0.28;
				} else if (item.kind === "wing_r") {
					item.mesh.rotation.z = -0.42 - Math.sin(timeSec * 16.0) * 0.28;
				}
			}
			for (const item of this.#fireflyLights) {
				item.light.position.set(
					item.basePos.x + dx,
					item.basePos.y + dy,
					item.basePos.z + dz,
				);
				item.light.intensity = item.baseIntensity * pulse;
			}
		}

		// Zero-G asteroid & sheared hull debris drift + Dying Star & Bridge hologram animation
		for (const item of this.#spaceDrifters) {
			if (item.mode === "debris") {
				item.mesh.position.y =
					item.basePos.y + Math.sin(timeSec * 0.32 + item.seed) * 0.35;
				item.mesh.rotation.x = item.baseRot.x + timeSec * 0.06;
				item.mesh.rotation.y = item.baseRot.y + timeSec * 0.09;
			} else if (item.mode === "star") {
				item.mesh.rotation.y = item.baseRot.y + timeSec * 0.04;
				item.mesh.rotation.z = item.baseRot.z + timeSec * 0.02;
			} else if (item.mode === "surreal-spin") {
				const dir = Math.floor(item.seed) % 2 === 0 ? 1 : -1;
				item.mesh.rotation.y = item.baseRot.y + timeSec * 0.32 * dir;
				item.mesh.rotation.x = item.baseRot.x + timeSec * 0.18 * dir;
			} else if (item.mode === "surreal-float") {
				item.mesh.position.y =
					item.basePos.y + Math.sin(timeSec * 0.85 + item.seed) * 0.075;
				item.mesh.rotation.y = item.baseRot.y + timeSec * 0.14;
			} else {
				item.mesh.rotation.y = item.baseRot.y + timeSec * 0.55;
				item.mesh.position.y =
					item.basePos.y + Math.sin(timeSec * 1.4 + item.seed) * 0.025;
			}
		}
		for (const item of this.#pulsingLights) {
			item.light.intensity =
				item.baseIntensity *
				(1.0 + Math.sin(timeSec * item.speed) * item.depth);
		}
	}

	#clearCurrent(): void {
		this.#fireflyMeshes = [];
		this.#fireflyLights = [];
		this.#spaceDrifters = [];
		this.#pulsingLights = [];
		this.#pendingChunks = [];
		this.#lastChunkCheckSec = -1;
		if (this.#levelGroup) {
			this.#scene.remove(this.#levelGroup);
			disposeObject3D(this.#levelGroup);
			this.#levelGroup = undefined;
		}
	}

	dispose(): void {
		this.#loadGeneration += 1;
		this.#clearCurrent();
		this.#skyboxTexture?.dispose();
		this.#skyboxTexture = undefined;
	}
}

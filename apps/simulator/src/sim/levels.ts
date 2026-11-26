import {
	type LazyLevelBundle,
	type LevelDefinition,
	type SimulatorLevelId,
	versionedAssetUrl,
} from "./contracts.js";

/**
 * Lightweight level catalog for the Cockpit dropdown.
 * Every arena (Robotics Lab + the 5 worlds: Observatory, Yggdrasil, Miranda Wreck,
 * Solitude, Sci Fi Room) loads its scene JSON, terrain heightfield, and GLB assets
 * lazily on demand when selected.
 */
export const SIMULATOR_LEVELS: readonly LevelDefinition[] = [
	{
		id: "v2_lab",
		name: "Robotics Lab (Obstacle Course)",
		subtitle:
			"19m multi-zone proving ground · agility runway, maze, ramp bridge, terrain pit, AprilTags & vision targets",
		lazyBundleUrl: "/sim/levels/v2-lab.level.json",
		skyboxDir: "/assets/skyboxes/classic",
		backgroundHex: "#101a2c",
		fogHex: "#142238",
		fogDensity: 0.0052,
		ambientHex: "#d8e8ff",
		ambientIntensity: 1.12,
		sunHex: "#fffaf0",
		sunIntensity: 1.72,
		sunPos: [8, 14, 6],
		floorColor: "#253244",
		floorSize: 24,
		showGrid: true,
		useDefaultFloorPlane: true,
		obstaclesMj: [],
		audio: {
			label: "Portal Deck",
			track: "/audio/ambient/portal-deck.mp3",
			volume: 0.32,
			surfaceAcoustic: "metal",
		},
		robotSpawnMj: [0, 0, 0.066],
		defaultCameraPos: [0.58, 0.36, -0.82],
		defaultCameraTarget: [0.0, 0.14, 0.52],
	},
	{
		id: "observatory",
		name: "Observatory",
		subtitle:
			"Coastal stone observatory · chunked terrain & MuJoCo heightfield",
		lazyBundleUrl: "/sim/levels/observatory.level.json",
		skyboxDir: "/assets/skyboxes/observatory",
		backgroundHex: "#202c40",
		fogHex: "#596784",
		fogDensity: 0.0012,
		ambientHex: "#c9d8f2",
		ambientIntensity: 0.85,
		sunHex: "#f5f7ff",
		sunIntensity: 1.5,
		sunPos: [40, 80, -35],
		floorColor: "#2c3440",
		floorSize: 0,
		showGrid: false,
		useDefaultFloorPlane: false,
		obstaclesMj: [],
		audio: {
			label: "Portal Deck",
			track: "/audio/ambient/portal-deck.mp3",
			volume: 0.34,
			surfaceAcoustic: "stone",
		},
		robotSpawnMj: [0, 0, 0.066],
		defaultCameraPos: [0.54, 0.22, 0.68],
		defaultCameraTarget: [0, 0.12, 0.0],
	},
	{
		id: "yggdrasil",
		name: "Yggdrasil (Tree of Life)",
		subtitle:
			"Colossal 27m Norse World Tree · Bifrost, cathedral roots, ramps, slalom & wells",
		lazyBundleUrl: "/sim/levels/yggdrasil.level.json",
		skyboxDir: "/assets/skyboxes/observatory",
		backgroundHex: "#0b1626",
		fogHex: "#132845",
		fogDensity: 0.0042,
		ambientHex: "#c6e0fc",
		ambientIntensity: 1.12,
		sunHex: "#ffe6bf",
		sunIntensity: 1.75,
		sunPos: [18, 34, -16],
		floorColor: "#2a4f30",
		floorSize: 0,
		showGrid: false,
		useDefaultFloorPlane: false,
		obstaclesMj: [],
		audio: {
			label: "Shadow Waltz",
			track: "/audio/ambient/shadow-waltz.mp3",
			volume: 0.36,
			surfaceAcoustic: "meadow",
			regions: [
				{
					id: "yggdrasil-mimir",
					label: "Well of Mimir",
					track: "/audio/ambient/untitled.mp3",
					posThree: [-7.0, 0.2, 6.6],
					radius: 2.4,
					falloff: 2.8,
					volume: 0.34,
				},
				{
					id: "yggdrasil-jotunheim",
					label: "Jotunheim Bridge",
					track: "/audio/ambient/dark-shadows-of-delight.mp3",
					posThree: [-4.8, 0.2, 10.6],
					radius: 2.3,
					falloff: 2.6,
					volume: 0.34,
				},
				{
					id: "yggdrasil-valhalla",
					label: "Valhalla Circle",
					track: "/audio/ambient/wicked-shadows-whisper.mp3",
					posThree: [4.8, 0.2, 11.2],
					radius: 2.4,
					falloff: 2.6,
					volume: 0.34,
				},
			],
		},
		robotSpawnMj: [0, 0, 0.066],
		defaultCameraPos: [0.95, 0.36, -1.42],
		defaultCameraTarget: [0, 0.92, 2.25],
	},
	{
		id: "miranda",
		name: "Miranda Wreck",
		subtitle:
			"Derelict starship · Bridge stairs, Crew Quarters, Mess Hall, Asteroid Field & Dying Star",
		lazyBundleUrl: "/sim/levels/miranda.level.json",
		skyboxDir: "/assets/skyboxes/classic",
		backgroundHex: "#04060c",
		fogHex: "#080c16",
		fogDensity: 0.0062,
		ambientHex: "#93b0d4",
		ambientIntensity: 0.96,
		sunHex: "#fca5a5",
		sunIntensity: 1.35,
		sunPos: [4, 16, 28],
		floorColor: "#232a35",
		floorSize: 0,
		showGrid: false,
		useDefaultFloorPlane: false,
		obstaclesMj: [],
		audio: {
			label: "Dark Shadows of Delight",
			track: "/audio/ambient/dark-shadows-of-delight.mp3",
			volume: 0.34,
			surfaceAcoustic: "metal",
		},
		robotSpawnMj: [0, 0, 0.066],
		defaultCameraPos: [0.58, 0.42, -1.12],
		defaultCameraTarget: [0, 0.78, 3.8],
	},
	{
		id: "solitude",
		name: "Solitude (Stonehenge Plain)",
		subtitle:
			"Glowing ancient Stonehenge, rolling grassy plain & the single firefly",
		lazyBundleUrl: "/sim/levels/solitude.level.json",
		skyboxDir: "/assets/skyboxes/observatory",
		backgroundHex: "#121b2d",
		fogHex: "#1c2a42",
		fogDensity: 0.0052,
		ambientHex: "#c8dcf2",
		ambientIntensity: 1.02,
		sunHex: "#ffe6c4",
		sunIntensity: 1.55,
		sunPos: [18, 28, -14],
		floorColor: "#3f6a3c",
		floorSize: 0,
		showGrid: false,
		useDefaultFloorPlane: false,
		terrainStyle: "grassy-plain",
		obstaclesMj: [],
		audio: {
			label: "Wicked Shadows Whisper",
			track: "/audio/ambient/wicked-shadows-whisper.mp3",
			volume: 0.34,
			surfaceAcoustic: "meadow",
		},
		robotSpawnMj: [0, 0, 0.066],
		defaultCameraPos: [0.88, 0.38, -1.28],
		defaultCameraTarget: [0, 0.68, 2.55],
	},
	{
		id: "sci-fi-room",
		name: "Sci Fi Room (Astral House)",
		subtitle:
			"Surreal far-future house · Chronos-Orrery, Escher stairs, crystal garden & portals",
		lazyBundleUrl: "/sim/levels/sci-fi-room.level.json",
		skyboxDir: "/assets/skyboxes/observatory",
		backgroundHex: "#0d1026",
		fogHex: "#1b1f42",
		fogDensity: 0.0044,
		ambientHex: "#dbeafe",
		ambientIntensity: 1.15,
		sunHex: "#fef3c7",
		sunIntensity: 1.55,
		sunPos: [14, 24, -12],
		floorColor: "#d8dee9",
		floorSize: 0,
		showGrid: false,
		useDefaultFloorPlane: false,
		obstaclesMj: [],
		audio: {
			label: "Whistling Dreams",
			track: "/audio/ambient/whistling-dreams.mp3",
			volume: 0.34,
			surfaceAcoustic: "stone",
		},
		robotSpawnMj: [0, 0, 0.066],
		defaultCameraPos: [0.92, 0.44, -1.35],
		defaultCameraTarget: [0, 1.15, 3.6],
	},
];

const lazyBundleCache = new Map<SimulatorLevelId, LevelDefinition>();

export function getSimulatorLevel(id: SimulatorLevelId): LevelDefinition {
	const match = SIMULATOR_LEVELS.find((lvl) => lvl.id === id);
	if (!match) {
		return SIMULATOR_LEVELS[0] as LevelDefinition;
	}
	return lazyBundleCache.get(match.id) ?? match;
}

/**
 * Lazily fetch and hydrate a level's scene primitives, GLB instances,
 * MuJoCo colliders, and optional heightfield on demand.
 */
export async function loadSimulatorLevel(
	id: SimulatorLevelId,
): Promise<LevelDefinition> {
	const cached = lazyBundleCache.get(id);
	if (cached) {
		return cached;
	}
	const base = getSimulatorLevel(id);
	if (!base.lazyBundleUrl) {
		return base;
	}
	const resp = await fetch(versionedAssetUrl(base.lazyBundleUrl));
	if (!resp.ok) {
		throw new Error(
			`Failed to load level bundle ${base.lazyBundleUrl} (${resp.status})`,
		);
	}
	const bundle = (await resp.json()) as LazyLevelBundle;
	const hydrated: LevelDefinition = {
		...base,
		name: bundle.name || base.name,
		subtitle: bundle.subtitle || base.subtitle,
		skyboxDir: bundle.skyboxDir || base.skyboxDir,
		backgroundHex: bundle.backgroundHex || base.backgroundHex,
		fogHex: bundle.fogHex || base.fogHex,
		fogDensity: bundle.fogDensity ?? base.fogDensity,
		useDefaultFloorPlane: bundle.useDefaultFloorPlane,
		terrainStyle: bundle.terrainStyle ?? base.terrainStyle,
		robotSpawnMj: bundle.robotSpawnMj,
		primitives: bundle.primitives,
		glbInstances: bundle.glbInstances,
		collidersMj: bundle.colliders,
		hfield: bundle.hfield,
		lights: bundle.lights,
		water: bundle.water,
	};
	lazyBundleCache.set(id, hydrated);
	return hydrated;
}

/**
 * World Music, Spatial Audio Regions, Original UI/Portal SFX, and MuJoCo
 * Foot-Contact Acoustic Engine for simulator.ainek.io.
 *
 * - Zero third-party audio dependencies (native HTMLAudioElement + Web Audio API).
 * - Strictly lazy on demand: zero audio tracks or SFX are fetched until the
 *   user unlocks audio via first gesture or audio button, and only the active
 *   level's soundtrack (and nearby spatial regions) are loaded.
 * - Coexists cleanly with BrowserRobotAudioAdapter (ducks music softly while
 *   the virtual ESP32-P4 robot's speaker is actively talking).
 */

import {
	type LevelAudioSpec,
	type SimulatorAudioState,
	type WorldSfxId,
	mujocoPositionToThree,
} from "../sim/contracts";

type SfxDef = {
	readonly src: string;
	readonly volume: number;
	readonly rate?: number;
	readonly rateJitter?: number;
	readonly cooldownMs?: number;
};

export const WORLD_SFX_CATALOG: Record<WorldSfxId, SfxDef> = {
	select: {
		src: "/audio/sfx/select-click.mp3",
		volume: 0.42,
		rateJitter: 0.03,
		cooldownMs: 70,
	},
	soft: {
		src: "/audio/sfx/interface-click-tone.mp3",
		volume: 0.22,
		rateJitter: 0.03,
		cooldownMs: 65,
	},
	open: {
		src: "/audio/sfx/interface-open.mp3",
		volume: 0.38,
		rateJitter: 0.03,
		cooldownMs: 120,
	},
	back: {
		src: "/audio/sfx/interface-back.mp3",
		volume: 0.3,
		rateJitter: 0.03,
		cooldownMs: 100,
	},
	sweep: {
		src: "/audio/sfx/interface-sweep.mp3",
		volume: 0.24,
		rate: 0.96,
		rateJitter: 0.04,
		cooldownMs: 100,
	},
	"portal-activate": {
		src: "/audio/sfx/portal-activate.mp3",
		volume: 0.4,
		rateJitter: 0.02,
		cooldownMs: 450,
	},
	"portal-awaken": {
		src: "/audio/sfx/portal-awaken.mp3",
		volume: 0.32,
		rateJitter: 0.02,
		cooldownMs: 500,
	},
	"portal-impact": {
		src: "/audio/sfx/portal-impact.mp3",
		volume: 0.44,
		rate: 0.85,
		rateJitter: 0.05,
		cooldownMs: 220,
	},
	"portal-reveal": {
		src: "/audio/sfx/portal-reveal.mp3",
		volume: 0.32,
		rateJitter: 0.03,
		cooldownMs: 250,
	},
};

const STORAGE_KEY = "ainekio_sim_audio_v1";

type PersistedAudioPrefs = {
	enabled?: boolean;
	musicVolume?: number;
	sfxVolume?: number;
	footstepsEnabled?: boolean;
};

type MusicChannel = {
	readonly src: string;
	readonly label: string;
	readonly element: HTMLAudioElement;
	currentVolume: number;
	targetVolume: number;
	playRequested: boolean;
};

function clamp01(value: number): number {
	return Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
}

export class WorldAudioEngine {
	readonly #onStateChange?: (() => void) | undefined;
	#audioCtx: AudioContext | undefined;
	#sfxMasterGain: GainNode | undefined;
	#sfxBufferCache = new Map<string, AudioBuffer>();
	#sfxInFlight = new Map<string, Promise<AudioBuffer | undefined>>();
	#sfxLastPlayedMs = new Map<string, number>();

	#channels = new Map<string, MusicChannel>();
	#fadeTimer: number | undefined;
	#activeLevelAudio: LevelAudioSpec | undefined;
	#lastRobotPosThree: [number, number, number] = [0, 0, 0];

	#enabled = true;
	#unlocked = false;
	#musicVolume = 0.55;
	#sfxVolume = 0.7;
	#footstepsEnabled = true;
	#duckedByRobotSpeech = false;
	#activeTrackLabel = "";

	#prevFootContacts: [boolean, boolean, boolean, boolean] = [
		false,
		false,
		false,
		false,
	];
	#lastFootTapMs: [number, number, number, number] = [0, 0, 0, 0];
	#noiseBuffer: AudioBuffer | undefined;
	#disposed = false;

	constructor(onStateChange?: () => void) {
		this.#onStateChange = onStateChange;
		this.#loadPrefs();
	}

	getState(): SimulatorAudioState {
		let playing = false;
		for (const ch of this.#channels.values()) {
			if (!ch.element.paused && ch.currentVolume > 0.004) {
				playing = true;
				break;
			}
		}
		return {
			enabled: this.#enabled,
			unlocked: this.#unlocked,
			playing,
			musicVolume: this.#musicVolume,
			sfxVolume: this.#sfxVolume,
			footstepsEnabled: this.#footstepsEnabled,
			activeTrackLabel:
				this.#activeTrackLabel || this.#activeLevelAudio?.label || "",
		};
	}

	unlock(): void {
		if (this.#disposed) {
			return;
		}
		const wasUnlocked = this.#unlocked;
		this.#unlocked = true;
		const ctx = this.#ensureContext();
		if (ctx && ctx.state === "suspended") {
			void ctx.resume().catch(() => {});
		}
		this.#recomputeMusicTargets();
		if (!wasUnlocked) {
			this.#notify();
		}
	}

	setEnabled(enabled: boolean): void {
		if (this.#disposed) {
			return;
		}
		this.#enabled = enabled;
		if (enabled) {
			this.#unlocked = true;
			const ctx = this.#ensureContext();
			if (ctx && ctx.state === "suspended") {
				void ctx.resume().catch(() => {});
			}
		} else {
			for (const ch of this.#channels.values()) {
				ch.targetVolume = 0;
				ch.currentVolume = 0;
				ch.element.volume = 0;
				if (!ch.element.paused) {
					ch.element.pause();
				}
			}
		}
		this.#savePrefs();
		this.#recomputeMusicTargets();
		this.#notify();
	}

	setMusicVolume(volume: number): void {
		this.#musicVolume = clamp01(volume);
		this.#savePrefs();
		this.#recomputeMusicTargets();
		this.#notify();
	}

	setSfxVolume(volume: number): void {
		this.#sfxVolume = clamp01(volume);
		if (this.#sfxMasterGain) {
			this.#sfxMasterGain.gain.value = this.#sfxVolume;
		}
		this.#savePrefs();
		this.#notify();
	}

	setFootstepsEnabled(enabled: boolean): void {
		this.#footstepsEnabled = enabled;
		this.#savePrefs();
		this.#notify();
	}

	setRobotSpeechDucking(ducked: boolean): void {
		if (this.#duckedByRobotSpeech === ducked) {
			return;
		}
		this.#duckedByRobotSpeech = ducked;
		this.#recomputeMusicTargets();
	}

	setLevelAudio(audio: LevelAudioSpec | undefined): void {
		if (this.#disposed) {
			return;
		}
		this.#activeLevelAudio = audio;
		this.#activeTrackLabel = audio?.label ?? "";
		this.#prevFootContacts = [false, false, false, false];
		this.#recomputeMusicTargets();
		this.#notify();
	}

	updateRobotTelemetry(
		rootPosMj: readonly [number, number, number],
		footContacts: readonly [boolean, boolean, boolean, boolean],
		isMoving: boolean,
	): void {
		if (this.#disposed) {
			return;
		}
		const [tx, ty, tz] = mujocoPositionToThree(rootPosMj);
		const movedSq =
			(tx - this.#lastRobotPosThree[0]) ** 2 +
			(tz - this.#lastRobotPosThree[2]) ** 2;
		this.#lastRobotPosThree = [tx, ty, tz];

		if (
			movedSq > 0.04 &&
			this.#activeLevelAudio?.regions &&
			this.#activeLevelAudio.regions.length > 0
		) {
			this.#recomputeMusicTargets();
		}

		// Subtle MuJoCo foot-contact taps on rising edge while actively walking/moving
		if (
			this.#enabled &&
			this.#unlocked &&
			this.#footstepsEnabled &&
			this.#sfxVolume > 0.02 &&
			isMoving
		) {
			const now = performance.now();
			for (let i = 0; i < 4; i += 1) {
				const contact = Boolean(footContacts[i]);
				const prev = this.#prevFootContacts[i];
				const lastTap = this.#lastFootTapMs[i] ?? 0;
				if (contact && !prev && now - lastTap >= 85) {
					this.#lastFootTapMs[i] = now;
					this.#playFootstepTap(i);
				}
				this.#prevFootContacts[i] = contact;
			}
		} else {
			for (let i = 0; i < 4; i += 1) {
				this.#prevFootContacts[i] = Boolean(footContacts[i]);
			}
		}
	}

	playSfx(id: WorldSfxId): void {
		if (
			this.#disposed ||
			!this.#enabled ||
			!this.#unlocked ||
			this.#sfxVolume <= 0.005
		) {
			return;
		}
		const def = WORLD_SFX_CATALOG[id];
		if (!def) {
			return;
		}
		const now = performance.now();
		const last = this.#sfxLastPlayedMs.get(id) ?? Number.NEGATIVE_INFINITY;
		if (def.cooldownMs && now - last < def.cooldownMs) {
			return;
		}
		this.#sfxLastPlayedMs.set(id, now);

		const ctx = this.#ensureContext();
		if (!ctx || !this.#sfxMasterGain) {
			return;
		}
		if (ctx.state === "suspended") {
			void ctx.resume().catch(() => {});
		}

		const cached = this.#sfxBufferCache.get(def.src);
		if (cached) {
			this.#triggerBuffer(ctx, cached, def);
			return;
		}
		void this.#loadSfxBuffer(ctx, def.src).then((buf) => {
			if (!buf || this.#disposed || !this.#enabled) {
				return;
			}
			this.#triggerBuffer(ctx, buf, def);
		});
	}

	playServoClick(pinned: boolean): void {
		if (
			this.#disposed ||
			!this.#enabled ||
			!this.#unlocked ||
			this.#sfxVolume <= 0.005
		) {
			return;
		}
		const ctx = this.#ensureContext();
		if (!ctx || !this.#sfxMasterGain || ctx.state === "suspended") {
			return;
		}
		const now = ctx.currentTime;
		const osc = ctx.createOscillator();
		const gain = ctx.createGain();
		osc.type = "triangle";
		osc.frequency.setValueAtTime(pinned ? 520 : 760, now);
		osc.frequency.exponentialRampToValueAtTime(
			pinned ? 210 : 1080,
			now + 0.055,
		);
		gain.gain.setValueAtTime(0.0001, now);
		gain.gain.linearRampToValueAtTime(0.14, now + 0.006);
		gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.065);
		osc.connect(gain);
		gain.connect(this.#sfxMasterGain);
		osc.start(now);
		osc.stop(now + 0.07);
	}

	dispose(): void {
		if (this.#disposed) {
			return;
		}
		this.#disposed = true;
		if (this.#fadeTimer !== undefined) {
			window.clearInterval(this.#fadeTimer);
			this.#fadeTimer = undefined;
		}
		for (const ch of this.#channels.values()) {
			ch.element.pause();
			ch.element.removeAttribute("src");
			ch.element.load();
		}
		this.#channels.clear();
		this.#sfxBufferCache.clear();
		this.#sfxInFlight.clear();
		if (this.#audioCtx) {
			void this.#audioCtx.close().catch(() => {});
			this.#audioCtx = undefined;
		}
		this.#sfxMasterGain = undefined;
	}

	// ---- Internals ----

	#ensureContext(): AudioContext | undefined {
		if (this.#audioCtx) {
			return this.#audioCtx;
		}
		if (typeof AudioContext === "undefined") {
			return undefined;
		}
		const ctx = new AudioContext();
		const master = ctx.createGain();
		master.gain.value = this.#sfxVolume;
		master.connect(ctx.destination);
		this.#audioCtx = ctx;
		this.#sfxMasterGain = master;
		return ctx;
	}

	#loadSfxBuffer(
		ctx: AudioContext,
		src: string,
	): Promise<AudioBuffer | undefined> {
		const existing = this.#sfxInFlight.get(src);
		if (existing) {
			return existing;
		}
		const promise = fetch(src)
			.then((res) => (res.ok ? res.arrayBuffer() : undefined))
			.then((buf) => (buf ? ctx.decodeAudioData(buf.slice(0)) : undefined))
			.then((decoded) => {
				if (decoded) {
					this.#sfxBufferCache.set(src, decoded);
				}
				return decoded;
			})
			.catch(() => undefined)
			.finally(() => {
				this.#sfxInFlight.delete(src);
			});
		this.#sfxInFlight.set(src, promise);
		return promise;
	}

	#triggerBuffer(ctx: AudioContext, buffer: AudioBuffer, def: SfxDef): void {
		if (!this.#sfxMasterGain) {
			return;
		}
		const source = ctx.createBufferSource();
		source.buffer = buffer;
		const baseRate = def.rate ?? 1;
		const jitter = def.rateJitter
			? (Math.random() * 2 - 1) * def.rateJitter
			: 0;
		source.playbackRate.value = Math.max(0.5, Math.min(2, baseRate + jitter));

		const gain = ctx.createGain();
		gain.gain.value = clamp01(def.volume);
		source.connect(gain);
		gain.connect(this.#sfxMasterGain);
		source.start();
	}

	#playFootstepTap(footIndex: number): void {
		const ctx = this.#ensureContext();
		if (!ctx || !this.#sfxMasterGain || ctx.state === "suspended") {
			return;
		}
		const surface = this.#activeLevelAudio?.surfaceAcoustic ?? "metal";
		const now = ctx.currentTime;

		// Soft bandpass noise click
		if (!this.#noiseBuffer) {
			const len = Math.max(1, Math.floor(ctx.sampleRate * 0.032));
			const buf = ctx.createBuffer(1, len, ctx.sampleRate);
			const data = buf.getChannelData(0);
			for (let i = 0; i < len; i += 1) {
				const env = Math.exp((-i / len) * 6.5);
				data[i] = (Math.random() * 2 - 1) * env;
			}
			this.#noiseBuffer = buf;
		}

		const src = ctx.createBufferSource();
		src.buffer = this.#noiseBuffer;

		const filter = ctx.createBiquadFilter();
		filter.type = "bandpass";
		const pitchOffset =
			(footIndex % 2 === 0 ? 1 : 0.94) * (0.96 + Math.random() * 0.08);
		if (surface === "meadow") {
			filter.frequency.value = 460 * pitchOffset;
			filter.Q.value = 1.4;
		} else if (surface === "stone") {
			filter.frequency.value = 920 * pitchOffset;
			filter.Q.value = 2.2;
		} else {
			filter.frequency.value = 1350 * pitchOffset;
			filter.Q.value = 2.8;
		}

		const gain = ctx.createGain();
		gain.gain.setValueAtTime(0.085, now);
		gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.032);

		src.connect(filter);
		filter.connect(gain);
		gain.connect(this.#sfxMasterGain);
		src.start(now);
	}

	#ensureMusicChannel(src: string, label: string): MusicChannel {
		const existing = this.#channels.get(src);
		if (existing) {
			return existing;
		}
		const element = new Audio();
		element.src = src;
		element.loop = true;
		element.preload = "none";
		element.volume = 0;
		const channel: MusicChannel = {
			src,
			label,
			element,
			currentVolume: 0,
			targetVolume: 0,
			playRequested: false,
		};
		this.#channels.set(src, channel);
		return channel;
	}

	#recomputeMusicTargets(): void {
		// Default every existing channel target to 0 (fades out cleanly)
		for (const ch of this.#channels.values()) {
			ch.targetVolume = 0;
		}

		const spec = this.#activeLevelAudio;
		if (
			!spec ||
			!this.#enabled ||
			!this.#unlocked ||
			this.#musicVolume <= 0.002
		) {
			this.#ensureFadeLoop();
			return;
		}

		const duck = this.#duckedByRobotSpeech ? 0.35 : 1.0;
		const masterScale = this.#musicVolume * duck;

		// Check spatial region influence (e.g. Yggdrasil wells / zones)
		let dominantLabel = spec.label;
		let dominantWeight = 0;
		let regionInfluenceSum = 0;

		if (spec.regions && spec.regions.length > 0) {
			const [rx, , rz] = this.#lastRobotPosThree;
			for (const region of spec.regions) {
				const dist = Math.hypot(
					rx - region.posThree[0],
					rz - region.posThree[2],
				);
				let influence = 0;
				if (dist <= region.radius) {
					influence = 1;
				} else if (dist < region.radius + region.falloff) {
					influence =
						1 - (dist - region.radius) / Math.max(0.1, region.falloff);
				}
				if (influence > 0.02) {
					const ch = this.#ensureMusicChannel(region.track, region.label);
					const vol = clamp01(region.volume * influence * masterScale);
					ch.targetVolume = Math.max(ch.targetVolume, vol);
					regionInfluenceSum = Math.min(1, regionInfluenceSum + influence);
					if (influence > dominantWeight) {
						dominantWeight = influence;
						dominantLabel = region.label;
					}
				}
			}
		}

		const baseWeight = Math.max(0.22, 1 - regionInfluenceSum * 0.78);
		const baseChannel = this.#ensureMusicChannel(spec.track, spec.label);
		baseChannel.targetVolume = Math.max(
			baseChannel.targetVolume,
			clamp01(spec.volume * baseWeight * masterScale),
		);

		if (dominantLabel !== this.#activeTrackLabel) {
			this.#activeTrackLabel = dominantLabel;
			this.#notify();
		}

		this.#ensureFadeLoop();
	}

	#ensureFadeLoop(): void {
		if (this.#fadeTimer !== undefined || this.#disposed) {
			return;
		}
		this.#fadeTimer = window.setInterval(() => {
			this.#stepMusicFades();
		}, 50);
		this.#stepMusicFades();
	}

	#stepMusicFades(): void {
		let anyActive = false;
		let playingChanged = false;
		const step = 0.035;

		for (const [src, ch] of this.#channels) {
			const wasPlaying = !ch.element.paused && ch.currentVolume > 0.004;
			if (ch.targetVolume > 0.002 && ch.element.paused && !ch.playRequested) {
				ch.playRequested = true;
				void ch.element
					.play()
					.then(() => {
						ch.playRequested = false;
						this.#notify();
					})
					.catch(() => {
						ch.playRequested = false;
					});
			}

			const delta = ch.targetVolume - ch.currentVolume;
			if (Math.abs(delta) <= step) {
				ch.currentVolume = ch.targetVolume;
			} else {
				ch.currentVolume += Math.sign(delta) * step;
			}
			ch.element.volume = clamp01(ch.currentVolume);

			if (ch.currentVolume <= 0.002 && ch.targetVolume <= 0.002) {
				if (!ch.element.paused) {
					ch.element.pause();
				}
				// Unload tracks that do not belong to the active level to keep memory tidy
				const isCurrentLevelTrack =
					this.#activeLevelAudio?.track === src ||
					(this.#activeLevelAudio?.regions?.some((r) => r.track === src) ??
						false);
				if (!isCurrentLevelTrack) {
					ch.element.removeAttribute("src");
					ch.element.load();
					this.#channels.delete(src);
				}
			} else if (Math.abs(ch.targetVolume - ch.currentVolume) > 0.001) {
				anyActive = true;
			}

			const isPlayingNow = !ch.element.paused && ch.currentVolume > 0.004;
			if (isPlayingNow !== wasPlaying) {
				playingChanged = true;
			}
		}

		if (playingChanged) {
			this.#notify();
		}
		if (!anyActive && this.#fadeTimer !== undefined) {
			window.clearInterval(this.#fadeTimer);
			this.#fadeTimer = undefined;
		}
	}

	#loadPrefs(): void {
		if (typeof window === "undefined") {
			return;
		}
		try {
			const raw = window.localStorage.getItem(STORAGE_KEY);
			if (!raw) {
				const nav = navigator as Navigator & {
					connection?: { saveData?: boolean };
				};
				if (nav.connection?.saveData) {
					this.#enabled = false;
				}
				return;
			}
			const parsed = JSON.parse(raw) as PersistedAudioPrefs;
			if (typeof parsed.enabled === "boolean") {
				this.#enabled = parsed.enabled;
			}
			if (typeof parsed.musicVolume === "number") {
				this.#musicVolume = clamp01(parsed.musicVolume);
			}
			if (typeof parsed.sfxVolume === "number") {
				this.#sfxVolume = clamp01(parsed.sfxVolume);
			}
			if (typeof parsed.footstepsEnabled === "boolean") {
				this.#footstepsEnabled = parsed.footstepsEnabled;
			}
		} catch {
			// Ignore malformed storage entries
		}
	}

	#savePrefs(): void {
		if (typeof window === "undefined") {
			return;
		}
		try {
			const payload: PersistedAudioPrefs = {
				enabled: this.#enabled,
				musicVolume: this.#musicVolume,
				sfxVolume: this.#sfxVolume,
				footstepsEnabled: this.#footstepsEnabled,
			};
			window.localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
		} catch {
			// Ignore storage quota errors
		}
	}

	#notify(): void {
		this.#onStateChange?.();
	}
}

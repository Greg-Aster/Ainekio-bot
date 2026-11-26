/**
 * Pure-TypeScript 50 Hz runtime for Ainekio's production Neural Gait
 * (`ainekio-neural-gait-v7-proprio` / MicroDuck MLP) and Neural Pose
 * (`ainekio-neural-pose-v1` / Equivariant Residual MLP) policies.
 *
 * Matches:
 *  - `Ainekio/Master/gateway/neural_gait/contract.py`
 *  - `Ainekio/Master/gateway/neural_gait/client.py`
 *  - `Ainekio/Master/gateway/neural_gait/microduck_actor.py`
 *  - `Ainekio/experiments/freestyle/neural_pose/contract.py`
 *  - `Ainekio/experiments/freestyle/neural_pose/actor.py`
 *
 * Runs zero-dependency Float32Array math in <1 ms per 50 Hz tick in any browser Web Worker.
 */

const DEG2RAD = Math.PI / 180;

export type PackedTensorLayout = {
	readonly offset: number;
	readonly length: number;
	readonly shape: readonly number[];
};

export type MlpLayerSpec = {
	readonly weight: string;
	readonly bias: string;
	readonly inDim: number;
	readonly outDim: number;
	readonly activation: "elu" | "tanh" | "linear";
};

export type GoldenPolicyTest = {
	readonly seed: number;
	readonly obs: readonly number[];
	readonly action: readonly number[];
	readonly decodedJointDeg?: readonly number[];
};

export type NeuralGaitManifest = {
	readonly schemaVersion: number;
	readonly kind: string;
	readonly modelId: string;
	readonly observationSchema: string;
	readonly actionContract: string;
	readonly checkpointSha256: string;
	readonly geometryId: string;
	readonly controlHz: number;
	readonly obsDim: number;
	readonly featureDim: number;
	readonly historySamples: number;
	readonly footActionScaleMm: readonly [number, number, number];
	readonly referenceJointDeg: readonly number[];
	readonly defaultProfile: {
		readonly forwardMS: number;
		readonly lateralMS: number;
		readonly yawRadS: number;
	};
	readonly weightsFile: string;
	readonly layers: readonly MlpLayerSpec[];
	readonly tensors: Readonly<Record<string, PackedTensorLayout>>;
	readonly onnxMaxAbsError?: number;
	readonly goldenTests?: readonly GoldenPolicyTest[];
};

export type NeuralPoseManifest = {
	readonly schemaVersion: number;
	readonly kind: string;
	readonly modelId: string;
	readonly observationSchema: string;
	readonly actionContract: string;
	readonly checkpointSha256: string;
	readonly geometryId: string;
	readonly controlHz: number;
	readonly obsDim: number;
	readonly featureDim: number;
	readonly historySamples: number;
	readonly goalFootSliceStart: number;
	readonly goalFootSliceEnd: number;
	readonly residualScale: number;
	readonly footScaleMm: readonly [number, number, number];
	readonly obsMirrorPerm: readonly number[];
	readonly actMirrorPerm: readonly number[];
	readonly weightsFile: string;
	readonly layers: readonly MlpLayerSpec[];
	readonly tensors: Readonly<Record<string, PackedTensorLayout>>;
	readonly onnxMaxAbsError?: number;
	readonly goldenTests?: readonly GoldenPolicyTest[];
};

export type CompiledPoseSegment =
	| { readonly kind: "face"; readonly expr: string }
	| { readonly kind: "hold"; readonly seconds: number }
	| {
			readonly kind: "pose_goal";
			readonly goalDeg: readonly number[];
			readonly goalFootNorm: readonly number[];
			readonly legSupport: readonly number[];
			readonly speedScale: number;
			readonly durationS: number;
			readonly isStand: boolean;
			readonly fromNonstanding: boolean;
	  }
	| {
			readonly kind: "oscillate_goal";
			readonly baseDeg: readonly number[];
			readonly jointIndices: readonly number[];
			readonly centersDeg: readonly number[];
			readonly amplitudesDeg: readonly number[];
			readonly hz: number;
			readonly cycles: number;
			readonly legSupport: readonly number[];
			readonly speedScale: number;
			readonly durationS: number;
			readonly endDeg: readonly number[];
	  };

export type CompiledNeuralPoseMotion = {
	readonly id: string;
	readonly label: string;
	readonly sourceFamily: string;
	readonly sourceTitle: string;
	readonly sourceId: string;
	readonly segments: readonly CompiledPoseSegment[];
};

export type NeuralPoseLibrary = {
	readonly schemaVersion: number;
	readonly poseModelId: string;
	readonly standAnglesDeg: readonly number[];
	readonly motions: readonly CompiledNeuralPoseMotion[];
};

type CompiledLayer = {
	readonly w: Float32Array;
	readonly b: Float32Array;
	readonly inDim: number;
	readonly outDim: number;
	readonly activation: "elu" | "tanh" | "linear";
	readonly outBuf: Float32Array;
};

function sliceTensor(
	weights: Float32Array,
	tensors: Readonly<Record<string, PackedTensorLayout>>,
	name: string,
): Float32Array {
	const entry = tensors[name];
	if (!entry) {
		throw new Error(`Missing tensor '${name}' in policy weights`);
	}
	return weights.subarray(entry.offset, entry.offset + entry.length);
}

function buildLayers(
	weights: Float32Array,
	tensors: Readonly<Record<string, PackedTensorLayout>>,
	specs: readonly MlpLayerSpec[],
): CompiledLayer[] {
	return specs.map((spec) => ({
		w: sliceTensor(weights, tensors, spec.weight),
		b: sliceTensor(weights, tensors, spec.bias),
		inDim: spec.inDim,
		outDim: spec.outDim,
		activation: spec.activation,
		outBuf: new Float32Array(spec.outDim),
	}));
}

function runNormalizedMlp(
	obs: ArrayLike<number>,
	mean: Float32Array,
	std: Float32Array,
	normBuf: Float32Array,
	layers: readonly CompiledLayer[],
): Float32Array {
	const n = normBuf.length;
	for (let i = 0; i < n; i += 1) {
		normBuf[i] = ((obs[i] ?? 0) - (mean[i] ?? 0)) / (std[i] || 1);
	}
	let current: Float32Array = normBuf;
	for (let li = 0; li < layers.length; li += 1) {
		const layer = layers[li];
		if (!layer) {
			continue;
		}
		const { w, b, inDim, outDim, activation, outBuf } = layer;
		for (let r = 0; r < outDim; r += 1) {
			const rowOffset = r * inDim;
			let acc = b[r] ?? 0;
			for (let c = 0; c < inDim; c += 1) {
				acc += (w[rowOffset + c] ?? 0) * (current[c] ?? 0);
			}
			if (activation === "elu") {
				outBuf[r] = acc > 0 ? acc : Math.expm1(acc);
			} else if (activation === "tanh") {
				outBuf[r] = Math.tanh(acc);
			} else {
				outBuf[r] = acc;
			}
		}
		current = outBuf;
	}
	return current;
}

function clamp(v: number, lo: number, hi: number): number {
	return v < lo ? lo : v > hi ? hi : v;
}

/**
 * Matches `gateway/neural_gait/client.py:_relative_orientation`.
 */
export function relativeOrientationWxyz(
	quatWxyz: readonly [number, number, number, number],
	yaw: number,
	sign: number,
): [number, number, number, number] {
	const [w, x, y, z] = quatWxyz;
	const c = Math.cos(yaw / 2);
	const s = Math.sin(yaw / 2);
	return [
		sign * (c * w + s * z),
		sign * (c * x + s * y),
		sign * (c * y - s * x),
		sign * (c * z - s * w),
	];
}

/**
 * Matches `gateway/neural_gait/client.py:walking_orientation_reference`.
 */
export function walkingOrientationReference(
	quatWxyz: readonly [number, number, number, number],
): readonly [number, number] {
	const [w, x, y, z] = quatWxyz;
	const yaw = Math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z));
	const rel = relativeOrientationWxyz(quatWxyz, yaw, 1);
	return [yaw, rel[0] >= 0 ? 1 : -1];
}

/**
 * Matches `neural_pose/contract.py:projected_gravity_from_wxyz` and
 * `neural_gait/contract.py:ObservationHistory.project` (`-gravity(q)`).
 */
export function projectedGravityFromWxyz(
	quatWxyz: readonly [number, number, number, number],
): [number, number, number] {
	const [w, x, y, z] = quatWxyz;
	return [-2 * (x * z - w * y), -2 * (y * z + w * x), 1 - 2 * (w * w + z * z)];
}

/**
 * Causal 15-frame (300 ms @ 20 ms) observation history for `ainekio-neural-gait-v7-proprio`.
 * Matches `gateway/neural_gait/contract.py:ObservationHistory.project`.
 */
export class NeuralGaitObservationHistory {
	readonly #samples: Array<{ readonly t: number; readonly row: Float32Array }> =
		[];
	readonly #out = new Float32Array(720);
	#lastTime = -1;

	reset(): void {
		this.#samples.length = 0;
		this.#lastTime = -1;
	}

	pushAndProject(params: {
		readonly observationTimeS: number;
		readonly jointDeg: ArrayLike<number>;
		readonly jointVelocityDegS: ArrayLike<number>;
		readonly orientationWxyz: readonly [number, number, number, number];
		readonly angularRateRadS: readonly [number, number, number];
		readonly accelerationMS2: readonly [number, number, number];
		readonly commandTwist: readonly [number, number, number];
		readonly previousAction: ArrayLike<number>;
	}): Float32Array {
		const now = params.observationTimeS;
		const row = new Float32Array(48);
		for (let i = 0; i < 12; i += 1) {
			row[i] = (params.jointDeg[i] ?? 0) * DEG2RAD;
			row[12 + i] = (params.jointVelocityDegS[i] ?? 0) * DEG2RAD;
		}
		row[24] = params.angularRateRadS[0];
		row[25] = params.angularRateRadS[1];
		row[26] = params.angularRateRadS[2];
		row[27] = params.accelerationMS2[0] / 9.81;
		row[28] = params.accelerationMS2[1] / 9.81;
		row[29] = params.accelerationMS2[2] / 9.81;
		const grav = projectedGravityFromWxyz(params.orientationWxyz);
		row[30] = grav[0];
		row[31] = grav[1];
		row[32] = grav[2];
		row[33] = params.commandTwist[0];
		row[34] = params.commandTwist[1];
		row[35] = params.commandTwist[2];
		for (let i = 0; i < 12; i += 1) {
			row[36 + i] = params.previousAction[i] ?? 0;
		}

		if (this.#lastTime < 0 || now < this.#lastTime) {
			this.#samples.length = 0;
		}
		this.#lastTime = now;
		const last = this.#samples[this.#samples.length - 1];
		if (last && last.t === now) {
			this.#samples[this.#samples.length - 1] = { t: now, row };
		} else {
			this.#samples.push({ t: now, row });
		}
		while (
			this.#samples.length > 1 &&
			(this.#samples[1]?.t ?? 0) < now - 15 * 0.02
		) {
			this.#samples.shift();
		}

		this.#out.fill(0);
		for (let idx = 0; idx < 15; idx += 1) {
			const targetT = now - idx * 0.02 + 1e-9;
			let matched: Float32Array | undefined;
			for (let k = this.#samples.length - 1; k >= 0; k -= 1) {
				const s = this.#samples[k];
				if (s && s.t <= targetT) {
					matched = s.row;
					break;
				}
			}
			if (matched) {
				this.#out.set(matched, idx * 48);
			}
		}
		return this.#out;
	}
}

/**
 * Causal 15-frame (300 ms @ 20 ms) observation history for `ainekio-neural-pose-v1`.
 * Matches `experiments/freestyle/neural_pose/contract.py:PoseObservationHistory`.
 */
export class NeuralPoseObservationHistory {
	readonly #samples: Array<{ readonly t: number; readonly row: Float32Array }> =
		[];
	readonly #out = new Float32Array(1290);

	reset(): void {
		this.#samples.length = 0;
	}

	pushAndProject(params: {
		readonly observationTimeS: number;
		readonly measuredDeg: ArrayLike<number>;
		readonly commandedDeg: ArrayLike<number>;
		readonly velocityDegS: ArrayLike<number>;
		readonly usableFlags: ArrayLike<boolean>;
		readonly orientationWxyz: readonly [number, number, number, number];
		readonly angularRateRadS: readonly [number, number, number];
		readonly accelerationMS2: readonly [number, number, number];
		readonly goalJointDeg: ArrayLike<number>;
		readonly goalFootNorm: ArrayLike<number>;
		readonly legSupport: ArrayLike<number>;
		readonly speedScale: number;
		readonly previousAction: ArrayLike<number>;
	}): Float32Array {
		const row = new Float32Array(86);
		for (let i = 0; i < 12; i += 1) {
			const meas = params.measuredDeg[i];
			const cmd = params.commandedDeg[i];
			const ok =
				Boolean(params.usableFlags[i]) &&
				typeof meas === "number" &&
				Number.isFinite(meas);
			const fallback =
				typeof cmd === "number" && Number.isFinite(cmd) ? cmd : 0;
			const deg = ok ? (meas as number) : fallback;
			const velRaw = params.velocityDegS[i];
			const vel =
				ok && typeof velRaw === "number" && Number.isFinite(velRaw)
					? velRaw
					: 0;
			row[i] = deg * DEG2RAD;
			row[12 + i] = vel * DEG2RAD;
			row[24 + i] = ok ? 1 : 0;
		}
		row[36] = params.angularRateRadS[0];
		row[37] = params.angularRateRadS[1];
		row[38] = params.angularRateRadS[2];
		row[39] = params.accelerationMS2[0] / 9.81;
		row[40] = params.accelerationMS2[1] / 9.81;
		row[41] = params.accelerationMS2[2] / 9.81;
		const grav = projectedGravityFromWxyz(params.orientationWxyz);
		row[42] = grav[0];
		row[43] = grav[1];
		row[44] = grav[2];
		for (let i = 0; i < 12; i += 1) {
			row[45 + i] = (params.goalJointDeg[i] ?? 0) * DEG2RAD;
			row[57 + i] = clamp(params.goalFootNorm[i] ?? 0, -1, 1);
		}
		for (let l = 0; l < 4; l += 1) {
			row[69 + l] = (params.legSupport[l] ?? 1) >= 0.5 ? 1 : 0;
		}
		row[73] = clamp(params.speedScale, 0.1, 1.0);
		for (let i = 0; i < 12; i += 1) {
			row[74 + i] = clamp(params.previousAction[i] ?? 0, -1, 1);
		}

		const t = params.observationTimeS;
		const last = this.#samples[this.#samples.length - 1];
		if (last && t < last.t) {
			this.#samples.length = 0;
		}
		const tail = this.#samples[this.#samples.length - 1];
		if (tail && tail.t === t) {
			this.#samples[this.#samples.length - 1] = { t, row };
		} else {
			this.#samples.push({ t, row });
		}
		const cutoff = t - 15 * 0.02 - 0.1;
		while (this.#samples.length > 1 && (this.#samples[0]?.t ?? 0) < cutoff) {
			this.#samples.shift();
		}

		const earliest = this.#samples[0]?.row ?? row;
		for (let idx = 0; idx < 15; idx += 1) {
			const targetT = t - idx * 0.02 + 1e-9;
			let matched: Float32Array | undefined;
			for (let k = this.#samples.length - 1; k >= 0; k -= 1) {
				const s = this.#samples[k];
				if (s && s.t <= targetT) {
					matched = s.row;
					break;
				}
			}
			this.#out.set(matched ?? earliest, idx * 86);
		}
		return this.#out;
	}
}

export class NeuralGaitPolicy {
	readonly manifest: NeuralGaitManifest;
	readonly #mean: Float32Array;
	readonly #std: Float32Array;
	readonly #normBuf: Float32Array;
	readonly #layers: readonly CompiledLayer[];

	constructor(manifest: NeuralGaitManifest, weights: Float32Array) {
		this.manifest = manifest;
		this.#mean = sliceTensor(weights, manifest.tensors, "mean");
		this.#std = sliceTensor(weights, manifest.tensors, "std");
		this.#normBuf = new Float32Array(manifest.obsDim);
		this.#layers = buildLayers(weights, manifest.tensors, manifest.layers);
	}

	predictAction(obs: ArrayLike<number>): number[] {
		const raw = runNormalizedMlp(
			obs,
			this.#mean,
			this.#std,
			this.#normBuf,
			this.#layers,
		);
		const action: number[] = new Array(12);
		for (let i = 0; i < 12; i += 1) {
			action[i] = clamp(raw[i] ?? 0, -1, 1);
		}
		return action;
	}

	footOffsetsMm(action: ArrayLike<number>): number[] {
		const scale = this.manifest.footActionScaleMm;
		const feet: number[] = new Array(12);
		for (let i = 0; i < 12; i += 1) {
			feet[i] = clamp(action[i] ?? 0, -1, 1) * (scale[i % 3] ?? 0);
		}
		return feet;
	}
}

export class NeuralPosePolicy {
	readonly manifest: NeuralPoseManifest;
	readonly #mean: Float32Array;
	readonly #std: Float32Array;
	readonly #obsMirrorPerm: Int32Array;
	readonly #obsMirrorSign: Float32Array;
	readonly #actMirrorPerm: Int32Array;
	readonly #actMirrorSign: Float32Array;
	readonly #normBuf: Float32Array;
	readonly #mirroredObsBuf: Float32Array;
	readonly #y1Buf = new Float32Array(12);
	readonly #layers: readonly CompiledLayer[];

	constructor(manifest: NeuralPoseManifest, weights: Float32Array) {
		this.manifest = manifest;
		this.#mean = sliceTensor(weights, manifest.tensors, "mean");
		this.#std = sliceTensor(weights, manifest.tensors, "std");
		this.#obsMirrorPerm = Int32Array.from(manifest.obsMirrorPerm);
		this.#obsMirrorSign = sliceTensor(
			weights,
			manifest.tensors,
			"obsMirrorSign",
		);
		this.#actMirrorPerm = Int32Array.from(manifest.actMirrorPerm);
		this.#actMirrorSign = sliceTensor(
			weights,
			manifest.tensors,
			"actMirrorSign",
		);
		this.#normBuf = new Float32Array(manifest.obsDim);
		this.#mirroredObsBuf = new Float32Array(manifest.obsDim);
		this.#layers = buildLayers(weights, manifest.tensors, manifest.layers);
	}

	predictAction(obs: ArrayLike<number>): number[] {
		const y1Raw = runNormalizedMlp(
			obs,
			this.#mean,
			this.#std,
			this.#normBuf,
			this.#layers,
		);
		this.#y1Buf.set(y1Raw);

		const obsDim = this.manifest.obsDim;
		for (let i = 0; i < obsDim; i += 1) {
			const srcIdx = this.#obsMirrorPerm[i] ?? i;
			this.#mirroredObsBuf[i] =
				(obs[srcIdx] ?? 0) * (this.#obsMirrorSign[i] ?? 1);
		}
		const y2Raw = runNormalizedMlp(
			this.#mirroredObsBuf,
			this.#mean,
			this.#std,
			this.#normBuf,
			this.#layers,
		);

		const goalStart = this.manifest.goalFootSliceStart;
		const resScale = this.manifest.residualScale;
		const action: number[] = new Array(12);
		for (let i = 0; i < 12; i += 1) {
			const mIdx = this.#actMirrorPerm[i] ?? i;
			const y2 = (y2Raw[mIdx] ?? 0) * (this.#actMirrorSign[i] ?? 1);
			const sym = 0.5 * ((this.#y1Buf[i] ?? 0) + y2) * resScale;
			const base = obs[goalStart + i] ?? 0;
			action[i] = clamp(base + sym, -1, 1);
		}
		return action;
	}
}

// =============================================================================
// Ainekio V1 (8-Servo) Neural Gait (`v1-microduck-p4`), Neural Pose (`neural_pose_v1`),
// and Native Firmware (`v1_motion.c`) Runtime
// =============================================================================

export type V1NeuralGaitManifest = {
	readonly schemaVersion: number;
	readonly kind: string;
	readonly modelId: string;
	readonly observationSchema: string;
	readonly checkpointSha256: string;
	readonly geometryId: string;
	readonly controlHz: number;
	readonly gaitHz: number;
	readonly gaitHzMin?: number;
	readonly gaitHzMax?: number;
	readonly obsDim: number;
	readonly featureDim: number;
	readonly historySamples: number;
	readonly actionScaleDeg: readonly [number, number];
	readonly jointMinDeg: readonly number[];
	readonly jointMaxDeg: readonly number[];
	readonly defaultProfile: {
		readonly forwardMS: number;
		readonly lateralMS: number;
		readonly yawRadS: number;
	};
	readonly weightsFile: string;
	readonly layers: readonly MlpLayerSpec[];
	readonly tensors: Readonly<Record<string, PackedTensorLayout>>;
	readonly onnxMaxAbsError?: number;
	readonly goldenTests?: readonly GoldenPolicyTest[];
};

export type V1NeuralPoseMotionSpec = {
	readonly id: string;
	readonly label: string;
	readonly face: string;
	readonly goalDeg: readonly number[];
	readonly support: readonly number[];
};

export type V1NeuralPoseManifest = {
	readonly schemaVersion: number;
	readonly kind: string;
	readonly modelId: string;
	readonly observationSchema: string;
	readonly checkpointSha256: string;
	readonly geometryId: string;
	readonly controlHz: number;
	readonly obsDim: number;
	readonly featureDim: number;
	readonly historySamples: number;
	readonly goalSliceStart: number;
	readonly goalSliceEnd: number;
	readonly residualScale: number;
	readonly jointCenterDeg: readonly number[];
	readonly jointHalfSpanDeg: readonly number[];
	readonly jointMinDeg: readonly number[];
	readonly jointMaxDeg: readonly number[];
	readonly obsMirrorPerm: readonly number[];
	readonly actMirrorPerm: readonly number[];
	readonly weightsFile: string;
	readonly layers: readonly MlpLayerSpec[];
	readonly tensors: Readonly<Record<string, PackedTensorLayout>>;
	readonly motions: readonly V1NeuralPoseMotionSpec[];
	readonly onnxMaxAbsError?: number;
	readonly goldenTests?: readonly GoldenPolicyTest[];
};

export class V1GaitObservationHistory {
	readonly #featureDim: number;
	readonly #samples: number;
	readonly #buf: Float32Array;
	#seeded = false;

	constructor(featureDim = 38, samples = 8) {
		this.#featureDim = featureDim;
		this.#samples = samples;
		this.#buf = new Float32Array(featureDim * samples);
	}

	reset(): void {
		this.#buf.fill(0);
		this.#seeded = false;
	}

	push(frame: ArrayLike<number>): Float32Array {
		const f = this.#featureDim;
		if (!this.#seeded) {
			for (let s = 0; s < this.#samples; s += 1) {
				for (let i = 0; i < f; i += 1) {
					this.#buf[s * f + i] = frame[i] ?? 0;
				}
			}
			this.#seeded = true;
			return this.#buf;
		}
		// Roll right by 1 frame (newest frame at [0..f-1])
		this.#buf.copyWithin(f, 0, (this.#samples - 1) * f);
		for (let i = 0; i < f; i += 1) {
			this.#buf[i] = frame[i] ?? 0;
		}
		return this.#buf;
	}
}

export class V1NeuralGaitPolicy {
	readonly manifest: V1NeuralGaitManifest;
	readonly #mean: Float32Array;
	readonly #std: Float32Array;
	readonly #normBuf: Float32Array;
	readonly #layers: readonly CompiledLayer[];

	constructor(manifest: V1NeuralGaitManifest, weights: Float32Array) {
		this.manifest = manifest;
		this.#mean = sliceTensor(weights, manifest.tensors, "mean");
		this.#std = sliceTensor(weights, manifest.tensors, "std");
		this.#normBuf = new Float32Array(manifest.obsDim);
		this.#layers = buildLayers(weights, manifest.tensors, manifest.layers);
	}

	predictAction(obs: ArrayLike<number>): number[] {
		const raw = runNormalizedMlp(
			obs,
			this.#mean,
			this.#std,
			this.#normBuf,
			this.#layers,
		);
		const action: number[] = new Array(8);
		for (let i = 0; i < 8; i += 1) {
			action[i] = clamp(raw[i] ?? 0, -1, 1);
		}
		return action;
	}

	actionToJointDeg(action: ArrayLike<number>): number[] {
		const [hipScale, kneeScale] = this.manifest.actionScaleDeg;
		const out: number[] = new Array(8);
		for (let i = 0; i < 8; i += 1) {
			const scale = i < 4 ? hipScale : kneeScale;
			const lo = this.manifest.jointMinDeg[i] ?? -45;
			const hi = this.manifest.jointMaxDeg[i] ?? 45;
			out[i] = clamp(clamp(action[i] ?? 0, -1, 1) * scale, lo, hi);
		}
		return out;
	}
}

export class V1PoseObservationHistory {
	readonly #featureDim: number;
	readonly #samples: number;
	readonly #buf: Float32Array;
	#seeded = false;

	constructor(featureDim = 54, samples = 15) {
		this.#featureDim = featureDim;
		this.#samples = samples;
		this.#buf = new Float32Array(featureDim * samples);
	}

	reset(): void {
		this.#buf.fill(0);
		this.#seeded = false;
	}

	push(frame: ArrayLike<number>): Float32Array {
		const f = this.#featureDim;
		if (!this.#seeded) {
			for (let s = 0; s < this.#samples; s += 1) {
				for (let i = 0; i < f; i += 1) {
					this.#buf[s * f + i] = frame[i] ?? 0;
				}
			}
			this.#seeded = true;
			return this.#buf;
		}
		this.#buf.copyWithin(f, 0, (this.#samples - 1) * f);
		for (let i = 0; i < f; i += 1) {
			this.#buf[i] = frame[i] ?? 0;
		}
		return this.#buf;
	}
}

export class V1NeuralPosePolicy {
	readonly manifest: V1NeuralPoseManifest;
	readonly #mean: Float32Array;
	readonly #std: Float32Array;
	readonly #obsMirrorPerm: Int32Array;
	readonly #obsMirrorSign: Float32Array;
	readonly #actMirrorPerm: Int32Array;
	readonly #actMirrorSign: Float32Array;
	readonly #normBuf: Float32Array;
	readonly #mirroredObsBuf: Float32Array;
	readonly #y1Buf = new Float32Array(8);
	readonly #layers: readonly CompiledLayer[];

	constructor(manifest: V1NeuralPoseManifest, weights: Float32Array) {
		this.manifest = manifest;
		this.#mean = sliceTensor(weights, manifest.tensors, "mean");
		this.#std = sliceTensor(weights, manifest.tensors, "std");
		this.#obsMirrorPerm = Int32Array.from(manifest.obsMirrorPerm);
		this.#obsMirrorSign = sliceTensor(
			weights,
			manifest.tensors,
			"obsMirrorSign",
		);
		this.#actMirrorPerm = Int32Array.from(manifest.actMirrorPerm);
		this.#actMirrorSign = sliceTensor(
			weights,
			manifest.tensors,
			"actMirrorSign",
		);
		this.#normBuf = new Float32Array(manifest.obsDim);
		this.#mirroredObsBuf = new Float32Array(manifest.obsDim);
		this.#layers = buildLayers(weights, manifest.tensors, manifest.layers);
	}

	degToNorm(anglesDeg: ArrayLike<number>): number[] {
		const out: number[] = new Array(8);
		for (let i = 0; i < 8; i += 1) {
			const c = this.manifest.jointCenterDeg[i] ?? 0;
			const s = this.manifest.jointHalfSpanDeg[i] ?? 45;
			out[i] = clamp(((anglesDeg[i] ?? 0) - c) / s, -1, 1);
		}
		return out;
	}

	normToDeg(actionNorm: ArrayLike<number>): number[] {
		const out: number[] = new Array(8);
		for (let i = 0; i < 8; i += 1) {
			const c = this.manifest.jointCenterDeg[i] ?? 0;
			const s = this.manifest.jointHalfSpanDeg[i] ?? 45;
			const lo = this.manifest.jointMinDeg[i] ?? -45;
			const hi = this.manifest.jointMaxDeg[i] ?? 45;
			out[i] = clamp(c + clamp(actionNorm[i] ?? 0, -1, 1) * s, lo, hi);
		}
		return out;
	}

	predictAction(obs: ArrayLike<number>): number[] {
		const y1Raw = runNormalizedMlp(
			obs,
			this.#mean,
			this.#std,
			this.#normBuf,
			this.#layers,
		);
		this.#y1Buf.set(y1Raw);

		const obsDim = this.manifest.obsDim;
		for (let i = 0; i < obsDim; i += 1) {
			const srcIdx = this.#obsMirrorPerm[i] ?? i;
			this.#mirroredObsBuf[i] =
				(obs[srcIdx] ?? 0) * (this.#obsMirrorSign[i] ?? 1);
		}
		const y2Raw = runNormalizedMlp(
			this.#mirroredObsBuf,
			this.#mean,
			this.#std,
			this.#normBuf,
			this.#layers,
		);

		const goalStart = this.manifest.goalSliceStart;
		const resScale = this.manifest.residualScale;
		const action: number[] = new Array(8);
		for (let i = 0; i < 8; i += 1) {
			const mIdx = this.#actMirrorPerm[i] ?? i;
			const y2 = (y2Raw[mIdx] ?? 0) * (this.#actMirrorSign[i] ?? 1);
			const sym = 0.5 * ((this.#y1Buf[i] ?? 0) + y2) * resScale;
			const base = obs[goalStart + i] ?? 0;
			action[i] = clamp(base + sym, -1, 1);
		}
		return action;
	}
}

const V1_LEG_JOINT_PAIRS: readonly (readonly [
	number,
	number,
	boolean,
	boolean,
])[] = [
	[0, 5, false, true], // FR: R1, R3
	[1, 4, false, false], // RR: R2, R4
	[2, 6, true, true], // FL: L1, L3
	[3, 7, true, false], // RL: L2, L4
];
const V1_LEG_PHASE_OFFSETS = [0.0, 0.5, 0.5, 0.0] as const;

/** Exact TypeScript translation of `Slave/software/models/v1-8servo/v1_motion.c` `ainekio_v1_walk_sample`. */
export function sampleV1NativeWalkDeg(
	phase01: number,
	vxNorm: number,
	vyNorm: number,
	wzNorm: number,
	strideScale: number,
): number[] {
	let p = phase01 % 1;
	if (p < 0) p += 1;
	const scale = clamp(strideScale, 0, 1.5);
	const cmdMag = Math.min(
		1,
		Math.hypot(Math.hypot(vxNorm, vyNorm), Math.abs(wzNorm)),
	);
	const hipAmpDeg = 22 * scale;
	const liftDeg = 26 * (0.25 + 0.75 * cmdMag) * Math.min(1, scale);
	const stanceKneeDeg = 6;
	const out = [0, 0, 0, 0, 0, 0, 0, 0];

	for (let i = 0; i < 4; i += 1) {
		const pair = V1_LEG_JOINT_PAIRS[i];
		if (!pair) continue;
		const [hipJoint, kneeJoint, isLeft, isFront] = pair;
		const lp = (p + (V1_LEG_PHASE_OFFSETS[i] ?? 0)) % 1;
		const latSign = isFront !== isLeft ? -1 : 1;
		const dir = clamp(
			vxNorm + (isLeft ? -wzNorm : wzNorm) + 0.45 * vyNorm * latSign,
			-1,
			1,
		);
		let hip = 0;
		let knee = stanceKneeDeg;
		if (lp < 0.5) {
			const s = lp / 0.5;
			hip = -Math.cos(Math.PI * s) * (hipAmpDeg * dir);
			knee = stanceKneeDeg + Math.sin(Math.PI * s) * liftDeg;
		} else {
			const s = (lp - 0.5) / 0.5;
			hip = Math.cos(Math.PI * s) * (hipAmpDeg * dir);
		}
		out[hipJoint] = clamp(hip, -45, 45);
		out[kneeJoint] = clamp(knee, -15, 115);
	}
	return out;
}

/** Exact TypeScript translation of `Slave/software/models/v1-8servo/v1_motion.c` `ainekio_v1_posture_angles`. */
export function sampleV1NativePostureDeg(name: string): number[] | undefined {
	switch (name) {
		case "stand":
		case "home":
		case "neutral":
			return [0, 0, 0, 0, 0, 0, 0, 0];
		case "crouch":
			return [0, 0, 0, 0, 28, 28, 28, 28];
		case "lay":
		case "lay_down":
		case "rest":
		case "sleep":
			return [10, -10, 10, -10, 75, 75, 75, 75];
		case "sit":
			return [8, -15, 8, -15, 58, -8, -8, 58];
		case "bow":
		case "play_bow":
			return [15, 0, 15, 0, -5, 55, 55, -5];
		case "stretch":
			return [20, -20, 20, -20, 10, 35, 35, 10];
		case "wave":
		case "wave_fr":
			return [32, 10, -8, -6, 20, 95, 10, 15];
		case "wave_fl":
			return [-8, -6, 32, 10, 15, 10, 95, 20];
		default:
			return undefined;
	}
}

// =============================================================================
// Ainekio V3 (12-Servo Komatsu Option A-1 DS3225 PRO) Neural Gait (`v3-microduck-p4`),
// Neural Pose (`neural_pose_v3`), and Native Firmware (`v3_kinematics.c` + `v3_motion.c`)
// =============================================================================

export type V3NeuralGaitManifest = {
	readonly schemaVersion: number;
	readonly kind: string;
	readonly modelId: string;
	readonly observationSchema: string;
	readonly geometryId: string;
	readonly controlHz: number;
	readonly gaitHz: number;
	readonly gaitHzMin?: number;
	readonly gaitHzMax?: number;
	readonly obsDim: number;
	readonly featureDim: number;
	readonly historySamples: number;
	readonly actionSpace?: "normalized-foot-offsets-v3-ik" | "scaled-joint-deg";
	readonly footActionScaleMm?: readonly [number, number, number];
	readonly actionScaleDeg?: readonly [number, number, number];
	readonly actuatorDelaySubsteps?: number;
	readonly jointMinDeg: readonly number[];
	readonly jointMaxDeg: readonly number[];
	readonly defaultProfile: {
		readonly forwardMS: number;
		readonly lateralMS: number;
		readonly yawRadS: number;
	};
	readonly weightsFile: string;
	readonly layers: readonly MlpLayerSpec[];
	readonly tensors: Readonly<Record<string, PackedTensorLayout>>;
	readonly onnxMaxAbsError?: number;
	readonly goldenTests?: readonly GoldenPolicyTest[];
};

export type V3NeuralPoseMotionSpec = {
	readonly id: string;
	readonly label: string;
	readonly face: string;
	readonly goalDeg: readonly number[];
	readonly support: readonly number[];
};

export type V3NeuralPoseManifest = {
	readonly schemaVersion: number;
	readonly kind: string;
	readonly modelId: string;
	readonly observationSchema: string;
	readonly geometryId: string;
	readonly controlHz: number;
	readonly obsDim: number;
	readonly featureDim: number;
	readonly historySamples: number;
	readonly goalSliceStart: number;
	readonly goalSliceEnd: number;
	readonly residualScale: number;
	readonly jointCenterDeg: readonly number[];
	readonly jointHalfSpanDeg: readonly number[];
	readonly jointMinDeg: readonly number[];
	readonly jointMaxDeg: readonly number[];
	readonly obsMirrorPerm: readonly number[];
	readonly actMirrorPerm: readonly number[];
	readonly weightsFile: string;
	readonly layers: readonly MlpLayerSpec[];
	readonly tensors: Readonly<Record<string, PackedTensorLayout>>;
	readonly motions: readonly V3NeuralPoseMotionSpec[];
	readonly onnxMaxAbsError?: number;
	readonly goldenTests?: readonly GoldenPolicyTest[];
};

export class V3GaitObservationHistory {
	readonly #featureDim: number;
	readonly #samples: number;
	readonly #seedFirstFrame: boolean;
	readonly #buf: Float32Array;
	#seeded = false;

	constructor(featureDim = 50, samples = 12, seedFirstFrame = false) {
		this.#featureDim = featureDim;
		this.#samples = samples;
		this.#seedFirstFrame = seedFirstFrame;
		this.#buf = new Float32Array(featureDim * samples);
	}

	reset(): void {
		this.#buf.fill(0);
		this.#seeded = false;
	}

	push(frame: ArrayLike<number>): Float32Array {
		const f = this.#featureDim;
		if (this.#seedFirstFrame && !this.#seeded) {
			for (let s = 0; s < this.#samples; s += 1) {
				for (let i = 0; i < f; i += 1) {
					this.#buf[s * f + i] = frame[i] ?? 0;
				}
			}
			this.#seeded = true;
			return this.#buf;
		}
		this.#seeded = true;
		this.#buf.copyWithin(f, 0, (this.#samples - 1) * f);
		for (let i = 0; i < f; i += 1) {
			this.#buf[i] = frame[i] ?? 0;
		}
		return this.#buf;
	}
}

/**
 * Exact TypeScript translation of `V3TensorSensors` (`Master/gateway/neural_gait/v3_microduck.py`):
 * 50 Hz One-Euro filtered joint angles/velocities + body gyro, proper acceleration in g,
 * projected gravity, twist command, previous raw action, and gated 1.65 Hz CPG phase.
 */
export class V3ProprioSensorFilter {
	readonly #qRaw = new Float64Array(12);
	readonly #qFilt = new Float64Array(12);
	readonly #deriv = new Float64Array(12);
	readonly #dqFilt = new Float64Array(12);
	readonly #gyro = new Float64Array(3);
	readonly #accelG = new Float64Array([0, 0, 1]);
	readonly #grav = new Float64Array([0, 0, -1]);
	readonly #prevLinVelB = new Float64Array(3);
	#feedbackInit = false;

	reset(q0Rad?: ArrayLike<number>): void {
		for (let j = 0; j < 12; j += 1) {
			const v = q0Rad?.[j] ?? 0;
			const clean = Number.isFinite(v) ? v : 0;
			this.#qRaw[j] = clean;
			this.#qFilt[j] = clean;
			this.#deriv[j] = 0;
			this.#dqFilt[j] = 0;
		}
		this.#gyro[0] = 0;
		this.#gyro[1] = 0;
		this.#gyro[2] = 0;
		this.#accelG[0] = 0;
		this.#accelG[1] = 0;
		this.#accelG[2] = 1;
		this.#grav[0] = 0;
		this.#grav[1] = 0;
		this.#grav[2] = -1;
		this.#prevLinVelB[0] = 0;
		this.#prevLinVelB[1] = 0;
		this.#prevLinVelB[2] = 0;
		this.#feedbackInit = true;
	}

	update50Hz(
		qTrueRad: ArrayLike<number>,
		gyroB: readonly [number, number, number],
		linVelB: readonly [number, number, number],
		gravB: readonly [number, number, number],
		dt = 0.02,
	): void {
		const alpha = 1 / (1 + 1 / (2 * Math.PI * 5 * dt));
		for (let j = 0; j < 12; j += 1) {
			const raw = qTrueRad[j] ?? 0;
			const qMeas = Number.isFinite(raw) ? raw : 0;
			const qPrevRaw = this.#qRaw[j] ?? 0;
			const prevDeriv = this.#deriv[j] ?? 0;
			const derivNew =
				prevDeriv + alpha * ((qMeas - qPrevRaw) / dt - prevDeriv);
			const cutoff = 1.5 + 1.43 * Math.abs(derivNew);
			const gain = 1 / (1 + 1 / (2 * Math.PI * cutoff * dt));
			const prevQFilt = this.#qFilt[j] ?? 0;
			const qFiltNew = prevQFilt + gain * (qMeas - prevQFilt);
			const prevDqFilt = this.#dqFilt[j] ?? 0;
			const dqFiltNew =
				prevDqFilt + alpha * ((qFiltNew - prevQFilt) / dt - prevDqFilt);
			if (this.#feedbackInit) {
				this.#qFilt[j] = qFiltNew;
				this.#deriv[j] = derivNew;
				this.#dqFilt[j] = dqFiltNew;
			} else {
				this.#qFilt[j] = qMeas;
				this.#deriv[j] = 0;
				this.#dqFilt[j] = 0;
			}
			this.#qRaw[j] = qMeas;
		}
		this.#feedbackInit = true;

		for (let a = 0; a < 3; a += 1) {
			const lv = Number.isFinite(linVelB[a]) ? linVelB[a] ?? 0 : 0;
			const gv = Number.isFinite(gravB[a]) ? gravB[a] ?? 0 : 0;
			const accB = (lv - (this.#prevLinVelB[a] ?? 0)) / dt - 9.81 * gv;
			this.#prevLinVelB[a] = lv;
			this.#accelG[a] = clamp(accB / 9.81, -4, 4);
			this.#gyro[a] = Number.isFinite(gyroB[a]) ? gyroB[a] ?? 0 : 0;
			this.#grav[a] = gv;
		}
	}

	writeFeatures(
		commandTwist: readonly [number, number, number],
		prevAction: ArrayLike<number>,
		phaseRad: number,
		out: Float32Array,
	): void {
		for (let j = 0; j < 12; j += 1) {
			out[j] = this.#qFilt[j] ?? 0;
			out[12 + j] = this.#dqFilt[j] ?? 0;
			out[36 + j] = prevAction[j] ?? 0;
		}
		out[24] = this.#gyro[0] ?? 0;
		out[25] = this.#gyro[1] ?? 0;
		out[26] = this.#gyro[2] ?? 0;
		out[27] = this.#accelG[0] ?? 0;
		out[28] = this.#accelG[1] ?? 0;
		out[29] = this.#accelG[2] ?? 1;
		out[30] = this.#grav[0] ?? 0;
		out[31] = this.#grav[1] ?? 0;
		out[32] = this.#grav[2] ?? -1;
		out[33] = commandTwist[0];
		out[34] = commandTwist[1];
		out[35] = commandTwist[2];
		const moving =
			Math.hypot(commandTwist[0], commandTwist[1]) +
				0.18 * Math.abs(commandTwist[2]) >
			0.02;
		out[48] = moving ? Math.sin(phaseRad) : 0;
		out[49] = moving ? Math.cos(phaseRad) : 0;
	}
}

/** Rotate world-frame linear velocity into body frame using MuJoCo quaternion [w, x, y, z]. */
export function bodyLinearVelocityFromWxyz(
	quatWxyz: readonly [number, number, number, number],
	velWorld: readonly [number, number, number],
): [number, number, number] {
	const [w, x, y, z] = quatWxyz;
	const [vx, vy, vz] = velWorld;
	const r00 = 1 - 2 * (y * y + z * z);
	const r10 = 2 * (x * y + w * z);
	const r20 = 2 * (x * z - w * y);
	const r01 = 2 * (x * y - w * z);
	const r11 = 1 - 2 * (x * x + z * z);
	const r21 = 2 * (y * z + w * x);
	const r02 = 2 * (x * z + w * y);
	const r12 = 2 * (y * z - w * x);
	const r22 = 1 - 2 * (x * x + y * y);
	return [
		r00 * vx + r10 * vy + r20 * vz,
		r01 * vx + r11 * vy + r21 * vz,
		r02 * vx + r12 * vy + r22 * vz,
	];
}

export class V3NeuralGaitPolicy {
	readonly manifest: V3NeuralGaitManifest;
	readonly #mean: Float32Array;
	readonly #std: Float32Array;
	readonly #normBuf: Float32Array;
	readonly #layers: readonly CompiledLayer[];

	constructor(manifest: V3NeuralGaitManifest, weights: Float32Array) {
		this.manifest = manifest;
		this.#mean = sliceTensor(weights, manifest.tensors, "mean");
		this.#std = sliceTensor(weights, manifest.tensors, "std");
		this.#normBuf = new Float32Array(manifest.obsDim);
		this.#layers = buildLayers(weights, manifest.tensors, manifest.layers);
	}

	predictAction(obs: ArrayLike<number>): number[] {
		const raw = runNormalizedMlp(
			obs,
			this.#mean,
			this.#std,
			this.#normBuf,
			this.#layers,
		);
		const action: number[] = new Array(12);
		for (let i = 0; i < 12; i += 1) {
			action[i] = clamp(raw[i] ?? 0, -1, 1);
		}
		return action;
	}

	computeGaitHz(commandTwist: readonly [number, number, number]): number {
		const lo = this.manifest.gaitHzMin;
		const hi = this.manifest.gaitHzMax;
		if (lo !== undefined && hi !== undefined) {
			const lin = Math.hypot(commandTwist[0], commandTwist[1]);
			const eff = clamp(
				lin / 0.38 + (0.45 * Math.abs(commandTwist[2])) / 1.3,
				0,
				1,
			);
			return lo + (hi - lo) * eff;
		}
		return this.manifest.gaitHz;
	}

	actionToJointDeg(action: ArrayLike<number>): number[] {
		if (
			this.manifest.actionSpace === "normalized-foot-offsets-v3-ik" ||
			this.manifest.footActionScaleMm
		) {
			return decodeV3FootOffsetsToJointDeg(
				action,
				this.manifest.footActionScaleMm ?? [55, 22, 32],
				this.manifest.jointMinDeg,
				this.manifest.jointMaxDeg,
			);
		}
		const scales = this.manifest.actionScaleDeg ?? [25, 45, 45];
		const out: number[] = new Array(12);
		for (let i = 0; i < 12; i += 1) {
			const scale = scales[i % 3] ?? 30;
			const lo = this.manifest.jointMinDeg[i] ?? -30;
			const hi = this.manifest.jointMaxDeg[i] ?? 30;
			out[i] = clamp(clamp(action[i] ?? 0, -1, 1) * scale, lo, hi);
		}
		return out;
	}
}

export class V3PoseObservationHistory {
	readonly #featureDim: number;
	readonly #samples: number;
	readonly #buf: Float32Array;
	#seeded = false;

	constructor(featureDim = 86, samples = 15) {
		this.#featureDim = featureDim;
		this.#samples = samples;
		this.#buf = new Float32Array(featureDim * samples);
	}

	reset(): void {
		this.#buf.fill(0);
		this.#seeded = false;
	}

	push(frame: ArrayLike<number>): Float32Array {
		const f = this.#featureDim;
		if (!this.#seeded) {
			for (let s = 0; s < this.#samples; s += 1) {
				for (let i = 0; i < f; i += 1) {
					this.#buf[s * f + i] = frame[i] ?? 0;
				}
			}
			this.#seeded = true;
			return this.#buf;
		}
		this.#buf.copyWithin(f, 0, (this.#samples - 1) * f);
		for (let i = 0; i < f; i += 1) {
			this.#buf[i] = frame[i] ?? 0;
		}
		return this.#buf;
	}
}

export class V3NeuralPosePolicy {
	readonly manifest: V3NeuralPoseManifest;
	readonly #mean: Float32Array;
	readonly #std: Float32Array;
	readonly #obsMirrorPerm: Int32Array;
	readonly #obsMirrorSign: Float32Array;
	readonly #actMirrorPerm: Int32Array;
	readonly #actMirrorSign: Float32Array;
	readonly #normBuf: Float32Array;
	readonly #mirroredObsBuf: Float32Array;
	readonly #y1Buf = new Float32Array(12);
	readonly #layers: readonly CompiledLayer[];

	constructor(manifest: V3NeuralPoseManifest, weights: Float32Array) {
		this.manifest = manifest;
		this.#mean = sliceTensor(weights, manifest.tensors, "mean");
		this.#std = sliceTensor(weights, manifest.tensors, "std");
		this.#obsMirrorPerm = Int32Array.from(manifest.obsMirrorPerm);
		this.#obsMirrorSign = sliceTensor(
			weights,
			manifest.tensors,
			"obsMirrorSign",
		);
		this.#actMirrorPerm = Int32Array.from(manifest.actMirrorPerm);
		this.#actMirrorSign = sliceTensor(
			weights,
			manifest.tensors,
			"actMirrorSign",
		);
		this.#normBuf = new Float32Array(manifest.obsDim);
		this.#mirroredObsBuf = new Float32Array(manifest.obsDim);
		this.#layers = buildLayers(weights, manifest.tensors, manifest.layers);
	}

	degToNorm(anglesDeg: ArrayLike<number>): number[] {
		const out: number[] = new Array(12);
		for (let i = 0; i < 12; i += 1) {
			const c = this.manifest.jointCenterDeg[i] ?? 0;
			const s = this.manifest.jointHalfSpanDeg[i] ?? 45;
			out[i] = clamp(((anglesDeg[i] ?? 0) - c) / s, -1, 1);
		}
		return out;
	}

	normToDeg(actionNorm: ArrayLike<number>): number[] {
		const out: number[] = new Array(12);
		for (let i = 0; i < 12; i += 1) {
			const c = this.manifest.jointCenterDeg[i] ?? 0;
			const s = this.manifest.jointHalfSpanDeg[i] ?? 45;
			const lo = this.manifest.jointMinDeg[i] ?? -45;
			const hi = this.manifest.jointMaxDeg[i] ?? 45;
			out[i] = clamp(c + clamp(actionNorm[i] ?? 0, -1, 1) * s, lo, hi);
		}
		return out;
	}

	predictAction(obs: ArrayLike<number>): number[] {
		const y1Raw = runNormalizedMlp(
			obs,
			this.#mean,
			this.#std,
			this.#normBuf,
			this.#layers,
		);
		this.#y1Buf.set(y1Raw);

		const obsDim = this.manifest.obsDim;
		for (let i = 0; i < obsDim; i += 1) {
			const srcIdx = this.#obsMirrorPerm[i] ?? i;
			this.#mirroredObsBuf[i] =
				(obs[srcIdx] ?? 0) * (this.#obsMirrorSign[i] ?? 1);
		}
		const y2Raw = runNormalizedMlp(
			this.#mirroredObsBuf,
			this.#mean,
			this.#std,
			this.#normBuf,
			this.#layers,
		);

		const goalStart = this.manifest.goalSliceStart;
		const resScale = this.manifest.residualScale;
		const action: number[] = new Array(12);
		for (let i = 0; i < 12; i += 1) {
			const mIdx = this.#actMirrorPerm[i] ?? i;
			const y2 = (y2Raw[mIdx] ?? 0) * (this.#actMirrorSign[i] ?? 1);
			const sym = 0.5 * ((this.#y1Buf[i] ?? 0) + y2) * resScale;
			const base = obs[goalStart + i] ?? 0;
			action[i] = clamp(base + sym, -1, 1);
		}
		return action;
	}
}

type V3LegKinSpec = {
	readonly rollSign: number;
	readonly shoulderMm: readonly [number, number, number];
	readonly carrierMm: readonly [number, number, number];
	readonly crankMm: readonly [number, number, number];
	readonly soleInKneeMm: readonly [number, number, number];
	readonly neutralSoleRobotMm: readonly [number, number, number];
};

const V3_CARRIER_MM = 54.0;
const V3_CRANK_MM = 22.0;
const V3_PICKUP_MM = 46.0;
const V3_ROD_MM = 56.0;
const V3_ALPHA_ZERO_RAD = -2.202809465985;
const V3_THETA_ZERO_RAD = 3.055204643652;
const V3_BETA_OFFSET_RAD = Math.PI + 0.4256858;
const V3_RAD2DEG = 180 / Math.PI;

const V3_LEG_SPECS: readonly V3LegKinSpec[] = [
	// RL
	{
		rollSign: -1,
		shoulderMm: [-128.0, 47.2, 140.0],
		carrierMm: [36.05, 3.66, -19.75],
		crankMm: [16.0, 3.66, 0.25],
		soleInKneeMm: [133.3995, 44.5, -25.4657],
		neutralSoleRobotMm: [-55.9487, 95.36, -40.9336],
	},
	// RR
	{
		rollSign: 1,
		shoulderMm: [-128.0, -47.2, 140.0],
		carrierMm: [36.05, -3.66, -19.75],
		crankMm: [16.0, -3.66, 0.25],
		soleInKneeMm: [133.3995, -44.5, -25.4657],
		neutralSoleRobotMm: [-55.9487, -95.36, -40.9336],
	},
	// FL
	{
		rollSign: -1,
		shoulderMm: [143.5, 47.2, 140.0],
		carrierMm: [-16.0, 3.66, -19.75],
		crankMm: [-36.05, 3.66, 0.25],
		soleInKneeMm: [133.3995, 44.5, -25.4657],
		neutralSoleRobotMm: [163.5013, 95.36, -40.9336],
	},
	// FR
	{
		rollSign: 1,
		shoulderMm: [143.5, -47.2, 140.0],
		carrierMm: [-16.0, -3.66, -19.75],
		crankMm: [-36.05, -3.66, 0.25],
		soleInKneeMm: [133.3995, -44.5, -25.4657],
		neutralSoleRobotMm: [163.5013, -95.36, -40.9336],
	},
];

function wrapPi(rad: number): number {
	return Math.atan2(Math.sin(rad), Math.cos(rad));
}

type V3FkCheck = {
	readonly footMm: readonly [number, number, number];
	readonly sinTransmission: number;
};

function solveV3LegFkFoot(
	leg: V3LegKinSpec,
	hDeg: number,
	alphaDeg: number,
	thetaDeg: number,
): V3FkCheck | undefined {
	const a = V3_ALPHA_ZERO_RAD + alphaDeg * DEG2RAD;
	const t = V3_THETA_ZERO_RAD + thetaDeg * DEG2RAD;
	const dx = leg.carrierMm[0] + V3_CARRIER_MM * Math.cos(a);
	const dz = leg.carrierMm[2] + V3_CARRIER_MM * Math.sin(a);
	const px = leg.crankMm[0] + V3_CRANK_MM * Math.cos(t);
	const pz = leg.crankMm[2] + V3_CRANK_MM * Math.sin(t);
	const wx = px - dx;
	const wz = pz - dz;
	const d = Math.hypot(wx, wz);
	if (d <= 10.5 || d >= 101.5) return undefined;
	const pk2 = V3_PICKUP_MM * V3_PICKUP_MM;
	const rd2 = V3_ROD_MM * V3_ROD_MM;
	const along = (pk2 - rd2 + d * d) / (2 * d);
	const h2 = pk2 - along * along;
	if (h2 <= 0) return undefined;
	const hh = Math.sqrt(h2);
	const ex = dx + (along * wx - hh * wz) / d;
	const ez = dz + (along * wz + hh * wx) / d;
	const ux = (ex - dx) / V3_PICKUP_MM;
	const uz = (ez - dz) / V3_PICKUP_MM;
	const vxRod = (ex - px) / V3_ROD_MM;
	const vzRod = (ez - pz) / V3_ROD_MM;
	const sinTransmission = Math.abs(ux * vzRod - uz * vxRod);
	const beta = Math.atan2(ez - dz, ex - dx);
	const kneeRotY = -wrapPi(beta - V3_BETA_OFFSET_RAD);
	const cy = Math.cos(kneeRotY);
	const sy = Math.sin(kneeRotY);
	const [sx, syLat, sz] = leg.soleInKneeMm;
	const fxSh = dx + cy * sx + sy * sz;
	const fySh = leg.carrierMm[1] + syLat;
	const fzSh = dz - sy * sx + cy * sz;
	const rx = leg.rollSign * hDeg * DEG2RAD;
	const cr = Math.cos(rx);
	const sr = Math.sin(rx);
	return {
		footMm: [
			leg.shoulderMm[0] + fxSh,
			leg.shoulderMm[1] + cr * fySh - sr * fzSh,
			leg.shoulderMm[2] + sr * fySh + cr * fzSh,
		],
		sinTransmission,
	};
}

function solveV3LegIkOffset(
	legIdx: number,
	dxMm: number,
	dyMm: number,
	dzMm: number,
): readonly [number, number, number] | undefined {
	const leg = V3_LEG_SPECS[legIdx];
	if (!leg) return undefined;
	const tx = leg.neutralSoleRobotMm[0] + dxMm - leg.shoulderMm[0];
	const ty = leg.neutralSoleRobotMm[1] + dyMm - leg.shoulderMm[1];
	const tz = leg.neutralSoleRobotMm[2] + dzMm - leg.shoulderMm[2];

	const yConst = leg.carrierMm[1] + leg.soleInKneeMm[1];
	const r2 = ty * ty + tz * tz;
	if (r2 <= yConst * yConst + 1e-4) return undefined;
	const zSh = -Math.sqrt(r2 - yConst * yConst);
	const cr = (yConst * ty + zSh * tz) / r2;
	const sr = (yConst * tz - zSh * ty) / r2;
	const hDeg = clamp((Math.atan2(sr, cr) * V3_RAD2DEG) / leg.rollSign, -30, 30);

	const ox = leg.carrierMm[0];
	const oz = leg.carrierMm[2];
	const sx = leg.soleInKneeMm[0];
	const sz = leg.soleInKneeMm[2];
	const lFoot = Math.hypot(sx, sz);
	const vx = tx - ox;
	const vz = zSh - oz;
	const dist = Math.hypot(vx, vz);
	if (
		dist < Math.abs(V3_CARRIER_MM - lFoot) + 1e-3 ||
		dist > V3_CARRIER_MM + lFoot - 1e-3
	) {
		return undefined;
	}
	const c2 = V3_CARRIER_MM * V3_CARRIER_MM;
	const f2 = lFoot * lFoot;
	const along = (c2 - f2 + dist * dist) / (2 * dist);
	const h2 = c2 - along * along;
	if (h2 < 0) return undefined;
	const hh = Math.sqrt(h2);

	const ax = ox + (along * vx - hh * vz) / dist;
	const az = oz + (along * vz + hh * vx) / dist;
	const bx = ox + (along * vx + hh * vz) / dist;
	const bz = oz + (along * vz - hh * vx) / dist;
	const nkx = ox + V3_CARRIER_MM * Math.cos(V3_ALPHA_ZERO_RAD);
	const nkz = oz + V3_CARRIER_MM * Math.sin(V3_ALPHA_ZERO_RAD);
	const da = (ax - nkx) * (ax - nkx) + (az - nkz) * (az - nkz);
	const db = (bx - nkx) * (bx - nkx) + (bz - nkz) * (bz - nkz);
	const kx = da <= db ? ax : bx;
	const kz = da <= db ? az : bz;
	const alphaDeg = clamp(
		wrapPi(Math.atan2(kz - oz, kx - ox) - V3_ALPHA_ZERO_RAD) * V3_RAD2DEG,
		-40,
		50,
	);

	const lx = tx - kx;
	const lz = zSh - kz;
	const cy = (lx * sx + lz * sz) / f2;
	const sy = (lx * sz - lz * sx) / f2;
	const beta = V3_BETA_OFFSET_RAD - Math.atan2(sy, cy);
	const ex = kx + V3_PICKUP_MM * Math.cos(beta);
	const ez = kz + V3_PICKUP_MM * Math.sin(beta);

	const cx = leg.crankMm[0];
	const cz = leg.crankMm[2];
	const exc = ex - cx;
	const ezc = ez - cz;
	const dc = Math.hypot(exc, ezc);
	if (
		dc < Math.abs(V3_CRANK_MM - V3_ROD_MM) + 1e-3 ||
		dc > V3_CRANK_MM + V3_ROD_MM - 1e-3
	) {
		return undefined;
	}
	const ca =
		(V3_CRANK_MM * V3_CRANK_MM - V3_ROD_MM * V3_ROD_MM + dc * dc) / (2 * dc);
	const ch2 = V3_CRANK_MM * V3_CRANK_MM - ca * ca;
	if (ch2 < 0) return undefined;
	const ch = Math.sqrt(ch2);

	let bestTheta = 0;
	let bestScore = 1e9;
	let found = false;
	for (const s of [-1, 1]) {
		const px = cx + (ca * exc - s * ch * ezc) / dc;
		const pz = cz + (ca * ezc + s * ch * exc) / dc;
		const td =
			wrapPi(Math.atan2(pz - cz, px - cx) - V3_THETA_ZERO_RAD) * V3_RAD2DEG;
		if (td < -51 || td > 51) continue;
		const tc = clamp(td, -50, 50);
		const fk = solveV3LegFkFoot(leg, hDeg, alphaDeg, tc);
		if (!fk || fk.sinTransmission < 0.15) continue;
		const err = Math.hypot(
			fk.footMm[0] - (leg.neutralSoleRobotMm[0] + dxMm),
			fk.footMm[2] - (leg.neutralSoleRobotMm[2] + dzMm),
		);
		if (err > 5.0) continue;
		const score = err + 0.005 * Math.abs(tc);
		if (score < bestScore) {
			bestScore = score;
			bestTheta = tc;
			found = true;
		}
	}
	if (!found) return undefined;
	return [hDeg, alphaDeg, bestTheta];
}

/**
 * Exact TypeScript translation of `V3TensorBody.decode` (`v3_microduck.py`) and
 * `ainekio_v3_microduck_predict` (`Slave/software/models/v3-12servo/v3_microduck.c`):
 * scales normalized [-1, 1] foot offsets by `footScaleMm` and runs 2-stage smooth
 * boundary bisection (Stage 1: 6-step vertical z bisection from clamp(dz, 0, 14) -> dz
 * preserving 100% horizontal stride; Stage 2: 7-step radial bisection from neutral).
 */
export function decodeV3FootOffsetsToJointDeg(
	action: ArrayLike<number>,
	footScaleMm: readonly [number, number, number] = [78, 28, 36],
	jointMinDeg?: readonly number[],
	jointMaxDeg?: readonly number[],
): number[] {
	const out: number[] = new Array(12);
	const sx = footScaleMm[0] ?? 78;
	const sy = footScaleMm[1] ?? 28;
	const sz = footScaleMm[2] ?? 36;
	for (let l = 0; l < 4; l += 1) {
		const base = l * 3;
		const dx = clamp(action[base] ?? 0, -1, 1) * sx;
		const dy = clamp(action[base + 1] ?? 0, -1, 1) * sy;
		const dz = clamp(action[base + 2] ?? 0, -1, 1) * sz;
		let solved = solveV3LegIkOffset(l, dx, dy, dz);
		if (!solved) {
			const zRef = clamp(dz, 0, 14);
			const refSol = solveV3LegIkOffset(l, dx, dy, zRef);
			if (refSol) {
				let lo = 0;
				let hi = 1;
				solved = refSol;
				for (let k = 0; k < 6; k += 1) {
					const mid = 0.5 * (lo + hi);
					const zm = zRef + (dz - zRef) * mid;
					const cand = solveV3LegIkOffset(l, dx, dy, zm);
					if (cand) {
						lo = mid;
						solved = cand;
					} else {
						hi = mid;
					}
				}
			} else {
				let lo = 0;
				let hi = 1;
				solved = [0, 0, 0];
				for (let k = 0; k < 7; k += 1) {
					const mid = 0.5 * (lo + hi);
					const cand = solveV3LegIkOffset(l, dx * mid, dy * mid, dz * mid);
					if (cand) {
						lo = mid;
						solved = cand;
					} else {
						hi = mid;
					}
				}
			}
		}
		const [hDeg, aDeg, tDeg] = solved ?? [0, 0, 0];
		out[base] = clamp(
			hDeg,
			jointMinDeg?.[base] ?? -30,
			jointMaxDeg?.[base] ?? 30,
		);
		out[base + 1] = clamp(
			aDeg,
			jointMinDeg?.[base + 1] ?? -40,
			jointMaxDeg?.[base + 1] ?? 50,
		);
		out[base + 2] = clamp(
			tDeg,
			jointMinDeg?.[base + 2] ?? -50,
			jointMaxDeg?.[base + 2] ?? 50,
		);
	}
	return out;
}

/** Exact TypeScript translation of `Slave/software/models/v3-12servo/v3_motion.c` `ainekio_v3_posture_angles`. */
export function sampleV3NativePostureDeg(name: string): number[] | undefined {
	switch (name) {
		case "stand":
		case "home":
		case "neutral":
			return [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
		case "crouch":
			return [-4, -22, 28, -4, -22, 28, -4, -22, 28, -4, -22, 28];
		case "lay":
		case "lay_down":
		case "rest":
		case "sleep":
			return [-8, -38, 46, -8, -38, 46, -8, -38, 46, -8, -38, 46];
		case "sit":
			return [-4, -34, 42, -4, -34, 42, 0, 14, -12, 0, 14, -12];
		case "bow":
		case "play_bow":
			return [0, 12, -10, 0, 12, -10, -4, -34, 42, -4, -34, 42];
		case "stretch":
			return [0, -18, -24, 0, -18, -24, 0, 24, 28, 0, 24, 28];
		case "wave":
		case "wave_fr":
			return [-6, -8, 8, 4, -14, 16, 6, -12, 14, -12, 36, 42];
		case "wave_fl":
			return [4, -14, 16, -6, -8, 8, -12, 36, 42, 6, -12, 14];
		default:
			return undefined;
	}
}

const V3_TROT_PHASE = [0.5, 0.0, 0.0, 0.5] as const;

/** Exact TypeScript translation of `Slave/software/models/v3-12servo/v3_motion.c` `ainekio_v3_analytic_trot`. */
export function sampleV3NativeWalkDeg(
	phaseCycles: number,
	vxMS: number,
	vyMS: number,
	wzRadS: number,
): number[] {
	const out = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
	const cmdMag = Math.hypot(vxMS, vyMS) + 0.18 * Math.abs(wzRadS);
	if (cmdMag < 0.015) return out;
	const vxNorm = clamp(vxMS / 0.35, -1, 1);
	const vyNorm = clamp(vyMS / 0.2, -1, 1);
	const wzNorm = clamp(wzRadS / 1.5, -1, 1);
	const liftScale = Math.min(1, cmdMag / 0.08);
	for (let l = 0; l < 4; l += 1) {
		const leg = V3_LEG_SPECS[l];
		if (!leg) continue;
		let p = (phaseCycles + (V3_TROT_PHASE[l] ?? 0)) % 1;
		if (p < 0) p += 1;
		let sweep = 0;
		let liftMm = 0;
		if (p < 0.5) {
			const u = p / 0.5;
			sweep = -Math.cos(u * Math.PI);
			liftMm = 26 * Math.sin(u * Math.PI) * liftScale;
		} else {
			const u = (p - 0.5) / 0.5;
			sweep = 1 - 2 * u;
		}
		const rxLeg = leg.neutralSoleRobotMm[0] * 0.001;
		const ryLeg = leg.neutralSoleRobotMm[1] * 0.001;
		const dxMm = 32 * (vxNorm - wzNorm * ryLeg * 6) * sweep;
		const dyMm = 24 * (vyNorm + wzNorm * rxLeg * 4) * sweep;
		const dzMm = -8 + liftMm;
		const solved = solveV3LegIkOffset(l, dxMm, dyMm, dzMm) ?? [0, 0, 0];
		out[l * 3] = solved[0];
		out[l * 3 + 1] = solved[1];
		out[l * 3 + 2] = solved[2];
	}
	return out;
}

/**
 * Exact pure-TypeScript port of Ainekio's V2 closed-chain four-bar PoseManifold
 * (`experiments/freestyle/neural_pose/goals.py:_FastNumPyBody` + `PoseManifold`).
 *
 * Guarantees that every 50 Hz `walk_target` (`feet_mm[12]`) sent by Neural Pose
 * resolves cleanly at `fraction = 1.0` inside the ESP32-P4 C firmware's
 * `ainekio_v2_nominal_foot_pose`, with zero P4 binary-halving jumps and exact
 * calibrated carrier-home clearance (`CARRIER_HOME_MARGIN_DEG = 3.0`).
 */

const DEG2RAD = Math.PI / 180;
const RAD2DEG = 180 / Math.PI;

export type PoseManifoldGoldenTest = {
	readonly inputDeg: readonly number[];
	readonly projectedDeg: readonly number[];
	readonly footNorm: readonly number[];
	readonly prevQDeg: readonly number[];
	readonly speedScale: number;
	readonly nextQDeg: readonly number[];
	readonly appliedAct: readonly number[];
	readonly feetMm: readonly number[];
};

export type PoseManifoldConfig = {
	readonly schemaVersion: number;
	readonly geometryId: string;
	readonly referenceJointDeg: readonly number[];
	readonly standAnglesDeg: readonly number[];
	readonly targetLimitsDeg: readonly (readonly [number, number])[];
	readonly motorNoLoadSpeedDegS: number;
	readonly O: readonly [number, number];
	readonly C: readonly [number, number];
	readonly A: number;
	readonly r: number;
	readonly L: number;
	readonly b: number;
	readonly a0: number;
	readonly t0: number;
	readonly b0: number;
	readonly branch: number;
	readonly sign: readonly (readonly [number, number, number])[];
	readonly translation: readonly (readonly [number, number, number])[];
	readonly shoulder: readonly (readonly [number, number, number])[];
	readonly mirror: readonly number[];
	readonly reference: readonly (readonly [number, number, number])[];
	readonly home: readonly (readonly [number, number, number])[];
	readonly pulseHome: readonly (readonly [number, number, number])[];
	readonly pulseScale: readonly (readonly [number, number, number])[];
	readonly low: readonly (readonly [number, number, number])[];
	readonly high: readonly (readonly [number, number, number])[];
	readonly q0: readonly (readonly [number, number, number])[];
	readonly origin: readonly (readonly [number, number, number])[];
	readonly scale: readonly [number, number, number];
	readonly tickUs: number;
	readonly projectionFractions: readonly number[];
	readonly goldenTests?: readonly PoseManifoldGoldenTest[];
};

function wrapAngle(x: number): number {
	return Math.atan2(Math.sin(x), Math.cos(x));
}

function clamp(v: number, lo: number, hi: number): number {
	return v < lo ? lo : v > hi ? hi : v;
}

function circleIntersect(
	d2: number,
	radius: number,
	other: number,
): {
	readonly along: number;
	readonly height: number;
	readonly valid: boolean;
} {
	const safe = d2 > 1e-8 ? d2 : 1e-8;
	const along = (radius * radius - other * other + d2) / (2 * safe);
	const hSq = (radius * radius) / safe - along * along;
	const height = hSq > 0 ? Math.sqrt(hSq) : 0;
	const diff = radius - other;
	const sum = radius + other;
	const valid = d2 > 1e-8 && d2 >= diff * diff && d2 <= sum * sum;
	return { along, height, valid };
}

type LegSeedResult = {
	readonly dx: number;
	readonly dz: number;
	readonly bc: number;
	readonly bs: number;
	readonly lc: number;
	readonly ls: number;
	readonly valid: boolean;
};

export class PoseManifoldRuntime {
	readonly config: PoseManifoldConfig;
	readonly #cb0: number;
	readonly #sb0: number;
	readonly #length2: Float64Array;
	readonly #length: Float64Array;
	readonly #dx0: Float64Array;
	readonly #dz0: Float64Array;
	readonly #crankBranch: Float64Array;
	readonly #geomAlphas: Float64Array;

	constructor(config: PoseManifoldConfig) {
		this.config = config;
		this.#cb0 = Math.cos(config.b0);
		this.#sb0 = Math.sin(config.b0);
		this.#length2 = new Float64Array(4);
		this.#length = new Float64Array(4);
		this.#dx0 = new Float64Array(4);
		this.#dz0 = new Float64Array(4);
		this.#crankBranch = new Float64Array(4);

		for (let l = 0; l < 4; l += 1) {
			const ref = config.reference[l] ?? [0, 0, 0];
			const len2 = ref[0] * ref[0] + ref[2] * ref[2];
			this.#length2[l] = len2;
			this.#length[l] = Math.sqrt(len2);
			const q0l = config.q0[l] ?? [0, 0, 0];
			const s = this.#seedLeg(q0l[1], q0l[2]);
			this.#dx0[l] = s.dx;
			this.#dz0[l] = s.dz;
			const oldt = config.t0 + q0l[2];
			this.#crankBranch[l] =
				(s.dx + config.b * s.bc - config.C[0]) * Math.sin(oldt) -
				(s.dz + config.b * s.bs - config.C[1]) * Math.cos(oldt);
		}

		// Precompute np.geomspace(0.001, 1.0, 24)
		this.#geomAlphas = new Float64Array(24);
		const logStart = Math.log(0.001);
		const logEnd = 0;
		for (let i = 0; i < 24; i += 1) {
			this.#geomAlphas[i] = Math.exp(logStart + ((logEnd - logStart) * i) / 23);
		}
	}

	get geometryId(): string {
		return this.config.geometryId;
	}

	get referenceJointDeg(): readonly number[] {
		return this.config.referenceJointDeg;
	}

	get standAnglesDeg(): readonly number[] {
		return this.config.standAnglesDeg;
	}

	#seedLeg(qCarrier: number, qCrank: number): LegSeedResult {
		const c = this.config;
		const a = qCarrier + c.a0;
		const t = qCrank + c.t0;
		const dx = c.O[0] + c.A * Math.cos(a);
		const dz = c.O[1] + c.A * Math.sin(a);
		const x = c.C[0] + c.r * Math.cos(t) - dx;
		const z = c.C[1] + c.r * Math.sin(t) - dz;
		const ci = circleIntersect(x * x + z * z, c.b, c.L);
		const height = ci.height * c.branch;
		const bc = (ci.along * x - height * z) / c.b;
		const bs = (ci.along * z + height * x) / c.b;
		const lc = bc * this.#cb0 + bs * this.#sb0;
		const ls = bs * this.#cb0 - bc * this.#sb0;
		return { dx, dz, bc, bs, lc, ls, valid: ci.valid };
	}

	forwardLeg(
		l: number,
		q0: number,
		q1: number,
		q2: number,
	): {
		readonly x: number;
		readonly y: number;
		readonly z: number;
		readonly valid: boolean;
	} {
		const c = this.config;
		const s = this.#seedLeg(q1, q2);
		const ch = Math.cos(q0);
		const sh = Math.sin(q0);
		const ref = c.reference[l] ?? [0, 0, 0];
		const tr = c.translation[l] ?? [0, 0, 0];
		const shd = c.shoulder[l] ?? [0, 0, 0];
		const sgn = c.sign[l] ?? [1, 1, 1];
		const mir = c.mirror[l] ?? 1;

		const px = s.dx + s.lc * ref[0] - s.ls * ref[2];
		const py = tr[1] + ref[1];
		const pz = tr[2] + s.dz + s.ls * ref[0] + s.lc * ref[2];

		const pt0 = tr[0] + mir * px;
		const pt1 = ch * py - sh * pz;
		const pt2 = sh * py + ch * pz;

		return {
			x: shd[0] + sgn[0] * pt0,
			y: shd[1] + sgn[1] * pt1,
			z: shd[2] + sgn[2] * pt2,
			valid: s.valid,
		};
	}

	forward(qRad12: ArrayLike<number>): {
		readonly points: Float64Array;
		readonly valid: [boolean, boolean, boolean, boolean];
	} {
		const points = new Float64Array(12);
		const valid: [boolean, boolean, boolean, boolean] = [
			false,
			false,
			false,
			false,
		];
		for (let l = 0; l < 4; l += 1) {
			const res = this.forwardLeg(
				l,
				qRad12[l * 3] ?? 0,
				qRad12[l * 3 + 1] ?? 0,
				qRad12[l * 3 + 2] ?? 0,
			);
			points[l * 3] = res.x;
			points[l * 3 + 1] = res.y;
			points[l * 3 + 2] = res.z;
			valid[l] = res.valid;
		}
		return { points, valid };
	}

	inverseLeg(
		l: number,
		tx: number,
		ty: number,
		tz: number,
	): {
		readonly q0: number;
		readonly q1: number;
		readonly q2: number;
		readonly valid: boolean;
	} {
		const c = this.config;
		const shd = c.shoulder[l] ?? [0, 0, 0];
		const sgn = c.sign[l] ?? [1, 1, 1];
		const tr = c.translation[l] ?? [0, 0, 0];
		const ref = c.reference[l] ?? [0, 0, 0];
		const mir = c.mirror[l] ?? 1;
		const q0l = c.q0[l] ?? [0, 0, 0];

		const vx = (tx - shd[0]) * sgn[0];
		const vy = (ty - shd[1]) * sgn[1];
		const vz = (tz - shd[2]) * sgn[2];
		const y = tr[1] + ref[1];
		const vy2vz2 = vy * vy + vz * vz;
		const zz = vy2vz2 - y * y;
		const zRoot = -Math.sqrt(zz > 0 ? zz : 0);
		const norm = vy2vz2 > 1e-8 ? vy2vz2 : 1e-8;
		const hc = (y * vy + zRoot * vz) / norm;
		const hs = (y * vz - zRoot * vy) / norm;

		const x = (vx - tr[0]) * mir - c.O[0];
		const z = zRoot - tr[2] - c.O[1];
		const ci = circleIntersect(x * x + z * z, c.A, this.#length[l] ?? 0);

		const ax = c.O[0] + ci.along * x - ci.height * z;
		const az = c.O[1] + ci.along * z + ci.height * x;
		const bx = c.O[0] + ci.along * x + ci.height * z;
		const bz = c.O[1] + ci.along * z - ci.height * x;
		const dx0 = this.#dx0[l] ?? 0;
		const dz0 = this.#dz0[l] ?? 0;
		const first =
			(ax - dx0) * (ax - dx0) + (az - dz0) * (az - dz0) <=
			(bx - dx0) * (bx - dx0) + (bz - dz0) * (bz - dz0);
		const dx = first ? ax : bx;
		const dz = first ? az : bz;

		const lx = x + c.O[0] - dx;
		const lz = z + c.O[1] - dz;
		const len2 = this.#length2[l] || 1;
		const lc = (lx * ref[0] + lz * ref[2]) / len2;
		const ls = (lz * ref[0] - lx * ref[2]) / len2;
		const bc = this.#cb0 * lc - this.#sb0 * ls;
		const bs = this.#sb0 * lc + this.#cb0 * ls;
		const ex = dx + c.b * bc;
		const ez = dz + c.b * bs;

		const cx = ex - c.C[0];
		const cz = ez - c.C[1];
		const cci = circleIntersect(cx * cx + cz * cz, c.r, c.L);
		const cb = this.#crankBranch[l] ?? 1;

		const px0 = c.C[0] + cci.along * cx + cci.height * cz;
		const pz0 = c.C[1] + cci.along * cz - cci.height * cx;
		const ang0 = wrapAngle(Math.atan2(pz0 - c.C[1], px0 - c.C[0]) - c.t0);
		const ok0 =
			(cx * (pz0 - c.C[1]) - cz * (px0 - c.C[0])) * cb > 0 &&
			((px0 - dx) * (ez - dz) - (pz0 - dz) * (ex - dx)) * c.branch >= 0;

		const px1 = c.C[0] + cci.along * cx - cci.height * cz;
		const pz1 = c.C[1] + cci.along * cz + cci.height * cx;
		const ang1 = wrapAngle(Math.atan2(pz1 - c.C[1], px1 - c.C[0]) - c.t0);
		const ok1 =
			(cx * (pz1 - c.C[1]) - cz * (px1 - c.C[0])) * cb > 0 &&
			((px1 - dx) * (ez - dz) - (pz1 - dz) * (ex - dx)) * c.branch >= 0;

		const d0 = Math.abs(wrapAngle(ang0 - q0l[2]));
		const d1 = Math.abs(wrapAngle(ang1 - q0l[2]));
		const choose0 = ok0 && (!ok1 || d0 <= d1);
		const theta = choose0 ? ang0 : ang1;

		return {
			q0: Math.atan2(hs, hc),
			q1: wrapAngle(Math.atan2(dz - c.O[1], dx - c.O[0]) - c.a0),
			q2: theta,
			valid: ci.valid && cci.valid && zz >= 0 && (ok0 || ok1),
		};
	}

	pulseValidLeg(l: number, q0: number, q1: number, q2: number): boolean {
		const ph = this.config.pulseHome[l] ?? [1500, 1500, 1500];
		const hm = this.config.home[l] ?? [0, 0, 0];
		const ps = this.config.pulseScale[l] ?? [10, 10, 10];
		const p0 = Math.floor(ph[0] + (q0 * RAD2DEG - hm[0]) * ps[0] + 0.5);
		const p1 = Math.floor(ph[1] + (q1 * RAD2DEG - hm[1]) * ps[1] + 0.5);
		const p2 = Math.floor(ph[2] + (q2 * RAD2DEG - hm[2]) * ps[2] + 0.5);
		return (
			p1 >= 300 &&
			p1 <= 2950 &&
			p2 >= 300 &&
			p2 <= 2950 &&
			p0 >= 1 &&
			p0 <= 65535 &&
			p1 >= 1 &&
			p1 <= 65535 &&
			p2 >= 1 &&
			p2 <= 65535
		);
	}

	boundedLeg(
		l: number,
		q0In: number,
		q1In: number,
		q2In: number,
	): {
		readonly q0: number;
		readonly q1: number;
		readonly q2: number;
		readonly valid: boolean;
	} {
		const lo = this.config.low[l] ?? [-3, -3, -3];
		const hi = this.config.high[l] ?? [3, 3, 3];
		if (
			q0In >= lo[0] &&
			q0In <= hi[0] &&
			q1In >= lo[1] &&
			q1In <= hi[1] &&
			q2In >= lo[2] &&
			q2In <= hi[2]
		) {
			const f = this.forwardLeg(l, q0In, q1In, q2In);
			return { q0: q0In, q1: q1In, q2: q2In, valid: f.valid };
		}

		const target = this.forwardLeg(l, q0In, q1In, q2In);
		const q0 = clamp(q0In, lo[0], hi[0]);
		let q1 = clamp(q1In, lo[1], hi[1]);
		let q2 = clamp(q2In, lo[2], hi[2]);
		const probeStep = Math.PI / 18000;
		const fracs = this.config.projectionFractions;

		for (let iter = 0; iter < 8; iter += 1) {
			const pos = this.forwardLeg(l, q0, q1, q2);
			const ex = target.x - pos.x;
			const ey = target.y - pos.y;
			const ez = target.z - pos.z;
			const cost = ex * ex + ey * ey + ez * ez;
			if (cost < 1e-8) {
				break;
			}
			const step1 = q1 + probeStep <= hi[1] ? probeStep : -probeStep;
			const step2 = q2 + probeStep <= hi[2] ? probeStep : -probeStep;
			const p1 = this.forwardLeg(l, q0, q1 + step1, q2);
			const p2 = this.forwardLeg(l, q0, q1, q2 + step2);
			const derivOk =
				pos.valid &&
				p1.valid &&
				p2.valid &&
				q1 + step1 >= lo[1] &&
				q2 + step2 >= lo[2];
			if (!derivOk) {
				break;
			}
			const ja0 = (p1.x - pos.x) / step1;
			const ja1 = (p1.y - pos.y) / step1;
			const ja2 = (p1.z - pos.z) / step1;
			const jb0 = (p2.x - pos.x) / step2;
			const jb1 = (p2.y - pos.y) / step2;
			const jb2 = (p2.z - pos.z) / step2;

			const a = ja0 * ja0 + ja1 * ja1 + ja2 * ja2;
			const bDot = ja0 * jb0 + ja1 * jb1 + ja2 * jb2;
			const d = jb0 * jb0 + jb1 * jb1 + jb2 * jb2;
			const e = ja0 * ex + ja1 * ey + ja2 * ez;
			const f = jb0 * ex + jb1 * ey + jb2 * ez;
			const det = a * d - bDot * bDot;
			const detSafe = det > 1e-12 ? det : 1e-12;
			const aSafe = a > 1e-12 ? a : 1e-12;
			const dSafe = d > 1e-12 ? d : 1e-12;
			let sa = det > 1e-12 ? (d * e - bDot * f) / detSafe : e / aSafe;
			let sb = det > 1e-12 ? (a * f - bDot * e) / detSafe : f / dSafe;
			if ((q1 <= lo[1] && sa < 0) || (q1 >= hi[1] && sa > 0)) {
				sa = 0;
				sb = f / dSafe;
			}
			if ((q2 <= lo[2] && sb < 0) || (q2 >= hi[2] && sb > 0)) {
				sb = 0;
				sa = e / aSafe;
			}

			let updated = false;
			for (let k = 0; k < fracs.length; k += 1) {
				const fr = fracs[k] ?? 1;
				const nq1 = clamp(q1 + fr * sa, lo[1], hi[1]);
				const nq2 = clamp(q2 + fr * sb, lo[2], hi[2]);
				const pt = this.forwardLeg(l, q0, nq1, nq2);
				if (!pt.valid) {
					continue;
				}
				const dx = target.x - pt.x;
				const dy = target.y - pt.y;
				const dz = target.z - pt.z;
				if (dx * dx + dy * dy + dz * dz < cost) {
					q1 = nq1;
					q2 = nq2;
					updated = true;
					break;
				}
			}
			if (!updated) {
				break;
			}
		}

		const finalF = this.forwardLeg(l, q0, q1, q2);
		return { q0, q1, q2, valid: finalF.valid };
	}

	continuousDecodeLeg(
		l: number,
		ax: number,
		ay: number,
		az: number,
		gridSteps = 65,
		subSteps = 17,
	): [number, number, number] {
		const org = this.config.origin[l] ?? [0, 0, 0];
		const sc = this.config.scale;
		const lo = this.config.low[l] ?? [-3, -3, -3];
		const hi = this.config.high[l] ?? [3, 3, 3];
		const dx = ax * sc[0];
		const dy = ay * sc[1];
		const dz = az * sc[2];
		const maxStepGrid = 18 * DEG2RAD;
		const maxStepSub = 12 * DEG2RAD;

		const qGrid0 = new Float64Array(gridSteps);
		const qGrid1 = new Float64Array(gridSteps);
		const qGrid2 = new Float64Array(gridSteps);
		let idxLo = 0;

		for (let i = 0; i < gridSteps; i += 1) {
			const s = i / (gridSteps - 1);
			const inv = this.inverseLeg(
				l,
				org[0] + dx * s,
				org[1] + dy * s,
				org[2] + dz * s,
			);
			qGrid0[i] = inv.q0;
			qGrid1[i] = inv.q1;
			qGrid2[i] = inv.q2;
			if (i === 0) {
				idxLo = 0;
			} else if (idxLo === i - 1) {
				const step = Math.max(
					Math.abs(inv.q0 - (qGrid0[i - 1] ?? 0)),
					Math.abs(inv.q1 - (qGrid1[i - 1] ?? 0)),
					Math.abs(inv.q2 - (qGrid2[i - 1] ?? 0)),
				);
				if (inv.valid && step <= maxStepGrid) {
					idxLo = i;
				}
			}
		}

		let g0 = qGrid0[idxLo] ?? 0;
		let g1 = qGrid1[idxLo] ?? 0;
		let g2 = qGrid2[idxLo] ?? 0;

		if (idxLo < gridSteps - 1) {
			const sLo = idxLo / (gridSteps - 1);
			const sHi = Math.min(idxLo + 1, gridSteps - 1) / (gridSteps - 1);
			let prev0 = g0;
			let prev1 = g1;
			let prev2 = g2;
			for (let k = 1; k < subSteps - 1; k += 1) {
				const u = k / (subSteps - 1);
				const s = sLo + u * (sHi - sLo);
				const inv = this.inverseLeg(
					l,
					org[0] + dx * s,
					org[1] + dy * s,
					org[2] + dz * s,
				);
				const step = Math.max(
					Math.abs(inv.q0 - prev0),
					Math.abs(inv.q1 - prev1),
					Math.abs(inv.q2 - prev2),
				);
				if (inv.valid && step <= maxStepSub) {
					prev0 = inv.q0;
					prev1 = inv.q1;
					prev2 = inv.q2;
					g0 = inv.q0;
					g1 = inv.q1;
					g2 = inv.q2;
				} else {
					break;
				}
			}
		}

		const inBounds =
			g0 >= lo[0] &&
			g0 <= hi[0] &&
			g1 >= lo[1] &&
			g1 <= hi[1] &&
			g2 >= lo[2] &&
			g2 <= hi[2];
		let c0 = g0;
		let c1 = g1;
		let c2 = g2;
		let candOk: boolean;
		if (!inBounds) {
			const proj = this.boundedLeg(l, g0, g1, g2);
			c0 = proj.q0;
			c1 = proj.q1;
			c2 = proj.q2;
			candOk = proj.valid && this.pulseValidLeg(l, c0, c1, c2);
		} else {
			candOk = this.pulseValidLeg(l, c0, c1, c2);
		}
		if (candOk) {
			return [c0, c1, c2];
		}

		// Fallback: last strictly in-bounds ray point
		let sIdx = 0;
		for (let i = 1; i <= idxLo; i += 1) {
			const qi0 = qGrid0[i] ?? 0;
			const qi1 = qGrid1[i] ?? 0;
			const qi2 = qGrid2[i] ?? 0;
			if (
				qi0 >= lo[0] &&
				qi0 <= hi[0] &&
				qi1 >= lo[1] &&
				qi1 <= hi[1] &&
				qi2 >= lo[2] &&
				qi2 <= hi[2] &&
				this.pulseValidLeg(l, qi0, qi1, qi2)
			) {
				sIdx = i;
			} else {
				break;
			}
		}
		return [qGrid0[sIdx] ?? 0, qGrid1[sIdx] ?? 0, qGrid2[sIdx] ?? 0];
	}

	continuousDecodeRad(actions12: ArrayLike<number>): Float64Array {
		const out = new Float64Array(12);
		for (let l = 0; l < 4; l += 1) {
			const [q0, q1, q2] = this.continuousDecodeLeg(
				l,
				actions12[l * 3] ?? 0,
				actions12[l * 3 + 1] ?? 0,
				actions12[l * 3 + 2] ?? 0,
			);
			out[l * 3] = q0;
			out[l * 3 + 1] = q1;
			out[l * 3 + 2] = q2;
		}
		return out;
	}

	projectAnglesDeg(anglesDeg12: ArrayLike<number>): {
		readonly deg: number[];
		readonly footNorm: number[];
	} {
		const qB = new Float64Array(12);
		const sc = this.config.scale;
		const footNormInitial = new Float64Array(12);

		for (let l = 0; l < 4; l += 1) {
			const lo = this.config.low[l] ?? [-3, -3, -3];
			const hi = this.config.high[l] ?? [3, 3, 3];
			const lim0 = this.config.targetLimitsDeg[l * 3] ?? [-180, 180];
			const lim1 = this.config.targetLimitsDeg[l * 3 + 1] ?? [-180, 180];
			const lim2 = this.config.targetLimitsDeg[l * 3 + 2] ?? [-180, 180];

			const c0 = clamp(
				clamp((anglesDeg12[l * 3] ?? 0) * DEG2RAD, lo[0], hi[0]),
				lim0[0] * DEG2RAD,
				lim0[1] * DEG2RAD,
			);
			const c1 = clamp(
				clamp((anglesDeg12[l * 3 + 1] ?? 0) * DEG2RAD, lo[1], hi[1]),
				lim1[0] * DEG2RAD,
				lim1[1] * DEG2RAD,
			);
			const c2 = clamp(
				clamp((anglesDeg12[l * 3 + 2] ?? 0) * DEG2RAD, lo[2], hi[2]),
				lim2[0] * DEG2RAD,
				lim2[1] * DEG2RAD,
			);

			const b = this.boundedLeg(l, c0, c1, c2);
			let f = this.forwardLeg(l, b.q0, b.q1, b.q2);
			let r0 = b.q0;
			let r1 = b.q1;
			let r2 = b.q2;
			if (!b.valid || !f.valid) {
				const q0l = this.config.q0[l] ?? [0, 0, 0];
				r0 = q0l[0];
				r1 = q0l[1];
				r2 = q0l[2];
				f = this.forwardLeg(l, r0, r1, r2);
			}
			qB[l * 3] = r0;
			qB[l * 3 + 1] = r1;
			qB[l * 3 + 2] = r2;
			const org = this.config.origin[l] ?? [0, 0, 0];
			footNormInitial[l * 3] = clamp((f.x - org[0]) / sc[0], -1, 1);
			footNormInitial[l * 3 + 1] = clamp((f.y - org[1]) / sc[1], -1, 1);
			footNormInitial[l * 3 + 2] = clamp((f.z - org[2]) / sc[2], -1, 1);
		}

		const qConsistent = this.continuousDecodeRad(footNormInitial);
		const fwd = this.forward(qConsistent);
		const deg: number[] = [];
		const footNorm: number[] = [];
		for (let l = 0; l < 4; l += 1) {
			const org = this.config.origin[l] ?? [0, 0, 0];
			for (let k = 0; k < 3; k += 1) {
				deg.push((qConsistent[l * 3 + k] ?? 0) * RAD2DEG);
				footNorm.push(
					clamp(
						((fwd.points[l * 3 + k] ?? 0) - (org[k] ?? 0)) / (sc[k] ?? 1),
						-1,
						1,
					),
				);
			}
		}
		return { deg, footNorm };
	}

	/**
	 * Matches `PoseManifold.step_host_command` in `experiments/freestyle/neural_pose/goals.py`.
	 */
	stepHostCommand(
		actions12: ArrayLike<number>,
		prevQRad12: ArrayLike<number>,
		speedScale = 1.0,
	): {
		readonly nextQRad: Float64Array;
		readonly appliedAction: number[];
		readonly feetMm: number[];
	} {
		const maxTravel =
			(this.config.motorNoLoadSpeedDegS *
				clamp(speedScale, 0.25, 1.0) *
				DEG2RAD) /
			50.0;
		const goal = this.continuousDecodeRad(actions12);
		const nextQRad = new Float64Array(12);
		const sc = this.config.scale;

		for (let l = 0; l < 4; l += 1) {
			const i0 = l * 3;
			const p0 = prevQRad12[i0] ?? 0;
			const p1 = prevQRad12[i0 + 1] ?? 0;
			const p2 = prevQRad12[i0 + 2] ?? 0;
			const d0 = (goal[i0] ?? 0) - p0;
			const d1 = (goal[i0 + 1] ?? 0) - p1;
			const d2 = (goal[i0 + 2] ?? 0) - p2;
			const legMax = Math.max(Math.abs(d0), Math.abs(d1), Math.abs(d2), 1e-12);
			const u = Math.min(maxTravel / legMax, 1.0);
			const cand = this.boundedLeg(l, p0 + u * d0, p1 + u * d1, p2 + u * d2);
			let sel0 = cand.q0;
			let sel1 = cand.q1;
			let sel2 = cand.q2;
			let ok = cand.valid && this.pulseValidLeg(l, sel0, sel1, sel2);

			if (!ok) {
				// Step along the closed foot-space manifold to avoid concave four-bar toggle boundary
				const fPrev = this.forwardLeg(l, p0, p1, p2);
				const fGoal = this.forwardLeg(
					l,
					goal[i0] ?? 0,
					goal[i0 + 1] ?? 0,
					goal[i0 + 2] ?? 0,
				);
				const org = this.config.origin[l] ?? [0, 0, 0];
				const ap0 = (fPrev.x - org[0]) / sc[0];
				const ap1 = (fPrev.y - org[1]) / sc[1];
				const ap2 = (fPrev.z - org[2]) / sc[2];
				const ag0 = (fGoal.x - org[0]) / sc[0];
				const ag1 = (fGoal.y - org[1]) / sc[1];
				const ag2 = (fGoal.z - org[2]) / sc[2];

				let bestWithin: [number, number, number] | undefined;
				let firstAny: [number, number, number] | undefined;
				for (let k = 0; k < this.#geomAlphas.length; k += 1) {
					const alpha = this.#geomAlphas[k] ?? 1;
					const [pq0, pq1, pq2] = this.continuousDecodeLeg(
						l,
						ap0 + alpha * (ag0 - ap0),
						ap1 + alpha * (ag1 - ap1),
						ap2 + alpha * (ag2 - ap2),
					);
					const pf = this.forwardLeg(l, pq0, pq1, pq2);
					if (!pf.valid || !this.pulseValidLeg(l, pq0, pq1, pq2)) {
						continue;
					}
					const stepSz = Math.max(
						Math.abs(pq0 - p0),
						Math.abs(pq1 - p1),
						Math.abs(pq2 - p2),
					);
					if (stepSz > 1e-5) {
						if (!firstAny) {
							firstAny = [pq0, pq1, pq2];
						}
						if (stepSz <= maxTravel * 1.15) {
							bestWithin = [pq0, pq1, pq2];
						}
					}
				}
				const chosen = bestWithin ?? firstAny;
				if (chosen) {
					sel0 = chosen[0];
					sel1 = chosen[1];
					sel2 = chosen[2];
					ok = true;
				}
			}

			nextQRad[i0] = ok ? sel0 : p0;
			nextQRad[i0 + 1] = ok ? sel1 : p1;
			nextQRad[i0 + 2] = ok ? sel2 : p2;
		}

		const fwd = this.forward(nextQRad);
		const feetMm: number[] = [];
		const appliedAction: number[] = [];
		for (let l = 0; l < 4; l += 1) {
			const org = this.config.origin[l] ?? [0, 0, 0];
			for (let k = 0; k < 3; k += 1) {
				const off = (fwd.points[l * 3 + k] ?? 0) - (org[k] ?? 0);
				feetMm.push(off);
				appliedAction.push(clamp(off / (sc[k] ?? 1), -1, 1));
			}
		}
		return { nextQRad, appliedAction, feetMm };
	}

	feetMmForAnglesRad(qRad12: ArrayLike<number>): number[] {
		const fwd = this.forward(qRad12);
		const out: number[] = [];
		for (let l = 0; l < 4; l += 1) {
			const org = this.config.origin[l] ?? [0, 0, 0];
			for (let k = 0; k < 3; k += 1) {
				out.push((fwd.points[l * 3 + k] ?? 0) - (org[k] ?? 0));
			}
		}
		return out;
	}
}

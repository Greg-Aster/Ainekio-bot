/* Planar closed-chain kinematics. Coordinates: mm, x forward, z up; radians. */
(function (root) {
  "use strict";
  const add = (a, b) => [a[0] + b[0], a[1] + b[1]],
    sub = (a, b) => [a[0] - b[0], a[1] - b[1]];
  const mul = (a, s) => [a[0] * s, a[1] * s],
    dot = (a, b) => a[0] * b[0] + a[1] * b[1];
  const cross = (a, b) => a[0] * b[1] - a[1] * b[0],
    perp = (a) => [-a[1], a[0]];
  const norm = (a) => Math.hypot(...a),
    rad = (d) => (d * Math.PI) / 180,
    deg = (r) => (r * 180) / Math.PI;
  const rotate = (a, r) => [
    a[0] * Math.cos(r) - a[1] * Math.sin(r),
    a[0] * Math.sin(r) + a[1] * Math.cos(r),
  ];
  const wrap = (a) => Math.atan2(Math.sin(a), Math.cos(a));
  function circle(o, r, c, s, branch) {
    const v = sub(c, o),
      d = norm(v);
    if (d < 1e-10) return null;
    const along = (r * r - s * s + d * d) / (2 * d),
      h2 = r * r - along * along;
    if (h2 < -1e-7) return null;
    return add(
      o,
      add(
        mul(v, along / d),
        mul(perp(v), (branch * Math.sqrt(Math.max(0, h2))) / d)
      )
    );
  }
  function valid(g) {
    return (
      ["carrier", "crank", "rod", "pickup", "leg"].every(
        (k) => Number.isFinite(g[k]) && g[k] > 0
      ) && ["shaftX", "shaftZ", "footAngle"].every((k) => Number.isFinite(g[k]))
    );
  }
  function enrich(g, D, E, P, T) {
    const O = [0, 0],
      C = [g.shaftX, g.shaftZ],
      out = sub(E, D),
      rod = sub(E, P),
      ip = sub(P, C);
    const den = cross(out, rod),
      da = perp(D),
      dt = perp(ip),
      foot = sub(T, D);
    const J =
      Math.abs(den) < 1e-8
        ? null
        : [
            add(da, mul(perp(foot), -dot(rod, da) / den)),
            mul(perp(foot), dot(rod, dt) / den),
          ];
    return {
      ok: true,
      O,
      C,
      D,
      E,
      P,
      T,
      J,
      alpha: Math.atan2(D[1], D[0]),
      theta: Math.atan2(ip[1], ip[0]),
      closureBranch: Math.sign(cross(sub(P, D), out)),
      legAngle: deg(Math.asin(Math.min(1, Math.abs(foot[1]) / g.leg))),
      outputAngle: deg(
        Math.asin(Math.min(1, Math.abs(den) / (g.pickup * g.rod)))
      ),
      inputAngle: deg(
        Math.asin(Math.min(1, Math.abs(cross(ip, rod)) / (g.crank * g.rod)))
      ),
    };
  }
  function inverse(g, T) {
    if (!valid(g) || !T.every(Number.isFinite))
      return { ok: false, reason: "Enter finite, positive link lengths." };
    const D = circle([0, 0], g.carrier, T, g.leg, g.kneeBranch);
    if (!D)
      return {
        ok: false,
        reason: "Foot is outside carrier + lower-leg reach.",
      };
    const u = mul(rotate(sub(T, D), -rad(g.footAngle)), -1 / g.leg),
      E = add(D, mul(u, g.pickup));
    const P = circle([g.shaftX, g.shaftZ], g.crank, E, g.rod, g.crankBranch);
    if (!P)
      return {
        ok: false,
        reason: "Rod cannot connect the pickup to this crank shaft.",
      };
    return enrich(g, D, E, P, T);
  }
  function forward(g, alpha, theta, branch = 1) {
    if (!valid(g)) return { ok: false, reason: "Invalid dimensions." };
    const D = mul([Math.cos(alpha), Math.sin(alpha)], g.carrier);
    const P = add(
      [g.shaftX, g.shaftZ],
      mul([Math.cos(theta), Math.sin(theta)], g.crank)
    );
    const E = circle(D, g.pickup, P, g.rod, branch);
    if (!E)
      return {
        ok: false,
        reason: "These shaft angles cannot close the linkage.",
      };
    const T = add(
      D,
      mul(rotate(sub(E, D), rad(g.footAngle)), -g.leg / g.pickup)
    );
    return enrich(g, D, E, P, T);
  }
  function localToBody(m, p) {
    const b = m.basis;
    return [
      m.carrier[0] + b[0][0] * p[0] + b[0][1] * p[1],
      m.carrier[1] + b[1][0] * p[0] + b[1][1] * p[1],
    ];
  }
  function bodyToLocal(m, p) {
    const b = m.basis,
      v = sub(p, m.carrier),
      det = b[0][0] * b[1][1] - b[0][1] * b[1][0];
    return [
      (b[1][1] * v[0] - b[0][1] * v[1]) / det,
      (-b[1][0] * v[0] + b[0][0] * v[1]) / det,
    ];
  }
  function path(p, phase, mount, ground) {
    phase = ((phase % 1) + 1) % 1;
    const stance = phase < p.duty,
      u = stance ? 0 : (phase - p.duty) / (1 - p.duty);
    const smooth = 10 * u ** 3 - 15 * u ** 4 + 6 * u ** 5,
      correction = u - 10 * u ** 3 + 15 * u ** 4 - 6 * u ** 5;
    const x = stance
      ? p.stroke * (0.5 - phase / p.duty)
      : -p.stroke / 2 +
        p.stroke * smooth -
        ((p.stroke * (1 - p.duty)) / p.duty) * correction;
    return {
      stance,
      body: [
        mount.carrier[0] + p.center + x,
        ground + (stance ? 0 : p.lift * 64 * u ** 3 * (1 - u) ** 3),
      ],
    };
  }
  function torques(solution, mount, Fx, Fz) {
    if (!solution.J) return null;
    return solution.J.map((j) => {
      const b = mount.basis,
        world = [
          b[0][0] * j[0] + b[0][1] * j[1],
          b[1][0] * j[0] + b[1][1] * j[1],
        ];
      return -(world[0] * Fx + world[1] * Fz) / 1000;
    });
  }
  function analyze(g, p, mount, ground, n = 240) {
    const samples = [],
      load = ((p.mass / 1000) * 9.80665) / p.supports;
    for (let i = 0; i < n; i++) {
      const phase = i / n,
        t = path(p, phase, mount, ground),
        s = inverse(g, bodyToLocal(mount, t.body));
      samples.push({
        ...s,
        phase,
        stance: t.stance,
        target: t.body,
        torque: s.ok && t.stance ? torques(s, mount, p.push, load) : null,
      });
    }
    const good = samples.filter((s) => s.ok),
      planted = good.filter((s) => s.stance);
    let previous = null,
      branchChanges = 0;
    for (const s of samples) {
      if (!s.ok) {
        previous = null;
        continue;
      }
      s.q = [s.alpha, s.theta];
      if (previous) {
        s.q = s.q.map((a, j) => previous.q[j] + wrap(a - previous.q[j]));
        if (s.closureBranch !== previous.closureBranch) branchChanges++;
      }
      previous = s;
    }
    const ranges = [0, 1].map((j) =>
      good.length
        ? deg(
            Math.max(...good.map((s) => s.q[j])) -
              Math.min(...good.map((s) => s.q[j]))
          )
        : NaN
    );
    const speeds = [0, 0],
      peakTorque = [0, 0],
      rmsTorque = [0, 0];
    let singular = 0;
    for (let i = 0; i < n; i++) {
      const s = samples[i],
        before = samples[(i + n - 1) % n],
        after = samples[(i + 1) % n];
      if (s.ok && !s.J) singular++;
      if (s.ok && before.ok && after.ok) {
        s.speed = [
          deg(wrap(after.alpha - before.alpha)),
          deg(wrap(after.theta - before.theta)),
        ].map((v) => (v * n) / (2 * p.period));
        s.speed.forEach(
          (v, j) => (speeds[j] = Math.max(speeds[j], Math.abs(v)))
        );
      }
      if (s.torque)
        s.torque.forEach((v, j) => {
          peakTorque[j] = Math.max(peakTorque[j], Math.abs(v));
          rmsTorque[j] += v * v;
        });
    }
    const torqueCount = planted.filter((s) => s.torque).length;
    for (let j = 0; j < 2; j++)
      rmsTorque[j] = torqueCount ? Math.sqrt(rmsTorque[j] / torqueCount) : NaN;
    const maxPeak = Math.max(...peakTorque),
      imbalance = maxPeak
        ? (100 * Math.abs(peakTorque[0] - peakTorque[1])) / maxPeak
        : 0;
    return {
      samples,
      validCount: good.length,
      count: n,
      complete: good.length === n,
      branchChanges,
      singular,
      ranges,
      speeds,
      peakTorque,
      rmsTorque,
      imbalance,
      load,
      minLegAngle: planted.length
        ? Math.min(...planted.map((s) => s.legAngle))
        : NaN,
      minOutputAngle: planted.length
        ? Math.min(...planted.map((s) => s.outputAngle))
        : NaN,
      minInputAngle: planted.length
        ? Math.min(...planted.map((s) => s.inputAngle))
        : NaN,
      travelFits: ranges.every((v) => v <= p.travel),
      torqueComplete: torqueCount === samples.filter((s) => s.stance).length,
    };
  }
  function longestStroke(g, p, mount, ground) {
    let best = null;
    for (
      let stroke = 0;
      stroke <= Math.ceil(2 * (g.carrier + g.leg));
      stroke++
    ) {
      const a = analyze(g, { ...p, stroke }, mount, ground, 120);
      if (a.complete && a.travelFits && !a.singular && !a.branchChanges)
        best = stroke;
    }
    return best;
  }
  const api = {
    add,
    sub,
    mul,
    norm,
    dot,
    cross,
    perp,
    rad,
    deg,
    wrap,
    circle,
    forward,
    inverse,
    localToBody,
    bodyToLocal,
    path,
    torques,
    analyze,
    longestStroke,
  };
  root.LegMechanics = api;
  if (typeof module !== "undefined") module.exports = api;
})(globalThis);

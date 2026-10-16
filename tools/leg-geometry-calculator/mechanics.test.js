"use strict";
const test = require("node:test"),
  assert = require("node:assert/strict");
const M = require("./mechanics.js"),
  R = require("./robot-data.js");
const geometry = () => ({
  ...R.dimensions,
  footAngle: 0,
  kneeBranch: -1,
  crankBranch: -1,
});
const path = {
  stroke: 32,
  center: 0,
  clearance: 45,
  lift: 8,
  period: 1.8,
  duty: 0.8,
  mass: 566,
  supports: 3,
  push: 0,
  travel: 230,
};
const near = (a, b, t = 1e-7) => assert.ok(Math.abs(a - b) < t, `${a} != ${b}`);
test("WAVEGO-like same-side foot closes with the fixed shafts and correct Jacobian", () => {
  const phi = Math.atan2(30.8076, 39.8153 + 31.775);
  const g = {...geometry(), leg:50,carrier:30,crank:30,rod:52,pickup:40,
    footAngle:-180+M.deg(phi),kneeBranch:1,crankBranch:-1};
  for(const h of [40,55,65,70,75])for(const x of (h<60?[0]:[-25,0,25])) {
    const s=M.inverse(g,[x,-h]); assert.ok(s.ok && s.J);
    const f=M.forward(g,s.alpha,s.theta,s.closureBranch);
    near(M.norm(M.sub(f.T,s.T)),0);
    const bend=M.add(s.D,M.mul(M.sub(s.E,s.D),50*Math.cos(phi)/40));
    near(M.dot(M.sub(bend,s.D),M.sub(s.T,bend)),0,1e-7);
    near(M.norm(M.sub(s.T,bend)),50*Math.sin(phi));
    assert.ok(M.dot(M.sub(s.E,s.D),M.sub(s.T,s.D))>0);
    for(let j=0;j<2;j++) {
      const plus=[s.alpha,s.theta],minus=plus.slice(),eps=1e-6;
      plus[j]+=eps;minus[j]-=eps;
      const a=M.forward(g,...plus,s.closureBranch),b=M.forward(g,...minus,s.closureBranch);
      assert.ok(a.ok && b.ok);
      for(let k=0;k<2;k++)near((a.T[k]-b.T[k])/(2*eps),s.J[j][k],1e-4);
    }
  }
});
test("IK closes all five links and independently reconstructs the point foot", () => {
  let n = 0;
  for (const leg of [45, 50, 55])
    for (const shaftX of [-25, -12.5, 10])
      for (const footAngle of [-15, 0, 20])
        for (let x = -30; x <= 30; x += 5) {
          const g = { ...geometry(), leg, shaftX, footAngle },
            s = M.inverse(g, [x, -60]);
          if (!s.ok) continue;
          n++;
          near(M.norm(s.D), g.carrier);
          near(M.norm(M.sub(s.P, s.C)), g.crank);
          near(M.norm(M.sub(s.E, s.P)), g.rod);
          near(M.norm(M.sub(s.E, s.D)), g.pickup);
          near(M.norm(M.sub(s.T, s.D)), g.leg);
          const f = M.forward(g, s.alpha, s.theta, s.closureBranch);
          assert.ok(f.ok);
          near(f.T[0], s.T[0]);
          near(f.T[1], s.T[1]);
        }
  assert.ok(n > 100);
});
test("analytic closed-chain Jacobian matches central differences and virtual work", () => {
  for (const x of [-20, -5, 10, 20])
    for (const footAngle of [0, 18]) {
      const g = { ...geometry(), footAngle },
        s = M.inverse(g, [x, -62]);
      assert.ok(s.ok && s.J);
      const q = [s.alpha, s.theta],
        eps = 1e-6;
      for (let j = 0; j < 2; j++) {
        const a = q.slice(),
          b = q.slice();
        a[j] += eps;
        b[j] -= eps;
        const f = M.forward(g, ...a, s.closureBranch),
          r = M.forward(g, ...b, s.closureBranch);
        for (let k = 0; k < 2; k++)
          near((f.T[k] - r.T[k]) / (2 * eps), s.J[j][k], 1e-4);
      }
      const tau = M.torques(s, R.mounts[0], 0.4, 2),
        dq = [eps, -eps],
        f = M.forward(g, q[0] + dq[0], q[1] + dq[1], s.closureBranch);
      const a = M.localToBody(R.mounts[0], s.T),
        b = M.localToBody(R.mounts[0], f.T);
      near(
        tau[0] * dq[0] + tau[1] * dq[1],
        -(0.4 * (b[0] - a[0]) + 2 * (b[1] - a[1])) / 1000,
        1e-10
      );
    }
});
test("installed shaft separation is taken from exported coordinates", () => {
  for (const mount of R.mounts) {
    const p = M.localToBody(mount, [R.dimensions.shaftX, R.dimensions.shaftZ]);
    near(p[0], mount.crank[0]);
    near(p[1], mount.crank[1]);
  }
  near(R.dimensions.shaftX, -12.50007220289615, 1e-6);
  near(R.dimensions.shaftZ, 11.50002646686177, 1e-6);
});
test("same link ratios with a moved shaft produce different angles and torque", () => {
  const a = M.inverse(geometry(), [0, -62]),
    b = M.inverse({ ...geometry(), shaftX: 0 }, [0, -62]);
  assert.ok(a.ok && b.ok);
  assert.ok(Math.abs(a.theta - b.theta) > 0.1);
  assert.ok(
    Math.abs(
      M.torques(a, R.mounts[0], 0, 2)[1] - M.torques(b, R.mounts[0], 0, 2)[1]
    ) > 0.001
  );
});
test("coordinate translation preserves geometry; moving mounts within the chassis does not", () => {
  const g = geometry(),
    m = R.mounts[0],
    z = R.bodyBottom - path.clearance;
  const a = M.analyze(g, path, m, z),
    b = M.analyze(
      g,
      path,
      { ...m, carrier: [m.carrier[0] + 40, m.carrier[1] + 20] },
      z + 20
    );
  assert.ok(a.complete && b.complete);
  a.ranges.forEach((v, j) => near(v, b.ranges[j]));
  const c = M.analyze(
    g,
    path,
    { ...m, carrier: [m.carrier[0], m.carrier[1] + 10] },
    z
  );
  assert.ok(!c.complete || Math.abs(c.ranges[0] - a.ranges[0]) > 0.5);
});
test("cycle is continuous across lift-off/touchdown and speed scales with period", () => {
  const g = geometry(),
    m = R.mounts[0],
    z = R.bodyBottom - path.clearance;
  for (const phase of [0, path.duty]) {
    const a = M.path(path, phase - 1e-7, m, z),
      b = M.path(path, phase + 1e-7, m, z);
    assert.ok(M.norm(M.sub(a.body, b.body)) < 0.0001);
  }
  const a = M.analyze(g, path, m, z),
    b = M.analyze(g, { ...path, period: path.period * 2 }, m, z);
  a.speeds.forEach((v, j) => near(v / 2, b.speeds[j]));
  a.peakTorque.forEach((v, j) => near(v, b.peakTorque[j]));
});
test("unreachable path is reported rather than reduced; mass scales torque", () => {
  const g = geometry(),
    m = R.mounts[0],
    z = R.bodyBottom - path.clearance;
  const bad = M.analyze(g, { ...path, stroke: 300 }, m, z);
  assert.ok(!bad.complete);
  assert.equal(bad.count, 240);
  const a = M.analyze(g, path, m, z),
    b = M.analyze(g, { ...path, mass: path.mass * 2 }, m, z);
  a.peakTorque.forEach((v, j) => near(v * 2, b.peakTorque[j]));
});
test("stroke search returns the largest successful sampled candidate in its stated domain", () => {
  const g = geometry(),
    m = R.mounts[0],
    z = R.bodyBottom - path.clearance,
    best = M.longestStroke(g, path, m, z);
  assert.ok(best !== null);
  const a = M.analyze(g, { ...path, stroke: best }, m, z, 120);
  assert.ok(a.complete && a.travelFits && !a.singular && !a.branchChanges);
  for (let n = best + 1; n <= Math.ceil(2 * (g.carrier + g.leg)); n++) {
    const b = M.analyze(g, { ...path, stroke: n }, m, z, 120);
    assert.ok(!b.complete || !b.travelFits || b.singular || b.branchChanges);
  }
});

/* Offline fixed-shaft WAVEGO-topology study. No robot connection or firmware edits.
 * Run: node tools/leg-geometry-calculator/wavego-study.js > /tmp/wavego-study.json
 */
"use strict";
const M = require("./mechanics.js"), R = require("./robot-data.js");
const mount = { carrier: [0, 0], basis: [[1, 0], [0, 1]] };
const phi = M.deg(Math.atan2(30.8076, 39.8153 + 31.775));
const force = 0.566 * 9.80665 / 3;
const path = { stroke: 50, center: 0, lift: 12, period: 1.8,
  duty: 0.8, mass: 566, supports: 3, push: 0, travel: 230 };
const range = (a, b, d) => Array.from({length: Math.floor((b-a)/d)+1}, (_, i) => a+i*d);
const heights = [60, 65, 70];
const targets = heights.flatMap(h => range(-25, 25, 5).map(x => [x, -h]));
targets.push(...range(40, 70, 2).map(h => [0, -h]));
const cycles = [65, 70].map(h => range(0, 119, 1).map(i => {
  const p = M.path(path, i/120, mount, -h);
  return {T:p.body, stance:p.stance};
}));
function footBend(g, s) {
  // WAVEGO's straight pickup/continuation plus a perpendicular toe segment.
  const angle=M.wrap(M.rad(g.footAngle)-Math.PI);
  return M.add(s.D,M.mul(M.sub(s.E,s.D),g.leg*Math.cos(angle)/g.pickup));
}
function screen(g) {
  let branch, peak = [0,0], squares = [0,0], n = 0;
  const get = T => {
    const s = M.inverse(g, T);
    if (!s.ok || !s.J || !s.closureBranch) return null;
    if (branch === undefined) branch = s.closureBranch;
    return s.closureBranch === branch ? s : null;
  };
  for (const T of targets) {
    const s = get(T); if (!s) return null;
    for (const push of [-0.25, 0, 0.25]) {
      const t = M.torques(s, mount, push*force, force);
      t.forEach((v,j) => peak[j] = Math.max(peak[j],Math.abs(v)));
    }
  }
  let speed = [0,0], excursion = [0,0];
  for (const cycle of cycles) {
    const ss = [];
    for (const p of cycle) {
      const s = get(p.T); if (!s) return null;
      if (p.stance) {
        M.torques(s,mount,0,force).forEach((v,j) => squares[j] += v*v);
        n++;
      }
      ss.push([s.alpha,s.theta]);
    }
    let q=ss[0].slice(), lo=q.slice(), hi=q.slice();
    for (let i=0; i<ss.length; i++) for (let j=0;j<2;j++) {
      if(i) q[j]+=M.wrap(ss[i][j]-ss[i-1][j]);
      lo[j]=Math.min(lo[j],q[j]); hi[j]=Math.max(hi[j],q[j]);
      const before=ss[(i+ss.length-1)%ss.length],after=ss[(i+1)%ss.length];
      speed[j]=Math.max(speed[j],Math.abs(M.deg(M.wrap(after[j]-before[j]))*ss.length/(2*path.period)));
    }
    excursion=excursion.map((v,j)=>Math.max(v,M.deg(hi[j]-lo[j])));
  }
  if(excursion.some(v=>v>path.travel))return null;
  const rms=squares.map(v=>Math.sqrt(v/n));
  return {g,peak,rms,speed,excursion,
    worstTorque:Math.max(...peak), worstSpeed:Math.max(...speed),
    rmsImbalance:Math.abs(rms[0]-rms[1])/Math.max(...rms),
    speedImbalance:Math.abs(speed[0]-speed[1])/Math.max(...speed)};
}
function analyze(g, height, stroke=50, lift=12, count=1920) {
  const a=M.analyze(g,{...path,stroke,lift},mount,-height,count);
  const {samples,...summary}=a;
  let closureError=0, jacobianError=0, minOtherJointHeight=Infinity;
  for(const s of samples.filter(s=>s.ok)) {
    const f=M.forward(g,s.alpha,s.theta,s.closureBranch);
    if(!f.ok)throw Error("Independent FK failed");
    closureError=Math.max(closureError,M.norm(M.sub(f.T,s.T)));
    const points=[s.D,s.E,s.P];
    if(Math.cos(M.rad(g.footAngle))<0)points.push(footBend(g,s));
    minOtherJointHeight=Math.min(minOtherJointHeight,...points.map(p=>p[1]+height));
    if(!s.J)continue;
    for(let j=0;j<2;j++){
      const q=[s.alpha,s.theta],qp=q.slice(),qm=q.slice(),eps=1e-6;
      qp[j]+=eps; qm[j]-=eps;
      const plus=M.forward(g,...qp,s.closureBranch),minus=M.forward(g,...qm,s.closureBranch);
      if(!plus.ok||!minus.ok)throw Error("Finite difference FK failed");
      for(let k=0;k<2;k++)jacobianError=Math.max(jacobianError,Math.abs((plus.T[k]-minus.T[k])/(2*eps)-s.J[j][k]));
    }
  }
  return {height,stroke,lift,...summary,minOtherJointHeight,closureError,jacobianError};
}
function envelope(g) {
  const points=range(60,70,1).flatMap(h=>range(-25,25,1).map(x=>[x,-h]));
  points.push(...range(40,70,.5).map(h=>[0,-h]));
  let peak=[0,0],branch,complete=true,minOtherJointHeight=Infinity;
  for(const p of points){
    const s=M.inverse(g,p);
    if(!s.ok||!s.J){complete=false;continue;}
    if(branch===undefined)branch=s.closureBranch;
    if(s.closureBranch!==branch)complete=false;
    for(const push of [-.25,0,.25])M.torques(s,mount,push*force,force).forEach((v,j)=>peak[j]=Math.max(peak[j],Math.abs(v)));
    const joints=[s.D,s.E,s.P];
    if(Math.cos(M.rad(g.footAngle))<0)joints.push(footBend(g,s));
    minOtherJointHeight=Math.min(minOtherJointHeight,...joints.map(x=>x[1]-p[1]));
  }
  return {samples:points.length,complete,peak,minOtherJointHeight};
}
function report(){
  const candidate={...R.dimensions,leg:50,carrier:30,crank:30,rod:52,pickup:40,
    footAngle:180+phi,kneeBranch:1,crankBranch:-1};
  const installed={...R.dimensions,footAngle:0,kneeBranch:-1,crankBranch:-1};
  const cases={installed,candidate,
    lowerTorque:{...candidate,carrier:26,crank:26,rod:54,pickup:36},
    shorterLeg:{...candidate,leg:45,pickup:38},
    minimumArms:{...candidate,leg:55,carrier:20,crank:20,rod:44,pickup:32}};
  return {source:R.source,sourceSha256:R.sha256,phi,path,force,
    bend:{kneeToBend:50*Math.cos(M.rad(phi)),pickupToBend:50*Math.cos(M.rad(phi))-40,toeSegment:50*Math.sin(M.rad(phi))},
    cases:Object.fromEntries(Object.entries(cases).map(([name,g])=>[name,{g,
      envelope:envelope(g),benchmarks:[65,70,75].map(h=>analyze(g,h))}])),
    widerCandidate:[65,70,75].flatMap(h=>[40,50,60,70,82].map(stroke=>analyze(candidate,h,stroke))),
    candidatePose:M.inverse(candidate,[0,-70]),
    interpretation:"External-force torque only. Equal assumed three-foot support, not measured load sharing between feet. Arm load sharing is evaluated, not guaranteed by equal lengths. Partial-path values are not valid cycle comparisons. No housing or horn collision model, motor curve, mass inertia, sole profile or whole-body stability simulation."};
}
function search(){
  const found=[];let tried=0;
  // Equal driven arms first; passive links adapted to the actual fifth link.
  for(const leg of [45,50,55])for(const arm of range(20,40,2))
    for(const pickup of range(20,44,2))for(const rod of range(20,56,2))
      for(const bend of [-phi,phi])for(const kneeBranch of [-1,1])for(const crankBranch of [-1,1]){
        if(pickup>=leg*Math.cos(M.rad(bend)))continue;
        const g={...R.dimensions,leg,carrier:arm,crank:arm,pickup,rod,
          footAngle:180+bend,kneeBranch,crankBranch};
        tried++;const a=screen(g);if(a)found.push(a);
      }
  // Keep the full feasible set, so choosing a tradeoff is auditable.
  found.sort((a,b)=>a.worstTorque-b.worstTorque);
  return {source:R.source,sourceSha256:R.sha256,
    wavegoSource:"https://github.com/waveshare/WAVEGO/blob/main/Arduino/WAVEGO/ServoCtrl.h",
    phi,force,path,heights,shaftOffset:[R.dimensions.shaftX,R.dimensions.shaftZ],
    scope:"Planar point-foot external-load calculation; no collision, motor, dynamic or whole-body qualification. Peak includes +/-25% horizontal force. RMS uses vertical support only. Rise is centred 40..70 mm. Search minima are not universal optima.",
    tried,feasible:found.length,found};
}
if(require.main===module)console.log(JSON.stringify(process.argv.includes("--report")?report():search(),null,2));
module.exports={screen,analyze,search,report,path,mount,phi,force,footBend};

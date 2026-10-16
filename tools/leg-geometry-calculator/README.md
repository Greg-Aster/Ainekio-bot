# Leg geometry calculator

Open [index.html](index.html) in a browser. It runs directly from disk, with no
server, installation, network requests or connection to the robot.

The default dimensions are the owner's installed **55 mm lower leg, 35 mm
carrier, 38 mm rod, 28 mm pickup and 20 mm crank**. Dimensions are hole-centre
distances; lower-leg length is knee to the idealised foot point. The pickup is
on the opposite side of the knee by default. Foot angle can represent a bent
lower leg.

Foot angle **0°** puts the pickup opposite the foot; **±180°** puts them on
the same side of the knee. The WAVEGO-inspired study uses **−156.716°**, a
23.284° bend relative to the same-side pickup. The schematic joins the knee,
pickup and ideal foot; it does not prescribe the printed part's outline.

`wavego-study.js` compares this topology around the fixed shafts, with both
driven arms at least 20 mm to accommodate the owner's servo horns. Run with
`--report` for dense checks of the selected 50/30/30/52/40 mm
leg/carrier/crank/rod/pickup candidate and alternatives; run without arguments
for the full bounded equal-arm search. These are research calculations, not
firmware gait settings or proof that a part clears the housing.

## Mount positions are part of the mechanism

`robot-data.js` is an explicitly dated snapshot of
`Slave/software/models/v2-12servo/geometry.json`, including its SHA-256. Both
shaft positions are calculated from the exported mechanism and shoulder
transforms. The crank shaft is approximately **12.5001 mm behind and 11.5000 mm
above** the carrier shaft. Neutral front/rear carrier positions are approximately
**(+66.6878, 69.7118)** and **(-66.7216, 69.7118) mm** in body X/Z coordinates.
Physical front legs have CAD labels RL/RR; physical rear legs have CAD labels
FL/FR. The interface uses physical names.

Changing link lengths preserves those mounts. Uncheck **Keep installed shaft
positions** to edit crank-to-carrier separation or the selected carrier's body
position. Crank separation applies to all legs; a carrier position change applies
only to the selected leg. Rechecking restores all installed shaft positions.
The chassis view shows the original shaft locations as ghost rings when changed.
The shoulder axes are reference markers: the calculator holds the shoulder
rotation at CAD neutral, and does not solve its lateral motion or torque.

## Using it

1. Keep the default mounts and select a physical leg.
2. Adjust link lengths, clearance, foot centre and stride. Play or scrub the
   cycle; inspect **On chassis** to see the mechanism relative to the body.
3. Compare servo excursion, static support torque, angular speed, and the lowest
   planted leg angle. “Reachable” means the sampled geometry closes, not that the
   servo can drive it under load.
4. **Keep this design** adds a comparison snapshot. Selecting a design name restores
   its dimensions, mounts, path and load assumptions. Comparisons last for the
   browser session; export any design you want to retain.
5. **Find largest sampled stride** scans centred strokes in 1 mm increments up to
   twice carrier-plus-leg reach, checking 120 full-cycle samples, the entered
   excursion, singularities, and assembly branch continuity. It does not optimise
   torque, speed, stability or collisions. Inspect the result with the regular
   240-sample calculation; neither is a continuous-path proof.
6. Export the current design to JSON, cycle samples to CSV, or drawing to SVG.
   JSON imports reproduce parameters. Exported files are not firmware or robot
   commands. A different source snapshot is identified on import.

## Calculation and scope

In the linkage plane, carrier shaft O is `(0,0)` and crank shaft C is the
configured offset. The driven carrier ends at knee D, driven crank at P, rod
connects P to pickup E, and the lower leg extends from D to foot T. Two circle
intersections solve D and P for each requested T. A separately implemented
forward solver closes the pickup/rod circles for given motor angles.

Shaft geometry is loaded from the repository, not freshly measured hardware.
The default point-foot representation is **not the physical Part 027 contact
hull used by firmware**, and the calculator is not a firmware gait playback.
It omits the third-axis shoulder rotation, part thickness, collisions, boots,
rocking contact and deformation. Body clearance is relative to the bottom of
the exported chassis hull at neutral orientation. The assumed COM marker is not
a support polygon, mass distribution measurement or balance prediction.

Torque follows virtual work: `tau = -J^T F`, using the analytic closed-chain
Jacobian and external foot force. The upward force per supporting leg is
`mass * gravity / supporting_leg_count`; horizontal force is entered per leg.
The default is the owner's 566 g robot and three equal-load supports. Link
weight, inertia, acceleration, friction and motor losses are excluded. No MG90
torque or speed rating is assumed. RMS torque percentages are relative demand
magnitudes, not motor power shares. Excursion does not establish horn indexing,
calibrated pulse bounds or actual usable servo travel. Missing cycle samples are
reported rather than silently shrinking the requested stride.

The planted path has constant rearward speed relative to the body. The swing
polynomial matches its endpoint velocity and uses a smooth vertical lift.
Cycle duration controls the reported joint-speed demand; it does not estimate
actual ground speed or traction. Changing a physical mount can change all of
these results despite unchanged link-length ratios.

## Verification

Run from the repository root:

```sh
node tools/leg-geometry-calculator/mechanics.test.js
```

Nine tests cover closure and independent forward/inverse parity over varied
lengths/foot angles/shaft offsets; central-difference Jacobians and virtual work;
exported mount reconstruction; mount-location sensitivity; coordinate invariance;
path continuity and speed scaling; unreachable-path reporting and load scaling;
and the stated sampled-stride search. Browser checks cover editing, fixed mounts,
animation, chassis view, comparison snapshots and responsive layout. These are
numerical/software checks, not physical robot qualification.

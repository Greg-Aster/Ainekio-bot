# Dead — twelve-servo motion source

> Geometry snapshot note (2026-09-17): The 2026-09-17 final comparison found later front-panel, camera and display changes relative to the preserved integration baseline; those current edits are retained. No leg meshes appear in the changed/missing list, and earlier actuator/body curves match all 19 recorded baseline frames. All twelve new actuator/body tracks also match every exported source sample (see `current-curve-source-review.json`). Body-contact points and complete-body floor results below describe the earlier measured geometry snapshot and have not been requalified for the later front changes. Completed preview frames span the saved model revisions; visor work remains deferred.

## Eight-servo reference

All four lower joints reach 90 degrees and remain held. Original dead face boomerangs; V1 has no automatic recovery.

The exact source entry is `reference-v1-dead.json`. `reference-v1-joints.json` preserves electrical joint IDs; `reference-adaptation.json` resolves sparse target frames. Faces are original seed bitmaps. V1 electrical angles and sequential frame timing are reference evidence, not a twelve-servo calibration.

## Twelve-servo adaptation

V1 moves all four lower joints to 90 degrees and holds with the boomerang dead face. V2 lowers onto the measured complete-body rear-cover/visor support plane, flattens four legs outward using mirrored shoulders and coordinated lower joints, and remains still. Appended stand recovery is demonstration-only.

Total source duration is **12.30s**, with 1477 samples at120Hz.

## Held command versus playlist recovery

The dead pose is reached at4.4s and held through **7.4s** (`semantic_end_s`). Command execution ends there and holds the geometric angles until a later explicit command. The source then includes `demonstration_recovery_*` phases for the Blender playlist, returning to standing by11.8s; total preview12.3s. The original dead face boomerangs through the held pose and recovery; the stand face returns at11.8s.

The body rests at33.537235mm and pitchY−5.713782degrees on the measured rear bottom-cover edge and front visor. The exported support polygon comes from current saved geometry, and current complete-body sampled floor clearance passes. **Physical visor/contact load capacity is unverified.** This pose does not imply approval to load the visor on hardware. All geometry remains unchanged.

## Coordinates and mechanics

CAD ordering is FL rear-left, FR rear-right, RL front-left, RR front-right. Every triplet is h/Part002 shoulder, alpha/Part006 carrier, theta/Part005 input crank. Angles are geometric **radians**, positions **millimeters**, and times **seconds**; body axes Xforward, Yleft, Zup. Four-bar passive beta comes from fixed-branch closure. These are not electrical servo targets.

Measured sole rolling during approach/recovery. During flattening and hold, the measured rear-cover edge and front visor support the body; visor contact load capacity is unverified.

## Numerical review

- Minimum assumed COM support margin: 22.755339mm.
- Minimum sole height: -0.000000005mm.
- Minimum body sample clearance: 0.000000mm.
- Maximum coupler closure error: 1.42e-14mm.
- Maximum adjacent actuator change: 1.018704degrees.
- Peak actuator speed: 122.244degrees/s.
- Peak sampled acceleration: 376.107degrees/s².
- Final standing angle error: 0.000000000degrees.

COM is explicitly assumed at the body datum. Battery/Q6A mass and position remain configurable. Joint envelopes are research ranges, not calibrated stops. Inter-part collisions, electrical timing, servo load, friction, and physical stability remain unverified. Runtime timing and PWM staggering belong to the shared execution contract.

## Reproduce

Run inside this command folder with Blender's Python (NumPy required):

```sh
/home/greggles/blender-5.0.0-linux-x64/5.0/python/bin/python3.11 generate_dead.py
```

This writes `source.json`, `config.json`, and `validation.json`. Dependencies are copied locally: `motion_common.py`, `plan_crawl.py`, `gait_kinematics.py`, measured geometry/sole/body files, and base COM configuration. Dead additionally uses `current-body-samples.npz` and `body-rest-plane.json` from the current saved scene. `gait_start_frame` is assigned by the parent playlist exporter. The root agent owns Blender append, preview, execution export, and saved-scene review.

## Integrated Blender and handoff

Saved library: `Ainekio-Motion-Library.blend`, frames **4499–4794** at 24 fps. [Preview](preview.mp4). The library selector is `select_motion("dead", play=True)`.

`source.csv`, `schema.json`, `manifest.json` and `execution-contract.json` are the independent firmware research handoff. Positions are mm and actuator angles are geometric radians; electrical calibration is not supplied. Run `python3 export_command.py` after regeneration. `timing.py` shares one clock across all joints and excludes optional demonstration recovery by default; add `--include-demo-recovery` to inspect that path. Operating timing remains unset.

The reviewed source and saved poses are reported in `source-review.json`, `interpolation-validation.json`, and `blender-validation.json`. Visor and inter-part collision checks are deferred at the owner’s request.

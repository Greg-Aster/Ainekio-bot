# Freaky — twelve-servo motion source

> Geometry snapshot note (2026-09-17): The 2026-09-17 final comparison found later front-panel, camera and display changes relative to the preserved integration baseline; those current edits are retained. No leg meshes appear in the changed/missing list, and earlier actuator/body curves match all 19 recorded baseline frames. All twelve new actuator/body tracks also match every exported source sample (see `current-curve-source-review.json`). Body-contact points and complete-body floor results below describe the earlier measured geometry snapshot and have not been requalified for the later front changes. Completed preview frames span the saved model revisions; visor work remains deferred.

## Eight-servo reference

Asymmetric braced setup with three short right-front lower-joint flicks. V1 R3 joint ID 5 cycles between 0 and 25 degrees after an asymmetric R4/R3 setup.

The exact source entry is `reference-v1-freaky.json`. `reference-v1-joints.json` preserves electrical joint IDs; `reference-adaptation.json` resolves the sparse target frames. Faces are the original seed bitmaps.

## Twelve-servo adaptation

V1 spreads its upper joints, partly folds right rear R4, and repeats three short right-front R3 flicks. V2 lowers into a three-foot braced posture, raises the right-front shoulder, and flicks right-front Part005 with coupled Part006. Three supporting soles are retained; no invented belly contact.

The animation lasts **9.70 seconds**, with 1165 samples at120Hz. Return to standing after the gesture; hold the final pose.

CAD ordering is FL rear-left, FR rear-right, RL front-left, RR front-right. Every triplet is h/Part002 shoulder, alpha/Part006 carrier, theta/Part005 input crank. Angles are geometric **radians**, positions **millimeters**, and times **seconds**; body axes are Xforward, Yleft, Zup. Four-bar passive beta comes from fixed-branch closure. These are not electrical servo angles.

## Contact and numerical review

Measured convex sole rolling: fixed material vertex between feature transfers. Belly support is explicit when selected; no friction or dynamics simulation.

- Minimum assumed COM support margin: 17.557420mm.
- Minimum evaluated sole height: -0.000000009mm.
- Minimum body sample clearance: 10.573752mm.
- Maximum coupler closure error: 1.42e-14mm.
- Maximum adjacent actuator change: 1.344947degrees.
- Peak actuator speed: 161.394degrees/s.
- Peak sampled acceleration: 620.466degrees/s².
- Final standing angle error: 0.000000000degrees.

COM is an explicitly assumed body datum. Battery/Q6A mass and position remain configurable in `config.json`. Joint envelopes are research ranges, not calibrated stops. Collisions, electrical timing, servo load, friction, and physical stability are unverified. Source speed is for choreography; runtime timing and PWM staggering belong to the shared execution contract.

## Reproduce

Run from this command folder with Blender's Python (NumPy required):

```sh
/home/greggles/blender-5.0.0-linux-x64/5.0/python/bin/python3.11 generate_freaky.py
```

This writes `source.json`, `config.json`, and `validation.json`. The generator is self-contained with `motion_common.py`, `plan_crawl.py`, `gait_kinematics.py`, the measured geometry/sole/body files, and base COM configuration. `gait_start_frame` is assigned by the parent playlist exporter. Blender append, preview, final export contract, and saved-scene review are handled by the batch generator.

## Integrated Blender and handoff

Saved library: `Ainekio-Motion-Library.blend`, frames **3457–3690** at 24 fps. [Preview](preview.mp4). The library selector is `select_motion("freaky", play=True)`.

`source.csv`, `schema.json`, `manifest.json` and `execution-contract.json` are the independent firmware research handoff. Positions are mm and actuator angles are geometric radians; electrical calibration is not supplied. Run `python3 export_command.py` after regeneration. `timing.py` shares one clock across all joints and excludes optional demonstration recovery by default; add `--include-demo-recovery` to inspect that path. Operating timing remains unset.

The reviewed source and saved poses are reported in `source-review.json`, `interpolation-validation.json`, and `blender-validation.json`. Visor and inter-part collision checks are deferred at the owner’s request.

# Twelve-servo motion library — 2026-09-16

Twelve adaptations of the existing eight-servo commands, appended after Bow in `Ainekio-Motion-Library.blend`. Earlier animations and the current live model are retained; later front/display revisions are recorded in the preservation report. Each command has its own original V1 reference, reproducible generator, configuration, geometric source, execution contract and preview.

## Playback

Open the saved library. The new sequence occupies frames **3109–6865** at 24 fps. Use timeline markers or run `BATCH select_motion.py` in Blender’s Text Editor, then call `select_motion("cute", play=True)` in the Python console. `strech` is accepted by this local selector as an alias for the canonical `stretch` command.

`select_motion("dead", play=True)` stops in Dead. Add `include_demo_recovery=True` to show its separately labelled return to standing. The complete playlist includes that recovery so subsequent commands start from the expected standing pose.

| Command | Demo duration | Blender frames | Source and review |
| --- | ---: | --- | --- |
| CUTE | 13.5 s | 3109–3433 | [cute](commands/cute/README.md) |
| FREAKY | 9.7 s | 3457–3690 | [freaky](commands/freaky/README.md) |
| WORM | 12.5 s | 3714–4014 | [worm](commands/worm/README.md) |
| SHAKE | 7 s | 4038–4206 | [shake](commands/shake/README.md) |
| SHRUG | 10.2 s | 4230–4475 | [shrug](commands/shrug/README.md) |
| DEAD | 12.3 s | 4499–4794 | [dead](commands/dead/README.md) |
| CRAB | 30.6 s | 4818–5552 | [crab](commands/crab/README.md) |
| CELEBRATE | 12.5 s | 5576–5876 | [celebrate](commands/celebrate/README.md) |
| STRETCH | 6.7 s | 5900–6061 | [stretch](commands/stretch/README.md) |
| SURPRISED | 11.95 s | 6085–6372 | [surprised](commands/surprised/README.md) |
| SAD | 8.8 s | 6396–6607 | [sad](commands/sad/README.md) |
| CURIOUS | 9.75 s | 6631–6865 | [curious](commands/curious/README.md) |

## Coordinates and execution

Source samples are **120 Hz**, positions **millimeters**, signed actuator angles **geometric radians**, time **seconds** plus CSV integer microseconds. World X is physical forward, Y left, Z up. Quaternion order is wxyz. Each triplet is shoulder h/Part002, carrier alpha/Part006, crank theta/Part005. CAD order FL, FR, RL, RR maps to physical rear-left, rear-right, front-left, front-right. Passive linkage beta follows measured four-bar closure; no servo electrical angles are inferred from these data.

All twelve joints, body, feet and face cues use one shared trajectory clock. The exported policy retains separate PWM phase and initial engagement scheduling; independent per-joint motion delays would change the coordinated contact geometry. Operating speed profiles remain unset pending loaded calibration. Demonstration and adjustable research profiles are included.

## Review and limits

The 2026-09-17 final comparison found later front-panel, camera and display changes relative to the preserved integration baseline; those current edits are retained. No leg meshes appear in the changed/missing list, and earlier actuator/body curves match all 19 recorded baseline frames. All twelve new actuator/body tracks also match every exported source sample (see `current-curve-source-review.json`). Body-contact points and complete-body floor results below describe the earlier measured geometry snapshot and have not been requalified for the later front changes. Completed preview frames span the saved model revisions; visor work remains deferred.

Three agents built four commands each from the exact V1 assets; the primary agent independently reviewed the resulting source and Blender mechanism. Every full source is checked for FK foot/sole agreement, fixed link length, passive branch consistency, finite and continuous bounded angles, and endpoint continuity. Exported interpolation uses monotone cubic Hermite curves; all intervals are sampled at quarters and extrema demands are calculated analytically. Actual saved Blender poses are also evaluated between source keys.

`source-review.json`, `interpolation-validation.json` and `blender-validation.json` accompany each command. `preservation-validation.json` records earlier model meshes and animation comparisons. Visor/inter-part collisions are **unverified and deferred at the owner’s request**. The lying gestures use their already completed pitched resting poses; physical loading on the cover/visor contacts remains unverified. COM is assumed and support margins do not prove dynamic stability.

Crab is provisional: its lowest assumed support margin is approximately **1.01 mm**, and its final grounded contact settle moves the feet approximately **1.58 mm**. Contact friction and hardware execution must be resolved before deployment. Contact assumptions for every other gesture are stated in its command README and source.

## Reproduce and hand off

Each command folder contains `generate_<command>.py` or `generator.py`, local dependencies, `config.json`, `source.json`, `source.csv`, `schema.json`, `manifest.json`, `execution-contract.json`, the shared execution policy, original references and face bitmaps. Run its generator using Python 3 with NumPy, then `python3 export_command.py`. Generator configuration retains the assigned Blender frame slot. Changing duration requires rerunning the library preparation step to avoid overlap.

To rebuild the combined Blender sequence, run `prepare_library.py` using Python with NumPy, open `Before-Motion-Batch.blend` or the preserved pre-append copy, then execute `apply_library.py` from Blender. The script appends all commands, preserves earlier keys, and saves `Ainekio-Motion-Library.blend`. `cautious_previews.py` runs bounded sequential preview workers; follow `resource-policy.md` for the memory-limited launch. Do not start parallel background renders.

The per-command ZIPs are portable firmware research handoffs. The combined ZIP includes all twelve plus the library scripts. Large `.blend` files stay in the workspace. No firmware, gateway, Body Control implementation or V1 motion assets were changed.

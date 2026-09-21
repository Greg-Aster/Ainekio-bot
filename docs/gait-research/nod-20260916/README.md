# Nod — preserved twelve-servo sequence

At the owner's request, the original shallow Pushup has been retained as **Nod**.
Its body, all twelve joint tracks, passive linkage angles, sole contacts and
sample times are unchanged. `retention-validation.json` verifies exact equality
for all 1741 samples against the original Pushup source.

- Saved Blender: `/home/greggles/blender-5.0.0-linux-x64/robot-nod-20260916/Ainekio-Nod.blend`
- Original live backup: `Before-Nod.blend` in the same directory.
- Frames **2137–2485**; duration **14.5 seconds**; five nodding cycles.
- Preview: `nod-preview.mp4`; source: `source.json` and `source.csv` at 120 Hz.
- All four soles remain grounded. Front-body travel is **36.833 mm**.

This is now a distinct semantic `nod` reference. `reference-v1-nod.json` records
the older eight-servo Nod for context; this version follows the user's approved
reclassification of the previous motion. Its prior face appearance is retained
under the package's Nod bitmap name. Existing V1 face assets are not replaced.
The original V1 Pushup provenance is kept as `retained-sequence-v1-provenance.json`.

## Firmware handoff

Use `execution-contract.json` with the shared `execution-policy.json`. The wire
intent is `{"t":"intent","name":"emote","asset":"nod"}`. Source positions are
mm, angles signed geometric radians, time seconds; CSV includes microseconds.
CAD FL, FR, RL, RR map to rear-left, rear-right, front-left, front-right. Each
triplet is h/Part002, alpha/Part006, theta/Part005. Body axes: X forward, Y left,
Z up; quaternion wxyz. `schema.json` and `manifest.json` document exact ordering
and bind the source files by hash. Calibration and operating timing are pending.

One trajectory clock coordinates all joints, body, feet and face cues. Electrical
pulse staggering and initial engagement follow the shared policy, independently
of geometric sample time. Do not independently delay motion tracks.

## Retained validation

The unchanged motion retains its earlier evaluated leg results: 16 sampled
Blender poses, maximum closure error 0.0000342 mm and foot prediction error
0.0000312 mm. Minimum assumed-COM support margin is **39.115 mm**. Peak
interpolated demand is **106.565 degrees/s** and **538.262 degrees/s squared**.
The complete-model floor check remains flagged by the pre-existing camera
reference at -2.2 mm; leg soles pass separately. Full collisions, measured COM,
mechanical/electrical travel and loaded hardware capability remain unverified.
The retained validation reports are historical checks of the identical motion;
the source equality check establishes that renaming it did not change the tracks.

## Reproduce

With Python 3 and NumPy, from this package directory:

```bash
python3 generate_nod.py
python3 export_nod.py
```

After opening `Before-Nod.blend`, run in Blender's Python console:

```python
from pathlib import Path
p = Path('/home/greggles/blender-5.0.0-linux-x64/robot-nod-20260916/apply_nod.py')
exec(compile(p.read_text(), str(p), 'exec'), {'__file__': str(p), 'PLAY': True})
```

The portable ZIP includes scripts, geometry, source, preview and timing contract.
Large Blender files remain in the workspace. No firmware or V1 assets changed.

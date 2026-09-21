# Sit · bored — twelve-servo motion source

The robot folds its rear legs close to their current geometric travel limit and extends its front legs to hold the body upright. It remains sitting until another command. This recreates the existing Body Control **Sit · bored** behavior using the corrected twelve-servo mechanism.

## Command contract

```json
{"t":"intent","name":"sit"}
```

This is the existing `sit` intent, paired with the existing `bored` face cue. It is not an `emote` named `sit_bored`, and does not introduce another command name.

- **0–3 seconds:** smooth descent and front extension.
- **3–5 seconds:** held seated pose, with zero final joint velocity.
- **After completion:** continue holding the recorded sitting angles. No automatic return to standing and no reset to zero.
- **Face:** unchanged owner-authored `bored` bitmaps, 128 × 64, 2 fps, boomerang mode, starting at command time zero. The Blender display uses a separate overlay; the original screen/model mesh is preserved.

The three-second movement time is an adjustable research setting. V1's electrical angles and 650 ms descent were not reused as V2 joint geometry or measured actuator timing.

## Pose and coordinates

| Quantity | Recorded target |
| --- | ---: |
| Body datum height | 63.415 mm |
| Body backward shift | 8 mm |
| Body nose-up pitch | 27.5° |
| Rear carrier / Part006 | +66.767° geometric |
| Front carrier / Part006 | +6.383° geometric |
| Front crank / Part005 | +55.818° geometric |
| Lowest chassis point | Approximately 2 mm above the floor |

The rear-carrier bound in the current research configuration is +67.4°. A 28° nose-up candidate exceeded it and was rejected; the selected 27.5° pose stays within the configured bounds. These are provisional geometric limits, not calibrated electrical servo limits.

All four soles remain supported. The shoulder angles hold geometric zero because this motion changes body pitch and front/rear folding without changing the lateral stance. All twelve angles are still recorded at every timestamp.

Export order is CAD **FL, FR, RL, RR**, with **h002, alpha006, theta005** within each leg. FL/FR are the physical rear legs; RL/RR are the physical front legs. Positions are millimeters, actuator angles are signed geometric radians, time is seconds, and quaternions are w,x,y,z. World axes are X forward, Y left, Z up. Negative rotation about body Y raises the front. Part005 re-clocking is already included in geometric zero.

## Files for the firmware / Body Control agent

- `source.json`: complete 601-sample, 120 Hz body, foot, contact and twelve-joint trajectory.
- `source.csv` / `schema.json`: flat timestamps, explicit units and joint/leg ordering.
- `config.json`: posture, timing, bounds and assumed COM configuration.
- `manifest.json`: existing wire command, face cue, final pose, completion behavior and provenance hashes.
- `robot-gait-parameters.json` / `sole-hulls.npz`: measured linkage and sole geometry used by the solver.
- `body-samples.npz` / `body-and-face-reference.json`: measured fixed-body vertices used for floor clearance and display alignment.
- `generate_sit.py`, `gait_kinematics.py`, `plan_crawl.py`: reproducible kinematic generator and closure solver.
- `sample_reference.py`: portable read-only interpolation reference; outputs signed CAD centidegrees and derivatives.
- `faces/bored/0.bin`, `1.bin`, `reference-bored-face.json`: exact existing bored-face assets and playback metadata.
- `reference-v1-sit.json`: V1 behavior reference only; its eight electrical servo targets are not V2 actuator values.
- `validation.json`, `blender-validation.json`, `interpolation-validation.json`, `preservation.json`: measured results and saved-artifact preservation evidence.
- `Ainekio-Sit-Bored.blend`: full working file, with the command at frames 529–649 after the original tests.
- `sit-bored-preview.mp4`: five-second motion preview.

## Integration notes

`Master/gateway/dashboard/static/dashboard.html` already sends `data-intent="sit"`, and `Master/gateway/environment_adapter/translation.py` already maps `sit` to the native intent. Preserve that semantic command. Import this source under the twelve-servo model in `Slave/software/models/v2-12servo/`; keep the old V1 motion independent.

Use the robot's local monotonic clock and rational 120 Hz indexing (`elapsed_us * 120 / 1_000_000`). Match the provided monotone cubic Hermite interpolation: harmonic adjacent same-sign secants, zero tangents at sign changes and endpoints. The final sample is a held terminal posture. `sample_reference.py` shows this behavior, including timestamps after completion.

Entry currently assumes the recorded neutral standing pose. Transitions from walking, turning, an interrupted command, or an arbitrary current pose require the firmware agent's calibrated entry/stop handling. A completion receipt should describe the real executor's result, not merely successful source sampling.

Electrical channels, servo sign/center/pulse mappings, loaded speed/torque/travel limits and physical stop behavior remain unassigned or unqualified. Keep this source in geometric coordinates until calibration is available. The face cue belongs to the existing display asset path.

## Validation and assumptions

Cover edits present during this session were retained. Four cover meshes differ from the initial backup; the other 696 mapped model/test objects match the preservation check. The sitting generator does not edit those covers. `cover-comparison.json` records the differences.

The evaluated Blender mechanism stays connected and its foot positions agree with the independent solver within 0.00005 mm at 18 sampled extrema/intermediate poses, including poses between source keys. The complete visible model clears the floor apart from approximately 0.00007 mm numerical residue at the sole; the chassis minimum is 2.000006 mm.

The assumed-COM support margin remains positive, with a minimum of **35.586 mm**. This uses an explicitly assumed COM at the body datum; component masses and loaded physical balance are unverified. Rounded-sole rolling uses a fixed material contact vertex with supporting-feature transfers, whose small normal corrections are recorded.

Peak interpolated joint speed is **39.905°/s**, and peak interpolated acceleration is **50.669°/s²**. These are requested kinematic demands. Position and velocity are continuous; continuous acceleration, servo capability and dynamics are not established. Full part-to-part collision checking remains unverified, including the existing intended mount interference.

## Reproduce

With Python and NumPy available, from this directory:

```bash
python3 generate_sit.py
python3 export_sit.py
python3 sample_reference.py 3000
```

Optional generator arguments are `--height`, `--pitch` and `--x`, in millimeters/degrees as indicated by the configuration. Infeasible angles, linkage branches and body-floor clearance are rejected; actuators are not independently clamped.

In Blender's Python console, with the preserved current rig open:

```python
from pathlib import Path
p = Path('/home/greggles/blender-5.0.0-linux-x64/robot-sit-bored-20260915/apply_sit.py')
exec(compile(p.read_text(), str(p), 'exec'), {'__file__': str(p)})
```

The live demonstration plays once and stops on the held sit. The saved curves remain constant beyond their final keys. Manually looping Blender's timeline replays the clip; that timeline rewind is not a stand command.

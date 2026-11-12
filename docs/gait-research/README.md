# Preserved V2 Task-Space Choreography Inputs

This directory retains **only** the 92 SHA-256-pinned 120 Hz task-space choreography JSON files (`source.json`, `manifest.json`, `schema.json`, and gesture `execution-contract.json`) consumed by [`Slave/software/models/v2-12servo/tools/retarget_clips.py`](../../Slave/software/models/v2-12servo/tools/retarget_clips.py) via [`Slave/software/models/v2-12servo/motions/retargeting.json`](../../Slave/software/models/v2-12servo/motions/retargeting.json).

- **Role**: Supplies authored world-space foot/body choreography, phase timing, and semantic completion metadata when rebuilding V2 finite postures, gestures, and historical turns against current linkage geometry.
- **Not runtime firmware data**: Current V2 joint trajectories, calibration fits, and compiled firmware clip tables live under [`Slave/software/models/v2-12servo/motions/`](../../Slave/software/models/v2-12servo/motions/).
- **Cleaned artifacts**: Redundant `.zip` bundles, `.mp4` previews, `.png` contact sheets, `.npz`/`.bin` intermediates, and one-off sweep directories were removed; do not commit render bundles or binary archives here.

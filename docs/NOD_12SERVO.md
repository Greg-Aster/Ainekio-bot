# Nod — preserved shallow motion

The owner reclassified the original shallow Pushup as **Nod**. All body, joint,
contact and timing tracks are unchanged: five cycles over **14.5 seconds**.

- [Description and source-retention proof](gait-research/nod-20260916/README.md)
- [Preview](gait-research/nod-20260916/nod-preview.mp4)
- [Independent source handoff ZIP](gait-research/nod-20260916/ainekio-nod-12servo-20260916.zip)
- [Source JSON](gait-research/nod-20260916/source.json)
- [Execution contract](gait-research/nod-20260916/execution-contract.json)

Saved Blender:
`/home/greggles/blender-5.0.0-linux-x64/robot-nod-20260916/Ainekio-Nod.blend`.
Frames **2137–2485** retain the original movement; the new deep Pushup follows
at 2509 in its combined scene. The handoff uses semantic command `nod`, signed
geometric joint angles and the same shared execution policy. Hardware
calibration and loaded validation remain pending.

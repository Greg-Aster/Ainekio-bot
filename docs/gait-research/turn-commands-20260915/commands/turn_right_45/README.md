# turn right 45

**45 degrees right; 19 seconds total.**
This is a separate twelve-servo geometric source for firmware and Body Control integration.

- Semantic command: `turn_right_45`; envelope `{"t":"intent","name":"emote","asset":"turn_right_45"}`.
- 120 Hz, 2281 rows. Entry 0–5 s, turning 5–13 s, then six seconds of settling.
- 2 four-leg cycles; 22.5 degrees per cycle. A cycle alternates four 0.5 s supported body shifts and four 0.5 s single-leg swings.
- Body height 78 mm, actual sole lift 5 mm. The center returns to its initial XY position.
- CAD leg step order: FL, RL, FR, RR. Export column order: FL, FR, RL, RR; each h002, alpha006, theta005.
- FL/FR are physical rear left/right; RL/RR are physical front left/right.
- Angle signs and zero are geometric. No pulse widths, electrical centers or PCA9685 channels are assigned.

## Files

- `source.json`: complete body pose, twelve actuators, passive linkage angle, foot targets, sole contacts, contact states, COM assumption and phases.
- `source.csv` / `schema.json`: flat timestamped export and explicit units/order.
- `config.json`: independently adjustable recipe; shared geometry/solver are two directories above.
- `manifest.json`: command mapping, duration, final pose and provenance hashes.
- `validation.json`: complete sampled ranges and speed/acceleration estimates.
- `blender-validation.json`: evaluated mechanism and sole comparison, including poses between keys.
- `Ainekio-Turn-Right-45.blend`: full animation after the preserved range tests, beginning at frame 529.

## Qualification

The assumed-COM minimum support margin is **-2.591 mm**; a negative value means the projection leaves the support triangle. Static balance is therefore unqualified.
Peak sampled actuator speed is 159.489 degrees/s. These are kinematic demands, not demonstrated servo capability.
Foot rolling retains a world-fixed sole vertex until the supporting feature changes; point-contact yaw is permitted. Friction, yaw scrub, full collision clearance, measured mass, loaded servo limits and dynamics remain unverified.
The final recorded standing pose differs slightly from CAD zero. Integrators must handle current-pose entry, hold/stop and command-to-command transitions; do not concatenate sources with a jump.

The existing Body Control semantic name can be retained; select this source only for the twelve-servo model.

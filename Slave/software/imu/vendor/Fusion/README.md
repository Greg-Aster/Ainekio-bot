# Fusion dependency provenance

- Upstream: https://github.com/xioTechnologies/Fusion
- Pinned commit: `a8d7224f36a0ec82345ef49a3db50e65f8d3bab8`
- Retrieved: 2026-09-29
- License: MIT, preserved verbatim in `LICENSE.md`.

`Fusion/FusionAhrs.c`, `FusionAhrs.h`, `FusionMath.h`, `FusionInline.h`,
`FusionConvention.h` and `FusionConfig.h` are unmodified upstream files from
that commit. Only the AHRS implementation and its required headers are included.
No network download occurs during a build.

The build defines the upstream-supported `FUSION_USE_NORMAL_SQRT` option for
standard floating-point square roots on host and P4. Ainekio's wrapper handles
units, calibration, mounting, timestamps, freshness and restart policy. It uses
Fusion's public API for attitude updates and initialization; vendor code is not
patched. The library's internal state type is exposed for fixed caller-owned
storage, but consumers must use Ainekio's sample/observation functions.

An upgrade must review the API and run estimator/replay tests and the P4 build.
Changing this revision does not qualify the new filter on physical hardware.

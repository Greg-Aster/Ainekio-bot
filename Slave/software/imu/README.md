# Portable IMU estimation

This component owns timestamped six-axis samples and attitude estimation. The
same C source builds on the workstation and as an ESP-IDF component for P4.
It has no hardware driver, task, transport, dynamic allocation or motion output.
P4 includes it in the build, but no firmware task calls it yet: live sampling,
wire telemetry and feedback control remain subsequent integration work.

## Data contract

`include/ainekio/imu.h` is the interface. One acquisition owner calls
`ainekio_imu_update` once per new sample. Consumers call `ainekio_imu_observe`
without advancing filter state. The eventual P4 owner must synchronize copies
across tasks and associate transmitted observations with the active boot/session.

- Input time is acquisition time in monotonic microseconds, in one session.
  Do not substitute host receipt time or the gait's rate-limited phase clock.
- Input acceleration is specific force in m/s², including gravity at rest;
  angular velocity is rad/s. Both use the sensor's axes.
- Calibration subtracts per-axis sensor biases and applies accelerometer scale,
  then rotates both vectors into body axes: x forward, y left, z up.
- `sensor_to_body` must be an orthonormal, right-handed rotation matrix.
  This boundary does not change the existing motion model's units or geometry.
- Output quaternion order is w,x,y,z and rotates body vectors into a local z-up
  world. Heading is arbitrary at startup and drifts without an external reference.
- Output acceleration still includes gravity. There is no position, velocity,
  joint-position or contact estimate.
- Available, fresh, startup and recovery flags describe filter state. They do
  not prove calibration, hardware readiness or suitability for enabling movement.

The default configuration selects 208 Hz, 20 ms gap/staleness thresholds, ±2000
degrees/s and ±16 g input ranges, and identity mounting/zero biases. These are
software starting values, not programmed sensor registers or a mounting
calibration. Actual acquisition settings must match the configured ranges/rate.
Bias and scale calibration are supplied by the caller; automatic bias learning
is not enabled. Fusion's startup/recovery counters use the nominal sample rate;
measured intervals govern gyro integration. Use approximately regular samples.

The first sample establishes time and, if acceleration is nonzero, inclination;
it invents no gyro interval. Inclination initialization supports inverted poses.
Convergence remains marked as startup. There is no reliable gravity direction
during arbitrary linear acceleration: initial calibration/convergence should be
checked at rest. Vanishing acceleration cannot complete startup.

Duplicate, backward, non-finite or out-of-range inputs do not refresh the last
observation. A long gap restarts convergence without integrating across missing
time. A new sensor clock/session requires explicit reinitialization. Reading an
old estimate retains its original timestamp and marks it stale. Expired or
recovering estimates must not silently become fresh control inputs.

## Build and verify

From the repository root:

```sh
cmake -S Slave/software/imu -B /tmp/ainekio-imu-tests -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/ainekio-imu-tests -j4
ctest --test-dir /tmp/ainekio-imu-tests --output-on-failure
```

The P4 native test project also includes this component. Seven analytical
scenarios cover configuration/mount validation, calibrated tilt, rotation with
sample jitter, invalid/stale input, gap/session reset, acceleration/gyro recovery
flags, and inverted startup/near-zero acceleration. These are algorithm and
contract checks, not physical sensor measurements or a P4 execution-time bound.

Validation on 2026-09-29: the P4 native suite passed 31 tests and skipped three
existing geometry/regeneration tests because its Python environment lacks
NumPy/SciPy. The estimator scenarios also passed AddressSanitizer and
UndefinedBehaviorSanitizer. The host reports 328 bytes of fixed estimator state;
that excludes function stack, code and any future acquisition task/buffers.

## Next hardware integration

The owner has not selected wiring. Existing P4 I2C0 uses SDA GPIO7/SCL GPIO8
for ES8311 and camera control; I2C1 uses GPIO2/3 for PCA9685, with OE on GPIO4.
The recommended IMU connection is the existing GPIO7/8 bus, consistent with
`docs/v2-12servo/RESOURCE_BUDGET.md`. Share its single bus owner, with bounded
transactions; do not instantiate another I2C0 driver or couple acquisition to
successful camera/audio startup. Bus ownership should be explicit before adding
the driver. Sensor identity/address, electrical connection, acquisition timing
and axis mapping still require device verification.

Read-only Blender inspection on 2026-09-29 found the visible
`Purple_PCB_13x18_two_holes_ESTIMATED` under `GY_LSM6DS3_TWO_HOLE_REFERENCE`.
Its current world bounds are approximately X 27.251–45.251, Y −6.500–6.500,
Z 81.534–84.301 mm. This locates the assembly; it does not establish silicon
axes. The reference metadata labels chip placement and its pin-one marker as
estimated. No mounting transform is inferred from object rotation or baked mesh
geometry, and no Blender objects were changed.

Dependency provenance and license are in `vendor/Fusion/README.md`.

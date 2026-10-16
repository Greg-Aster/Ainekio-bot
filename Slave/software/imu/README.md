# Portable IMU estimation

This component owns timestamped six-axis samples and attitude estimation. The
same C source builds on the workstation and as an ESP-IDF component for P4.
It has no hardware driver, task, transport, dynamic allocation or motion output.
P4's `ainekio_p4_media/imu.c` now owns continuous hardware acquisition and
calls this estimator. The console reads synchronized snapshots (`imu`,
`imu sample`, `imu watch`, `imu body`). P4 now loads a saved nominal mounting
rotation and measured stationary gyro bias at boot. Raw sensor snapshots remain
available alongside corrected body observations. Network telemetry and gait
feedback are not connected yet; precise mounting and accelerometer calibration
remain unmeasured.

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

## Hardware integration

On 2026-10-12 the owner confirmed that the LSM6DS3 sensor board is mounted in
the robot frame but is not connected or operational. The owner is willing to
connect it for gait feedback. Subsequent owner photos show the 3V3, VIN, GND,
SCL, SDA, CS, SA0, SCX, SDX and interrupt labels. The proposed connections are
recorded in the [gait research journal](../../../docs/v2-12servo/GAIT_RESEARCH_JOURNAL.md).
Subsequent P4 bring-up read address 0x6A / WHO_AM_I 0x69 and 207 six-axis
samples with no I2C error. Subsequent hand-tilt checks support the nominal
sensor-to-body mapping `diag(-1, -1, +1)`; precise misalignment and full sensor
calibration remain unmeasured. Application `0.8.19-p4-imu-cal` now applies this
mapping and the measured gyro bias, with persistence verified across a restart.

The owner subsequently confirmed the board wired, P4 plugged in and servos
disconnected on 2026-10-12. Existing P4 I2C0 uses SDA GPIO7/SCL GPIO8
for ES8311 and camera control; I2C1 uses GPIO2/3 for PCA9685, with OE on GPIO4.
The recommended IMU connection is the existing GPIO7/8 bus, consistent with
`docs/v2-12servo/RESOURCE_BUDGET.md`. Share its single bus owner, with bounded
transactions; do not instantiate another I2C0 driver or couple acquisition to
successful camera/audio startup. Bus ownership should be explicit before adding
the driver. Initial sensor identity/address, continuous reads and saved gyro
correction are now verified; acquisition timing under combined active media and
network load remains subsequent work.

### P4 console bring-up

Since `0.8.18-p4-imu-live`, the media owner registers LSM6DS3 at 0x6A before
creating camera/audio devices. It reads WHO_AM_I, configures 208 Hz, ±16 g and
±2000 degrees/s with block-data-update and auto-increment, and starts a separate
acquisition task after media initialization. Camera/audio readiness is not a
condition for acquisition. Only the existing shared I2C0 bus is used.

`imu` and `imu probe` display the startup identity readback and live acquisition
counters, sample age, error and timing measurements, and quaternion. Status labels
the frame `body_nominal` when saved calibration is applied, or
`sensor_unverified` with the identity/zero-bias configuration.
`imu sample` prints two seconds of snapshots; `imu watch` prints ten seconds.
Console output is decimated to at most 50 Hz while acquisition remains at nominal
208 Hz. These commands never access sensor registers or interrupt acquisition.
This replaces the finite 104 Hz reader from `0.8.17-p4-imu-probe`.

`imu sample` / `imu watch` CSV values are raw sensor axes in m/s² and rad/s;
they have no mounting transform or bias correction. `imu body` prints two seconds
of estimator body acceleration and corrected angular rate in the same units.
Acceleration includes gravity and has no fitted bias/scale correction.
`read_mid_us` is the P4's monotonic read midpoint, and `read_us`
is transaction duration, not a sensor data-ready timestamp. The task polls
data-ready flags every 2 ms; scheduling or bus contention can skip updates.
The task calls the estimator once per acquired sample. I2C errors retain the
previous acquisition timestamp, so snapshots age according to the existing
20 ms freshness contract. Snapshot reads do not advance filter state.
No motion admission or actuator output depends on this data.
See [gait journal](../../../docs/v2-12servo/GAIT_RESEARCH_JOURNAL.md) for physical
results rather than treating compilation as working hardware.

### Saved P4 calibration

`imu calibration` reads the stored matrix and sensor-axis gyro bias and reports
whether calibration is active. To save measured values:

```text
imu calibration set r00 r01 r02 r10 r11 r12 r20 r21 r22 bx by bz
```

The nine row-major values rotate sensor vectors into body coordinates; `bx by bz`
are sensor XYZ biases in **rad/s**, subtracted before rotation. The existing
estimator configuration validation checks the rotation and numeric values.
Storage uses NVS namespace `p4_imu`, blob `cal_v1` (nine rotation floats followed
by three bias floats). Saving reports the NVS result and affects the next boot;
it does not mutate the running estimator. Other robot settings are untouched.
With no saved record, acquisition uses its identity/zero-bias diagnostic setup.

On 2026-10-12, the installed unit saved `diag(-1,-1,+1)` and sensor bias
`(+0.045871328,-0.072864937,-0.058707263)` rad/s from 476 stationary snapshots.
After restart, 285 corrected snapshots averaged approximately
`(-0.002,-0.001,+0.023)` degrees/s in body axes. These are this unit's measurements,
not defaults for other sensors or temperatures. Heading remains arbitrary and
will drift without an external reference. Gait feedback is not connected.

Read-only Blender inspection on 2026-09-29 found the visible
`Purple_PCB_13x18_two_holes_ESTIMATED` under `GY_LSM6DS3_TWO_HOLE_REFERENCE`.
Its current world bounds are approximately X 27.251–45.251, Y −6.500–6.500,
Z 81.534–84.301 mm. This locates the assembly; it does not establish silicon
axes. The reference metadata labels chip placement and its pin-one marker as
estimated. No mounting transform is inferred from object rotation or baked mesh
geometry, and no Blender objects were changed.

Dependency provenance and license are in `vendor/Fusion/README.md`.

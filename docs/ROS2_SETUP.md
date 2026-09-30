# ROS 2 development environment

This records the desktop-first ROS setup and the owner's portability requirement.
ROS installation does not integrate Ainekio with ROS: the robot adapter, IMU
feedback, vision nodes, and Q6A deployment remain separate implementation work.

## Common baseline

Use ROS 2 Jazzy with an Ubuntu 24.04 (Noble) userspace. Upstream provides both
amd64 and arm64 packages and supports Jazzy through May 2029. The development
desktop is Linux Mint 22.2, whose Ubuntu base is Noble; Mint itself is not a
separate ROS Tier 1 target. Radxa publishes Noble images for the Q6A. Confirm
the board's actual installed OS before installing packages there.

- [ROS Jazzy platform support](https://www.openrobotics.org/blog/2024/5/ros-jazzy-jalisco-released)
- [Official installation instructions](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html)
- [Q6A system images](https://docs.radxa.com/en/dragon/q6a/download)

Use the same application source and interface definitions on both hosts. Install
dependencies and build separately for each architecture; do not copy desktop
binaries, Python virtual environments, or colcon build/install output to ARM64.

## Ownership and portability requirements

These are implementation requirements for the forthcoming ROS integration,
not claims that the services below are already implemented.

| Responsibility | Desktop development | Onboard deployment |
| --- | --- | --- |
| Servo output, local trajectory timing, calibration and faults | P4 firmware | P4 firmware |
| Future fast IMU stabilization | P4 firmware | P4 firmware |
| Gateway, one motion arbiter, gait supervision and perception | Desktop | Q6A |
| YOLO inference | Desktop backend | Q6A backend |
| Larger-model reasoning | Local or configured remote service | Desktop or configured remote service |

Keep control and perception logic independent of hostname, repository location,
network address, camera device path, and accelerator vendor. Supply these through
launch parameters or host configuration. Keep robot geometry/calibration separate
from host configuration: changing computers does not change the robot.

Use timestamped, documented ROS messages for observations and semantic movement
requests. Keep measured state distinct from commanded/model-predicted state.
Every host must use consistent units, coordinate frames, and message versions.
Cross-host sensor fusion also needs a defined clock relationship and measured
latency; moving nodes across machines is not timing-neutral.

Maintain one movement authority per robot. Move the gateway and local control
supervisor together when migrating to Q6A. The current gateway's `/environment`
endpoint is intentionally loopback-only; a remote LLM service should provide
reasoning responses to the local supervisor, not take over that endpoint or send
raw servo commands. Network loss to the reasoning server must not replay stale
commands or interrupt an otherwise valid, already-authorized local task. Loss of
the P4 control connection retains its existing firmware fault behavior.

Separate inference from its backend. A CPU backend provides a portable baseline;
desktop CUDA and Q6A acceleration are optional implementations of the same
input/output contract. Exported model formats such as ONNX help portability, but
vendor-compiled engines and quantized models require target-specific validation.
Neither Q6A acceleration nor equal inference performance is established by this
desktop setup. Keep model assets, recordings, logs, and credentials outside
tracked source.

## Install the tools

Enable the official ROS repository using its `ros2-apt-source` package, as
described in the upstream installation instructions. For Ubuntu derivatives,
select `UBUNTU_CODENAME` (`noble` on this desktop), not Mint's `zara` codename.
The repository package used for this setup is `1.3.0~noble` from the
[official 1.3.0 release](https://github.com/ros-infrastructure/ros-apt-source/releases/tag/1.3.0).

With that repository enabled:

```sh
sudo apt-get update
sudo apt-get install --no-remove --no-install-recommends \
  ros-jazzy-ros-base ros-jazzy-rviz2 \
  ros-jazzy-demo-nodes-cpp ros-jazzy-demo-nodes-py \
  python3-colcon-common-extensions python3-rosdep
```

This supplies ROS command-line tools, messaging, transforms, rosbag recording,
RViz, C++/Python demos, and package build/dependency tools. It avoids the broader
desktop metapackage. A headless Q6A deployment can omit RViz and demos and add the
dependencies declared by the actual application packages. No CUDA requirement
belongs in the common ROS dependency set.

Initialize rosdep once per host, then update its cache as the ordinary user:

```sh
sudo rosdep init
rosdep update --rosdistro jazzy
```

If rosdep is already initialized, retain its existing source configuration.
When later resolving application dependencies on Mint, use
`--os=ubuntu:noble` with `rosdep install`; do not edit `/etc/os-release`.

Activate ROS explicitly in each development terminal:

```sh
source /opt/ros/jazzy/setup.bash
```

Use the system-compatible Python interpreter for ROS packages. Keep unrelated
application virtual environments and machine-specific inference dependencies
separate. No global shell startup changes are required.

On this desktop, CMake initially selected an existing local Python 3.10 instead
of Noble's system Python 3.12, which could not import the apt-installed
`catkin_pkg` module. Explicitly select the system interpreter when building:

```sh
colcon build --cmake-args -DPython3_EXECUTABLE=/usr/bin/python3
```

If a previous build cached a different interpreter, add `--cmake-clean-cache`
once. The temporary validation build passed with this setting; no existing
Python installations were replaced.

## Local communication check

In both test terminals, after sourcing ROS, use:

```sh
export ROS_DOMAIN_ID=67
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
```

Domain 67 is a test setting, not a fixed robot identity. Localhost discovery
keeps this check on one machine; it is not an authentication mechanism. A later
multi-machine deployment needs deliberate discovery/network configuration.

Run the C++ publisher in one terminal:

```sh
ros2 run demo_nodes_cpp talker
```

Run the Python subscriber in the other:

```sh
ros2 run demo_nodes_py listener
```

Matching messages confirm communication between the two language runtimes.
Stop both with Ctrl+C. RViz can be started with `rviz2`; successful topic exchange
alone does not prove graphics, GPU inference, robot connectivity, or physical
motion. Do not launch the physical gateway or issue robot commands as part of
this environment check.

## Desktop validation record

Validated on 2026-09-29:

- Installed the six requested ROS/development packages and initialized rosdep;
  the Jazzy dependency index is cached under the ordinary user's `.ros` directory.
- C++ talker and Python listener exchanged nine matching messages with localhost
  discovery and domain 67. MCAP recording captured nine messages and its metadata
  was readable with `ros2 bag info`.
- A temporary `ament_cmake` C++ example built successfully with colcon and the
  explicit system-Python setting above. Source/build/install output stayed in
  `/tmp`, outside the application source tree.
- The restricted agent sandbox denied network-interface discovery, so the
  communication check was repeated successfully with host network access.
- Rosdep reported all dependencies satisfied for the temporary package, and
  `dpkg --audit` reported no incomplete package configuration.
- RViz started, initialized OpenGL 4.6, remained running for the check, and was
  closed afterward. This verifies graphics startup, not an Ainekio model display.

This establishes the desktop toolchain and local ROS communication. No Ainekio
ROS adapter, YOLO service, IMU driver, or Q6A runtime was implemented by this
setup. Firmware and the live gateway were not changed or started by this work;
no robot movement was requested.

During the package-index refresh, the pre-existing GitHub CLI repository reported
a missing signing key. The ROS and Ubuntu indexes refreshed successfully and
the ROS installation completed. No unrelated repository keys were changed.

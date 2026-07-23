# Ainekio Gateway

The gateway owns the brain side of each protocol-v1 robot WebSocket. Production
mode authenticates robot sessions, assigns epochs and command sequences, tracks
command lifecycle results, and serves the password-protected local operations
dashboard. Robot tokens, the dashboard password verifier, and the bounded audit
log live under the ignored `build/gateway/` runtime directory by default.

## Physical Robot Gateway

The physical robot and the Environment Bridge share one authenticated,
full-duplex gateway. Ainekio connects to `/robot`; MetaHuman OS connects to
`/environment`. Once established, either side of each WebSocket can send data,
so the fact that the ESP32 initiates its connection does not make communication
one-way.

On first launch, supply a strong robot token and a separate Environment Bridge
token through the environment. Do not commit either value:

```sh
export AINEKIO_ROBOT_ID='ainekio-01'
export AINEKIO_ROBOT_TOKEN='<strong generated robot token>'
export AINEKIO_ENVIRONMENT_ADAPTER_TOKEN='<strong generated environment token>'
# Optional; otherwise each launch generates and prints a fresh password.
export AINEKIO_DASHBOARD_PASSWORD='<strong local dashboard password>'
./Master/start-physical-gateway.sh
```

The launcher listens for the robot and Environment Bridge on `0.0.0.0:8790`
but keeps the dashboard on `127.0.0.1:8791`. Configure the robot with
`ws://<brain-lan-ip>:8790/robot`; a same-computer MetaHuman OS process can use
`ws://127.0.0.1:8790/environment`. Reserve the brain computer's address in the
home router or update the robot setting if DHCP changes it. Runtime tokens and
password verifiers remain under ignored `build/gateway/physical/` storage.
The physical launcher prints the active dashboard password on every start. If
`AINEKIO_DASHBOARD_PASSWORD` is unset, it generates a fresh password and replaces
the prior verifier; if it is set, it prints and installs that configured value.
Only the verifier persists. Dashboard authentication is separate from robot
WiFi setup and is never presented by the ESP32 setup portal.

The launcher stays in the foreground. Press Ctrl+C to stop it.
The physical dashboard uses the selected robot's authenticated JPEG stream as
its first panel; enable the camera in **Camera and audio** if the panel is
waiting for frames. The emulator stack keeps the visual robot simulator in that
position instead.

Run the production gateway with development credentials supplied through the
environment on first startup:

```sh
export AINEKIO_ROBOT_ID='ainekio-emulator-01'
export AINEKIO_ROBOT_TOKEN='local-development-token'
export AINEKIO_DASHBOARD_PASSWORD='local-operator-password'
PYTHONPATH=Master:Slave/software python3 -m gateway.server
```

The dashboard is then available at `http://127.0.0.1:8791/`. If its password
store does not exist, an interactive launch can generate and print a random
one-time password instead of using `AINEKIO_DASHBOARD_PASSWORD`.

The scripted gateway stub remains available for focused body-client tests:

```sh
export AINEKIO_ROBOT_TOKEN='local-development-token'
PYTHONPATH=Master:Slave/software \
  python3 -m gateway.server --stub --commands stand,walk,neutral
```

To expose the generic environment adapter, configure a dedicated adapter token:

```sh
export AINEKIO_ENVIRONMENT_ADAPTER_TOKEN='shared-environment-adapter-token'
PYTHONPATH=Master:Slave/software python3 -m gateway.server
```

The endpoint is `ws://127.0.0.1:8790/environment`. The connecting environment
agent authenticates in its first protocol message. Ainekio does not contain a
MetaHuman URL or call MetaHuman APIs directly.

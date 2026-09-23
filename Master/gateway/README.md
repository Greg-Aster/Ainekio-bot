# Ainekio Gateway

The gateway owns the brain side of each protocol-v1 robot WebSocket. Production
mode authenticates robot sessions, assigns epochs and command sequences, tracks
command lifecycle results, and serves the password-protected local operations
dashboard. Robot tokens, the dashboard password verifier, and the bounded audit
log live under the ignored `build/gateway/` runtime directory by default.

## Physical Robot Gateway

The physical robot and the Environment Bridge share one authenticated,
full-duplex gateway process. Ainekio connects to the LAN-facing `/robot` route;
MetaHuman OS connects from loopback to `/environment`. Non-loopback peers are
rejected from `/environment`, as are requests carrying Cloudflare relay
headers. Once established, either side can send data,
so the fact that the ESP32 initiates its connection does not make communication
one-way.

On first launch, supply a strong robot token and a separate Environment Bridge
token through the environment. Do not commit either value:

```sh
export AINEKIO_ROBOT_ID='ainekio-01'
export AINEKIO_ROBOT_TOKEN='<strong generated robot token>'
export AINEKIO_ENVIRONMENT_ADAPTER_TOKEN='<strong generated environment token>'
# Optional fixed password; the physical launcher otherwise creates one per start.
export AINEKIO_DASHBOARD_PASSWORD='<strong local dashboard password>'
./Master/start-physical-gateway.sh
```

The launcher listens for the robot and Environment Bridge on `0.0.0.0:8790`
but permits `/environment` only from loopback and keeps the dashboard on
`127.0.0.1:8791`. In the default local mode the
launcher advertises `_ainekio._tcp.local`, and the robot accepts only an
advertised IPv4 address on its current WiFi subnet. After authentication the
robot caches that local endpoint and tries it first on the next boot or
transport reconnect. A failed cached attempt falls back to DNS-SD, so DHCP or
network changes require no reconfiguration. A
same-computer MetaHuman OS process continues to use
`ws://127.0.0.1:8790/environment`. Runtime tokens and password verifiers remain
under ignored `build/gateway/physical/` storage.

This one-off home deployment intentionally uses authenticated `ws://` on the
owner's private WPA2 LAN. It is the smallest local path, but the LAN is part of
the trust boundary: do not use it on guest, shared, or public WiFi. Remote mode
remains explicit and requires `wss://`; it is never an automatic fallback.
On every physical-launcher start, the terminal prints the dashboard password.
If `AINEKIO_DASHBOARD_PASSWORD` is unset, the launcher creates a fresh password
for that run and replaces the prior verifier. Setting the environment variable
uses and prints that configured password instead. Only the verifier persists;
the generated plaintext is not written to the repository or runtime data.
Dashboard authentication is separate from robot WiFi setup and is never
presented by the ESP32 setup portal.

The launcher stays in the foreground. Press Ctrl+C to stop it. For normal
owner operation it can instead be supervised by the included user service.
After `.env` contains the required tokens, this is a one-time setup:

```sh
systemctl --user link "$PWD/Master/ainekio-gateway.service"
systemctl --user enable --now ainekio-gateway.service
```

After that, the gateway and its discovery advertisement start when the owner
logs in and restart after a process failure. This service file assumes the
repository remains at `~/Ainekio`.
The physical dashboard uses the selected robot's authenticated JPEG stream as
its first panel; enable the camera in **Camera and audio** if the panel is
waiting for frames. The emulator stack keeps the visual robot simulator in that
position instead. For bring-up testing, the body microphone starts enabled with
the VAD gate; the same panel can turn it off or select another supported gate
and shows the live input level. Camera streaming is local to this dashboard and
is not forwarded as a continuous image stream to MetaHuman.

The robot controller now originates one fresh still after completed physical
actions and VAD-delimited microphone utterances. The gateway receives the
firmware correlation metadata and JPEG, validates them, and forwards one
correlated Environment observation; it does not send a second automatic
snapshot command. MetaHuman can still request `captureImage` directly. These
bounded snapshots share the camera service with the dashboard but are the only
camera images admitted to the Environment observation path.

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

Completed microphone utterances and completed physical actions arrive with one
firmware-originated correlated still when the camera is ready. Future typed
safety or sensor events should opt into the same controller-owned trigger and
correlation fields. Routine status, heartbeat, individual PCM frames, and
dashboard preview traffic do not produce Environment snapshots.

## P4 assembly calibration

Body Control uses the connected body's advertised capabilities. The P4 joint
panel reads twelve saved/staged device records through `body_calibration_v2`;
it does not reuse the eight-servo angle contract. Select the joint, enable
calibration, then use a pulse target or ±5 µs adjustment. **Use commanded pulse
as home** stages the trim; **Save calibration** applies edited joint settings,
commits them and displays the controller's readback. A pulse entered for **Move
joint** is not automatically a Home setting. Saving disables outputs without rebooting; **Home
selected joint** or an explicit move resumes that joint. **Read from body** is
available without enabling calibration. Home and pulse targets use µs, and
the displayed pulse is a command, not a shaft-position sensor reading.

The pulse slider previews a calculated model angle from the controller's Home,
direction and µs/degree mapping, and sends one movement request after release.
Its view includes the owner's observed 300–2900 µs span and expands for Home,
the last commanded pulse or typed targets; this does not change saved calibration. Numeric
entry remains available across the reported PWM capacity.
The selected robot/joint, pulse target and joint-setting drafts are retained in
this browser across reconnects and reloads. **Resume calibration** requests mode
entry explicitly; restoration never replays a movement or saves settings.
Controller readback is shown separately. **Use controller values** discards the
selected joint's local draft without moving it.

Channel -1 disables a joint. Staging Home, direction or channel does not move
outputs. P4 motion uses the model angle at Home, pulse direction and µs per degree
from the same records. The P4 mapping form has no minimum or maximum pulse fields.
Manual and generated motion use the body's actual PWM timer capacity.
The owner sets Home, direction and angle scale from actual positioning behavior.
Named poses
come from the body's installed catalog; walk/crawl exposes direction, continuous
or finite cycles, speed/stride/rate and Finish when `walk_controls_v2` is present.
Calibration mode does not block semantic motion. A pulse outside the PWM timer's
capacity is rejected by the body rather than silently rescaled.
Unsupported or disconnected media controls show the body's reason;
V1 controls retain their existing wire protocol. `/api/calibration/body` requires
the dashboard session and CSRF token; Environment Bridge exposes no raw joint
calibration action. The former `/api/diagnostics/output` bench route is removed.

The P4 SD panel reads controller capacity, mount/busy state and dropped records.
**Retry mount** works with an unmounted card. **Clear logs and captures** requires
an explicit confirmation and controller readback; it does not reformat the card.
Media controls follow current capabilities reported in regular body status, so
a camera that finishes initializing after the handshake becomes available
without reconnecting. Speaker PCM is paced at 20 ms per frame with at most
100 ms of prebuffer/catch-up lead; cached utterances cannot be sent as an
unbounded burst into the controller's playback queue.

### V2 mounting references

Current P4 calibration readback separates saved per-joint mappings from recommended mounting offsets, reports `servo_profile_id` and `profile_confirmed`, and labels shaft travel unmeasured. The observed 300–2900 µs span has arithmetic midpoint 1600 µs; the selected mounting reference is 1300 µs. The panel shows the recommended model offset without overwriting restored drafts or transmitting settings automatically. Review the mapping and Save before semantic motion; after outputs are disabled, establish a known reference with Calibration Home/Move. See the [assembly guide](../../Slave/software/models/v2-12servo/SERVO_ASSEMBLY.md).

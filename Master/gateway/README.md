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

On first pairing, supply a strong robot token. Configure a separate Environment
Bridge token when using MetaHuman on this host; standalone Body Control does not
require MetaHuman. Do not commit either value:

```sh
export AINEKIO_ROBOT_ID='ainekio-01'
export AINEKIO_ROBOT_TOKEN='<strong generated robot token>'
export AINEKIO_ENVIRONMENT_ADAPTER_TOKEN='<strong generated environment token>'
# Optional first-run password; later launches reuse the saved password.
export AINEKIO_DASHBOARD_PASSWORD='<strong local dashboard password>'
./Master/start-physical-gateway.sh
```

The launcher listens for the robot and Environment Bridge on `0.0.0.0:8790`
but permits `/environment` only from loopback and keeps the dashboard on
`127.0.0.1:8791`. In the default local mode the
launcher advertises `_ainekio._tcp.local` with a host-specific service name. P4
firmware advertising `gateway_switching_v1` tries the saved addresses for its
associated Wi-Fi, then discovered protocol-v1 LAN gateways on that subnet. It
keeps an authenticated connection until that connection fails or the gateway
stops. Discoveries are bounded to eight and stay in RAM for that network
association. A
same-computer MetaHuman OS process continues to use
`ws://127.0.0.1:8790/environment`. Runtime tokens and password verifiers remain
under ignored `build/gateway/physical/` storage.

Older P4 firmware retries one configured URL and requires an update for this
switching behavior. The S3 consumer retains its single-candidate ambiguity result.
The [distributed foundation](../../docs/DISTRIBUTED_ROBOT_FOUNDATION.md) records
the remaining cross-installation work and control-grant design.

This one-off home deployment intentionally uses authenticated `ws://` on the
owner's private WPA2 LAN. It is the smallest local path, but the LAN is part of
the trust boundary: do not use it on guest, shared, or public WiFi. Remote
endpoints remain explicitly configured `wss://` addresses with certificate
verification. TLS-only Wi-Fi profiles never fall back to discovered plain WS;
configure a LAN address on that same network to opt into discovery there.
The dashboard reuses its saved operator password across launches. A first run
without `AINEKIO_DASHBOARD_PASSWORD` generates and prints a password once when
launched in an interactive terminal; an unattended first run requires that
environment variable. Later launches do not generate or print another password.
Use **Settings → Body Control password** to change it with your current password.
The environment variable seeds a missing password store only; it cannot undo a
later password change. Only the verifier persists; plaintext passwords are not
saved by the dashboard. Browser sessions last 30 days and survive server
restarts. Logging out revokes the session. A password change keeps the current
browser signed in and signs out other browsers.
Session token hashes and CSRF state are stored in the owner-only ignored runtime
file `dashboard-sessions.json` alongside `dashboard-auth.json`.
Dashboard authentication is separate from robot WiFi setup and is never
presented by the ESP32 setup portal.

**Settings → Robot Wi-Fi and pairing** reads and edits P4 settings over the
existing authenticated connection when firmware advertises `robot_settings_v1`.
Older firmware shows an update message. The operator can save four connection slots,
each with Wi-Fi credentials and a Body Control URL, remove a connection,
change the robot setup-hotspot password, and change its pairing token. Passwords
are write-only: unchecked password options preserve the saved secret; checking
an option with an empty Wi-Fi password explicitly selects an open network.
WPA2 passphrases follow the radio's 8–63 ASCII requirement (station profiles also
accept a 64-digit hexadecimal PSK); the dashboard login has no such policy.
With `gateway_switching_v1`, two slots may name the same Wi-Fi and different
computer/tunnel addresses. They share one Wi-Fi password; changing it updates
all slots for that network. Adding another address may omit the already saved
password. Duplicate network/address pairs are rejected. Older firmware is
explicitly rejected before a same-network alternate is written.

Read the robot settings before editing. Saves carry the device revision so a
stale browser cannot overwrite another editor's changes. Saving disables output
and persists settings without dropping the running connection. **Restart robot
to apply** is a separate confirmed action; normal startup can move servos to
saved Home positions. A save/restart response confirms that operation, not
successful reconnection. Secrets are omitted from readback, status and audit.

Pairing changes persist the old and new credentials on this server before the
robot receives the write. Both survive a gateway restart or ambiguous device
result. The first authenticated connection using the new token promotes it and
retires the old one. Reuse that pending token when retrying an uncertain save;
apply/reconnect before starting another rotation. Other server installations
must be given the matching token separately. The existing Generate/Revoke
controls still manage server pairing only. Startup environment tokens seed
missing identities and never overwrite a saved token.

## Using more than one computer

The robot identity belongs to the robot. Each host runs the same gateway and uses
the existing robot token and Body Control password. Transfer those credentials
once using the existing security owners; copying `.env` alone is insufficient.
On the working computer, from the repository root:

```sh
./Master/start-physical-gateway.sh --export-pairing /tmp/ainekio-pairing.json
```

Privately transfer that owner-only file to the other computer, then run:

```sh
chmod 600 /tmp/ainekio-pairing.json
./Master/start-physical-gateway.sh --import-pairing /tmp/ainekio-pairing.json
./Master/start-physical-gateway.sh --check
```

Import starts no listeners or services and is idempotent for the same credentials.
It validates both stores before writing; different existing credentials are
preserved with an explicit error. A disk failure can leave one newly imported
store; repeating that same import completes it. The bundle contains tokens and
the password verifier, including any pending token transition. It excludes
browser sessions, tasks, action receipts, logs, Python paths, MetaHuman credentials
and Cloudflare tunnel credentials. Delete the transfer file when finished.
Later password/token changes are local to each installation; copy the matching
credentials to other hosts again rather than assuming automatic synchronization.

Both hosts install their own gateway dependencies and use their own checkout's
`.venv`. Keep machine paths out of shared configuration. Each optional MetaHuman
Bridge retains its matching adapter token. The robot relay hostname remains
`/robot` only. A separate Cloudflare Access TCP hostname can connect a remote
MetaHuman desktop as described below; its credentials/configuration stay local.

- **Same LAN:** a paired gateway with local discovery enabled can be found after
  the current gateway stops. Multiple advertisements are candidates, not an
  error or permission for simultaneous controllers.
- **Different hotspots:** save their SSIDs/passwords and server addresses once.
  P4 cycles distinct networks when Wi-Fi is offline, then selects gateways on
  the associated network. Turn off the previous hotspot when switching SSIDs;
  a still-working Wi-Fi connection is retained. With `AINEKIO_HOTSPOT=1`, the
gateway stops its managed hotspot on shutdown.
- **Cloudflare/remote:** save the `wss://.../robot` endpoint on the relevant Wi-Fi.
  It uses the same pairing and command/result contract with verified TLS.

Start Body Control on the desired host and stop it on the current host using
`./Master/stop-physical-gateway.sh` (or Ctrl+C for a foreground launcher).
A returning host does not seize a healthy connection. The P4 destroys the old
WebSocket and closes admission before opening another. Stop/disconnect output
disable and generation fencing remain; interrupted actions return their existing
disconnect outcome. Connection switching does not transfer a MetaHuman objective,
replay movement or copy a durable execution database.

A phone browser can use an available host's password-protected dashboard when
that host's `AINEKIO_DASHBOARD_HOST` is bound to its private LAN address. The
default dashboard remains loopback. Direct on-P4 browser control is separate
from its setup portal and is not implemented by this change.

The launcher stays in the foreground. Press Ctrl+C to stop it. For normal
owner operation it can instead be supervised by the included user service.
The launcher uses `.venv/bin/python3` from this checkout; `AINEKIO_PYTHON` can
select another absolute interpreter path with the gateway dependencies installed.
Check local prerequisites without opening listeners or printing credentials:

```sh
./Master/start-physical-gateway.sh --check
```

This checks the interpreter, dependencies, discovery executable when enabled, and
saved pairing/password-store validity and recognition/Bridge configuration.
It does not verify network/port
availability or a physical connection.

Install the user service for this checkout without enabling or starting it:

```sh
./Master/start-physical-gateway.sh --install-service
systemctl --user daemon-reload
```

The installer preserves unmanaged existing units. After `.env` contains the
required tokens and the check passes, explicitly enable operation with:

```sh
systemctl --user enable --now ainekio-gateway.service
```

After that, the gateway and its discovery advertisement start when the owner
logs in and restart after a process failure. Rerun the installer and daemon reload
after moving the checkout. The unmodified tracked template assumes `~/Ainekio`.

On a host with the Ainekio hotspot services installed, set `AINEKIO_HOTSPOT=1`
in the ignored `.env` to select hotspot mode at startup. In Body Control,
**Settings → Robot connection mode** switches between the existing Wi-Fi network
and the configured robot hotspot immediately, saving the choice in `.env`.
The running gateway starts `ainekio-hotspot-dhcp.service` and its dependencies,
then stops `ainekio-hotspot-interface.service` and its dependent services when
switched to Wi-Fi or when the gateway exits, including a failed startup.
Switching does not restart Body Control. A robot using the hotspot reconnects
through its saved Wi-Fi profiles when that hotspot is turned off.
The operator needs permission to
start/stop those specific system units without an interactive prompt. Disable
their independent boot enablement when using this gateway-owned lifecycle.
The default is `0`, so other hosts need no hotspot services. Body Control's
dashboard login and robot pairing authentication continue to use their existing
owners. The launcher loads `.env`; a direct `python3 -m gateway.server` invocation
uses `AINEKIO_HOTSPOT` from its process environment and saves UI choices to `.env`
in its working directory.

To install these missing services on Ubuntu, install the packaged dependencies
and run the existing-contract installer once as root:

```sh
sudo apt-get install --no-install-recommends hostapd dnsmasq-base iw iproute2 network-manager polkitd
sudo python3 Master/install-robot-hotspot.py --interface wlan0 --operator "$USER" \
  --credentials /private/path/hostapd.conf
```

Run from the repository root; select the actual station interface and an
owner-only (0600) hostapd file containing the existing `ssid` and either
`wpa_passphrase` or `wpa_psk`. Privately copy that identity from the working
host to reuse the robot's saved Wi-Fi credentials. The installer copies only
those fields; desktop interface names and other hostapd settings are not imported.
It preserves unmanaged existing files with an explicit error and installs
no independently boot-enabled hotspot. Stop the gateway before updating the
installed configuration. Set `AINEKIO_HOTSPOT=1` in `.env` and use the normal
launcher to start it.

The radio must support an AP alongside its station connection; inspect `iw list`
for valid interface combinations. The installer adds `aineap0`, leaves the
station connection intact and defaults to 2.4 GHz channel 1. Use `--channel`
for another permitted channel (1–11); hardware limited to one channel requires
a compatible uplink channel or another adapter. Verify actual radio operation.
The separate interface serves the private `10.42.77.0/24` robot LAN, with the
gateway at `ws://10.42.77.1:8790/robot`. DHCP is confined to that interface and
does not advertise Internet routing or DNS. This is the robot-to-gateway link;
the Q6A gateway and configured remote services use the Q6A's existing uplink.
The installer does not configure NAT, remote MetaHuman execution or Cloudflare.
Operator permissions allow only starting/stopping the three named hotspot
units. Stopping the gateway removes its AP and DHCP/hostapd services together.

Updated P4 firmware tries distinct saved Wi-Fi networks in order, allowing 15
seconds per network while offline. It keeps a working Wi-Fi connection; gateway
failure selects other computers on that same network without Wi-Fi roaming.
An unauthenticated gateway attempt expires after 10 seconds, with a 1-second
retry delay and a bounded 2.5-second discovery query after configured candidates.
These are source limits, not measured physical handoff latency. Each slot supplies its own server
URL (for example `ws://10.42.77.1:8790/robot` on the computer hotspot). This uses
normal Wi-Fi association, not Wi-Fi Direct. If no saved network works, the
existing timed setup AP becomes available after 60 seconds; with no networks it
opens immediately. Wi-Fi/controller loss retains the existing output disable
and stale-command fencing, and reconnecting never replays movement.

The AP-only setup page at `http://192.168.4.1/` remains the recovery path. For an
already configured P4, it can replace a network and optionally change its server
address or token; blank address/token inputs preserve those values. Portal
saves restart immediately, as before. The serial configuration path also remains.
Existing single-network NVS configuration and setup passwords are retained when
upgrading; the first save creates the new P4 settings record. No NVS erase is
needed. Board-level switching and provisioning still require device testing.

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

Bodies advertising `camera_profiles_v1` expose separate **Stream resolution**
and **Snapshot resolution** controls in the existing panel. Stream output is
QVGA or VGA at the selected frame rate; snapshots can also use XGA (1024×768).
The still profile defaults to VGA and stays unchanged when a gateway caller
omits `snapshot_resolution`. Both profiles are runtime settings. One P4 camera
task and JPEG encoder serve both outputs, with no additional image-buffer
allocation. Disabling preview leaves requested snapshots available. A still
has explicit request/action/audio correlation, independent of preview FPS.

This supports a local P4→Q6A preview and occasional remote LLM stills through
the existing gateway and Environment Bridge. Continuous video is not sent to
the remote LLM. Selecting a frame from a low-resolution preview would limit
remote image detail to that preview resolution; requesting a separate encoded
still preserves the option of more detail from the same sensor capture mode.

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

## Desktop MetaHuman connected to a Q6A through Cloudflare

Run MetaHuman OS and its Environment Bridge on the desktop. Run only the Ainekio
gateway and its Cloudflare connector on the Ubuntu Q6A. The robot connects to
the Q6A gateway's `/robot` endpoint over its local Wi-Fi. No phone is involved.

The existing `Master/start-physical-relay.sh` can add a separate TCP hostname to
its named tunnel. TCP forwarding preserves the inner WebSocket request and the
Q6A connector opens a loopback connection, so `/environment` retains its existing
loopback and adapter-token checks. An HTTP tunnel to `/environment` is rejected
because it adds Cloudflare relay headers. TCP forwards the gateway port, including
both `/robot` and `/environment`; it is not a path-filtered HTTP route. The
dashboard remains on its separate, unrouted port.

### Q6A setup

On Ubuntu, install `python3-venv` and `avahi-utils` for the existing launcher,
then create this checkout's Python environment:

```sh
python3 -m venv .venv
.venv/bin/python3 -m pip install -r Emulator/requirements-host.txt
```

Install `cloudflared` using Cloudflare's
[download instructions](https://developers.cloudflare.com/tunnel/downloads/).
Import the existing robot pairing/password as described under **Using more than
one computer**. Runtime stores and `.env` do not arrive through Git sync.

Use a locally managed named tunnel with the existing relay launcher. If creating
one for the Q6A, run:

```sh
cloudflared tunnel login
cloudflared tunnel create ainekio-q6a
cloudflared tunnel route dns ainekio-q6a bridge.ainek.io
```

Use `bridge.ainek.io` on your Cloudflare-managed domain. Login opens a
browser, or prints a URL you can open on the desktop. In Cloudflare Zero Trust,
create a self-hosted Access application for this exact hostname and an Allow
policy for your login identity before starting the connector. Dashboard login
alone is not the application's Access login.

Set these in the Q6A's ignored `.env`, using the UUID/credentials file generated
on this host and the same adapter secret configured on the MetaHuman desktop:

```dotenv
AINEKIO_CLOUDFLARE_TUNNEL_ID=<tunnel UUID>
AINEKIO_CLOUDFLARE_CREDENTIALS_FILE=/home/<user>/.cloudflared/<tunnel UUID>.json
AINEKIO_CLOUDFLARE_ENVIRONMENT_HOSTNAME=bridge.ainek.io
AINEKIO_ENVIRONMENT_ADAPTER_TOKEN=<shared adapter secret>
```

Keep tunnel credentials outside the checkout. `AINEKIO_GATEWAY_PORT` selects the
gateway origin port when changed from 8790. The legacy robot HTTP hostname is
still configured, but only the separate TCP hostname needs a DNS route for this
desktop-to-Q6A setup. Do not run the same tunnel's connector simultaneously on
another host: Cloudflare can send connections to either installation.

Start the gateway and connector in separate terminals for the first test:

```sh
./Master/start-physical-gateway.sh --check
./Master/start-physical-gateway.sh
# In a second terminal:
./Master/start-physical-relay.sh --check
./Master/start-physical-relay.sh
```

`--check` validates the local relay configuration; it does not prove the Access
policy, DNS, Internet connectivity, or a robot connection. Keep both processes
running. The gateway's existing user service is documented above. For unattended
connector startup after reboot, use Cloudflare's documented
[Linux service setup](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/as-a-service/linux/)
with the generated `build/gateway/cloudflare/ainekio-robot.yml` config. Regenerate
it with the relay's `--check` after changing `.env`, then restart that service;
use either the service or the foreground relay launcher to own the connector.

### Desktop setup and test

Install `cloudflared` on the desktop, then in the MetaHuman checkout run:

```sh
./bin/connect-environment bridge.ainek.io
```

This opens local port 18790. Configure MetaHuman's ignored `.env` with
`MH_ENVIRONMENT_ADAPTER_URL=ws://127.0.0.1:18790/environment` and
`MH_ENVIRONMENT_ADAPTER_TOKEN` matching the Q6A's adapter secret.
`MH_ENVIRONMENT_BRIDGE_TOKEN` remains the desktop's existing internal service
token; it is separate from the adapter secret. Restart MetaHuman to load changed
environment variables. Alternatively set **Agent Monitor → Environment Bridge
→ Adapter URL** when `MH_ENVIRONMENT_ADAPTER_URL` is absent; the environment
variable takes precedence over that setting.

When the Bridge connects, the desktop connector opens a browser for Cloudflare
Access authentication. A desktop shortcut can run the forwarding command.
Keep the forwarder running, and use Agent Monitor's existing Bridge state and
diagnostics to verify the returned gateway session and connected robot. Test an
owner-selected command and its returned receipt, followed by the intended camera,
microphone and speech paths, before calling the demo ready. No motion is started
by the tunnel or desktop forwarding launchers.

This transport uses Cloudflare's
[Access TCP workflow](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/non-http/cloudflared-authentication/arbitrary-tcp/).
Cloudflare recommends Client-to-Tunnel for
[long-lived connections](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/protocols/).
The local TCP-forwarding regression test establishes gateway compatibility, not
Cloudflare authentication, Q6A performance, Wi-Fi latency, or physical behavior.

## Updating an ongoing movement

The authenticated Environment adapter accepts `environment.action.update` for
an already-admitted, ongoing V2 walk. It updates the original command through
the same gateway and body lease; it does not submit another cognitive action or
take task ownership from MetaHuman. The original action must have passed the
existing accepted-feedback admission gate before updates can be sent.

The `bridge.ready` observation exposes `state.activeMovementUpdates`. Updates
are available only for an online, motion-ready V2 body advertising ongoing
locomotion and command deadlines. Composed steering additionally requires
`walk_steering_v1`; use only the advertised `controls`. Older supported bodies
keep speed/stride/rate updates and explicitly reject steering before dispatch.
Use its `gatewayInstance`, the body's current
`robotId`/`epoch`, the original `actionId`, and the exact original `bodyLease`:

```json
{
  "type": "environment.action.update",
  "version": 1,
  "sessionId": "ainekio-01",
  "gatewayInstance": "<current gateway instance>",
  "robotId": "<connected robot ID>",
  "epoch": 7,
  "actionId": "<original action ID>",
  "bodyLease": {
    "bodyId": "ainekio-01",
    "executionId": "<original execution ID>",
    "generation": 1
  },
  "revision": 1,
  "validForMs": 500,
  "controls": {"speed": 70, "forward": 80, "turn": 25}
}
```

`controls` accepts `speed` **or** both `stride` and `rate`, using the existing
walking protocol ranges. Optional paired `forward` and `turn` percentages
(-100 through 100) compose translation and yaw in the running gait. Positive
forward advances; positive turn turns left. The original direction and gait
identifiers stay attached to the original command; composed steering is
interpolated over a gait cycle without resetting its phase. Finite movements cannot be converted into ongoing
walks. Servo targets and additional control fields are rejected. The body retains
its existing gait interpolation, coordinated timing and calibrated limits.

Use increasing positive integer revisions, up to 2,147,483,647. A revision
reserved for dispatch is stored in the original receipt and cannot be replayed,
including after reopening the receipt store. Send one update at a time and await
its result; a second concurrent update is rejected rather than queued.

`validForMs` is an integer from 1 through 2000, measured from receipt at this
adapter. The gateway's configured action-age limit can shorten it. Expiry,
lease, cancellation and connection identity are checked before dispatch; the
remaining validity also reaches the P4 through its existing command deadline.
Queueing and body receipt do not restart that validity. Upstream observation age
and transport delay before adapter receipt are separate and remain the sender's
responsibility.

The reply is `environment.action.update.result`, with the same `actionId` and
`revision`, a wire `sequence` when assigned, and status `acknowledged`, `rejected`
or `outcome_unknown`. An acknowledgement confirms body acceptance of the update;
it does not complete the parent task or verify measured motion. If the body's
reply times out after dispatch, further updates are blocked until that sequence
has a terminal receipt. Cancellation remains available while awaiting a reply.
Update results are not cognitive feedback and are not replayed to a new bridge.
The original action retains its normal completion/cancellation receipt.

MetaHuman's canonical active task executor now produces these updates through
the existing Coordinator and Bridge. The Bridge correlates each update receipt
to its finite settings job while leaving the original movement active. Task
programs use semantic moves, rather than a new body-level search command. Object-recognition model
comparisons are deferred to the assembled prototype.

Desktop coverage includes an authenticated WebSocket bridge, the real gateway
command path with a simulated body, parent-action lifetime, cancellation and
ownership changes, expiry, replay, reconnect identities and lost receipts:

```sh
PYTHONPATH=Master:Slave/software:Emulator:Emulator/tests \
  python3 -m unittest Emulator.tests.test_active_movement
```

## Continuous camera processing

`gateway.plugins.CameraFramePlugin` processes camera images outside the robot
receive loop. It retains one image being processed and one waiting image; each
new arrival replaces the waiting image. Synchronous consumers run on one worker
thread, and async consumers run in a separate task and must yield during I/O.
Slow inference therefore does not make the receive loop await the model.

An optional `observe` callback receives a `CameraAnalysis` containing the
backend's result, robot ID, connection epoch, frame counter, and monotonic
receipt/completion times. The backend can return detector boxes or a vision LLM
description; the gateway does not reinterpret either as verified identity or
task completion. Consumers must not treat model scores as measured probabilities.

The plugin drops frames/results that exceed `max_frame_age_s` (default one
second), belong to an ended connection epoch, or have a stale control heartbeat.
Set this limit for the intended observation use before selecting a backend.
Receipt time is **not** sensor capture time: it excludes age accumulated before
the gateway received the image. Acquisition timestamps and frame-associated
robot pose remain necessary before using image geometry for motion control.

The owner must await `plugin.aclose()` on removal or shutdown. Closing
unsubscribes the plugin, discards waiting frames/results, and joins its worker.
A running native inference call cannot be killed by coroutine cancellation;
shutdown waits for that call, so inference backends need their own bounded
request deadlines. This thread separation does not establish hard real-time
behavior for CPU-bound Python code or under system-wide load.

At the current 256 KiB JPEG transport cap, the two retained input images use at
most 512 KiB of payload storage. Model weights, decoded images, intermediate
tensors, results, and runtime overhead require a separate measured budget.

## Configured recognition and MetaHuman handoff

The production gateway can connect the camera worker to an explicitly configured
local or remote vision service. It uses the Chat Completions image/JSON interface supported
by services such as [vLLM](https://docs.vllm.ai/en/latest/features/multimodal_inputs/).
The model must support images and JSON output. No model, weights, package or
inference server is installed or started by this gateway.

```sh
export AINEKIO_VISION_URL='https://your-recognition-host/v1/chat/completions'
export AINEKIO_VISION_MODEL='your-served-vision-model'
# Set AINEKIO_VISION_API_KEY in the ignored .env or the service environment.
# Start the existing authenticated production gateway with these settings.
```

Equivalent CLI options are `--vision-url`, `--vision-model`,
`--vision-timeout-s` (default 2), and `--vision-max-frame-age-s` (default 1).
The frame-age limit must be 0.1–30 seconds and includes inference time; choose it
for the consumer's freshness needs. The URL and model must both be configured,
and the authenticated Environment Bridge must be enabled. Omission disables
recognition while leaving preview and correlated stills available.
`AINEKIO_VISION_API_KEY` supplies a Bearer authorization header; it is required
for a remote service and optional for a loopback service. Remote endpoints must
use HTTPS with normal certificate and hostname verification. Private certificate
authorities can use Python's standard `SSL_CERT_FILE` trust configuration; there
is no TLS-disable option. HTTP is retained only on a loopback IP (or `localhost`,
pinned to 127.0.0.1). URL credentials, queries, fragments and control characters
are rejected. Proxies and redirects are not followed. Images go only to this
operator-configured endpoint; observations cannot supply another destination.
The gateway's one bounded camera worker handles transport and validation while
the remote server performs heavy perception. The existing correlated remote
snapshot path is unchanged; no second runtime or task authority is added.

[`RecognitionResult`](perception.py) contains a bounded summary, up to 32
candidate objects, and up to 8 uncertainties. Object labels may carry optional
scores and normalized top-left `x/y/width/height` boxes. Missing scores or boxes
stay absent. Scores are estimates, not calibrated probabilities; a label does
not verify physical identity, task completion, distance or walkability. A
detector can return the same result type through the existing camera consumer
without changing the bridge or MetaHuman. Backend errors, incomplete JSON and
oversized responses are failures, not empty successful observations. Current-body
failures reach the existing `environment.observation` route as
`metadata.recognitionFailure` with robot/epoch/frame/gateway correlation and an
explicit reason (including HTTP authentication failures and timeouts). They do
not fabricate objects, body completion, or an automatic stop policy.

The adapter emits `environment.telemetry` with `kind: "vision.recognition"`
and a compact `perception` record: version 1, robot ID, connection epoch,
gateway instance, frame counter, backend/model, receipt-based `observedAt` and
`expiresAt`, summary, objects and uncertainties. `timeBasis: "gateway_receipt"`
explicitly excludes unmeasured sensor/transport age. Results expire from frame
receipt, not inference completion. Recognition metadata has no image data and
is not replayed after bridge reconnection.

MetaHuman's existing Environment Bridge coalesces recognition delivery to one
active and one newest pending result, independently of control receipts. Core
validates its contract and robot/session identity, rejects old frames, and stores
it in the existing observation's `state.perception` without replacing its still
image or renewing its control heartbeat. The existing **Environment Bridge
Input** exposes a fresh `perception` output; live observation reads remove
expired recognition while recorded evidence remains intact. Recognition arrivals
create no new objective or independent body job. An existing MetaHuman local
task can resume on recognition through its execution ledger and Work Coordinator.
MetaHuman retains task and movement decisions through the same body leases.

MetaHuman's sole active task executor accepts complete ordered programs from
Environment Mode and the autonomy selector. It advances saved gestures from
physical receipts without additional model calls, and can retain an ongoing gait
while fresh recognition steers it. Target identification uses free-text phase
criteria and finite asynchronous snapshot/model jobs. A confirmed identification
requests Finish on the original gait; its terminal receipt precedes subsequent
gestures, which run before the
whole task is complete. This replaces the temporary repeated-motion local-task
route and the per-movement Action Result model workflow. MetaHuman remains the
commander; processing services do not acquire another motion channel.

Stage 1 stopping policy (source/software only, 2026-10-07): normal Finish is a
speed-zero update, preserving concurrent speech. MetaHuman allows 5 seconds for
the original gait's terminal receipt, then uses owned cancellation. Failed or
expired required feedback requests cancellation promptly. Adapter cancellation
has a 2-second send/confirmation budget and requires the original command's
terminal receipt; a Stop ACK alone cannot terminate older action records.
MetaHuman also bounds its confirmation wait and retains `outcome_unknown` when
transport or receipt confirmation is unavailable. These bounds depend on the
existing Coordinator and transport; they are not a firmware feedback watchdog.

Cancellation and steering validate the immutable action/lease, gateway instance,
robot epoch and latest body dispatch inside the same send lock as manual control.
An unguarded manual update also invalidates autonomous cleanup authority. Speaker
cancellation is separately fenced. Capture cancellation never issues a body-wide
Stop. Disconnect/reconnect evidence stays unknown; old motion is never replayed.
A correlated terminal receipt establishes commanded execution outcome, not sensed
physical rest or measured servo position. Emergency Stop still sends the existing
P4 output-disable command and can interrupt speech.

Stage 2 instruction interpretation (software only) runs as finite Coordinator work
alongside the same MetaHuman execution. The approved pending-turn policy combines
all unanswered messages in order and attributes the response to the newest turn.
An interpretation-origin body command carries `metadata.interpretationBody`
(session, gateway instance, robot, epoch, last body sequence). The adapter checks
that fence under the existing wire-send lock; manual commands and body-session changes
invalidate late proposals. Every body command in an interpreted program keeps
this check. Admitted body dispatches persist `data.interpretationBody` in their
correlated receipt; Core advances its expected ownership from that receipt, never
from a newer live status snapshot. Steering updates keep the original action's
owner, and owned cancellation advances it to the Stop dispatch. Failed admission
cannot mint successor ownership. Stored receipt replay keeps the same evidence
across adapter recovery; a different gateway session or robot epoch invalidates
old commands. Emergency Stop remains independent of interpretation.
Owned cancellation records its Stop dispatch fence in `data.cancellationBody`,
including unknown results, so MetaHuman can distinguish its cleanup from a later
manual takeover. That ownership evidence never substitutes for the original
command's terminal receipt or proves physical rest. No firmware change is needed.

Before deployment, identify the actual MetaHuman/gateway/P4 versions and reconcile
old active executions. Supervised checks must cover normal Finish with speech,
required-feedback expiry, Stop plus original cancellation receipt, missing/late
receipts, manual takeover and reconnect. No firmware or service was changed on a
running robot during Stage 1; IMU and vision setup remain separate work.

Metric navigation, tracking, live IMU feedback and hardware qualification remain
separate work. Model comparisons remain deferred to the assembled prototype.

Desktop replay and WebSocket tests cover newest-frame delivery, stale/session
rejection, processing failures, shutdown, and command/stop receipts while
synchronous inference is blocked:

```sh
PYTHONPATH=Master:Slave/software:Emulator:Emulator/tests \
  python3 -m unittest Emulator.tests.test_recognition_backend \
  Emulator.tests.test_camera_perception \
  Emulator.tests.test_gateway_service Emulator.tests.test_environment_adapter \
  Emulator.tests.test_action_receipts
```

These tests use synthetic observations and the host emulator. They do not
qualify object-recognition accuracy, Q6A throughput, Wi-Fi latency, or physical
movement.

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

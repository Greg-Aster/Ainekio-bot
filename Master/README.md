# Master

This folder contains remote brain-side code. It does not run on the physical
robot.

- `gateway/server/` owns the brain side of the protocol-v1 WebSocket.
- `gateway/dashboard/` owns the authenticated local operator interface.
- `gateway/environment_adapter/` owns the authenticated full-duplex environment
  endpoint and semantic command translation.
- `gateway/security.py` owns bounded dashboard-verifier and robot-token stores.
- `start-physical-gateway.sh` starts the real brain-side gateway on the LAN while
  keeping the operator dashboard bound to localhost. It publishes the one
  default `_ainekio._tcp.local` discovery identity.
- `stop-physical-gateway.sh` stops only the physical gateway. It stops the user
  service first when supervised, then narrowly matches the repo runtime data as
  a fallback for older manual/background launches. Pass `--disable` to also
  prevent the enabled user service from starting automatically after login or
  reboot.
- `ainekio-gateway.service` supervises that same launcher for normal physical
  use; it does not introduce another gateway implementation.
- `start-physical-relay.sh` starts the optional foreground Cloudflare transport
  for `wss://robot-gateway.ainek.io/robot`; it publishes no dashboard or
  Environment Bridge route and keeps tunnel credentials outside the repository.
  Pass `--check` to validate the local tunnel configuration without connecting.
- `configure-physical-relay-dns.py` dry-runs or creates only the exact proxied
  relay CNAME. It refuses the wrong Cloudflare account and existing conflicting
  records, requires `--apply` for mutation, and reads its short-lived scoped API
  token from the terminal environment rather than the repository.

The physical gateway's Environment Bridge automatically uses the single connected
robot, including V1 (8 servos) and V2 (12 servos). Disconnect one and connect the
other to switch its capabilities, audio input and command/speech destination.
Disconnected entries do not affect selection. `AINEKIO_ROBOT_ID` is the pairing
identity used with `AINEKIO_ROBOT_TOKEN`; it does not pin the Environment Bridge.
`AINEKIO_ENVIRONMENT_SESSION_ID` remains the stable MetaHuman session name.

Body Control **Audio → Speech output** selects **Computer** (the MetaHuman browser)
or **Robot speaker** (the connected V1 or V2) for robot conversation replies.
It reads and saves the active owner's existing MetaHuman `tts.outputTarget`
preference over the authenticated Environment Bridge; it does not store a second
copy in Body Control. Keep MetaHuman Environment Mode connected to change it.
Robot speech uses Kokoro. **Test robot speaker** always sends its tone to the
robot, independently of the speech destination.

Robot replies have no configured duration, total audio size, or chunk-count cutoff.
MetaHuman prepares the complete reply on the host; the Environment Bridge sends
it to Body Control, which streams 20 ms PCM frames to the robot. Reply length
therefore uses host memory and storage without growing the robot's audio buffer.
Interrupted speech is cancelled through the existing adapter receipt handshake
before MetaHuman releases its queue ownership. Speech is not replayed after an
uncertain delivery, and cancelling speech uses the audio command, not a motion stop.

On updated P4 firmware, **Audio → Robot speaker volume → Save volume on robot**
sets a persistent master volume for speech and local sounds. The slider reads the
robot's reported setting; 0% mutes and 100% preserves full output. The test tone's
own level is multiplied by this master volume. This control does not change
Computer playback volume, which remains controlled by the browser/OS.

# Bridge Liveness Handoff - 2026-07-22

Status: paused by owner for the night. Do not flash again until the owner is
present. The OLED may remain attached for all later work.

## Owner requirement

An authenticated home-companion session must remain connected through
conversational idle and recoverable Wi-Fi stalls. Robot or MetaHuman messages
may be many minutes apart.

Safety is action-scoped:

- a stale control heartbeat stops active motion;
- stale control alone does not close the WebSocket, clear authentication, or
  force mDNS rediscovery;
- an actual Wi-Fi or WebSocket error still enters the existing body failsafe and
  reconnect path.

## Physical controller currently flashed

The controller is running the last application-only diagnostic image flashed on
2026-07-22. Independent read-back verification passed for its 1,411,648-byte
application region at `0x20000`. NVS and LittleFS were not written, so saved
Wi-Fi, robot identity, pairing token, and OLED assets remain intact.

That flashed image contains:

- no gateway-side or body-side application heartbeat disconnect timer;
- a four-second stale-control motion stop that keeps the session authenticated;
- duplicate native WebSocket PING frames disabled;
- transient single-frame control and microphone writes treated as recoverable;
- temporary cumulative diagnostic status fields;
- the earlier aggressive TCP keepalive values (5-second idle, 5-second retry,
  three retries).

The last item is important: the keepalive-free correction described below is
built in source but is **not flashed on the controller**.

The temporary diagnostic fields remain on the physical controller until the
next application flash. They have been removed from the prepared source so they
do not become permanent protocol surface.

## Gateway state

The physical gateway was reloaded under the enabled
`ainekio-gateway.service`, with one gateway process and one
`_ainekio._tcp.local` publisher. Its LAN address during this session was
`192.168.0.44`; the controller peer was `192.168.0.84`.

The maintained gateway source no longer closes an authenticated robot with
`1011 control timeout`. It continues one-second JSON heartbeats for control-loop
health and waits for a real socket close/error before removing the robot.

The gateway restart performed immediately before this pause loaded the temporary
diagnostic audit whitelist. Restarting the service once after the next clean
source validation will remove that temporary whitelist; it does not affect
control behavior.

## Evidence collected

Successive physical A/B sessions established the following:

| Image/policy | Approximate session result |
| --- | --- |
| Original application timeout | disconnected after roughly 6-10 seconds |
| Separate WebSocket TX lock | reached roughly 31 seconds, then `1011 control timeout` |
| Timer teardown removed | reached roughly 68 seconds, then abnormal close `1006` |
| Native WebSocket PING disabled | reached roughly 93 seconds, then `1006` |
| Transient write failure made nonfatal | reached roughly 171 seconds, then `1006`; automatically rediscovered and re-authenticated |

The diagnostic controller reported:

- control transmit failures: zero through most of the 171-second session, then
  one cumulative failure after reconnect;
- media transmit failures: zero;
- several stale-control intervals that recovered on the same authenticated
  socket before the eventual close.

Live `ss -tin` evidence during one impaired interval showed:

- RTT around 444 ms;
- congestion window reduced to one packet;
- retransmissions and loss;
- TCP retransmission timeout around 6.2 seconds;
- a small queued gateway control write;
- no Environment Bridge or dashboard TCP client attached at that moment.

This is physical LAN impairment, not conversational idle. The 20-30 second
status pauses could later recover in bursts, but the controller's aggressive
TCP keepalive window could expire first and turn the recoverable pause into
`1006`.

## Prepared source after diagnostic cleanup

The source tree now keeps the product changes and removes temporary telemetry:

- gateway application-heartbeat timeout teardown removed;
- emulator parity updated so idle does not disconnect a body session;
- controller stale heartbeat stops motion without closing the session;
- actual socket/Wi-Fi disconnect still invokes failsafe and reconnect;
- native ESP WebSocket PING disabled in the pinned client because protocol-v1
  already owns heartbeats;
- TCP keepalive teardown disabled so TCP retransmission can recover from a long
  local Wi-Fi pause;
- single-frame control and microphone write failures are dropped/retried without
  destroying the session;
- a failed fragmented camera write still rebuilds the socket because continuing
  an incomplete WebSocket message would corrupt framing;
- temporary `control_tx_failures`, `media_tx_failures`, and
  `control_stale_events` status fields removed from firmware/core source and
  gateway audit filtering.

The internal bounded failure counters and failure-only firmware logs that
predated the temporary wire telemetry remain. They do not expand the protocol
or continuously write storage.

## Validation completed

- Full Emulator/gateway suite: 141 tests passed before the final keepalive
  adjustment.
- Focused gateway liveness/security suite: 22 tests passed after the final
  keepalive adjustment and again after temporary diagnostic-field removal.
- Standalone C control encoder test passed in its intended debug configuration.
- Final diagnostic-cleaned ESP-IDF build passed after disabling TCP keepalive;
  the application is `0x158960` bytes and retains 55% free space.

The diagnostic cleanup is source-complete, built, and host-tested. It has not
been flashed. No further architecture change is needed for that cleanup.

## Next session

1. Confirm the owner is present and the controller is on the left CH343 USB
   port. Leave the OLED attached.
2. Confirm `git diff --check`, the focused 22-test gateway suite, and the clean
   ESP-IDF build remain current; rerun only if another agent changed the files.
3. Restart `ainekio-gateway.service` once so gateway runtime matches source.
4. Flash **only** `build/ainekio_slave_brain.bin` at `0x20000`. Do not write
   NVS, OTA data, LittleFS, the bootloader, or the partition table.
5. Independently run `verify_flash` for the application region.
6. Require a 15-minute authenticated idle soak with five-second status traffic.
   Watch both `operations.jsonl` and `ss -tin`; do not treat the OLED face alone
   as proof.
7. During the soak, confirm there is no disconnect record and no repeated
   `SEARCHING GATEWAY` cycle.
8. Stop/restart the gateway deliberately once and confirm one clean new epoch,
   motion failsafe, mDNS rediscovery, and automatic return to the face.
9. Only after idle stability passes, test one snapshot and VAD microphone
   traffic. Continuous camera streaming remains off unless enabled explicitly
   in Body Control.

If the keepalive-free image still receives `1006`, capture simultaneous
controller RSSI from the existing status/dashboard and TCP retransmission state.
Do not reintroduce an application idle-disconnect timer. At that point the next
question is Wi-Fi/AP reliability or ESP transport behavior under loss, not
MetaHuman message timing.

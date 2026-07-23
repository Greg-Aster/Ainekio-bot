# Ainekio Cloudflare Robot Relay Deployment and Audit Trail

Status: **Shelved by owner - local WiFi selected as the primary transport**  
Owner approval: 2026-07-22  
Protocol authority: `Ainekio - System Specification v1.0`, especially sections
3.1, 3.2, 3.7, 9, 10, and 11

## Purpose

Give the physical robot one stable gateway endpoint that does not change when
the brain computer receives a different DHCP address or moves to another
Internet-connected network.

The intended robot endpoint is:

```text
wss://robot-gateway.ainek.io/robot
```

The relay is transport only. It does not translate protocol messages, persist
robot media, make safety decisions, or replace the existing gateway. The body
continues to initiate exactly one protocol-v1 WebSocket, authenticate with its
existing robot identity and token, and enforce all motion and disconnect safety
locally.

## Confirmed starting state

- `ainek.io` uses Cloudflare authoritative DNS and is already served through
  Cloudflare.
- `cloudflared` is installed on the brain computer.
- Existing `metahuman` and `ollama-tunnel` Cloudflare tunnels are unrelated and
  must not be modified or reused for the robot relay.
- The Ainekio gateway listens for robot WebSockets on port 8790 and routes the
  body at `/robot`.
- The dashboard remains bound to `127.0.0.1:8791`.
- The Environment Bridge uses `/environment` on port 8790 but must remain local
  and must not be published by the robot relay.
- The current firmware source accepts `ws://` and `wss://` endpoint URLs and
  attaches the ESP-IDF certificate bundle for `wss://` connections. This is not
  evidence that the currently installed controller image has completed a WSS
  handshake; R4 owns that physical proof.
- The current robot configuration stores one endpoint. Automatic LAN/relay
  fallback is not implemented and is not being implied by this deployment.

## Architecture

```text
Physical Ainekio body
  -> wss://robot-gateway.ainek.io/robot
  -> Cloudflare edge
  -> named tunnel: ainekio-robot
  -> cloudflared on the brain
  -> http://127.0.0.1:8790/robot
  -> existing authenticated Ainekio Gateway
```

Only the exact public hostname and `/robot` path may reach the local gateway.
Every other path must terminate at the tunnel with HTTP 404. In particular:

- `/environment` is not public.
- The dashboard and login page on port 8791 are not public.
- The static `ainek.io` website is not a relay and is not changed.
- No Cloudflare credential, robot token, tunnel credential JSON, runtime log,
  or plaintext password may enter the repository.

## Why this fits the system specification

Section 3.1 explicitly says that LAN and relay endpoints use the identical
protocol, that a relay is a transparent payload pipe, and that relay transport
must use `wss://`. The gateway remains the owner of robot authentication,
epochs, sequence assignment, lifecycle, and final command gates. The body
remains the only owner of physical safety.

Section 11 keeps a shipped relay implementation out of v1 until a deployment
document and relay-specific reconnect, revocation, duplicate-session, and
stop-latency tests exist. This file is that deployment record; creating a
tunnel does not mark those gates passed.

## Security boundaries

1. Cloudflare terminates public TLS; the tunnel reaches the gateway only through
   loopback HTTP on the brain.
   Cloudflare therefore joins the trust boundary and can technically process
   the WebSocket payload at its edge. That socket carries the robot hello token,
   camera JPEGs, microphone PCM, commands, and feedback. "No relay persistence"
   is not the same as end-to-end payload encryption between body and gateway.
2. Tunnel ingress matches `robot-gateway.ainek.io` and `/robot` only.
3. The existing strong robot token remains mandatory in the protocol hello.
4. Gateway authentication failures continue to close the socket with code 4001.
5. Cloudflare Access service authentication is a production gate, not an
   assumed current capability. The current firmware does not send Cloudflare
   Access service-token headers during the WebSocket upgrade.
6. Until Access authentication or an owner-approved equivalent relay-level
   control is implemented and tested, the public relay is a supervised pilot
   and is not considered a shipped primary transport.
7. No raw servo or unsafe command surface is introduced. The relay carries only
   the existing protocol.

Official operational references:

- <https://developers.cloudflare.com/tunnel/>
- <https://developers.cloudflare.com/cloudflare-one/faq/cloudflare-tunnels-faq/>
- <https://developers.cloudflare.com/network/websockets/>
- <https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/>

## Reliability and mobility tradeoffs

The hostname remains stable while the brain changes LAN addresses because
`cloudflared` makes the outbound connection. The robot and brain may be on
different Internet-connected networks. This does not remove the robot's need
for valid WiFi credentials.

Cloudflare or Internet loss can terminate a long-lived WebSocket. That is a
normal protocol disconnect: the body must fail safe and reconnect with bounded
backoff. A dedicated travel router remains the preferred offline/mobile LAN
option when the robot and brain travel together. A home DHCP reservation remains
a useful local recovery path but is not the robot's stable public identity.

Cloudflare may also terminate established WebSockets during edge updates and
closes idle WebSockets. Protocol ping/pong traffic must remain active, and relay
acceptance must treat a Cloudflare-initiated close like any other disconnect.

## Cross-work compatibility findings

This review compares the relay plan with the bridge-hardening work recorded in
`BRIDGE_HARDENING_PLAN.md`. The relay does not require a second bridge or a
protocol translation layer. MetaHuman continues to connect locally to
`/environment`; the physical body alone uses the public `/robot` endpoint. Robot
identity, pairing token, epochs, semantic action gates, capability truth,
terminal feedback, and correlated camera handling remain owned by the existing
gateway/body path.

| Finding | Status and required resolution |
| --- | --- |
| C1 - Bridge compatibility | Compatible. The relay is transport-only and does not invalidate the existing bridge hardening. Any implementation that publishes `/environment`, translates messages, stores/replays commands, or reports completion itself would violate this boundary. |
| C2 - Liveness contract drift | **Unresolved production blocker.** System Specification v1.0 section 3.7 still specifies ping after 2 seconds and FAILSAFE/offline after 3 seconds. Prepared gateway/controller source uses a 1-second heartbeat and 4-second offline/failsafe bound. Resolve this through an approved specification erratum or restore the normative 2/3-second behavior before claiming relay acceptance. Record both the source constants and the behavior of the image actually installed on the controller. |
| C3 - Stop-latency measurement | **Test correction required.** The normative 100 ms safety bound starts when the body receives `stop`. Relay testing must separately record gateway-send-to-body-receipt network latency and body-receipt-to-motion-preemption latency. Internet round-trip time must not be presented as the local S7 deadline. |
| C4 - Cloudflare Access | **Known production blocker.** The current controller does not attach Access service-token headers to the WebSocket upgrade. Enabling Access now would prevent connection. Adding it requires protected configuration/NVS fields, provisioning and rotation behavior, upgrade-header support, tests, and a later owner-approved firmware flash. |
| C5 - Privacy boundary | **Owner decision required before primary use.** Cloudflare terminates TLS, so robot authentication data, camera images, microphone audio, commands, and feedback are no longer confined to the owner LAN even though the relay must not persist them. Document the accepted trust, logging, retention, and media-use policy. |
| C6 - Source versus installed firmware | Source inspection confirms WSS URL support and ESP-IDF CA-bundle attachment. The currently flashed image and real certificate negotiation remain unproven until R4. Do not describe source capability as physical evidence. |
| C7 - Process availability | The pilot relay launcher is deliberately foreground-only. A stable DNS name does not keep the gateway or `cloudflared` running after reboot. Primary use needs coordinated startup, shutdown, failure reporting, and recovery for both processes. |
| C8 - Operator guidance | The current setup portal still instructs the operator to enter a brain LAN address even though it accepts `wss://`. Update and physically verify that guidance with the next approved firmware/UI batch; it does not require a standalone flash. |

## Acceptance gates

The relay cannot be declared flash-ready/primary until all applicable evidence
is recorded here.

### Configuration and isolation

- [x] A separate named tunnel `ainekio-robot` exists. Its current ID is
      `ddf3b49b-0ef4-4442-b997-f3372a6cd393`; it has no active connector.
- [x] `robot-gateway.ainek.io` resolves through Cloudflare; exact tunnel routing
      remains part of the connector smoke test because a proxied CNAME does not
      expose its target in public DNS answers.
- [x] Tunnel configuration validates locally.
- [x] `/robot` reaches the local gateway through WSS. A negative-authentication
      hello reached the gateway and returned its protocol `auth` error and 4001
      close code.
- [x] Cloudflare WebSockets are enabled for the zone and pass a WSS upgrade.
- [ ] The initial upgrade is covered by the intended WAF/rate-limit policy.
- [x] `/environment`, `/`, `/login`, and arbitrary paths return 404 through the
      public hostname.
- [x] Port 8791 remains loopback-only.
- [x] Existing Cloudflare tunnels and the static website are unchanged after
      removal of the exact accidental DNS record.
- [x] No secret or credential file is tracked by Git. The tunnel credential is
      outside the repository with mode 0400, and generated runtime configuration
      is covered by the existing `build/` ignore rule.

### Protocol and security

- [x] Correct robot id/token authenticates through the relay. The protected
      stored token produced a protocol-v1 `welcome` without being printed.
- [x] Wrong token is rejected with the protocol-auth close path.
- [ ] Token revocation closes and prevents relay reconnect.
- [ ] Duplicate authenticated connection preserves epoch/cancellation rules.
- [ ] Cloudflare Access service authentication or an owner-approved equivalent
      relay-level control is implemented before primary deployment.
- [ ] The owner accepts and records the Cloudflare TLS/media trust boundary.

### Safety and reliability

- [ ] The 2/3-second specification versus prepared 1/4-second liveness behavior
      is resolved, and tunnel interruption causes body FAILSAFE within the
      approved bound.
- [ ] Body reconnects after tunnel restoration without replaying an old command.
- [ ] Gateway-send-to-body-receipt latency is measured under representative
      relay conditions.
- [ ] Body receipt-to-motion-preemption remains within 100 ms under
      representative relay conditions.
- [ ] Camera and microphone traffic do not delay control or stop.
- [ ] A supervised soak records reconnects, latency, drops, and minimum heap.
- [ ] Rollback to the LAN endpoint is documented and exercised.
- [ ] Primary deployment has coordinated gateway/relay startup, shutdown,
      health reporting, and recovery after a brain-computer reboot.

## Rollback

1. Stop the repo-local relay process.
2. Remove or disable the `robot-gateway.ainek.io` DNS route.
3. Leave the existing gateway and dashboard unchanged.
4. Reconfigure the robot to a validated local `ws://` endpoint if relay testing
   cannot continue.
5. Delete the `ainekio-robot` tunnel only after confirming no connector uses it.

Stopping or deleting the relay never erases robot NVS, gateway tokens,
calibration, assets, or dashboard data.

## Implementation phases

1. **R0 - Architecture record:** create this deployment/audit file.
2. **R1 - Repo-local tooling:** add a foreground relay launcher that generates
   ignored runtime configuration, validates exact-path ingress, and never stores
   credentials in the repository.
3. **R2 - Cloudflare resources:** create a separate named tunnel and DNS route.
4. **R3 - Host smoke tests:** prove WSS authentication and public-path isolation,
   then stop the pilot connector when unattended.
5. **R4 - Body endpoint:** update the robot once to the stable WSS hostname and
   verify ESP certificate validation and reconnect behavior.
6. **R5 - Production hardening:** resolve the normative liveness values, add
   relay-level authentication, record the Cloudflare trust decision, add
   coordinated process supervision, and complete the safety/reliability gates
   before choosing the relay as primary.

## Current implementation boundary

R0 and the repo-local portion of R1 are complete. A separate tunnel was created
for R2, but the host's current `cloudflared` origin certificate is authorized
for the `megameal.org` zone, not the intended `ainek.io` zone. Its global
configuration also defaults to the unrelated `metahuman` tunnel. Those two
conditions make the shorthand `cloudflared tunnel route dns` command unsafe on
this host unless both the tunnel and zone context are made explicit.

The first route attempt exposed that mismatch: Cloudflare created
`robot-gateway.ainek.io.megameal.org` pointing at the existing MetaHuman tunnel,
not `robot-gateway.ainek.io` pointing at the new robot tunnel. Work stopped
immediately. The exact accidental record was identified by zone, full record
name, type, and target; only that record was deleted; and a follow-up query
confirmed zero records with that name. No connector ran, no robot configuration
changed, and no existing tunnel or `ainek.io` website/DNS record was modified.

R2 remains incomplete until the owner authorizes the actual `ainek.io` zone.
Local Wrangler deployment logs confirm that the `merkin-ainekio` Pages project
and the new robot tunnel share Cloudflare account
`85ab4e804339eb1a39a5a8d9da96ab39`, so tunnel recreation is not currently
required. The safe continuation is to obtain a zone-scoped Cloudflare
credential for `ainek.io`, create the exact CNAME for
`robot-gateway.ainek.io` to
`ddf3b49b-0ef4-4442-b997-f3372a6cd393.cfargotunnel.com`, then verify the record
through an independent DNS lookup before starting a connector. The repository
tool `Master/configure-physical-relay-dns.py` implements that exact operation.
It requires a short-lived `CLOUDFLARE_API_TOKEN` with `Zone:Read` and `DNS:Edit`
limited to `ainek.io`; it runs read-only unless `--apply` is present, rejects a
different account or any same-name conflict, and does not store the token.

## Shelving decision and local replacement

On 2026-07-22 the owner chose not to use Cloudflare as the robot's primary
transport. Camera JPEGs, microphone PCM, commands, and feedback should remain
on the local WiFi instead of making an avoidable Internet round trip and adding
Cloudflare availability, latency, and privacy dependencies. The host-side relay
proved technically functional, but the physical controller never completed a
public WSS request and there is no architectural reason to carry the local media
path through a remote edge for normal operation.

The connector was stopped gracefully. The `ainekio-robot` tunnel, proxied DNS
record, credentials, repo-local launcher, and test evidence are retained but
inactive so the work remains recoverable for a later, explicitly scoped remote
access experiment. Nothing starts the relay automatically.

The selected local stabilization path is a DHCP reservation in the CenturyLink
router for the brain's WiFi interface:

```text
Brain WiFi MAC:     FC:77:74:C8:19:F5
Reserved IPv4:      192.168.0.44
Robot endpoint:     ws://192.168.0.44:8790/robot
```

Do not use `DNDIY.local` yet. The brain runs Avahi, but current IPv4 resolution
advertises Docker's `172.17.0.1` rather than the WiFi address, so it is not a
valid robot endpoint without a separately approved and physically tested mDNS
configuration change.

After the DHCP reservation is saved, use manual provisioning to replace only
the endpoint with the local URL above while re-entering the current WiFi,
identity, and protected robot token. Then verify a sustained body session and
resolve the pre-existing 1011 `control timeout` before declaring the local path
stable. The Cloudflare R4/R5 acceptance work is no longer an active target.

### Owner-authorized R2 procedure

1. In Cloudflare, create a short-lived custom API token with `Zone:Read` and
   `DNS:Edit`, limited to the single `ainek.io` zone. Do not paste it into this
   document, the repository, chat, or shell history.
2. Enter it through a hidden terminal prompt and run the read-only check:

   ```bash
   read -rsp "Cloudflare token: " CLOUDFLARE_API_TOKEN
   printf '\n'
   export CLOUDFLARE_API_TOKEN
   ./Master/configure-physical-relay-dns.py
   ```

3. Confirm that the dry-run prints only this planned record:

   ```text
   robot-gateway.ainek.io -> ddf3b49b-0ef4-4442-b997-f3372a6cd393.cfargotunnel.com
   ```

4. Apply and immediately remove the token from the terminal environment:

   ```bash
   ./Master/configure-physical-relay-dns.py --apply
   unset CLOUDFLARE_API_TOKEN
   ```

5. Independently verify public DNS, then run
   `./Master/start-physical-relay.sh --check` before any supervised R3 connector
   or WSS test.

## Audit trail

| Time (PDT) | Phase | Action and evidence | Result |
| --- | --- | --- | --- |
| 2026-07-22 13:16 | R0 | Owner approved documenting and implementing a stable `ainek.io` relay endpoint. | Started |
| 2026-07-22 13:16 | R0 | Confirmed `ainek.io` uses Cloudflare DNS; `cloudflared` is installed; unrelated `metahuman` and `ollama-tunnel` tunnels exist. | Existing tunnels marked protected from modification |
| 2026-07-22 13:16 | R0 | Compared deployment against System Specification v1.0 relay, security, liveness, and acceptance clauses. | Architecture-compatible with explicit unpassed production gates |
| 2026-07-22 13:18 | R1 | Added `Master/start-physical-relay.sh`, documented non-secret environment inputs, generated config under ignored `build/gateway/cloudflare/`, and validated exact `/robot` versus catch-all routing with `cloudflared tunnel ingress`. | Passed; launcher remains foreground and credentials are rejected if placed inside the repo |
| 2026-07-22 13:18 | R1 | Ran Bash syntax validation. `shellcheck` is not installed on this host, so no ShellCheck result is claimed. | Bash syntax passed; ShellCheck unavailable |
| 2026-07-22 13:20 | R2 | Created the separate named tunnel `ainekio-robot` with ID `ddf3b49b-0ef4-4442-b997-f3372a6cd393`; its credential file is mode 0400 outside the repository. | Tunnel created; no connector started |
| 2026-07-22 13:23 | R2 | Attempted the intended DNS route using the host CLI. The host's global `metahuman` tunnel default and `megameal.org` origin-certificate zone caused Cloudflare to create `robot-gateway.ainekio.megameal.org` pointing at the existing MetaHuman tunnel. | Failed safely; work stopped before starting a connector or changing the robot |
| 2026-07-22 13:26 | Cross-work review | Compared the relay plan with bridge hardening, current firmware/gateway source, the normative specification, and current Cloudflare WebSocket and Access requirements. | Transport architecture remains compatible; C2-C8 are explicit unresolved production or owner-decision gates |
| 2026-07-22 13:29 | R2 rollback | Queried the `megameal.org` zone for the exact accidental CNAME and required a single match on zone, full name, type, and old MetaHuman tunnel target before deletion. Deleted only record `e7d4c53eaeba8110f69fbcece9ffe902`. | Exact accidental record removed |
| 2026-07-22 13:30 | R2 rollback | Repeated the exact-name DNS query and queried the new robot tunnel by UUID with the unrelated global config disabled. | Zero accidental DNS records remain; robot tunnel has no active connection; existing services were not touched |
| 2026-07-22 13:30 | R2 authorization | Confirmed the current host origin certificate is scoped to `megameal.org`; the existing Wrangler OAuth session is known not to have DNS-write permission for `ainek.io`. | Paused before DNS creation; owner authorization for the actual `ainek.io` zone is required |
| 2026-07-22 13:31 | R1 verification | Re-ran Bash syntax and Git whitespace checks; verified the generated runtime path is ignored, the launcher is executable, and the tunnel credential is outside the repository with mode 0400. | Passed; no credential content was printed or added to Git |
| 2026-07-22 13:34 | R2 account verification | Compared the account ID in the tunnel origin certificate with the account used to create and deploy the `merkin-ainekio` Pages project in local Wrangler logs. | Both use account `85ab4e804339eb1a39a5a8d9da96ab39`; keep the new tunnel and obtain only `ainek.io` DNS authorization |
| 2026-07-22 13:38 | R2 login safety | Tested a separate `--origincert` login path with a temporary filename. This installed CLI still tried to overwrite the existing default origin certificate and refused to proceed. | Rejected certificate-swapping as the operator path; existing MetaHuman certificate remained untouched |
| 2026-07-22 13:39 | R2 DNS tooling | Added `Master/configure-physical-relay-dns.py` with dry-run default, explicit `--apply`, exact account/zone/name/target checks, conflict refusal, and environment-only token handling. | Python syntax/help/missing-token behavior passed; three mocked API-flow tests passed for dry-run, apply-and-verify, and conflict refusal |
| 2026-07-22 13:42 | R1 local configuration | Added the new tunnel ID and outside-repository credential path to the ignored operator `.env`; added `--check` mode to the relay launcher and ran it against the actual credential path. | Passed; exact `/robot` and 404 catch-all rules validated; runtime config is mode 0600 and ignored; no connector started |
| 2026-07-22 13:53 | R2 DNS verification | Queried public DNS after the owner manually added the record. The hostname returned Cloudflare IPv4 and IPv6 addresses; HTTPS `/` returned 530 before any connector was running. | DNS/proxy active; pre-connector failure state captured |
| 2026-07-22 13:53 | R3 preflight | Inspected host listeners and reran `start-physical-relay.sh --check`. The gateway listens on `0.0.0.0:8790`, the dashboard remains on `127.0.0.1:8791`, and exact `/robot` plus catch-all isolation rules validate. | Passed; ready for supervised connector start |
| 2026-07-22 13:54 | R3 connector | Started `ainekio-robot` using its exact runtime configuration. Four QUIC connections registered with Cloudflare Seattle edge locations. The installed client warned that ICMP proxying is unavailable and the UDP receive buffer is below its requested size. | Connector live; ICMP warning is unrelated to HTTP/WSS routing; UDP warning retained for soak/performance review |
| 2026-07-22 13:55 | R3 isolation | Requested public `/`, `/environment`, `/login`, and an arbitrary route; each returned 404. Confirmed the local dashboard answered on `127.0.0.1:8791` while the listener remained loopback-only. | Passed; dashboard and Environment Bridge are not published |
| 2026-07-22 13:55 | R3 negative authentication | Established TLS/WSS through `robot-gateway.ainek.io/robot` using normal certificate verification and sent a protocol-v1 hello with an intentionally wrong identity/token. Upgrade completed in 109.5 ms; gateway returned `{"t":"err","code":"auth"}` and closed with 4001. | Passed; exact public route reaches the existing gateway and preserves its authentication failure path |
| 2026-07-22 13:56 | Live body observation | The real `ainekio-01` authenticated as epoch 2, received the gateway's automatic `stop`, reported `boot`, `sd_fail`, and status, then disconnected with 1011 `control timeout`. Host socket and tunnel metrics showed no corresponding public request. | This was a direct-LAN body session, not a relay failure; the existing body liveness problem remains open and the body was not displaced for testing |
| 2026-07-22 13:59 | R3 positive authentication | Confirmed zero active robot sockets, loaded the protected token without printing it, and completed a short correct-token WSS hello. Gateway returned protocol-v1 `welcome` for epoch 3/profile `home`; TLS/WSS upgrade took 112.4 ms. Cloudflared's request counter increased from 5 to 6 and returned to zero concurrent body sockets afterward. | Passed; correct and incorrect authentication both traverse the public relay while preserving gateway behavior |
| 2026-07-22 14:02 | R3 handoff | Rechecked local cloudflared metrics after smoke testing: four healthy tunnel connections, six completed requests, and zero active proxied robot sockets. | Host-side relay smoke test complete; connector kept running for the owner's supervised R4 provisioning step |
| 2026-07-22 16:52 | R4 physical report | Owner reported the OLED reads `GATEWAY OFFLINE` after provisioning. Cloudflared had four active connections, zero proxy errors, zero current body sockets, and still only the six earlier test requests; the gateway audit contained no new body session. | Failure occurs before a request reaches Cloudflare or the gateway; authentication and gateway routing are not implicated yet |
| 2026-07-22 16:52 | R4 network history | Connector logs showed that the brain lost all QUIC routes and local DNS while its WiFi interface was away from the CenturyLink network, then recovered four Cloudflare connections at 16:49. | The brain-side outage recovered, but the body did not subsequently reach the relay; future provisioning should use another device or keep the brain on Ethernet |
| 2026-07-22 16:56 | R4 relay recheck | Repeated public HTTPS and WSS negative-authentication checks after recovery. Public `/` returned 404, TLS/WSS upgraded in 120.8 ms, wrong-token rejection remained correct, four tunnel connections were healthy, and request count rose only for the two controlled host checks from 6 to 8. | Relay currently healthy; no evidence of a physical-body WSS request |
| 2026-07-22 16:56 | R4 firmware configuration review | Confirmed the flashed-build configuration enables the full ESP-IDF certificate bundle and disallows insecure TLS; WSS client construction attaches that bundle. | Source/build settings are correct, but physical DNS/TLS negotiation needs serial evidence |
| 2026-07-22 16:58 | R4 SNTP hypothesis | Searched the firmware and installed ESP-IDF 5.5.4 after noting that no SNTP service is started. The current build has `CONFIG_MBEDTLS_HAVE_TIME_DATE` disabled, which the installed Kconfig states causes X.509 validity timestamps to be ignored. | Missing SNTP is not the blocker for this image; no speculative time-sync code added |
| 2026-07-22 16:58 | R4 diagnostic boundary | No `/dev/ttyACM*` or `/dev/ttyUSB*` controller is currently attached to the brain. | Exact body-side DNS/TLS/startup error cannot be distinguished until a USB serial log is available |
| 2026-07-22 17:13 | Owner decision | Owner shelved Cloudflare as the primary robot transport because local camera, audio, command, and feedback traffic should stay on local WiFi. | Cloudflare R4/R5 work stopped; local LAN stabilization selected |
| 2026-07-22 17:13 | Relay shutdown | Sent an interrupt to the supervised connector. Cloudflared closed all four edge connections, stopped its metrics server, and exited with status 0. | Relay stopped cleanly; gateway and dashboard left running |
| 2026-07-22 17:15 | Local addressing | Confirmed brain WiFi `wlo1` is connected at `192.168.0.44/24` with MAC `FC:77:74:C8:19:F5`. Avahi is active, but `DNDIY.local` currently resolves over IPv4 to Docker address `172.17.0.1`. | Recommend CenturyLink DHCP reservation for `192.168.0.44`; reject current mDNS name as unsafe for the robot |
| 2026-07-22 17:19 | Shutdown verification | Confirmed no `cloudflared` process remains and the public relay returns 530. Confirmed the local robot listener remains on `0.0.0.0:8790` and dashboard remains loopback-only on `127.0.0.1:8791`. | Shelving complete; local gateway service preserved |

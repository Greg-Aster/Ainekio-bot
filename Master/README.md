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

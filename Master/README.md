# Master

This folder contains remote brain-side code. It does not run on the physical
robot.

- `gateway/server/` owns the brain side of the protocol-v1 WebSocket.
- `gateway/dashboard/` owns the authenticated local operator interface.
- `gateway/environment_adapter/` owns the authenticated full-duplex environment
  endpoint and semantic command translation.
- `gateway/security.py` owns bounded dashboard-verifier and robot-token stores.

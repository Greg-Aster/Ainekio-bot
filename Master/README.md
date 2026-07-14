# Master

This folder contains remote brain-side code. It does not run on the physical
robot.

- `gateway/server/` owns the brain side of the protocol-v1 WebSocket.
- `gateway/dashboard/` owns the authenticated local operator interface.
- `gateway/bridge_client/` owns MetaHuman environment-stream translation.
- `gateway/security.py` owns bounded dashboard-verifier and robot-token stores.

# Ainekio Gateway

The gateway owns the brain side of the single protocol-v1 robot WebSocket. The
local stub currently authenticates a body `hello`, assigns a new epoch, sends
`welcome`, assigns strictly increasing command sequences, and records command
lifecycle responses. It exists so the body emulator can be tested without
MetaHuman OS running.

Run the local stub with a development-only token supplied through the
environment:

```sh
export AINEKIO_ROBOT_TOKEN='local-development-token'
PYTHONPATH=Master:Slave/software \
  python3 -m gateway.server --commands stand,walk,neutral
```

The later production gateway and MetaHuman `bridge_client` will extend this
owner. The old motion adapter under `Emulator/legacy/` remains a simulator-only
development path and is not part of the robot deployment transport.

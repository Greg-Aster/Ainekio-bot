# Ainekio Gateway

The gateway owns the brain side of each protocol-v1 robot WebSocket. Production
mode authenticates robot sessions, assigns epochs and command sequences, tracks
command lifecycle results, and serves the password-protected local operations
dashboard. Robot tokens, the dashboard password verifier, and the bounded audit
log live under the ignored `build/gateway/` runtime directory by default.

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

The old motion adapter under `Emulator/legacy/` remains a simulator-only
development path and is not part of the robot deployment transport.

To connect the gateway to MetaHuman OS, configure the same
`MH_ENVIRONMENT_BRIDGE_TOKEN` in MetaHuman's `.env` and start the gateway with
the following environment:

```sh
export MH_ENVIRONMENT_BRIDGE_TOKEN='shared-metahuman-bridge-token'
PYTHONPATH=Master:Slave/software python3 -m gateway.server \
  --metahuman-url http://127.0.0.1:4321
```

The token is sent only as a Bearer credential to the existing observation,
action-stream, and result endpoints.

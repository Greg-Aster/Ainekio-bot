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

To expose the generic environment adapter, configure a dedicated adapter token:

```sh
export AINEKIO_ENVIRONMENT_ADAPTER_TOKEN='shared-environment-adapter-token'
PYTHONPATH=Master:Slave/software python3 -m gateway.server
```

The endpoint is `ws://127.0.0.1:8790/environment`. The connecting environment
agent authenticates in its first protocol message. Ainekio does not contain a
MetaHuman URL or call MetaHuman APIs directly.

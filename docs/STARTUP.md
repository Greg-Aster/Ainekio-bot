# Restarting Body Control and remote MetaHuman OS

Use this routine for an already configured installation where one computer runs
Ainekio Body Control and another runs MetaHuman OS. Existing pairing, passwords,
and connection settings are retained across shutdowns.

## Check the network

Connect both computers to the configured network. If the bridge uses WireGuard,
start the existing VPN connection before expecting the remote bridge to connect.
An enabled `wg-quick` system service starts at boot; installing WireGuard tools
alone does not enable a tunnel.

LAN testing uses the configured local address of the MetaHuman computer. Internet
operation needs a reachable VPN endpoint, the appropriate UDP forwarding and
firewall configuration, and a test from a separate network. A successful LAN test
does not establish internet reachability.

## Start MetaHuman on its computer

Open a terminal on the MetaHuman computer. From its repository root, run:

```bash
./start.sh
```

Leave the terminal open. The normal launcher starts the web server and its
configured background services. An app-only launch starts the web application
without starting all those services.

For Body Control on another computer, select **Environment Bridge Remote** in
MetaHuman's Agent Monitor. Starting that connection saves the startup choice and
stops the Local bridge. The Remote bridge uses its saved SSH or Cloudflare route.
For SSH over WireGuard, its SSH destination is the Body Control computer's VPN
address or an SSH alias configured for that address.

The MetaHuman computer initiates this connection back to Body Control. The web
portal's address and the robot bridge's transport are separate settings.

You can run the same launcher from an SSH terminal connected to the MetaHuman
computer. Keep that terminal open for the foreground launcher.

## Start Body Control on its computer

In a separate terminal on the Body Control computer, run this from the Ainekio
repository root:

```bash
./Master/start-physical-gateway.sh
```

Reuse the saved dashboard connection choice if prompted. The launcher uses the
repository's Python environment and saved configuration. Leave the terminal open.
Turn on the paired robot if it is off; it can reconnect as services become
available.

Open Body Control in a browser on that same computer:

<http://127.0.0.1:8791/>

Open MetaHuman using its configured web address. When browsing on the MetaHuman
computer itself, the default local address is:

<http://127.0.0.1:4321/>

Use the existing logins. Confirm the robot is online in Body Control and that
MetaHuman's Remote Environment Bridge is connected. A reachable dashboard alone
does not establish a live robot connection.

## Check a WireGuard installation

For a tunnel named `wg-robot`, run on each computer:

```bash
systemctl is-active wg-quick@wg-robot.service
```

The expected result is `active`. Check peer reachability with `ping` using the
other computer's configured VPN address. If the link fails after a reboot, check
both machines' network connections and whether the configured endpoint address
has changed.

If a launcher reports that its server is already running, use the existing
instance. The [gateway reference](../Master/gateway/README.md) describes installed
service management, pairing, and connection settings.

## Stop the system

Press **Ctrl+C** in the Body Control terminal to stop its gateway. Press
**Ctrl+C** in the normal MetaHuman launcher terminal to stop MetaHuman and its
managed background services. An independently managed VPN remains controlled by
the operating system.

Keep private keys, passwords, tunnel credentials, and installation-specific
configuration in their existing local storage rather than in this guide.

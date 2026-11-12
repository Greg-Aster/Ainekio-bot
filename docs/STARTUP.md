# Starting Body Control and Remote Ainekio OS

Use this runbook for a configured installation where one host runs **Ainekio Body Control** (such as a Radxa Q6A or local workstation) and the same or another host runs **[Ainekio OS](https://github.com/Greg-Aster/ainekio-os)**. Saved pairing tokens, dashboard settings, and calibration persist across restarts.

## 1. Verify Local Inference (`llama-cpp.service`)

Each host that runs local model inference uses one shared native `llama-cpp.service` instance; see [Shared `llama.cpp` hosting](https://github.com/Greg-Aster/ainekio-os/blob/main/docs/robot/SYSTEM_ARCHITECTURE.md#shared-llamacpp-hosting).

- When Ainekio OS and Body Control run on the same host, both attach to that host's `127.0.0.1:8080` listener using separate model aliases and request-scoped LoRA scales.
- In a two-computer setup, the Body Control host's Freestyle generator (`ainekio-freestyle-api.service`) uses its own local `llama-cpp.service` (or configured SSH Big Brother endpoint) independently of desktop inference.
- Check service state on the relevant host:
  ```bash
  systemctl --user status llama-cpp.service
  ```
- Stopping Ainekio OS or Body Control leaves `llama-cpp.service` running.

## 2. Check Network and Optional VPN

Connect both hosts to the configured LAN or robot Wi-Fi hotspot. When bridging across networks over WireGuard, confirm the tunnel is active before expecting remote bridge connection:

```bash
systemctl is-active wg-quick@wg-robot.service
```

Verify peer reachability with `ping` against the peer's VPN address. LAN reachability does not prove remote tunnel reachability across separate networks.

## 3. Start Ainekio OS

From the `ainekio-os` repository root:

```bash
./start.sh
```

Open the web interface (`http://127.0.0.1:4321/` locally) and confirm **Environment Bridge** is running in **Agent Monitor**:
- Enable **Follow the same robot across saved hosts** under **Body connection** and select the paired robot ID once to follow it across saved Local, SSH, or Cloudflare routes.
- Manual host mode connects strictly to the selected endpoint (`ws://127.0.0.1:8790/environment` locally, or forwarded loopback over SSH/Cloudflare).
- Disconnected speech or transcription failures surface directly in the conversation feed and Body Control status banner.

## 4. Start Physical Body Control

From the `Ainekio-bot` repository root on the Body Control host:

```bash
./Master/start-physical-gateway.sh
```

- On interactive startup, select **This computer**, **LAN / Wi-Fi**, or **Cloudflare** within 10 seconds, or press Enter to reuse the saved choice in `build/gateway/physical/dashboard-connection.json`.
- Open the operator dashboard (`http://127.0.0.1:8791/` by default). Dashboard authentication uses the saved password verifier unless `AINEKIO_DASHBOARD_NO_LOGIN=1` is explicitly set for a trusted local/hotspot display.
- Power on the paired robot. Confirm the robot appears **Online** in the header selector and the bridge banner reports **Ainekio OS bridge connected** (`MetaHuman control` enabled when embodied cognitive commands should execute).

## 5. Stop Services

- Stop physical Body Control with `./Master/stop-physical-gateway.sh` or **Ctrl+C** in its foreground terminal.
- Stop Ainekio OS and its managed services with `./stop.sh` or **Ctrl+C** in its launcher terminal.
- Keep pairing tokens, dashboard verifiers, VPN keys, and tunnel credentials in ignored local runtime storage (`build/gateway/` or `~/.config/ainekio/`), never in tracked files.

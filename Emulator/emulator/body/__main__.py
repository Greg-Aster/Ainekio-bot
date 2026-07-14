from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from emulator.backends.sesame import SesameMotionBackend

from .calibration import CalibrationStore
from .client import BodyClientConfig, ProtocolV1BodyClient
from .core import PortableCore
from .host_media import AlsaMicrophoneSource, AlsaSpeakerSink, WebcamCameraSource
from .session import BodySession
from emulator.faults import EmulatorFaultController, start_fault_control_server


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Ainekio protocol-v1 body emulator.")
    parser.add_argument("--endpoint", default="ws://127.0.0.1:8790/robot")
    parser.add_argument("--robot-id", default="ainekio-emulator-01")
    parser.add_argument("--firmware-version", default="0.1.0-host")
    parser.add_argument("--shim-url", default="http://127.0.0.1:8788")
    parser.add_argument("--core-library", type=Path)
    parser.add_argument(
        "--calibration-file",
        type=Path,
        default=Path("build/emulator/calibration-v1.json"),
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--webcam-device")
    parser.add_argument("--alsa-capture-device")
    parser.add_argument("--alsa-playback-device")
    parser.add_argument("--simulated-vbat", type=float, default=8.0)
    parser.add_argument("--media-kib-per-second", type=int, default=512)
    parser.add_argument("--fault-host", default="127.0.0.1")
    parser.add_argument("--fault-port", type=int, default=8792)
    parser.add_argument("--no-fault-server", action="store_true")
    return parser


async def _run(args: argparse.Namespace, token: str) -> None:
    faults = EmulatorFaultController(battery_volts=args.simulated_vbat)
    fault_server = None
    fault_thread = None
    if not args.no_fault_server:
        fault_server, fault_thread = start_fault_control_server(
            args.fault_host, args.fault_port, faults
        )
        print(
            f"Ainekio emulator faults: http://{args.fault_host}:{fault_server.server_address[1]}"
        )
    try:
        with PortableCore(args.core_library) as core:
            session = BodySession(
                core,
                SesameMotionBackend(args.shim_url),
                CalibrationStore(args.calibration_file),
                camera_source=(
                    WebcamCameraSource(args.webcam_device)
                    if args.webcam_device
                    else None
                ),
                microphone_source=(
                    AlsaMicrophoneSource(args.alsa_capture_device)
                    if args.alsa_capture_device
                    else None
                ),
                speaker_sink=(
                    AlsaSpeakerSink(args.alsa_playback_device)
                    if args.alsa_playback_device
                    else None
                ),
                media_bytes_per_second=args.media_kib_per_second * 1024,
                faults=faults,
            )
            client = ProtocolV1BodyClient(
                BodyClientConfig(
                    endpoint=args.endpoint,
                    robot_id=args.robot_id,
                    auth_token=token,
                    firmware_version=args.firmware_version,
                ),
                session,
                faults,
            )
            if args.once:
                await client.run_once()
            else:
                await client.run_forever()
    finally:
        if fault_server is not None:
            await asyncio.to_thread(fault_server.shutdown)
            fault_server.server_close()
        if fault_thread is not None:
            fault_thread.join(timeout=2.0)


def main() -> int:
    args = _parser().parse_args()
    token = os.environ.get("AINEKIO_ROBOT_TOKEN")
    if not token:
        raise SystemExit("AINEKIO_ROBOT_TOKEN must be set; tokens are not stored in the repo")
    asyncio.run(_run(args, token))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORT_DIRECTORY = ROOT / "build" / "acceptance"
CORE_BUILD_DIRECTORY = REPORT_DIRECTORY / "core"
REPORT_PATH = REPORT_DIRECTORY / "a-series.json"

for path in (ROOT, ROOT / "Emulator", ROOT / "Master", ROOT / "Slave" / "software"):
    sys.path.insert(0, str(path))


@dataclass(frozen=True)
class AcceptanceCase:
    description: str
    evidence: tuple[str, ...]


PY = "python:Emulator.tests."
CASES = {
    "A1": AcceptanceCase(
        "Authenticated body connection; wrong token closes 4001.",
        (
            PY + "test_websocket_integration.WebSocketIntegrationTests.test_body_initiates_authenticated_session_and_completes_motion",
            PY + "test_websocket_integration.WebSocketIntegrationTests.test_wrong_token_is_rejected",
        ),
    ),
    "A2": AcceptanceCase(
        "Command lifecycles terminate once; stale sequences reject.",
        (
            PY + "test_session.BodySessionTests.test_movement_acks_then_completes",
            PY + "test_portable_core.PortableCoreTests.test_accepts_movement_and_rejects_duplicate_sequence",
            PY + "test_golden_fixtures.GoldenFixtureConsumptionTests.test_emulator_consumes_every_brain_to_body_valid_fixture",
        ),
    ),
    "A3": AcceptanceCase(
        "Disconnect enters failsafe and reconnect resets epoch without replay.",
        (
            PY + "test_websocket_integration.WebSocketIntegrationTests.test_disconnect_mid_motion_fails_safe_and_reconnect_resets_epoch",
            PY + "test_session.BodySessionTests.test_new_epoch_cancels_old_work_and_resets_sequence",
        ),
    ),
    "A4": AcceptanceCase(
        "E-stop preempts motion, cancels it, and preserves detach semantics.",
        (
            PY + "test_session.BodySessionTests.test_stop_cancels_active_movement_and_detaches",
            PY + "test_session.BodySessionTests.test_face_and_say_complete_without_reattaching_after_stop",
            PY + "test_websocket_integration.WebSocketIntegrationTests.test_stop_bypasses_saturated_control_queue",
        ),
    ),
    "A5": AcceptanceCase(
        "Calibration is mode-gated, bounded, coalesced, and persisted only on save.",
        (
            PY + "test_session.BodySessionTests.test_calibration_is_mode_gated_and_persists_only_on_save",
            PY + "test_session.BodySessionTests.test_calibration_limits_and_idle_timeout_are_enforced",
            PY + "test_session.BodySessionTests.test_calibration_burst_acks_all_and_coalesces_to_latest_at_20hz",
        ),
    ),
    "A6": AcceptanceCase(
        "PCM/VAD reaches the gateway transcriber and TTS completes at a null sink.",
        (
            PY + "test_gateway_service.GatewayServiceTests.test_vad_pcm_reaches_stubbed_transcriber",
            PY + "test_media.BodyMediaTests.test_vad_opens_streams_pcm_and_closes_after_hangover",
            PY + "test_session.BodySessionTests.test_tts_frames_complete_in_order_after_end",
        ),
    ),
    "A7": AcceptanceCase(
        "Camera cadence and throttle drop camera before control or microphone.",
        (
            PY + "test_media.BodyMediaTests.test_camera_stream_respects_state_and_counts_oversize_drop",
            PY + "test_media.BodyMediaTests.test_bandwidth_pressure_drops_camera_before_microphone",
        ),
    ),
    "A8": AcceptanceCase(
        "Battery debounce, warning lock, cutoff, and recovery work during walking.",
        (
            PY + "test_battery.BatteryMonitorTests.test_sample_sets_are_bounded_and_thresholds_need_three_readings",
            PY + "test_session.BodySessionTests.test_battery_warning_locks_movement_but_allows_neutral",
            PY + "test_session.BodySessionTests.test_battery_cutoff_preempts_continuous_walk_and_recovers",
        ),
    ),
    "A9": AcceptanceCase(
        "Tether profile enforces media caps.",
        (
            PY + "test_media.BodyMediaTests.test_tether_rejects_streaming_and_open_mic_but_allows_vga_snap",
            PY + "test_gateway_service.GatewayServiceTests.test_gateway_refuses_out_of_profile_media_before_assigning_sequence",
        ),
    ),
    "A10": AcceptanceCase(
        "Malformed input survives; overflow closes without delaying stop.",
        (
            PY + "test_session.BodySessionTests.test_malformed_input_does_not_end_the_session",
            PY + "test_golden_fixtures.GoldenFixtureConsumptionTests.test_emulator_rejects_every_invalid_fixture_without_execution",
            PY + "test_websocket_integration.WebSocketIntegrationTests.test_stop_bypasses_saturated_control_queue",
        ),
    ),
    "A11": AcceptanceCase(
        "Duplicate connection replaces the old epoch and cancels unfinished work.",
        (
            PY + "test_gateway_service.GatewayServiceTests.test_duplicate_connection_cancels_old_epoch_and_closes_4000",
            PY + "test_websocket_integration.WebSocketIntegrationTests.test_new_authenticated_socket_replaces_old_session",
        ),
    ),
    "A12": AcceptanceCase(
        "E-stop remains below 100 ms with a max JPEG and saturated control queue.",
        (
            PY + "test_websocket_integration.WebSocketIntegrationTests.test_stop_bypasses_saturated_control_queue",
        ),
    ),
    "A13": AcceptanceCase(
        "Open microphone gate is rejected under tether.",
        (
            PY + "test_media.BodyMediaTests.test_tether_rejects_streaming_and_open_mic_but_allows_vga_snap",
        ),
    ),
    "A14": AcceptanceCase(
        "Provisioning, atomic replacement, reset preservation, and rotation pass.",
        (
            "ctest:ainekio_provisioning_tests",
            "ctest:ainekio_config_store_tests",
            PY + "test_gateway_service.GatewayServiceTests.test_token_revocation_closes_active_socket_and_rejects_reconnect",
        ),
    ),
    "A15": AcceptanceCase(
        "Dashboard auth, CSRF, verifier storage, and rate limiting pass.",
        (
            PY + "test_gateway_dashboard.GatewayDashboardTests.test_session_and_csrf_are_required_for_commands",
            PY + "test_gateway_dashboard.GatewayDashboardTests.test_login_is_rate_limited_after_five_failures",
            PY + "test_gateway_security.GatewaySecurityTests.test_dashboard_file_contains_verifier_not_plaintext",
        ),
    ),
    "A16": AcceptanceCase(
        "Shared valid, invalid, wrap, and truncation fixtures are consumed.",
        (
            "suite:protocol",
            "ctest:ainekio_control_fixture_tests",
            "ctest:ainekio_binary_fixture_tests",
            PY + "test_golden_fixtures.GoldenFixtureConsumptionTests.test_emulator_consumes_every_brain_to_body_valid_fixture",
        ),
    ),
    "A17": AcceptanceCase(
        "Offline and over-age gateway actions expire before sequence assignment.",
        (
            PY + "test_gateway_service.GatewayServiceTests.test_freshness_is_checked_before_sequence_assignment",
            PY + "test_gateway_service.GatewayServiceTests.test_wrong_token_and_offline_actions_are_rejected",
        ),
    ),
    "A18": AcceptanceCase(
        "Speaker order is preserved; congestion cancels the whole utterance.",
        (
            PY + "test_session.BodySessionTests.test_speaker_queue_overflow_cancels_whole_utterance",
            PY + "test_websocket_integration.WebSocketIntegrationTests.test_tts_end_cannot_overtake_earlier_speaker_frame",
            PY + "test_gateway_service.GatewayServiceTests.test_tts_api_preserves_start_frames_end_order",
        ),
    ),
    "A19": AcceptanceCase(
        "Token revocation closes 4001 and rejects reconnect.",
        (
            PY + "test_gateway_service.GatewayServiceTests.test_token_revocation_closes_active_socket_and_rejects_reconnect",
        ),
    ),
    "A20": AcceptanceCase(
        "Sleep echoes duration, sends final status, closes 1000, and reconnects on schedule.",
        (
            PY + "test_websocket_integration.WebSocketIntegrationTests.test_sleep_lifecycle_closes_cleanly_and_returns_scaled_delay",
        ),
    ),
    "A21": AcceptanceCase(
        "Camera metadata and counters expose stream position and drops.",
        (
            PY + "test_media.BodyMediaTests.test_camera_counter_wraps_without_affecting_lifecycle",
            PY + "test_media.BodyMediaTests.test_bandwidth_pressure_drops_camera_before_microphone",
        ),
    ),
    "A22": AcceptanceCase(
        "TTS start/end/cancel, orphan, stop, and say-busy lifecycles pass.",
        (
            PY + "test_session.BodySessionTests.test_tts_frames_complete_in_order_after_end",
            PY + "test_session.BodySessionTests.test_tts_orphan_event_is_once_per_burst",
            PY + "test_session.BodySessionTests.test_stop_cancels_speaker_playback",
            PY + "test_session.BodySessionTests.test_tts_selects_talk_face_restores_and_blocks_say",
        ),
    ),
    "A23": AcceptanceCase(
        "Idle/doze intent and media-setting state matrix passes.",
        (
            PY + "test_session.BodySessionTests.test_settings_do_not_reset_idle_timer_and_intent_exits_doze",
            PY + "test_session.BodySessionTests.test_profiles_states_and_settings_use_portable_core",
        ),
    ),
    "A24": AcceptanceCase(
        "Gateway freshness uses monotonic time across wall-clock jumps.",
        (
            PY + "test_gateway_service.GatewayServiceTests.test_wall_clock_jump_does_not_change_monotonic_freshness",
            PY + "test_environment_adapter.EnvironmentAdapterTests.test_fresh_control_uses_local_monotonic_receipt",
        ),
    ),
    "A25": AcceptanceCase(
        "Environment actions remain semantic and reject raw servo-like commands.",
        (
            PY + "test_environment_adapter.EnvironmentAdapterTests.test_translation_emits_only_bounded_semantic_commands",
        ),
    ),
    "A26": AcceptanceCase(
        "Logical joint ids, labels, versions, assets, dashboard, and limits agree.",
        (
            PY + "test_assets.AssetTests.test_joint_contract_rejects_drift_before_asset_execution",
            PY + "test_assets.AssetTests.test_logical_targets_apply_center_and_invert_before_limits",
            PY + "test_gateway_dashboard.GatewayDashboardTests.test_calibration_diagnostics_use_named_joints_and_calibration_messages",
            "ctest:ainekio_settings_tests",
        ),
    ),
    "A27": AcceptanceCase(
        "All 19 Sesame motions match deterministic converted fixtures and remain safe.",
        (
            PY + "test_assets.AssetTests.test_all_seed_motions_and_faces_load",
            PY + "test_assets.AssetTests.test_converter_output_is_deterministic",
            PY + "test_session.BodySessionTests.test_every_seed_motion_is_limit_checked_and_stop_preemptible",
            "ctest:ainekio_asset_tests",
        ),
    ),
    "A28": AcceptanceCase(
        "Face modes, fps, blink schedule, talk face, and failure isolation pass.",
        (
            PY + "test_assets.AssetTests.test_face_modes_are_deterministic",
            PY + "test_assets.DisplayTimingTests.test_face_fps_advances_by_elapsed_ticks_without_drift",
            PY + "test_session.BodySessionTests.test_idle_display_blinks_with_seeded_bounded_double_blink",
            PY + "test_session.BodySessionTests.test_tts_selects_talk_face_restores_and_blocks_say",
            PY + "test_session.BodySessionTests.test_display_failure_never_fails_face_command",
        ),
    ),
    "A29": AcceptanceCase(
        "Browser manual controls are semantic, bounded, and release-to-stop.",
        ("browser:dashboard-controls",),
    ),
    "A30": AcceptanceCase(
        "Named-joint diagnostics, neutral, detach, limits, and atomic save pass.",
        (
            PY + "test_gateway_dashboard.GatewayDashboardTests.test_calibration_diagnostics_use_named_joints_and_calibration_messages",
            PY + "test_session.BodySessionTests.test_calibration_is_mode_gated_and_persists_only_on_save",
            "ctest:ainekio_settings_tests",
        ),
    ),
}


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.outcomes: dict[str, dict[str, str]] = {}

    def addSuccess(self, test: unittest.case.TestCase) -> None:
        super().addSuccess(test)
        self.outcomes[test.id()] = {"status": "passed"}

    def addFailure(
        self,
        test: unittest.case.TestCase,
        err: tuple[type[BaseException], BaseException, object],
    ) -> None:
        super().addFailure(test, err)
        self.outcomes[test.id()] = {
            "status": "failed",
            "detail": self._exc_info_to_string(err, test),
        }

    def addError(
        self,
        test: unittest.case.TestCase,
        err: tuple[type[BaseException], BaseException, object],
    ) -> None:
        super().addError(test, err)
        self.outcomes[test.id()] = {
            "status": "failed",
            "detail": self._exc_info_to_string(err, test),
        }

    def addSkip(self, test: unittest.case.TestCase, reason: str) -> None:
        super().addSkip(test, reason)
        self.outcomes[test.id()] = {"status": "failed", "detail": f"skipped: {reason}"}


def run_python_suite(start: Path, top: Path) -> tuple[bool, dict[str, dict[str, str]], str]:
    suite = unittest.defaultTestLoader.discover(
        str(start),
        pattern="test_*.py",
        top_level_dir=str(top),
    )
    output = io.StringIO()
    result = unittest.TextTestRunner(
        stream=output,
        verbosity=1,
        resultclass=RecordingResult,
    ).run(suite)
    assert isinstance(result, RecordingResult)
    return result.wasSuccessful(), result.outcomes, output.getvalue()


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        str(path)
        for path in (ROOT / "Emulator", ROOT / "Master", ROOT / "Slave" / "software")
    )
    return subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def run_ctest() -> tuple[bool, dict[str, dict[str, str]], str]:
    REPORT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    commands = (
        [
            "cmake",
            "-S",
            str(ROOT / "Slave" / "software" / "core"),
            "-B",
            str(CORE_BUILD_DIRECTORY),
            "-DCMAKE_BUILD_TYPE=Debug",
        ],
        ["cmake", "--build", str(CORE_BUILD_DIRECTORY), "--parallel"],
    )
    logs: list[str] = []
    for command in commands:
        completed = run_command(command)
        logs.append(completed.stdout + completed.stderr)
        if completed.returncode != 0:
            return False, {}, "\n".join(logs)
    junit = REPORT_DIRECTORY / "ctest.xml"
    completed = run_command(
        [
            "/usr/bin/ctest",
            "--test-dir",
            str(CORE_BUILD_DIRECTORY),
            "--output-on-failure",
            "--output-junit",
            str(junit),
        ]
    )
    logs.append(completed.stdout + completed.stderr)
    outcomes: dict[str, dict[str, str]] = {}
    if junit.exists():
        for test_case in ET.parse(junit).getroot().iter("testcase"):
            name = test_case.attrib.get("name", "unknown")
            failure = test_case.find("failure")
            if failure is None:
                outcomes[name] = {"status": "passed"}
            else:
                outcomes[name] = {
                    "status": "failed",
                    "detail": failure.text or "ctest failure",
                }
    return completed.returncode == 0, outcomes, "\n".join(logs)


def run_browser() -> tuple[bool, dict[str, object], str]:
    completed = run_command(
        ["node", str(ROOT / "Emulator" / "tools" / "dashboard_browser_acceptance.mjs")]
    )
    detail = completed.stdout + completed.stderr
    payload: dict[str, object] = {}
    if completed.returncode == 0:
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            payload = {"output": completed.stdout.strip()}
    return completed.returncode == 0, payload, detail


def main() -> int:
    REPORT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    evidence: dict[str, dict[str, str]] = {}
    logs: dict[str, str] = {}

    emulator_ok, emulator_results, logs["emulator"] = run_python_suite(
        ROOT / "Emulator" / "tests",
        ROOT,
    )
    evidence.update(
        {f"python:{test_id}": outcome for test_id, outcome in emulator_results.items()}
    )
    evidence["suite:emulator"] = {
        "status": "passed" if emulator_ok else "failed"
    }

    protocol_ok, protocol_results, logs["protocol"] = run_python_suite(
        ROOT / "Slave" / "software" / "tests" / "protocol",
        ROOT / "Slave" / "software" / "tests" / "protocol",
    )
    evidence.update(
        {f"python:{test_id}": outcome for test_id, outcome in protocol_results.items()}
    )
    evidence["suite:protocol"] = {
        "status": "passed" if protocol_ok else "failed"
    }

    ctest_ok, ctest_results, logs["ctest"] = run_ctest()
    evidence.update(
        {f"ctest:{test_id}": outcome for test_id, outcome in ctest_results.items()}
    )
    evidence["suite:ctest"] = {"status": "passed" if ctest_ok else "failed"}

    browser_ok, browser_payload, logs["browser"] = run_browser()
    evidence["browser:dashboard-controls"] = {
        "status": "passed" if browser_ok else "failed"
    }

    case_results: dict[str, dict[str, object]] = {}
    for case_id, case in CASES.items():
        missing = [item for item in case.evidence if item not in evidence]
        failed = [
            item
            for item in case.evidence
            if item in evidence and evidence[item]["status"] != "passed"
        ]
        case_results[case_id] = {
            "status": "passed" if not missing and not failed else "failed",
            "description": case.description,
            "evidence": list(case.evidence),
            "missing": missing,
            "failed": failed,
        }

    gates = {
        "emulator": emulator_ok,
        "protocol": protocol_ok,
        "portable_c": ctest_ok,
        "dashboard_browser": browser_ok,
    }
    passed_cases = sum(
        result["status"] == "passed" for result in case_results.values()
    )
    all_passed = all(gates.values()) and passed_cases == len(CASES)
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "specification": "docs/Ainekio - System Specification v1.0.docx",
        "result": "passed" if all_passed else "failed",
        "summary": {"passed": passed_cases, "total": len(CASES)},
        "gates": gates,
        "cases": case_results,
        "evidence": evidence,
        "browser": browser_payload,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(
        f"A-series acceptance: {'PASS' if all_passed else 'FAIL'} "
        f"({passed_cases}/{len(CASES)})"
    )
    print(f"Report: {REPORT_PATH}")
    print(
        "Gates: "
        + ", ".join(f"{name}={'pass' if ok else 'fail'}" for name, ok in gates.items())
    )
    if not all_passed:
        for name, ok in gates.items():
            if not ok:
                log_name = "browser" if name == "dashboard_browser" else name
                print(f"\n[{name}]\n{logs[log_name][-5000:]}")
        for case_id, result in case_results.items():
            if result["status"] != "passed":
                print(
                    f"{case_id}: missing={result['missing']} failed={result['failed']}"
                )
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

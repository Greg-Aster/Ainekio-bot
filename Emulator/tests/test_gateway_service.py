from __future__ import annotations

import asyncio
import io
import json
import struct
import threading
import unittest
import wave
from collections.abc import Mapping
from time import monotonic

import websockets

from emulator.body import BodySession, PortableCore
from emulator.body.client import BodyClientConfig, HandshakeRejected, ProtocolV1BodyClient
from gateway.server.service import (
    ActionExpiredError,
    GatewayError,
    GatewayClock,
    GatewayConnection,
    GatewayService,
    GatewayServiceConfig,
    RobotOfflineError,
)
from gateway.plugins import AudioTranscriptPlugin, CameraFramePlugin
from protocol.control_v1 import CAMERA_PROFILES_FEATURE, CAMERA_ADAPTIVE_FEATURE, COMMAND_DEADLINE_FEATURE
from emulator.body.media import FixtureCameraSource, QueueMicrophoneSource
from Emulator.tests.support import build_core_library


class ImmediateMotionBackend:
    async def execute(self, message: Mapping[str, object], *, session_id: str) -> None:
        return None

    async def stop(self, sequence: int, *, session_id: str) -> None:
        return None


class LifecycleSocket:
    def __init__(self, *, clock_ms=10000, acknowledge=False):
        self.closed = False
        self.sent = []
        self.incoming = asyncio.Queue()
        self.incoming.put_nowait(json.dumps({'t': 'hello', 'ver': 1, 'fw': 'fixture',
            'id': 'fixture-body', 'auth': 'test', 'features': [COMMAND_DEADLINE_FEATURE], 'clock_ms': clock_ms}))
        self.welcomed = asyncio.Event()
        self.pong = asyncio.Event()
        self.close_started = asyncio.Event()
        self.close_release = None
        self.acknowledge = acknowledge

    async def recv(self):
        value = await self.incoming.get()
        if value is None:
            raise websockets.exceptions.ConnectionClosedOK(None, None)
        return value

    async def send(self, raw):
        message = json.loads(raw)
        self.sent.append(message)
        if message['t'] == 'welcome':
            self.welcomed.set()
        if message['t'] == 'pong':
            self.pong.set()
        if self.acknowledge and 'seq' in message:
            for kind in ['ack', 'done']:
                self.incoming.put_nowait(json.dumps({'t': kind, 'seq': message['seq']}))

    async def close(self, code=1000, reason=''):
        self.close_started.set()
        if self.close_release is not None:
            await self.close_release.wait()
        self.closed = True
        self.incoming.put_nowait(None)


class GatewayServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_speech_expiry_uses_pcm_duration_and_existing_heartbeat_cadence(self):
        now = [0.0]
        service = GatewayService(GatewayServiceConfig(tokens={'robot':'test'}, ping_interval_s=1), clock=lambda:now[0])
        service.set_external_speech('robot', 'first', True, duration_ms=5000)
        self.assertEqual(service.external_speech_remaining_ms('robot'), 7000)
        now[0] = 4.0
        self.assertEqual(service.external_speech_remaining_ms('robot'), 3000)
        now[0] = 6.0  # Playback process is still draining; no speech timeout.
        self.assertTrue(service.external_speech_active('robot'))
        self.assertEqual(service.external_speech_remaining_ms('robot'), 2000)
        service.set_external_speech('robot', 'replacement', True, duration_ms=10000)
        service.set_external_speech('robot', 'first', False)
        self.assertEqual(service.external_speech_remaining_ms('robot'), 12000)
        service.set_external_speech('robot', 'replacement', False)
        self.assertEqual(service.external_speech_remaining_ms('robot'), 0)

    async def test_dropped_resume_is_repeated_by_regular_heartbeat(self):
        service = GatewayService(GatewayServiceConfig(tokens={'robot':'test'}))
        class Socket:
            closed = False
            fail = False
            def __init__(self): self.sent = []
            async def send(self, raw):
                if self.fail: raise OSError('resume notification lost')
                self.sent.append(json.loads(raw))
        socket = Socket()
        connection = GatewayConnection(service, socket, 'robot', 1, model='v2-12servo')
        service._connections['robot'] = connection
        service.set_external_speech('robot', 'speech', True)
        await connection._external_speech_notification
        self.assertTrue(socket.sent[-1]['external_speech'])
        socket.fail = True
        service.set_external_speech('robot', 'speech', False)
        await connection._external_speech_notification
        self.assertIn('lost', connection.external_speech_error)
        socket.fail = False
        await connection._handle_control({'t':'ping'})
        self.assertEqual(socket.sent[-1], {'t':'pong', 'external_speech':False})
        self.assertIsNone(connection.external_speech_error)
        self.assertFalse(connection.pending)

    async def test_notification_failure_does_not_hold_host_capture_off(self):
        from gateway.plugins import AudioUtteranceAssembler
        service=GatewayService(GatewayServiceConfig(tokens={'robot':'test'}))
        class Socket:
            closed=False
            async def send(self,raw): raise OSError('link unavailable')
        connection=GatewayConnection(service,Socket(),'robot',1,model='v2-12servo')
        service._connections['robot']=connection
        captured=[];assembler=AudioUtteranceAssembler(captured.append)
        service.subscribe_external_speech(assembler.external_speech)
        service.set_external_speech('robot','one',True)
        await connection._external_speech_notification
        self.assertIn('link unavailable',connection.external_speech_error)
        service.set_external_speech('robot','one',False)
        self.assertNotIn(('robot',1),assembler._blocked)
        await connection._external_speech_notification
        from protocol.binary_helpers import MIC_PCM_FRAME_TYPE
        await assembler.handle_frame({'robot_id':'robot','epoch':1,'frame_type':MIC_PCM_FRAME_TYPE,'counter':5,'payload':bytes(640)})
        await assembler.handle_event({'robot_id':'robot','epoch':1,'t':'event','name':'vad_close'})
        self.assertEqual(len(captured),1)
        self.assertFalse(service.external_speech_active('robot'))

    async def test_external_speech_notification_never_waits_for_ack_and_uses_latest_state(self):
        service = GatewayService(GatewayServiceConfig(tokens={'robot':'test'}))
        class Socket:
            closed=False
            def __init__(self): self.sent=[]
            async def send(self,raw): self.sent.append(json.loads(raw))
        socket=Socket()
        connection=GatewayConnection(service,socket,'robot',1,model='v2-12servo')
        service._connections['robot']=connection
        await connection._send_lock.acquire()
        service.set_external_speech('robot','old',True)
        await asyncio.sleep(0)
        self.assertTrue(service.external_speech_active('robot'))
        self.assertFalse(connection.pending)
        service.set_external_speech('robot','new',True)
        service.set_external_speech('robot','old',False)
        self.assertTrue(service.external_speech_active('robot'))
        connection._send_lock.release()
        await connection._external_speech_notification
        self.assertTrue(socket.sent[-1]['external_speech'])
        self.assertNotIn('seq',socket.sent[-1])
        service.set_external_speech('robot','new',False)
        await connection._external_speech_notification
        self.assertFalse(socket.sent[-1]['external_speech'])
        self.assertFalse(connection.pending)

    async def test_external_speech_drops_microphone_but_not_camera_and_resumes_new_utterance(self):
        from protocol.binary_helpers import encode_binary_frame, MIC_PCM_FRAME_TYPE, CAMERA_JPEG_FRAME_TYPE
        service=GatewayService(GatewayServiceConfig(tokens={'robot':'test'}))
        class Socket:
            closed=False
            async def send(self,raw): pass
        connection=GatewayConnection(service,Socket(),'robot',1,model='v2-12servo')
        service._connections['robot']=connection
        frames=[];events=[]
        service.subscribe_frames(frames.append);service.subscribe_events(events.append)
        service.set_external_speech('robot','speech',True)
        await connection._handle_binary(encode_binary_frame(MIC_PCM_FRAME_TYPE,1,bytes(640)))
        await connection._handle_binary(encode_binary_frame(CAMERA_JPEG_FRAME_TYPE,1,b'\xff\xd8test\xff\xd9'))
        self.assertEqual(len(frames),1)
        self.assertEqual(frames[0]['frame_type'],CAMERA_JPEG_FRAME_TYPE)
        await connection._handle_control({'t':'event','name':'wake_word'})
        self.assertFalse(any(e.get('name')=='wake_word' for e in events))
        service.set_external_speech('robot','speech',False)
        await connection._external_speech_notification
        await connection._handle_binary(encode_binary_frame(MIC_PCM_FRAME_TYPE,2,bytes(640)))
        self.assertEqual(len(frames),2)
        await connection._handle_control({'t':'event','name':'vad_open'})
        await connection._handle_binary(encode_binary_frame(MIC_PCM_FRAME_TYPE,3,bytes(640)))
        self.assertEqual(len(frames),3)

    async def test_disconnect_preserves_protocol_failure_without_peer_close_reply(self):
        from websockets.frames import Close
        from websockets.exceptions import ConnectionClosedError, ProtocolError
        class FailedSocket(LifecycleSocket):
            async def recv(self):
                if not self.incoming.empty():
                    return await super().recv()
                raise ConnectionClosedError(None, Close(1002, "")) from ProtocolError("invalid opcode")
        service = GatewayService(GatewayServiceConfig(tokens={"fixture-body": "test"}))
        events = []
        service.subscribe_events(events.append)
        await service.handler(FailedSocket(), '/robot')
        closed = next(event for event in events if event.get('status') == 'disconnected')
        self.assertEqual(closed['close_code'], 1002)
        self.assertEqual(closed['close_reason'], 'invalid opcode')

    async def test_invalid_control_reports_owning_protocol_error_on_disconnect(self):
        service = GatewayService(GatewayServiceConfig(tokens={"fixture-body": "test"}))
        socket = LifecycleSocket()
        socket.incoming.put_nowait('{')
        events = []
        service.subscribe_events(events.append)
        await service.handler(socket, '/robot')
        closed = next(event for event in events if event.get('status') == 'disconnected')
        self.assertEqual(closed['close_code'], 1002)
        self.assertEqual(closed['close_reason'], 'malformed control frame: invalid JSON')

    async def test_named_motion_selection_is_per_robot_and_library_remains_explicit(self):
        from unittest.mock import AsyncMock
        service = GatewayService(GatewayServiceConfig(tokens={}))
        for robot in ("one", "two"):
            service._connections[robot] = GatewayConnection(service, LifecycleSocket(), robot, 1)
        service.queue_intent = AsyncMock(return_value=17)
        service.freestyle_motion = AsyncMock(return_value={"job_id": "model-motion"})
        service.motion_systems["one"] = "freestyle"
        self.assertEqual(await service.request_motion("stretch", robot_id="one"),
                         {"system": "freestyle", "jobId": "model-motion", "state": "submitted"})
        service.freestyle_motion.assert_awaited_once_with("one", "stretch", execute=True)
        service.queue_intent.assert_not_awaited()
        self.assertEqual(await service.request_motion("stretch", robot_id="two"),
                         {"system": "library", "sequence": 17})
        service.queue_intent.assert_awaited_once_with("emote", {"asset": "stretch"}, robot_id="two", received_at=None, on_sequence=None)
        service.motion_systems["one"] = "library"
        await service.request_motion("stand", robot_id="one")
        service.queue_intent.assert_awaited_with("stand", robot_id="one")
        self.assertEqual(service.freestyle_motion.await_count, 1)

    async def test_camera_chunks_deliver_audio_before_complete_image_and_preserve_metadata(self):
        from protocol.binary_helpers import encode_binary_frame, CAMERA_CHUNK_FRAME_TYPE, MIC_PCM_FRAME_TYPE
        service = GatewayService(GatewayServiceConfig(tokens={"robot": "test"}))
        frames = []
        async def received(frame):
            frames.append(frame)
        service.subscribe_frames(received)
        connection = GatewayConnection(service, LifecycleSocket(), "robot", 1)
        jpeg = b"\xff\xd8" + bytes(range(256)) * 40 + b"\xff\xd9"
        connection.camera_metadata = {"counter_base": 42, "origin": "request", "origin_id": 7}
        for offset in range(0, len(jpeg), 4083):
            chunk = struct.pack("<II", len(jpeg), offset) + jpeg[offset:offset+4083]
            await connection._handle_binary(encode_binary_frame(CAMERA_CHUNK_FRAME_TYPE, 42, chunk))
            await connection._handle_binary(encode_binary_frame(MIC_PCM_FRAME_TYPE, offset, bytes(640)))
            if offset + 4083 < len(jpeg):
                self.assertTrue(all(frame["frame_type"] == MIC_PCM_FRAME_TYPE for frame in frames))
        image = next(frame for frame in frames if frame["frame_type"] == 2)
        self.assertEqual(image["payload"], jpeg)
        self.assertEqual(image["camera_metadata"]["origin_id"], 7)
        self.assertEqual(connection.camera_frames_received, 1)
        self.assertEqual(len(frames), 4)
        self.assertIsNone(connection.camera_chunks)

    async def test_camera_chunks_do_not_cross_connections_or_publish_incomplete_images(self):
        from protocol.binary_helpers import encode_binary_frame, CAMERA_CHUNK_FRAME_TYPE
        service = GatewayService(GatewayServiceConfig(tokens={"robot": "test"}))
        frames = []
        async def received(frame):
            frames.append(frame)
        service.subscribe_frames(received)
        old = GatewayConnection(service, LifecycleSocket(), "robot", 1)
        new = GatewayConnection(service, LifecycleSocket(), "robot", 2)
        def chunk(counter, total, offset, data):
            return encode_binary_frame(CAMERA_CHUNK_FRAME_TYPE, counter, struct.pack("<II", total, offset) + data)
        await old._handle_binary(chunk(1, 6, 0, b"\xff\xd8"))
        await new._handle_binary(chunk(1, 6, 2, b"ab\xff\xd9"))
        self.assertEqual(frames, [])
        await new._handle_binary(chunk(2, 6, 0, b"\xff\xd8"))
        await new._handle_binary(chunk(2, 6, 3, b"b\xff\xd9"))
        self.assertEqual(frames, [])
        await new._handle_binary(chunk(3, 4, 0, b"\xff\xd8\xff\xd9"))
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["counter"], 3)
        self.assertEqual(frames[0]["epoch"], 2)

    async def test_calibration_readback_preserves_body_command_ownership(self):
        from protocol.control_v1 import BODY_CALIBRATION_FEATURE
        class Socket:
            closed=False
            async def send(self,raw):pass
        service=GatewayService(GatewayServiceConfig(tokens={'robot':'test'}))
        connection=GatewayConnection(service,Socket(),'robot',1,model='v2-12servo',features=(BODY_CALIBRATION_FEATURE,))
        connection.body_command_sequence=321
        connection.body_command={'t':'intent','name':'walk','seq':321}
        await connection.send_command({'t':'calibration','op':'get'},received_at=service.clock())
        self.assertEqual(connection.body_command_sequence,321)
        self.assertEqual(connection.body_command['name'],'walk')
        connection.cancel_pending()

    @classmethod
    def setUpClass(cls) -> None:
        cls.library_path = build_core_library()

    async def test_camera_metadata_is_matched_once_to_its_binary_frame(self):
        from protocol.binary_helpers import CAMERA_JPEG_FRAME_TYPE, encode_binary_frame
        service = GatewayService(GatewayServiceConfig(tokens={"robot": "test"}))
        connection = GatewayConnection(service, object(), "robot", 4)
        frames = []
        service.subscribe_frames(frames.append)
        await connection._handle_control({'t': 'cam_meta', 'res': 'VGA', 'fps': 1,
            'counter_base': 17, 'origin': 'request', 'origin_id': 31})
        await connection._handle_binary(encode_binary_frame(CAMERA_JPEG_FRAME_TYPE, 17, b'\xff\xd8jpeg\xff\xd9'))
        await connection._handle_binary(encode_binary_frame(CAMERA_JPEG_FRAME_TYPE, 18, b'\xff\xd8preview\xff\xd9'))
        self.assertEqual(frames[0]['camera_metadata']['origin_id'], 31)
        self.assertEqual(frames[0]['epoch'], 4)
        self.assertNotIn('camera_metadata', frames[1])
        await connection._handle_control({'t': 'cam_meta', 'res': 'VGA', 'fps': 1,
            'counter_base': 19, 'origin': 'request', 'origin_id': 32})
        await connection._handle_binary(encode_binary_frame(CAMERA_JPEG_FRAME_TYPE, 20, b'\xff\xd8other\xff\xd9'))
        self.assertNotIn('camera_metadata', frames[2])

    async def test_walking_feedback_does_not_change_leveling_or_motion(self):
        class Socket:
            closed = False
            def __init__(self): self.sent = []
            async def send(self, raw): self.sent.append(json.loads(raw))
        service = GatewayService(GatewayServiceConfig(tokens={"robot":"test"}))
        socket = Socket()
        connection = GatewayConnection(service, socket, "robot", 1, model="v2-12servo",
                                       features=("balance_control_v1", "walking_feedback_v1"))
        service._connections["robot"] = connection
        connection.body_command_sequence = 321
        task = asyncio.create_task(service.body_balance("walking", {"enabled":True}, robot_id="robot"))
        while not socket.sent: await asyncio.sleep(0)
        self.assertEqual(socket.sent[-1], {"t":"balance", "op":"walking", "enabled":True, "seq":1})
        await connection._handle_control({"t":"ack", "seq":1})
        reply = {"t":"balance_status", "seq":1, "enabled":False, "saved":True, "active":False,
                 "walking_enabled":True, "walking_saved":True}
        await connection._handle_control(reply)
        self.assertEqual(await task, reply)
        self.assertEqual(connection.body_command_sequence, 321)
        self.assertFalse(connection.last_balance["enabled"])

    async def test_balance_readback_preserves_motion_owner(self):
        class Socket:
            closed = False
            def __init__(self): self.sent = []
            async def send(self, raw): self.sent.append(json.loads(raw))
        service = GatewayService(GatewayServiceConfig(tokens={"robot": "test"}))
        socket = Socket()
        connection = GatewayConnection(service, socket, "robot", 1, model="v2-12servo",
                                       features=("balance_control_v1",))
        service._connections["robot"] = connection
        connection.body_command_sequence = 321
        connection.body_command_source = "manual"
        connection.body_command = {"t":"intent", "name":"walk", "seq":321}
        task = asyncio.create_task(service.body_balance("save", {"enabled":False}, robot_id="robot"))
        while not socket.sent: await asyncio.sleep(0)
        message = socket.sent[-1]
        self.assertEqual(message, {"t":"balance", "seq":1, "op":"save", "enabled":False})
        result = {"t":"balance_status", "seq":1, "enabled":False, "saved":True, "active":False}
        await connection._handle_control(result)  # Not a receipt before ACK.
        self.assertIsNone(connection.last_balance)
        await connection._handle_control({"t":"ack", "seq":1})
        self.assertFalse(task.done())
        await connection._handle_control({**result, "seq":999})
        self.assertIsNone(connection.last_balance)
        await connection._handle_control(result)
        self.assertEqual(await task, result)
        self.assertEqual(service.status()["robots"]["robot"]["balance_settings"], result)
        self.assertEqual(connection.body_command_sequence, 321)
        self.assertEqual(connection.body_command["name"], "walk")
        self.assertEqual(len(socket.sent), 1)
        with self.assertRaisesRegex(GatewayError, "unknown self-leveling"):
            await service.body_balance("save", {"angle":10}, robot_id="robot")
        connection.features = ()
        with self.assertRaisesRegex(GatewayError, "firmware"):
            await service.body_balance("get", robot_id="robot")
        self.assertEqual(len(socket.sent), 1)

    async def test_gyro_calibration_preserves_motion_and_uses_receipts(self):
        class Socket:
            closed = False
            def __init__(self): self.sent = []
            async def send(self, raw): self.sent.append(json.loads(raw))
        service = GatewayService(GatewayServiceConfig(tokens={"robot": "test"}))
        socket = Socket()
        connection = GatewayConnection(service, socket, "robot", 1, model="v2-12servo",
                                       features=("balance_control_v1",))
        service._connections["robot"] = connection
        connection.body_command_sequence = 321
        with self.assertRaisesRegex(GatewayError, "stationary gyro"):
            await service.body_balance("calibrate_gyro", robot_id="robot")
        self.assertEqual(socket.sent, [])
        connection.features += ("balance_feedback_v1",)
        task = asyncio.create_task(service.body_balance("calibrate_gyro", robot_id="robot"))
        while not socket.sent: await asyncio.sleep(0)
        self.assertEqual(socket.sent[-1], {"t":"balance", "op":"calibrate_gyro", "seq":1})
        await connection._handle_control({"t":"ack", "seq":1})
        reply = {"t":"balance_status", "seq":1, "enabled":False, "saved":True, "active":False}
        await connection._handle_control(reply)
        self.assertEqual(await task, reply)
        self.assertEqual(connection.body_command_sequence, 321)
        self.assertEqual(len(socket.sent), 1)

    async def test_balance_tuning_negotiation_and_atomic_readback(self):
        class Socket:
            closed = False
            def __init__(self): self.sent = []
            async def send(self,raw): self.sent.append(json.loads(raw))
        service=GatewayService(GatewayServiceConfig(tokens={"robot":"test"}))
        socket=Socket()
        connection=GatewayConnection(service,socket,"robot",1,model="v2-12servo",features=("balance_control_v1",))
        service._connections["robot"]=connection
        fields={"enabled":False,"strength":1.75,"damping":.6,"roll_deg":-2,"pitch_deg":3}
        with self.assertRaisesRegex(GatewayError,"tune self-leveling"):
            await service.body_balance("save",fields,robot_id="robot")
        self.assertEqual(socket.sent,[])
        connection.features+=("balance_tuning_v1",)
        task=asyncio.create_task(service.body_balance("save",fields,robot_id="robot"))
        while not socket.sent: await asyncio.sleep(0)
        self.assertEqual(socket.sent[-1],{"t":"balance","op":"save","seq":1,**fields})
        await connection._handle_control({"t":"ack","seq":1})
        result={"t":"balance_status","seq":1,"saved":True,"active":False,"tuning_saved":True,**fields}
        await connection._handle_control(result)
        self.assertEqual(await task,result)

    async def test_maintenance_address_uses_selected_remote_peer(self) -> None:
        from types import SimpleNamespace
        service = GatewayService(GatewayServiceConfig(tokens={"robot": "test"}))
        socket = SimpleNamespace(remote_address=("192.0.2.7", 32100), local_address=("192.0.2.1", 8790))
        connection = GatewayConnection(service, socket, "robot", 1)
        service._connections["robot"] = connection
        self.assertEqual(await service.maintenance_address("robot"), "192.0.2.7")
        with self.assertRaises(RobotOfflineError): await service.maintenance_address("other")
        connection.transport = "bridge"
        with self.assertRaises(GatewayError): await service.maintenance_address("robot")

    async def test_speech_cancellation_uses_audio_command_and_preserves_dispatch_receipt(self) -> None:
        from contextlib import asynccontextmanager
        messages, dispatches = [], []

        class Socket:
            closed = False
            async def send(self, raw):
                message = json.loads(raw)
                self_test.assertEqual(dispatches, [message["seq"]])
                messages.append(message)
                await connection._handle_control({"t": "ack", "seq": message["seq"]})

        @asynccontextmanager
        async def record(sequence):
            dispatches.append(sequence)
            yield

        self_test = self
        service = GatewayService(GatewayServiceConfig(tokens={"robot": "test"}))
        connection = GatewayConnection(service, Socket(), "robot", 1)
        service._connections["robot"] = connection
        sequence = await service.cancel_speech(robot_id="robot", on_sequence=record)
        self.assertEqual((messages[0]["t"], messages[0]["op"]), ("tts", "cancel"))
        self.assertEqual((await service.wait_terminal(sequence, robot_id="robot"))["t"], "ack")

    async def test_audio_controls_and_pre_gate_meter(self) -> None:
        class Socket:
            closed = False
            def __init__(self):
                self.sent = []
            async def send(self, raw):
                self.sent.append(json.loads(raw))

        service = GatewayService(GatewayServiceConfig(tokens={"robot": "test"}))
        socket = Socket()
        connection = GatewayConnection(service, socket, "robot", 1, model="v2-12servo",
                                       capabilities={"microphone": True, "wake": True, "speaker": True})
        service._connections["robot"] = connection
        with self.assertRaisesRegex(GatewayError, "audio input adjustments"):
            await service.set_microphone(on=True, gate="wake", gain_db=36, robot_id="robot")
        with self.assertRaisesRegex(GatewayError, "audio input adjustments"):
            await service.set_wake_configuration(enabled=True, model="ainekio", threshold=0.4, robot_id="robot")
        self.assertEqual(socket.sent, [])
        self.assertEqual(connection.next_sequence, 1)
        with self.assertRaisesRegex(GatewayError, "saved speaker volume"):
            await service.set_speaker_volume(volume_percent=37, robot_id="robot")
        connection.features = ("audio_input_v1",)
        seq = await service.set_microphone(on=True, gate="wake", gain_db=36, robot_id="robot")
        self.assertEqual(socket.sent[-1], {"t": "mic", "seq": seq, "on": True, "gate": "wake", "gain_db": 36})
        await connection._handle_control({"t": "ack", "seq": seq})
        seq = await service.set_wake_configuration(enabled=True, model="ainekio", threshold=0.4, robot_id="robot")
        self.assertEqual(socket.sent[-1]["threshold"], 0.4)
        await connection._handle_control({"t": "ack", "seq": seq})
        audio = {"on": True, "listening": True, "gate": "wake", "gain_db": 36,
                 "wake_enabled": True, "wake_threshold": 0.4, "rms": 0.08, "peak": 0.24,
                 "speaker_volume_percent": 37}
        # Meter updates without a wake event or any transmitted microphone PCM.
        await connection._handle_control({"t": "ping", "clock_ms": 12000, "audio": audio})
        self.assertEqual(socket.sent[-1], {"t": "pong", "external_speech": False})
        entry = service.status()["robots"]["robot"]
        self.assertEqual(entry["audio_input"], audio)
        self.assertEqual(entry["microphone_level"], 0.08)
        self.assertLess(entry["audio_input_age_ms"], 100)
        for volume in (0, 37, 100):
            seq = await service.set_speaker_volume(volume_percent=volume, robot_id="robot")
            self.assertEqual(socket.sent[-1], {"t": "speaker", "seq": seq, "volume_percent": volume})
        # Gated PCM does not overwrite the pre-gate meter on upgraded bodies.
        await connection._handle_binary(b"\x01" + struct.pack("<I320h", 1, *([0] * 320)))
        self.assertEqual(connection.microphone_level, 0.08)
        await connection._handle_control({"t": "pong", "audio": {**audio, "listening": False}})
        self.assertEqual(connection.microphone_level, 0)

    async def test_independent_camera_profiles_require_negotiation_before_sending(self) -> None:
        class Socket:
            closed = False
            sent = []

            async def send(self, raw):
                self.sent.append(json.loads(raw))

        service = GatewayService(GatewayServiceConfig(tokens={"robot": "test"}))
        socket = Socket()
        connection = GatewayConnection(service, socket, "robot", 1, model="v2-12servo", capabilities={"camera": True})
        service._connections["robot"] = connection
        with self.assertRaisesRegex(GatewayError, "independent snapshot"):
            await service.set_camera(on=True, fps=5, resolution="QVGA", snapshot_resolution="XGA", robot_id="robot")
        self.assertEqual(socket.sent, [])
        self.assertEqual(connection.next_sequence, 1)
        connection.features = (CAMERA_PROFILES_FEATURE,)
        for resolution in ("AUTO", "960P", "FHD"):
            with self.assertRaisesRegex(GatewayError, "adaptive/high-resolution"):
                await service.set_camera(on=False, fps=0, resolution="VGA", snapshot_resolution=resolution, robot_id="robot")
        self.assertEqual(socket.sent, [])
        self.assertEqual(connection.next_sequence, 1)
        sequence = await service.set_camera(on=True, fps=5, resolution="QVGA", snapshot_resolution="XGA", robot_id="robot")
        self.assertEqual(socket.sent, [{"t": "cam", "seq": sequence, "on": True, "fps": 5, "res": "QVGA", "snapshot_res": "XGA"}])
        await connection._handle_control({"t": "ack", "seq": sequence})

        connection.features = (CAMERA_PROFILES_FEATURE, CAMERA_ADAPTIVE_FEATURE)
        for resolution in ("AUTO", "960P", "FHD"):
            sequence = await service.set_camera(on=False, fps=0, resolution="VGA", snapshot_resolution=resolution, robot_id="robot")
            self.assertEqual(socket.sent[-1]["snapshot_res"], resolution)
            await connection._handle_control({"t": "ack", "seq": sequence})
        self.assertEqual((await service.wait_terminal(sequence))["t"], "ack")
        # Existing stream callers retain their envelope and leave the still profile alone.
        sequence = await service.set_camera(on=False, fps=0, resolution="VGA", robot_id="robot")
        self.assertNotIn("snapshot_res", socket.sent[-1])
        await connection._handle_control({"t": "ack", "seq": sequence})

    async def test_hd_camera_controls_negotiate_and_preserve_exact_manual_values(self):
        class Socket:
            closed = False
            def __init__(self): self.sent = []
            async def send(self, raw): self.sent.append(json.loads(raw))
        service = GatewayService(GatewayServiceConfig(tokens={"robot": "test"}))
        socket = Socket()
        connection = GatewayConnection(service, socket, "robot", 1, model="v2-12servo", capabilities={"camera": True})
        service._connections["robot"] = connection
        settings = dict(on=True, fps=3, resolution="960P", exposure_us=50000, gain_x16=64, jpeg_quality=85, robot_id="robot")
        with self.assertRaisesRegex(GatewayError, "camera_controls_v1"):
            await service.set_camera(**settings)
        self.assertEqual(socket.sent, [])
        connection.features = ("camera_controls_v1",)
        for resolution in ("XGA", "960P", "FHD"):
            sequence = await service.set_camera(**{**settings, "resolution": resolution})
            self.assertEqual(socket.sent[-1], {"t": "cam", "seq": sequence, "on": True, "fps": 3, "res": resolution,
                "exposure_us": 50000, "gain_x16": 64, "jpeg_quality": 85})
            await connection._handle_control({"t": "ack", "seq": sequence})
        before = len(socket.sent)
        for changes in ({"exposure_us": 99}, {"gain_x16": 1}, {"jpeg_quality": 101}, {"gain_x16": None}):
            with self.assertRaises(ValueError):
                await service.set_camera(**{**settings, **changes})
        self.assertEqual(len(socket.sent), before)
        sequence = await service.set_camera(**{**settings, "exposure_us": 0, "gain_x16": 0})
        self.assertEqual(socket.sent[-1]["gain_x16"], 0)
        await connection._handle_control({"t": "ack", "seq": sequence})

    def test_gateway_liveness_defaults_match_physical_body_contract(self) -> None:
        config = GatewayServiceConfig(tokens={"ainekio-test-01": "test-token"})
        self.assertEqual(config.ping_interval_s, 1.0)
        with self.assertRaisesRegex(ValueError, "between 0.01 and 60"):
            GatewayServiceConfig(
                tokens={"ainekio-test-01": "test-token"},
                ping_interval_s=0.0,
            )

    def test_gateway_reports_stale_before_transport_disconnects(self) -> None:
        class Socket:
            closed = False

        now = [10.0]
        service = GatewayService(
            GatewayServiceConfig(tokens={"ainekio-test-01": "test-token"}),
            clock=lambda: now[0],
        )
        service._connections["ainekio-test-01"] = GatewayConnection(
            service,
            Socket(),
            "ainekio-test-01",
            1,
        )

        fresh = service.status()["robots"]["ainekio-test-01"]
        self.assertEqual(fresh["connection_state"], "online")
        self.assertEqual(fresh["heartbeat_age_ms"], 0)

        now[0] += 4.0
        stale = service.status()["robots"]["ainekio-test-01"]
        self.assertEqual(stale["connection_state"], "stale")
        self.assertEqual(stale["heartbeat_age_ms"], 4000)

    async def test_gateway_api_tracks_command_lifecycle(self) -> None:
        service = GatewayService(
            GatewayServiceConfig(tokens={"ainekio-test-01": "test-token"})
        )
        core = PortableCore(self.library_path)
        session = BodySession(core, ImmediateMotionBackend())

        async with websockets.serve(
            service.handler,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            client = ProtocolV1BodyClient(
                BodyClientConfig(
                    endpoint=f"ws://127.0.0.1:{port}/robot",
                    robot_id="ainekio-test-01",
                    auth_token="test-token",
                ),
                session,
            )
            client_task = asyncio.create_task(client.run_once())
            await service.wait_connected("ainekio-test-01")

            for expected_sequence, (intent, params) in enumerate(
                (("stand", None), ("emote", {"asset": "curious"})), start=1
            ):
                sequence = await service.queue_intent(intent, params)
                terminal = await service.wait_terminal(
                    sequence, robot_id="ainekio-test-01", epoch=1, timeout=None
                )

                self.assertEqual(sequence, expected_sequence)
                self.assertEqual(terminal, {"t": "done", "seq": sequence})
                self.assertEqual(service.terminals[-1]["epoch"], 1)

            await service.revoke_token("ainekio-test-01")
            await client_task

        core.close()

    async def test_p4_freestyle_selects_map_two_and_keeps_completion_pending(self):
        class Socket:
            closed=False
            def __init__(self): self.sent=[]
            async def send(self,raw): self.sent.append(json.loads(raw))
        service=GatewayService(GatewayServiceConfig(tokens={"robot":"test"}))
        socket=Socket()
        connection=GatewayConnection(service,socket,"robot",1,model="v2-12servo",features=("motion_plan_v2",))
        service._connections["robot"]=connection
        seq=await service.queue_motion_plan([[12000,[-11768]*12]],end="hold",robot_id="robot")
        self.assertEqual(socket.sent[-1]["map"],2)
        self.assertEqual(socket.sent[-1]["frames"],[[12000,[-11768]*12]])
        self.assertTrue(connection.pending[seq].needs_done)
        self.assertFalse(connection.pending[seq].future.done())
        next_seq=connection.next_sequence
        with self.assertRaises(ValueError):
            await service.queue_motion_plan([[100,[9000]*8]],end="hold",robot_id="robot")
        self.assertEqual(connection.next_sequence,next_seq)

    async def test_gateway_motion_plan_requires_feature_and_tracks_done(self) -> None:
        service = GatewayService(
            GatewayServiceConfig(tokens={"ainekio-test-01": "test-token"})
        )
        core = PortableCore(self.library_path)
        session = BodySession(core, ImmediateMotionBackend())

        async with websockets.serve(
            service.handler,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            client = ProtocolV1BodyClient(
                BodyClientConfig(
                    endpoint=f"ws://127.0.0.1:{port}/robot",
                    robot_id="ainekio-test-01",
                    auth_token="test-token",
                ),
                session,
            )
            client_task = asyncio.create_task(client.run_once())
            await service.wait_connected("ainekio-test-01")

            self.assertEqual(
                service.status()["robots"]["ainekio-test-01"]["features"],
                ["motion_plan_v1"],
            )
            sequence = await service.queue_motion_plan(
                [[300, [9000] * 8]],
                end="hold",
            )
            self.assertEqual(
                await service.wait_terminal(sequence),
                {"t": "done", "seq": sequence},
            )

            await service.revoke_token("ainekio-test-01")
            await client_task

        core.close()

    async def test_freshness_is_checked_before_sequence_assignment(self) -> None:
        service = GatewayService(
            GatewayServiceConfig(
                tokens={"ainekio-test-01": "test-token"},
                max_action_age_ms=100,
            )
        )
        core = PortableCore(self.library_path)
        session = BodySession(core, ImmediateMotionBackend())

        async with websockets.serve(
            service.handler,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            client = ProtocolV1BodyClient(
                BodyClientConfig(
                    endpoint=f"ws://127.0.0.1:{port}/robot",
                    robot_id="ainekio-test-01",
                    auth_token="test-token",
                ),
                session,
            )
            client_task = asyncio.create_task(client.run_once())
            await service.wait_connected("ainekio-test-01")

            with self.assertRaises(ActionExpiredError):
                await service.queue_intent("stand", received_at=monotonic() - 1.0)

            sequence = await service.set_profile("tether")
            terminal = await service.wait_terminal(sequence)
            self.assertEqual(sequence, 1)
            self.assertEqual(terminal, {"t": "ack", "seq": 1})

            await service.revoke_token("ainekio-test-01")
            await client_task

        core.close()

    async def test_gateway_persists_disabled_wake_configuration_on_body(self) -> None:
        service = GatewayService(
            GatewayServiceConfig(tokens={"ainekio-test-01": "test-token"})
        )
        core = PortableCore(self.library_path)
        session = BodySession(core, ImmediateMotionBackend())

        async with websockets.serve(
            service.handler,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            client = ProtocolV1BodyClient(
                BodyClientConfig(
                    endpoint=f"ws://127.0.0.1:{port}/robot",
                    robot_id="ainekio-test-01",
                    auth_token="test-token",
                ),
                session,
            )
            client_task = asyncio.create_task(client.run_once())
            await service.wait_connected("ainekio-test-01")

            sequence = await service.set_wake_configuration(
                enabled=False,
                model="ainekio",
            )
            self.assertEqual(
                await service.wait_terminal(sequence),
                {"t": "ack", "seq": sequence},
            )
            self.assertEqual(
                session.wake_settings,
                {"enabled": False, "model": "ainekio", "ready": False},
            )

            await service.revoke_token("ainekio-test-01")
            await client_task

        core.close()

    async def test_tts_api_preserves_start_frames_end_order(self) -> None:
        service = GatewayService(
            GatewayServiceConfig(tokens={"ainekio-test-01": "test-token"})
        )
        core = PortableCore(self.library_path)
        session = BodySession(core, ImmediateMotionBackend())

        async with websockets.serve(
            service.handler,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            client = ProtocolV1BodyClient(
                BodyClientConfig(
                    endpoint=f"ws://127.0.0.1:{port}/robot",
                    robot_id="ainekio-test-01",
                    auth_token="test-token",
                ),
                session,
            )
            client_task = asyncio.create_task(client.run_once())
            await service.wait_connected("ainekio-test-01")

            start_sequence = await service.tts_speak([bytes(640), bytes(640)])
            terminal = await service.wait_terminal(start_sequence)

            self.assertEqual(start_sequence, 1)
            self.assertEqual(terminal, {"t": "done", "seq": 1})
            self.assertEqual(service.terminals[-1]["seq"], 1)

            await service.revoke_token("ainekio-test-01")
            await client_task

        core.close()

    async def test_tts_waits_for_start_ack_before_sending_pcm(self) -> None:
        class Socket:
            closed = False

            def __init__(self) -> None:
                self.sent: list[object] = []

            async def send(self, payload: object) -> None:
                self.sent.append(payload)

        service = GatewayService(
            GatewayServiceConfig(tokens={"ainekio-test-01": "test-token"})
        )
        socket = Socket()
        connection = GatewayConnection(
            service,
            socket,
            "ainekio-test-01",
            1,
        )
        service._connections["ainekio-test-01"] = connection

        send_task = asyncio.create_task(service.tts_speak([bytes(640)]))
        await asyncio.sleep(0)

        self.assertEqual(len(socket.sent), 1)
        self.assertEqual(
            json.loads(str(socket.sent[0])),
            {"t": "tts", "op": "start", "seq": 1},
        )

        await connection._handle_control({"t": "ack", "seq": 1})
        self.assertEqual(await send_task, 1)
        self.assertEqual(len(socket.sent), 3)
        self.assertIsInstance(socket.sent[1], bytes)
        self.assertEqual(len(socket.sent[1]), 645)
        self.assertEqual(
            json.loads(str(socket.sent[2])),
            {"t": "tts", "op": "end", "seq": 2},
        )

    async def test_wrong_token_and_offline_actions_are_rejected(self) -> None:
        service = GatewayService(
            GatewayServiceConfig(tokens={"ainekio-test-01": "correct-token"})
        )
        with self.assertRaises(RobotOfflineError):
            await service.queue_intent("stand")

        core = PortableCore(self.library_path)
        session = BodySession(core, ImmediateMotionBackend())
        async with websockets.serve(
            service.handler,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            client = ProtocolV1BodyClient(
                BodyClientConfig(
                    endpoint=f"ws://127.0.0.1:{port}/robot",
                    robot_id="ainekio-test-01",
                    auth_token="wrong-token",
                ),
                session,
            )
            with self.assertRaises(HandshakeRejected):
                await client.run_once()

        core.close()

    async def test_replacement_reads_heartbeats_while_previous_socket_closes(self) -> None:
        now = [0.0]
        service = GatewayService(GatewayServiceConfig(tokens={'fixture-body': 'test'}), clock=lambda: now[0])
        old, new = LifecycleSocket(), LifecycleSocket(acknowledge=True)
        old_task = asyncio.create_task(service.handler(old, '/robot'))
        await asyncio.wait_for(old.welcomed.wait(), 1)
        old_sequence = await service.queue_intent('stand')
        old.close_release = asyncio.Event()
        new_task = asyncio.create_task(service.handler(new, '/robot'))
        try:
            await asyncio.wait_for(old.close_started.wait(), 1)
            await asyncio.wait_for(new.welcomed.wait(), 1)
            self.assertFalse(old.closed)
            now[0] = 2.0
            new.incoming.put_nowait(json.dumps({'t': 'ping', 'clock_ms': 12000}))
            await asyncio.wait_for(new.pong.wait(), 1)
            sequence = await service.queue_intent('stand')
            terminal = await service.wait_terminal(sequence, robot_id='fixture-body', timeout=1)
            self.assertEqual(terminal['t'], 'done')
            self.assertEqual(service._connections['fixture-body'].body_clock_ms, 12000)
            old_results = [item for item in service.terminals if item['epoch'] == 1 and item['seq'] == old_sequence]
            self.assertEqual(old_results[-1]['result']['code'], 'reconnect')
        finally:
            old.close_release.set()
            await old.close()
            await new.close()
            await asyncio.gather(old_task, new_task)

    async def test_lost_heartbeats_close_the_old_session_and_allow_reconnect(self) -> None:
        now = [0.0]
        service = GatewayService(GatewayServiceConfig(tokens={'fixture-body': 'test'}), clock=lambda: now[0])
        old = LifecycleSocket()
        old_task = asyncio.create_task(service.handler(old, '/robot'))
        await asyncio.wait_for(old.welcomed.wait(), 1)
        old_sequence = await service.queue_intent('stand')
        now[0] = 3.0
        old.incoming.put_nowait(json.dumps({'t': 'ping', 'clock_ms': 13000}))
        await asyncio.wait_for(old.pong.wait(), 1)
        now[0] = 6.8
        await asyncio.sleep(0.15)
        self.assertFalse(old.closed)  # Silence from the user is not lost robot liveness.
        now[0] = 7.1
        await asyncio.wait_for(old.close_started.wait(), 1)
        await asyncio.wait_for(old_task, 1)
        self.assertNotIn('fixture-body', service._connections)
        self.assertTrue(any(item['seq'] == old_sequence and item['result']['outcome_unknown']
                            for item in service.terminals))

        replacement = LifecycleSocket(acknowledge=True)
        replacement_task = asyncio.create_task(service.handler(replacement, '/robot'))
        try:
            await asyncio.wait_for(replacement.welcomed.wait(), 1)
            self.assertFalse(any(item.get('t') == 'intent' for item in replacement.sent))
            sequence = await service.queue_intent('stand')
            terminal = await service.wait_terminal(sequence, robot_id='fixture-body', timeout=1)
            self.assertEqual(terminal['t'], 'done')
        finally:
            await replacement.close()
            await replacement_task

    async def test_connected_callback_can_receive_its_command_receipt(self) -> None:
        service = GatewayService(GatewayServiceConfig(tokens={'fixture-body': 'test'}))
        socket = LifecycleSocket(acknowledge=True)
        completed = asyncio.Event()
        async def connected(event):
            if event.get('status') != 'connected':
                return
            sequence = await service.queue_intent('stand')
            terminal = await service.wait_terminal(sequence, robot_id='fixture-body', timeout=1)
            self.assertEqual(terminal['t'], 'done')
            completed.set()
        service.subscribe_events(connected)
        task = asyncio.create_task(service.handler(socket, '/robot'))
        try:
            await asyncio.wait_for(completed.wait(), 1)
        finally:
            await socket.close()
            await task

    async def test_duplicate_connection_cancels_old_epoch_and_closes_4000(self) -> None:
        service = GatewayService(
            GatewayServiceConfig(tokens={"ainekio-test-01": "test-token"})
        )
        first_disconnected = asyncio.Event()
        events: list[dict[str, object]] = []

        def record_event(event: dict[str, object]) -> None:
            events.append(event)
            if (
                event.get("t") == "connection"
                and event.get("status") == "disconnected"
                and event.get("epoch") == 1
            ):
                first_disconnected.set()

        service.subscribe_events(record_event)
        async with websockets.serve(
            service.handler,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}/robot"
            first = await websockets.connect(uri, ping_interval=None)
            await first.send(
                json.dumps(
                    {
                        "t": "hello",
                        "ver": 1,
                        "fw": "test",
                        "id": "ainekio-test-01",
                        "auth": "test-token",
                    }
                )
            )
            self.assertEqual(json.loads(await first.recv())["epoch"], 1)
            sequence = await service.queue_intent("stand")
            command = json.loads(await first.recv())
            self.assertEqual(command["seq"], sequence)
            await first.send(json.dumps({"t": "ack", "seq": sequence}))

            second = await websockets.connect(uri, ping_interval=None)
            await second.send(
                json.dumps(
                    {
                        "t": "hello",
                        "ver": 1,
                        "fw": "test",
                        "id": "ainekio-test-01",
                        "auth": "test-token",
                    }
                )
            )
            self.assertEqual(json.loads(await second.recv())["epoch"], 2)
            await first.wait_closed()

            self.assertEqual(first.close_code, 4000)
            await asyncio.wait_for(first_disconnected.wait(), timeout=1.0)
            self.assertIn(
                {
                    "t": "connection",
                    "status": "disconnected",
                    "robot_id": "ainekio-test-01",
                    "epoch": 1,
                    "transport": "lan",
                    "close_code": 4000,
                    "close_reason": "new authenticated connection",
                },
                events,
            )
            self.assertEqual(
                service.terminals[-1]["result"],
                {"t": "cancelled", "seq": sequence, "code": "reconnect", "outcome_unknown": True},
            )
            await second.close()

    async def test_gateway_tolerates_brief_control_gap(self) -> None:
        service = GatewayService(
            GatewayServiceConfig(
                tokens={"ainekio-test-01": "test-token"},
                ping_interval_s=0.05,
            )
        )
        async with websockets.serve(
            service.handler,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            socket = await websockets.connect(
                f"ws://127.0.0.1:{port}/robot",
                ping_interval=None,
            )
            await socket.send(
                json.dumps(
                    {
                        "t": "hello",
                        "ver": 1,
                        "fw": "test",
                        "id": "ainekio-test-01",
                        "auth": "test-token",
                    }
                )
            )
            self.assertEqual(json.loads(await socket.recv())["t"], "welcome")

            self.assertEqual(json.loads(await socket.recv())["t"], "ping")
            # A response can arrive after multiple scheduler ticks without
            # converting an idle but healthy session into an outage.
            await asyncio.sleep(0.1)
            await socket.send(json.dumps({"t": "pong"}))
            self.assertFalse(socket.closed)
            self.assertEqual(json.loads(await socket.recv())["t"], "ping")
            await socket.send(json.dumps({"t": "pong"}))
            await socket.close()

    async def test_silent_controller_is_not_disconnected_by_idle_timer(self) -> None:
        events: list[dict[str, object]] = []
        service = GatewayService(
            GatewayServiceConfig(
                tokens={"ainekio-test-01": "test-token"},
                ping_interval_s=0.05,
            )
        )
        service.subscribe_events(events.append)
        async with websockets.serve(
            service.handler,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            socket = await websockets.connect(
                f"ws://127.0.0.1:{port}/robot",
                ping_interval=None,
            )
            await socket.send(
                json.dumps(
                    {
                        "t": "hello",
                        "ver": 1,
                        "fw": "test",
                        "id": "ainekio-test-01",
                        "auth": "test-token",
                    }
                )
            )
            self.assertEqual(json.loads(await socket.recv())["t"], "welcome")
            # Staying silent for several heartbeat periods must not turn an
            # established home-companion session into an outage.
            for _ in range(4):
                self.assertEqual(json.loads(await socket.recv())["t"], "ping")
            self.assertFalse(socket.closed)
            self.assertIn("ainekio-test-01", service.status()["robots"])
            self.assertFalse(
                any(event.get("status") == "disconnected" for event in events)
            )
            await socket.close()

    async def test_token_revocation_closes_active_socket_and_rejects_reconnect(self) -> None:
        service = GatewayService(
            GatewayServiceConfig(tokens={"ainekio-test-01": "test-token"})
        )
        async with websockets.serve(
            service.handler,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}/robot"
            socket = await websockets.connect(uri, ping_interval=None)
            hello = {
                "t": "hello",
                "ver": 1,
                "fw": "test",
                "id": "ainekio-test-01",
                "auth": "test-token",
            }
            await socket.send(json.dumps(hello))
            await socket.recv()

            await service.revoke_token("ainekio-test-01")
            await socket.wait_closed()
            self.assertEqual(socket.close_code, 4001)

            rejected = await websockets.connect(uri, ping_interval=None)
            await rejected.send(json.dumps(hello))
            self.assertEqual(json.loads(await rejected.recv()), {"t": "err", "code": "auth"})
            await rejected.wait_closed()
            self.assertEqual(rejected.close_code, 4001)

    async def test_vad_pcm_reaches_stubbed_transcriber(self) -> None:
        service = GatewayService(
            GatewayServiceConfig(tokens={"ainekio-test-01": "test-token"})
        )
        transcript_ready = asyncio.Event()
        transcripts: list[dict[str, object]] = []

        def receive_transcript(transcript: dict[str, object]) -> None:
            transcripts.append(transcript)
            transcript_ready.set()

        service.subscribe_transcripts(receive_transcript)
        transcribed_audio: list[bytes] = []

        def transcribe(payload: bytes) -> str:
            transcribed_audio.append(payload)
            return "fixture transcript"

        AudioTranscriptPlugin(service, transcribe)
        microphone = QueueMicrophoneSource(
            [struct.pack("<320h", *([1200] * 320))]
            + [bytes(640) for _ in range(6)]
        )
        core = PortableCore(self.library_path)
        session = BodySession(
            core,
            ImmediateMotionBackend(),
            microphone_source=microphone,
        )

        async with websockets.serve(
            service.handler,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            client = ProtocolV1BodyClient(
                BodyClientConfig(
                    endpoint=f"ws://127.0.0.1:{port}/robot",
                    robot_id="ainekio-test-01",
                    auth_token="test-token",
                ),
                session,
            )
            client_task = asyncio.create_task(client.run_once())
            await service.wait_connected("ainekio-test-01")
            sequence = await service.set_microphone(on=True, gate="vad")
            self.assertEqual(await service.wait_terminal(sequence), {"t": "ack", "seq": sequence})
            await asyncio.wait_for(transcript_ready.wait(), timeout=2.0)

            self.assertEqual(transcripts[0]["text"], "fixture transcript")
            self.assertEqual(transcripts[0]["first_counter"], 0)
            self.assertEqual(transcripts[0]["last_counter"], 5)
            self.assertEqual(transcripts[0]["duration_ms"], 120)
            with wave.open(io.BytesIO(transcribed_audio[0]), "rb") as wav:
                self.assertEqual(wav.getnchannels(), 1)
                self.assertEqual(wav.getsampwidth(), 2)
                self.assertEqual(wav.getframerate(), 16000)
                self.assertEqual(wav.getnframes(), 1920)
            await service.revoke_token("ainekio-test-01")
            await client_task
        core.close()

    async def test_camera_frame_reaches_camera_plugin(self) -> None:
        service = GatewayService(
            GatewayServiceConfig(tokens={"ainekio-test-01": "test-token"})
        )
        frame_ready = asyncio.Event()
        payloads: list[bytes] = []
        loop = asyncio.get_running_loop()

        def consume(payload: bytes) -> None:
            payloads.append(payload)
            loop.call_soon_threadsafe(frame_ready.set)

        plugin = CameraFramePlugin(service, consume)
        self.addAsyncCleanup(plugin.aclose)
        camera = FixtureCameraSource(b"\xff\xd8fixture\xff\xd9")
        core = PortableCore(self.library_path)
        session = BodySession(
            core,
            ImmediateMotionBackend(),
            camera_source=camera,
        )
        async with websockets.serve(
            service.handler,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            client = ProtocolV1BodyClient(
                BodyClientConfig(
                    endpoint=f"ws://127.0.0.1:{port}/robot",
                    robot_id="ainekio-test-01",
                    auth_token="test-token",
                ),
                session,
            )
            client_task = asyncio.create_task(client.run_once())
            await service.wait_connected("ainekio-test-01")
            sequence = await service.set_camera(on=True, fps=5, resolution="VGA")
            self.assertEqual(await service.wait_terminal(sequence), {"t": "ack", "seq": sequence})
            await asyncio.wait_for(frame_ready.wait(), timeout=2.0)

            self.assertEqual(payloads, [b"\xff\xd8fixture\xff\xd9"])
            await service.revoke_token("ainekio-test-01")
            await client_task
        core.close()

    async def test_slow_camera_inference_preserves_command_and_stop_receipts(self) -> None:
        service = GatewayService(GatewayServiceConfig(tokens={"ainekio-test-01": "test-token"}))
        inference_started, release = asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()

        def consume(payload: bytes) -> str:
            loop.call_soon_threadsafe(inference_started.set)
            if not release.wait(5):
                raise TimeoutError("test inference was not released")
            return "replayed scene"

        plugin = CameraFramePlugin(service, consume)
        self.addAsyncCleanup(plugin.aclose)
        core = PortableCore(self.library_path)
        self.addCleanup(core.close)
        session = BodySession(core, ImmediateMotionBackend(),
                              camera_source=FixtureCameraSource(b"\xff\xd8fixture\xff\xd9"))
        async with websockets.serve(service.handler, "127.0.0.1", 0, ping_interval=None) as server:
            port = server.sockets[0].getsockname()[1]
            client = ProtocolV1BodyClient(BodyClientConfig(
                endpoint=f"ws://127.0.0.1:{port}/robot", robot_id="ainekio-test-01",
                auth_token="test-token",
            ), session)
            client_task = asyncio.create_task(client.run_once())
            try:
                await service.wait_connected("ainekio-test-01")
                camera_sequence = await service.set_camera(on=True, fps=5, resolution="VGA")
                self.assertEqual(await service.wait_terminal(camera_sequence, timeout=1),
                                 {"t": "ack", "seq": camera_sequence})
                await asyncio.wait_for(inference_started.wait(), 1)
                sequence = await service.queue_intent("stand")
                self.assertEqual(await service.wait_terminal(sequence, timeout=1),
                                 {"t": "done", "seq": sequence})
                stop_sequence = await service.estop()
                self.assertEqual(await service.wait_terminal(stop_sequence, timeout=1),
                                 {"t": "ack", "seq": stop_sequence})
                self.assertFalse(release.is_set())
            finally:
                release.set()
                await service.revoke_token("ainekio-test-01")
                await client_task

    async def test_gateway_allows_explicit_media_in_tether(self) -> None:
        service = GatewayService(
            GatewayServiceConfig(
                tokens={"ainekio-test-01": "test-token"},
                profile="tether",
            )
        )
        core = PortableCore(self.library_path)
        session = BodySession(core, ImmediateMotionBackend())
        async with websockets.serve(
            service.handler,
            "127.0.0.1",
            0,
            ping_interval=None,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            client = ProtocolV1BodyClient(
                BodyClientConfig(
                    endpoint=f"ws://127.0.0.1:{port}/robot",
                    robot_id="ainekio-test-01",
                    auth_token="test-token",
                ),
                session,
            )
            client_task = asyncio.create_task(client.run_once())
            await service.wait_connected("ainekio-test-01")

            sequence = await service.set_camera(on=True, fps=15, resolution="QVGA")
            self.assertEqual(await service.wait_terminal(sequence), {"t": "ack", "seq": 1})
            sequence = await service.set_microphone(on=True, gate="open")
            self.assertEqual(await service.wait_terminal(sequence), {"t": "ack", "seq": 2})
            caps = service.status()["robots"]["ainekio-test-01"]["effective_caps"]
            self.assertEqual(caps["camera_max_fps"], 15)
            self.assertIn("open", caps["microphone_gates"])
            await service.revoke_token("ainekio-test-01")
            await client_task
        core.close()

    async def test_wall_clock_jump_does_not_change_monotonic_freshness(self) -> None:
        class Socket:
            closed = False

            def __init__(self) -> None:
                self.sent: list[object] = []

            async def send(self, payload: object) -> None:
                self.sent.append(payload)

        now = [10.0]
        clock = GatewayClock(
            monotonic_clock=lambda: now[0],
            wall_clock=lambda: 1000.0,
        )
        service = GatewayService(
            GatewayServiceConfig(
                tokens={"ainekio-test-01": "test-token"},
                max_action_age_ms=100,
            ),
            clock_source=clock,
        )
        connection = GatewayConnection(service, Socket(), "ainekio-test-01", 1)
        service._connections["ainekio-test-01"] = connection

        service.jump_wall_clock(86400.0)
        self.assertEqual(clock.wall_time(), 87400.0)
        self.assertEqual(
            await service.queue_intent("stand", received_at=10.0),
            1,
        )

        now[0] = 10.2
        with self.assertRaises(ActionExpiredError):
            await service.queue_intent("stand", received_at=10.0)


if __name__ == "__main__":
    unittest.main()

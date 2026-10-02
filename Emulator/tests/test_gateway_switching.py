"""Real gateway sockets and native P4 selection/admission; device I/O is simulated."""
from __future__ import annotations

import asyncio
import ctypes
import json
import os
from pathlib import Path
import ssl
import signal
import socket
import subprocess
import tempfile
import sys
import unittest

import websockets

from gateway.security import DashboardPasswordStore, RobotTokenStore, export_pairing, import_pairing
from gateway.environment_adapter.server import ADAPTER_PROTOCOL_VERSION
from gateway.server.__main__ import _robot_transport
from gateway.server.service import GatewayService, GatewayServiceConfig, RobotOfflineError


ROOT = Path(__file__).resolve().parents[2]
BRIDGE = r'''
#include <stdlib.h>
#include <string.h>
#include "gateway_selection.h"
#include "ainekio/admission.h"
typedef struct {
    ainekio_p4_robot_settings_t settings;
    ainekio_p4_gateway_selection_t selection;
    ainekio_admission_t admission;
} simulation_t;
void *simulation_create(const char *first, const char *second) {
    simulation_t *s=calloc(1,sizeof(*s));
    if(!s)return NULL;
    s->settings.version=1;
    strcpy(s->settings.robot_id,"robot");strcpy(s->settings.robot_token,"shared-token");
    strcpy(s->settings.networks[0].ssid,"Home");strcpy(s->settings.networks[0].password,"home-password");
    strcpy(s->settings.networks[0].endpoint,first);
    s->settings.networks[1]=s->settings.networks[0];strcpy(s->settings.networks[1].endpoint,second);
    if(!ainekio_p4_robot_settings_valid(&s->settings)){free(s);return NULL;}
    ainekio_p4_gateway_select_network(&s->selection,&s->settings,0);
    ainekio_admission_init(&s->admission,AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_INTENT)|AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_STOP),true);
    ainekio_core_set_boot_ready(&s->admission.core,true);
    return s;
}
const char *simulation_endpoint(simulation_t *s) { return ainekio_p4_gateway_endpoint(&s->selection,&s->settings); }
uint64_t simulation_open(simulation_t *s) { return ainekio_admission_open(&s->admission); }
void simulation_failed(simulation_t *s,uint64_t generation) {
    ainekio_admission_close(&s->admission,generation);
    ainekio_p4_gateway_failed(&s->selection,&s->settings);
}
int simulation_welcome(simulation_t *s,uint64_t generation,const char *json) {
    ainekio_control_message_t m;
    if(ainekio_control_decode_for_body(json,strlen(json),&m)!=AINEKIO_DECODE_OK||m.kind!=AINEKIO_MESSAGE_WELCOME)return 0;
    return ainekio_admission_welcome(&s->admission,generation,m.data.welcome.epoch,m.data.welcome.profile,m.data.welcome.deadline_supported,1000000);
}
int simulation_accept(simulation_t *s,uint64_t generation,const char *json) {
    ainekio_control_message_t m;
    if(ainekio_control_decode_for_body(json,strlen(json),&m)!=AINEKIO_DECODE_OK)return -1;
    if(!ainekio_admission_control(&s->admission,generation,1000000))return -2;
    return ainekio_admission_accept(&s->admission,generation,&m,1000000,1000000,true).accepted;
}
void simulation_destroy(simulation_t *s) { free(s); }
'''


class GatewaySwitchingTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.build.cleanup)
        root = Path(cls.build.name)
        bridge = root / "bridge.c"
        bridge.write_text(BRIDGE)
        firmware = ROOT / "Slave/firmware/esp32p4-wifi6"
        core = ROOT / "Slave/software/core"
        library = root / "switching.so"
        subprocess.run(["cc", "-std=c11", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror", "-Wpedantic",
            "-I", str(firmware / "main"), "-I", str(firmware / "tests/body_shim"),
            "-I", str(ROOT / "Slave/firmware/components/ainekio_discovery/include"), "-I", str(core / "include"),
            str(bridge), str(firmware / "main/gateway_selection.c"), str(firmware / "main/robot_settings.c"),
            *[str(path) for path in sorted((core / "src").glob("*.c"))],
            "-lm", "-o", str(library)], check=True, capture_output=True, text=True, timeout=30)
        cls.native = ctypes.CDLL(str(library))
        signatures = {
            "simulation_create": ([ctypes.c_char_p, ctypes.c_char_p], ctypes.c_void_p),
            "simulation_endpoint": ([ctypes.c_void_p], ctypes.c_char_p),
            "simulation_open": ([ctypes.c_void_p], ctypes.c_uint64),
            "simulation_failed": ([ctypes.c_void_p, ctypes.c_uint64], None),
            "simulation_welcome": ([ctypes.c_void_p, ctypes.c_uint64, ctypes.c_char_p], ctypes.c_int),
            "simulation_accept": ([ctypes.c_void_p, ctypes.c_uint64, ctypes.c_char_p], ctypes.c_int),
            "simulation_destroy": ([ctypes.c_void_p], None),
        }
        for name, (args, result) in signatures.items():
            getattr(cls.native, name).argtypes = args
            getattr(cls.native, name).restype = result
        cls.cert = root / "server.crt"
        key = root / "server.key"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-keyout", str(key), "-out", str(cls.cert), "-subj", "/CN=localhost",
            "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"], check=True, capture_output=True)
        cls.server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cls.server_tls.load_cert_chain(cls.cert, key)

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.first, self.second = root / "first", root / "second"
        RobotTokenStore(self.first / "robot-tokens.json").set("robot", "shared-token")
        await asyncio.to_thread(DashboardPasswordStore(self.first / "dashboard-auth.json").set_password, "same-password")
        export_pairing(self.first, root / "pairing.json")
        import_pairing(self.second, root / "pairing.json")
        self.services = []
        self.servers = []
        self.body = None
        self.executed = []
        self.reader = None
        self.socket = None

    async def gateway(self, data, *, tls=False):
        store = RobotTokenStore(data / "robot-tokens.json")
        service = GatewayService(GatewayServiceConfig(tokens=store.snapshot()), token_store=store)
        async def route(socket, path):
            await service.handler(socket, path, transport=_robot_transport(socket))
        server = await websockets.serve(route, "127.0.0.1", 0, ping_interval=None, close_timeout=1,
                                       ssl=self.server_tls if tls else None)
        self.services.append(service)
        self.servers.append(server)
        return service, server, f"{'wss' if tls else 'ws'}://127.0.0.1:{server.sockets[0].getsockname()[1]}/robot"

    async def connect_body(self, *, token="shared-token", trust=True):
        endpoint = self.native.simulation_endpoint(self.body).decode()
        self.generation = self.native.simulation_open(self.body)
        options = {"ping_interval": None, "open_timeout": 1, "close_timeout": 1}
        if endpoint.startswith("wss:"):
            options["ssl"] = ssl.create_default_context(cafile=str(self.cert) if trust else None)
            options["extra_headers"] = {"CF-Ray": "simulated-relay"}
        self.socket = await websockets.connect(endpoint, **options)
        await self.socket.send(json.dumps({"t":"hello", "ver":1, "fw":"native-p4-sim", "id":"robot", "auth":token,
            "features":["command_deadline_v1", "body_capabilities_v1", "body_commands_v1", "walk_controls_v2",
                        "walk_steering_v1", "gateway_switching_v1"], "clock_ms":1000, "model":"v2-12servo",
            "capabilities":{"motion":True,"speaker":False,"microphone":False,"camera":False,"commands":["stand","walk","stop"]}}))
        welcome = await self.socket.recv()
        if json.loads(welcome)["t"] == "err":
            await self.socket.wait_closed()
            return False
        self.assertEqual(self.native.simulation_welcome(self.body, self.generation, welcome.encode()), 1)
        self.reader = asyncio.create_task(self.receive_commands(self.socket, self.generation))
        return True

    async def receive_commands(self, socket, generation):
        try:
            async for raw in socket:
                message = json.loads(raw)
                if message["t"] == "ping":
                    await socket.send(json.dumps({"t":"pong", "clock_ms":1000}))
                    continue
                accepted = self.native.simulation_accept(self.body, generation, raw.encode())
                if accepted != 1:
                    await socket.send(json.dumps({"t":"nak", "seq":message["seq"], "code":"stale"}))
                    continue
                self.executed.append((generation, message))
                await socket.send(json.dumps({"t":"ack", "seq":message["seq"]}))
                # Simulated finite body execution only. An ongoing walk stays
                # pending until interrupted, just like the production contract.
                if message.get("name") != "walk":
                    await socket.send(json.dumps({"t":"done", "seq":message["seq"]}))
        except websockets.ConnectionClosed:
            pass

    async def close_body(self):
        if self.socket is not None:
            await asyncio.wait_for(self.socket.close(), timeout=3)
            self.socket = None
        if self.reader is not None:
            await asyncio.wait_for(self.reader, timeout=3)
            self.reader = None
        self.native.simulation_failed(self.body, self.generation)

    async def asyncTearDown(self):
        if self.socket is not None:
            await self.close_body()
        for service, server in zip(self.services, self.servers):
            await service.close()
            server.close()
            await asyncio.wait_for(server.wait_closed(), timeout=3)
        if self.body is not None:
            self.native.simulation_destroy(self.body)

    async def test_switch_between_independent_hosts_cancels_old_action_without_replay(self):
        first, server, a = await self.gateway(self.first)
        second, _, b = await self.gateway(self.second)
        self.body = self.native.simulation_create(a.encode(), b.encode())
        self.assertTrue(self.body)
        self.assertTrue(await self.connect_body())
        old = first._connection("robot")
        sequence = await old.send_command({"t":"intent", "name":"walk", "dir":"fwd", "steps":0,
                                          "forward":50,"turn":25}, received_at=first.clock())
        await old.wait_acknowledged(sequence, timeout=2)
        self.assertFalse(old.pending[sequence].future.done())
        self.assertEqual(self.native.simulation_endpoint(self.body).decode(), a)
        self.assertNotIn("robot", second.status()["robots"])
        await first.close()
        server.close()
        await asyncio.wait_for(server.wait_closed(), timeout=3)
        result = await old.wait_terminal(sequence, timeout=2)
        self.assertEqual((result["t"], result["code"]), ("cancelled", "disconnect"))
        old_generation = self.generation
        await self.close_body()
        self.assertEqual(self.native.simulation_endpoint(self.body).decode(), b)
        self.assertTrue(await self.connect_body())
        self.assertNotEqual(self.generation, old_generation)
        self.assertEqual(len(self.executed), 1)
        with self.assertRaises(RobotOfflineError):
            first._connection("robot")
        new = second._connection("robot")
        self.assertFalse(new.pending)
        self.assertEqual(new.next_sequence, 1)
        stale = json.dumps({"t":"stop","seq":1,"epoch":1}).encode()
        self.assertEqual(self.native.simulation_accept(self.body, old_generation, stale), -2)
        sequence = await new.send_command({"t":"intent","name":"stand"}, received_at=second.clock())
        self.assertEqual((await new.wait_terminal(sequence, timeout=2))["t"], "done")
        self.assertEqual([m.get("name") for _, m in self.executed], ["walk", "stand"])

    async def test_configured_tls_relay_uses_same_pairing_and_rejects_untrusted_certificate(self):
        _, _, a = await self.gateway(self.first)
        second, _, b = await self.gateway(self.second, tls=True)
        self.body = self.native.simulation_create(a.encode(), b.encode())
        self.generation = self.native.simulation_open(self.body)
        self.native.simulation_failed(self.body, self.generation)
        with self.assertRaises(ssl.SSLCertVerificationError):
            await self.connect_body(trust=False)
        self.assertNotIn("robot", second.status()["robots"])
        self.assertTrue(await self.connect_body())
        connection = second._connection("robot")
        self.assertEqual(connection.transport, "relay")
        sequence = await connection.send_command({"t":"intent","name":"stand"}, received_at=second.clock())
        self.assertEqual((await connection.wait_terminal(sequence, timeout=2))["t"], "done")
        self.assertTrue(DashboardPasswordStore(self.second / "dashboard-auth.json").verify("same-password"))

    async def test_wrong_pairing_is_rejected_then_next_configured_host_can_connect(self):
        first, _, a = await self.gateway(self.first)
        second, _, b = await self.gateway(self.second)
        self.body = self.native.simulation_create(a.encode(), b.encode())
        self.assertFalse(await self.connect_body(token="wrong-token"))
        self.assertNotIn("robot", first.status()["robots"])
        await self.close_body()
        self.assertTrue(await self.connect_body())
        self.assertIn("robot", second.status()["robots"])
        self.assertFalse(self.executed)

    async def test_closed_gateway_rejects_a_new_body_session_with_explicit_reason(self):
        service, _, endpoint = await self.gateway(self.first)
        await service.close()
        async with websockets.connect(endpoint, ping_interval=None) as client:
            await client.send(json.dumps({"t":"hello","ver":1,"fw":"test","id":"robot","auth":"shared-token"}))
            with self.assertRaises(websockets.ConnectionClosed) as closed:
                await client.recv()
            self.assertEqual((closed.exception.code, closed.exception.reason), (1001, "gateway stopped"))
        self.assertNotIn("robot", service.status()["robots"])

    async def test_production_sigterm_releases_body_and_exits_without_waiting_for_robot(self):
        with socket.socket() as gateway_port, socket.socket() as dashboard_port:
            gateway_port.bind(("127.0.0.1", 0))
            dashboard_port.bind(("127.0.0.1", 0))
            ports = [gateway_port.getsockname()[1], dashboard_port.getsockname()[1]]
        environment = {k:v for k,v in os.environ.items() if not k.startswith("AINEKIO_")}
        environment["PYTHONPATH"] = os.pathsep.join(str(ROOT / p) for p in ("Master", "Slave/software"))
        environment["AINEKIO_ENVIRONMENT_ADAPTER_TOKEN"] = "fixture-bridge-token"
        process = await asyncio.create_subprocess_exec(sys.executable, "-u", "-m", "gateway.server",
            "--host", "127.0.0.1", "--port", str(ports[0]), "--dashboard-host", "127.0.0.1",
            "--dashboard-port", str(ports[1]), "--data-dir", str(self.first),
            cwd=ROOT, env=environment, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            # A startup line is printed only after both servers are listening.
            await asyncio.wait_for(process.stdout.readline(), timeout=5)
            async with websockets.connect(f"ws://127.0.0.1:{ports[0]}/robot", ping_interval=None) as client:
                await client.send(json.dumps({"t":"hello","ver":1,"fw":"test","id":"robot","auth":"shared-token"}))
                self.assertEqual(json.loads(await client.recv())["t"], "welcome")
                async with websockets.connect(f"ws://127.0.0.1:{ports[0]}/environment", ping_interval=None) as bridge:
                    await bridge.send(json.dumps({"type":"bridge.connect", "version":ADAPTER_PROTOCOL_VERSION,
                                                  "token":"fixture-bridge-token"}))
                    self.assertEqual(json.loads(await bridge.recv())["type"], "bridge.ready")
                    # An incomplete HTTP handshake must not hold gateway stop
                    # open for the opening timeout either.
                    reader, writer = await asyncio.open_connection("127.0.0.1", ports[0])
                    try:
                        writer.write(b"GET /robot HTTP/1.1\r\nHost: localhost\r\n")
                        await writer.drain()
                        process.send_signal(signal.SIGTERM)
                        self.assertEqual(await asyncio.wait_for(process.wait(), timeout=3), 0)
                        self.assertEqual(await reader.read(), b"")
                        await client.wait_closed()
                        await bridge.wait_closed()
                        self.assertEqual((client.close_code, client.close_reason), (1001, "gateway stopped"))
                        self.assertEqual((bridge.close_code, bridge.close_reason), (1001, "gateway stopped"))
                    finally:
                        writer.close()
                        await writer.wait_closed()
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()

import asyncio
import http.client
import io
import json
import threading

import cbor2


def decode_trace_response(data, content_type):
    """Decode the device trace without changing its records or cursor contract."""
    media_type = content_type.split(';', 1)[0].strip().lower()
    if media_type == 'application/cbor-seq':
        stream = io.BytesIO(data)
        decoder = cbor2.CBORDecoder(stream)
        records = []
        try:
            while stream.tell() < len(data):
                records.append(decoder.decode())
        except cbor2.CBORDecodeError as error:
            raise ValueError('Incomplete or invalid device CBOR trace') from error
        return records
    # Installed firmware before CBOR uses NDJSON during rolling upgrades.
    return [json.loads(line) for line in data.splitlines() if line.strip()]


class TraceSessionChanged(ValueError):
    """The device restarted or another trace_start replaced this recording."""


class RobotLearningTransport:
    """Use the gateway's authenticated LAN robot and token, never user URLs."""
    def __init__(self, gateway, tokens):
        self.gateway, self.tokens = gateway, tokens
        self.locks = {}

    async def request(self, robot, endpoint, payload):
        address = await self.gateway.maintenance_address(robot)
        token = self.tokens.snapshot()[robot]
        lock = self.locks.setdefault(robot, threading.Lock())
        return await asyncio.to_thread(self._serialized_request, lock, address, token, endpoint, payload)

    def _serialized_request(self, lock, address, token, endpoint, payload):
        # A cancelled to_thread await can leave its request running. Preserve
        # read/Stop/drain order on the device's serial maintenance HTTP server.
        # Each completed response releases its socket; trace identity belongs
        # to boot/session/cursor, not an idle TCP connection. No request retries.
        with lock:
            return self._request(address, token, endpoint, payload)

    async def close(self):
        def close_sessions():
            for lock in tuple(self.locks.values()):
                with lock:
                    pass  # Drain workers whose asyncio await was cancelled.
        await asyncio.to_thread(close_sessions)

    @staticmethod
    def _request(address, token, endpoint, payload):
        connection = http.client.HTTPConnection(address, 80, timeout=30)
        try:
            connection.request("POST" if payload is not None else "GET", "/api/"+endpoint,
                               json.dumps(payload) if payload is not None else None,
                               {"Authorization": "Bearer "+token, "Content-Type": "application/json",
                                "Connection": "close"})
            response = connection.getresponse()
            data = response.read()
            if response.status != 200:
                if response.status == 409 and (payload or {}).get("op", "").startswith("trace_"):
                    if json.loads(data).get("error") == "Trace session changed":
                        raise TraceSessionChanged("Device trace session changed")
                raise ValueError(f"Robot {endpoint}: HTTP {response.status}: {data.decode()}")
            if (payload or {}).get("op", "").startswith("trace_"):
                return decode_trace_response(data, response.getheader('Content-Type', 'application/x-ndjson'))
            return json.loads(data)
        finally:
            connection.close()

import asyncio
import http.client
import json
import threading


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
            connection.request(
                "POST" if payload is not None else "GET",
                "/api/" + endpoint,
                json.dumps(payload) if payload is not None else None,
                {
                    "Authorization": "Bearer " + token,
                    "Content-Type": "application/json",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            data = response.read()
            if response.status != 200:
                raise ValueError(f"Robot {endpoint}: HTTP {response.status}: {data.decode()}")
            return json.loads(data)
        finally:
            connection.close()

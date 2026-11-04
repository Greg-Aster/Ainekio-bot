import asyncio
import http.client
import json
import threading


class TraceSessionChanged(ValueError):
    """The device restarted or another trace_start replaced this recording."""


class RobotLearningTransport:
    """Use the gateway's authenticated LAN robot and token, never user URLs."""
    def __init__(self, gateway, tokens, *, persistent=True):
        self.gateway, self.tokens = gateway, tokens
        self.persistent = persistent
        self.sessions = {}

    async def request(self, robot, endpoint, payload):
        address = await self.gateway.maintenance_address(robot)
        token = self.tokens.snapshot()[robot]
        if not self.persistent:
            # Inference may outlast the robot's HTTP idle connection. Sparse
            # observations own a fresh socket; streamed traces retain reuse.
            return await asyncio.to_thread(self._request, address, token, endpoint, payload)
        session = self.sessions.setdefault(robot, {"lock": threading.Lock(), "address": None, "connection": None})
        return await asyncio.to_thread(self._persistent_request, session, address, token, endpoint, payload)

    def _persistent_request(self, session, address, token, endpoint, payload):
        # HTTP/1.1 request/response pairs on one socket must be serialized.
        # This lock belongs only to this robot's measurement/model HTTP stream;
        # semantic commands, camera and other robots use their existing owners.
        with session["lock"]:
            if session["address"] != address or session["connection"] is None:
                if session["connection"] is not None:
                    session["connection"].close()
                session.update(address=address, connection=http.client.HTTPConnection(address, 80, timeout=30))
            try:
                return self._request(address, token, endpoint, payload, session["connection"])
            except Exception:
                session["connection"].close()
                session["connection"] = None
                raise  # Existing caller reports failure; no request is replayed here.

    async def close(self):
        def close_sessions():
            for session in self.sessions.values():
                with session["lock"]:
                    if session["connection"] is not None:
                        session["connection"].close()
                        session["connection"] = None
        await asyncio.to_thread(close_sessions)

    @staticmethod
    def _request(address, token, endpoint, payload, connection=None):
        owned = connection is None
        if owned:
            connection = http.client.HTTPConnection(address, 80, timeout=30)
        try:
            connection.request("POST" if payload is not None else "GET", "/api/"+endpoint,
                               json.dumps(payload) if payload is not None else None,
                               {"Authorization": "Bearer "+token, "Content-Type": "application/json"})
            response = connection.getresponse()
            data = response.read().decode()
            if response.status != 200:
                if response.status == 409 and (payload or {}).get("op", "").startswith("trace_"):
                    if json.loads(data).get("error") == "Trace session changed":
                        raise TraceSessionChanged("Device trace session changed")
                raise ValueError(f"Robot {endpoint}: HTTP {response.status}: {data}")
            if (payload or {}).get("op", "").startswith("trace_"):
                return [json.loads(line) for line in data.splitlines() if line.strip()]
            return json.loads(data)
        finally:
            if owned:
                connection.close()

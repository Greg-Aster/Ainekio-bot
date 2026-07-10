from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterator
from urllib import error, parse, request


class MetaHumanBridgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class BridgeEvent:
    event: str
    data: dict[str, Any]


@dataclass(frozen=True)
class MetaHumanBridgeClient:
    base_url: str
    timeout_s: float = 5.0

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            self._url(path),
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._open_json(req)

    def stream_events(self, path: str, *, query: dict[str, Any] | None = None) -> Iterator[BridgeEvent]:
        url = self._url(path)
        if query:
            url = f"{url}?{parse.urlencode(query)}"
        req = request.Request(url, headers={"Accept": "text/event-stream"}, method="GET")

        try:
            with request.urlopen(req, timeout=None) as response:
                event = "message"
                data_lines: list[str] = []
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if line == "":
                        if data_lines:
                            yield BridgeEvent(event, _parse_event_data("\n".join(data_lines)))
                        event = "message"
                        data_lines = []
                        continue
                    if line.startswith(":"):
                        continue
                    field, _, value = line.partition(":")
                    value = value[1:] if value.startswith(" ") else value
                    if field == "event":
                        event = value or "message"
                    elif field == "data":
                        data_lines.append(value)
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise MetaHumanBridgeError(f"MetaHuman bridge stream HTTP {exc.code}: {detail}") from exc
        except OSError as exc:
            raise MetaHumanBridgeError(f"MetaHuman bridge stream failed: {exc}") from exc

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"

    def _open_json(self, req: request.Request) -> dict[str, Any]:
        try:
            with request.urlopen(req, timeout=self.timeout_s) as response:
                data = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise MetaHumanBridgeError(f"MetaHuman bridge HTTP {exc.code}: {detail}") from exc
        except OSError as exc:
            raise MetaHumanBridgeError(f"MetaHuman bridge request failed: {exc}") from exc

        if not data:
            return {}
        parsed = json.loads(data)
        if not isinstance(parsed, dict):
            raise MetaHumanBridgeError("MetaHuman bridge returned non-object JSON")
        return parsed


def _parse_event_data(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise MetaHumanBridgeError("MetaHuman bridge stream returned non-object event data")
    return parsed

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request


MAX_HTTP_RESPONSE_BYTES = 64 * 1024
MAX_SSE_LINE_BYTES = 64 * 1024
MAX_SSE_EVENT_BYTES = 256 * 1024


class MetaHumanBridgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class BridgeEvent:
    event: str
    data: dict[str, Any]


@dataclass(frozen=True)
class MetaHumanBridgeClient:
    base_url: str
    service_token: str = ""
    timeout_s: float = 5.0

    def __post_init__(self) -> None:
        parsed = parse.urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("MetaHuman base URL must be HTTP or HTTPS")
        if parsed.path.rstrip("/").endswith("/robot"):
            raise ValueError("MetaHuman bridge client cannot target the robot endpoint")
        if not self.service_token.strip() or len(self.service_token) > 512:
            raise ValueError("MetaHuman bridge service token is required and must be bounded")

    def post_json(self, path: str, payload: Mapping[str, object]) -> dict[str, Any]:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if len(body) > MAX_HTTP_RESPONSE_BYTES:
            raise MetaHumanBridgeError("MetaHuman bridge request exceeds its size limit")
        req = request.Request(
            self._url(path),
            data=body,
            headers={
                "Authorization": f"Bearer {self.service_token.strip()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        return self._open_json(req)

    def stream_events(
        self,
        path: str,
        *,
        query: Mapping[str, object] | None = None,
    ) -> Iterator[BridgeEvent]:
        url = self._url(path)
        if query:
            url = f"{url}?{parse.urlencode(query)}"
        req = request.Request(
            url,
            headers={
                "Accept": "text/event-stream",
                "Authorization": f"Bearer {self.service_token.strip()}",
            },
            method="GET",
        )

        try:
            with request.urlopen(req, timeout=None) as response:
                event = "message"
                data_lines: list[str] = []
                data_bytes = 0
                while True:
                    raw_line = response.readline(MAX_SSE_LINE_BYTES + 1)
                    if not raw_line:
                        return
                    if len(raw_line) > MAX_SSE_LINE_BYTES:
                        raise MetaHumanBridgeError("MetaHuman bridge SSE line is oversized")
                    line = raw_line.decode("utf-8", errors="strict").rstrip("\r\n")
                    if line == "":
                        if data_lines:
                            yield BridgeEvent(event, _parse_event_data("\n".join(data_lines)))
                        event = "message"
                        data_lines = []
                        data_bytes = 0
                        continue
                    if line.startswith(":"):
                        continue
                    field, separator, value = line.partition(":")
                    if separator and value.startswith(" "):
                        value = value[1:]
                    if field == "event":
                        event = value or "message"
                    elif field == "data":
                        data_bytes += len(value.encode("utf-8"))
                        if data_bytes > MAX_SSE_EVENT_BYTES:
                            raise MetaHumanBridgeError("MetaHuman bridge SSE event is oversized")
                        data_lines.append(value)
        except error.HTTPError as exc:
            detail = exc.read(MAX_HTTP_RESPONSE_BYTES).decode("utf-8", errors="replace")
            raise MetaHumanBridgeError(
                f"MetaHuman bridge stream HTTP {exc.code}: {detail}"
            ) from exc
        except (OSError, UnicodeDecodeError) as exc:
            raise MetaHumanBridgeError(f"MetaHuman bridge stream failed: {exc}") from exc

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"

    def _open_json(self, req: request.Request) -> dict[str, Any]:
        try:
            with request.urlopen(req, timeout=self.timeout_s) as response:
                data = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
        except error.HTTPError as exc:
            detail = exc.read(MAX_HTTP_RESPONSE_BYTES).decode("utf-8", errors="replace")
            raise MetaHumanBridgeError(
                f"MetaHuman bridge HTTP {exc.code}: {detail}"
            ) from exc
        except OSError as exc:
            raise MetaHumanBridgeError(f"MetaHuman bridge request failed: {exc}") from exc
        if len(data) > MAX_HTTP_RESPONSE_BYTES:
            raise MetaHumanBridgeError("MetaHuman bridge response is oversized")
        if not data:
            return {}
        try:
            parsed = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MetaHumanBridgeError("MetaHuman bridge returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise MetaHumanBridgeError("MetaHuman bridge returned non-object JSON")
        return parsed


def _parse_event_data(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise MetaHumanBridgeError("MetaHuman bridge stream returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise MetaHumanBridgeError("MetaHuman bridge stream returned non-object event data")
    return parsed

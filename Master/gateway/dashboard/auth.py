from __future__ import annotations

import json
import hashlib
import math
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Callable

from gateway.security import _atomic_secure_json, _read_json


SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
MAX_SESSIONS = 32
LOGIN_WINDOW_SECONDS = 60.0
LOGIN_ATTEMPTS_PER_WINDOW = 5
MAX_AUDIT_BYTES = 1024 * 1024


@dataclass(frozen=True)
class DashboardSession:
    csrf_token: str
    expires_at: float


class DashboardSessions:
    def __init__(
        self,
        *,
        path: Path | None = None,
        password_revision: str = "",
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._clock = clock
        self._path = path
        self._password_revision = password_revision
        self._sessions: dict[str, DashboardSession] = {}
        self._lock = threading.Lock()
        if path is not None and path.exists():
            record = _read_json(path)
            if not isinstance(record, dict) or record.get("schema_version") != 1:
                raise RuntimeError("dashboard session store has an unsupported schema")
            if record.get("password_revision") == password_revision:
                entries = record.get("sessions")
                if not isinstance(entries, dict) or len(entries) > MAX_SESSIONS:
                    raise RuntimeError("dashboard session store is malformed")
                for digest, entry in entries.items():
                    if (
                        not isinstance(digest, str) or len(digest) != 64
                        or any(character not in "0123456789abcdef" for character in digest)
                        or not isinstance(entry, dict)
                        or not isinstance(entry.get("csrf_token"), str)
                        or not 1 <= len(entry["csrf_token"]) <= 128
                        or type(entry.get("expires_at")) not in (int, float)
                        or not math.isfinite(entry["expires_at"])
                    ):
                        raise RuntimeError("dashboard session store contains an invalid entry")
                    self._sessions[digest] = DashboardSession(**entry)
            self._prune_locked()
            self._save_locked()

    def create(self) -> tuple[str, DashboardSession]:
        token = secrets.token_urlsafe(32)
        session = DashboardSession(
            csrf_token=secrets.token_urlsafe(24),
            expires_at=self._clock() + SESSION_TTL_SECONDS,
        )
        with self._lock:
            self._sessions[self._digest(token)] = session
            self._prune_locked()
            while len(self._sessions) > MAX_SESSIONS:
                oldest = min(self._sessions, key=lambda key: self._sessions[key].expires_at)
                del self._sessions[oldest]
            self._save_locked()
        return token, session

    def get(self, token: str | None) -> DashboardSession | None:
        if not token:
            return None
        with self._lock:
            digest = self._digest(token)
            session = self._sessions.get(digest)
            if session is None:
                return None
            if session.expires_at <= self._clock():
                del self._sessions[digest]
                self._save_locked()
                return None
            return session

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(self._digest(token), None)
            self._save_locked()

    def password_changed(self, revision: str, keep_token: str) -> None:
        with self._lock:
            digest = self._digest(keep_token)
            current = self._sessions.get(digest)
            self._sessions = {digest: current} if current is not None else {}
            self._password_revision = revision
            self._save_locked()

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _save_locked(self) -> None:
        if self._path is not None:
            _atomic_secure_json(self._path, {
                "schema_version": 1,
                "password_revision": self._password_revision,
                "sessions": {
                    digest: {"csrf_token": session.csrf_token, "expires_at": session.expires_at}
                    for digest, session in self._sessions.items()
                },
            })

    def _prune_locked(self) -> None:
        now = self._clock()
        for token, session in tuple(self._sessions.items()):
            if session.expires_at <= now:
                del self._sessions[token]


class LoginRateLimiter:
    def __init__(self, *, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow_attempt(self, address: str) -> bool:
        now = self._clock()
        with self._lock:
            attempts = self._attempts[address]
            while attempts and now - attempts[0] >= LOGIN_WINDOW_SECONDS:
                attempts.popleft()
            if len(attempts) >= LOGIN_ATTEMPTS_PER_WINDOW:
                return False
            attempts.append(now)
            return True

    def clear(self, address: str) -> None:
        with self._lock:
            self._attempts.pop(address, None)


class AuditLog:
    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._entries: deque[dict[str, object]] = deque(maxlen=500)
        self._lock = threading.Lock()

    def record(self, event: str, **details: object) -> None:
        entry = {
            "timestamp": int(time.time()),
            "event": event,
            **details,
        }
        encoded = (json.dumps(entry, separators=(",", ":")) + "\n").encode("utf-8")
        with self._lock:
            self._entries.append(entry)
            if self.path is not None:
                self._append_locked(encoded)

    def entries(self) -> list[dict[str, object]]:
        with self._lock:
            return [dict(entry) for entry in self._entries]

    def _append_locked(self, encoded: bytes) -> None:
        assert self.path is not None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and self.path.stat().st_size + len(encoded) > MAX_AUDIT_BYTES:
            rotated = self.path.with_suffix(f"{self.path.suffix}.1")
            try:
                rotated.unlink()
            except FileNotFoundError:
                pass
            os.replace(self.path, rotated)
        descriptor = os.open(
            self.path,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o600,
        )
        with os.fdopen(descriptor, "ab") as handle:
            handle.write(encoded)
        os.chmod(self.path, 0o600)

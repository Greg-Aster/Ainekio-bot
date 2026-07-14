from __future__ import annotations

import json
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Callable


SESSION_TTL_SECONDS = 8 * 60 * 60
LOGIN_WINDOW_SECONDS = 60.0
LOGIN_ATTEMPTS_PER_WINDOW = 5
MAX_AUDIT_BYTES = 1024 * 1024


@dataclass(frozen=True)
class DashboardSession:
    csrf_token: str
    expires_at: float


class DashboardSessions:
    def __init__(self, *, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._sessions: dict[str, DashboardSession] = {}
        self._lock = threading.Lock()

    def create(self) -> tuple[str, DashboardSession]:
        token = secrets.token_urlsafe(32)
        session = DashboardSession(
            csrf_token=secrets.token_urlsafe(24),
            expires_at=self._clock() + SESSION_TTL_SECONDS,
        )
        with self._lock:
            self._sessions[token] = session
            self._prune_locked()
        return token, session

    def get(self, token: str | None) -> DashboardSession | None:
        if not token:
            return None
        with self._lock:
            session = self._sessions.get(token)
            if session is None:
                return None
            if session.expires_at <= self._clock():
                del self._sessions[token]
                return None
            return session

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)

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

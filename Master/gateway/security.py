from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import stat
import threading
from pathlib import Path
from typing import TextIO


SECURE_FILE_MODE = 0o600
MAX_SECURITY_FILE_BYTES = 64 * 1024
PASSWORD_ITERATIONS = 240_000


class RobotTokenStore:
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._pending: dict[str, str] = {}
        self._tokens = self._load()

    def snapshot(self) -> dict[str, str]:
        return dict(self._tokens)

    def set(self, robot_id: str, token: str) -> None:
        _validate_robot_token(robot_id, token)
        with self._lock:
            updated = {**self._tokens, robot_id: token}
            previous = dict(self._pending)
            self._pending.pop(robot_id, None)
            try:
                self._write(updated)
            except Exception:
                self._pending = previous
                raise
            self._tokens = updated

    def generate(self, robot_id: str) -> str:
        token = secrets.token_urlsafe(32)
        self.set(robot_id, token)
        return token

    def revoke(self, robot_id: str) -> None:
        with self._lock:
            if robot_id not in self._tokens:
                return
            updated = dict(self._tokens)
            del updated[robot_id]
            previous = dict(self._pending)
            self._pending.pop(robot_id, None)
            try:
                self._write(updated)
            except Exception:
                self._pending = previous
                raise
            self._tokens = updated

    def _load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        value = _read_json(self.path)
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise RuntimeError("robot token store has an unsupported schema")
        tokens = value.get("tokens")
        if not isinstance(tokens, dict):
            raise RuntimeError("robot token store is malformed")
        result: dict[str, str] = {}
        for robot_id, token in tokens.items():
            if not isinstance(robot_id, str) or not isinstance(token, str):
                raise RuntimeError("robot token store contains an invalid entry")
            _validate_robot_token(robot_id, token)
            result[robot_id] = token
        pending = value.get("pending", {})
        if not isinstance(pending, dict):
            raise RuntimeError("robot token transitions are malformed")
        for robot_id, token in pending.items():
            if robot_id not in result or not isinstance(token, str):
                raise RuntimeError("robot token transition is invalid")
            _validate_robot_token(robot_id, token)
        self._pending = dict(pending)
        return result

    def stage(self, robot_id: str, token: str) -> None:
        _validate_robot_token(robot_id, token)
        with self._lock:
            if robot_id not in self._tokens:
                raise ValueError("robot is not paired")
            pending = self._pending.get(robot_id)
            if pending is not None and pending != token:
                raise ValueError("a pairing change is awaiting reconnect; apply it before changing the token again")
            previous = dict(self._pending)
            self._pending[robot_id] = token
            try:
                self._write(self._tokens)
            except Exception:
                self._pending = previous
                raise

    def matches(self, robot_id: str, token: str) -> bool:
        with self._lock:
            pending = self._pending.get(robot_id)
            if pending is not None and hmac.compare_digest(pending.encode(), token.encode()):
                self.set(robot_id, token)
                return True
            current = self._tokens.get(robot_id)
            return current is not None and hmac.compare_digest(current.encode(), token.encode())

    def _write(self, tokens: dict[str, str]) -> None:
        _atomic_secure_json(
            self.path,
            {"schema_version": 1, "tokens": tokens, "pending": self._pending},
        )


class DashboardPasswordStore:
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def initialize(
        self,
        *,
        output: TextIO | None = None,
        password: str | None = None,
    ) -> str | None:
        if self.path.exists():
            self._record()
            return None
        if password is not None:
            self.set_password(password)
            return password
        if output is None or not output.isatty():
            raise RuntimeError(
                "dashboard password store is missing and no interactive TTY is available"
            )
        password = secrets.token_urlsafe(18)
        output.write(f"Ainekio dashboard password: {password}\n")
        output.flush()
        self.set_password(password)
        return password

    def set_password(self, password: str) -> None:
        salt = secrets.token_bytes(32)
        verifier = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            PASSWORD_ITERATIONS,
        )
        _atomic_secure_json(
            self.path,
            {
                "schema_version": 1,
                "algorithm": "pbkdf2-sha256",
                "iterations": PASSWORD_ITERATIONS,
                "salt": base64.b64encode(salt).decode("ascii"),
                "verifier": base64.b64encode(verifier).decode("ascii"),
            },
        )

    def verify(self, password: str) -> bool:
        record = self._record()
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            record["salt"],
            record["iterations"],
        )
        return hmac.compare_digest(candidate, record["verifier"])

    def revision(self) -> str:
        record = self._record()
        return hashlib.sha256(record["salt"] + record["verifier"]).hexdigest()

    def _record(self) -> dict[str, object]:
        value = _read_json(self.path)
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != 1
            or value.get("algorithm") != "pbkdf2-sha256"
            or value.get("iterations") != PASSWORD_ITERATIONS
            or not isinstance(value.get("salt"), str)
            or not isinstance(value.get("verifier"), str)
        ):
            raise RuntimeError("dashboard password store has an unsupported schema")
        try:
            salt = base64.b64decode(value["salt"], validate=True)
            verifier = base64.b64decode(value["verifier"], validate=True)
        except (ValueError, TypeError) as exc:
            raise RuntimeError("dashboard password store contains invalid base64") from exc
        if len(salt) != 32 or len(verifier) != 32:
            raise RuntimeError("dashboard password store contains invalid verifier data")
        return {
            "iterations": value["iterations"],
            "salt": salt,
            "verifier": verifier,
        }


def _validate_robot_token(robot_id: str, token: str) -> None:
    if not 1 <= len(robot_id) <= 64:
        raise ValueError("robot_id must contain 1 to 64 characters")
    if not 1 <= len(token) <= 128:
        raise ValueError("robot token must contain 1 to 128 characters")


def _read_json(path: Path) -> object:
    if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise RuntimeError(f"security file {path} must use owner-only permissions")
    raw = path.read_bytes()
    if len(raw) > MAX_SECURITY_FILE_BYTES:
        raise RuntimeError(f"security file {path} exceeds its size limit")
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"security file {path} is invalid JSON") from exc


def _atomic_secure_json(path: Path, value: object) -> None:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_SECURITY_FILE_BYTES:
        raise OSError("security file exceeds its size limit")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        SECURE_FILE_MODE,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, SECURE_FILE_MODE)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise

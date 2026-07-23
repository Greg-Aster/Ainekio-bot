from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import stat
from pathlib import Path
from typing import TextIO


SECURE_FILE_MODE = 0o600
MAX_SECURITY_FILE_BYTES = 64 * 1024
PASSWORD_ITERATIONS = 240_000


class RobotTokenStore:
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._tokens = self._load()

    def snapshot(self) -> dict[str, str]:
        return dict(self._tokens)

    def set(self, robot_id: str, token: str) -> None:
        _validate_robot_token(robot_id, token)
        updated = dict(self._tokens)
        updated[robot_id] = token
        self._write(updated)
        self._tokens = updated

    def generate(self, robot_id: str) -> str:
        token = secrets.token_urlsafe(32)
        self.set(robot_id, token)
        return token

    def revoke(self, robot_id: str) -> None:
        if robot_id not in self._tokens:
            return
        updated = dict(self._tokens)
        del updated[robot_id]
        self._write(updated)
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
        return result

    def _write(self, tokens: dict[str, str]) -> None:
        _atomic_secure_json(
            self.path,
            {"schema_version": 1, "tokens": tokens},
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
        if password is not None:
            self.set_password(password)
            return password
        if self.path.exists():
            self._record()
            return None
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
        if not 12 <= len(password) <= 256:
            raise ValueError("dashboard password must contain 12 to 256 characters")
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

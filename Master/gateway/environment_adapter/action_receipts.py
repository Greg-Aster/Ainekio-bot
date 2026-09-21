"""Persistent receipts at the adapter's physical acceptance boundary."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from time import time
from typing import Any, AsyncIterator, Iterator, Mapping

from gateway.server.service import GatewayError


class ActionConflictError(GatewayError):
    """A delivery cannot replace the immutable action bearing this ID."""


def encoded(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class ActionReceipts:
    def __init__(self, path: str) -> None:
        if not path:
            raise ValueError("adapter receipt database path is required")
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.db = sqlite3.connect(path, isolation_level=None, timeout=5, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS body_owner (
              body_id TEXT PRIMARY KEY, generation INTEGER NOT NULL, execution_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS actions (
              id TEXT PRIMARY KEY, payload TEXT NOT NULL, accepted TEXT NOT NULL,
              state TEXT NOT NULL, wire TEXT, result TEXT, updated REAL NOT NULL, observation_recorded INTEGER NOT NULL DEFAULT 0,
              cancellation_only INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS delivery (
              id TEXT PRIMARY KEY, action_id TEXT, envelope TEXT NOT NULL, created REAL NOT NULL);
        """)
        if "cancellation_only" not in {row[1] for row in self.db.execute("PRAGMA table_info(actions)")}:
            self.db.execute("ALTER TABLE actions ADD COLUMN cancellation_only INTEGER NOT NULL DEFAULT 0")
        if path != ":memory:":
            os.chmod(path, 0o600)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def action(self, action_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self._action(action_id)

    def _action(self, action_id: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()

    def _assert_owner(self, action: Mapping[str, Any], *, advance: bool) -> None:
        lease = action.get("bodyLease")
        if action.get("type") == "speechAudio":
            return
        if not isinstance(lease, dict) or not isinstance(lease.get("bodyId"), str) or not isinstance(lease.get("executionId"), str) or type(lease.get("generation")) is not int or lease["generation"] < 1:
            raise GatewayError("physical action requires a Coordinator body lease")
        current = self.db.execute("SELECT * FROM body_owner WHERE body_id=?", (lease["bodyId"],)).fetchone()
        if current and (lease["generation"] < current["generation"] or (lease["generation"] == current["generation"] and lease["executionId"] != current["execution_id"])):
            raise GatewayError("stale body ownership")
        if not advance and (not current or current["generation"] != lease["generation"] or current["execution_id"] != lease["executionId"]):
            raise GatewayError("body ownership changed before dispatch")
        if advance:
            self.db.execute("INSERT INTO body_owner VALUES (?,?,?) ON CONFLICT(body_id) DO UPDATE SET generation=excluded.generation, execution_id=excluded.execution_id", (lease["bodyId"], lease["generation"], lease["executionId"]))

    def receive(self, action: dict[str, Any], accepted: Mapping[str, object]) -> dict[str, Any]:
        payload = {key: value for key, value in action.items() if key != "timing"}
        with self.transaction():
            previous = self._action(str(action["id"]))
            if previous:
                if previous["cancellation_only"]:
                    if json.loads(previous["payload"])["bodyLease"] != payload.get("bodyLease"):
                        raise ActionConflictError("cancelled action id reused for a different body owner")
                    return json.loads(previous["result"])
                if previous["payload"] != encoded(payload):
                    raise ActionConflictError("action id reused with different content")
                return json.loads(previous["result"] or previous["accepted"])
            self._assert_owner(payload, advance=True)
            self.db.execute("INSERT INTO actions(id,payload,accepted,state,updated) VALUES (?,?,?,'received',?)", (action["id"], encoded(payload), encoded(accepted), time()))
            return dict(accepted)

    def begin(self, action_id: str, wire: Mapping[str, object]) -> None:
        with self.transaction():
            row = self._action(action_id)
            if row is None or row["state"] != "received":
                raise GatewayError("action was already started or completed")
            self._assert_owner(json.loads(row["payload"]), advance=False)
            self.db.execute("UPDATE actions SET state='started',wire=?,updated=? WHERE id=?", (encoded(wire), time(), action_id))

    def request_cancel(self, action_id: str, lease: object, cancelled: Mapping[str, object]) -> sqlite3.Row:
        with self.transaction():
            row = self._action(action_id)
            if row is None:
                if not isinstance(lease, dict) or not isinstance(lease.get("bodyId"), str) or not isinstance(lease.get("executionId"), str) or type(lease.get("generation")) is not int or lease["generation"] < 1:
                    raise ActionConflictError("cancellation requires the dispatched body lease")
                # Cancellation may overtake the original delivery. Persist its
                # receipt before ACK so a late original can never execute.
                self.db.execute("INSERT INTO actions(id,payload,accepted,state,result,updated,cancellation_only) VALUES (?,?,?,'terminal',?,?,1)",
                    (action_id, encoded({"id": action_id, "bodyLease": lease}), encoded(cancelled), encoded(cancelled), time()))
                return self._action(action_id)
            payload = json.loads(row["payload"])
            if payload.get("type") != "speechAudio" and payload.get("bodyLease") != lease:
                raise ActionConflictError("cancellation identifies a different body owner")
            if row["state"] != "terminal":
                self._assert_owner(payload, advance=False)
                self.db.execute("UPDATE actions SET state='cancelling',updated=? WHERE id=?", (time(), action_id))
            return row

    def _acquire_dispatch(self, action_id: str, expected_state: str = "started") -> None:
        self._lock.acquire()
        try:
            self.db.execute("BEGIN IMMEDIATE")
            row = self._action(action_id)
            if row is None or row["state"] != expected_state:
                raise GatewayError("action is not awaiting wire dispatch")
            self._assert_owner(json.loads(row["payload"]), advance=False)
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            self._lock.release()
            raise

    def _release_dispatch(self) -> None:
        try:
            self.db.execute("COMMIT")
        finally:
            self._lock.release()

    @asynccontextmanager
    async def dispatch(self, action_id: str, wire: Mapping[str, object]) -> AsyncIterator[None]:
        # This commit precedes any physical send, so a crash can never replay a
        # possibly accepted action. The following transaction fences the actual
        # bounded socket send, not merely preparation before an await.
        await asyncio.to_thread(self.begin, action_id, wire)
        async with self._wire_guard(action_id, "started"):
            yield

    @asynccontextmanager
    async def cancellation_dispatch(self, action_id: str) -> AsyncIterator[None]:
        async with self._wire_guard(action_id, "cancelling"):
            yield

    @asynccontextmanager
    async def _wire_guard(self, action_id: str, state: str) -> AsyncIterator[None]:
        acquisition = asyncio.create_task(asyncio.to_thread(self._acquire_dispatch, action_id, state))
        try:
            await asyncio.shield(acquisition)
        except asyncio.CancelledError:
            # Cancelling a coroutine cannot cancel SQLite's worker thread.
            # Transfer cleanup to the acquisition itself: another cancellation
            # must not interrupt an await and abandon a subsequently held lock.
            def release_acquired(task: asyncio.Task[None]) -> None:
                if not task.cancelled() and task.exception() is None:
                    self._release_dispatch()
            acquisition.add_done_callback(release_acquired)
            raise
        try:
            yield
        finally:
            # This thread already owns the read-only guard transaction. Pool
            # workers can all be waiting for its lock; release must not queue
            # behind those waiters. COMMIT performs no physical or network I/O.
            self._release_dispatch()

    def queue_feedback(self, envelope: dict[str, Any]) -> dict[str, Any]:
        feedback = envelope["feedback"]
        with self.transaction():
            row = self._action(str(feedback.get("actionId", "")))
            if row and feedback["type"] != "accepted":
                previous = json.loads(row["result"]) if row["result"] else None
                if previous and (row["state"] == "terminal" or previous["id"] == feedback["id"]):
                    # Natural completion and cancellation can race. The first
                    # committed terminal receipt is returned to both callers.
                    feedback = previous
                self.db.execute("UPDATE actions SET state=?,result=?,updated=? WHERE id=?", (
                    "outcome_unknown" if feedback["type"] == "outcome_unknown" else "terminal",
                    encoded(feedback), time(), feedback["actionId"]))
                payload = json.loads(row["payload"])
                wire = json.loads(row["wire"]) if row["wire"] else {}
                if wire.get("kind") == "stop" and feedback["type"] == "completed":
                    lease = payload["bodyLease"]
                    for prior in self.db.execute("SELECT * FROM actions WHERE state != 'terminal'").fetchall():
                        prior_lease = json.loads(prior["payload"]).get("bodyLease", {})
                        if prior_lease.get("bodyId") != lease["bodyId"] or prior_lease.get("generation", 0) >= lease["generation"]:
                            continue
                        cancelled = {"id": f"{prior['id']}:stopped-by:{row['id']}", "actionId": prior["id"],
                            "timestamp": feedback["timestamp"], "type": "cancelled",
                            "message": "A later stop ended this action's control of the body; any earlier physical effect remains unverified.",
                            "data": {"stoppedByActionId": row["id"], "bodyLease": lease,
                                "priorOutcome": json.loads(prior["result"]) if prior["result"] else None,
                                "earlierEffectUnknown": prior["wire"] is not None}}
                        self.db.execute("UPDATE actions SET state='terminal',result=?,updated=?,observation_recorded=1 WHERE id=?",
                            (encoded(cancelled), time(), prior["id"]))
                        self._queue(cancelled["id"], prior["id"], {**envelope, "feedback": cancelled})
            message = {**envelope, "feedback": feedback}
            return self._queue(str(feedback["id"]), feedback.get("actionId"), message)

    def _queue(self, message_id: str, action_id: str | None, envelope: Mapping[str, object]) -> dict[str, Any]:
        previous = self.db.execute("SELECT envelope FROM delivery WHERE id=?", (message_id,)).fetchone()
        if previous:
            if previous[0] != encoded(envelope):
                raise GatewayError("delivery id reused with different content")
            return json.loads(previous[0])
        self.db.execute("INSERT INTO delivery VALUES (?,?,?,?)", (message_id, action_id, encoded(envelope), time()))
        if action_id and envelope.get("type") == "environment.observation":
            self.db.execute("UPDATE actions SET observation_recorded=1 WHERE id=?", (action_id,))
        return dict(envelope)

    def queue(self, message_id: str, action_id: str | None, envelope: Mapping[str, object]) -> dict[str, Any]:
        with self.transaction():
            return self._queue(message_id, action_id, envelope)

    def acknowledge(self, message_id: str) -> None:
        with self.transaction():
            self.db.execute("DELETE FROM delivery WHERE id=?", (message_id,))

    def pending(self) -> list[dict[str, Any]]:
        with self._lock:
            return [json.loads(row[0]) for row in self.db.execute("SELECT envelope FROM delivery ORDER BY created,id")]

    def recoverable(self) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.db.execute("SELECT * FROM actions WHERE state != 'terminal' OR observation_recorded=0 ORDER BY updated"))

    def prune(self, before: float) -> None:
        with self.transaction():
            self.db.execute("DELETE FROM actions WHERE state='terminal' AND observation_recorded=1 AND updated<? AND NOT EXISTS (SELECT 1 FROM delivery WHERE action_id=actions.id)", (before,))

    def close(self) -> None:
        with self._lock:
            self.db.close()

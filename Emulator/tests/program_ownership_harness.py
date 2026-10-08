"""JSON-lines software body for paired MetaHuman/gateway contract tests.

Run with PYTHONPATH=Master:Slave/software:Emulator:Emulator/tests. Nothing
listens on a socket and no providers, cameras, audio, or hardware are accessed.
The adapter, dashboard command route, receipt store, and gateway send owner are
production code; only the body's wire and terminal messages are simulated.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import replace

import gateway.environment_adapter.server as adapter_server
from Emulator.tests.test_active_movement import ActiveMovementTests


class ProgramBody:
    def __init__(self) -> None:
        self.fixture = ActiveMovementTests()
        self.fixture.setUp()
        if session := os.environ.get("AINEKIO_TEST_SESSION"):
            self.fixture.adapter.config = replace(self.fixture.adapter.config, session_id=session)
        self.fixture.adapter._bridge_ready = True
        self.actions: dict[str, asyncio.Task] = {}
        self.bridge_cursor = 0
        adapter_server.CANCELLATION_TIMEOUT_SECONDS = 0.05

    def snapshot(self) -> dict:
        fixture = self.fixture
        events = [json.loads(item) for item in fixture.bridge.sent[self.bridge_cursor:]]
        self.bridge_cursor = len(fixture.bridge.sent)
        return {"observation": fixture.adapter._observation(), "events": events,
            "wire": [json.loads(item) for item in fixture.body.sent],
            "receipts": {identifier: json.loads(row["result"] or row["accepted"])
                for identifier in self.actions
                if (row := fixture.adapter.receipts.action(identifier)) is not None}}

    async def await_dispatch(self, task: asyncio.Task, before: int) -> None:
        async def ready():
            while not task.done() and len(self.fixture.body.sent) == before:
                await asyncio.sleep(0.001)
            if task.done():
                await task
        await asyncio.wait_for(ready(), 5)

    async def request(self, request: dict) -> dict:
        fixture = self.fixture
        operation = request["op"]
        if operation == "action":
            payload = request["action"]
            accepted = fixture.adapter._feedback(payload["id"], "accepted", "accepted",
                command=str(payload.get("type", "environment.action")))
            accepted = await asyncio.to_thread(fixture.adapter.receipts.receive, payload, accepted)
            await fixture.adapter._send_feedback(accepted)
            row = fixture.adapter.receipts.action(payload["id"])
            if row["state"] == "received":
                before = len(fixture.body.sent)
                previous = set(fixture.adapter._action_tasks)
                await fixture.adapter._acknowledge_feedback(accepted["id"], admitted=True)
                for task in fixture.adapter._action_tasks - previous:
                    self.actions[payload["id"]] = task
                    await self.await_dispatch(task, before)
        elif operation == "manual":
            await fixture.manual_walk()
        elif operation == "complete":
            action_id = request.get("actionId")
            if action_id:
                row = fixture.adapter.receipts.action(action_id)
                sequence = json.loads(row["wire"])["sequence"]
            else:
                sequence = request["sequence"]
            await fixture.connection._handle_control({"t": "ack", "seq": sequence})
            kind = request.get("kind", "done")
            if kind != "ack":
                await fixture.connection._handle_control({"t": kind, "seq": sequence, **request.get("fields", {})})
            task = self.actions.get(action_id)
            if task is not None and kind != "ack":
                await asyncio.wait_for(asyncio.shield(task), 5)
        elif operation == "cancel":
            before = len(fixture.body.sent)
            task = asyncio.create_task(fixture.adapter._cancel_action(request["cancellation"]))
            fixture.tasks.append(task)
            await self.await_dispatch(task, before)
        elif operation == "update":
            before = len(fixture.body.sent)
            await fixture.adapter._schedule_walk_update(request["update"], fixture.bridge)
            if fixture.adapter._walk_update_task:
                await self.await_dispatch(fixture.adapter._walk_update_task, before)
        elif operation == "reconnect":
            fixture.connection.cancel_pending()
            fixture.connection.epoch += 1
            await asyncio.gather(*self.actions.values())
        elif operation == "recover":
            await fixture.adapter._recover_action_receipts()
        elif operation == "state":
            # Allows bounded unknown receipt processing without inventing a
            # terminal receipt on behalf of the simulated body.
            await asyncio.sleep(min(max(float(request.get("wait", 0)), 0), 0.2))
        else:
            raise ValueError("unknown harness operation: " + operation)
        return self.snapshot()


async def main() -> None:
    body = ProgramBody()
    print(json.dumps({"ready": body.snapshot()}), flush=True)
    try:
        while line := await asyncio.to_thread(sys.stdin.readline):
            try:
                request = json.loads(line)
                result = await body.request(request)
                response = {"id": request.get("id"), "result": result}
            except Exception as error:
                response = {"error": type(error).__name__ + ": " + str(error)}
            print(json.dumps(response), flush=True)
    finally:
        await body.fixture.asyncTearDown()


if __name__ == "__main__":
    asyncio.run(main())

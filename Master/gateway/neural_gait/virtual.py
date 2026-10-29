"""V2 simulated hardware on the real Body Control transport.

VirtualRobot replaces the physical network peripheral, not GatewayConnection's
motion producer or the P4 executor. VirtualGatewaySession provides an isolated
gateway and a learner-backed inference client for synchronous training callers.
The plant and its clock remain owned by GaitEnvironment.
"""

import asyncio
from copy import deepcopy
import json
import secrets
from uuid import uuid4

from websockets.legacy.client import connect
from websockets.legacy.server import serve

from gateway.server.service import GatewayService, GatewayServiceConfig
from .client import walking_profile


class VirtualWalkEnded(RuntimeError):
    def __init__(self, terminal):
        self.terminal = dict(terminal)
        super().__init__(f"Virtual Walk ended: {self.terminal}")


class VirtualProducerFailed(RuntimeError):
    """A gateway producer failure, distinct from a physical body terminal."""

    def __init__(self, diagnostic):
        self.diagnostic = dict(diagnostic)
        super().__init__(str(self.diagnostic["error"]))


class LearnerInference:
    """One learner response to the existing gateway's pending inference call."""

    def __init__(self, environment, model_id="training"):
        self.environment = deepcopy(environment)
        self.model_id = model_id
        self.requests = asyncio.Queue()
        self.pending = None

    async def call(self, path, payload=None):
        if path == "/status":
            return {"model_id": self.model_id, "environment": deepcopy(self.environment)}
        if path != "/infer":
            raise ValueError(f"Unsupported learner inference operation: {path}")
        response = asyncio.get_running_loop().create_future()
        self.requests.put_nowait((deepcopy(payload["observation"]), response))
        return await response

    async def observation(self):
        if self.pending is not None and not self.pending[1].done():
            return deepcopy(self.pending[0])
        while True:
            request = await self.requests.get()
            if not request[1].done():
                self.pending = request
                return deepcopy(request[0])

    def respond(self, action):
        if self.pending is None or self.pending[1].done():
            raise RuntimeError("Observe the pending gateway inference before supplying its action")
        self.pending[1].set_result({"model_id": self.model_id, "action": list(action)})
        self.pending = None


class VirtualRobot:
    """Standalone V2 body client, also usable against an existing gateway.

The supplied executor is the native production body binding. All ACKs, errors,
terminals and sensor packets are its encoded output. This class only transports
them and supplies network connection identity.
"""

    def __init__(self, executor, endpoint, robot_id, token, now_us):
        self.executor = executor
        self.endpoint = endpoint
        self.robot_id = robot_id
        self.token = token
        self.now_us = now_us
        self.websocket = None
        self.reader = None
        self.epoch = None

    async def connect(self):
        self.websocket = await connect(self.endpoint, ping_interval=None)
        try:
            await self.publish([self.executor.hello(self.robot_id, self.token, self.now_us())])
            raw = await self.websocket.recv()
            welcome = json.loads(raw)
            if welcome.get("t") != "welcome":
                raise RuntimeError(f"Virtual body connection rejected: {welcome}")
            self.epoch = welcome["epoch"]
            self.executor.reset(self.now_us(), self.epoch)
            await self.publish(self.executor.receive(raw, self.epoch, self.now_us()))
            self.reader = asyncio.create_task(self._receive())
            return welcome
        except BaseException:
            await self.close()
            raise

    async def _receive(self):
        try:
            async for raw in self.websocket:
                if not isinstance(raw, str):
                    raise ValueError("The virtual movement body does not advertise binary media")
                await self.publish(self.executor.receive(raw, self.epoch, self.now_us()))
        finally:
            await self.websocket.close()
            self.executor.connection_lost(self.epoch)

    async def publish(self, messages):
        for message in messages:
            await self.websocket.send(message if isinstance(message, str) else json.dumps(message))

    async def telemetry(self):
        packet = self.executor.telemetry(self.now_us())
        await self.publish([packet])

    async def close(self):
        if self.websocket is not None:
            await self.websocket.close()
        if self.reader is not None:
            await asyncio.gather(self.reader, return_exceptions=True)
        self.reader = self.websocket = None


class VirtualFeedbackTransport:
    """Replace HTTP I/O with the same native read serializer; never a model echo."""
    def __init__(self, session):
        self.session = session

    async def request(self, robot, endpoint, payload):
        if robot != self.session.robot_id or endpoint != "servo-feedback" or payload is not None:
            raise ValueError("Virtual recovery transport supports the existing feedback read only")
        return self.session.executor.feedback(self.session.now_us())

    async def close(self):
        pass


class VirtualGatewaySession:
    """Ephemeral loopback Body Control, with no physical gateway configuration.

Call action(), advance the existing plant/native executor, publish its receipts
and telemetry(), then observation(). An ACK means admission only; consumed
sample attribution comes back through the real gateway sensor projection.
"""

    def __init__(self, executor, environment, now_us, source_profile, *, model_id="training"):
        self.executor = executor
        self.now_us = now_us
        self.robot_id = "virtual-v2-" + uuid4().hex[:16]
        self.token = secrets.token_hex(24)
        self.gateway = GatewayService(GatewayServiceConfig(tokens={self.robot_id: self.token}),
            clock=lambda: self.now_us()/1e6)
        self.client = LearnerInference(environment, model_id)
        self.gateway.neural_gait = self.client
        profile = walking_profile(source_profile)
        if profile["source"] != "neural":
            raise ValueError("Learner sessions require an explicit neural walking source profile")
        self.gateway.walking_sources[self.robot_id] = profile
        self.targets = asyncio.Queue()
        self.gateway.subscribe_commands(self._command_sent)
        self.server = self.robot = None
        self.walk = None
        self.walk_connection = None
        self.started_us = None
        self.recovery = None

    async def enable_recovery(self, endpoint, *, generate=None):
        """Opt in to the existing Freestyle event consumer for a scenario.

        A replacement still ends the original Walk. The scenario's hardware
        loop must continue independently while the separate recovery job runs.
        Its motion_plan actions are not PPO action labels.
        """
        if self.recovery is None:
            from experiments.freestyle.bridge import Bridge
            options = {"generate": generate} if generate is not None else {}
            self.recovery = Bridge(self.gateway, VirtualFeedbackTransport(self), **options)
        elif generate is not None:
            raise ValueError("A running recovery bridge already owns its generator")
        await self.recovery.configure(self.robot_id, endpoint, True)
        return self.recovery

    async def _command_sent(self, command):
        if command.get("t") == "walk_target":
            self.targets.put_nowait(dict(command))

    async def start(self):
        self.server = await serve(self.gateway.handler, "127.0.0.1", 0, ping_interval=None)
        port = self.server.sockets[0].getsockname()[1]
        self.robot = VirtualRobot(self.executor, f"ws://127.0.0.1:{port}/robot",
            self.robot_id, self.token, self.now_us)
        try:
            await self.robot.connect()
        except BaseException:
            await self.close()
            raise
        return self

    @property
    def connection(self):
        return self.gateway._connection(self.robot_id)

    async def command(self, name, params=None):
        return await self.gateway.queue_intent(name, params or {}, robot_id=self.robot_id)

    async def start_walk(self, command):
        self.walk = await self.command("walk", command)
        self.walk_connection = self.connection
        await self.walk_connection.wait_acknowledged(self.walk, timeout=None)
        self.started_us = self.now_us()
        return self.walk

    async def update_walk(self, command):
        sequence = await self.command("walk", {**command, "update": self.walk})
        # A real in-flight inference eventually returns and the gateway drops
        # its old steering revision. Complete that same obsolete learner call
        # so the new observation can be requested; no target is sent for it.
        if self.client.pending is not None and not self.client.pending[1].done():
            self.client.respond(self.client.pending[0]["previous_action"])
        return sequence

    async def finish(self):
        original = self.connection.pending[self.walk].command
        return await self.command("walk", {"dir": original["dir"],
            "gait": original.get("gait", "walk"), "steps": 0, "speed": 0, "update": self.walk})

    async def stop(self, *, release=False):
        return await self.gateway.estop(robot_id=self.robot_id, detach=release)

    async def _until_terminal(self, operation):
        """Wait on the same original receipt, never fabricate successful exit."""
        task = asyncio.create_task(operation)
        walk, connection = self.walk, self.walk_connection
        pending = connection.pending.get(walk)
        terminal = pending.future if pending is not None else None
        failure = asyncio.get_running_loop().create_future()
        def failed(diagnostic):
            if (diagnostic.get("event") == "neural_gait" and diagnostic.get("error")
                    and diagnostic.get("walk") == walk
                    and diagnostic.get("epoch") == connection.epoch
                    and not failure.done()):
                failure.set_result(dict(diagnostic))
        self.gateway.subscribe_diagnostics(failed)
        if pending is not None and pending.producer_error:
            failure.set_result({"error": pending.producer_error, "walk": walk,
                                "source": "gateway_pending_command"})
        try:
            if terminal is None:
                raise VirtualWalkEnded(connection.completed[walk])
            done, _ = await asyncio.wait((task, terminal, failure), return_when=asyncio.FIRST_COMPLETED)
            if terminal in done:
                raise VirtualWalkEnded(terminal.result())
            if task not in done:
                raise VirtualProducerFailed(failure.result())
            return task.result()
        finally:
            self.gateway.unsubscribe_diagnostics(failed)
            if not failure.done():
                failure.cancel()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def observation(self):
        return await self._until_terminal(self.client.observation())

    @property
    def observation_ready(self):
        if self.walk_connection is not None:
            pending = self.walk_connection.pending.get(self.walk)
            terminal = (pending.future.result() if pending is not None and pending.future.done()
                        else self.walk_connection.completed.get(self.walk))
            if terminal is not None:
                raise VirtualWalkEnded(terminal)
            if pending is not None and pending.producer_error:
                raise VirtualProducerFailed({"error": pending.producer_error, "walk": self.walk,
                                             "source": "gateway_pending_command"})
        return ((self.client.pending is not None and not self.client.pending[1].done())
                or not self.client.requests.empty())

    async def action(self, action):
        walk, connection = self.walk, self.walk_connection
        self.client.respond(action)
        target = await self._until_terminal(self._next_target(walk))
        pending = connection.pending.get(target["seq"])
        ack = (await asyncio.shield(pending.acknowledgement) if pending is not None
               else connection.completed[target["seq"]])
        return {"walk": walk, "sequence": target["seq"], "sample": target["sample"],
                "ack": dict(ack), "accepted": ack.get("t") == "ack", **self.execution_info()}

    async def _next_target(self, walk):
        while True:
            target = await self.targets.get()
            if target["walk"] == walk:
                return target

    def execution_info(self):
        imu = (self.connection.last_status or {}).get("imu") or {}
        motion = imu.get("motion") or {}
        return {"consumed_sample": motion.get("nominal_sample", 0),
                "sampled_us": motion.get("sampled_us"),
                "elapsed_simulation_s": (self.now_us()-(self.started_us or self.now_us()))/1e6,
                "epoch": self.robot.epoch}

    async def publish(self, messages):
        await self.robot.publish(messages)

    async def telemetry(self):
        # Deterministic *simulator* scheduling: deliver this physical sensor
        # frame through the real socket before advancing the next physics
        # interval. This is not an inference freshness filter or a production
        # gateway wait. No received observation or generated target is dropped.
        packet = self.executor.telemetry(self.now_us())
        receipt = asyncio.get_running_loop().create_future()
        async def observed(event):
            if (event.get("t") == "imu" and event.get("robot_id") == self.robot_id
                    and event.get("epoch") == self.robot.epoch
                    and event["imu"]["joint_feedback"]["device_us"] == packet["data"]["joint_feedback"]["device_us"]
                    and not receipt.done()):
                receipt.set_result(None)
        self.gateway.subscribe_events(observed)
        try:
            await self.robot.publish([packet])
            done, _ = await asyncio.wait((receipt, self.robot.reader), return_when=asyncio.FIRST_COMPLETED)
            if receipt not in done:
                await self.robot.reader
                raise ConnectionError("Virtual body disconnected before sensor delivery")
        finally:
            self.gateway.unsubscribe_events(observed)
            if not receipt.done():
                receipt.cancel()

    async def close(self):
        if self.recovery is not None:
            await self.recovery.close()
            self.recovery = None
        if self.robot is not None:
            await self.robot.close()
        await self.gateway.close()
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
        self.robot = self.server = None


async def run_robot(environment, endpoint, robot_id, token, *, seed=1):
    """Run only virtual hardware against a normally configured Body Control.

    Real-time pacing belongs to this simulator. The gateway remains free to
    receive commands/infer concurrently, and simulation episode flags do not
    invent a physical Stop or terminate the standalone body.
    """
    from .environment import GaitEnvironment
    plant = GaitEnvironment(environment, include_visuals=False)
    executor = robot = None
    try:
        plant.reset(seed=seed)
        executor = plant.virtual_body()
        robot = VirtualRobot(executor, endpoint, robot_id, token,
            lambda: round(1+plant.data.time*1e6))
        await robot.connect()
        print(f"Virtual V2 connected as {robot_id} to {endpoint}; simulated movement and sensors only", flush=True)
        loop = asyncio.get_running_loop()
        deadline = loop.time()
        while not robot.reader.done():
            _, output = plant.advance_body(executor)
            await robot.publish(output["messages"])
            await robot.telemetry()
            deadline += 1/plant.config.control_hz
            await asyncio.sleep(max(0, deadline-loop.time()))
        await robot.reader
    finally:
        if robot is not None:
            await robot.close()
        if executor is not None:
            executor.close()
        plant.close()


async def run_recovery_scenario(environment, policy_run, directory, endpoint, *, seed=1):
    """Qualify separate walking/recovery owners on the existing virtual plant.

    Freestyle output is generated by the configured service, never used as PPO
    labels. Ground truth is saved for evaluation; inference gets actual gateway
    observations. The scenario horizon does not fabricate a body completion.
    """
    from dataclasses import asdict
    import hashlib
    from pathlib import Path
    import numpy as np
    from .environment import GaitEnvironment, ENVIRONMENT_VERSION, representation_identity
    from .training import load_policy, save_json
    from .contract import vector
    policy_run, directory = Path(policy_run), Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "recovery-evaluation.json"
    if destination.exists():
        raise ValueError("Choose a new recovery trial directory to preserve its evidence")
    report = dict(scope="simulation_recovery_qualification", physical_qualification=False,
        self_righting_trained=False, seed=seed, environment=asdict(environment),
        environment_version=ENVIRONMENT_VERSION, representation=representation_identity(),
        policy=dict(directory=str(policy_run.resolve()),
            sha256=hashlib.sha256((policy_run/"policy.zip").read_bytes()).hexdigest()),
        generator=dict(kind="configured_freestyle_service", endpoint=endpoint, canned=False),
        body_events=[], commands=[], trajectory=[], original_walk_terminal=None)
    plant = GaitEnvironment(environment, include_visuals=False)
    executor = session = policy_task = None
    try:
        model = load_policy(policy_run, device="cpu")
        plant.reset(seed=seed)
        executor = plant.virtual_body()
        profile = {"source":"neural", **{key:abs(environment.command[i]) or 1.
            for i,key in enumerate(("forward_m_s","lateral_m_s","yaw_rad_s"))}}
        session = VirtualGatewaySession(executor,asdict(environment),
            lambda:round(1+plant.data.time*1e6),profile,model_id=policy_run.name)
        def depth_measurement(robot_id):
            measurement = deepcopy(plant.depth_measurement or {})
            measurement.update(robotId=session.robot_id,epoch=session.connection.epoch)
            return measurement
        session.gateway.locomotion_measurement = depth_measurement
        async def record_event(event):
            if event.get("name")=="body_event":
                report["body_events"].append(deepcopy(event))
        async def record_command(command):
            report["commands"].append(deepcopy(command))
        session.gateway.subscribe_events(record_event)
        session.gateway.subscribe_commands(record_command)
        await session.start()
        await session.enable_recovery(endpoint)
        command=dict(dir="fwd",gait="walk",steps=0,speed=100,
            **{key:round(100*environment.command[i]/profile[scale])
               for i,(key,scale) in enumerate(zip(("forward","lateral","turn"),
                   ("forward_m_s","lateral_m_s","yaw_rad_s")))})
        await session.start_walk(command)
        original = session.walk_connection.pending[session.walk].future
        async def produce():
            try:
                while True:
                    obs = await session.observation()
                    action,_ = await asyncio.to_thread(model.predict,
                        np.asarray(vector(obs),dtype=np.float32),deterministic=True)
                    await session.action(action.tolist())
            except VirtualWalkEnded as ended:
                report["original_walk_terminal"] = ended.terminal
        policy_task = asyncio.create_task(produce())
        loop = asyncio.get_running_loop()
        deadline = loop.time()
        for _ in range(round(environment.episode_seconds*environment.control_hz)):
            metrics, output = plant.advance_body(executor)
            await session.publish(output["messages"])
            await session.telemetry()
            report["trajectory"].append(dict(time_s=float(plant.data.time),
                position_m=plant.data.qpos[:3].tolist(), orientation_wxyz=plant.data.qpos[3:7].tolist(),
                **metrics, **session.execution_info()))
            if policy_task.done():
                # A cancellation receipt is an expected ownership handoff;
                # other errors remain observable, rather than false recovery.
                policy_task.result()
            deadline += 1/environment.control_hz
            await asyncio.sleep(max(0,deadline-loop.time()))
        if original.done():
            report["original_walk_terminal"] = original.result()
        report["horizon_reached"] = True
        report["recovery_jobs"] = deepcopy(session.recovery.jobs)
        report["final_position_m"] = plant.data.qpos[:3].tolist()
        report["final_orientation_wxyz"] = plant.data.qpos[3:7].tolist()
        report["final_upright"] = float(plant.data.xmat[plant.model.body("torso").id].reshape(3,3)[2,2])
    except BaseException as error:
        report["error"] = str(error)
        raise
    finally:
        if policy_task is not None:
            policy_task.cancel()
            await asyncio.gather(policy_task,return_exceptions=True)
        if session is not None:
            if session.recovery is not None:
                report.setdefault("recovery_jobs",deepcopy(session.recovery.jobs))
            await session.close()
        if executor is not None:
            executor.close()
        plant.close()
        save_json(destination,report)
    print(str(destination),flush=True)
    return report


def main():
    import argparse
    import os
    from pathlib import Path
    from .environment import EnvironmentConfig, body_control_config
    parser = argparse.ArgumentParser(description="Connect the actual V2 executor and CAD plant to Body Control")
    parser.add_argument("--environment", required=True, type=Path,
        help="EnvironmentConfig JSON or existing run manifest containing environment")
    parser.add_argument("--endpoint", help="Existing gateway WebSocket /robot URL")
    parser.add_argument("--robot-id", help="Virtual robot identity registered in that gateway")
    parser.add_argument("--token-file", type=Path, help="Private token file; otherwise AINEKIO_ROBOT_TOKEN")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--recovery-scenario",action="store_true",
        help="Run separate neural Walk/Freestyle recovery owners on an isolated actual gateway")
    parser.add_argument("--policy-run",type=Path,help="Existing neural policy run for scenario walking")
    parser.add_argument("--directory",type=Path,help="Unused trial directory under build/neural-gait")
    parser.add_argument("--recovery-endpoint",help="Configured Freestyle generation service URL")
    args = parser.parse_args()
    document = json.loads(args.environment.read_text())
    config = EnvironmentConfig(**document.get("environment", document))
    if args.recovery_scenario:
        if not all((args.policy_run,args.directory,args.recovery_endpoint)):
            parser.error("Recovery scenario requires --policy-run, --directory and --recovery-endpoint")
        asyncio.run(run_recovery_scenario(config,args.policy_run,args.directory,args.recovery_endpoint,seed=args.seed))
        return
    if not args.endpoint or not args.robot_id:
        parser.error("Virtual robot connection requires --endpoint and --robot-id")
    token = args.token_file.read_text().strip() if args.token_file else os.environ.get("AINEKIO_ROBOT_TOKEN")
    if not token:
        parser.error("Set AINEKIO_ROBOT_TOKEN or supply --token-file; credentials are not stored in source")
    document = json.loads(args.environment.read_text())
    config = body_control_config(EnvironmentConfig(**document.get("environment", document)))
    try:
        asyncio.run(run_robot(config, args.endpoint, args.robot_id, token, seed=args.seed))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

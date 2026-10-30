"""Gym scheduling around the real Body Control / P4 virtual-body connection.

The gateway owns policy production and the P4 executor owns movement. This
adapter only advances simulated hardware and hands the gateway's inference
requests to the learner. All native state, physics and socket callbacks run on
one event loop thread; independent training workers remain separate processes.
"""

import asyncio
from dataclasses import asdict
import threading

import numpy as np

from .contract import vector
from .client import walking_twist
from .environment import GaitEnvironment
from .virtual import VirtualGatewaySession, VirtualWalkEnded, VirtualProducerFailed


class BodyControlEnvironment(GaitEnvironment):
    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)
        self.session = self.executor = None
        self.gateway_observation = None
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever,
            name="virtual-body-control", daemon=True)
        self.thread.start()
        commands = self.commands or [self.config.command]
        # This is SI-to-percent encoding for these requested tasks, not a
        # measured speed limit. Zero-only axes need a nonzero conversion scale.
        self.profile = dict(source="neural", **{
            key: max(abs(command[index]) for command in commands) or 1.
            for index, key in enumerate(("forward_m_s", "lateral_m_s", "yaw_rad_s"))})

    def _run(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result()

    def _now_us(self):
        return round(1+self.data.time*1e6)

    def _wire_command(self, command):
        return dict(dir="fwd", gait="walk", steps=0, speed=100,
            **{key: round(100*command[index]/self.profile[scale])
               for index, (key, scale) in enumerate(zip(
                   ("forward", "lateral", "turn"),
                   ("forward_m_s", "lateral_m_s", "yaw_rad_s")))})

    async def _disconnect(self):
        if self.session is not None:
            await self.session.close()
            self.session = None
        if self.executor is not None:
            self.executor.close()
            self.executor = None

    async def _reset(self, **kwargs):
        await self._disconnect()
        _, info = super().reset(**kwargs)
        self.requested_command = list(self.config.command)
        wire = self._wire_command(self.requested_command)
        super().set_command(walking_twist(wire, self.profile))
        self.executor = self.virtual_body()
        self.session = VirtualGatewaySession(self.executor, asdict(self.config),
            self._now_us, self.profile)
        self.session.gateway.locomotion_measurement = lambda robot_id: {
            **(self.depth_measurement or {}), "robotId": robot_id,
            "epoch": self.session.connection.epoch}
        try:
            await self.session.start()
            await self.session.start_walk(wire)
            # Admission precedes the first scheduled PWM frame. Run hardware
            # acquisition until the existing producer actually asks for its
            # first action; a frozen simulated clock cannot produce that data.
            while not self.session.observation_ready:
                _, output = self.advance_body(self.executor)
                await self.session.publish(output["messages"])
                await self.session.telemetry()
            self.gateway_observation = await self.session.observation()
            info.update(execution_backend="body_control", requested_command=self.requested_command,
                        command=list(self.config.command), **self.session.execution_info())
            return np.asarray(vector(self.with_critic(self.gateway_observation)), dtype=np.float32), info
        except BaseException:
            await self._disconnect()
            raise

    def reset(self, **kwargs):
        return self._run(self._reset(**kwargs))

    async def _step(self, action):
        terminal = None
        producer_failure = None
        admission = {}
        try:
            admission = await self.session.action(np.asarray(action).tolist())
        except VirtualWalkEnded as error:
            terminal = error.terminal
        except VirtualProducerFailed as error:
            producer_failure = error.diagnostic
        result, output = self.advance_body(self.executor, action)
        _, reward, terminated, truncated, info = result
        await self.session.publish(output["messages"])
        await self.session.telemetry()
        rejected = admission.get("accepted") is False
        if terminal is None and not rejected and producer_failure is None:
            try:
                self.gateway_observation = await self.session.observation()
            except VirtualWalkEnded as error:
                terminal = error.terminal
            except VirtualProducerFailed as error:
                producer_failure = error.diagnostic
        info.update(admission, **self.session.execution_info(), execution_backend="body_control")
        info["requested_command"] = list(self.requested_command)
        if rejected:
            info["body_rejection"] = admission["ack"]
            info["target_rejected"] = True
            terminated = True
        if terminal is not None:
            # A body terminal ends this training episode; it is not converted
            # into a simulated success or ignored while direct PWM continues.
            info["body_terminal"] = terminal
            terminated = True
        if producer_failure is not None:
            info["producer_failure"] = producer_failure
            terminated = True
        return (np.asarray(vector(self.with_critic(self.gateway_observation)), dtype=np.float32),
                reward, terminated, truncated, info)

    def step(self, action):
        return self._run(self._step(action))

    async def _set_command(self, command):
        self.requested_command = list(command)
        wire = self._wire_command(command)
        super().set_command(walking_twist(wire, self.profile))
        await self.session.update_walk(wire)
        self.gateway_observation = await self.session.observation()
        return np.asarray(vector(self.with_critic(self.gateway_observation)), dtype=np.float32)

    def set_command(self, command):
        return self._run(self._set_command(command))

    async def _close(self):
        await self._disconnect()
        super().close()

    def close(self):
        if not self.loop.is_closed():
            try:
                self._run(self._close())
            finally:
                self.loop.call_soon_threadsafe(self.loop.stop)
                self.thread.join()
                self.loop.close()

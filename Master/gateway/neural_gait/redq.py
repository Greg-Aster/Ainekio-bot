"""Desktop REDQ learner and dependency-light deployment actor.

SAC-family REDQ: Chen et al., ICLR 2021, https://arxiv.org/abs/2101.05982.
Algorithm reference: https://github.com/watchernyu/REDQ (MIT, watchernyu 2021).
This implementation uses a random target-critic subset, ensemble-mean actor loss,
reparameterized tanh Gaussian policy and learned entropy temperature. It is not
TD3. Collection, reward/variable-time discount calculation and activation belong
to Body Control. Nothing in this module starts training or commands hardware.

Upstream algorithm implementation notice (watchernyu/REDQ):
MIT License, Copyright (c) 2021 watchernyu
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Normalization is explicit and frozen for a learner's lifetime. Inputs already
normalized by the gait contract use identity normalization. Export carries the
same affine transform; there is no deployment-only clipping or smoothing.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import copy
import json
import math
from pathlib import Path

import numpy as np

FORMAT = "ainekio-redq-v1"


@dataclass(frozen=True)
class REDQConfig:
    observation_dim: int
    action_dim: int = 12
    ensemble_size: int = 10
    target_subset: int = 2
    utd_ratio: int = 20
    policy_delay: int = 20
    batch_size: int = 256
    replay_capacity: int = 100000
    seed: int = 0
    learning_rate: float = 3e-4
    tau: float = .005
    initial_alpha: float = .2
    target_entropy: float | None = None
    pending_input_dim: int = 0
    pending_hidden_dim: int = 32

    def __post_init__(self):
        if self.pending_input_dim not in (0, 14) or type(self.pending_hidden_dim) is not int or self.pending_hidden_dim < 1:
            raise ValueError("Pending inputs require fourteen values and a positive hidden size")
        for key in ("observation_dim", "ensemble_size", "target_subset", "utd_ratio",
                    "policy_delay", "batch_size", "replay_capacity"):
            if type(getattr(self, key)) is not int or getattr(self, key) < 1:
                raise ValueError(f"{key} must be a positive integer")
        if self.action_dim != 12 or self.target_subset > self.ensemble_size:
            raise ValueError("Expected twelve actions and subset no larger than ensemble")
        if not 0 < self.tau <= 1 or not math.isfinite(self.learning_rate) or self.learning_rate <= 0:
            raise ValueError("Invalid learning rate or target update coefficient")
        if not math.isfinite(self.initial_alpha) or self.initial_alpha <= 0:
            raise ValueError("initial_alpha must be finite and positive")
        if self.target_entropy is not None and not math.isfinite(self.target_entropy):
            raise ValueError("target_entropy must be finite")


def _normalization(size, mean, scale):
    mean = np.zeros(size, np.float32) if mean is None else np.asarray(mean, np.float32).copy()
    scale = np.ones(size, np.float32) if scale is None else np.asarray(scale, np.float32).copy()
    if mean.shape != (size,) or scale.shape != (size,) or not np.isfinite(mean).all() or not np.isfinite(scale).all() or (scale <= 0).any():
        raise ValueError("Normalization requires finite mean and positive scale per observation")
    return mean, scale


def _pending_batch(value, count, *, single=False):
    """Keep every ordered request; ragged rows are not padded in saved replay."""
    if value is None:
        return [np.empty((0, 14), np.float32) for _ in range(count)]
    rows = [value] if single else value
    if len(rows) != count:
        raise ValueError("Pending sequences must match the observation count")
    result = []
    for row in rows:
        row = np.asarray(row, np.float32)
        if row.size == 0:
            row = np.empty((0, 14), np.float32)
        if row.ndim != 2 or row.shape[1] != 14 or not np.isfinite(row).all():
            raise ValueError("Pending sequences require finite ordered fourteen-value rows")
        result.append(row.copy())
    return result


class NumpyActor:
    """Deployment needs NumPy only, including stochastic labelled trial actions."""
    def __init__(self, arrays, metadata):
        self.arrays = arrays
        self.metadata = metadata
        self.observation_dim = len(arrays["observation_mean"])
        self.action_dim = arrays["mean_bias"].shape[0]

    @classmethod
    def load(cls, path):
        with np.load(path, allow_pickle=False) as archive:
            metadata = json.loads(str(archive["metadata"]))
            if metadata.get("format") != FORMAT:
                raise ValueError("Unsupported REDQ actor format")
            arrays = {key: archive[key].copy() for key in archive.files if key != "metadata"}
        _normalization(len(arrays["observation_mean"]), arrays["observation_mean"], arrays["observation_scale"])
        return cls(arrays, metadata)

    def act(self, observations, deterministic=True, rng=None, noise=None, pending_actions=None):
        a = self.arrays
        x = np.asarray(observations, np.float32)
        if x.shape[-1] != self.observation_dim or not np.isfinite(x).all():
            raise ValueError("Invalid actor observation")
        x = (x - a["observation_mean"]) / a["observation_scale"]
        if self.metadata.get("pending_input_dim", 0):
            single = x.ndim == 1
            if x.ndim not in (1, 2):
                raise ValueError("Pending actor expects one observation or a batch")
            rows = _pending_batch(pending_actions, 1 if single else len(x), single=single)
            hidden = np.zeros((len(rows), self.metadata["pending_hidden_dim"]), np.float32)
            # Match torch.GRUCell's reset/update/new ordering, including its
            # reset gate on the recurrent new-state bias. No sequence is capped.
            for step in range(max((len(row) for row in rows), default=0)):
                indices = [i for i, row in enumerate(rows) if step < len(row)]
                inputs = np.stack([rows[i][step] for i in indices])
                gi = inputs @ a["pending_weight_ih"].T + a["pending_bias_ih"]
                gh = hidden[indices] @ a["pending_weight_hh"].T + a["pending_bias_hh"]
                ir, iz, inn = np.split(gi, 3, axis=-1)
                hr, hz, hn = np.split(gh, 3, axis=-1)
                reset = .5 * (1 + np.tanh((ir + hr) * .5))
                update = .5 * (1 + np.tanh((iz + hz) * .5))
                new = np.tanh(inn + reset * hn)
                hidden[indices] = new + update * (hidden[indices] - new)
            x = np.concatenate((x, hidden[0] if single else hidden), axis=-1)
        for i in range(2):
            x = np.maximum(x @ a[f"hidden_{i}_weight"].T + a[f"hidden_{i}_bias"], 0)
        mean = x @ a["mean_weight"].T + a["mean_bias"]
        if not deterministic:
            if noise is None:
                if rng is None:
                    raise ValueError("Stochastic inference requires an explicit RNG")
                noise = rng.standard_normal(mean.shape).astype(np.float32)
            noise = np.asarray(noise, np.float32)
            if noise.shape != mean.shape or not np.isfinite(noise).all():
                raise ValueError("Invalid actor noise")
            log_std = np.clip(x @ a["log_std_weight"].T + a["log_std_bias"], -20, 2)
            mean = mean + np.exp(log_std) * noise
        return np.tanh(mean).astype(np.float32)


class REDQLearner:
    """Explicit offline updates from supplied physical transitions, with replay.

    discounts already include gamma ** elapsed_time and zero for true terminal
    transitions. Time-limit truncation can therefore bootstrap without inventing
    a terminal. Replay stores the supplied observations/actions unchanged.
    """
    def __init__(self, config: REDQConfig, device="cuda", observation_mean=None, observation_scale=None):
        import torch
        from torch import nn
        self.torch, self.config, self.device = torch, config, torch.device(device)
        self.observation_mean, self.observation_scale = _normalization(config.observation_dim, observation_mean, observation_scale)
        self.mean = torch.as_tensor(self.observation_mean, device=self.device)
        self.scale = torch.as_tensor(self.observation_scale, device=self.device)
        self.rng = np.random.default_rng(config.seed)
        # CPU noise generator preserves its state across CPU/GPU checkpoint moves.
        self.noise_rng = torch.Generator(device="cpu").manual_seed(config.seed)
        with torch.random.fork_rng(devices=[]):
            torch.random.default_generator.manual_seed(config.seed)
            inputs = config.observation_dim + (config.pending_hidden_dim if config.pending_input_dim else 0)
            self.actor = nn.ModuleDict({
                "hidden": nn.Sequential(nn.Linear(inputs, 256), nn.ReLU(), nn.Linear(256, 256), nn.ReLU()),
                "mean": nn.Linear(256, config.action_dim),
                "log_std": nn.Linear(256, config.action_dim),
            }).to(self.device)
            self.critics = nn.ModuleList([
                nn.Sequential(nn.Linear(inputs + config.action_dim, 256), nn.ReLU(),
                              nn.Linear(256, 256), nn.ReLU(), nn.Linear(256, 1))
                for _ in range(config.ensemble_size)]).to(self.device)
            if config.pending_input_dim:
                self.actor["pending"] = nn.GRUCell(14, config.pending_hidden_dim).to(self.device)
                self.critics = nn.ModuleList([nn.ModuleDict({"hidden": critic,
                    "pending": nn.GRUCell(14, config.pending_hidden_dim).to(self.device)}) for critic in self.critics])
        self.targets = copy.deepcopy(self.critics).requires_grad_(False)
        self.actor_optimizer = torch.optim.Adam(self.actor.parameters(), lr=config.learning_rate)
        self.critic_optimizer = torch.optim.Adam(self.critics.parameters(), lr=config.learning_rate)
        self.log_alpha = torch.tensor(math.log(config.initial_alpha), device=self.device, requires_grad=True)
        self.alpha_optimizer = torch.optim.Adam([self.log_alpha], lr=config.learning_rate)
        self.target_entropy = -float(config.action_dim) if config.target_entropy is None else config.target_entropy
        self.total_updates = self.policy_updates = self.total_transitions = 0
        # Collection provenance belongs to the checkpoint transaction, not a
        # separately written sidecar that can lag replay after a process crash.
        self.extra_state = {}
        self.replay_size = self.replay_cursor = 0
        self.replay = {"observations": np.empty((config.replay_capacity, config.observation_dim), np.float32),
                       "actions": np.empty((config.replay_capacity, config.action_dim), np.float32),
                       "rewards": np.empty((config.replay_capacity, 1), np.float32),
                       "next_observations": np.empty((config.replay_capacity, config.observation_dim), np.float32),
                       "discounts": np.empty((config.replay_capacity, 1), np.float32)}
        self.pending_replay = ({key: [None] * config.replay_capacity
                               for key in ("pending_actions", "next_pending_actions")}
                              if config.pending_input_dim else None)

    def _encode_pending(self, encoder, rows):
        torch = self.torch
        hidden = torch.zeros((len(rows), self.config.pending_hidden_dim), device=self.device)
        for step in range(max((len(row) for row in rows), default=0)):
            indices = [i for i, row in enumerate(rows) if step < len(row)]
            values = torch.as_tensor(np.stack([rows[i][step] for i in indices]), device=self.device)
            updated = encoder(values, hidden[indices])
            hidden = hidden.index_copy(0, torch.as_tensor(indices, device=self.device), updated)
        return hidden

    def _policy(self, observations, deterministic=False, noise=None, pending_actions=None):
        torch = self.torch
        if self.config.pending_input_dim:
            single = observations.ndim == 1
            encoded = self._encode_pending(self.actor["pending"], pending_actions)
            observations = torch.cat((observations, encoded[0] if single else encoded), -1)
        x = self.actor["hidden"](observations)
        mean = self.actor["mean"](x)
        log_std = self.actor["log_std"](x).clamp(-20, 2)
        if deterministic:
            return mean.tanh(), None
        if noise is None:
            noise = torch.randn(mean.shape, generator=self.noise_rng).to(self.device)
        pre_tanh = mean + log_std.exp() * noise
        log_prob = (-.5 * (noise.square() + math.log(2 * math.pi)) - log_std
                    - 2 * (math.log(2) - pre_tanh - torch.nn.functional.softplus(-2 * pre_tanh))).sum(-1, keepdim=True)
        return pre_tanh.tanh(), log_prob

    def _critic(self, critic, observations, actions, pending_actions=None):
        inputs = [observations, actions]
        if self.config.pending_input_dim:
            inputs.append(self._encode_pending(critic["pending"], pending_actions))
            critic = critic["hidden"]
        return critic(self.torch.cat(inputs, -1))

    def act(self, observations, deterministic=False, noise=None, pending_actions=None):
        torch = self.torch
        x = np.asarray(observations, np.float32)
        if x.shape[-1] != self.config.observation_dim or not np.isfinite(x).all():
            raise ValueError("Invalid actor observation")
        rows = (_pending_batch(pending_actions, 1 if x.ndim == 1 else len(x), single=x.ndim == 1)
                if self.config.pending_input_dim else None)
        with torch.no_grad():
            value = (torch.as_tensor(x, device=self.device) - self.mean) / self.scale
            n = None if noise is None else torch.as_tensor(noise, dtype=torch.float32, device=self.device)
            return self._policy(value, deterministic, n, rows)[0].cpu().numpy()

    def add_transitions(self, observations, actions, rewards, next_observations, discounts,
                        pending_actions=None, next_pending_actions=None):
        values = dict(observations=observations, actions=actions, rewards=rewards,
                      next_observations=next_observations, discounts=discounts)
        count = None
        for key, value in values.items():
            value = np.asarray(value, np.float32).reshape(-1, self.replay[key].shape[1])
            if count is None:
                count = len(value)
            if len(value) != count or not np.isfinite(value).all():
                raise ValueError("Transition arrays must be finite and have equal row counts")
            values[key] = value
        if (np.abs(values["actions"]) > 1).any() or ((values["discounts"] < 0) | (values["discounts"] > 1)).any():
            raise ValueError("Actions must be normalized and discounts in [0, 1]")
        pending = ({"pending_actions": _pending_batch(pending_actions, count),
                    "next_pending_actions": _pending_batch(next_pending_actions, count)}
                   if self.config.pending_input_dim else None)
        capacity = self.config.replay_capacity
        # Keep the latest capacity samples while preserving the true ring cursor.
        first = max(0, count - capacity)
        indices = (self.replay_cursor + np.arange(first, count)) % capacity
        for key, value in values.items():
            self.replay[key][indices] = value[first:]
        if pending is not None:
            for key, rows in pending.items():
                for index, row in zip(indices, rows[first:]):
                    self.pending_replay[key][index] = row
        self.replay_cursor = (self.replay_cursor + count) % capacity
        self.replay_size = min(capacity, self.replay_size + count)
        self.total_transitions += count
        return count

    def upgrade_pending_inputs(self, pending_actions, next_pending_actions):
        """Extend a v5 learner in place using verified replay-storage-order rows.

        Old dense coordinates and Adam moments stay unchanged. New embedding
        columns start at zero, so adding this input preserves existing outputs;
        subsequent updates can learn its effect without resetting the policy.
        """
        if self.config.pending_input_dim:
            raise ValueError("Learner already has pending-action inputs")
        rows = {"pending_actions": _pending_batch(pending_actions, self.replay_size),
                "next_pending_actions": _pending_batch(next_pending_actions, self.replay_size)}
        torch, nn = self.torch, self.torch.nn
        width = self.config.pending_hidden_dim
        replacements = {}

        def expand(network):
            old = network[0]
            new = nn.Linear(old.in_features + width, old.out_features).to(self.device)
            with torch.no_grad():
                new.weight.zero_()
                new.weight[:, :old.in_features].copy_(old.weight)
            new.bias = old.bias
            replacements[old.weight] = new.weight
            network[0] = new

        def optimizer(previous, added, parameters):
            groups = [{**group, "params": [replacements.get(p, p) for p in group["params"]]}
                      for group in previous.param_groups]
            groups[0]["params"] = groups[0]["params"] + list(added)
            # Adam checkpoints map states by parameter order. Match the v6
            # constructor's module order, including each critic's own encoder.
            parameters = list(parameters)
            for group in groups:
                members = {id(parameter) for parameter in group["params"]}
                group["params"] = [parameter for parameter in parameters if id(parameter) in members]
            updated = torch.optim.Adam(groups, **previous.defaults)
            for parameter, state in previous.state.items():
                destination = replacements.get(parameter, parameter)
                copied = {}
                for key, value in state.items():
                    if torch.is_tensor(value) and value.shape == parameter.shape and destination.shape != parameter.shape:
                        expanded = torch.zeros_like(destination)
                        expanded[:, :parameter.shape[1]].copy_(value)
                        copied[key] = expanded
                    else:
                        copied[key] = value.clone() if torch.is_tensor(value) else copy.deepcopy(value)
                updated.state[destination] = copied
            return updated

        with torch.random.fork_rng(devices=[]):
            torch.random.default_generator.manual_seed(self.config.seed)
            expand(self.actor["hidden"])
            self.actor["pending"] = nn.GRUCell(14, width).to(self.device)
            critics, targets, added = [], [], []
            for critic, target in zip(self.critics, self.targets):
                expand(critic)
                expand(target)
                encoder = nn.GRUCell(14, width).to(self.device)
                added.extend(encoder.parameters())
                critics.append(nn.ModuleDict({"hidden": critic, "pending": encoder}))
                targets.append(nn.ModuleDict({"hidden": target, "pending": copy.deepcopy(encoder)}))
            self.critics = nn.ModuleList(critics)
            self.targets = nn.ModuleList(targets).requires_grad_(False)
        self.actor_optimizer = optimizer(self.actor_optimizer, self.actor["pending"].parameters(), self.actor.parameters())
        self.critic_optimizer = optimizer(self.critic_optimizer, added, self.critics.parameters())
        self.config = replace(self.config, pending_input_dim=14)
        self.pending_replay = {key: value + [None] * (self.config.replay_capacity - self.replay_size)
                               for key, value in rows.items()}

    def imitate(self, observations, actions, updates, *, pending_actions=None):
        """Fit demonstrated targets with the existing actor and optimizer.

        This consumes observation/action pairs, not rewards. Critics, replay,
        temperature and RL update counts remain unchanged. The caller owns
        physical action coordinates, demonstration provenance and evaluation.
        """
        x = np.asarray(observations, np.float32)
        y = np.asarray(actions, np.float32)
        if (x.ndim != 2 or x.shape[1] != self.config.observation_dim or not len(x)
                or y.shape != (len(x), self.config.action_dim)
                or not np.isfinite(x).all() or not np.isfinite(y).all()):
            raise ValueError("Demonstrations require finite matching observation/action rows")
        if (np.abs(y) > 1).any():
            raise ValueError("Demonstrated actions exceed the configured physical action domain")
        if type(updates) is not int or updates < 0:
            raise ValueError("Imitation updates must be a nonnegative integer")
        pending = _pending_batch(pending_actions, len(x)) if self.config.pending_input_dim else None
        before = float(np.sqrt(np.mean((self.act(x, deterministic=True, pending_actions=pending) - y)**2)))
        for _ in range(updates):
            indices = self.rng.integers(len(x), size=self.config.batch_size)
            observed = (self.torch.as_tensor(x[indices], device=self.device) - self.mean) / self.scale
            target = self.torch.as_tensor(y[indices], device=self.device)
            rows = [pending[index] for index in indices] if pending is not None else None
            predicted, _ = self._policy(observed, deterministic=True, pending_actions=rows)
            loss = (predicted-target).square().mean()
            self.actor_optimizer.zero_grad(set_to_none=True)
            loss.backward()
            self.actor_optimizer.step()
        after = float(np.sqrt(np.mean((self.act(x, deterministic=True, pending_actions=pending) - y)**2)))
        total = self.extra_state.get("imitation_updates", 0) + updates
        self.extra_state["imitation_updates"] = total
        return dict(method="behavior_cloning", rows=len(x), updates=updates,
                    imitation_updates=total, action_rmse_before=before,
                    action_rmse_after=after,
                    qualification="Demonstration fit; not physical walking qualification")

    def train(self, new_transitions=1):
        """Explicit UTD schedule; callers supply how many new transitions to train."""
        if type(new_transitions) is not int or new_transitions < 0:
            raise ValueError("new_transitions must be a nonnegative integer")
        return self.update(new_transitions * self.config.utd_ratio)

    def update(self, gradient_steps):
        """Explicit update budget, independent of collection and activation."""
        if type(gradient_steps) is not int or gradient_steps < 0:
            raise ValueError("gradient_steps must be a nonnegative integer")
        if gradient_steps and not self.replay_size:
            raise ValueError("Cannot update without replay data")
        torch, config = self.torch, self.config
        metrics = {}
        for _ in range(gradient_steps):
            indices = self.rng.integers(self.replay_size, size=config.batch_size)
            data = {key: torch.as_tensor(value[indices], device=self.device) for key, value in self.replay.items()}
            obs = (data["observations"] - self.mean) / self.scale
            next_obs = (data["next_observations"] - self.mean) / self.scale
            pending = ({key: [rows[index] for index in indices] for key, rows in self.pending_replay.items()}
                       if self.pending_replay is not None else {})
            subset = self.rng.choice(config.ensemble_size, config.target_subset, replace=False)
            with torch.no_grad():
                next_actions, log_prob = self._policy(next_obs, **({"pending_actions": pending["next_pending_actions"]} if pending else {}))
                minimum = torch.stack([self._critic(self.targets[int(i)], next_obs, next_actions,
                    pending.get("next_pending_actions")) for i in subset]).amin(0)
                target = data["rewards"] + data["discounts"] * (minimum - self.log_alpha.exp() * log_prob)
            # Sum critic losses so each independent critic keeps its own MSE scale.
            q_loss = sum((self._critic(critic, obs, data["actions"], pending.get("pending_actions")) - target).square().mean()
                         for critic in self.critics)
            self.critic_optimizer.zero_grad(set_to_none=True)
            q_loss.backward()
            self.critic_optimizer.step()
            self.total_updates += 1
            if self.total_updates % config.policy_delay == 0:
                self.critics.requires_grad_(False)
                actions, log_prob = self._policy(obs, **({"pending_actions": pending["pending_actions"]} if pending else {}))
                mean_q = torch.stack([self._critic(critic, obs, actions, pending.get("pending_actions"))
                                      for critic in self.critics]).mean(0)
                actor_loss = (self.log_alpha.exp().detach() * log_prob - mean_q).mean()
                self.actor_optimizer.zero_grad(set_to_none=True)
                actor_loss.backward()
                self.actor_optimizer.step()
                self.critics.requires_grad_(True)
                alpha_loss = -(self.log_alpha * (log_prob + self.target_entropy).detach()).mean()
                self.alpha_optimizer.zero_grad(set_to_none=True)
                alpha_loss.backward()
                self.alpha_optimizer.step()
                self.policy_updates += 1
                metrics.update(actor_loss=float(actor_loss.detach()), alpha_loss=float(alpha_loss.detach()))
            with torch.no_grad():
                for target_parameter, parameter in zip(self.targets.parameters(), self.critics.parameters()):
                    target_parameter.lerp_(parameter, config.tau)
            metrics["critic_loss"] = float(q_loss.detach()) / config.ensemble_size
        return {**metrics, "alpha": float(self.log_alpha.detach().exp()), "total_updates": self.total_updates,
                "policy_updates": self.policy_updates, "replay_size": self.replay_size,
                "total_transitions": self.total_transitions}

    def save(self, path):
        """Trusted local trainer checkpoint, including the replay needed to resume."""
        payload = {"format": FORMAT, "config": asdict(self.config),
            "observation_mean": self.observation_mean, "observation_scale": self.observation_scale,
            "actor": self.actor.state_dict(), "critics": self.critics.state_dict(), "targets": self.targets.state_dict(),
            "actor_optimizer": self.actor_optimizer.state_dict(), "critic_optimizer": self.critic_optimizer.state_dict(),
            "alpha_optimizer": self.alpha_optimizer.state_dict(), "log_alpha": self.log_alpha.detach(),
            "rng": self.rng.bit_generator.state, "noise_rng": self.noise_rng.get_state(),
            "total_updates": self.total_updates, "policy_updates": self.policy_updates,
            "extra_state": copy.deepcopy(self.extra_state),
            "total_transitions": self.total_transitions, "replay_size": self.replay_size, "replay_cursor": self.replay_cursor,
            "replay": {key: value[:self.replay_size].copy() for key, value in self.replay.items()}}
        if self.pending_replay is not None:
            payload["pending_replay"] = {key: rows[:self.replay_size] for key, rows in self.pending_replay.items()}
        path = Path(path)
        temporary = path.with_name(path.name + ".tmp")
        self.torch.save(payload, temporary)
        temporary.replace(path)

    @classmethod
    def load(cls, path, device="cuda"):
        import torch
        saved = torch.load(path, map_location=device, weights_only=False)
        if saved["format"] != FORMAT:
            raise ValueError("Unsupported REDQ checkpoint")
        learner = cls(REDQConfig(**saved["config"]), device, saved["observation_mean"], saved["observation_scale"])
        for name in ("actor", "critics", "targets", "actor_optimizer", "critic_optimizer", "alpha_optimizer"):
            getattr(learner, name).load_state_dict(saved[name])
        with torch.no_grad():
            learner.log_alpha.copy_(saved["log_alpha"])
        learner.rng.bit_generator.state = saved["rng"]
        learner.noise_rng.set_state(saved["noise_rng"].cpu())
        learner.extra_state = saved.get("extra_state", {})
        for name in ("total_updates", "policy_updates", "total_transitions", "replay_size", "replay_cursor"):
            setattr(learner, name, saved[name])
        for key, value in saved["replay"].items():
            learner.replay[key][:learner.replay_size] = value
        if learner.pending_replay is not None:
            for key, rows in saved["pending_replay"].items():
                learner.pending_replay[key][:learner.replay_size] = _pending_batch(rows, learner.replay_size)
        return learner

    def export_actor(self, path, metadata=None):
        arrays = {"observation_mean": self.observation_mean, "observation_scale": self.observation_scale}
        layers = {"hidden_0": self.actor["hidden"][0], "hidden_1": self.actor["hidden"][2],
                  "mean": self.actor["mean"], "log_std": self.actor["log_std"]}
        for name, layer in layers.items():
            arrays[name + "_weight"] = layer.weight.detach().cpu().numpy()
            arrays[name + "_bias"] = layer.bias.detach().cpu().numpy()
        if self.config.pending_input_dim:
            arrays.update({"pending_" + key: value.detach().cpu().numpy()
                           for key, value in self.actor["pending"].state_dict().items()})
        info = {**(metadata or {}), "format": FORMAT, "observation_dim": self.config.observation_dim,
                "action_dim": self.config.action_dim, "total_updates": self.total_updates,
                "pending_input_dim": self.config.pending_input_dim, "pending_hidden_dim": self.config.pending_hidden_dim,
                "normalization": "frozen-affine", "activation": "relu", "action_distribution": "tanh-gaussian"}
        path = Path(path)
        temporary = path.with_name(path.name + ".tmp")
        with temporary.open("wb") as stream:
            np.savez_compressed(stream, metadata=json.dumps(info), **arrays)
        temporary.replace(path)
        return info

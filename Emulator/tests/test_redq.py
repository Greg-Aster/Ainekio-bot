"""Physical gait learner numerics and deployment/continuation contract."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from gateway.neural_gait.redq import NumpyActor, REDQConfig, REDQLearner


class REDQTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        cls.torch = torch
        cls.threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        cls.torch.set_num_threads(cls.threads)

    def learner(self, **config):
        options = dict(observation_dim=7, ensemble_size=3, batch_size=4,
                       replay_capacity=13, utd_ratio=2, policy_delay=2, seed=31)
        options.update(config)
        return REDQLearner(REDQConfig(**options), device="cpu",
                           observation_mean=np.arange(7) / 10, observation_scale=np.arange(7) + 1)

    def transitions(self, size=9):
        rng = np.random.default_rng(8)
        return (rng.normal(size=(size, 7)), rng.uniform(-1, 1, (size, 12)),
                rng.normal(size=size), rng.normal(size=(size, 7)), rng.choice([0, .85, .99], size=size))

    def test_random_subset_bellman_target_uses_entropy_and_supplied_discounts(self):
        learner = self.learner(policy_delay=20, tau=.1)
        torch = self.torch
        with torch.no_grad():
            for i, (critic, target) in enumerate(zip(learner.critics, learner.targets)):
                for parameter in critic.parameters():
                    parameter.zero_()
                for parameter in target.parameters():
                    parameter.zero_()
                critic[-1].bias.fill_(i + 1)
                target[-1].bias.fill_((i + 1) * 10)
        learner.add_transitions(np.zeros((4, 7)), np.zeros((4, 12)), [1, 2, 3, 4],
                                np.zeros((4, 7)), [0, .5, .8, .99])
        rng = np.random.default_rng(31)
        indices = rng.integers(4, size=4)
        subset = rng.choice(3, 2, replace=False)
        learner._policy = lambda observations: (torch.zeros((len(observations), 12)), torch.full((len(observations), 1), -2.))
        target = np.array([1, 2, 3, 4])[indices] + np.array([0, .5, .8, .99])[indices] * ((min(subset) + 1) * 10 + .4)
        expected = np.mean([(i - target) ** 2 for i in (1, 2, 3)])
        result = learner.update(1)
        self.assertAlmostEqual(result["critic_loss"], expected, places=4)
        self.assertEqual(learner.policy_updates, 0)
        for i, (critic, target_net) in enumerate(zip(learner.critics, learner.targets)):
            expected_bias = .9 * (i + 1) * 10 + .1 * critic[-1].bias.detach()
            torch.testing.assert_close(target_net[-1].bias, expected_bias)

    def test_imitation_fits_actor_without_reward_updates_and_exports_the_same_policy(self):
        learner = self.learner(batch_size=16, pending_input_dim=14)
        learner.add_transitions(*self.transitions())
        learner.update(2)
        obs = np.zeros((32, 7), np.float32)
        pending = [np.full((1, 14), -1 if i % 2 else 1, np.float32) for i in range(len(obs))]
        targets = np.asarray([np.full(12, -.8 if i % 2 else .8) for i in range(len(obs))], np.float32)
        critics = {k: v.clone() for k, v in learner.critics.state_dict().items()}
        target_critics = {k: v.clone() for k, v in learner.targets.state_dict().items()}
        log_std = {k: v.clone() for k, v in learner.actor['log_std'].state_dict().items()}
        replay = {k: v[:learner.replay_size].copy() for k, v in learner.replay.items()}
        counters = (learner.total_updates, learner.policy_updates, learner.total_transitions)
        alpha = learner.log_alpha.clone()
        report = learner.imitate(obs, targets, 160, pending_actions=pending)
        self.assertLess(report['action_rmse_after'], .05)
        self.assertLess(report['action_rmse_after'], report['action_rmse_before']/5)
        self.assertEqual((learner.total_updates, learner.policy_updates, learner.total_transitions), counters)
        self.assertEqual(report['imitation_updates'], 160)
        self.assertTrue(self.torch.equal(alpha, learner.log_alpha))
        for module, before in ((learner.critics, critics), (learner.targets, target_critics),
                               (learner.actor['log_std'], log_std)):
            for key, value in before.items():
                self.assertTrue(self.torch.equal(value, module.state_dict()[key]), key)
        for key, value in replay.items():
            np.testing.assert_array_equal(value, learner.replay[key][:learner.replay_size])
        with tempfile.TemporaryDirectory() as directory:
            checkpoint, exported = Path(directory)/'learner.pt', Path(directory)/'actor.npz'
            learner.save(checkpoint); learner.export_actor(exported)
            restored = REDQLearner.load(checkpoint, 'cpu')
            self.assertEqual(restored.extra_state['imitation_updates'], 160)
            np.testing.assert_allclose(NumpyActor.load(exported).act(obs, pending_actions=pending),
                learner.act(obs, deterministic=True, pending_actions=pending), atol=2e-6, rtol=2e-6)

    def test_imitation_does_not_clip_out_of_domain_demonstrations(self):
        learner = self.learner()
        before = {k: v.clone() for k, v in learner.actor.state_dict().items()}
        with self.assertRaisesRegex(ValueError, 'physical action domain'):
            learner.imitate(np.zeros((1, 7)), np.full((1, 12), 1.01), 1)
        for key, value in before.items():
            self.assertTrue(self.torch.equal(value, learner.actor.state_dict()[key]))
        self.assertNotIn('imitation_updates', learner.extra_state)

    def test_utd_policy_delay_and_temperature_are_persistent_across_calls(self):
        learner = self.learner(utd_ratio=3, policy_delay=4)
        learner.add_transitions(*self.transitions())
        before = {key: value.clone() for key, value in learner.actor.state_dict().items()}
        learner.train(new_transitions=1)
        self.assertEqual(learner.total_updates, 3)
        self.assertEqual(learner.policy_updates, 0)
        self.assertTrue(all(self.torch.equal(value, learner.actor.state_dict()[key]) for key, value in before.items()))
        learner.update(1)
        self.assertEqual(learner.policy_updates, 1)
        self.assertTrue(any(not self.torch.equal(value, learner.actor.state_dict()[key]) for key, value in before.items()))
        self.assertNotEqual(float(learner.log_alpha.detach().exp()), learner.config.initial_alpha)
        self.assertTrue(np.isfinite(list(learner.update(0).values())).all())

    def test_checkpoint_resumes_replay_rng_optimizer_temperature_and_next_update_exactly(self):
        learner = self.learner()
        learner.add_transitions(*self.transitions(19))  # Exercise ring wrap and overwrite.
        learner.update(3)  # Mid-delay checkpoint: next update must include actor/alpha.
        learner.extra_state["physical_imported"] = ["a" * 64, "b" * 64]
        learner.extra_state["collection"] = {"trial": "physical-1", "intervals": 19}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "learner.pt"
            learner.save(path)
            restored = REDQLearner.load(path, "cpu")
            self.assertEqual(restored.extra_state, learner.extra_state)
            restored.extra_state["physical_imported"].append("c" * 64)
            self.assertEqual(len(learner.extra_state["physical_imported"]), 2)
            self.assertEqual(learner.replay_cursor, restored.replay_cursor)
            for key in learner.replay:
                np.testing.assert_array_equal(learner.replay[key], restored.replay[key])
            obs = self.transitions(2)[0]
            np.testing.assert_array_equal(learner.act(obs), restored.act(obs))
            self.assertEqual(learner.update(3), restored.update(3))
            for name in ("actor", "critics", "targets"):
                for key, value in getattr(learner, name).state_dict().items():
                    self.assertTrue(self.torch.equal(value, getattr(restored, name).state_dict()[key]), (name, key))
            self.assertTrue(self.torch.equal(learner.log_alpha, restored.log_alpha))

    def test_numpy_export_matches_deterministic_and_stochastic_actor_with_normalization(self):
        learner = self.learner()
        learner.add_transitions(*self.transitions())
        learner.train()
        observations = self.transitions(5)[0]
        noise = np.random.default_rng(17).normal(size=(5, 12)).astype(np.float32)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "actor.npz"
            learner.export_actor(path, {"observation_schema": "fixture", "checkpoint": "round-1"})
            actor = NumpyActor.load(path)
            self.assertEqual(actor.metadata["checkpoint"], "round-1")
            for deterministic in (True, False):
                np.testing.assert_allclose(actor.act(observations, deterministic, noise=noise),
                    learner.act(observations, deterministic, noise=noise), rtol=2e-6, atol=2e-6)
            self.assertEqual(actor.act(observations[0]).shape, (12,))
            with self.assertRaisesRegex(ValueError, "explicit RNG"):
                actor.act(observations, deterministic=False)
            # Import and execute deployment in a fresh process without loading torch.
            script = "from gateway.neural_gait.redq import NumpyActor; import sys,numpy as np; a=NumpyActor.load(sys.argv[1]); assert a.act(np.zeros(7)).shape==(12,); assert 'torch' not in sys.modules"
            subprocess.run([sys.executable, "-c", script, str(path)], env=os.environ.copy(), check=True)

    def test_transition_validation_does_not_mutate_replay(self):
        learner = self.learner()
        values = list(self.transitions())
        values[1][0, 0] = 2
        with self.assertRaises(ValueError):
            learner.add_transitions(*values)
        self.assertEqual(learner.total_transitions, 0)
        self.assertEqual(learner.replay_size, 0)
        self.assertEqual(REDQConfig(7).ensemble_size, 10)
        self.assertEqual(REDQConfig(7).target_subset, 2)
        with self.assertRaises(ValueError):
            learner.update(1)

    def test_pending_actor_processes_every_ordered_row_and_numpy_matches(self):
        learner = self.learner(pending_input_dim=14)
        observations = self.transitions(4)[0]
        rng = np.random.default_rng(9)
        pending = [rng.normal(size=(length, 14)).astype(np.float32) for length in (0, 1, 37, 257)]
        noise = rng.normal(size=(4, 12)).astype(np.float32)
        consumed = []
        hook = learner.actor["pending"].register_forward_pre_hook(lambda module, args: consumed.append(len(args[0])))
        expected = learner.act(observations, deterministic=True, pending_actions=pending)
        hook.remove()
        self.assertEqual(sum(consumed), sum(map(len, pending)))
        reversed_rows = [rows[::-1].copy() for rows in pending]
        changed = learner.act(observations, deterministic=True, pending_actions=reversed_rows)
        self.assertGreater(np.max(np.abs(changed[2:] - expected[2:])), 1e-5)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "actor.npz"
            learner.export_actor(path)
            actor = NumpyActor.load(path)
            for deterministic in (True, False):
                np.testing.assert_allclose(actor.act(observations, deterministic, noise=noise, pending_actions=pending),
                    learner.act(observations, deterministic, noise=noise, pending_actions=pending), rtol=2e-6, atol=2e-6)
            np.testing.assert_allclose(actor.act(observations[3], pending_actions=pending[3]), expected[3], atol=2e-6)
            script = ("from gateway.neural_gait.redq import NumpyActor; import sys,numpy as np; "
                      "a=NumpyActor.load(sys.argv[1]); "
                      "assert a.act(np.zeros(7),pending_actions=np.ones((257,14))).shape==(12,); "
                      "assert 'torch' not in sys.modules")
            subprocess.run([sys.executable, "-c", script, str(path)], env=os.environ.copy(), check=True)

    def test_pending_upgrade_preserves_policy_critics_optimizer_history_and_resume(self):
        import copy
        learner = self.learner()
        learner.add_transitions(*self.transitions(19))
        learner.update(3)
        learner.extra_state = {"physical_imported": [str(i) for i in range(19)]}
        observations = self.transitions(3)[0]
        actions = self.transitions(3)[1]
        expected = learner.act(observations, deterministic=True)
        obs_tensor = (self.torch.as_tensor(observations, dtype=self.torch.float32) - learner.mean) / learner.scale
        act_tensor = self.torch.as_tensor(actions, dtype=self.torch.float32)
        with self.torch.no_grad():
            critic_values = [learner._critic(critic, obs_tensor, act_tensor).clone() for critic in learner.critics]
            target_values = [learner._critic(critic, obs_tensor, act_tensor).clone() for critic in learner.targets]
        actor_weight = learner.actor["hidden"][0].weight.detach().clone()
        actor_state = copy.deepcopy(learner.actor_optimizer.state[learner.actor["hidden"][0].weight])
        critic_states = [copy.deepcopy(learner.critic_optimizer.state[c[0].weight]) for c in learner.critics]
        counters = (learner.total_updates, learner.policy_updates, learner.total_transitions, learner.replay_size, learner.replay_cursor)
        replay = {key: value.copy() for key, value in learner.replay.items()}
        rng_state, noise_state = copy.deepcopy(learner.rng.bit_generator.state), learner.noise_rng.get_state().clone()
        pending = [np.full((i % 4, 14), i / 20, np.float32) for i in range(learner.replay_size)]
        following = [np.full((i % 5, 14), -i / 20, np.float32) for i in range(learner.replay_size)]
        learner.upgrade_pending_inputs(pending, following)
        self.assertEqual(learner.config.pending_input_dim, 14)
        self.assertEqual(counters, (learner.total_updates, learner.policy_updates, learner.total_transitions, learner.replay_size, learner.replay_cursor))
        self.assertEqual(rng_state, learner.rng.bit_generator.state)
        self.assertTrue(self.torch.equal(noise_state, learner.noise_rng.get_state()))
        for key in replay:
            np.testing.assert_array_equal(replay[key], learner.replay[key])
        weight = learner.actor["hidden"][0].weight
        self.torch.testing.assert_close(weight[:, :7], actor_weight, rtol=0, atol=0)
        self.assertEqual(int(self.torch.count_nonzero(weight[:, 7:])), 0)
        for state, current, old_width in [(actor_state, learner.actor_optimizer.state[weight], 7)] + [
            (old, learner.critic_optimizer.state[c["hidden"][0].weight], 19)
            for old, c in zip(critic_states, learner.critics)]:
            for key, value in state.items():
                if value.ndim == 2:
                    self.torch.testing.assert_close(current[key][:, :old_width], value, rtol=0, atol=0)
                    self.assertEqual(int(self.torch.count_nonzero(current[key][:, old_width:])), 0)
                else:
                    self.torch.testing.assert_close(current[key], value, rtol=0, atol=0)
        np.testing.assert_allclose(learner.act(observations, deterministic=True, pending_actions=pending[:3]), expected, atol=1e-7)
        with self.torch.no_grad():
            for group, values in ((learner.critics, critic_values), (learner.targets, target_values)):
                for critic, value in zip(group, values):
                    self.torch.testing.assert_close(learner._critic(critic, obs_tensor, act_tensor, pending[:3]), value, atol=1e-7, rtol=1e-6)
        before_gru = {key: value.clone() for key, value in learner.actor["pending"].state_dict().items()}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "learner.pt"
            learner.save(path)
            restored = REDQLearner.load(path, "cpu")
            self.assertEqual(restored.extra_state, learner.extra_state)
            for key in learner.pending_replay:
                for i in range(learner.replay_size):
                    np.testing.assert_array_equal(learner.pending_replay[key][i], restored.pending_replay[key][i])
            np.testing.assert_array_equal(learner.act(observations, pending_actions=pending[:3]), restored.act(observations, pending_actions=pending[:3]))
            self.assertEqual(learner.update(6), restored.update(6))
            for name in ("actor", "critics", "targets"):
                for key, value in getattr(learner, name).state_dict().items():
                    self.assertTrue(self.torch.equal(value, getattr(restored, name).state_dict()[key]), (name, key))
        self.assertTrue(any(not self.torch.equal(value, learner.actor["pending"].state_dict()[key]) for key, value in before_gru.items()))

    def test_pending_replay_ring_and_invalid_sequence_are_transactional(self):
        learner = self.learner(pending_input_dim=14)
        pending = [np.full((i, 14), i / 20, np.float32) for i in range(19)]
        learner.add_transitions(*self.transitions(19), pending_actions=pending, next_pending_actions=pending[::-1])
        for source in range(6, 19):
            slot = source % learner.config.replay_capacity
            np.testing.assert_array_equal(learner.pending_replay["pending_actions"][slot], pending[source])
            np.testing.assert_array_equal(learner.pending_replay["next_pending_actions"][slot], pending[18-source])
        with self.assertRaisesRegex(ValueError, "fourteen"):
            learner.add_transitions(*self.transitions(1), pending_actions=[np.ones((3, 13))])
        self.assertEqual(learner.total_transitions, 19)
        self.assertEqual(learner.replay_cursor, 6)

    def test_cuda_training_export_and_exact_checkpoint_continuation(self):
        if not self.torch.cuda.is_available():
            self.skipTest("CUDA is not installed on this test host")
        learner = REDQLearner(REDQConfig(7, batch_size=8, replay_capacity=20, utd_ratio=2, policy_delay=2), "cuda")
        learner.add_transitions(*self.transitions())
        learner.update(3)
        pending = [np.full((i % 4, 14), i / 10, np.float32) for i in range(learner.replay_size)]
        learner.upgrade_pending_inputs(pending, pending[::-1])
        with tempfile.TemporaryDirectory() as directory:
            checkpoint, actor_path = Path(directory) / "learner.pt", Path(directory) / "actor.npz"
            learner.save(checkpoint)
            restored = REDQLearner.load(checkpoint, "cuda")
            self.assertEqual(learner.update(1), restored.update(1))
            learner.export_actor(actor_path)
            observations = self.transitions()[0]
            np.testing.assert_allclose(NumpyActor.load(actor_path).act(observations, pending_actions=pending),
                learner.act(observations, deterministic=True, pending_actions=pending), rtol=1e-5, atol=1e-5)


if __name__ == "__main__":
    unittest.main()

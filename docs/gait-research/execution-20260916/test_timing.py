"""Focused offline checks: timing continuity, synchronization, looping, provenance."""
import copy
import hashlib
import json
import math
import unittest
from pathlib import Path

from timing import build_schedule, event_times, locate

ROOT = Path(__file__).resolve().parent


def contract(name):
    return json.loads((ROOT / 'contracts' / f'{name}.json').read_text())


class TimingTests(unittest.TestCase):
    def test_all_twelve_demonstrations_preserve_phase_time(self):
        paths = list((ROOT / 'contracts').glob('*.json'))
        self.assertEqual(len(paths), 12)
        for path in paths:
            c = json.loads(path.read_text())
            s = build_schedule(c)
            for phase in s['phases']:
                for fraction in (0, .25, .5, .75, .9999):
                    elapsed = phase['start_s'] + fraction * (phase['end_s'] - phase['start_s'])
                    sample = locate(s, elapsed)
                    self.assertAlmostEqual(sample['source_time_s'], phase['source_start_s'] + elapsed - phase['start_s'], places=8)
                    self.assertAlmostEqual(sample['source_rate'], 1, places=8)
                    self.assertAlmostEqual(sample['source_acceleration'], 0, places=7)
            self.assertFalse(s['hardware_ready'])
            self.assertTrue(locate(s, s['duration_s'])['complete'])

    def test_uniform_speed_and_acceleration_chain_rule(self):
        s = build_schedule(contract('wave'), 'research_candidate', scale=2)
        self.assertAlmostEqual(s['duration_s'], 8)
        sample = locate(s, 3)
        self.assertAlmostEqual(sample['source_time_s'], 6)
        self.assertAlmostEqual(sample['source_rate'], 2)
        self.assertAlmostEqual(sample['source_acceleration'], 0)
        # An analytic q(s)=s^2 must have twice the speed and four times the
        # acceleration of the source evaluated at the same source position.
        source_s = sample['source_time_s']
        velocity = 2 * source_s * sample['source_rate']
        acceleration = 2 * sample['source_rate']**2 + 2 * source_s * sample['source_acceleration']
        self.assertAlmostEqual(velocity, 24)
        self.assertAlmostEqual(acceleration, 8)
        self.assertAlmostEqual(event_times(s, 15.2)[0], 7.6)

    def test_nonuniform_clock_is_monotone_and_c2_at_boundaries(self):
        c = contract('wave')
        durations = c['timing_profiles']['research_candidate']['duration_s']
        for i, key in enumerate(durations):
            durations[key] *= (.45, 1.3, .8)[i % 3]
        s = build_schedule(c, 'research_candidate')
        previous = -1
        for i in range(2001):
            sample = locate(s, s['duration_s'] * i / 2001)
            self.assertGreaterEqual(sample['source_time_s'], previous)
            self.assertGreater(sample['source_rate'], 0)
            previous = sample['source_time_s']
        for phase in s['phases'][:-1]:
            boundary = phase['end_s']
            before = locate(s, boundary - 1e-8)
            after = locate(s, boundary + 1e-8)
            self.assertAlmostEqual(before['source_time_s'], after['source_time_s'], places=6)
            self.assertAlmostEqual(before['source_rate'], after['source_rate'], places=6)
            self.assertAlmostEqual(before['source_acceleration'], after['source_acceleration'], places=4)
        for cue in (0, 3, 6.7, 15.2):
            event = event_times(s, cue)
            self.assertEqual(len(event), 1)
            self.assertAlmostEqual(locate(s, event[0])['source_time_s'], cue, places=8)

    def test_walk_repeats_without_extra_closing_knot_hold(self):
        c = contract('walk')
        s = build_schedule(c, cycles=3)
        self.assertAlmostEqual(s['duration_s'], 32.4)
        self.assertAlmostEqual(locate(s, 16.2)['source_time_s'], 12.2)
        self.assertEqual(locate(s, 16.2)['cycle'], 1)
        self.assertAlmostEqual(locate(s, 24.2)['source_time_s'], 24.2)
        self.assertEqual(locate(s, 24.2)['section'], 'exit')
        self.assertEqual(event_times(s, 13.0), [13.0, 17.0, 21.0])
        self.assertAlmostEqual(build_schedule(c, cycles=10)['duration_s'], 60.4)

    def test_completion_is_terminal_hold(self):
        s = build_schedule(contract('sit'))
        at_end, later = locate(s, 5), locate(s, 50)
        self.assertEqual(at_end, later)
        self.assertEqual(at_end['source_time_s'], 5)
        self.assertEqual(at_end['source_rate'], 0)
        self.assertEqual(event_times(s, 5), [5])

    def test_rejects_unknown_or_uncalibrated_settings(self):
        c = contract('wave')
        for profile in ('operating', 'missing'):
            with self.assertRaises(ValueError):
                build_schedule(c, profile)
        for scale in (0, -1, math.inf, math.nan):
            with self.assertRaises(ValueError):
                build_schedule(c, scale=scale)
        for cycles in (0, 2, 1.5, True):
            with self.assertRaises(ValueError):
                build_schedule(c, cycles=cycles)
        for value in (None, 0, -1, True, math.inf):
            bad = copy.deepcopy(c)
            durations = bad['timing_profiles']['research_candidate']['duration_s']
            durations[next(iter(durations))] = value
            with self.assertRaises(ValueError):
                build_schedule(bad, 'research_candidate')
        bad = copy.deepcopy(c)
        bad['timing_profiles']['research_candidate']['duration_s']['unexpected'] = 1
        with self.assertRaises(ValueError):
            build_schedule(bad, 'research_candidate')

    def test_catalog_and_shared_policy_bindings(self):
        catalog = json.loads((ROOT / 'catalog.json').read_text())
        policy_sha = hashlib.sha256((ROOT / 'execution-policy.json').read_bytes()).hexdigest()
        for item in catalog['motions']:
            p = ROOT / item['contract']
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), item['sha256'])
            c = json.loads(p.read_text())
            self.assertEqual(c['policy_sha256'], policy_sha)
            self.assertFalse(c['hardware_ready'])
            self.assertTrue(all(v is None for v in c['timing_profiles']['operating']['duration_s'].values()))
            self.assertEqual(c['leg_order'], ['FL', 'FR', 'RL', 'RR'])
            self.assertEqual(c['joint_order'], ['h_Part002', 'alpha_Part006', 'theta_Part005'])


if __name__ == '__main__':
    unittest.main(verbosity=2)

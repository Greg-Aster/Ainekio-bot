"""Imported MicroDuck task, sensor-only deployment, and existing service lifecycle."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gateway.neural_gait.contract import PROPRIO_SCHEMA, JOINTS, observation_size
from Emulator.tests.test_neural_gait_sensors import robot_fixture


def config_fixture():
    from gateway.neural_gait.environment import EnvironmentConfig
    return EnvironmentConfig(robot=robot_fixture(), target_limits_deg=[[-80.,80.]]*12,
        foot_action_scale_mm=[30.,20.,30.], observation_schema=PROPRIO_SCHEMA,
        episode_seconds=40., command=[.08,.04,1.], imu_prehistory_s=4.,
        control_hz=50, physics_hz=500)


@unittest.skipUnless(importlib.util.find_spec("onnxruntime") and importlib.util.find_spec("rsl_rl"),
                     "Install optional gait training/inference dependencies")
class MicroduckActorTests(unittest.TestCase):
    def export(self, path):
        import numpy as np
        import onnx
        import torch
        from tensordict import TensorDict
        from rsl_rl.models import MLPModel
        size = observation_size(PROPRIO_SCHEMA)
        torch.manual_seed(17)
        values = torch.randn(16,size)
        policy = MLPModel(TensorDict({"actor":values},batch_size=[16]),
                          {"actor":["actor"]}, "actor", 12,
                          hidden_dims=(32,16), obs_normalization=True,
                          distribution_cfg={"class_name":
                              "gateway.neural_gait.microduck_policy:FootGaussianDistribution"})
        policy.update_normalization(TensorDict({"actor":values},batch_size=[16]))
        policy.eval()
        export = policy.as_onnx(verbose=False).eval()
        torch.onnx.export(export,export.get_dummy_inputs(),str(path),opset_version=18,
                          input_names=export.input_names,output_names=export.output_names,
                          dynamo=False)
        model=onnx.load(str(path))
        onnx.helper.set_model_props(model, {"ainekio_schema":PROPRIO_SCHEMA,
            "ainekio_action":"normalized-foot-offsets-v1"})
        onnx.save(model,str(path))
        return policy, values[:2].numpy()

    def test_export_keeps_normalization_and_each_required_sensor_influences_actions(self):
        import numpy as np
        import torch
        from tensordict import TensorDict
        from gateway.neural_gait.microduck_actor import MicroduckActor, sensor_influence
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"policy.onnx"
            policy, values=self.export(path)
            actor=MicroduckActor(path)
            with torch.inference_mode():
                expected=policy(TensorDict({"actor":torch.as_tensor(values)},batch_size=[2])).numpy()
            actual,_=actor.predict(values)
            np.testing.assert_allclose(actual,np.clip(expected,-1,1),atol=2e-7)
            self.assertTrue(all(value>0 for value in sensor_influence(actor,values).values()))
            self.assertLess(float(abs(actual).max()),1.)

    def test_bounded_distribution_likelihood_kl_and_entropy_match_executed_actions(self):
        import torch
        from torch.distributions import Normal, TransformedDistribution, TanhTransform
        from gateway.neural_gait.microduck_policy import FootGaussianDistribution
        distribution=FootGaussianDistribution(12)
        means=torch.linspace(-.5,.5,12).expand(32,-1)
        distribution.update(means)
        actions=distribution.sample()
        self.assertTrue(bool((actions.abs()<1).all()))
        expected=TransformedDistribution(Normal(means,torch.ones_like(means)),[TanhTransform()])
        torch.testing.assert_close(distribution.log_prob(actions),expected.log_prob(actions).sum(-1))
        torch.testing.assert_close(distribution.kl_divergence(distribution.params,distribution.params),torch.zeros(32))
        self.assertTrue(bool((distribution.std<1).all()))
        with torch.no_grad():
            distribution.log_std_param.fill_(2.)
        distribution.update(torch.zeros_like(means))
        distribution.entropy.mean().backward()
        self.assertTrue(bool((distribution.log_std_param.grad<0).all()),
                        "Bounded entropy must discourage saturated latent exploration")

    def test_loader_rejects_microduck_biped_contract(self):
        import onnx
        from gateway.neural_gait.microduck_actor import MicroduckActor
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"policy.onnx"
            self.export(path)
            model=onnx.load(str(path))
            onnx.helper.set_model_props(model,{"ainekio_schema":"microduck-61d"})
            onnx.save(model,str(path))
            with self.assertRaisesRegex(ValueError,"sensor/foot-action"):
                MicroduckActor(path)

    def test_service_load_and_infer_use_exported_actor_without_changing_motion_owner(self):
        from dataclasses import asdict
        from gateway.neural_gait.environment import representation_identity, ENVIRONMENT_VERSION, GaitEnvironment
        from gateway.neural_gait.server import Runtime
        from gateway.neural_gait.artifacts import save_json
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run=root/"abcd";run.mkdir()
            self.export(run/"policy.onnx")
            config=config_fixture()
            save_json(run/"manifest.json",dict(kind="microduck-mjlab",algorithm="PPO",
                environment=asdict(config),schema=PROPRIO_SCHEMA,policy="policy.onnx",
                representation=representation_identity(),environment_version=ENVIRONMENT_VERSION))
            runtime=Runtime(root)
            runtime.load("abcd")
            self.assertEqual(runtime.kind,"microduck-mjlab")
            env=GaitEnvironment(config,include_assembly=False)
            try:
                env.reset(seed=3)
                result=runtime.infer(env.observation())
                self.assertEqual(result["execution"],"preview_only")
                self.assertEqual(len(result["action"]),12)
                self.assertEqual(result["schema"],PROPRIO_SCHEMA)
            finally:
                env.close()

    def test_imported_training_uses_the_existing_process_owner(self):
        from dataclasses import asdict
        from gateway.neural_gait.server import Runtime
        environment=asdict(config_fixture())
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict("os.environ", {"AINEKIO_MICRODUCK_PYTHON":"/usr/bin/python3"}), \
             patch("gateway.neural_gait.server.subprocess.Popen") as process:
            process.return_value.poll.return_value=None
            runtime=Runtime(directory)
            payload=dict(recipe="microduck-mjlab-v1",steps=7680,workers=64,
                         environment=environment,device="cuda:0")
            result=runtime.start_training(payload)
            command=process.call_args.args[0]
            self.assertEqual(command[:3],["/usr/bin/python3","-m","gateway.neural_gait.microduck"])
            self.assertEqual(command[command.index("--iterations")+1],"5")
            self.assertEqual(runtime.training_id,result["run_id"])
            with self.assertRaisesRegex(ValueError,"already active"):
                runtime.start_training(payload)


@unittest.skipUnless(importlib.util.find_spec("mjlab") and importlib.util.find_spec("mjlab_microduck"),
                     "Use the separate imported MicroDuck environment")
class MicroduckTaskTests(unittest.TestCase):
    def test_action_reset_observe_decode_and_apply_keep_sensor_and_mujoco_contracts(self):
        import torch
        from dataclasses import asdict, replace
        from types import SimpleNamespace
        from gateway.neural_gait.contract import PROPRIO_SCHEMA
        from gateway.neural_gait.microduck import FootAction, FootActionCfg
        positions=torch.full((2,12),-.2)
        target=torch.zeros_like(positions)
        def set_target(value,joint_ids):
            target[:,joint_ids]=value
        entity=SimpleNamespace(data=SimpleNamespace(joint_pos=positions),
            find_joints=lambda *args,**kwargs:(list(range(12)),list(JOINTS)),
            set_joint_position_target=set_target)
        scene={'robot':entity,'robot/accel':SimpleNamespace(data=torch.tensor([[0.,0.,9.81]]).expand(2,-1)),
               'robot/gyro':SimpleNamespace(data=torch.zeros(2,3))}
        env=SimpleNamespace(num_envs=2,device='cpu',scene=scene,common_step_counter=0,
            command_manager=SimpleNamespace(get_command=lambda name:torch.zeros(2,3)))
        config=replace(config_fixture(),observation_schema=PROPRIO_SCHEMA,feedback_noise_raw_std=0.)
        action=FootAction(FootActionCfg(entity_name='robot',environment=asdict(config)),env)
        observation=action.observations()
        torch.testing.assert_close(observation[:,:12],positions,atol=.001,rtol=0.)
        action.process_actions(torch.full((2,12),.1))
        action.apply_actions()
        self.assertEqual(target.dtype,torch.float32)
        self.assertEqual(action.logical.dtype,torch.float64)
        self.assertTrue(bool(target.isfinite().all()))
        other=action.history[0].clone()
        positions[1]=-.1
        action.reset(torch.tensor([1]))
        observation=action.observations()
        torch.testing.assert_close(action.history[0],other)
        torch.testing.assert_close(observation[1,:12],positions[1],atol=.001,rtol=0.)
        self.assertTrue(bool((action.history[1,1:]==0).all()))

    def test_periodic_runner_save_keeps_the_existing_resume_checkpoint_current(self):
        from types import SimpleNamespace
        from gateway.neural_gait.microduck import AinekioOnPolicyRunner
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'learner').mkdir()
            runner=SimpleNamespace(logger=SimpleNamespace(log_dir=str(root/'learner')))
            def upstream_save(self,path,infos):
                Path(path).write_bytes(b'checkpoint')
            with patch('gateway.neural_gait.microduck.MjlabOnPolicyRunner.save',upstream_save):
                AinekioOnPolicyRunner.save(runner,str(root/'learner/model_50.pt'))
                self.assertEqual((root/'learner.pt').read_bytes(),b'checkpoint')
                AinekioOnPolicyRunner.save(runner,str(root/'learner.pt'))
                self.assertEqual((root/'learner/model_50.pt').read_bytes(),b'checkpoint')

    def test_failure_keeps_completed_step_count(self):
        from gateway.neural_gait.microduck import train
        with tempfile.TemporaryDirectory() as directory:
            def fail(*args):
                (Path(directory)/'progress.json').write_text(json.dumps(dict(state='training',steps=73728)))
                raise ValueError('recorded failure')
            with patch('gateway.neural_gait.microduck.make_config',side_effect=fail):
                with self.assertRaisesRegex(ValueError,'recorded failure'):
                    train(directory,config_fixture(),iterations=5)
            progress=json.loads((Path(directory)/'progress.json').read_text())
            self.assertEqual(progress['state'],'error')
            self.assertEqual(progress['steps'],73728)

    def test_actual_upstream_factory_is_adapted_to_closed_chain_quadruped(self):
        import mujoco
        from gateway.neural_gait.microduck import make_config, sensor_observations, MG90SActuatorCfg
        cfg=make_config(config_fixture(),num_envs=2)
        robot=cfg.scene.entities["robot"].build()
        model=robot.spec.compile()
        self.assertEqual(model.nu,12)
        self.assertEqual(model.neq,4)
        self.assertAlmostEqual(float(model.body_mass.sum()),.650,places=6)
        self.assertLessEqual(sum((model.geom_contype|model.geom_conaffinity)!=0),24)
        self.assertTrue(all(model.joint(name).id>=0 for name in JOINTS))
        self.assertIsInstance(cfg.scene.entities["robot"].articulation.actuators[0],MG90SActuatorCfg)
        self.assertIs(cfg.observations["actor"].terms["sensors"].func,sensor_observations)
        self.assertEqual(set(cfg.observations["actor"].terms),{"sensors"})
        self.assertEqual(set(cfg.commands),{"twist"})
        self.assertNotIn("action_rate_weight",cfg.curriculum)
        self.assertEqual(cfg.commands["twist"].ranges.lin_vel_x,(-.15,.20))
        self.assertEqual(cfg.commands["twist"].ranges.ang_vel_z,(-1.,1.))
        self.assertEqual(cfg.episode_length_s,40.)
        from gateway.neural_gait import microduck_mdp
        self.assertIs(cfg.rewards['tracking_twist'].func,microduck_mdp.tracking_twist)
        self.assertIn('action_change',cfg.rewards)
        self.assertIn('nan_state',cfg.terminations)
        self.assertEqual(cfg.rewards['foot_clearance'].weight,-.2)
        self.assertNotIn('air_time',cfg.rewards)
        self.assertIs(cfg.rewards['alternating_stride'].func,microduck_mdp.alternating_stride)
        self.assertIs(cfg.terminations['body_collapsed'].func,microduck_mdp.body_collapsed)
        self.assertIs(cfg.events['push_robot'].func,microduck_mdp.push_robot)
        self.assertIs(cfg.curriculum['walking_difficulty'].func,microduck_mdp.WalkingDifficulty)

    def test_pupper_anti_hop_diagonal_stride_and_scoot_prevention(self):
        import torch
        from types import SimpleNamespace
        from gateway.neural_gait import microduck_mdp as mdp
        command=torch.tensor([[.15,0.,0.]]).expand(3,-1)
        curriculum=SimpleNamespace(widths=torch.tensor([.1,.1,.5]),
                                   score_sum=torch.zeros(3),score_count=torch.zeros(3),elapsed=torch.zeros(3))
        # Row 0: diagonal trot stance (RL=1, RR=0, FL=0, FR=1), upright
        # Row 1: front-leg hop (RL=1, RR=1, FL=0, FR=0), upright
        # Row 2: rear pelvis pitched down/scooting (up_b_x = +0.55, up_b_z = +0.835)
        found=torch.tensor([[1.,0.,0.,1.],[1.,1.,0.,0.],[1.,1.,1.,1.]])
        grav=torch.tensor([[0.,0.,-1.],[0.,0.,-1.],[-.55,0.,-.835]])
        robot=SimpleNamespace(root_link_lin_vel_b=torch.zeros(3,3),
            root_link_ang_vel_b=torch.zeros(3,3),projected_gravity_b=grav)
        env=SimpleNamespace(scene={'robot':SimpleNamespace(data=robot),
            'feet_ground_contact':SimpleNamespace(data=SimpleNamespace(found=found))},
            command_manager=SimpleNamespace(get_command=lambda name:command),
            curriculum_manager=SimpleNamespace(get_term_cfg=lambda name:SimpleNamespace(func=curriculum)),
            extras={'log':{}})
        stride=mdp.alternating_stride(env)
        self.assertGreater(float(stride[0]),0.)
        self.assertLess(float(stride[1]),0.)
        collapsed=mdp.body_collapsed(env)
        self.assertEqual(collapsed.tolist(),[False,False,True])
        upright=mdp.upright_cost(env)
        self.assertGreater(float(upright[2]),float(upright[0])+0.5)
        # Lifting one front and one rear swing foot by 25 mm while stance feet stay grounded must NOT trigger body_collapsed,
        # whereas retracting both rear legs (+20 mm, +22 mm) while extending FR (-12 mm) MUST trigger body_collapsed.
        foot_b_mm=torch.tensor([
            [[0.,0.,0.],[0.,0.,25.],[0.,0.,25.],[0.,0.,0.]],
            [[0.,0.,20.1],[0.,0.,22.4],[0.,0.,12.9],[0.,0.,-11.6]],
            [[0.,0.,0.],[0.,0.,25.],[0.,0.,25.],[0.,0.,0.]],
        ])
        body_mock=SimpleNamespace(O=torch.zeros(2),origin=torch.zeros(4,3),
                                  forward=lambda q:(foot_b_mm,torch.ones(3,4,dtype=torch.bool)),
                                  q0=torch.zeros(4,3))
        feet_mock=SimpleNamespace(body=body_mock,sensors=SimpleNamespace(joint=torch.zeros(3,12),joint_velocity=torch.zeros(3,12)),
                                  mean_dq=torch.zeros(3,12),mean_foot_pos_m=torch.zeros(3,4,3),foot_home_pos_m=torch.zeros(4,3),
                                  mean_amp_q=torch.tensor([[0.25,0.25,0.25,0.25],[0.40,0.05,0.40,0.05],[0.40,0.05,0.40,0.05]]),
                                  mean_amp_z_m=torch.tensor([[0.015,0.015,0.015,0.015],[0.025,0.002,0.025,0.002],[0.025,0.002,0.025,0.002]]))
        env.action_manager=SimpleNamespace(get_term=lambda name:feet_mock)
        self.assertEqual(mdp.body_collapsed(env).tolist(),[False,True,True])
        curriculum.difficulty=torch.tensor([0.,0.,0.5])
        found[:]=torch.tensor([[1.,0.,0.,1.]])
        grav[:]=torch.tensor([[0.,0.,-1.]])
        stride_sym=mdp.alternating_stride(env)
        # Row 0 (flat, symmetric) beats Row 1 (flat, asymmetric); Row 2 (uneven terrain difficulty=0.5) disables symmetry penalty
        self.assertGreater(float(stride_sym[0]),float(stride_sym[1])+0.3)
        self.assertGreater(float(stride_sym[2]),float(stride_sym[1])+0.1)

    def test_tracking_rewards_progress_and_allows_early_foot_lift(self):
        import torch
        from types import SimpleNamespace
        from gateway.neural_gait import microduck_mdp as mdp
        command=torch.tensor([[.15,.03,.8]]).expand(4,-1)
        actual=torch.stack((torch.zeros(3),command[0],-command[0],command[0]*8))
        curriculum=SimpleNamespace(widths=torch.tensor([.03,.03,.5]),
                                   score_sum=torch.zeros(4),score_count=torch.zeros(4),elapsed=torch.zeros(4))
        robot=SimpleNamespace(root_link_lin_vel_b=torch.cat((actual[:,:2],torch.zeros(4,1)),-1),
            root_link_ang_vel_b=torch.cat((torch.zeros(4,2),actual[:,2:]),-1),
            projected_gravity_b=torch.tensor([[0.,0.,-1.]]).expand(4,-1))
        env=SimpleNamespace(scene={'robot':SimpleNamespace(data=robot)},
            command_manager=SimpleNamespace(get_command=lambda name:command),
            curriculum_manager=SimpleNamespace(get_term_cfg=lambda name:SimpleNamespace(func=curriculum)),
            extras={'log':{}})
        reward=mdp.tracking_twist(env)
        self.assertEqual(float(reward[0]),0.)
        self.assertGreater(float(reward[1]),.9)
        self.assertTrue(bool((reward[2:]<0).all()))
        with patch.object(mdp.mdp,'feet_air_time',return_value=torch.full((4,),4.)):
            air=mdp.tracked_air_time(env)
        self.assertGreater(float(air[0]),.25)
        self.assertTrue(bool((air<=1).all()))
        with patch.object(mdp.mdp,'feet_air_time',return_value=torch.zeros(4)):
            self.assertTrue(bool((mdp.tracked_air_time(env)==0).all()))

    def test_disturbance_curriculum_starts_at_zero_and_only_updates_completed_rows(self):
        import torch
        from types import SimpleNamespace
        from gateway.neural_gait.microduck_mdp import WalkingDifficulty
        terrain=SimpleNamespace(terrain_origins=torch.zeros(5,5,3),terrain_levels=torch.zeros(3,dtype=torch.long),
                                update_env_origins=lambda *args:None)
        env=SimpleNamespace(num_envs=3,device='cpu',episode_length_buf=torch.zeros(3),
                            max_episode_length=2000,scene=SimpleNamespace(terrain=terrain))
        difficulty=WalkingDifficulty(SimpleNamespace(params={'widths':[.03,.03,.5]}),env)
        ids=torch.arange(3)
        difficulty(env,ids)
        self.assertTrue(bool((difficulty.difficulty==0).all()))
        difficulty.score_sum[:]=torch.tensor([90.,0.,90.]);difficulty.score_count[:]=100
        env.episode_length_buf[:]=2000
        difficulty.elapsed[:]=torch.tensor([2000,2000,100])
        difficulty(env,torch.tensor([0,1]))
        torch.testing.assert_close(difficulty.difficulty,torch.tensor([1.,0.,0.]))
        self.assertEqual(float(difficulty.score_sum[2]),90.)
        difficulty(env,torch.tensor([2]))
        self.assertEqual(float(difficulty.difficulty[2]),0.)

    def test_linear_progress_is_independent_of_yaw_tracking_quality(self):
        import torch
        from gateway.neural_gait.microduck_mdp import tracking_scores
        command=torch.tensor([[.15,0.,.8]]).expand(4,-1)
        actual=torch.tensor([[0.,0.,0.],[.03,0.,0.],[0.,0.,-1.],[.03,0.,-1.]])
        quality,baseline=tracking_scores(actual,command,torch.tensor([.1,.1,.5]))
        improvement=(quality-baseline).sum(-1)
        torch.testing.assert_close(improvement[1]-improvement[0],improvement[3]-improvement[2])
        self.assertGreater(float(improvement[1]-improvement[0]),.1)

    def test_bounded_cost_prevents_single_world_spike_without_changing_physics(self):
        import torch
        from types import SimpleNamespace
        from gateway.neural_gait.microduck_mdp import BoundedCost
        values=torch.tensor([.1,2.,1e10,float('nan'),float('inf')])
        original=values.clone()
        cfg=SimpleNamespace(params=dict(function=lambda env:values,parameters={},limit=20.))
        cost=BoundedCost(cfg,SimpleNamespace())
        torch.testing.assert_close(cost(None),torch.tensor([.1,2.,20.,0.,20.]))
        torch.testing.assert_close(values,original,equal_nan=True)

    def test_gpu_nonfinite_world_resets_before_ppo_and_finite_spike_cost_is_bounded(self):
        import torch
        from dataclasses import replace
        from gateway.neural_gait.contract import PROPRIO_SCHEMA
        from gateway.neural_gait.microduck import make_config, ManagerBasedRlEnv
        if not torch.cuda.is_available():
            self.skipTest('CUDA required for MuJoCo-Warp reset regression')
        cfg=make_config(replace(config_fixture(),observation_schema=PROPRIO_SCHEMA),num_envs=4)
        # Exercise the actual physics/reset path; decoder compilation is checked
        # separately against the native owner and in full trainer smoke runs.
        with patch('torch.compile',side_effect=lambda function,**kwargs:function):
            env=ManagerBasedRlEnv(cfg,device='cuda:0')
        try:
            env.reset()
            original=env.sim.step
            calls=0
            def inject():
                nonlocal calls
                original()
                calls+=1
                if calls==cfg.decimation:
                    env.sim.data.qvel[0,0]=float('nan')
            env.sim.step=inject
            obs,reward,terminated,truncated,_=env.step(torch.zeros(4,12,device='cuda:0'))
            self.assertTrue(bool(env.termination_manager.get_term('nan_state')[0]))
            self.assertTrue(bool(terminated[0]))
            self.assertFalse(bool(truncated[0]))
            self.assertTrue(bool(reward.isfinite().all()))
            self.assertTrue(all(bool(value.isfinite().all()) for value in obs.values()))
            self.assertEqual(int(env.episode_length_buf[0]),0)
            self.assertEqual(int(env.episode_length_buf[1]),1)
            env.sim.step=original
            saved=env.sim.data.qvel.clone()
            env.sim.data.qvel[1,3]=1200.
            env.sim.forward()
            cost=env.reward_manager.get_term_cfg('body_ang_vel').func(env)
            self.assertAlmostEqual(float(cost[1]),20.,places=4)
            self.assertEqual(float(env.sim.data.qvel[1,3]),1200.)
            env.sim.data.qvel.copy_(saved)
            env.sim.forward()
            obs,*_=env.step(torch.zeros(4,12,device='cuda:0'))
            self.assertTrue(all(bool(value.isfinite().all()) for value in obs.values()))
        finally:
            env.close()

    def test_motor_envelope_preserves_advertised_speed_and_stall_load(self):
        import torch
        from types import SimpleNamespace
        from gateway.neural_gait.microduck import MG90SActuator
        ranges=torch.zeros((1,3,2))
        actuator=SimpleNamespace(entity=SimpleNamespace(data=SimpleNamespace(
            model=SimpleNamespace(actuator_forcerange=ranges))), _global_ctrl_ids=torch.arange(3),
            cfg=SimpleNamespace(effort_limit=.18,speed_rad_s=10.))
        command=SimpleNamespace(position_target=torch.tensor([[1.,1.,-1.]]),
                                pos=torch.zeros((1,3)),vel=torch.tensor([[0.,20.,20.]]))
        output=MG90SActuator.compute(actuator,command)
        torch.testing.assert_close(output,command.position_target)
        torch.testing.assert_close(ranges[:,:,1],torch.tensor([[.18,0.,0.]]))
        torch.testing.assert_close(ranges[:,:,0],torch.tensor([[-.18,-.18,-.18]]))
        torch.testing.assert_close(command.vel,torch.tensor([[0.,20.,20.]]))

    def test_mjlab_keeps_mg90s_compute_instead_of_fusing_it_as_a_builtin(self):
        from mjlab.actuator.builtin_group import BuiltinActuatorGroup
        from gateway.neural_gait.microduck import MG90SActuator
        actuator=object.__new__(MG90SActuator)
        _,custom=BuiltinActuatorGroup.process([actuator])
        self.assertEqual(custom,(actuator,))


@unittest.skipUnless(importlib.util.find_spec("torch"), "Install optional tensor dependencies")
class TensorHardwareTests(unittest.TestCase):
    def test_partial_reset_reports_acquired_joint_pose_and_preserves_other_sensor_rows(self):
        import torch
        from dataclasses import replace
        from gateway.neural_gait.tensor_sensors import TensorSensors
        config=replace(config_fixture(),feedback_noise_raw_std=0.)
        sensors=TensorSensors(config,3,'cpu')
        home=torch.deg2rad(torch.full((3,12),-20.))
        sensors.reset(slice(None),home)
        self.assertLess(float((sensors.joint-home).abs().max()),.001)
        sensors.feedback(home+.1,.02)
        self.assertTrue(bool((sensors.joint_velocity.abs()>0).all()))
        old=sensors.joint.clone();old_velocity=sensors.joint_velocity.clone()
        sensors.clock=.014
        sensors.reset(torch.tensor([1]),home[1:2]+.2)
        torch.testing.assert_close(sensors.joint[[0,2]],old[[0,2]])
        torch.testing.assert_close(sensors.joint_velocity[[0,2]],old_velocity[[0,2]])
        self.assertLess(float((sensors.joint[1]-home[1]-.2).abs().max()),.001)
        self.assertTrue(bool((sensors.joint_velocity[1]==0).all()))
        self.assertAlmostEqual(float(sensors.feedback_time[1]),.014,places=7)
        self.assertTrue(bool(sensors.feedback_initialized.all()))

    def test_deployment_history_uses_causal_sensor_samples_at_50_hz(self):
        import numpy as np
        from gateway.neural_gait.contract import ObservationHistory, PROPRIO_SCHEMA, vector
        history=ObservationHistory()
        for index in range(17):
            observation=dict(schema=PROPRIO_SCHEMA,observation_time_s=index*.02,
                joint_deg=[float(index)]*12,joint_velocity_deg_s=[2.]*12,
                angular_rate_rad_s=[.1,.2,.3],acceleration_m_s2=[0.,0.,9.81],
                orientation_wxyz=[1.,0.,0.,0.],command=[.2,0.,1.],previous_action=[.4]*12)
            result=history.project(observation)
        rows=np.array(vector(result)).reshape(15,48)
        np.testing.assert_allclose(rows[:,0],np.deg2rad(np.arange(16,1,-1)))
        np.testing.assert_allclose(rows[0,24:36],[.1,.2,.3,0.,0.,1.,0.,0.,-1.,.2,0.,1.])
        self.assertEqual(history.project(dict(observation,observation_time_s=0.))['proprio_history'][1],[0.]*48)

    def test_locomotion_proxy_keeps_cad_inertias_without_false_self_contacts(self):
        from dataclasses import replace
        import xml.etree.ElementTree as ET
        from gateway.neural_gait.environment import build_xml, GaitEnvironment
        config=config_fixture()
        detailed=ET.fromstring(build_xml(config,include_visuals=False))
        config=replace(config,collision_profile="locomotion")
        compact=ET.fromstring(build_xml(config,include_visuals=False))
        for body in compact.iter("body"):
            inertia=body.find("inertial")
            if inertia is not None:
                self.assertEqual(inertia.attrib,detailed.find(f".//body[@name='{body.get('name')}']/inertial").attrib)
        env=GaitEnvironment(config,include_visuals=False)
        try:
            env.reset(seed=1)
            for pair in env.data.contact[:env.data.ncon]:
                self.assertTrue(env.model.geom_bodyid[pair.geom1]==0 or env.model.geom_bodyid[pair.geom2]==0)
            self.assertEqual(len(env.foot_measurements()['clearance_m']),4)
        finally:
            env.close()

    def test_imu_stream_matches_native_registers_and_fusion(self):
        import numpy as np
        import torch
        from dataclasses import replace
        from gateway.neural_gait.native import BodyModel
        from gateway.neural_gait.tensor_sensors import TensorSensors
        config=replace(config_fixture(),imu_prehistory_s=0.,imu_accel_noise_std=0.,imu_gyro_noise_std=0.)
        sensors=TensorSensors(config,1,"cpu")
        native=BodyModel(config.robot)
        try:
            for index in range(700):
                accel=[.2*np.sin(index*.01),.1,9.80665];gyro=[.02,.01,.03]
                sensors.imu(torch.tensor([accel]),torch.tensor([gyro]),.005 if index else 0.)
                measured=native.imu_sample(1000+5000*index,accel,gyro)
                np.testing.assert_allclose(sensors.quaternion[0].numpy(),measured[:4],atol=4e-7)
                np.testing.assert_allclose(sensors.accel[0].numpy(),measured[4:7],atol=2e-6)
                np.testing.assert_allclose(sensors.gyro[0].numpy(),measured[7:10],atol=1e-7)
        finally:
            native.close()

    def test_batched_feet_and_coupled_pwm_match_native_owner(self):
        import numpy as np
        import torch
        from gateway.neural_gait.environment import GEOMETRY
        from gateway.neural_gait.native import BodyModel
        from gateway.neural_gait.tensor_body import TensorBody
        config=config_fixture()
        tensor=TensorBody(json.loads(GEOMETRY.read_text()),config)
        native=BodyModel(config.robot)
        try:
            torch.manual_seed(27)
            previous=tensor.q0.reshape(1,12)
            for magnitude in (.05,.3,1.):
                action=(torch.rand(8,12)*2-1)*magnitude
                decoded=tensor.decode(action)
                for index in range(8):
                    result=native.foot_target(action[index].reshape(4,3).numpy()*config.foot_action_scale_mm,
                        config.reference_joint_deg,torch.rad2deg(previous[0]).numpy(),
                        config.joint_speed_deg_s,1/config.control_hz)
                    np.testing.assert_allclose(torch.rad2deg(decoded[index]).numpy(),
                                               result['nominal_goal_angles'],atol=.002)
                logical,physical=tensor.command(action[:1],previous)
                result=native.foot_target(action[0].reshape(4,3).numpy()*config.foot_action_scale_mm,
                    config.reference_joint_deg,torch.rad2deg(previous[0]).numpy(),
                    config.joint_speed_deg_s,1/config.control_hz)
                output=native.pwm_output(result['ramped_angles'])
                np.testing.assert_allclose(torch.rad2deg(logical[0]).numpy(),result['ramped_angles'],atol=.002)
                np.testing.assert_allclose(torch.rad2deg(physical[0]).numpy(),output['physical_angles'],atol=.002)
                previous=logical
        finally:
            native.close()

    def test_sampled_feedback_filter_matches_native_adc_filter(self):
        import numpy as np
        import torch
        from dataclasses import replace
        from gateway.neural_gait.native import BodyModel
        from gateway.neural_gait.tensor_sensors import TensorSensors
        config=replace(config_fixture(),feedback_noise_raw_std=0.)
        sensors=TensorSensors(config,1,"cpu")
        native=BodyModel(config.robot)
        try:
            for step in range(30):
                position=torch.deg2rad(torch.full((1,12),float(step)))
                sensors.feedback(position,.02)
                angle,velocity,_,_=native.feedback_sample(sensors.raw[0].numpy(),[0.]*12,
                                                        [1000+step*20000]*12)
                np.testing.assert_allclose(torch.rad2deg(sensors.joint[0]).numpy(),angle,atol=.0001)
                np.testing.assert_allclose(torch.rad2deg(sensors.joint_velocity[0]).numpy(),velocity,atol=.002)
        finally:
            native.close()


if __name__ == "__main__":
    unittest.main()

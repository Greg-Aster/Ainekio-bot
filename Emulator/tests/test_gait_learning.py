import copy
import unittest
import numpy as np
from gateway.gait_learning import fit, evaluate, basis, policy_seed, policy_response


def recording(offset=0.):
    records=[{'schema':'gait_trace_v1','geometry':'test-geometry','boot_id':12,'session':1}]
    for i,p in enumerate(np.linspace(2,4,201,endpoint=False)):
        legs=[]
        for l in range(4):
            desired=np.array([20., 30.+l, -50.])
            error=np.array([1.+2*np.sin(p*2*np.pi), .5*np.cos(p*2*np.pi), -2+np.cos(4*np.pi*p)])
            applied=np.array([offset,0,0])
            legs.append({'sampled_us':1000+i*20000,'phase':p,'target_mm':desired.tolist(),
                         'measured_mm':(desired-error).tolist(),'correction_mm':applied.tolist()})
        records.append({'kind':'tracking','sequence':i+1,'signature':123,'command_sequence':9,
                        'nominal_pulses_us':[1500+i%20]*12,'stride':100,'eligible':True,'valid_mask':15,'legs':legs})
    records.append({'next':201,'lost':0})
    return [{'records':records}]


def policy_recording():
    batches = recording()
    for event in batches[0]['records'][1:-1]:
        event['policy'] = {'schema': 'gait_policy_input_v1', 'signature': 456, 'phase': event['legs'][0]['phase'],
                           'usable': True, 'features': [1., -.5, .2, -.3, -.2, .2, -.3, .4]*4,
                           'imu_timestamp_us': 1, 'correction_mm': [0.]*12, 'eligible': True,
                           'gait_signature': 789, 'command_schema': 'gait_policy_command_v1', 'command': [1., 0., 0., 1.]}
    return batches


class LearningTests(unittest.TestCase):
    def test_known_periodic_error_becomes_task_space_residual(self):
        result=fit(recording(), .5)
        self.assertEqual(result['model']['pulse_min_us'], [1500]*12)
        self.assertEqual(result['model']['pulse_max_us'], [1519]*12)
        c=np.array(result['model']['coefficients']).reshape(4,3,5)
        np.testing.assert_allclose(c[:,0,:],np.tile([.5,1,0,0,0],(4,1)),atol=1e-10)
        np.testing.assert_allclose(c[:,2,:],np.tile([-1,0,0,0,.5],(4,1)),atol=1e-10)
        self.assertFalse(result['training']['physical_improvement_demonstrated'])
        # A separate synthetic plant with unit task-space response improves.
        p=np.linspace(2,3,80,endpoint=False)+.003
        actual_error=np.column_stack((1+2*np.sin(2*np.pi*p),.5*np.cos(2*np.pi*p),-2+np.cos(4*np.pi*p)))
        corrected=actual_error-basis(p)@c[0].T
        np.testing.assert_allclose(corrected,.5*actual_error,atol=1e-10)

    def test_iteration_retains_applied_correction_not_just_last_error(self):
        a=np.array(fit(recording(3.))['model']['coefficients']).reshape(4,3,5)
        np.testing.assert_allclose(a[:,0,0],3.5)

    def test_context_loss_nonfinite_and_missing_leg_reported(self):
        for change in ('loss','context','nan','missing','pulses'):
            data=recording()
            if change=='loss':data[0]['records'][-1]['lost']=1
            if change=='context':data[0]['records'][4]['signature']=55
            if change=='nan':data[0]['records'][5]['legs'][0]['target_mm'][0]=float('nan')
            if change=='pulses': del data[0]['records'][3]['nominal_pulses_us']
            if change=='missing':
                for r in data[0]['records'][1:-1]:r['valid_mask']=7
            with self.assertRaises(ValueError):fit(data)

    def test_duplicates_do_not_double_weight_measurements(self):
        data=recording()
        self.assertEqual(fit(data)['model'],fit(data+copy.deepcopy(data))['model'])
        report=evaluate(data)
        self.assertEqual(report['legs'][0]['samples'],201)

    def test_sensor_policy_seed_is_baseline_not_an_unmeasured_improvement(self):
        batches = policy_recording()
        seed = policy_seed(batches)
        self.assertEqual(seed, policy_seed(batches+copy.deepcopy(batches)))
        self.assertEqual(seed['model']['signature'], 456)
        self.assertEqual(seed['model']['schema'], 'gait_learning_v3')
        self.assertEqual(seed['model']['feedback_coefficients'], [0.]*96)
        self.assertFalse(seed['training']['physical_improvement_demonstrated'])
        for invalid in (recording(), policy_recording()):
            if 'policy' in invalid[0]['records'][1]:
                invalid[0]['records'][2]['policy']['signature'] = 567
            with self.assertRaises(ValueError):
                policy_seed(invalid)

    def test_sensor_response_matches_native_contract_at_same_phase(self):
        model = policy_seed(policy_recording())['model']
        features = np.array([1., -.5, .2, -.3, -.2, .2, -.3, .4]*4).reshape(1, 4, 8)
        model['feedback_coefficients'][0] = .2
        model['feedback_coefficients'][2*8+3] = .2
        response = policy_response(model, [2.75], features)
        np.testing.assert_allclose(response[0, 0], [.2, 0, -.06])
        features[0, 0, 0] = -1
        response = policy_response(model, [2.75], features)
        np.testing.assert_allclose(response[0, 0], [-.2, 0, -.06])

    def test_gait_seed_retains_multi_command_coverage(self):
        batches = policy_recording()
        event = batches[0]['records'][5]
        event['eligible'] = False;event['stride'] = 50
        event['policy']['command'] = [-1., .3, 0., .5]
        seed = policy_seed(batches, gait=True)['model']
        self.assertEqual(seed['schema'], 'gait_learning_v4')
        self.assertEqual(seed['signature'], 789)
        self.assertEqual(seed['gait_profile'], [0.]*33)
        self.assertEqual(len(seed['gait_profile_fields']), 33)
        self.assertEqual(seed['observed_command_range'], [[-1., 0., 0., .5], [1., .3, 0., 1.]])
        seed['command_coefficients'][1] = .5
        response = policy_response(seed, [3.], np.zeros((1, 4, 8)), [[.7, -.4, 0., .5]])
        np.testing.assert_allclose(response[0, 0], [-.2, 0., 0.])


if __name__=='__main__':unittest.main()

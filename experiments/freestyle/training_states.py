"""Constructed Body Control-shaped states for offline training, not sensor logs."""
from recovery import quaternion
from runtime import JOINTS

def observation(rng):
    """Same field names/nesting as Bridge.observation, with varied numeric data."""
    timestamp = rng.randrange(1000000, 800000000)
    old = rng.choice(['wave', 'sit', 'walk', 'motion_plan', 'neutral'])
    joints = {}
    for index, joint in enumerate(JOINTS):
        home = [0, -30.87, -117.68][index % 3] + rng.choice([0, -1.25, 2.5])
        measured = round(home + rng.uniform(-18, 18), 5)
        commanded = round(measured + rng.uniform(-.8, .8), 5)
        joints[joint] = {'home_deg':home, 'commanded_model_deg':commanded,
                         'model_deg':measured, 'calibrated':True, 'in_calibrated_range':True,
                         'command_us':rng.randrange(400, 2800), 'velocity_deg_s':round(rng.uniform(-.2,.2),5)}
    imu = {'boot_id':rng.randrange(100000,999999), 'timestamp_us':timestamp, 'age_us':rng.randrange(100,4000),
           'accepted_samples':rng.randrange(1000,100000), 'rejected_samples':0,'gap_restarts':0,
           'available':True,'fresh':True,'startup':False,'calibration_applied':True,
           'gyro_recovery':False,'acceleration_recovery':False,'accelerometer_ignored':False,
           'frame':'body_nominal','orientation_wxyz':quaternion(rng.uniform(-6,6),rng.uniform(-6,6)),
           'acceleration_m_s2':[.1,.2,9.8],'angular_rate_rad_s':[.001,-.002,.001],
           'acquisition':{'io_errors':0,'no_data_polls':10000},
           'motion':{'command':old,'activity':'freestyle' if old=='motion_plan' else old,
                     'phase':'hold','sequence':rng.randrange(1,100),'connection':2,
                     'started_us':timestamp-20000,'sampled_us':timestamp,'expected_up':None},
           'face_token':'','received_at':'2026-10-21T00:00:00+00:00'}
    return {'epoch':2,'joints':joints,'imu':imu,'expected_up':None,
            'feedback':{'device_us':timestamp,'scan_us':1500,'enabled':True,'stalled_joints':0,'no_progress_ms':0},
            'joint_speed_limit_deg_s':rng.choice([90,180,360,720,1500,2000]),
            'action':{'t':'intent','name':old,'args':{'speed':200,'steps':0},'seq':9,'epoch':2},
            'model':'v2-12servo'}

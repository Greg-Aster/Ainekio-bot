import asyncio
import copy
import json
import threading
import unittest
from unittest.mock import patch

from experiments.freestyle.bridge import Bridge
from experiments.freestyle.program import JOINTS, calibrated_positions, compile_motion, targets_for, packets, gait_intents
from compact import call, move
from refine import records, POSTURES, GAITS
from protocol.control_v1 import validate_control_message


class ProgramTests(unittest.TestCase):
    def test_calibrated_home_and_signed_inversion(self):
        home,current=calibrated_positions({'joints':[{'id':0,'home_cd':2300,'home_us':1500,
                        'pulse_us':1600,'us_per_degree':10,'invert':True}]})
        self.assertEqual(home[JOINTS[0]],23)
        self.assertEqual(current[JOINTS[0]],13)

    def test_compilation_preserves_large_oscillation_and_nonmoving_joints(self):
        start=dict.fromkeys(JOINTS,7);home=dict.fromkeys(JOINTS,12)
        chunks=list(packets(targets_for(call('oscillate',joint=JOINTS[0],amplitude_deg=20,cycles=12,speed_pct=50),start,home,90)))
        self.assertEqual([len(p) for p in chunks],[32,16])
        all_frames=sum(chunks,[])
        self.assertTrue(all(f[0]==4500 for f in all_frames))
        self.assertEqual([f[1][0] for f in all_frames[:4]],[2700,700,-1300,700])
        self.assertEqual(all_frames[-1][1], [700]*12)
        for chunk in chunks:
            validate_control_message({'t':'motion_plan','seq':1,'map':2,'control':'targets','frames':chunk,'end':'hold'})

    def test_percentage_speed_and_home_are_not_zero(self):
        start=dict.fromkeys(JOINTS,10);home=dict.fromkeys(JOINTS,15)
        frame=list(targets_for(move(JOINTS[0],20,'home',50),start,home,100))[0]
        self.assertEqual(frame[0],5000)
        self.assertEqual(frame[1],[3500]+[1000]*11)

    def test_released_output_is_not_a_negative_angle(self):
        home,current=calibrated_positions({'joints':[{'id':0,'home_cd':2300,'home_us':1500,
                        'pulse_us':0,'us_per_degree':10,'invert':False}]})
        self.assertEqual(home[JOINTS[0]],23)
        self.assertIsNone(current[JOINTS[0]])

    def test_all_gaits_preserve_more_than_ten_cycles(self):
        for name in GAITS:
            intents=list(gait_intents({'command':name,'speed_pct':50,'cycles':12}))
            self.assertEqual([v['steps'] for v in intents],[10,2])
            for intent in intents:
                validate_control_message({'t':'intent','seq':1,'name':'walk',**intent})

    def test_recovery_and_novel_sequences_are_in_disjoint_splits(self):
        splits=[records(s) for s in ('train','evaluation','test')]
        queries=[{r['query'] for r in rows} for rows in splits]
        for a,b in ((0,1),(0,2),(1,2)):
            self.assertFalse(queries[a]&queries[b])
        for rows in splits:
            families={r['family'] for r in rows}
            self.assertTrue({'jam_smaller_wave','jam_backoff','fall_correction','slip_correction','novel_sequence'}<=families)
        for row in splits[0]:
            if row['family']=='jam_backoff':
                obs=json.loads(row['query'])['observation']['joints']
                action=row['answers'][0]['arguments'];j=obs[action['joint']]
                self.assertLess((action['angle_deg']-j['model_deg'])*(j['commanded_model_deg']-j['model_deg']),0)


class FakeGateway:
    def __init__(self):
        self.events=[];self.commands=[];self.sent=[];self.seq=0
        self.connected=True;self.epoch=1
        self.calibration={'joints':[{'id':i,'home_cd':1000,'home_us':1500,'pulse_us':1500,
                          'invert':False,'us_per_degree':10} for i in range(12)]}
    def subscribe_events(self,c):self.events.append(c)
    def subscribe_commands(self,c):self.commands.append(c)
    def unsubscribe_events(self,c):self.events.remove(c)
    def unsubscribe_commands(self,c):self.commands.remove(c)
    async def status_snapshot(self):
        if not self.connected:return {'robots':{}}
        return {'robots':{'robot':{'model':'v2-12servo','epoch':self.epoch,'calibration':self.calibration,
            'motion_speed':{'joint_speed_limit_deg_s':100},'status':{'imu':{'orientation_wxyz':[1,0,0,0]}},'body_command':None}}}
    async def queue_motion_plan(self,frames,**kwargs):
        self.seq+=1
        if kwargs.get('on_sequence'):kwargs['on_sequence'](self.seq)
        self.sent.append(copy.deepcopy(frames))
        for c in self.commands:await c({'t':'motion_plan','robot_id':'robot','seq':self.seq})
        return self.seq
    async def wait_terminal(self,seq,**kwargs):
        self.assert_timeout=kwargs['timeout']
        return {'t':'done','seq':seq}


class FakeTransport:
    async def request(self,*args):
        return {'joints':[{'id':i,'model_deg':10,'command_us':1500,'calibrated':True} for i in range(12)]}
    async def close(self):pass


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.gateway=FakeGateway()
        self.generated=[]
        async def compiler(*args):
            from experiments.freestyle import bridge
            return await asyncio.to_thread(bridge.compile_motion,*args)
        self.bridge=Bridge(self.gateway,FakeTransport(),self.generate,compiler=compiler)
        await self.bridge.configure('robot','http://unused',False)
    def generate(self,endpoint,request):
        self.generated.append(request)
        return {'program':[call('oscillate',joint=JOINTS[0],amplitude_deg=20,cycles=12,speed_pct=50)]}
    async def asyncTearDown(self):await self.bridge.close()
    async def test_preview_generates_without_motion(self):
        job=await self.bridge.submit('robot','new greeting',False)
        await self.bridge.tasks[job['job_id']]
        self.assertFalse(self.gateway.sent)
        self.assertEqual(self.bridge.jobs[job['job_id']]['state'],'generated')
        self.assertIn('model_deg',self.generated[0]['observation']['joints'][JOINTS[0]])
    async def test_saved_trial_preserves_evidence_without_claiming_tracking_success(self):
        job=await self.bridge.submit('robot','new greeting',False)
        await self.bridge.tasks[job['job_id']]
        exported=self.bridge.trial('robot',job['job_id'])
        self.assertFalse(exported['job']['execute'])
        self.assertEqual(exported['job']['initial_observation']['epoch'],1)
        self.assertIsNone(exported['evidence']['physical_success'])
        self.assertFalse(exported['evidence']['continuous_servo_trace'])
        exported['job']['request']='changed copy'
        self.assertEqual(self.bridge.jobs[job['job_id']]['request'],'new greeting')
        self.assertFalse(self.gateway.sent)
    async def test_execution_preserves_all_packets(self):
        job=await self.bridge.submit('robot','twelve wiggles',True)
        await self.bridge.tasks[job['job_id']]
        self.assertEqual([len(p) for p in self.gateway.sent],[32,16])
        self.assertEqual(self.bridge.jobs[job['job_id']]['state'],'completed')
        self.assertIsNone(self.gateway.assert_timeout)

    async def test_spawned_compiler_executes_the_same_generated_targets(self):
        self.bridge.compiler=self.bridge._compile_motion
        self.bridge.generate=lambda *args:{'program':[
            move(JOINTS[0],20,'current',50),move(JOINTS[0],-20,'current',50)]}
        submitted=await self.bridge.submit('robot','out and back',True)
        await self.bridge.tasks[submitted['job_id']]
        self.assertEqual(self.bridge.jobs[submitted['job_id']]['state'],'completed')
        self.assertEqual(self.gateway.sent[0][-1][1],[3000]+[1000]*11)
        self.assertEqual(self.gateway.sent[1][-1][1],[1000]*12)

    async def test_relative_sequence_returns_to_anchor_despite_feedback_error(self):
        self.bridge.generate=lambda *args:{'program':[
            move(JOINTS[0],20,'current',50),move(JOINTS[0],-20,'current',50)]}
        async def feedback(*args):
            angle=-30 if self.gateway.sent else 10
            return {'joints':[{'id':i,'model_deg':angle,'command_us':1500,'calibrated':True} for i in range(12)]}
        self.bridge.transport.request=feedback
        submitted=await self.bridge.submit('robot','out and back',True)
        await self.bridge.tasks[submitted['job_id']]
        self.assertEqual(self.gateway.sent[0][-1][1],[3000]+[1000]*11)
        self.assertEqual(self.gateway.sent[1][-1][1],[1000]*12)
        # Actual feedback is still retained; planned endpoints do not masquerade as measurements.
        self.assertEqual(self.bridge.jobs[submitted['job_id']]['history'][-1]['joints'][JOINTS[0]],-30)

    async def test_next_motion_compiles_while_current_receipt_is_pending(self):
        prepared=threading.Event()
        def compile_ahead(action,*args):
            result=compile_motion(action,*args)
            if action['arguments']['angle_deg']==-20:prepared.set()
            return result
        original=self.gateway.wait_terminal
        async def receipt(seq,**kwargs):
            if seq==1:
                self.assertTrue(await asyncio.to_thread(prepared.wait,2),
                                'The next computation must overlap the current movement')
            return await original(seq,**kwargs)
        self.gateway.wait_terminal=receipt
        self.bridge.generate=lambda *args:{'program':[
            move(JOINTS[0],20,'current',50),move(JOINTS[0],-20,'current',50)]}
        with patch('experiments.freestyle.bridge.compile_motion',compile_ahead):
            submitted=await self.bridge.submit('robot','out and back',True)
            await self.bridge.tasks[submitted['job_id']]
        self.assertEqual(self.bridge.jobs[submitted['job_id']]['state'],'completed')

    async def test_reassessment_reanchors_to_measured_pose(self):
        def generate(endpoint,request):
            if request['event']:
                return {'program':[move(JOINTS[0],5,'current',50)]}
            return {'program':[move(JOINTS[0],20,'current',50),call('reassess')]}
        async def feedback(*args):
            angle=18 if self.gateway.sent else 10
            return {'joints':[{'id':i,'model_deg':angle,'command_us':1500,'calibrated':True} for i in range(12)]}
        self.bridge.generate=generate;self.bridge.transport.request=feedback
        submitted=await self.bridge.submit('robot','move then reassess',True)
        await self.bridge.tasks[submitted['job_id']]
        self.assertEqual(self.gateway.sent[1][-1][1][0],2300)

    async def test_stop_discards_speculative_motion_without_delaying_command(self):
        prepared=threading.Event();release=threading.Event();sent=asyncio.Event()
        def compile_ahead(action,*args):
            if action['arguments']['angle_deg']==-20:
                prepared.set();release.wait()
            return compile_motion(action,*args)
        async def receipt(*args,**kwargs):
            sent.set();await asyncio.Future()
        self.gateway.wait_terminal=receipt
        self.bridge.generate=lambda *args:{'program':[
            move(JOINTS[0],20,'current',50),move(JOINTS[0],-20,'current',50)]}
        with patch('experiments.freestyle.bridge.compile_motion',compile_ahead):
            try:
                submitted=await self.bridge.submit('robot','out and back',True)
                task=self.bridge.tasks[submitted['job_id']]
                await sent.wait()
                self.assertTrue(await asyncio.to_thread(prepared.wait,2))
                await self.bridge.command({'robot_id':'robot','t':'stop'})
                await task
                self.assertEqual(self.bridge.jobs[submitted['job_id']]['state'],'superseded')
                self.assertEqual(len(self.gateway.sent),1)
            finally:release.set()

    async def test_released_servos_arm_at_measured_pose_before_correction(self):
        original=self.bridge.transport.request
        async def released(*args):
            value=await original(*args)
            for j in value['joints']:j['command_us']=0
            return value
        self.bridge.transport.request=released
        job=await self.bridge.submit('robot','twelve wiggles',True)
        await self.bridge.tasks[job['job_id']]
        # The P4 seeds its speed ramp from shaft feedback; no synthetic 1ms frame.
        self.assertEqual(self.gateway.sent[0][0],[5000,[3000]+[1000]*11])
        self.assertEqual(sum(map(len,self.gateway.sent)),48)
    async def test_events_are_opt_in_and_admit_without_waiting_for_inference(self):
        event={'robot_id':'robot','name':'body_event','data':{'kind':'servo_stall','joints':[{'id':0}]}}
        await self.bridge.event(event)
        self.assertFalse(self.bridge.jobs)
        await self.bridge.configure('robot','http://unused',True)
        await self.bridge.event(event)
        tasks=list(self.bridge.tasks.values())
        self.assertEqual(len(tasks),1)
        await asyncio.gather(*tasks)
        self.assertEqual(self.generated[0]['event']['type'],'servo_stall')
        self.assertEqual(self.generated[0]['event']['joints'],event['data']['joints'])
    async def test_manual_command_supersedes_pending_generation(self):
        entered=threading.Event(); release=threading.Event()
        def slow(*args):
            entered.set();release.wait();return self.generate(*args)
        self.bridge.generate=slow
        job=await self.bridge.submit('robot','wave',True)
        task=self.bridge.tasks[job['job_id']]
        await asyncio.to_thread(entered.wait)
        await self.bridge.command({'robot_id':'robot','t':'stop'})
        release.set();await task
        self.assertEqual(self.bridge.jobs[job['job_id']]['state'],'superseded')
        self.assertFalse(self.gateway.sent)

    async def connection(self, connected, epoch):
        self.gateway.connected=connected;self.gateway.epoch=epoch
        await self.bridge.event({'t':'connection','robot_id':'robot','epoch':epoch,
                                 'status':'connected' if connected else 'disconnected'})

    async def test_generation_survives_disconnect_and_reconnect_uses_fresh_pose(self):
        entered=asyncio.Event();release=asyncio.Event()
        async def generate(endpoint, request):
            self.generated.append(request);entered.set();await release.wait()
            return {'program':[move(JOINTS[0],20,'current',50)]}
        self.bridge.generate=generate
        submitted=await self.bridge.submit('robot','lift',True)
        identifier=submitted['job_id'];task=self.bridge.tasks[identifier]
        await entered.wait()
        await self.connection(False,1)
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        self.assertEqual(self.bridge.jobs[identifier]['state'],'generating')
        self.assertEqual(self.bridge.active['robot'],identifier)
        release.set()
        # The model completes even while the robot is offline. Only delivery waits.
        for _ in range(10):
            if self.bridge.jobs[identifier]['state']=='awaiting_connection':break
            await asyncio.sleep(0)
        self.assertEqual(self.bridge.jobs[identifier]['state'],'awaiting_connection')
        self.assertEqual(len(self.bridge.jobs[identifier]['programs']),1)
        self.assertFalse(self.gateway.sent)
        async def fresh(*args):
            return {'joints':[{'id':i,'model_deg':18,'command_us':1500,'calibrated':True} for i in range(12)]}
        self.bridge.transport.request=fresh
        await self.connection(True,2)
        await task
        self.assertEqual(len(self.generated),1)
        self.assertEqual(self.gateway.sent[0][-1][1][0],3800)
        self.assertEqual(self.bridge.jobs[identifier]['epoch'],2)
        self.assertEqual(self.bridge.jobs[identifier]['state'],'completed')

    async def test_preview_finishes_offline_and_stop_still_cancels_execution(self):
        entered=asyncio.Event();release=asyncio.Event()
        async def generate(*args):
            entered.set();await release.wait()
            return {'program':[move(JOINTS[0],20,'current',50)]}
        self.bridge.generate=generate
        preview=await self.bridge.submit('robot','preview',False)
        preview_task=self.bridge.tasks[preview['job_id']]
        await entered.wait();entered.clear()
        executing=await self.bridge.submit('robot','execute',True)
        task=self.bridge.tasks[executing['job_id']]
        await entered.wait();await self.connection(False,1)
        release.set();await preview_task
        self.assertEqual(self.bridge.jobs[preview['job_id']]['state'],'generated')
        self.assertFalse(task.done())
        await self.bridge.command({'robot_id':'robot','t':'stop'})
        await task
        await self.connection(True,2)
        self.assertEqual(self.bridge.jobs[executing['job_id']]['state'],'superseded')
        self.assertFalse(self.gateway.sent)

    async def test_reconnect_before_generation_finishes_does_not_restart_or_cancel_it(self):
        entered=asyncio.Event();release=asyncio.Event()
        async def generate(endpoint,request):
            self.generated.append(request);entered.set();await release.wait()
            return {'program':[move(JOINTS[0],20,'current',50)]}
        self.bridge.generate=generate
        submitted=await self.bridge.submit('robot','lift',True)
        task=self.bridge.tasks[submitted['job_id']]
        await entered.wait()
        await self.connection(False,1);await self.connection(True,2)
        # A delayed old-session disconnect cannot cancel the new delivery.
        await self.bridge.event({'t':'connection','robot_id':'robot','epoch':1,'status':'disconnected'})
        release.set();await task
        self.assertEqual(len(self.generated),1)
        self.assertEqual(self.bridge.jobs[submitted['job_id']]['state'],'completed')
        self.assertEqual(self.bridge.jobs[submitted['job_id']]['epoch'],2)

    async def test_replacement_supersedes_offline_delivery_without_replaying_it(self):
        entered=asyncio.Event();release=asyncio.Event()
        async def generate(*args):
            entered.set();await release.wait()
            return {'program':[move(JOINTS[0],20,'current',50)]}
        self.bridge.generate=generate
        first=await self.bridge.submit('robot','old',True)
        first_task=self.bridge.tasks[first['job_id']]
        await entered.wait();await self.connection(False,1);release.set()
        for _ in range(10):
            if self.bridge.jobs[first['job_id']]['state']=='awaiting_connection':break
            await asyncio.sleep(0)
        self.gateway.connected=True;self.gateway.epoch=2
        second=await self.bridge.submit('robot','replacement',True)
        second_task=self.bridge.tasks[second['job_id']]
        await self.connection(True,2)
        await asyncio.gather(first_task,second_task)
        self.assertEqual(self.bridge.jobs[first['job_id']]['state'],'superseded')
        self.assertEqual(self.bridge.jobs[second['job_id']]['state'],'completed')
        self.assertEqual(len(self.gateway.sent),1)

    async def test_disconnect_during_feedback_read_retries_on_new_connection(self):
        entered=asyncio.Event();release=asyncio.Event()
        original=self.bridge.transport.request
        reads=0
        async def interrupted(*args):
            nonlocal reads
            reads+=1
            if reads==1:
                entered.set();await release.wait()
                raise ConnectionError('measurement connection ended')
            return await original(*args)
        self.bridge.transport.request=interrupted
        submitted=await self.bridge.submit('robot','preview',False)
        task=self.bridge.tasks[submitted['job_id']]
        await entered.wait();await self.connection(False,1);release.set()
        for _ in range(10):
            if self.bridge.jobs[submitted['job_id']]['state']=='awaiting_connection':break
            await asyncio.sleep(0)
        self.assertFalse(task.done())
        await self.connection(True,2);await task
        self.assertEqual(len(self.generated),1)
        self.assertEqual(self.generated[0]['observation']['epoch'],2)
        self.assertEqual(self.bridge.jobs[submitted['job_id']]['state'],'generated')

    async def test_explicit_cancel_retires_finished_generation_awaiting_delivery(self):
        entered=asyncio.Event();release=asyncio.Event()
        async def generate(*args):
            entered.set();await release.wait()
            return {'program':[move(JOINTS[0],20,'current',50)]}
        self.bridge.generate=generate
        submitted=await self.bridge.submit('robot','lift',True)
        identifier=submitted['job_id']
        await entered.wait();await self.connection(False,1);release.set()
        for _ in range(10):
            if self.bridge.jobs[identifier]['state']=='awaiting_connection':break
            await asyncio.sleep(0)
        self.assertEqual(len(self.bridge.jobs[identifier]['programs']),1)
        result=await self.bridge.cancel(identifier)
        await self.connection(True,2)
        self.assertEqual(result['state'],'superseded')
        self.assertFalse(self.gateway.sent)

    async def test_recovery_plans_concurrently_then_replaces_with_fresh_positions(self):
        first_packet=asyncio.Event(); allow_first=asyncio.Event(); second_packet=asyncio.Event()
        model_entered=asyncio.Event(); model_release=asyncio.Event()
        faces=[]
        async def face(name,args,**kwargs):
            self.assertEqual(name,'face')
            if 'expr' in args:faces.append(args['expr'])
            return 0
        self.gateway.queue_intent=face
        original_receipt=self.gateway.wait_terminal
        async def receipt(sequence,**kwargs):
            if sequence==1:
                first_packet.set();await allow_first.wait()
            elif sequence==2:
                second_packet.set();await asyncio.Future()
            return await original_receipt(sequence,**kwargs)
        self.gateway.wait_terminal=receipt
        async def generate(endpoint,request):
            if request['event']:
                model_entered.set();await model_release.wait()
                return {'program':[call('face',expr='angry'),move(JOINTS[0],-4,'current',50),
                    call('face',expr='wave'),
                    call('oscillate',joint=JOINTS[0],amplitude_deg=2,cycles=3,speed_pct=50)]}
            return {'program':[call('oscillate',joint=JOINTS[0],amplitude_deg=20,cycles=20,speed_pct=50)]}
        self.bridge.generate=generate
        await self.bridge.configure('robot','http://unused',True)
        submitted=await self.bridge.submit('robot','wave',True)
        original=self.bridge.tasks[submitted['job_id']]
        await first_packet.wait()
        await self.bridge.event({'robot_id':'robot','epoch':1,'name':'body_event',
            'data':{'kind':'servo_stall','outputs_released':False,'joints':[{'id':0}]}})
        await model_entered.wait()
        recovery=next(task for key,task in self.bridge.tasks.items() if key!=submitted['job_id'])
        self.assertEqual(self.bridge.active['robot'],submitted['job_id'])
        allow_first.set();await second_packet.wait()
        self.assertFalse(original.done(),'Existing packets continue while recovery inference runs')
        async def fresh(*args):
            return {'joints':[{'id':i,'model_deg':18,'command_us':1500,'calibrated':True} for i in range(12)]}
        self.bridge.transport.request=fresh
        model_release.set();await asyncio.gather(original,recovery)
        self.assertEqual(self.bridge.jobs[submitted['job_id']]['state'],'superseded')
        self.assertEqual(self.gateway.sent[-1][-1][1][0],1400)
        self.assertEqual(len(self.gateway.sent[-1]),12)
        self.assertTrue(all(frame[1][0]<1800 for frame in self.gateway.sent[-1]))
        self.assertEqual(faces,['angry','wave'])

    async def test_manual_stop_cancels_pending_recovery_without_an_active_job(self):
        entered=asyncio.Event()
        async def generate(*args):
            entered.set();await asyncio.Future()
        self.bridge.generate=generate
        await self.bridge.configure('robot','http://unused',True)
        await self.bridge.event({'robot_id':'robot','epoch':1,'name':'body_event',
            'data':{'kind':'servo_stall','outputs_released':False}})
        await entered.wait();identifier=next(iter(self.bridge.tasks));task=self.bridge.tasks[identifier]
        await self.bridge.command({'robot_id':'robot','t':'stop'})
        await task
        self.assertEqual(self.bridge.jobs[identifier]['state'],'superseded')
        self.assertFalse(self.gateway.sent)

    async def test_recovery_generation_error_preserves_existing_motion(self):
        entered=asyncio.Event()
        async def receipt(*args,**kwargs):
            entered.set();await asyncio.Future()
        self.gateway.wait_terminal=receipt
        async def generate(endpoint,request):
            if request['event']:raise ValueError('model unavailable')
            return {'program':[move(JOINTS[0],20,'current',50)]}
        self.bridge.generate=generate
        await self.bridge.configure('robot','http://unused',True)
        submitted=await self.bridge.submit('robot','wave',True)
        current=self.bridge.tasks[submitted['job_id']];await entered.wait()
        await self.bridge.event({'robot_id':'robot','epoch':1,'name':'body_event',
            'data':{'kind':'servo_stall','outputs_released':False}})
        identifier=next(key for key in self.bridge.tasks if key!=submitted['job_id'])
        await self.bridge.tasks[identifier]
        self.assertEqual(self.bridge.jobs[identifier]['state'],'error')
        self.assertFalse(current.done())
        self.assertEqual(self.bridge.active['robot'],submitted['job_id'])

    async def test_empty_recovery_does_not_cancel_existing_motion(self):
        entered=asyncio.Event()
        async def receipt(*args,**kwargs):
            entered.set();await asyncio.Future()
        self.gateway.wait_terminal=receipt
        async def generate(endpoint,request):
            return {'program':[] if request['event'] else [move(JOINTS[0],20,'current',50)]}
        self.bridge.generate=generate
        await self.bridge.configure('robot','http://unused',True)
        submitted=await self.bridge.submit('robot','wave',True)
        current=self.bridge.tasks[submitted['job_id']];await entered.wait()
        await self.bridge.event({'robot_id':'robot','epoch':1,'name':'body_event',
            'data':{'kind':'servo_stall','outputs_released':False}})
        identifier=next(key for key in self.bridge.tasks if key!=submitted['job_id'])
        await self.bridge.tasks[identifier]
        self.assertEqual(self.bridge.jobs[identifier]['state'],'completed')
        self.assertFalse(current.done())
        self.assertEqual(self.bridge.active['robot'],submitted['job_id'])

    async def test_recovery_admission_failure_keeps_original_program_running(self):
        entered=asyncio.Event()
        async def receipt(*args,**kwargs):
            entered.set();await asyncio.Future()
        self.gateway.wait_terminal=receipt
        async def generate(endpoint,request):
            return {'program':[move(JOINTS[0],20,'current',50)]}
        self.bridge.generate=generate
        await self.bridge.configure('robot','http://unused',True)
        submitted=await self.bridge.submit('robot','wave',True)
        current=self.bridge.tasks[submitted['job_id']];await entered.wait()
        async def unavailable(*args,**kwargs):
            raise ValueError('Robot disconnected before admission')
        self.gateway.queue_motion_plan=unavailable
        await self.bridge.event({'robot_id':'robot','epoch':1,'name':'body_event',
            'data':{'kind':'servo_stall','outputs_released':False}})
        identifier=next(key for key in self.bridge.tasks if key!=submitted['job_id'])
        await self.bridge.tasks[identifier]
        self.assertEqual(self.bridge.jobs[identifier]['state'],'error')
        self.assertFalse(current.done())
        self.assertEqual(self.bridge.active['robot'],submitted['job_id'])
    async def test_empty_reassessment_does_not_automatically_replay_old_actions(self):
        count=0
        def generate(*args):
            nonlocal count
            count+=1
            if count==1:return {'program':[call('reassess'),move(JOINTS[0],20,'home',50)]}
            return {'program':[]}
        self.bridge.generate=generate
        job=await self.bridge.submit('robot','reassess then move',True)
        await self.bridge.tasks[job['job_id']]
        self.assertEqual(count,2)
        self.assertEqual(len(self.gateway.sent),0)

    async def test_short_corrections_retain_pending_goal_across_reassessments(self):
        requests=[]
        def generate(endpoint,request):
            requests.append(copy.deepcopy(request))
            if len(requests)==1:
                return {'program':[call('reassess'),move(JOINTS[0],40,'home',50)]}
            if len(requests)==2:
                return {'program':[move(JOINTS[0],-4,'current',25),call('reassess')]}
            return {'program':[move(JOINTS[0],10,'home',50)]}
        self.bridge.generate=generate
        job=await self.bridge.submit('robot','adapt the movement',True)
        await self.bridge.tasks[job['job_id']]
        for request in requests[1:]:
            self.assertEqual(request['observation']['pending_actions'],[move(JOINTS[0],40,'home',50)])
        self.assertEqual(len(self.gateway.sent),2)

    async def test_reassessment_replaces_old_path_instead_of_repeating_it(self):
        requests=[]
        def generate(endpoint,request):
            requests.append(copy.deepcopy(request))
            if len(requests)==1:
                return {'program':[call('reassess'),move(JOINTS[0],40,'home',50)]}
            return {'program':[move(JOINTS[0],-4,'current',25)]}
        self.bridge.generate=generate
        job=await self.bridge.submit('robot','adapt the movement',True)
        await self.bridge.tasks[job['job_id']]
        self.assertEqual(requests[1]['observation']['pending_actions'],[move(JOINTS[0],40,'home',50)])
        self.assertEqual(len(self.gateway.sent),1)
        self.assertEqual(self.bridge.jobs[job['job_id']]['state'],'completed')

    async def test_old_motion_event_does_not_override_replacement_command(self):
        await self.bridge.configure('robot','http://unused',True)
        await self.bridge.event({'robot_id':'robot','epoch':1,'name':'body_event',
            'data':{'kind':'servo_stall','command_sequence':99}})
        self.assertFalse(self.bridge.jobs)

    async def test_recovery_receives_interrupted_program_and_fresh_observations(self):
        self.bridge.generate=lambda endpoint,request:self.generate(endpoint,copy.deepcopy(request))
        for kind in ('servo_stall', 'tipped', 'rapid_movement', 'slip'):
            with self.subTest(kind=kind):
                entered=asyncio.Event()
                original_receipt=self.gateway.wait_terminal
                async def waiting_receipt(*args, **kwargs):
                    entered.set()
                    await asyncio.Future()
                self.gateway.wait_terminal=waiting_receipt
                submitted=await self.bridge.submit('robot','wave',True)
                interrupted=self.bridge.tasks[submitted['job_id']]
                await entered.wait()
                prior=self.bridge.jobs[submitted['job_id']]
                prior['history']=[{'joints':{JOINTS[0]:9}}]
                self.gateway.wait_terminal=original_receipt
                async def fresh(*args):
                    return {'joints':[{'id':i,'model_deg':12,'command_us':1500,
                                      'calibrated':True} for i in range(12)]}
                self.bridge.transport.request=fresh
                await self.bridge.configure('robot','http://unused',True)
                await self.bridge.event({'robot_id':'robot','epoch':1,'name':'body_event',
                    'data':{'kind':kind,'joints':[{'id':0}]}})
                recovery=next(task for identifier,task in self.bridge.tasks.items() if identifier!=submitted['job_id'])
                await asyncio.gather(interrupted,recovery)
                request=self.generated[-1]
                self.assertEqual(prior['state'],'superseded')
                self.assertEqual(request['request'],'wave')
                self.assertEqual(request['event']['type'],kind)
                self.assertEqual(request['observation']['joints'][JOINTS[0]]['model_deg'],12)
                self.assertEqual(len(request['history']),1)
                self.assertNotIn('interrupted_program',request['history'][0])
                self.assertEqual(request['history'][-1]['interrupted_action'],prior['current_action'])
                self.assertNotIn('packet_progress',request['history'][-1])
                self.assertEqual(request['history'][-1]['remaining_program'],prior['remaining_program'])

    async def test_faces_do_not_wait_for_receipts_and_release_only_the_owned_selection(self):
        sent=[]
        async def face(name,params,**kwargs):
            self.assertEqual(name,'face')
            sent.append(params)
            return 100+len(sent)
        self.gateway.queue_intent=face
        original_receipt=self.gateway.wait_terminal
        async def receipt(seq,**kwargs):
            self.assertLess(seq,100,'A face receipt must not block body movement')
            return await original_receipt(seq,**kwargs)
        self.gateway.wait_terminal=receipt
        self.bridge.generate=lambda *args:{'program':[
            call('face',expr='wave'),move(JOINTS[0],5,'current',50)]}
        submitted=await self.bridge.submit('robot','wave',True)
        await self.bridge.tasks[submitted['job_id']]
        self.assertEqual(self.bridge.jobs[submitted['job_id']]['state'],'completed')
        self.assertTrue(self.gateway.sent)
        self.assertEqual(sent[0]['expr'],'wave')
        self.assertEqual(sent[1],{'release':True,'token':sent[0]['token'],'if_token':sent[0]['token']})
        for message in sent:
            validate_control_message({'t':'intent','name':'face','seq':1,**message})

    async def test_face_only_request_retains_the_normal_visible_face(self):
        sent=[]
        async def face(name,params,**kwargs):
            sent.append(params);return 100
        self.gateway.queue_intent=face
        self.bridge.generate=lambda *args:{'program':[call('face',expr='happy')]}
        submitted=await self.bridge.submit('robot','look happy',True)
        await self.bridge.tasks[submitted['job_id']]
        self.assertEqual(sent,[{'expr':'happy'}])
        self.assertFalse(self.gateway.sent)

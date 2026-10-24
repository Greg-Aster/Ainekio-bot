"""Opt-in Body Control owner for the removable Freestyle experiment."""
import asyncio
import contextvars
from contextlib import AsyncExitStack
import copy
import inspect
import json
from pathlib import Path
from itertools import chain
from uuid import uuid4

from .generator import async_remote_generate
from .program import JOINTS, calibrated_positions, frame, frames_for, packets, gait_intents

OWNER = contextvars.ContextVar('freestyle_job', default=None)


class Bridge:
    def __init__(self, gateway, transport, generate=async_remote_generate, *, recorder=None, settings_path=None):
        self.gateway, self.transport, self.generate = gateway, transport, generate
        self.settings, self.jobs, self.tasks, self.active = {}, {}, {}, {}
        self.recorder = recorder
        self.settings_path = Path(settings_path) if settings_path else None
        if self.settings_path and self.settings_path.exists():
            self.settings = json.loads(self.settings_path.read_text())
        gateway.subscribe_events(self.event)
        gateway.subscribe_commands(self.command)

    def status(self):
        # The dashboard polls this summary. Full observations/history remain in
        # the inference request; they are not retransmitted on each UI refresh.
        jobs = {key:{**{k:job[k] for k in ('id','robot_id','request','execute','state')},
                     'error':job.get('error'),'current_action':job.get('current_action'),
                     'latest_generation':job['programs'][-1] if job['programs'] else None,
                     'completed_commands':len(job['receipts'])} for key,job in self.jobs.items()}
        return {'settings':copy.deepcopy(self.settings), 'jobs':copy.deepcopy(jobs),
                'recording':self.recorder.status() if self.recorder else {'enabled':False}}

    def record(self, job, kind, payload, sequence=None):
        if self.recorder:
            return self.recorder.record(kind, payload, robot_id=job['robot_id'], epoch=job['epoch'],
                                        job_id=job['id'], sequence=sequence)

    async def configure(self, robot, endpoint, recover_events):
        self.settings[robot] = {'endpoint':endpoint, 'recover_events':bool(recover_events)}
        if self.settings_path:
            saved = json.dumps(self.settings)
            def write():
                self.settings_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.settings_path.with_suffix('.tmp')
                temporary.write_text(saved)
                temporary.chmod(0o600)
                temporary.replace(self.settings_path)
            await asyncio.to_thread(write)
        return self.status()

    def review(self, robot, job_id, outcome, note='', corrected_request=None, corrected_program=None,
               generation_index=None):
        job = self.jobs[job_id]
        if job['robot_id'] != robot:
            raise ValueError('This trial belongs to a different selected robot')
        if outcome not in ('success', 'partial', 'incorrect'):
            raise ValueError('Choose success, partial, or incorrect')
        index = len(job['programs'])-1 if generation_index is None else generation_index
        if type(index) is not int or not 0 <= index < len(job['programs']):
            raise ValueError('Select an existing generation to review')
        value = {'generation_index':index, 'outcome':outcome, 'note':note,
                 'corrected_request':corrected_request, 'corrected_program':corrected_program}
        identifier = self.record(job, 'review', value)
        job['review'] = value
        return {'review_id':identifier, 'saved':identifier is not None, 'review':value}

    def trial(self, robot, job_id):
        job = self.jobs[job_id]
        if job['robot_id'] != robot:
            raise ValueError('This trial belongs to a different selected robot')
        return {'schema':'freestyle_trial_v1', 'job':copy.deepcopy(job),
                'evidence':{'sampling':'before and after each operation',
                            'continuous_servo_trace':False, 'physical_success':None},
                'note':'Completion receipts and endpoint observations do not prove all intermediate targets were reached.'}

    async def submit(self, robot, request, execute=False, event=None, *, job_id=None, on_start=None):
        setting = self.settings.get(robot, {'endpoint':'http://127.0.0.1:8794', 'recover_events':False})
        previous = self.active.get(robot)
        history = copy.deepcopy(self.jobs[previous]['history']) if event and previous else []
        if event and previous:
            interrupted = self.jobs[previous]
            history.append({'observation':copy.deepcopy(interrupted.get('observation')),
                            'interrupted_action':copy.deepcopy(interrupted.get('current_action')),
                            'interrupted_program':copy.deepcopy(interrupted['programs'][-1] if interrupted['programs'] else None),
                            'packet_progress':copy.deepcopy(interrupted.get('packet_progress')), 'event':event})
        job_id = job_id or uuid4().hex
        epoch=(await self.gateway.status_snapshot())['robots'][robot]['epoch']
        async with AsyncExitStack() as admission:
            if on_start is not None:
                await admission.enter_async_context(on_start(job_id))
            if execute and previous and previous in self.tasks:
                self.tasks[previous].cancel()
            job = {'id':job_id,'robot_id':robot,'request':request,'execute':execute,'event':event,
                   'epoch':epoch,'state':'generating','history':history,'programs':[],'receipts':[]}
            self.jobs[job_id] = job
            self.record(job, 'job_started', job)
            if execute:
                self.active[robot] = job_id
            task = asyncio.create_task(self._run(job, setting),name='freestyle-'+job_id)
            self.tasks[job_id] = task
            task.add_done_callback(lambda finished: self._cancelled_before_start(job, finished))
            return {'job_id':job_id}

    def _cancelled_before_start(self, job, task):
        if task.cancelled():
            job['state'] = 'superseded'
            self.record(job, 'job_finished', {'state':job['state'], 'execute':job['execute']})
            self.tasks.pop(job['id'], None)

    async def result(self, job_id):
        job = self.jobs[job_id]
        task = self.tasks.get(job_id)
        if task is not None:
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                if not task.cancelled():
                    raise
        return copy.deepcopy({key: job[key] for key in
            ('id', 'robot_id', 'epoch', 'request', 'state', 'receipts', 'observation', 'error', 'last_sequence') if key in job})

    async def cancel(self, job_id):
        job = self.jobs[job_id]
        task = self.tasks.get(job_id)
        if task is not None and self.active.get(job['robot_id']) == job_id:
            job['cancellation_requested'] = True
            task.cancel()
        return await self.result(job_id)

    async def observation(self, robot):
        snapshot = (await self.gateway.status_snapshot())['robots'][robot]
        if snapshot['model'] != 'v2-12servo':
            raise ValueError('This trained joint contract describes the V2 twelve-servo body')
        calibration = snapshot.get('calibration') or await self.gateway.body_calibration('get',robot_id=robot)
        speed = snapshot.get('motion_speed') or await self.gateway.body_motion_speed('get',robot_id=robot)
        feedback = await self.transport.request(robot,'servo-feedback',None)
        home, commanded = calibrated_positions(calibration)
        joints = {j:{'home_deg':home[j], 'commanded_model_deg':commanded[j]} for j in JOINTS}
        for item in feedback.get('joints',[]):
            j=JOINTS[item['id']]
            joints[j].update({k:item[k] for k in ('model_deg','calibrated','in_calibrated_range','command_us') if k in item})
            mapping = next(v for v in calibration['joints'] if v['id']==item['id'])
            joints[j]['commanded_model_deg'] = (home[j]+(-1 if mapping['invert'] else 1)*(item['command_us']-mapping['home_us'])/mapping['us_per_degree']
                                                 if item['command_us'] else None)
            if 'velocity_us_s' in item:
                joints[j]['velocity_deg_s'] = (-1 if mapping['invert'] else 1)*item['velocity_us_s']/mapping['us_per_degree']
        status = (await self.gateway.status_snapshot())['robots'][robot]['status'] or {}
        imu = status.get('imu')
        return {'epoch':snapshot['epoch'],'joints':joints,'imu':imu,
                'expected_up':((imu or {}).get('motion') or {}).get('expected_up'),
                'feedback':{k:feedback[k] for k in ('device_us','scan_us','enabled','stalled_joints','no_progress_ms') if k in feedback},
                'joint_speed_limit_deg_s':speed['joint_speed_limit_deg_s'],
                'action':snapshot.get('body_command'), 'model':'v2-12servo'}

    async def _run(self, job, setting):
        token = OWNER.set(job['id'])
        robot = job['robot_id']
        try:
            original_event = job['event']
            event = ({'type':original_event['data']['kind'], **original_event['data'],
                      'event_id':original_event.get('event_id'),'epoch':original_event.get('epoch')}
                     if original_event and original_event.get('name')=='body_event' else original_event)
            continuation = []
            while True:
                obs = await self.observation(robot)
                if continuation:obs={**obs,'pending_actions':continuation}
                job['observation'] = obs
                if 'initial_observation' not in job:
                    job['initial_observation'] = copy.deepcopy(obs)
                request = {'request':job['request'],'observation':obs,'event':event,'history':job['history']}
                generation_index = len(job['programs'])
                self.record(job, 'generation_requested', {'generation_index':generation_index,
                            'execute':job['execute'], 'request':request})
                result = (await self.generate(setting['endpoint'],request) if inspect.iscoroutinefunction(self.generate)
                          else await asyncio.to_thread(self.generate,setting['endpoint'],request))
                job['programs'].append(result)
                self.record(job, 'generation_completed', {'generation_index':generation_index, 'result':result})
                if not job['execute']:
                    job['state']='generated';return
                job['state']='executing'
                reassess = False
                program = result['program']+continuation
                continuation = []
                for index, action in enumerate(program):
                    job['current_action'] = action
                    job['packet_progress'] = None
                    self.record(job, 'operation_started', {'generation_index':generation_index,
                                'action_index':index, 'action':action, 'observation':obs})
                    name, args = action['name'], action['arguments']
                    if name == 'face':
                        # A token keeps the expression across this program's
                        # motion_plan revisions. Face receipts are captured by
                        # the gateway recorder; they never delay body motion.
                        scoped = any(item['name'] != 'face' for item in program)
                        face_token = 'fs_' + job['id'][:24] if scoped else None
                        seq = await self.gateway.queue_intent('face',
                            {'expr':args['expr'], **({'token':face_token} if scoped else {})}, robot_id=robot)
                        if scoped:job['face_token'] = face_token
                        self.record(job, 'face_submitted', {'expression':args['expr'],
                                    'scope':'program' if scoped else 'normal_face_selection',
                                    'generation_index':generation_index, 'action_index':index}, sequence=seq)
                        continue
                    if name == 'reassess':
                        continuation = program[index+1:]
                        reassess=True; break
                    before = obs
                    if name == 'hold':
                        await asyncio.sleep(args['seconds'])
                    elif name in ('move','pose','oscillate','feet','body'):
                        # Only commanded joints change. Current-relative targets
                        # start from measured angles when the body supplies them.
                        current = {j:v.get('model_deg',v['commanded_model_deg']) for j,v in obs['joints'].items()}
                        home = {j:v['home_deg'] for j,v in obs['joints'].items()}
                        commanded = {j:(v['commanded_model_deg'] if v['commanded_model_deg'] is not None else v.get('model_deg'))
                                     for j,v in obs['joints'].items()}
                        spatial=name in ('feet','body')
                        moving = (list(JOINTS) if name=='body' else
                                  [f'{leg}_{axis}' for leg in args['legs'] for axis in ('shoulder','carrier','crank')] if name=='feet' else
                                  args['joints'] if name=='pose' else [args['joint']])
                        start = {**commanded,**{j:current[j] for j in moving}}
                        if spatial:
                            from .kinematics import frames_for_spatial
                            frames = await asyncio.to_thread(frames_for_spatial,action,start)
                        else:
                            frames = frames_for(action,start,home,obs['joint_speed_limit_deg_s'])
                        if any(v.get('command_us')==0 for v in obs['joints'].values()):
                            # After released outputs the P4 arms at the packet's
                            # first target. Supply the measured starting pose,
                            # then the generated travel; never arm at its endpoint.
                            # One millisecond is the existing wire resolution.
                            frames = chain([frame(1,start)],frames)
                        progress = {'completed_frames':0,'submitted_frames':None,'sequence':None}
                        job['packet_progress'] = progress
                        for packet in packets(frames):
                            progress['submitted_frames'] = packet
                            seq = await self.gateway.queue_motion_plan(packet,end='hold',robot_id=robot)
                            progress['sequence'] = seq
                            await self._receipt(job,seq,obs['epoch'])
                            progress['completed_frames'] += len(packet)
                    elif name == 'gait':
                        for intent in gait_intents(args):
                            seq = await self.gateway.queue_intent('walk',intent,robot_id=robot)
                            await self._receipt(job,seq,obs['epoch'])
                    else:
                        if name == 'gesture':
                            gesture=args['name']
                            seq = await self.gateway.queue_intent(gesture,robot_id=robot) if gesture in ('stand','neutral','sit') else await self.gateway.emote(gesture,robot_id=robot)
                        elif name == 'stop':
                            seq = await self.gateway.estop(robot_id=robot)
                        else:
                            raise ValueError('Unknown program operation '+name)
                        await self._receipt(job,seq,obs['epoch'])
                    obs = await self.observation(robot)
                    job['observation'] = obs
                    # Preserve each measured before/after sample without copying
                    # calibration tables or the entire previous program again.
                    def sample(value):
                        return {'time_us':value['feedback'].get('device_us'),
                                'joints':{j:v.get('model_deg') for j,v in value['joints'].items()},
                                'imu':value['imu']}
                    initial = {**sample(before),'action':action}
                    if name in ('move','pose'):
                        targets = args['angles_deg'] if name=='pose' else [args['angle_deg']]
                        initial['correction_delta_deg'] = {
                            j:(angle if args['reference']=='current' else
                               angle+(home[j] if args['reference']=='home' else 0)-start[j])
                            for j,angle in zip(moving,targets)}
                    job['history'].extend([initial,sample(obs)])
                    self.record(job, 'operation_completed', {'generation_index':generation_index,
                                'action_index':index, 'before':initial, 'after':sample(obs)})
                if not reassess:
                    job['state']='completed';return
                job['state']='generating'
                event={'type':'reassess'}
        except asyncio.CancelledError:
            if job.get('cancellation_requested') and job['state'] == 'executing' and self.active.get(robot) == job['id']:
                try:
                    def still_owned(sequence):
                        if self.active.get(robot) != job['id']:
                            raise ValueError('Motion was replaced before cancellation dispatch')
                    seq = await self.gateway.estop(robot_id=robot, on_sequence=still_owned)
                    await self._receipt(job, seq, job['epoch'])
                except Exception as error:
                    job.update(state='error', error=str(error))
                else:
                    job['state']='superseded'
            else:
                job['state']='superseded'
        except Exception as error:
            job.update(state='error',error=str(error))
            self.record(job, 'job_error', {'error':str(error), 'evidence':getattr(error,'evidence',None)})
        finally:
            if job.get('face_token'):
                try:
                    seq = await self.gateway.queue_intent('face',
                        {'release':True, 'token':job['face_token'], 'if_token':job['face_token']}, robot_id=robot)
                    self.record(job, 'face_released', {'token':job['face_token']}, sequence=seq)
                except Exception as error:
                    self.record(job, 'face_release_error', {'error':str(error)})
            self.record(job, 'job_finished', {'state':job['state'], 'error':job.get('error'),
                        'execute':job['execute'], 'current_action':job.get('current_action'),
                        'packet_progress':job.get('packet_progress')})
            OWNER.reset(token)
            self.tasks.pop(job['id'],None)

    async def _receipt(self,job,seq,epoch):
        receipt=await self.gateway.wait_terminal(seq,robot_id=job['robot_id'],epoch=epoch,timeout=None)
        job['receipts'].append(receipt)
        self.record(job, 'command_receipt', receipt, sequence=seq)
        if receipt.get('t')!='done':
            raise RuntimeError('Body reported '+str(receipt))

    async def event(self,event):
        robot=event.get('robot_id'); setting=self.settings.get(robot,{})
        if event.get('t')=='connection':
            # Pending generation belongs to the body session that supplied its
            # observations; reconnect does not transfer ownership of that work.
            previous=self.active.get(robot)
            job=self.jobs.get(previous)
            if job and ((event.get('status')=='disconnected' and event.get('epoch')==job['epoch']) or
                        (event.get('status')=='connected' and event.get('epoch')!=job['epoch'])):
                self.active.pop(robot,None)
                if previous in self.tasks:self.tasks[previous].cancel()
            return
        if not setting.get('recover_events') or event.get('name')!='body_event':
            return
        data=event.get('data',{})
        if data.get('kind') not in ('servo_stall','tipped','rapid_movement','slip'):
            return
        snapshot=(await self.gateway.status_snapshot())['robots'].get(robot)
        if snapshot is None or event.get('epoch',snapshot['epoch'])!=snapshot['epoch']:
            return
        sequence=data.get('command_sequence')
        if sequence and sequence!=snapshot.get('body_command_sequence'):
            # A delayed receipt for a replaced command cannot supersede its
            # replacement (particularly an operator's Stop).
            return
        previous=self.jobs.get(self.active.get(robot),{})
        request=previous.get('request') or 'Recover from the reported body event using the available observations.'
        await self.submit(robot,request,True,event)

    async def command(self,command):
        robot=command.get('robot_id'); previous=self.active.get(robot)
        if not previous:
            return
        motion = command.get('t') in ('stop','motion_plan','servo','mode','state') or (
            command.get('t')=='intent' and command.get('name') not in ('face','say')) or (
            command.get('t')=='calibration' and command.get('op')!='get')
        if motion and OWNER.get() == previous:
            self.jobs[previous]['last_sequence'] = command.get('seq')
            return
        if motion:
            task=self.tasks.get(previous)
            if task:task.cancel()
            self.active.pop(robot,None)

    async def close(self):
        self.gateway.unsubscribe_events(self.event)
        self.gateway.unsubscribe_commands(self.command)
        tasks=list(self.tasks.values())
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        await self.transport.close()

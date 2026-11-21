"""Freestyle generation and execution owner shared by Body Control and MetaHuman."""
import asyncio
import contextvars
from contextlib import AsyncExitStack, asynccontextmanager
from concurrent.futures import ProcessPoolExecutor
import copy
import inspect
import json
import multiprocessing
from pathlib import Path
from uuid import uuid4

from .generator import async_remote_generate
from .recordings import read_records
from .observations import feedback_geometry
from .program import JOINTS, calibrated_positions, compile_motion, packets, gait_intents
from .neural_pose.executor import NeuralPoseRuntime, execute_neural_pose_program

OWNER = contextvars.ContextVar('freestyle_job', default=None)


class Bridge:
    def __init__(self, gateway, transport, generate=async_remote_generate, *, recorder=None, settings_path=None,
                 compiler=None, neural_pose_runtime=None):
        self.gateway, self.transport, self.generate = gateway, transport, generate
        self.settings, self.jobs, self.tasks, self.active = {}, {}, {}, {}
        self.connection_changes = {}
        self._custom_compiler = compiler is not None
        self.compiler = compiler or self._compile_motion
        self.neural_pose = neural_pose_runtime or NeuralPoseRuntime()
        self.compiler_pool = None
        self.trajectory_cleanups = set()
        self.feedback_syncs = set()
        self.synced_feedback_epochs = {}
        self.recorder = recorder
        self.settings_path = Path(settings_path) if settings_path else None
        if self.settings_path and self.settings_path.exists():
            loaded = json.loads(self.settings_path.read_text())
            self.settings = {
                robot: {'endpoint': cfg.get('endpoint', 'http://127.0.0.1:8794')}
                for robot, cfg in loaded.items()
                if isinstance(cfg, dict)
            }
        gateway.subscribe_events(self.event)
        gateway.subscribe_commands(self.command)

    async def _compile_motion(self, action, observation, planned):
        # Python-heavy IK must not compete for the gateway interpreter's GIL.
        # Use the canonical import path: the dashboard loads this bridge under
        # an optional package alias which a spawned worker cannot import.
        from experiments.freestyle.program import compile_motion as worker_compile
        if self.compiler_pool is None:
            self.compiler_pool = ProcessPoolExecutor(max_workers=1,
                mp_context=multiprocessing.get_context('spawn'))
        return await asyncio.get_running_loop().run_in_executor(
            self.compiler_pool,worker_compile,action,observation,planned)

    async def _compile_action(self, action, observation, planned, supplied):
        try:
            return await self.compiler(action,observation,planned)
        except Exception as cause:
            evidence=getattr(cause,'evidence',None) or {}
            producer='supplied_program' if supplied else 'freestyle_generator'
            if evidence.get('kind')=='invalid_pose':
                prefix='Supplied motion program is invalid: ' if supplied else 'Freestyle generated an invalid program: '
            else:
                prefix='Supplied motion program could not be compiled: ' if supplied else 'Freestyle generated program could not be compiled: '
            error=ValueError(prefix+str(cause))
            error.evidence={**evidence,'kind':producer+'_invalid','producer':producer,
                            'stage':'compilation','operation':action['name']}
            raise error from cause

    async def _discard_trajectory(self,job,identifier,upload):
        try:
            # Cancellation must not race a still-receiving upload or delay
            # Stop/next-command admission. Cleanup follows its actual response.
            await upload
        except Exception:
            pass
        try:
            await self.transport.request(job['robot_id'],'trajectory',{'op':'discard','id':identifier})
        except Exception as error:
            message='Trajectory upload cleanup unconfirmed: '+str(error)
            job['error']='; '.join(v for v in (job.get('error'),message) if v)
            self.record(job,'trajectory_cleanup_failed',{'id':identifier,'error':str(error)})

    def status(self):
        # The dashboard polls this summary. Full observations/history remain in
        # the recorder; they are not retransmitted on each UI refresh.
        jobs = {key:{**{k:job[k] for k in ('id','robot_id','request','execute','state')},
                     'error':job.get('error'),'current_action':job.get('current_action'),
                     'completed_action':job.get('completed_action'),
                     'operation_index':job.get('operation_index'),
                     'completed_operation_index':job.get('completed_operation_index'),
                     'pause_state':job.get('pause_state'),'pause_cursor':job.get('pause_cursor'),
                     'start_index':job.get('start_index',0),'source':job.get('source'),
                     'owns_motion':self.active.get(job['robot_id']) == key,
                     'latest_generation':job['programs'][-1] if job['programs'] else None,
                     'completed_commands':len(job['receipts'])} for key,job in self.jobs.items()}
        return {'settings':copy.deepcopy(self.settings), 'jobs':copy.deepcopy(jobs),
                'neural_pose_active':bool(self.neural_pose.load() is not None),
                'recording':self.recorder.status() if self.recorder else {'enabled':False}}

    def _use_neural_pose(self, obs):
        return (
            not self._custom_compiler
            and 'walk_nominal_v1' in obs.get('features', [])
            and hasattr(self.gateway, 'body_sensor_observation')
            and hasattr(self.gateway, '_connection')
            and self.neural_pose.load() is not None
        )

    def record(self, job, kind, payload, sequence=None):
        if self.recorder:
            return self.recorder.record(kind, payload, robot_id=job['robot_id'], epoch=job['epoch'],
                                        job_id=job['id'], sequence=sequence)

    async def _sync_neural_pose_servo_feedback(self, robot, epoch=None, feedback=None):
        """Disable C-side stand_hold_recover when NeuralPose owns stance, keeping jam_enabled thermal cutoff armed."""
        if self._custom_compiler or self.neural_pose.load() is None:
            return
        try:
            snapshot = (await self.gateway.status_snapshot())['robots'].get(robot)
            if not snapshot or not snapshot.get('connected', True):
                return
            features = snapshot.get('features', [])
            if 'walk_nominal_v1' not in features or 'servo_feedback_v1' not in features:
                return
            cur_epoch = snapshot.get('epoch') if epoch is None else epoch
            if self.synced_feedback_epochs.get(robot) == cur_epoch and feedback is None:
                return
            fb = feedback if isinstance(feedback, dict) else await self.transport.request(robot, 'servo-feedback', None)
            self.synced_feedback_epochs[robot] = cur_epoch
            if (
                isinstance(fb, dict)
                and fb.get('enabled') is True
                and fb.get('stand_enabled') is True
                and isinstance(fb.get('jam_enabled'), bool)
                and isinstance(fb.get('tolerance_us'), int)
            ):
                payload = {
                    'op': 'configure',
                    'enabled': True,
                    'stand_enabled': False,
                    'jam_enabled': bool(fb['jam_enabled']),
                    'tolerance_us': int(fb['tolerance_us']),
                }
                for opt in ('arrival_tolerance_us', 'no_progress_ms', 'progress_us'):
                    if isinstance(fb.get(opt), int):
                        payload[opt] = int(fb[opt])
                await self.transport.request(robot, 'servo-feedback', payload)
        except Exception:
            pass

    async def configure(self, robot, endpoint):
        self.settings[robot] = {'endpoint': endpoint}
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

    def _recorded_job(self, job_id):
        if job_id in self.jobs:
            return self.jobs[job_id]
        if self.recorder is None:
            raise KeyError(job_id)
        records = list(read_records(self.recorder.path, job_id))
        started = next((r['payload'] for r in records if r['kind'] == 'job_started'), None)
        if started is None:
            raise KeyError(job_id)
        job = copy.deepcopy(started)
        job['programs'] = [r['payload']['result'] for r in records
                           if r['kind'] in ('generation_completed', 'correction_trial_program')]
        job['receipts'] = [r['payload'] for r in records if r['kind'] == 'command_receipt']
        reviews = [r['payload'] for r in records if r['kind'] == 'review']
        if reviews:
            job['review'] = reviews[-1]
        finished = next((r['payload'] for r in reversed(records) if r['kind'] == 'job_finished'), None)
        if finished is not None:
            job.update({k: v for k, v in finished.items() if v is not None or k == 'state'})
        return job

    async def review(self, robot, job_id, outcome, note='', corrected_request=None, corrected_program=None,
               generation_index=None):
        job = await asyncio.to_thread(self._recorded_job, job_id) if job_id not in self.jobs else self.jobs[job_id]
        if job['robot_id'] != robot:
            raise ValueError('This trial belongs to a different selected robot')
        if outcome not in ('success', 'partial', 'incorrect'):
            raise ValueError('Choose success, partial, or incorrect')
        index = len(job['programs'])-1 if generation_index is None else generation_index
        if type(index) is not int or not 0 <= index < len(job['programs']):
            raise ValueError('Select an existing generation to review')
        value = {'generation_index':index, 'outcome':outcome, 'note':note,
                 'corrected_request':corrected_request, 'corrected_program':corrected_program}
        if corrected_program is not None:
            value['training_status'] = 'awaiting_physical_trial'
        identifier = self.record(job, 'review', value)
        if identifier is not None:
            await asyncio.to_thread(self.recorder.flush)
        job['review'] = value
        return {'review_id':identifier, 'saved':identifier is not None, 'review':value}

    def trial(self, robot, job_id):
        job = self._recorded_job(job_id)
        if job['robot_id'] != robot:
            raise ValueError('This trial belongs to a different selected robot')
        return {'schema':'freestyle_trial_v1', 'job':copy.deepcopy(job),
                'evidence':{'sampling':'before and after each operation',
                            'continuous_servo_trace':False, 'physical_success':None},
                'note':'Completion receipts and endpoint observations do not prove all intermediate targets were reached.'}

    async def corrections(self, robot):
        if self.recorder is None:
            raise ValueError('Motion recording is not configured')
        def executable(program):
            if not isinstance(program, list) or not program:
                return False
            for action in program:
                if not isinstance(action, dict) or not isinstance(action.get('arguments'), dict):
                    return False
                args = action['arguments']
                if action.get('name') in ('move', 'pose', 'oscillate', 'feet', 'body'):
                    if 'speed_pct' not in args or 'seconds' in args or 'period_s' in args:
                        return False
            return True
        def load():
            records = list(read_records(self.recorder.path, kinds=(
                'generation_requested', 'correction_trial_requested', 'review')))
            requested = {(r['job_id'], r['payload'].get('generation_index', 0)):r['payload']['request']
                         for r in records if r['kind'] in ('generation_requested', 'correction_trial_requested')}
            latest = {}
            for record in records:
                if record['kind'] == 'review' and record['robot_id'] == robot:
                    latest[(record['job_id'], record['payload'].get('generation_index', 0))] = record
            return [{**r, 'request':requested[key]['request']} for key,r in reversed(list(latest.items()))
                    if executable(r['payload'].get('corrected_program')) and key in requested]
        return await asyncio.to_thread(load)

    async def test_correction(self, robot, review_id):
        correction = next((r for r in await self.corrections(robot) if r['id'] == review_id), None)
        if correction is None:
            raise ValueError('Select a recorded correction for this robot')
        review = correction['payload']
        return await self.submit(robot, review.get('corrected_request') or correction['request'], True,
            program=review['corrected_program'],
            source={'kind':'correction_trial', 'original_job_id':correction['job_id'],
                    'review_id':review_id})

    async def submit(self, robot, request, execute=False, *, job_id=None, on_start=None,
                     program=None, source=None, start_index=0):
        setting = self.settings.get(robot, {'endpoint': 'http://127.0.0.1:8794'})
        previous = self.active.get(robot)
        job_id = job_id or uuid4().hex
        epoch = (await self.gateway.status_snapshot())['robots'][robot]['epoch']
        async with AsyncExitStack() as admission:
            if on_start is not None:
                await admission.enter_async_context(on_start(job_id))
            if execute and previous and previous in self.tasks:
                self.tasks[previous].cancel()
            job = {'id': job_id, 'robot_id': robot, 'request': request, 'execute': execute, 'event': None,
                   'epoch': epoch, 'state': 'generating', 'history': [], 'programs': [], 'receipts': []}
            if program is not None:
                job.update(supplied_program=copy.deepcopy(program), source=copy.deepcopy(source), start_index=start_index)
            self.jobs[job_id] = job
            self.record(job, 'job_started', job)
            if execute:
                self.active[robot] = job_id
            task = asyncio.create_task(self._run(job, setting), name='freestyle-' + job_id)
            self.tasks[job_id] = task
            task.add_done_callback(lambda finished: self._cancelled_before_start(job, finished))
            return {'job_id': job_id}

    def _cancelled_before_start(self, job, task):
        if task.cancelled():
            if job.get('abort_error'):
                job.update(state='error', error=job['abort_error'])
                if job.get('abort_evidence') is not None:
                    job['error_evidence'] = copy.deepcopy(job['abort_evidence'])
                self.record(job, 'job_error', {'error':job['abort_error'], 'evidence':job.get('abort_evidence')})
            else:
                job['state'] = 'superseded'
            self.record(job, 'job_finished', {'state':job['state'], 'error':job.get('error'), 'execute':job['execute']})
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
            ('id', 'robot_id', 'epoch', 'request', 'state', 'receipts', 'observation', 'error', 'error_evidence', 'last_sequence',
             'operation_index','completed_operation_index','pause_state','pause_cursor','start_index') if key in job})

    async def cancel(self, job_id):
        job = self.jobs[job_id]
        task = self.tasks.get(job_id)
        if task is not None and not job.get('cancellation_requested') and self.active.get(job['robot_id']) == job_id:
            job['cancellation_requested'] = True
            task.cancel()
        return await self.result(job_id)

    async def _stop_job(self, job, detach=False):
        token = OWNER.set(job['id'])
        try:
            def still_owned(sequence):
                if self.active.get(job['robot_id']) != job['id']:
                    raise ValueError('Motion was replaced before stop dispatch')
            options = {'detach':True} if detach else {}
            seq = await self.gateway.estop(robot_id=job['robot_id'],on_sequence=still_owned,**options)
            await self._receipt(job,seq,job['epoch'],acknowledgement=True)
            if job.get('pause_requested'):
                job['pause_state'] = 'released' if detach else 'paused'
        finally:
            OWNER.reset(token)

    async def pause(self, job_id, *, release=False):
        job = self.jobs[job_id]
        if self.active.get(job['robot_id']) != job_id:
            raise ValueError('This example no longer owns the robot')
        if job.get('pause_state') == 'released' and not release:
            return await self.result(job_id)
        snapshot = (await self.gateway.status_snapshot())['robots'].get(job['robot_id'],{})
        motion = ((snapshot.get('status') or {}).get('imu') or {}).get('motion') or {}
        if motion.get('sequence') == job.get('last_sequence') and motion.get('trajectory'):
            job['pause_cursor'] = copy.deepcopy(motion['trajectory'])
        if job_id not in self.tasks:job.pop('pause_stop_attempted',None)
        job['pause_requested'] = True
        job['pause_detach'] = release
        # Cancellation keeps the interrupted operation and performs the existing
        # Stop before trajectory cleanup. A terminal/never-started job still
        # needs the explicit operator Stop/Release below.
        await self.cancel(job_id)
        desired = 'released' if release else 'paused'
        if job.get('pause_state') == 'released' and not release:
            return await self.result(job_id)
        if job.get('pause_state') != desired:
            if job.get('pause_stop_attempted') and job.get('pause_state') is None:
                raise ValueError(job.get('error') or 'The body did not acknowledge pause')
            await self._stop_job(job,release)
        self.record(job,'editing_paused',{'pause_state':job['pause_state'],
            'operation_index':job.get('operation_index'), 'pause_cursor':job.get('pause_cursor')})
        return await self.result(job_id)

    async def observation(self, robot):
        snapshot = (await self.gateway.status_snapshot())['robots'][robot]
        if snapshot['model'] != 'v2-12servo':
            raise ValueError('This trained joint contract describes the V2 twelve-servo body')
        calibration = snapshot.get('calibration') or await self.gateway.body_calibration('get',robot_id=robot)
        speed = snapshot.get('motion_speed') or await self.gateway.body_motion_speed('get',robot_id=robot)
        feedback = await self.transport.request(robot,'servo-feedback',None)
        await self._sync_neural_pose_servo_feedback(robot, epoch=snapshot['epoch'], feedback=feedback)
        home, commanded = calibrated_positions(calibration)
        joints = {j:{'home_deg':home[j], 'commanded_model_deg':commanded[j]} for j in JOINTS}
        for item in feedback.get('joints',[]):
            j=JOINTS[item['id']]
            joints[j].update({k:item[k] for k in ('model_deg','calibrated','in_calibrated_range','command_us') if k in item})
            mapping = next(v for v in calibration['joints'] if v['id']==item['id'])
            joints[j].update(feedback_geometry(mapping, item, feedback))
            joints[j]['commanded_model_deg'] = (home[j]+(-1 if mapping['invert'] else 1)*(item['command_us']-mapping['home_us'])/mapping['us_per_degree']
                                                 if item['command_us'] else None)
            if 'velocity_us_s' in item:
                joints[j]['velocity_deg_s'] = (-1 if mapping['invert'] else 1)*item['velocity_us_s']/mapping['us_per_degree']
        status = (await self.gateway.status_snapshot())['robots'][robot]['status'] or {}
        imu = status.get('imu')
        motion=(imu or {}).get('motion') or {}
        trajectory=copy.deepcopy(motion.get('trajectory'))
        if trajectory is not None:
            trajectory.update({k:motion[k] for k in ('sequence','sampled_us','phase') if k in motion})
        return {'epoch':snapshot['epoch'],'joints':joints,'imu':imu,
                'features':snapshot.get('features',[]),
                'trajectory_progress':trajectory,
                'expected_up':((imu or {}).get('motion') or {}).get('expected_up'),
                'feedback':{k:feedback[k] for k in ('device_us','scan_us','enabled','stalled_joints','no_progress_ms',
                    'waiting_joints','stall_clock_us','health') if k in feedback},
                'joint_speed_limit_deg_s':speed['joint_speed_limit_deg_s'],
                'action':snapshot.get('body_command'), 'model':'v2-12servo'}

    async def connected_observation(self, job):
        """Retain local work while delivery has no robot transport.

        Connection events wake only this job; inference, other jobs and manual
        command admission remain independent. There is no reconnect deadline.
        """
        robot = job['robot_id']
        state = job['state']
        while True:
            changed = self.connection_changes.setdefault(robot, asyncio.Event())
            snapshot = (await self.gateway.status_snapshot())['robots'].get(robot)
            if snapshot and snapshot.get('connected', True):
                try:
                    obs = await self.observation(robot)
                except Exception:
                    current = (await self.gateway.status_snapshot())['robots'].get(robot)
                    if changed.is_set() or not current or not current.get('connected', True):
                        continue
                    raise
                current = (await self.gateway.status_snapshot())['robots'].get(robot)
                if current and current.get('connected', True) and current['epoch'] == obs['epoch']:
                    if job['epoch'] != obs['epoch']:
                        previous = job['epoch']
                        job['epoch'] = obs['epoch']
                        self.record(job, 'connection_resumed', {'previous_epoch':previous})
                    job['state'] = state
                    return obs
                continue
            if job['state'] != 'awaiting_connection':
                job['state'] = 'awaiting_connection'
                self.record(job, 'delivery_pending', {'resume_state':state})
            await changed.wait()

    async def _run(self, job, setting):
        token = OWNER.set(job['id'])
        robot = job['robot_id']
        prepared = None
        motion_names = ('move','pose','oscillate','feet','body')
        try:
            obs = await self.connected_observation(job)
            job['observation'] = obs
            if 'initial_observation' not in job:
                job['initial_observation'] = copy.deepcopy(obs)
            request = {'request':job['request'],'observation':obs,'event':None,'history':job['history']}
            generation_index = len(job['programs'])
            supplied = 'supplied_program' in job and not job['programs']
            self.record(job, 'correction_trial_requested' if supplied else 'generation_requested',
                        {'generation_index':generation_index, 'execute':job['execute'],
                         'request':request, **({'source':job['source']} if supplied else {})})
            if supplied:
                result = {'program':copy.deepcopy(job['supplied_program']), 'source':job['source']}
            elif self.generate is async_remote_generate:
                result = await self.generate(setting['endpoint'],request,job_id=job['id'])
            else:
                result = (await self.generate(setting['endpoint'],request) if inspect.iscoroutinefunction(self.generate)
                          else await asyncio.to_thread(self.generate,setting['endpoint'],request))
            job['programs'].append(result)
            self.record(job, 'correction_trial_program' if supplied else 'generation_completed',
                        {'generation_index':generation_index, 'result':result})
            if not job['execute']:
                job['state']='generated';return
            job['remaining_program'] = copy.deepcopy(result['program'])
            # Generation survives robot session changes. Compile its result
            # from current measurements, not the pre-inference body pose.
            obs = await self.connected_observation(job)
            job['observation'] = obs
            job['state']='executing'
            program = result['program']
            if self._use_neural_pose(obs):
                obs = await execute_neural_pose_program(
                    self,
                    job,
                    program,
                    obs,
                    generation_index=generation_index,
                    sequence_options={},
                    runtime=self.neural_pose,
                )
                job['state'] = 'completed_section' if job.get('start_index', 0) else 'completed'
                return
            planned = None
            planning_epoch = obs['epoch']
            for index in range(job.get('start_index',0),len(program)):
                action = program[index]
                name, args = action['name'], action['arguments']
                if obs['epoch'] != planning_epoch:
                    planned = None
                    planning_epoch = obs['epoch']
                    if prepared is not None:
                        prepared[1].cancel()
                        await asyncio.gather(prepared[1],return_exceptions=True)
                        prepared = None
                job['operation_index'] = index
                job['current_action'] = action
                job['remaining_program'] = copy.deepcopy(program[index+1:])
                job['packet_progress'] = None
                self.record(job, 'operation_started', {'generation_index':generation_index,
                            'action_index':index, 'action':action, 'observation':obs})
                if name == 'face':
                    # A token keeps the expression across this program's
                    # motion_plan revisions. Face receipts are captured by
                    # the gateway recorder; they never delay body motion.
                    scoped = any(item['name'] != 'face' for item in program)
                    # Request IDs are opaque caller correlation IDs, not
                    # protocol asset names. Own a separate wire-valid token
                    # and reuse it for this job's selections and release.
                    face_token = (job.get('face_token') or 'fs_' + uuid4().hex[:24]) if scoped else None
                    seq = await self.gateway.queue_intent('face',
                        {'expr':args['expr'], **({'token':face_token} if scoped else {})}, robot_id=robot)
                    if scoped:job['face_token'] = face_token
                    self.record(job, 'face_submitted', {'expression':args['expr'],
                                'scope':'program' if scoped else 'normal_face_selection',
                                'generation_index':generation_index, 'action_index':index}, sequence=seq)
                    # Face admission is asynchronous; it is no longer the
                    # operation being submitted, nor a verified body target.
                    job['completed_operation_index'] = index
                    job['current_action'] = None
                    continue
                before = obs
                receipt_start = len(job['receipts'])
                if name == 'hold':
                    await asyncio.sleep(args['seconds'])
                elif name in motion_names:
                    if prepared is not None:
                        prepared_index, compiling = prepared
                        assert prepared_index == index
                        compiled = await compiling
                        prepared = None
                    else:
                        compiled = await self._compile_action(action,obs,planned,supplied)
                    frames = compiled.get('frames',[])
                    start, home, moving = (compiled[key] for key in ('start','home','moving'))
                    planned = compiled['end']
                    self.record(job,'motion_prepared',{'action_index':index,'start':start,
                                'target':planned,'speed_deg_s':([compiled['curve']['speed_deg_s']]
                                    if 'curve' in compiled else [f[0]/100 for f in frames]),
                                **({'control':'trajectory','duration_s':compiled['curve']['times'][-1],
                                    'checkpoints_s':compiled['curve']['checkpoints']} if 'curve' in compiled else {})})
                    # Prepare one successor during playback. Faces and
                    # authored holds retain their order; native motions
                    # establish a new measured starting pose.
                    for following in range(index+1,len(program)):
                        next_action = program[following]
                        if next_action['name'] in motion_names:
                            prepared = (following,asyncio.create_task(
                                self._compile_action(next_action,obs,dict(planned),supplied)))
                            break
                        if next_action['name'] not in ('face','hold'):
                            break
                    progress = {'completed_frames':0,'submitted_frames':None,'sequence':None}
                    job['packet_progress'] = progress
                    for packet in packets(frames):
                        progress['submitted_frames'] = packet
                        seq = await self.gateway.queue_motion_plan(packet,end='hold',control='targets',robot_id=robot)
                        progress['sequence'] = seq
                        await self._receipt(job,seq,obs['epoch'])
                        progress['completed_frames'] += len(packet)
                    if 'curve' in compiled:
                        snapshot=(await self.gateway.status_snapshot())['robots'][robot]
                        if 'motion_curves_v1' not in snapshot.get('features',[]):
                            raise ValueError('Robot firmware does not advertise motion_curves_v1 for generated trajectories')
                        upload_id=uuid4().hex
                        upload=asyncio.create_task(self.transport.request(robot,'trajectory',{'id':upload_id,'curve':compiled['curve']}))
                        completed=False
                        try:
                            uploaded=await asyncio.shield(upload)
                            if uploaded.get('prepared') is not True:
                                raise ValueError('Robot did not acknowledge the generated trajectory upload')
                            progress['trajectory_id']=upload_id
                            seq=await self.gateway.queue_motion_plan([],end='hold',control='trajectory',
                                trajectory_token=upload_id,robot_id=robot)
                            progress['sequence']=seq
                            await self._receipt(job,seq,obs['epoch'])
                            completed=True
                        finally:
                            # This only releases unused upload data. Physical
                            # cancellation/replacement retains its existing
                            # gateway command and body-output ownership.
                            if not completed:
                                cleanup=asyncio.create_task(self._discard_trajectory(job,upload_id,upload))
                                self.trajectory_cleanups.add(cleanup)
                                cleanup.add_done_callback(self.trajectory_cleanups.discard)
                elif name == 'stand':
                    planned = None
                    seq = await self.gateway.queue_intent('stand',{},robot_id=robot)
                    await self._receipt(job,seq,obs['epoch'])
                elif name == 'gait':
                    planned = None
                    for intent in gait_intents(args):
                        seq = await self.gateway.queue_intent('walk',intent,robot_id=robot)
                        await self._receipt(job,seq,obs['epoch'])
                else:
                    planned = None
                    if name == 'release':
                        seq = await self.gateway.estop(robot_id=robot,detach=True)
                    elif name == 'stop':
                        seq = await self.gateway.estop(robot_id=robot)
                    else:
                        raise ValueError('Unknown program operation '+name)
                    await self._receipt(job,seq,obs['epoch'],acknowledgement=True)
                # Terminal receipt (or the authored hold) completes this
                # operation. A fresh observation may await a reconnect; do not
                # describe the already-finished operation as interrupted then.
                job['completed_operation_index'] = index
                job['completed_action'] = copy.deepcopy(action)
                job['current_action'] = None
                job['packet_progress'] = None
                obs = await self.connected_observation(job)
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
                after = sample(obs)
                # Correlate the actual body results with this operation.
                # A completed packet is evidence, not proof that the whole
                # requested gesture or recovery is finished.
                after['receipts'] = copy.deepcopy(job['receipts'][receipt_start:])
                job['history'].extend([initial,after])
                self.record(job, 'operation_completed', {'generation_index':generation_index,
                            'action_index':index, 'before':initial, 'after':after})
            job['state']='completed_section' if job.get('start_index',0) else 'completed'
        except asyncio.CancelledError:
            if job.get('abort_error'):
                job.update(state='error', error=job['abort_error'])
                if job.get('abort_evidence') is not None:
                    job['error_evidence'] = copy.deepcopy(job['abort_evidence'])
                self.record(job, 'job_error', {'error':job['abort_error'], 'evidence':job.get('abort_evidence')})
            elif job.get('cancellation_requested') and job['state'] == 'executing' and self.active.get(robot) == job['id']:
                try:
                    if job.get('pause_requested'):job['pause_stop_attempted'] = True
                    await self._stop_job(job,job.get('pause_detach',False))
                except Exception as error:
                    job.update(state='error', error=str(error))
                else:
                    job['state']='superseded'
            else:
                job['state']='superseded'
        except Exception as error:
            message=str(error)
            job.update(state='error',error=message)
            if getattr(error,'evidence',None) is not None:
                job['error_evidence'] = copy.deepcopy(error.evidence)
            self.record(job, 'job_error', {'error':message, 'evidence':getattr(error,'evidence',None)})
        finally:
            if prepared is not None:
                prepared[1].cancel()
                await asyncio.gather(prepared[1],return_exceptions=True)
            if job.get('face_token'):
                try:
                    seq = await self.gateway.queue_intent('face',
                        {'release':True, 'token':job['face_token'], 'if_token':job['face_token']}, robot_id=robot)
                    self.record(job, 'face_released', {'token':job['face_token']}, sequence=seq)
                except Exception as error:
                    self.record(job, 'face_release_error', {'error':str(error)})
            self.record(job, 'job_finished', {'state':job['state'], 'error':job.get('error'),
                        'execute':job['execute'], 'current_action':job.get('current_action'),
                        'completed_action':job.get('completed_action'),
                        'packet_progress':job.get('packet_progress'),
                        'start_index':job.get('start_index',0),'pause_state':job.get('pause_state')})
            OWNER.reset(token)
            self.tasks.pop(job['id'],None)

    async def _receipt(self,job,seq,epoch,*,acknowledgement=False):
        receipt=await self.gateway.wait_terminal(seq,robot_id=job['robot_id'],epoch=epoch,timeout=None)
        job['receipts'].append(receipt)
        self.record(job, 'command_receipt', receipt, sequence=seq)
        # Stop/Release end on the gateway's terminal acknowledgement. Target
        # execution still requires done; accepting its admission is not arrival.
        if receipt.get('t')!='done' and not (acknowledgement and receipt.get('t')=='ack'):
            raise RuntimeError('Body reported '+str(receipt))

    async def event(self,event):
        robot=event.get('robot_id')
        if event.get('t')=='connection':
            changed = self.connection_changes.pop(robot, None)
            if changed is not None:
                changed.set()
            if robot and event.get('status') in ('connected', None) and event.get('state') in ('online', None):
                sync = asyncio.create_task(self._sync_neural_pose_servo_feedback(robot, epoch=event.get('epoch')))
                self.feedback_syncs.add(sync)
                sync.add_done_callback(self.feedback_syncs.discard)
            return
        if event.get('name')!='body_event':
            return
        data=event.get('data') or {}
        kind=data.get('kind')
        if kind=='servo_stall' and data.get('outputs_released'):
            snapshot=(await self.gateway.status_snapshot())['robots'].get(robot)
            if snapshot is not None and event.get('epoch',snapshot['epoch'])!=snapshot['epoch']:
                return
            active_id=self.active.get(robot)
            active_job=self.jobs.get(active_id) if active_id else None
            if active_job is None:
                return
            if event.get('epoch') is not None and active_job.get('epoch')!=event.get('epoch'):
                return
            sequence=data.get('command_sequence')
            if (
                sequence
                and active_job.get('last_sequence') is not None
                and sequence!=active_job.get('last_sequence')
                and (snapshot is None or sequence!=snapshot.get('body_command_sequence'))
            ):
                return
            active_task=self.tasks.get(active_id)
            self.active.pop(robot,None)
            if active_task is None or active_task.done():
                return
            joints=[item.get('name') or str(item.get('id')) for item in (data.get('joints') or []) if isinstance(item,dict)]
            detail=f" ({', '.join(joints)})" if joints else ""
            active_job['abort_error']=f"servo_stall: body released servo outputs{detail}"
            active_job['abort_evidence']=copy.deepcopy(data)
            last_seq=active_job.get('last_sequence')
            if type(last_seq) is int and not any(r.get('seq')==last_seq for r in active_job.get('receipts',[])):
                active_job['receipts'].append({
                    't':'cancelled',
                    'seq':last_seq,
                    'code':'servo_stall',
                    'outputs_released':True,
                })
            active_task.cancel()

    async def command(self,command):
        robot=command.get('robot_id'); previous=self.active.get(robot)
        motion = command.get('t') in ('stop','motion_plan','servo','mode','state') or (
            command.get('t')=='intent' and command.get('name') not in ('face','say')) or (
            command.get('t')=='calibration' and command.get('op')!='get')
        if motion and previous and OWNER.get() == previous:
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
        await asyncio.gather(*list(self.feedback_syncs),return_exceptions=True)
        await asyncio.gather(*list(self.trajectory_cleanups),return_exceptions=True)
        if self.compiler_pool is not None:
            self.compiler_pool.shutdown(wait=False,cancel_futures=True)
        await self.transport.close()

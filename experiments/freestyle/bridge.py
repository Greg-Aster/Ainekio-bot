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
from .compact_wire import latest_correction, joint_progress
from .recordings import read_records
from .observations import feedback_geometry
from .program import JOINTS, calibrated_positions, compile_motion, packets, gait_intents

OWNER = contextvars.ContextVar('freestyle_job', default=None)


def recovery_has_motion_owner(snapshot):
    """Recovery cannot undo a later Stop, Release or manual control handoff.

    Use the gateway's existing command ownership, not a separate stop latch.
    An explicit new motion changes that owner through ordinary admission.
    """
    command = snapshot.get('body_command') or {}
    return command.get('t') not in ('stop', 'state', 'mode', 'calibration')


class Bridge:
    def __init__(self, gateway, transport, generate=async_remote_generate, *, recorder=None, settings_path=None,
                 compiler=None):
        self.gateway, self.transport, self.generate = gateway, transport, generate
        self.settings, self.jobs, self.tasks, self.active = {}, {}, {}, {}
        self.connection_changes = {}
        self.compiler = compiler or self._compile_motion
        self.compiler_pool = None
        self.trajectory_cleanups = set()
        self.recorder = recorder
        self.settings_path = Path(settings_path) if settings_path else None
        if self.settings_path and self.settings_path.exists():
            self.settings = json.loads(self.settings_path.read_text())
        gateway.subscribe_events(self.event)
        gateway.subscribe_commands(self.command)
        gateway.freestyle_recovery_state = self.recovery_state

    def recovery_state(self, robot, epoch):
        """Read actual recovery jobs, including generation and active execution."""
        return any(job['robot_id']==robot and job['epoch']==epoch and job['execute']
                   and job.get('event') and not job.get('cancellation_requested')
                   and identifier in self.tasks and not self.tasks[identifier].done()
                   for identifier,job in self.jobs.items())

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

    async def review(self, robot, job_id, outcome, note='', corrected_request=None, corrected_program=None,
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
        if corrected_program is not None:
            value['training_status'] = 'awaiting_physical_trial'
        identifier = self.record(job, 'review', value)
        if identifier is not None:
            await asyncio.to_thread(self.recorder.flush)
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

    async def corrections(self, robot):
        if self.recorder is None:
            raise ValueError('Motion recording is not configured')
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
                    if r['payload'].get('corrected_program') is not None and key in requested]
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

    async def submit(self, robot, request, execute=False, event=None, *, job_id=None, on_start=None,
                     program=None, source=None, start_index=0):
        setting = self.settings.get(robot, {'endpoint':'http://127.0.0.1:8794', 'recover_events':False})
        previous = self.active.get(robot)
        pending = [job for identifier,job in self.jobs.items() if identifier in self.tasks
                   and job['robot_id']==robot and 'recovery_owner' in job]
        history = []
        motion_goal = None
        if event and previous:
            prior = self.jobs[previous]
            context = {'program_state':prior['state']}
            if prior.get('current_action') is not None:
                role = 'failed_action' if prior['state']=='error' else 'interrupted_action'
                context[role] = copy.deepcopy(prior['current_action'])
                if prior.get('error_evidence') is not None:
                    context['error_evidence'] = copy.deepcopy(prior['error_evidence'])
            if prior.get('error') is not None:
                context['error'] = prior['error']
            if prior.get('completed_action') is not None:
                context['completed_action'] = copy.deepcopy(prior['completed_action'])
            if 'remaining_program' in prior:
                context['remaining_program'] = copy.deepcopy(prior['remaining_program'])
            motion_goal = copy.deepcopy(prior.get('motion_goal'))
            if motion_goal is None:
                motion_goal = {'request':prior['request'], **{key:copy.deepcopy(context[key])
                    for key in ('program_state','interrupted_action','failed_action',
                                'completed_action','remaining_program') if key in context}}
            history.append(context)
            effect = latest_correction(prior.get('history'))
            if effect:
                history[-1]['last_correction'] = effect
            progress = joint_progress([*prior.get('history', []),
                {'joints':prior.get('observation', {}).get('joints')}], event.get('data', event))
            if progress:
                history[-1]['joint_progress'] = progress
        job_id = job_id or uuid4().hex
        epoch=(await self.gateway.status_snapshot())['robots'][robot]['epoch']
        async with AsyncExitStack() as admission:
            if on_start is not None:
                await admission.enter_async_context(on_start(job_id))
            if execute:
                for pending_job in pending:
                    self.tasks[pending_job['id']].cancel()
            if execute and not event and previous and previous in self.tasks:
                self.tasks[previous].cancel()
            job = {'id':job_id,'robot_id':robot,'request':request,'execute':execute,'event':event,
                   'epoch':epoch,'state':'generating','history':history,'programs':[],'receipts':[]}
            if motion_goal is not None:
                job['motion_goal'] = motion_goal
            if program is not None:
                job.update(supplied_program=copy.deepcopy(program), source=copy.deepcopy(source),start_index=start_index)
            if execute and event:
                job['recovery_owner'] = previous
            self.jobs[job_id] = job
            self.record(job, 'job_started', job)
            if execute and not event:
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
            ('id', 'robot_id', 'epoch', 'request', 'state', 'receipts', 'observation', 'error', 'last_sequence',
             'operation_index','completed_operation_index','pause_state','pause_cursor','start_index') if key in job})

    async def cancel(self, job_id):
        job = self.jobs[job_id]
        task = self.tasks.get(job_id)
        if task is not None and not job.get('cancellation_requested') and (self.active.get(job['robot_id']) == job_id or 'recovery_owner' in job):
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

    def _admit_recovery(self, job, sequence):
        if 'recovery_owner' not in job:
            return
        robot=job['robot_id'];previous=job['recovery_owner']
        if self.active.get(robot)!=previous:
            raise ValueError('Recovery was replaced before command admission')
        if previous in self.tasks:
            self.tasks[previous].cancel()
        self.active[robot]=job['id']
        del job['recovery_owner']
        self.record(job,'recovery_admitted',{'previous_job_id':previous,
                    'observation':job['observation']},sequence=sequence)

    async def _run(self, job, setting):
        token = OWNER.set(job['id'])
        robot = job['robot_id']
        sequence_options = {'on_sequence':lambda seq:self._admit_recovery(job,seq)} if job['event'] else {}
        prepared = None
        motion_names = ('move','pose','oscillate','feet','body')
        try:
            original_event = job['event']
            event = ({'type':original_event['data']['kind'], **original_event['data'],
                      'event_id':original_event.get('event_id'),'epoch':original_event.get('epoch')}
                     if original_event and original_event.get('name')=='body_event' else original_event)
            obs = await self.connected_observation(job)
            if job['event'] and not recovery_has_motion_owner({'body_command':obs.get('action')}):
                job['state']='superseded'
                return
            expected = (job.get('event') or {}).get('data', {}).get('command_sequence')
            if ('recovery_owner' in job and expected is not None
                and (obs.get('action') or {}).get('seq') != expected):
                job['state']='superseded'
                return
            job['observation'] = obs
            if 'initial_observation' not in job:
                job['initial_observation'] = copy.deepcopy(obs)
            request = {'request':job['request'],'observation':obs,'event':event,'history':job['history']}
            if 'motion_goal' in job:
                request['motion_goal'] = copy.deepcopy(job['motion_goal'])
            generation_index = len(job['programs'])
            supplied = 'supplied_program' in job and not job['programs']
            self.record(job, 'correction_trial_requested' if supplied else 'generation_requested',
                        {'generation_index':generation_index, 'execute':job['execute'],
                         'request':request, **({'source':job['source']} if supplied else {})})
            if supplied:
                result = {'program':copy.deepcopy(job['supplied_program']), 'source':job['source']}
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
            planned = None
            planning_epoch = obs['epoch']
            for index in range(job.get('start_index',0),len(program)):
                action = program[index]
                name, args = action['name'], action['arguments']
                if 'recovery_owner' in job and name in (
                        'move','pose','oscillate','feet','body','gait','stand','stop','release'):
                    obs = await self.connected_observation(job)
                    job['observation'] = obs
                    planned = None
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
                        seq = await self.gateway.queue_motion_plan(packet,end='hold',control='targets',robot_id=robot,**sequence_options)
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
                                trajectory_token=upload_id,robot_id=robot,**sequence_options)
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
                    seq = await self.gateway.queue_intent('stand',{},robot_id=robot,**sequence_options)
                    await self._receipt(job,seq,obs['epoch'])
                elif name == 'gait':
                    planned = None
                    for intent in gait_intents(args):
                        seq = await self.gateway.queue_intent('walk',intent,robot_id=robot,**sequence_options)
                        await self._receipt(job,seq,obs['epoch'])
                else:
                    planned = None
                    if name == 'release':
                        seq = await self.gateway.estop(robot_id=robot,detach=True,**sequence_options)
                    elif name == 'stop':
                        seq = await self.gateway.estop(robot_id=robot,**sequence_options)
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
            if job.get('cancellation_requested') and job['state'] == 'executing' and self.active.get(robot) == job['id']:
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
        if receipt.get('position_verified') is False:
            error = RuntimeError('Body did not verify the requested motion target: '+str(receipt))
            error.evidence = copy.deepcopy(receipt)
            raise error

    async def event(self,event):
        robot=event.get('robot_id'); setting=self.settings.get(robot,{})
        if event.get('t')=='connection':
            changed = self.connection_changes.pop(robot, None)
            if changed is not None:
                changed.set()
            return
        if not setting.get('recover_events') or event.get('name')!='body_event':
            return
        data=event.get('data',{})
        if data.get('outputs_released'):
            return
        if data.get('kind') not in ('servo_stall','servo_feedback_fault','tipped','rapid_movement','slip'):
            return
        snapshot=(await self.gateway.status_snapshot())['robots'].get(robot)
        if snapshot is None or event.get('epoch',snapshot['epoch'])!=snapshot['epoch']:
            return
        if not recovery_has_motion_owner(snapshot):
            return
        sequence=data.get('command_sequence')
        if sequence and sequence!=snapshot.get('body_command_sequence'):
            # A delayed receipt for a replaced command cannot supersede its
            # replacement (particularly an operator's Stop).
            return
        previous=self.jobs.get(self.active.get(robot),{})
        request=previous.get('request') or 'Recover from the reported body event using the available observations.'
        await self.submit(robot,request,True,{**event,'data':{**data,
            'command_sequence':data.get('command_sequence',snapshot.get('body_command_sequence'))}})

    async def command(self,command):
        robot=command.get('robot_id'); previous=self.active.get(robot)
        motion = command.get('t') in ('stop','motion_plan','servo','mode','state') or (
            command.get('t')=='intent' and command.get('name') not in ('face','say')) or (
            command.get('t')=='calibration' and command.get('op')!='get')
        if motion and previous and OWNER.get() == previous:
            self.jobs[previous]['last_sequence'] = command.get('seq')
            return
        if motion:
            for identifier,pending in self.jobs.items():
                if pending['robot_id']==robot and 'recovery_owner' in pending and identifier in self.tasks:
                    self.tasks[identifier].cancel()
            task=self.tasks.get(previous)
            if task:task.cancel()
            self.active.pop(robot,None)

    async def close(self):
        if self.gateway.freestyle_recovery_state == self.recovery_state:
            self.gateway.freestyle_recovery_state = None
        self.gateway.unsubscribe_events(self.event)
        self.gateway.unsubscribe_commands(self.command)
        tasks=list(self.tasks.values())
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        await asyncio.gather(*list(self.trajectory_cleanups),return_exceptions=True)
        if self.compiler_pool is not None:
            self.compiler_pool.shutdown(wait=False,cancel_futures=True)
        await self.transport.close()

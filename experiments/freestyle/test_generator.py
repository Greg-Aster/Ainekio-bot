import json
import asyncio
from contextlib import suppress
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch

from experiments.freestyle.generator import Generator, IncompleteProgram, async_remote_generate, create_app, argument_schema
from experiments.freestyle.observations import enrich, feedback_geometry
from experiments.freestyle.recordings import Recorder, read_records
import math


class GeneratorTests(unittest.TestCase):
    def test_motion_contract_has_no_model_reentry_operation(self):
        from experiments.freestyle.motion_space import TOOLS, INSTRUCTIONS, COMPLETION_INSTRUCTIONS
        from experiments.freestyle.compact_wire import ProgramEncoding
        from jsonschema import Draft202012Validator
        encoding = ProgramEncoding(TOOLS)
        self.assertNotIn('reassess', encoding.tools)
        self.assertNotIn('reassess', (INSTRUCTIONS + COMPLETION_INSTRUCTIONS).lower())
        validator = Draft202012Validator(encoding.schema(argument_schema))
        self.assertFalse(validator.is_valid([['reassess']]))
        self.assertTrue(validator.is_valid([['move', 9, 20, 'current', 50, 0]]))

    def test_sync_requests_resolve_adapter_paths_and_report_missing_adapters(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'system.txt').write_text('test system');(root/'tools.json').write_text('[]')
            adapter=root/'freestyle.gguf';adapter.write_bytes(b'adapter');payloads=[];loaded=[{'id':4,'path':str(adapter),'scale':0}]
            generator=Generator('http://host/v1','shared',root,adapter_file=adapter)
            class Reply:
                def __init__(self,value):self.value=value
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def read(self):return json.dumps(self.value).encode()
            def native(req,*args,**kwargs):
                self.assertNotIn('timeout',kwargs)
                if isinstance(req,str):
                    self.assertEqual(req,'http://host/lora-adapters?model=shared')
                    return Reply(loaded)
                payloads.append(json.loads(req.data))
                return Reply({'choices':[{'finish_reason':'stop','message':{'content':'[]'}}]})
            with patch('urllib.request.urlopen',native):
                generator.generate('first');loaded[0]['id']=9;generator.generate('second')
                loaded.clear()
                with self.assertRaisesRegex(ValueError,'Freestyle LoRA is not loaded'):generator.generate('missing')
            self.assertEqual([p['lora'] for p in payloads],[[{'id':4,'scale':1}],[{'id':9,'scale':1}]])
            self.assertEqual(len(payloads),2)
            self.assertEqual(generator._payload('base request')['lora'],[])

    def test_joint_target_schemas_preserve_matching_pairs_in_named_and_compact_calls(self):
        from jsonschema import Draft202012Validator
        from experiments.freestyle.motion_space import TOOLS
        from experiments.freestyle.compact_wire import ProgramEncoding
        from experiments.freestyle.runtime import JOINTS
        for name,field,minimum in [('pose','angles_deg',0)]:
            tool=next(t for t in TOOLS if t['name']==name)
            named=Draft202012Validator(argument_schema(tool))
            encoding=ProgramEncoding([tool]);compact_validator=Draft202012Validator(encoding.schema(argument_schema))
            for count in range(minimum,13):
                args={'joints':list(JOINTS[:count]),'angles_deg':[-216.3]*count,'reference':'absolute','speed_pct':50,'taper_deg':0}
                self.assertTrue(named.is_valid(args),(name,count))
                self.assertTrue(compact_validator.is_valid(encoding.encode([{'name':name,'arguments':args}])))
                for different in range(13):
                    if different==count:continue
                    invalid=dict(args);invalid[field]=args[field][:different] if different<count else args[field]+[args[field][0] if args[field] else 0]*(different-count)
                    self.assertFalse(named.is_valid(invalid),(name,count,different))
                    self.assertFalse(compact_validator.is_valid(encoding.encode([{'name':name,'arguments':invalid}])),(name,count,different))

    def test_feedback_domain_uses_each_servo_mapping_and_never_invents_missing_calibration(self):
        joint={'id':7,'calibrated':True,'points':[{'pulse_us':500},{'pulse_us':1650},{'pulse_us':2800}]}
        mapping={'home_cd':-3087,'home_us':2740,'us_per_degree':100/9,'invert':True}
        value=feedback_geometry(mapping,joint,{'arrival_tolerance_us':100})
        self.assertAlmostEqual(value['feedback_range_deg'][0],-36.27)
        self.assertAlmostEqual(value['feedback_range_deg'][1],170.73)
        self.assertNotIn('feedback_usable',value)
        self.assertNotIn('feedback_range_deg',feedback_geometry(mapping,{**joint,'calibrated':False},{}))
        self.assertNotIn('feedback_range_deg',feedback_geometry(mapping,{**joint,'points':[None,None,None]},{}))

    def test_spatial_generation_schema_pairs_every_named_leg_with_its_offset(self):
        from jsonschema import Draft202012Validator
        for name,offset in [('feet','offsets_mm'),('body','foot_offsets_mm')]:
            tool={'name':name,'parameters':{'type':'object','properties':{
                'legs':{'type':'array','items':{'type':'string'}},
                offset:{'type':'array','items':{'type':'array','items':{'type':'number'}}}},
                'required':['legs',offset],'additionalProperties':False}}
            validator=Draft202012Validator(argument_schema(tool))
            for count in range(5):
                for offsets in range(5):
                    value={'legs':['front_left']*count,offset:[[0,0,30]]*offsets}
                    self.assertEqual(validator.is_valid(value),count==offsets)
            self.assertNotIn('maxItems',tool['parameters']['properties']['legs'])

    def test_incomplete_generation_retains_diagnostic_evidence_without_returning_a_program(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'system.txt').write_text('test system');(root/'tools.json').write_text('[]')
            generator=Generator('http://model/v1','test',root)
            class Reply:
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def read(self):return json.dumps({'choices':[{'finish_reason':'length','message':{'content':'[{"name":'}}],
                                                  'usage':{'completion_tokens':7}}).encode()
            with patch('urllib.request.urlopen',return_value=Reply()):
                with self.assertRaises(IncompleteProgram) as raised:generator.generate('wave')
            evidence=raised.exception.evidence
            self.assertEqual(evidence['content'],'[{"name":')
            self.assertEqual(evidence['usage']['completion_tokens'],7)
            self.assertNotIn('program',evidence)

    def test_orientation_and_tracking_arithmetic_adds_facts_without_policy(self):
        q=[math.cos(math.pi/8),math.sin(math.pi/8),0,0]
        original={'imu':{'orientation_wxyz':q},'joints':{'front_right_shoulder':{'model_deg':12,'commanded_model_deg':20}}}
        result=enrich(original)
        self.assertAlmostEqual(result['imu']['derived_orientation']['tilt_degrees'],45)
        self.assertAlmostEqual(result['imu']['derived_orientation']['roll_degrees'],45)
        self.assertEqual(result['joints']['front_right_shoulder']['tracking_error_deg'],8)
        self.assertEqual(original['imu'],{'orientation_wxyz':q})
        samples=enrich([{'imu':{'orientation_wxyz':q}},{'imu':{'orientation_wxyz':[1,0,0,0]}}])
        self.assertAlmostEqual(samples[1]['imu']['derived_orientation']['tilt_change_degrees'],-45)

    def test_context_and_history_preserved_without_runtime_token_or_time_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'system.txt').write_text('test system')
            (root/'tools.json').write_text('[]')
            (root/'model.gguf').write_bytes(b'test model identity')
            generator=Generator('http://model/v1','test',root,root/'model.gguf')
            history=[{'sample':i} for i in range(100)]
            payload={}
            class Reply:
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def read(self):return json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'[]'}}]}).encode()
            def request(req,*args,**kwargs):
                self.assertFalse(args)
                self.assertNotIn('timeout',kwargs)
                payload.update(json.loads(req.data))
                return Reply()
            with patch('urllib.request.urlopen',request):
                result=generator.generate('recover',{'imu':{'available':False}}, {'type':'servo_stall'}, history)
            self.assertEqual(result['program'],[])
            import hashlib
            self.assertEqual(result['generator']['configured_model_sha256'],hashlib.sha256(b'test model identity').hexdigest())
            self.assertNotIn('max_tokens',payload)
            self.assertFalse(payload['chat_template_kwargs']['enable_thinking'])
            message=json.loads(payload['messages'][1]['content'])
            self.assertEqual(message['history'],history)
            self.assertEqual(message['observation']['imu'],{'available':False})

    def test_model_receives_measured_error_and_configured_tolerance_without_claiming_arrival(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'system.txt').write_text('test');(root/'tools.json').write_text('[]')
            generator=Generator('http://model/v1','test',root)
            joints={'a':{'model_deg':13,'commanded_model_deg':20,'arrival_tolerance_deg':9,'feedback_usable':False},
                    'b':{'model_deg':10,'commanded_model_deg':20,'arrival_tolerance_deg':9},
                    'c':{'model_deg':10,'commanded_model_deg':None}}
            payload=generator._payload('recover',{'joints':joints,'imu':{'orientation_wxyz':[1,0,0,0]}},
                {'type':'servo_stall'},[{'receipts':[{'t':'done','seq':7,'position_verified':True}]}])
            query=json.loads(payload['messages'][-1]['content'])
            values=query['observation']['joints']
            self.assertEqual(values['a']['tracking_error_deg'],7)
            self.assertTrue(values['a']['within_arrival_tolerance'])
            self.assertFalse(values['a']['feedback_usable'])
            self.assertFalse(values['b']['within_arrival_tolerance'])
            self.assertNotIn('within_arrival_tolerance',values['c'])
            self.assertEqual(query['history'][0]['receipts'][0]['seq'],7)
            self.assertEqual(query['observation']['imu']['derived_orientation']['tilt_degrees'],0)
            serialized=generator._payload(json.dumps({'request':'recover','observation':{'joints':joints}}))
            self.assertEqual(json.loads(serialized['messages'][-1]['content'])['observation']['joints'],values)
            columns=enrich({'model_deg':[1,None,3],'commanded_model_deg':[2,2,None]})
            self.assertEqual(columns['tracking_error_deg'],[1,None,None])
            self.assertEqual(query['observation']['shaft_tracking']['outside_arrival_tolerance'],['b'])
            self.assertEqual(query['observation']['shaft_tracking']['unusable_feedback'],['a'])
            self.assertEqual(query['observation']['shaft_tracking']['unknown_arrival_tolerance'],['c'])
            self.assertEqual(list(query)[-1],'observation')
            self.assertNotIn('within_arrival_tolerance',enrich({'model_deg':None,
                'commanded_model_deg':10,'within_arrival_tolerance':True}))


class AsyncGeneratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_base_uses_request_local_lora_and_refreshes_native_ids(self):
        import hashlib
        requests=[];next_id=iter((7,23));pending=asyncio.Event();release=asyncio.Event()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'system.txt').write_text('test system');(root/'tools.json').write_text('[]')
            adapter=root/'freestyle.gguf';adapter.write_bytes(b'freestyle adapter')
            async def native(reader,writer):
                header=await reader.readuntil(b'\r\n\r\n');method,target,_=header.split(b'\r\n',1)[0].decode().split()
                length=int(next(line.split(b':',1)[1] for line in header.split(b'\r\n') if line.startswith(b'Content-Length:')))
                body=await reader.readexactly(length);payload=json.loads(body) if body else None
                requests.append((method,target,payload))
                if method=='GET':
                    result=[{'id':0,'path':'/other/intent.gguf','scale':0},
                            {'id':next(next_id),'path':str(adapter),'scale':0}]
                else:
                    if len([r for r in requests if r[0]=='POST'])==1:
                        pending.set();await release.wait()
                    result={'choices':[{'finish_reason':'stop','message':{'content':'[]'}}]}
                encoded=json.dumps(result).encode();writer.write((f'HTTP/1.1 200 OK\r\nContent-Length: {len(encoded)}\r\nConnection: close\r\n\r\n').encode()+encoded)
                await writer.drain();writer.close()
            server=await asyncio.start_server(native,'127.0.0.1',0)
            async with server:
                port=server.sockets[0].getsockname()[1]
                generator=Generator(f'http://127.0.0.1:{port}/v1','qwen3.5:0.8b',root,adapter_file=adapter)
                first=asyncio.create_task(generator.async_generate('first'))
                try:
                    await asyncio.wait_for(pending.wait(),3)
                    second=await asyncio.wait_for(generator.async_generate('second'),3)
                    self.assertFalse(first.done(),'LoRA selection must not serialize independent inference requests')
                    self.assertEqual(second['program'],[])
                    release.set();await first
                finally:
                    release.set();first.cancel()
                    with suppress(asyncio.CancelledError):await first
            self.assertEqual([target for method,target,_ in requests if method=='GET'],
                             ['/lora-adapters?model=qwen3.5%3A0.8b']*2)
            calls=[payload for method,target,payload in requests if method=='POST']
            self.assertEqual([p['lora'] for p in calls],[[{'id':7,'scale':1}],[{'id':23,'scale':1}]])
            self.assertTrue(all(p['model']=='qwen3.5:0.8b' for p in calls))
            self.assertTrue(all(target=='/v1/chat/completions' for method,target,_ in requests if method=='POST'))
            self.assertEqual(generator.identity['configured_adapter_sha256'],hashlib.sha256(b'freestyle adapter').hexdigest())

    async def test_big_brother_uses_named_contract_and_preserves_context(self):
        from experiments.freestyle.big_brother import command_json
        from experiments.freestyle.runtime import JOINTS
        from experiments.freestyle.program import compile_motion
        from jsonschema import validate
        operation={'name':'oscillate','arguments':{'joint':JOINTS[9],
                   'amplitude_deg':10,'cycles':2,'speed_pct':50,'taper_deg':0}}
        program=[operation]
        class Client:
            profile='test'
            async def complete(self, payload):
                self.payload=payload
                code=('import sys,json; p=json.loads(sys.stdin.readline()); '
                      'print(json.dumps({"model":"gpt-sol-test","choices":[{"finish_reason":"stop",'
                      '"message":{"content":json.dumps(p["program"])}}]}))')
                return await command_json([sys.executable,'-c',code],{'program':program})
        client=Client()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'system.txt').write_text('existing instructions')
            from experiments.freestyle.motion_space import TOOLS
            from experiments.freestyle.compact_wire import FORMAT
            (root/'tools.json').write_text(json.dumps(TOOLS))
            (root/'wire.json').write_text(json.dumps({'format':FORMAT}))
            generator=Generator('','configured-model',root,big_brother=client)
            observation={'joints':{j:{'model_deg':10,'commanded_model_deg':10,'home_deg':10} for j in JOINTS},
                         'joint_speed_limit_deg_s':90}
            history=[{'evidence':'unchanged'}]
            result=await generator.async_generate('two oscillations',observation,history=history)
            self.assertEqual(result['program'],program)
            self.assertEqual(result['generator']['model_alias'],'gpt-sol-test')
            self.assertEqual(result['generator']['provider'],'big-brother')
            self.assertEqual(client.payload['messages'][0]['content'],'existing instructions')
            query=json.loads(client.payload['messages'][1]['content'])
            self.assertEqual(query['history'],history)
            self.assertIn(JOINTS[9],query['observation']['joints'])
            self.assertFalse(client.payload['chat_template_kwargs']['enable_thinking'])
            validate(program,generator.schema)
            compiled=compile_motion(operation,observation)
            self.assertEqual(len(compiled['frames']),8)
            self.assertEqual(compiled['end'][JOINTS[9]],10)

    async def test_big_brother_remote_failure_is_reported(self):
        from experiments.freestyle.big_brother import command_json
        with self.assertRaisesRegex(ValueError,'Big Brother SSH exited 7: unavailable'):
            await command_json([sys.executable,'-c',
                'import sys;sys.stdin.readline();sys.stderr.write("unavailable");sys.exit(7)'],{})

    async def test_big_brother_cancellation_reaps_transport(self):
        from experiments.freestyle.big_brother import command_json
        import os
        with tempfile.TemporaryDirectory() as directory:
            pidfile=Path(directory)/'pid'
            code=('import sys,os,signal,pathlib;sys.stdin.readline();'
                  'pathlib.Path(sys.argv[1]).write_text(str(os.getpid()));signal.pause()')
            task=asyncio.create_task(command_json([sys.executable,'-c',code,str(pidfile)],{}))
            try:
                async def ready():
                    while not pidfile.exists():await asyncio.sleep(.01)
                await asyncio.wait_for(ready(),3)
                pid=int(pidfile.read_text())
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):await task
                with self.assertRaises(ProcessLookupError):os.kill(pid,0)
            finally:
                if not task.done():task.cancel()
                await asyncio.gather(task,return_exceptions=True)

    async def test_service_propagates_cancellation_and_admits_concurrent_full_history(self):
        from aiohttp import web
        arrived=asyncio.Event();closed=asyncio.Event();received=[]

        async def model_request(reader,writer):
            try:
                header=await reader.readuntil(b'\r\n\r\n')
                length=int(next(line.split(b':',1)[1] for line in header.split(b'\r\n')
                                if line.startswith(b'Content-Length:')))
                payload=json.loads(await reader.readexactly(length))
                received.append(payload)
                query=payload['messages'][1]['content']
                if query=='pending':
                    arrived.set()
                    self.assertEqual(await reader.read(),b'')
                    closed.set()
                    return
                body=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'[]'}}]}).encode()
                writer.write((f'HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\n'
                              'Connection: close\r\n\r\n').encode()+body)
                await writer.drain()
            finally:
                writer.close()

        model_server=await asyncio.start_server(model_request,'127.0.0.1',0)
        async with model_server:
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                (root/'system.txt').write_text('test system')
                (root/'tools.json').write_text('[]')
                model_port=model_server.sockets[0].getsockname()[1]
                generator=Generator(f'http://127.0.0.1:{model_port}/v1','test',root)
                evidence_path=root/'inference.sqlite'
                runner=web.AppRunner(create_app(generator, Recorder(evidence_path)))
                await runner.setup()
                site=web.TCPSite(runner,'127.0.0.1',0)
                await site.start()
                endpoint=f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}'
                pending=asyncio.create_task(async_remote_generate(endpoint,{'request':'pending'}))
                try:
                    await asyncio.wait_for(arrived.wait(),3)
                    history=[{'note':'x'*1100000}]
                    motion_goal={'request':'Wave hello.'}
                    result=await asyncio.wait_for(async_remote_generate(endpoint,{
                        'request':'new','history':history,'motion_goal':motion_goal},job_id='gateway-job-42'),3)
                    self.assertEqual(result['program'],[])
                    self.assertFalse(closed.is_set())
                    self.assertFalse(pending.done())
                    query=json.loads(received[1]['messages'][1]['content'])
                    self.assertEqual(query['history'],history)
                    self.assertEqual(query['motion_goal'],motion_goal)
                    self.assertNotIn('max_tokens',received[1])
                    pending.cancel()
                    with suppress(asyncio.CancelledError):await pending
                    await asyncio.wait_for(closed.wait(),3)
                finally:
                    pending.cancel()
                    with suppress(asyncio.CancelledError):await pending
                    await runner.cleanup()
                recorded=list(read_records(evidence_path))
                self.assertEqual(sum(r['kind']=='inference_requested' for r in recorded),2)
                self.assertEqual(sum(r['kind']=='inference_cancelled' for r in recorded),1)
                completed=next(r for r in recorded if r['kind']=='inference_completed')
                self.assertEqual(completed['job_id'],'gateway-job-42')
                self.assertEqual(result['inference_id'],'gateway-job-42')
                full=next(r for r in recorded if r['kind']=='inference_requested' and
                          r['payload']['request']['request']=='new')
                self.assertEqual(full['payload']['request']['history'],history)
                self.assertEqual(full['job_id'],'gateway-job-42')

    async def test_eof_during_async_json_raises_connection_error_not_index_error(self):
        async def drop(reader,writer):
            writer.close()
            await writer.wait_closed()
        server=await asyncio.start_server(drop,'127.0.0.1',0)
        async with server:
            port=server.sockets[0].getsockname()[1]
            with self.assertRaises(ConnectionError):
                await async_remote_generate(f'http://127.0.0.1:{port}',{'request':'wave'})

    async def test_cancel_closes_pending_inference_connection(self):
        arrived=asyncio.Event();closed=asyncio.Event()
        async def handle(reader,writer):
            header=await reader.readuntil(b'\r\n\r\n')
            length=int(next(line.split(b':',1)[1] for line in header.split(b'\r\n') if line.startswith(b'Content-Length:')))
            await reader.readexactly(length);arrived.set()
            self.assertEqual(await reader.read(),b'')
            writer.close();closed.set()
        server=await asyncio.start_server(handle,'127.0.0.1',0)
        async with server:
            port=server.sockets[0].getsockname()[1]
            task=asyncio.create_task(async_remote_generate(f'http://127.0.0.1:{port}',{'request':'wave'}))
            await asyncio.wait_for(arrived.wait(),2)
            task.cancel()
            with suppress(asyncio.CancelledError):await task
            await asyncio.wait_for(closed.wait(),2)

    def test_compact_wire_plain_request_serializes_as_json_request_object(self):
        from experiments.freestyle.compact_wire import FORMAT
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'system.txt').write_text('')
            (root/'tools.json').write_text('[]')
            (root/'wire.json').write_text(json.dumps({'format':FORMAT}))
            generator=Generator('http://host/v1','shared',root)
            payload=generator._payload('Raise your right hand.')
            self.assertEqual(payload['messages'][-1]['content'],'{"request":"Raise your right hand."}')

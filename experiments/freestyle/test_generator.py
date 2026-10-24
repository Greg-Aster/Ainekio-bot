import json
import asyncio
from contextlib import suppress
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments.freestyle.generator import Generator, IncompleteProgram, async_remote_generate, create_app, argument_schema
from experiments.freestyle.observations import enrich
from experiments.freestyle.recordings import Recorder, read_records
import math


class GeneratorTests(unittest.TestCase):
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


class AsyncGeneratorTests(unittest.IsolatedAsyncioTestCase):
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
                    result=await asyncio.wait_for(async_remote_generate(endpoint,{
                        'request':'new','history':history}),3)
                    self.assertEqual(result['program'],[])
                    self.assertFalse(closed.is_set())
                    self.assertFalse(pending.done())
                    query=json.loads(received[1]['messages'][1]['content'])
                    self.assertEqual(query['history'],history)
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
                self.assertEqual(completed['job_id'],result['inference_id'])
                full=next(r for r in recorded if r['kind']=='inference_requested' and
                          r['payload']['request']['request']=='new')
                self.assertEqual(full['payload']['request']['history'],history)

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

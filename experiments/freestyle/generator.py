"""Standalone compact-program client/server usable by either host application."""
import argparse
import asyncio
import copy
import json
import hashlib
import time
import urllib.request
from uuid import uuid4
from urllib.parse import urlsplit, quote
from pathlib import Path

from .runtime import compact, JOINTS
from .observations import enrich
from .compact_wire import FORMAT, LEGACY_FORMAT, ProgramEncoding, model_query


def argument_schema(tool):
    """Express the executor's existing corresponding-target requirements."""
    parameters = tool['parameters']
    paired = {'feet':('legs','offsets_mm',0,4),
              'body':('legs','foot_offsets_mm',0,4),
              'pose':('joints','angles_deg',0,len(JOINTS))}.get(tool['name'])
    if paired is None:
        return parameters
    names,targets,minimum,maximum=paired
    variants = []
    for count in range(minimum,maximum+1):
        variant = copy.deepcopy(parameters)
        for name in (names,targets):
            variant['properties'][name].update(minItems=count, maxItems=count)
        variants.append(variant)
    return {'oneOf':variants}


class IncompleteProgram(ValueError):
    def __init__(self, result, elapsed_s, identity):
        choice=result['choices'][0]
        super().__init__('Model returned an incomplete program: '+str(choice['finish_reason']))
        self.evidence={'finish_reason':choice['finish_reason'],
                       'content':choice['message'].get('content'),
                       'usage':result.get('usage'),'elapsed_s':elapsed_s,'generator':identity}


class Generator:
    def __init__(self, endpoint, model, contract, model_file=None, adapter_file=None, *, big_brother=None):
        self.endpoint, self.model = endpoint.rstrip('/'), model
        self.adapter_file = str(Path(adapter_file).resolve()) if adapter_file is not None else None
        self.big_brother = big_brother
        self.system = (Path(contract)/'system.txt').read_text()
        tools = json.loads((Path(contract)/'tools.json').read_text())
        wire_path = Path(contract)/'wire.json'
        self.encoding = None
        if wire_path.exists() and big_brother is None:
            wire = json.loads(wire_path.read_text())
            if wire['format'] not in (FORMAT, LEGACY_FORMAT):
                raise ValueError('Unknown Freestyle model representation: '+wire['format'])
            self.encoding = ProgramEncoding(tools)
        self.identity = {'model_alias':model,
                         'contract_sha256':hashlib.sha256(self.system.encode()).hexdigest(),
                         'tools_sha256':hashlib.sha256((Path(contract)/'tools.json').read_bytes()).hexdigest()}
        if model_file is not None:
            with Path(model_file).open('rb') as stream:
                self.identity['configured_model_sha256']=hashlib.file_digest(stream,'sha256').hexdigest()
        if self.adapter_file is not None:
            with Path(self.adapter_file).open('rb') as stream:
                self.identity['configured_adapter_sha256']=hashlib.file_digest(stream,'sha256').hexdigest()
            self.identity['adapter_path']=self.adapter_file
        self.schema = {'type':'array','items':{'oneOf':[
            {'type':'object','additionalProperties':False,'required':['name','arguments'],
             'properties':{'name':{'type':'string','const':t['name']},'arguments':argument_schema(t)}}
            for t in tools]}}
        if big_brother is not None:
            # General models use the existing named contract, not the numeric
            # serialization learned by the local fine-tune.
            for variant, tool in zip(self.schema['items']['oneOf'], tools):
                variant['description'] = tool.get('description', '')
            self.identity.update(provider='big-brother', profile=big_brother.profile,
                                 format='named-motion-calls')
        if self.encoding:
            self.schema = self.encoding.schema(argument_schema)
            self.identity['format'] = wire['format']
            self.identity['encoding_sha256'] = hashlib.sha256(Path(__file__).with_name('compact_wire.py').read_bytes()).hexdigest()
        self.identity['response_schema_sha256']=hashlib.sha256(compact(self.schema).encode()).hexdigest()

    def _payload(self, request, observation=None, event=None, history=None):
        query = request if observation is None and event is None and not history else {
            'request':request,'event':event,'observation':observation,'history':history or []}
        if isinstance(query,str):
            try:
                decoded=json.loads(query)
            except ValueError:
                pass
            else:
                if isinstance(decoded,dict):query=decoded
        if self.encoding:
            query = model_query(query, self.encoding)
        else:
            query = enrich(query)
        if not isinstance(query, str):
            query = compact(query)
        return {'model':self.model,'lora':[],'temperature':0,'chat_template_kwargs':{'enable_thinking':False},
                   'messages':([{'role':'system','content':self.system}] if self.system else [])+[
                       {'role':'user','content':query}],
                   'response_format':{'type':'json_schema','json_schema':{
                       'name':'motion_program','strict':True,'schema':self.schema}}}

    def _adapter_endpoint(self):
        return self.endpoint.removesuffix('/v1')+'/lora-adapters?model='+quote(self.model,safe='')

    def _request_lora(self, loaded):
        adapter=next((item for item in loaded if item['path']==self.adapter_file),None)
        if adapter is None:
            raise ValueError('Freestyle LoRA is not loaded: '+self.adapter_file)
        return [{'id':adapter['id'],'scale':1}]

    def generate(self, request, observation=None, event=None, history=None):
        if self.big_brother is not None:
            return asyncio.run(self.async_generate(request, observation, event, history))
        payload = self._payload(request, observation, event, history)
        started = time.perf_counter()
        if self.adapter_file is not None:
            with urllib.request.urlopen(self._adapter_endpoint()) as response:
                payload['lora']=self._request_lora(json.load(response))
        req = urllib.request.Request(self.endpoint+'/chat/completions',data=compact(payload).encode(),
                                     headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req) as response:
            result = json.load(response)
        return self._program(result, started)

    async def async_generate(self, request, observation=None, event=None, history=None):
        payload = self._payload(request, observation, event, history)
        started = time.perf_counter()
        if self.big_brother is not None:
            result = await self.big_brother.complete(payload)
        else:
            if self.adapter_file is not None:
                payload['lora']=self._request_lora(await _async_json(self._adapter_endpoint(),method='GET'))
            result = await _async_json(self.endpoint+'/chat/completions', payload)
        return self._program(result, started)

    def _program(self, result, started):
        choice = result['choices'][0]
        if choice['finish_reason'] != 'stop':
            raise IncompleteProgram(result,time.perf_counter()-started,self.identity)
        try:
            program = json.loads(choice['message']['content'])
            if self.encoding:
                program = self.encoding.decode(program)
        except (ValueError, TypeError) as error:
            error.evidence = {'response':result, 'generator':self.identity,
                              'elapsed_s':time.perf_counter()-started}
            raise
        identity = dict(self.identity)
        if self.big_brother is not None:
            identity['model_alias'] = result['model']
        return {'program':program,
                'elapsed_s':time.perf_counter()-started, 'usage':result.get('usage'),
                'generator':identity}


def remote_generate(endpoint, request):
    req = urllib.request.Request(endpoint.rstrip('/')+'/generate',data=compact(request).encode(),
                                 headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req) as response:
        return json.load(response)


async def async_remote_generate(endpoint, request):
    """Cancellable HTTP to this service and its downstream model request."""
    return await _async_json(endpoint.rstrip('/')+'/generate', request)


async def _async_json(endpoint, request=None, method='POST'):
    url=urlsplit(endpoint)
    reader,writer=await asyncio.open_connection(url.hostname,url.port or (443 if url.scheme=='https' else 80),
                                                 ssl=url.scheme=='https')
    try:
        body=compact(request).encode() if method=='POST' else b''
        target=(url.path or '/')+('?' + url.query if url.query else '')
        writer.write((f'{method} {target} HTTP/1.1\r\nHost: {url.netloc}\r\n'
                      f'Content-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n').encode()+body)
        await writer.drain()
        status=int((await reader.readline()).split()[1])
        headers={}
        while True:
            line=await reader.readline()
            if line in (b'\r\n',b''):break
            name,value=line.decode().split(':',1);headers[name.lower()]=value.strip()
        if headers.get('transfer-encoding','').lower()=='chunked':
            chunks=[]
            while True:
                size=int((await reader.readline()).split(b';',1)[0],16)
                if not size:break
                chunks.append(await reader.readexactly(size));await reader.readexactly(2)
            data=b''.join(chunks)
        elif 'content-length' in headers:
            data=await reader.readexactly(int(headers['content-length']))
        else:
            data=await reader.read()
        result=json.loads(data)
        if status!=200:
            error=ValueError(result.get('error',f'Freestyle HTTP {status}'))
            error.evidence=result.get('evidence')
            raise error
        return result
    finally:
        writer.close()


def create_app(generator, recorder=None):
    from aiohttp import web

    async def generate(request):
        request_id = uuid4().hex
        def record(kind, payload):
            if recorder:
                recorder.record(kind, payload, job_id=request_id)
        try:
            payload = await request.json()
            record('inference_requested', {'request':payload, 'generator':generator.identity})
            result = await generator.async_generate(**payload)
            result['inference_id'] = request_id
            record('inference_completed', result)
            return web.json_response(result)
        except asyncio.CancelledError:
            record('inference_cancelled', {'generator':generator.identity})
            raise
        except Exception as error:
            failure = {'error':str(error), 'evidence':getattr(error,'evidence',None),
                       'inference_id':request_id}
            record('inference_failed', failure)
            return web.json_response(failure, status=400)

    async def health(request):
        return web.json_response({'service':'freestyle','model':generator.model,
                                  'robot_transport':False,'generator':generator.identity,
                                  'recording':recorder.status() if recorder else {'enabled':False}})

    # A replaced request has no recipient. Cancel its inference connection too,
    # instead of leaving a blocking worker to occupy a model slot. Full request
    # history remains intact; no application byte, token or elapsed-time cap.
    app = web.Application(client_max_size=0, handler_args={'handler_cancellation':True})
    app.router.add_post('/generate',generate)
    app.router.add_get('/health',health)
    if recorder:
        async def cleanup(app):
            await asyncio.to_thread(recorder.close)
        app.on_cleanup.append(cleanup)
    return app


def serve(generator, host, port, recorder=None):
    from aiohttp import web
    web.run_app(create_app(generator, recorder), host=host, port=port,
                handler_cancellation=True, print=None)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    provider = p.add_mutually_exclusive_group(required=True)
    provider.add_argument('--endpoint')
    provider.add_argument('--big-brother-ssh', help='SSH target of the installed MetaHuman Big Brother owner')
    p.add_argument('--metahuman-root', help='MetaHuman checkout on the SSH host')
    p.add_argument('--profile', help='Existing MetaHuman profile used for Big Brother configuration')
    p.add_argument('--ssh-option', action='append', default=[], help='SSH option, e.g. HostName=10.77.42.1')
    p.add_argument('--model',required=True)
    p.add_argument('--contract',type=Path,required=True)
    p.add_argument('--model-file',type=Path,help='Configured artifact identity for saved trial provenance')
    p.add_argument('--adapter-file',type=Path,help='LoRA selected only for each Freestyle inference request')
    p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8794)
    p.add_argument('--recordings',type=Path,help='Local SQLite store for requests and generated outputs')
    a=p.parse_args()
    big_brother = None
    if a.big_brother_ssh:
        if not a.metahuman_root or not a.profile:
            p.error('--big-brother-ssh requires --metahuman-root and --profile')
        from .big_brother import BigBrotherClient
        big_brother = BigBrotherClient(a.big_brother_ssh, a.metahuman_root, a.profile,
                                      [part for option in a.ssh_option for part in ('-o',option)])
    from .recordings import Recorder
    serve(Generator(a.endpoint or '',a.model,a.contract,a.model_file,a.adapter_file,
                    big_brother=big_brother),a.host,a.port,
          Recorder(a.recordings) if a.recordings else None)

"""Host audio outputs and explicit Bluetooth pairing; no robot authority."""
from __future__ import annotations

import asyncio
import json
import re
from uuid import uuid4

from gateway.server.service import GatewayError


class HostAudio:
    def __init__(self):
        self.scanner = None
        self.scan_reader = None
        self.jobs = {}
        self.tasks = set()

    async def run(self, *args):
        process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
                                                     stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await process.communicate()
        except asyncio.CancelledError:
            if process.returncode is None:
                process.terminate()
            await process.communicate()
            raise
        text = stdout.decode(errors='replace')
        if process.returncode or 'Failed to ' in text:
            raise GatewayError((stderr.decode(errors='replace').strip() or text.strip() or
                                f'{args[0]} exited {process.returncode}'))
        return text

    async def outputs(self):
        outputs = json.loads(await self.run('pactl', '--format=json', 'list', 'sinks'))
        return [{'name':s['name'], 'description':s.get('description',s['name']),
                 'bluetooth':s.get('properties',{}).get('device.api') == 'bluez5' or s['name'].startswith('bluez_')}
                for s in outputs]

    async def devices(self):
        text = await self.run('bluetoothctl', 'devices')
        return [{'address':m[1], 'name':m[2]} for line in text.splitlines()
                if (m := re.match(r'^Device ([0-9A-Fa-f:]{17}) (.+)$', line))]

    async def snapshot(self):
        # A host without Bluetooth still has usable computer audio outputs.
        results = await asyncio.gather(self.outputs(), self.devices(), return_exceptions=True)
        return {'outputs':results[0] if not isinstance(results[0],Exception) else [],
                'devices':results[1] if not isinstance(results[1],Exception) else [],
                'errors':[str(v) for v in results if isinstance(v,Exception)],
                'scanning':self.scanner is not None and self.scanner.returncode is None,
                'jobs':list(self.jobs.values())}

    async def submit(self, operation, address=None):
        identifier = uuid4().hex
        job = dict(id=identifier, operation=operation, address=address, state='running')
        self.jobs[identifier] = job
        async def work():
            try:
                await self.operate(operation,address)
                job['state'] = 'completed'
            except (OSError,ValueError,GatewayError) as error:
                job.update(state='failed',error=str(error))
        task = asyncio.create_task(work())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return {'job':identifier}

    async def operate(self, operation, address=None):
        if operation == 'scan-start':
            if self.scanner is None or self.scanner.returncode is not None:
                self.scanner = await asyncio.create_subprocess_exec('bluetoothctl', '--agent', 'NoInputNoOutput',
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
                self.scanner.stdin.write(b'scan on\n')
                # Discovery remains active until the user stops it or this host
                # exits. Drain CLI output asynchronously; no robot task waits.
                async def drain(process):
                    while await process.stdout.read(4096):
                        pass
                    await process.wait()
                self.scan_reader = asyncio.create_task(drain(self.scanner))
        elif operation == 'scan-stop':
            await self.stop_scan()
        elif operation in {'pair','connect','disconnect'}:
            if not isinstance(address,str) or not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}',address):
                raise ValueError('Select a Bluetooth device address')
            await self.run('bluetoothctl', '--agent', 'NoInputNoOutput', operation, address)
        else:
            raise ValueError('Unknown host audio operation')
        return await self.snapshot()

    async def stop_scan(self):
        process, reader = self.scanner, self.scan_reader
        self.scanner = self.scan_reader = None
        if process is not None and process.returncode is None:
            process.terminate()
            await process.wait()
        if reader is not None:
            await reader

    async def close(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.stop_scan()

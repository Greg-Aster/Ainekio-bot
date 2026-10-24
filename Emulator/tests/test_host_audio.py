import asyncio
import json
import unittest
from unittest.mock import AsyncMock

from gateway.host_audio import HostAudio
from gateway.server.service import GatewayError


class HostAudioTests(unittest.IsolatedAsyncioTestCase):
    async def test_outputs_keep_stable_device_names_and_bluetooth_identity(self):
        audio=HostAudio()
        audio.run=AsyncMock(return_value=json.dumps([
            {'name':'bluez_output.AA.1','description':'Speaker','properties':{'device.api':'bluez5'}},
            {'name':'alsa_output.local','description':'Built-in','properties':{}}]))
        self.assertEqual(await audio.outputs(),[
            {'name':'bluez_output.AA.1','description':'Speaker','bluetooth':True},
            {'name':'alsa_output.local','description':'Built-in','bluetooth':False}])

    async def test_pairing_job_returns_before_bluetooth_finishes_and_reports_failure(self):
        audio=HostAudio();started=asyncio.Event();release=asyncio.Event()
        async def operation(*args):
            started.set();await release.wait();raise GatewayError('Speaker declined pairing')
        audio.operate=operation
        result=await audio.submit('pair','AA:BB:CC:DD:EE:FF')
        await started.wait()
        self.assertEqual(audio.jobs[result['job']]['state'],'running')
        release.set();await asyncio.gather(*audio.tasks)
        self.assertEqual(audio.jobs[result['job']]['state'],'failed')
        self.assertIn('declined',audio.jobs[result['job']]['error'])
        await audio.close()

    async def test_pairing_uses_arguments_not_a_shell(self):
        audio=HostAudio();audio.run=AsyncMock(return_value='Pairing successful')
        audio.snapshot=AsyncMock(return_value={})
        await audio.operate('pair','AA:BB:CC:DD:EE:FF')
        audio.run.assert_awaited_once_with('bluetoothctl','--agent','NoInputNoOutput','pair','AA:BB:CC:DD:EE:FF')
        with self.assertRaises(ValueError):await audio.operate('pair','--anything')

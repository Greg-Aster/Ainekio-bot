"""Freestyle inference through MetaHuman's existing Big Brother provider over SSH."""
import asyncio
import json
import shlex


# Execute inside the installed MetaHuman checkout. Its provider owns authentication,
# model selection, terminal visibility, and cancellation; this is only transport.
REMOTE_CLIENT = r'''
import { createInterface } from 'node:readline';
import { withUserContext } from './packages/core/src/context.ts';
import { getUserByUsername } from './packages/core/src/users.ts';
import { callProvider } from './packages/core/src/providers/bridge.ts';
console.log = (...args) => console.error(...args);
const abort = new AbortController();
const input = createInterface({input: process.stdin, crlfDelay: Infinity});
input.on('close', () => abort.abort());
process.on('SIGHUP', () => abort.abort());
process.on('SIGTERM', () => abort.abort());
input.once('line', async line => {
  try {
    const {profile, payload} = JSON.parse(line);
    const user = getUserByUsername(profile);
    if (!user) throw new Error('MetaHuman profile does not exist: ' + profile);
    const result = await withUserContext({userId:user.id, username:user.username, role:user.role},
      () => callProvider('big-brother', payload.messages, {
        jsonSchema:payload.response_format.json_schema.schema,
        enableThinking:payload.chat_template_kwargs.enable_thinking,
        signal:abort.signal,
      }));
    process.stdout.write(JSON.stringify({model:result.model, provider:result.provider,
      choices:[{finish_reason:'stop', message:{content:result.content}}], usage:result.usage}) + '\n',
      () => process.exit(0));
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(1);
  }
});
'''


async def command_json(command, payload):
    process = await asyncio.create_subprocess_exec(*command, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    readers = asyncio.gather(process.stdout.read(), process.stderr.read())
    try:
        # Keep stdin open until completion. Losing the SSH client closes it on the
        # remote side and aborts the request in the existing terminal owner.
        process.stdin.write((json.dumps(payload, ensure_ascii=False, allow_nan=False)+'\n').encode())
        await process.stdin.drain()
        stdout, stderr = await readers
        code = await process.wait()
        if code:
            raise ValueError(f'Big Brother SSH exited {code}: {stderr.decode().strip()}')
        return json.loads(stdout)
    finally:
        if process.returncode is None:
            process.terminate()
        await process.wait()
        if not readers.done():
            readers.cancel()
        await asyncio.gather(readers, return_exceptions=True)


class BigBrotherClient:
    def __init__(self, target, root, profile, ssh_options=()):
        self.profile = profile
        remote = ('cd '+shlex.quote(root)+' && set -a && . ./.env && set +a && '
                  'exec pnpm exec tsx -e '+shlex.quote(REMOTE_CLIENT))
        self.command = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                        *ssh_options, target, remote]

    async def complete(self, payload):
        return await command_json(self.command, {'profile':self.profile, 'payload':payload})

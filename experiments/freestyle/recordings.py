"""Append-only local motion evidence and reviewed training corrections.

Recording runs on a writer thread. It does not delay, stop, or change motion.
Raw failed programs remain evidence; only explicit reviews create targets.
"""
import argparse
import copy
import hashlib
import json
import logging
import os
from pathlib import Path
import queue
import sqlite3
import threading
import time
from uuid import uuid4
import zlib

LOG = logging.getLogger(__name__)
COMMANDS = {'intent', 'motion_plan', 'servo', 'stop', 'mode', 'state', 'motion_speed', 'calibration'}
EVENTS = {'imu', 'servo_feedback', 'status', 'connection', 'command_result', 'event'}


class Recorder:
    def __init__(self, path):
        self.path = Path(path)
        self.pending = queue.Queue()
        self.written = 0
        self.error = None
        self.failed = 0
        self.closed = False
        self.active = {}
        self.thread = threading.Thread(target=self._write, name='freestyle-recordings', daemon=True)
        self.thread.start()

    def record(self, kind, payload, *, robot_id=None, epoch=None, sequence=None, job_id=None):
        identifier = uuid4().hex
        if self.closed:
            return None
        self.pending.put((identifier, time.time_ns(), time.monotonic_ns(), kind,
                          robot_id, epoch, sequence, job_id, copy.deepcopy(payload)))
        return identifier

    def command(self, command):
        if command.get('t') not in COMMANDS:
            return
        robot = command.get('robot_id')
        motion = command.get('t') in {'motion_plan', 'servo', 'stop', 'mode', 'state'} or (
            command.get('t') == 'intent' and command.get('name') not in {'face', 'say'}) or (
            command.get('t') == 'calibration' and command.get('op') != 'get')
        if motion:
            self.active[robot] = (command.get('epoch'), command.get('seq'))
        self.record('body_command', command, robot_id=robot,
                    epoch=command.get('epoch'), sequence=command.get('seq'))

    def event(self, event):
        if event.get('t') not in EVENTS:
            return
        robot = event.get('robot_id')
        current = self.active.get(robot)
        if event.get('t') in {'imu', 'servo_feedback', 'status'} and (
                current is None or event.get('epoch') != current[0]):
            return
        sequence = event.get('seq')
        if sequence is None and current:
            sequence = current[1]
        self.record('body_event', event, robot_id=robot, epoch=event.get('epoch'), sequence=sequence)
        if current and event.get('t') == 'command_result' and (event.get('epoch'), sequence) == current:
            result = event.get('result', {})
            if result.get('t') in {'done', 'error', 'replaced'}:
                self.active.pop(robot, None)
        if event.get('t') == 'connection' and event.get('status') == 'disconnected':
            if current and event.get('epoch') == current[0]:
                self.active.pop(robot, None)

    def diagnostic(self, diagnostic):
        if diagnostic.get('event') == 'command_result' and diagnostic.get('command_type') in COMMANDS:
            self.event({'t': 'command_result', 'robot_id': diagnostic.get('robot_id'),
                        'epoch': diagnostic.get('epoch'), 'seq': diagnostic.get('seq'),
                        'result': diagnostic})

    def status(self):
        return {'enabled': True, 'path': str(self.path), 'written': self.written,
                'pending': self.pending.qsize(), 'error': self.error, 'failed': self.failed,
                'physical_success_inferred': False,
                'sampling': 'Gateway telemetry as received during command activity; per-operation observations also retained.'}

    def _write(self):
        connection = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=30)
            os.chmod(self.path, 0o600)
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute('CREATE TABLE IF NOT EXISTS evidence '
                '(id TEXT PRIMARY KEY, time_ns INTEGER, monotonic_ns INTEGER, kind TEXT, '
                'robot_id TEXT, epoch INTEGER, sequence INTEGER, job_id TEXT, payload BLOB)')
            connection.execute('CREATE INDEX IF NOT EXISTS evidence_job ON evidence(job_id,time_ns)')
            connection.execute('CREATE INDEX IF NOT EXISTS evidence_body ON evidence(robot_id,epoch,sequence,time_ns)')
            connection.commit()
            while True:
                item = self.pending.get()
                if item is None:
                    self.pending.task_done()
                    break
                batch = [item]
                # Consume already queued evidence, without waiting for a batch.
                while len(batch) < 128 and not self.pending.empty():
                    next_item = self.pending.get_nowait()
                    if next_item is None:
                        self.pending.task_done()
                        self.pending.put(None)
                        break
                    batch.append(next_item)
                try:
                    records = [(*row[:-1], zlib.compress(json.dumps(row[-1], separators=(',', ':')).encode()))
                               for row in batch]
                    connection.executemany('INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?,?)', records)
                    connection.commit()
                    self.written += len(batch)
                except Exception as error:
                    connection.rollback()
                    self.error = str(error)
                    self.failed += len(batch)
                    LOG.exception('Freestyle evidence write failed; robot execution continues')
                finally:
                    for _ in batch:
                        self.pending.task_done()
        except Exception as error:
            self.error = str(error)
            LOG.exception('Freestyle evidence store unavailable; robot execution continues')
            # Expose the error, without leaving an idle consumer accumulating data.
            self.closed = True
            while not self.pending.empty():
                self.pending.get_nowait()
                self.pending.task_done()
        finally:
            if connection is not None:
                connection.close()

    def close(self):
        if self.thread.is_alive():
            self.closed = True
            self.pending.put(None)
            self.thread.join()


def read_records(path, job_id=None, *, kinds=None):
    connection = sqlite3.connect(f'file:{Path(path).resolve()}?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        clauses, params = [], []
        if job_id:
            clauses.append('job_id=?')
            params.append(job_id)
        if kinds is not None:
            kinds = tuple(kinds)
            clauses.append('kind IN (' + ','.join('?' for _ in kinds) + ')')
            params.extend(kinds)
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        for row in connection.execute('SELECT * FROM evidence' + where + ' ORDER BY time_ns,id', params):
            result = dict(row)
            result['payload'] = json.loads(zlib.decompress(result['payload']))
            yield result
    finally:
        connection.close()


def corrected_rows(path):
    """Export only an explicitly reviewed generation or corrected program.

An unsuccessful attempt without a correction cannot become a positive label.
The latest review of a generation supersedes earlier reviews in this export.
"""
    records = list(read_records(path))
    requests, results, reviews, endings = {}, {}, {}, {}
    for item in records:
        value = item['payload']
        key = (item['job_id'], value.get('generation_index', 0))
        if item['kind'] in ('generation_requested', 'correction_trial_requested'): requests[key] = item
        elif item['kind'] in ('generation_completed', 'correction_trial_program'): results[key] = item
        elif item['kind'] == 'review': reviews[key] = item
        elif item['kind'] == 'job_finished': endings[item['job_id']] = value
    for key, review in reviews.items():
        value = review['payload']
        if value.get('training_status') == 'awaiting_physical_trial':
            continue
        request = requests.get(key)
        if request is None:
            continue
        result = results.get(key)
        program = value.get('corrected_program')
        measured = False
        if program is None and value.get('outcome') == 'success' and result is not None:
            ending = endings.get(key[0], {})
            if not request['payload'].get('execute') or ending.get('state') != 'completed':
                continue
            program = result['payload']['result']['program']
            measured = True
        if program is None:
            continue
        query = copy.deepcopy(request['payload']['request'])
        query.pop('_recording', None)
        if value.get('corrected_request'):
            query['request'] = value['corrected_request']
        signature = hashlib.sha256(json.dumps([query, program, review['id']], sort_keys=True).encode()).hexdigest()
        yield {'id': signature[:16], 'family': 'reviewed_robot_motion',
               'query': json.dumps(query, separators=(',', ':')), 'answers': program,
               'source_id': 'robot-review:' + review['id'], 'source_hash': signature,
               'synthetic': not measured, 'physical_qualification': measured,
               'qualification_basis': 'operator_reported_success' if measured else 'proposed_correction_not_executed',
               'job_id': key[0], 'generation_index': key[1], 'review': value,
               'request_evidence_id': request['id'], 'review_evidence_id': review['id'],
               **({'execution_source':request['payload']['source']} if 'source' in request['payload'] else {})}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('export', 'corrections'))
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--job-id')
    args = parser.parse_args()
    rows = (corrected_rows(args.database) if args.operation == 'corrections'
            else read_records(args.database, args.job_id))
    with args.output.open('x') as stream:
        for row in rows:
            stream.write(json.dumps(row, separators=(',', ':')) + '\n')

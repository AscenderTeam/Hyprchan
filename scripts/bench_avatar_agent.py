#!/usr/bin/env python3
"""Synthetic real-Codex test: create/run an emote and measure greeting latency.

No mic, camera, desktop image, personal memory, search or notifications are used.
Scripts generated here run with normal account permissions, like GUI emotes.
"""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from hyprchan.core.animations.avatar3d.emotes import EmoteLibrary, EmoteRunner

parser = argparse.ArgumentParser()
parser.add_argument('--output', required=True)
args = parser.parse_args()
output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
report = {'syntheticOnly': True, 'turns': [], 'emotes': [], 'scripts': []}
with tempfile.TemporaryDirectory(prefix='hyprchan-avatar-test-') as temporary:
    library = EmoteLibrary(Path(temporary)/'emotes'); runner = EmoteRunner()
    env = {**os.environ, 'HYPRCHAN_MEMORY':'off', 'HYPRCHAN_NOTIFICATIONS':'off', 'HYPRCHAN_WEB_SEARCH':'disabled',
           'XDG_DATA_HOME': temporary}
    env.pop('HYPRCHAN_CODEX_EFFORT', None)
    events = queue.Queue()
    log = output.with_suffix('.stderr.log').open('w')
    bridge = subprocess.Popen(['node', str(ROOT/'scripts/desktop_codex_bridge.mjs')], cwd=ROOT, env=env,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True, bufsize=1)
    def read():
        for line in bridge.stdout:
            try: events.put(json.loads(line))
            except ValueError: events.put({'type':'error','message':'Invalid bridge output'})
    threading.Thread(target=read, daemon=True).start()
    def send(value):
        bridge.stdin.write(json.dumps(value)+'\n'); bridge.stdin.flush()
    requests = [
        'hi', 'Привет!',
        'Create and immediately play a new reusable Python emote with id hoodie_huff and title Hoodie huff. '
        'Make it four seconds: anticipate, puff your cheeks with eyes open and mouth closed, tilt your head, then soften into a smile. '
        'Use mouth_close=1 and smile=0 during the puff, then release mouth_close when smiling. '
        'Only animate. Do not touch files yourself or use network/system commands. Use emote_create with play_now true. '
        'Keep your final in-character response to one short sentence.',
        'hi',
    ]
    deadline = time.monotonic()+120
    try:
        while time.monotonic() < deadline:
            event = events.get(timeout=30)
            kind = event['type']
            if kind == 'ready':
                report['ready'] = event
                for setting in ('memory','notification','audio','vision'):
                    send({'type':setting+'_mode','active':False})
                send({'type':'emote_state','mode':'3d','items':library.list()})
                send({'type':'chat','id':0,'text':requests[0]})
            elif kind == 'emote_request':
                a = event['arguments']
                try:
                    if event['tool'] == 'emote_create':
                        result = library.save(a['id'],a['title'],a['description'],a['python_code'])
                        report['scripts'].append({'id':a['id'],'code':a['python_code']})
                        (output.parent/(a['id']+'.py')).write_text(a['python_code'])
                        if a['play_now']: result.update(runner.play(library.path(a['id']),30))
                        result['saved'] = True
                    else: result = runner.play(library.path(a['id']),a['seconds'])
                    report['emotes'].append({'tool':event['tool'],'result':result})
                    send({'type':'emote_result','requestId':event['requestId'],'result':result})
                    send({'type':'emote_state','mode':'3d','items':library.list()})
                except Exception as error:
                    report['emotes'].append({'error':str(error)})
                    send({'type':'emote_result','requestId':event['requestId'],'error':str(error)})
            elif kind == 'done':
                report['turns'].append(event)
                print(json.dumps({k:event.get(k) for k in ('id','status','effort','firstTextMs','lastTextMs','toolCalls','reasoningTokens')}),flush=True)
                index = event['id']+1
                if index == len(requests): break
                send({'type':'chat','id':index,'text':requests[index]})
            elif kind == 'error': raise RuntimeError(event['message'])
        else: raise TimeoutError('Model/emote test timed out')
        until = time.monotonic()+10
        while time.monotonic() < until:
            _, event = runner.poll()
            if event and event['state'] in {'finished','error'}:
                report['animation'] = event; break
            time.sleep(.05)
        assert report['emotes'] and report['animation']['state']=='finished', report
        assert len(report['turns']) == len(requests)
    finally:
        runner.stop()
        send({'type':'quit'})
        try: bridge.wait(timeout=5)
        except subprocess.TimeoutExpired: bridge.kill(); bridge.wait()
        bridge.stdin.close(); bridge.stdout.close(); log.close()
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')

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
parser.add_argument('--spatial', action='store_true', help='Generate and measure face-relative wave/peace gestures')
args = parser.parse_args()
output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
report = {'syntheticOnly': True, 'turns': [], 'emotes': [], 'scripts': [], 'animations': [], 'spatial': {}}
if args.spatial:
    from hyprchan.core.animations.avatar3d.model import AvatarModel
    rig=AvatarModel()
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
    if args.spatial:
        requests = ['hi',
            'Create and play a new four-second emote called face_wave_test. Wave your open right hand directly '
            'in front of your face, not beside it. Raise it smoothly, wave, then lower it. '
            'Only animate; do not access files, network or system commands. Use emote_create and one short final sentence.',
            'Create and play a different four-second emote called face_peace_test. Hold a real two-finger peace '
            'sign directly in front of your face while tilting your head, then lower your hand. '
            'Only animate; do not access files, network or system commands. Use emote_create and one short final sentence.',
            'hi']
    deadline = time.monotonic()+120
    next_index = None
    running_id = None
    try:
        while time.monotonic() < deadline:
            try: event = events.get(timeout=.03)
            except queue.Empty: event = {}
            kind = event.get('type')
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
                        if a['play_now']:
                            result.update(runner.play(library.path(a['id']),30))
                            running_id=a['id']
                        result['saved'] = True
                    else:
                        result = runner.play(library.path(a['id']),a['seconds'])
                        running_id=a['id']
                    report['emotes'].append({'tool':event['tool'],'result':result})
                    send({'type':'emote_result','requestId':event['requestId'],'result':result})
                    send({'type':'emote_state','mode':'3d','items':library.list()})
                except Exception as error:
                    report['emotes'].append({'error':str(error)})
                    send({'type':'emote_result','requestId':event['requestId'],'error':str(error)})
            elif kind == 'done':
                report['turns'].append(event)
                print(json.dumps({k:event.get(k) for k in ('id','status','effort','firstTextMs','lastTextMs','toolCalls','reasoningTokens')}),flush=True)
                next_index = event['id']+1
            elif kind == 'error': raise RuntimeError(event['message'])
            frame, animation = runner.poll()
            if args.spatial and frame and frame.get('hands'):
                rig.posed({'leftUpperArm':[0,0,-72],'rightUpperArm':[0,0,72],**frame['bones']},hands=frame['hands'])
                item = report['spatial'].setdefault(running_id,{'frames':0,'heldFrames':0,'maxErrorMm':0,
                    'clampedFrames':0,'minForwardM':None,'maxLateralM':0,'shapes':[]})
                item['frames']+=1
                for hand in rig.hand_diagnostics.values():
                    if hand['weight']<.95: continue
                    item['heldFrames']+=1
                    item['maxErrorMm']=max(item['maxErrorMm'],hand['errorMm'])
                    item['clampedFrames']+=int(hand['reachClamped'])
                    item['minForwardM']=min(item['minForwardM'] or 100,hand['palmFromFace'][2])
                    item['maxLateralM']=max(item['maxLateralM'],abs(hand['palmFromFace'][0]))
                    if hand['shape'] not in item['shapes']: item['shapes'].append(hand['shape'])
            if animation and animation['state'] in {'finished','error'}:
                report['animations'].append(animation)
                report['animation']=animation
                send({'type':'emote_state','mode':'3d','items':library.list(),'lastEvent':animation})
            if next_index is not None and runner.process is None:
                if next_index == len(requests): break
                send({'type':'chat','id':next_index,'text':requests[next_index]})
                next_index=None
        else: raise TimeoutError('Model/emote test timed out')
        assert report['emotes'] and report['animation']['state']=='finished', report
        assert len(report['turns']) == len(requests)
        if args.spatial:
            for identity,shape in [('face_wave_test','open'),('face_peace_test','peace')]:
                item=report['spatial'][identity]
                assert item['heldFrames']>=10 and item['maxErrorMm']<1 and not item['clampedFrames'], item
                assert item['minForwardM']>=.07 and item['maxLateralM']<.09 and shape in item['shapes'], item
    finally:
        runner.stop()
        send({'type':'quit'})
        try: bridge.wait(timeout=5)
        except subprocess.TimeoutExpired: bridge.kill(); bridge.wait()
        bridge.stdin.close(); bridge.stdout.close(); log.close()
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')

"""Shared, renderer-independent facial and upper-body animation state."""
from __future__ import annotations

import math
import re
import time
from .emote_api import FINGER_BONES, HAND_SHAPES, hand_target

EXPRESSIONS = {
    'smile': 28, 'joy': 3, 'angry': 1, 'sad': 4, 'surprised': 5,
    'relaxed': 2, 'blink': 12, 'wink_left': 13, 'wink_right': 14,
    'brow_angry': 6, 'brow_happy': 8, 'brow_sad': 9, 'brow_up': 10,
    'eyes_happy': 17, 'eyes_wide': 21, 'mouth_a': 36, 'mouth_i': 37,
    'mouth_u': 38, 'mouth_e': 39, 'mouth_o': 40, 'mouth_small': 34,
    'mouth_down': 33, 'mouth_up': 32, 'mouth_close': 26,
}
BUILTINS = {
    'happy': ('Sunbeam', {'smile': .65, 'eyes_happy': .08}, {'head': [0, -4, -4]}, .16),
    'pout': ('Puffed cheeks', {'smile': 0, 'brow_angry': .65, 'mouth_small': .6, 'mouth_down': .35, 'mouth_close': 1,
                            'puff': .9}, {'head': [-3, 5, 8], 'chest': [0, 0, -2]}, .4),
    'shy': ('Hide in my hoodie', {'brow_sad': .35, 'smile': .4}, {'head': [9, -12, 7]}, .9),
    'curious': ('Curious head tilt', {'brow_up': .45, 'mouth_o': .16}, {'head': [0, 10, -12]}, .12),
    'laugh': ('Giggle', {'joy': .75, 'mouth_a': .4}, {'head': [-6, 0, -3]}, .32),
    'smug': ('Smug little gremlin', {'smile': .8, 'wink_left': .25, 'brow_up': .25}, {'head': [-5, -10, 8]}, .12),
    'surprised': ('Waa!', {'surprised': .85, 'mouth_o': .45}, {'head': [-5, 0, 0]}, .16),
    'sad': ('Rain cloud', {'sad': .75}, {'head': [8, 0, -5]}, .15),
    'angry': ('Tiny rebellion', {'angry': .7, 'puff': .3}, {'head': [-4, 0, 4]}, .3),
    'sleepy': ('Sleepy hoodie', {'blink': .72, 'mouth_o': .12}, {'head': [9, 0, 6]}, .08),
    'wink': ('Wink', {'wink_left': 1, 'smile': .65}, {'head': [0, -4, -9]}, .25),
    'wave': ('Sleeve wave', {'smile': .65}, {'head': [0, -5, -5], 'rightUpperArm': [0, 55, 10],
                                         'rightLowerArm': [0, 0, -110]}, .18),
    'shrug': ('What can you do?', {'brow_up': .5, 'smile': .3}, {'head': [0, 0, -9],
             'leftUpperArm': [0, 0, -52], 'rightUpperArm': [0, 0, 52]}, .1),
    'nod': ('Mhm!', {'smile': .5}, {}, .1),
    'wave_front': ('Wave in front of my face', {'smile': .65}, {'head': [0,-3,-3]}, .18),
    'peace': ('Peace sign by my face', {'smile': .65, 'wink_left': .6}, {'head': [0,-3,-3]}, .25),
}
BONES = {'head', 'neck', 'chest', 'upperChest', 'spine', 'leftShoulder', 'rightShoulder',
         'leftUpperArm', 'rightUpperArm', 'leftLowerArm', 'rightLowerArm', 'leftHand', 'rightHand'} | FINGER_BONES


def validate_frame(frame):
    """Scripts are executable; the rendering protocol still needs finite values."""
    if not isinstance(frame, dict):
        raise ValueError('A frame must be an object')
    if unknown := set(frame)-{'expressions','bones','hands'}:
        raise ValueError(f'Unknown frame channels: {sorted(unknown)}')
    expressions = frame.get('expressions', {})
    bones = frame.get('bones', {})
    hands = frame.get('hands', {})
    if not all(isinstance(value, dict) for value in (expressions,bones,hands)):
        raise ValueError('expressions, bones and hands must be objects')
    result = {'expressions': {}, 'bones': {}, 'hands': {}}
    for name, value in expressions.items():
        if name not in EXPRESSIONS and name not in {'blush', 'puff'}:
            raise ValueError(f'Unknown expression: {name}')
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('Expression values must be finite')
        result['expressions'][name] = max(0, min(1, number))
    for name, values in bones.items():
        if name not in BONES or not isinstance(values, (list, tuple)) or len(values) != 3:
            raise ValueError(f'Invalid bone rotation: {name}')
        values = [float(value) for value in values]
        if not all(math.isfinite(value) for value in values):
            raise ValueError('Bone angles must be finite')
        result['bones'][name] = [max(-120, min(120, value)) for value in values]
    for side, target in hands.items():
        if side not in {'left','right'} or not isinstance(target,dict):
            raise ValueError('Hand targets must use left or right')
        if set(target)-{'position','space','shape','roll','weight'}:
            raise ValueError('Unknown hand target option')
        position = target.get('position')
        if not isinstance(position,(list,tuple)) or len(position)!=3:
            raise ValueError('Hand position must be [x,y,z] metres')
        position = [float(value) for value in position]
        roll, weight = float(target.get('roll',0)), float(target.get('weight',1))
        if not all(math.isfinite(value) for value in [*position,roll,weight]):
            raise ValueError('Hand targets must be finite')
        if any(abs(value)>3 for value in position):
            raise ValueError('Hand position must be within three metres')
        space, shape = target.get('space','face'), target.get('shape','open')
        if space not in {'face','body','world'} or shape not in HAND_SHAPES:
            raise ValueError('Unknown hand space or shape')
        result['hands'][side] = {'position':position,'space':space,'shape':shape,
                                 'roll':max(-180,min(180,roll)), 'weight':max(0,min(1,weight))}
    return result


class AvatarMotion:
    def __init__(self):
        self.started = time.monotonic()
        self.emote = None
        self.emote_at = 0
        self.duration = 4
        self.intensity = 1
        self.script_frame = None
        self.script_at = 0
        self.voice_level = 0
        self.voice_at = 0
        self.last_sample = time.monotonic()
        self.smoothed = {}
        self.hand_targets = {}
        self.hair = [0, 0]
        self.hair_velocity = [0, 0]
        self.previous_head = [0, 0, 0]
        self.mood = {'f': 15, 'v': .5, 'e': .7, 'a': .5}

    def play(self, name, duration=4, intensity=1):
        if name not in BUILTINS:
            raise ValueError(f'Unknown emote: {name}')
        self.script_frame = None
        self.emote, self.emote_at = name, time.monotonic()
        self.duration = max(.5, min(30, float(duration)))
        self.intensity = max(0, min(1, float(intensity)))

    def set_frame(self, frame):
        self.script_frame = validate_frame(frame)
        self.script_at = time.monotonic()

    def stop(self):
        self.script_frame = None
        self.emote = None
        self.hand_targets.clear()

    def voice(self, level):
        self.voice_level = max(0, min(1, float(level)))
        self.voice_at = time.monotonic()

    def react(self, text, tool_played=False):
        """Immediate gestures from roleplay text; no model round trip required."""
        # A slow final reply can arrive after its custom script has finished.
        # Do not replace that deliberately chosen pose with a generic keyword.
        if tool_played: return None
        actions = ' '.join(re.findall(r'\*([^*]+)\*', text)).lower()
        for pattern, name in [
            (r'✌|peace\s*sign|v[ -]sign', 'peace'),
            (r'перед\s+лицом|in\s+front\s+of\s+(?:my\s+|her\s+|your\s+)?face', 'wave_front'),
            (r'наду|щёк|щеки|puff|pout', 'pout'), (r'подмиг|wink', 'wink'),
            (r'маш|wave', 'wave'), (r'хих|сме|giggl|laugh', 'laugh'),
            (r'смущ|красне|прячу|blush|shy', 'shy'), (r'зева|сон|yawn|sleep', 'sleepy'),
            (r'наклон|склон|любопыт|tilt|curious', 'curious'), (r'кива|nod', 'nod'),
            (r'улыб|smil', 'happy'), (r'серди|хмур|angry|frown', 'angry'),
        ]:
            if re.search(pattern, actions):
                if self.script_frame is None:
                    self.play(name)
                return name
        return None

    def sample(self, now=None):
        now = time.monotonic() if now is None else now
        t = now - self.started
        fatigue = self.mood.get('f', 15) / 100
        energy = self.mood.get('e', .7)
        expressions = {'smile': max(0, self.mood.get('v', .5)) * .3}
        hands = {}
        bones = {'leftUpperArm': [0, 0, -72], 'rightUpperArm': [0, 0, 72],
                 'leftLowerArm': [0, -8, -8], 'rightLowerArm': [0, 8, 8],
                 'head': [math.sin(t * .7) * 1.1, math.sin(t * .38) * 2, math.sin(t * .51) * 1.5],
                 'chest': [math.sin(t * 1.7) * .5 * energy, 0, math.sin(t * .5) * .5]}
        elapsed = now - self.emote_at
        if self.emote and elapsed < self.duration:
            _, face, pose, blush = BUILTINS[self.emote]
            weight = min(1, elapsed / .22, (self.duration - elapsed) / .5) * self.intensity
            expressions.update({name: value * weight for name, value in face.items()})
            expressions['blush'] = blush * weight
            for name, values in pose.items():
                base = bones.get(name, [0, 0, 0])
                bones[name] = [a + (b - a) * weight for a, b in zip(base, values)]
            if self.emote == 'wave': bones['rightHand'] = [0, 0, 18 * math.sin(elapsed * 10) * weight]
            if self.emote == 'nod': bones['head'][0] += math.sin(elapsed * 5) * 9 * weight
            if self.emote == 'laugh': bones['chest'][0] += math.sin(elapsed * 16) * 1.4 * weight
            if self.emote in {'wave_front','peace'}:
                peace = self.emote == 'peace'
                hands['right'] = hand_target([-.035 if peace else .018*math.sin(elapsed*7), -.025, .14],
                    shape='peace' if peace else 'open', roll=-8 if peace else 16*math.sin(elapsed*9), weight=weight)
        if self.script_frame is not None:
            # Last pose remains until the runner completes or the user stops it.
            expressions.update(self.script_frame['expressions'])
            bones.update(self.script_frame['bones'])
            hands.update(self.script_frame['hands'])
        blink_phase = (t + .31 * math.sin(t * .33)) % 4.3
        blink = max(0, 1 - abs(blink_phase - .14) / .11)
        expressions['blink'] = max(expressions.get('blink', 0), blink, max(0, fatigue - .65))
        voice = self.voice_level * max(0, 1 - (now - self.voice_at) / .18)
        expressions['mouth_a'] = max(expressions.get('mouth_a', 0), voice * .72)
        expressions['mouth_o'] = max(expressions.get('mouth_o', 0), voice * .18)
        expressions['mouth_close'] = expressions.get('mouth_close', 0)*(1-voice)
        # Blend turns/poses, then use a damped secondary spring on the hair rig.
        dt = max(0, min(.05, now-self.last_sample))
        self.last_sample = now
        blend = 1-math.exp(-dt*15)
        for side in self.hand_targets.keys() | hands.keys():
            target = hands.get(side)
            old = self.hand_targets.get(side)
            if target is None:
                target = {**old, 'weight':0}
            current = dict(target)
            current['weight'] = (old or {}).get('weight',0)+(target['weight']-(old or {}).get('weight',0))*blend
            if old and old['space']==target['space']:
                current['position'] = [a+(b-a)*blend for a,b in zip(old['position'],target['position'])]
                current['roll'] = old['roll']+(target['roll']-old['roll'])*blend
            if current['weight']>.0001: self.hand_targets[side] = current
            else: self.hand_targets.pop(side,None)
        for name, target in bones.items():
            old = self.smoothed.get(name, target)
            self.smoothed[name] = [a+(b-a)*blend for a,b in zip(old,target)]
        bones = {name: values[:] for name, values in self.smoothed.items() if name in bones}
        head = bones['head']
        for i, axis in enumerate((0, 2)):
            impulse = (head[axis]-self.previous_head[axis]) * -5
            self.hair_velocity[i] += impulse
            self.hair_velocity[i] += (-60*self.hair[i]-10*self.hair_velocity[i])*dt
            self.hair[i] = max(-2, min(2, self.hair[i]+self.hair_velocity[i]*dt))
        self.previous_head = head[:]
        # Full-face joy closes the eyes already; avoid double-closing the lid.
        expressions['blink'] *= 1-max(expressions.get('joy', 0), expressions.get('eyes_happy', 0))
        morphs = {EXPRESSIONS[name]: value for name, value in expressions.items()
                  if name in EXPRESSIONS and value > .001}
        return bones, morphs, expressions.get('blush', .08), expressions.get('puff', 0)

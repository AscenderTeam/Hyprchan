"""Written-action dispatch, streaming/tool precedence, and real rig movement."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import gi
gi.require_version('Gtk', '4.0')
from desktop_avatar import DesktopAvatar
from hyprchan.core.animations.avatar3d.motion import AvatarMotion, BUILTINS, GESTURE_TRIGGERS, matching_gesture

REPORTED_REPLY = '*прижимаю рукава к груди* Ууу, теперь я вся растаяла… ты тоже мой любимый человек, ня~'


def controller():
    avatar = DesktopAvatar.__new__(DesktopAvatar)
    avatar.motion = AvatarMotion()
    avatar.runner = SimpleNamespace(identity=None)
    avatar.label = SimpleNamespace(set_label=lambda text: None)
    avatar.mode, avatar.outfit, avatar.items = '3d', 'hoodie', []
    avatar.last_event = None
    avatar.events = []
    avatar.host = SimpleNamespace(model_ready=True, send=lambda _, event: avatar.events.append(event))
    return avatar


class WrittenGesturesTest(unittest.TestCase):
    def test_reported_reply_and_natural_variants(self):
        for text in [REPORTED_REPLY, '*прижимаю ладони к сердцу*', '*держу руки у груди*',
                     '*clutch my sleeves to my chest*', '*press my hands to my heart*']:
            with self.subTest(text=text):
                avatar = controller()
                self.assertEqual(avatar.react(text, {}, final=True), 'heart_hug')
                self.assertEqual(avatar.motion.emote, 'heart_hug')
                self.assertTrue(avatar.last_event['visible'])

    def test_every_prompt_example_is_executable_by_the_renderer(self):
        for item in GESTURE_TRIGGERS:
            self.assertIn(item['id'], BUILTINS)
            for text in item['examples']:
                with self.subTest(text=text):
                    self.assertEqual(matching_gesture('*'+text+'*'), item['id'])

    def test_streaming_waits_for_closed_action_then_plays_once(self):
        avatar, turn = controller(), {}
        text = '*прижимаю рукава к груди'
        self.assertIsNone(avatar.react(text, turn))
        self.assertIsNone(avatar.motion.emote)
        self.assertEqual(avatar.react(text+'*', turn), 'heart_hug')
        start = avatar.motion.emote_at
        for suffix in [' Ууу', ', теперь я вся растаяла', '… ня~']:
            self.assertIsNone(avatar.react(text+'*'+suffix, turn))
            self.assertEqual(avatar.motion.emote_at, start)
        avatar.motion.sample(start+5)
        self.assertIsNone(avatar.react(REPORTED_REPLY, turn, final=True))
        self.assertIsNone(avatar.motion.emote)  # no restart when a slow reply ends
        self.assertEqual(len(avatar.events), 1)
        self.assertEqual(avatar.react(REPORTED_REPLY, {}, final=True), 'heart_hug')

    def test_done_without_deltas_and_unknown_action_feedback(self):
        avatar = controller()
        self.assertEqual(avatar.react(REPORTED_REPLY, {}, final=True), 'heart_hug')
        avatar.motion.stop()
        turn = {}
        self.assertIsNone(avatar.react('*обнимаю колени* Привет!', turn, final=True))
        self.assertEqual(avatar.last_event['state'], 'unmapped_action')
        self.assertFalse(avatar.last_event['visible'])
        self.assertNotIn('written_emote_played', turn)
        self.assertIsNone(avatar.motion.emote)

    def test_plain_text_and_bold_are_not_actions(self):
        for text in ['прижимаю рукава к груди', '**прижимаю рукава к груди**', '*hands* to *chest*']:
            with self.subTest(text=text):
                self.assertIsNone(matching_gesture(text))

    def test_spatial_words_do_not_substitute_an_unrelated_animation(self):
        for text in ['*прячу руки за спиной*', '*касаюсь щеки*', '*hold a flower in front of my face*',
                     '*наклоняю ладонь*']:
            with self.subTest(text=text):
                self.assertIsNone(matching_gesture(text))

    def test_tool_animation_wins_including_after_it_finishes(self):
        avatar = controller()
        for tool_turn in [{'emote_played': True}, {}]:
            avatar.runner.identity = None if tool_turn else 'custom_hug'
            self.assertIsNone(avatar.react(REPORTED_REPLY, tool_turn, final=True))
            self.assertIsNone(avatar.motion.emote)
        avatar.runner.identity = None
        avatar.motion.set_frame({'bones': {'head': [0, 0, 10]}})
        self.assertIsNone(avatar.motion.react(REPORTED_REPLY))
        self.assertIsNotNone(avatar.motion.script_frame)

    def test_builtin_tool_reports_start_and_completion_without_stale_stop(self):
        from hyprchan.core.animations.avatar3d.emotes import EmoteRunner
        avatar = controller()
        avatar.runner = EmoteRunner()
        avatar.widgets, avatar.next_refresh = [], float('inf')
        avatar.host.closing = False
        avatar.host.mood_values = [avatar.motion.mood]
        avatar.host.mood = SimpleNamespace(get_selected=lambda: 0)
        result = avatar.play('heart_hug', seconds=3)
        self.assertTrue(result['started'])
        avatar.tick()
        self.assertEqual(avatar.last_event['state'], 'started')
        avatar.motion.emote_at -= 4
        avatar.tick()
        self.assertEqual(avatar.last_event['state'], 'finished')
        self.assertEqual(avatar.last_event['id'], 'heart_hug')

    def test_both_hands_actually_reach_chest_then_return(self):
        import numpy as np
        from hyprchan.core.animations.avatar3d.model import AvatarModel
        model, motion = AvatarModel(), AvatarMotion()
        rest_bones, *_ = motion.sample()
        rest = model.posed(rest_bones)
        motion.react(REPORTED_REPLY)
        start = motion.emote_at
        for frame in range(1, 46):
            bones, *_ = motion.sample(start+frame/30)
        world = model.posed(bones, hands=motion.hand_targets)
        for side in ('left', 'right'):
            report = model.hand_diagnostics[side]
            self.assertFalse(report['reachClamped'])
            self.assertLess(report['errorMm'], .1)
            self.assertGreater(report['weight'], .99)
            hand = world[model.bones[side+'Hand']][:3, 3]
            middle = world[model.bones[side+'MiddleProximal']][:3, 3]
            palm = (hand+middle)/2
            chest = world[model.bones['chest']][:3, 3]
            self.assertLess(abs(palm[0]-chest[0]), .09)
            self.assertGreater(palm[1]-chest[1], .08)
            self.assertGreater(palm[2]-chest[2], .18)
            self.assertGreater(hand[1]-rest[model.bones[side+'Hand']][1, 3], .25)
        self.assertTrue(np.isfinite(world).all())
        for frame in range(46, 161):
            motion.sample(start+frame/30)
        self.assertIsNone(motion.emote)
        self.assertFalse(motion.hand_targets)


if __name__ == '__main__': unittest.main()

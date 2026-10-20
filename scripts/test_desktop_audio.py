import unittest
import json
from desktop_pipewire_worker import AudioNodes, JsonArrays
from desktop_listen_in import listen_plan


def node(identity, name, state="idle", media_class="Stream/Output/Audio"):
    return {"id": identity, "type": "PipeWire:Interface:Node", "info": {
        "state": state, "props": {"object.serial": identity + 100, "media.class": media_class,
        "node.name": name, "application.name": name}}}


class AudioTests(unittest.TestCase):
    def test_dump_preambles_and_fragmented_arrays(self):
        arrays = [[{"type": "PipeWire:Interface:Core", "id": 0}],
                  [node(1, 'Player ["test"]')], [node(2, "New music")]]
        stream = "\n".join(json.dumps(array) for array in arrays)
        decoder = JsonArrays()
        decoded = []
        for offset in range(0, len(stream), 7):
            decoded.extend(decoder.feed(stream[offset:offset + 7]))
        self.assertEqual(decoded, arrays)
        tracker = AudioNodes()
        self.assertEqual(tracker.update(decoded[0]), [])
        self.assertTrue(tracker.initial)
        self.assertEqual(tracker.update(decoded[1]), [])
        self.assertFalse(tracker.initial)
        self.assertEqual(tracker.update(decoded[2])[0]["name"], "New music")

    def test_initial_devices_are_quiet_then_new_streams_and_restarts_are_reported_once(self):
        tracker = AudioNodes()
        self.assertEqual(tracker.update([node(1, "Existing player")]), [])
        events = tracker.update([node(2, "Music player", "running")])
        self.assertEqual(events[0]["name"], "Music player")
        self.assertEqual(events[0]["serial"], "102")
        self.assertEqual(tracker.update([node(2, "Music player", "running")]), [])
        tracker.update([{"id": 2, "info": {"state": "idle"}}])
        self.assertEqual(tracker.update([{"id": 2, "info": {"state": "running"}}])[0]["event"], "playback_started")
        tracker.update([{"id": 2, "info": None}])
        self.assertEqual(len(tracker.playback()), 1)

    def test_own_capture_does_not_trigger_a_feedback_loop(self):
        tracker = AudioNodes()
        tracker.update([])
        self.assertEqual(tracker.update([node(3, "Hyprchan listen_in", "running", "Stream/Input/Audio")]), [])
        self.assertEqual(tracker.update([node(4, "Hyprchan voice", "running", "Stream/Output/Audio")]), [])
        self.assertEqual(tracker.playback(), [])

    def test_listening_is_bounded_and_long_requests_have_five_chunks(self):
        self.assertEqual(listen_plan(10), (1, 640000))
        self.assertEqual(listen_plan(20), (5, 256000))
        self.assertEqual(listen_plan(11)[0], 5)
        for value in [0, 21, -1, True, "20", float("nan")]:
            with self.assertRaises(ValueError):
                listen_plan(value)


if __name__ == "__main__":
    unittest.main()

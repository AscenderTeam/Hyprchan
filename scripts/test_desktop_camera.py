"""Camera ownership regressions: never compete for the Asahi ISP or shared reader."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from desktop_vision_worker import VisionWorker, camera_device
from shared_camera_feed import SharedCamera


class SelectionTest(unittest.TestCase):
    def test_dedicated_context_output_wins_over_physical_and_obs_but_override_wins(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {}, clear=True):
            root = Path(directory)
            for number, name in [(0, "OBS Virtual Camera"), (1, "FaceTime HD Camera"),
                                 (2, "Hyprchan Shared Camera"), (3, "Hyprchan Camera Context")]:
                (root/f"video{number}").mkdir()
                (root/f"video{number}"/"name").write_text(name)
            self.assertEqual(camera_device(root), (3, "Hyprchan Camera Context"))
            with patch.dict("os.environ", {"HYPRCHAN_CAMERA_INDEX": "1"}):
                self.assertEqual(camera_device(root), (1, "FaceTime HD Camera"))


class OwnershipTest(unittest.IsolatedAsyncioTestCase):
    async def test_busy_physical_camera_is_not_opened_and_retries_are_throttled(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = VisionWorker(Path(directory))
            with patch("desktop_vision_worker.camera_device", return_value=(1, "FaceTime HD Camera")), \
                 patch("desktop_vision_worker.subprocess.run", return_value=Mock(stdout=b"123")) as users, \
                 patch("desktop_vision_worker.OpenCVPerceptionModule") as camera:
                await worker.ensure_camera()
                await worker.ensure_camera()
                camera.assert_not_called()
                self.assertIn("already in use", worker.camera_error)
                users.assert_called_once()

    async def test_shared_producer_does_not_block_hyprchan_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = VisionWorker(Path(directory))
            camera = Mock(start=AsyncMock(), stop=AsyncMock(), last_error=None)
            with patch("desktop_vision_worker.camera_device", return_value=(3, "Hyprchan Camera Context")), \
                 patch("desktop_vision_worker.subprocess.run") as users, \
                 patch("desktop_vision_worker.OpenCVPerceptionModule", return_value=camera):
                await worker.ensure_camera()
                camera.start.assert_awaited_once()
                users.assert_not_called()
                self.assertIsNone(worker.camera_error)


class FeedTest(unittest.TestCase):
    def test_either_app_can_start_first_and_last_reader_controls_camera_lifetime(self):
        for first, second in [(101, 202), (202, 101)]:
            with self.subTest(first=first):
                camera = SharedCamera("physical", ["obs", "context"])
                process = Mock(pid=303)
                process.poll.return_value = None
                readers = {first}
                def users(devices):
                    return set() if devices == ["physical"] else readers
                with patch("shared_camera_feed.device_users", side_effect=users), \
                     patch("shared_camera_feed.subprocess.Popen", return_value=process) as spawn, \
                     patch("shared_camera_feed.threading.Thread"):
                    camera.tick(100)
                    readers.update({second, process.pid})
                    camera.tick(101)
                    readers.remove(first)
                    camera.tick(102)
                    spawn.assert_called_once()
                    process.send_signal.assert_not_called()
                    readers.remove(second)
                    camera.tick(106)  # five-second grace has not elapsed yet
                    process.send_signal.assert_not_called()
                    camera.tick(108)
                    process.send_signal.assert_called_once()
                    process.wait.assert_called_once()
                    self.assertIsNone(camera.process)

    def test_other_physical_owner_is_left_alone_until_it_releases(self):
        camera = SharedCamera("physical", ["obs", "context"])
        with patch("shared_camera_feed.device_users", return_value={101}), \
             patch("shared_camera_feed.subprocess.Popen") as spawn:
            camera.tick(100)
            camera.tick(101)
            spawn.assert_not_called()
            self.assertEqual(camera.retry_at, 105)

    def test_stalled_capture_releases_hardware_and_backs_off(self):
        camera = SharedCamera("physical", ["obs", "context"])
        process = Mock(pid=303)
        process.poll.return_value = None
        camera.process = process
        camera.last_frame_at = 100
        with patch("shared_camera_feed.device_users", return_value={101}), \
             patch("shared_camera_feed.subprocess.Popen") as spawn:
            camera.tick(116)
            process.send_signal.assert_called_once()
            process.wait.assert_called_once()
            spawn.assert_not_called()
            self.assertEqual(camera.retry_at, 121)


if __name__ == "__main__":
    unittest.main()

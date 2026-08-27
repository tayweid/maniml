import json
import tempfile
import unittest
from pathlib import Path

from maniml.performance import PerformanceRecorder


class PerformanceRecorderTests(unittest.TestCase):
    def test_disabled_recorder_is_a_no_op(self):
        recorder = PerformanceRecorder()
        with recorder.stage("ignored"):
            pass
        recorder.increment("ignored")

        self.assertFalse(recorder.enabled)
        self.assertEqual(recorder.snapshot()["stages"], {})
        self.assertEqual(recorder.snapshot()["counters"], {})

    def test_enabled_recorder_writes_bounded_stage_summary(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "profile.json"
            recorder = PerformanceRecorder(path)
            recorder.observe_ms("checkpoint.copy", 1)
            recorder.observe_ms("checkpoint.copy", 3)
            recorder.increment("native.capture.calls", 2)
            recorder.gauge("checkpoint.count", 4)
            recorder.metadata(scene="Demo", route="direct")
            recorder.flush()

            profile = json.loads(path.read_text())
            stage = profile["stages"]["checkpoint.copy"]
            self.assertEqual(stage["count"], 2)
            self.assertEqual(stage["mean_ms"], 2)
            self.assertEqual(stage["p95_ms"], 3)
            self.assertEqual(profile["counters"]["native.capture.calls"], 2)
            self.assertEqual(profile["gauges"]["checkpoint.count"], 4)
            self.assertEqual(profile["metadata"]["scene"], "Demo")

    def test_pid_placeholder_is_resolved_once(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder = PerformanceRecorder(Path(folder) / "profile-{pid}.json")
            recorder.flush()
            self.assertTrue(recorder.path.is_file())
            self.assertNotIn("{pid}", recorder.path.name)


if __name__ == "__main__":
    unittest.main()

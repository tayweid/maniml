"""Point-read counters: raw versus reduction reads, tagged by scene phase
(TODO.md "Now", item 3; the Phase B sync-policy prerequisite)."""

import unittest

from maniml import RIGHT, Scene, Square, ValueTracker
from maniml.performance import performance


class ReadCounters(unittest.TestCase):
    def setUp(self):
        performance.enabled = True
        performance._counters.clear()
        performance.read_phase = "idle"

    def tearDown(self):
        performance.enabled = False
        performance._counters.clear()
        performance.read_phase = "idle"

    @staticmethod
    def reads():
        return {k: v for k, v in performance._counters.items()
                if k.startswith("reads.") and not k.startswith("reads.site.")}

    def test_raw_and_reduction_reads_are_told_apart(self):
        square = Square()
        performance._counters.clear()
        square.get_points()
        square.get_center()
        square.get_end()
        square.has_points()          # a count, not a read
        square.get_num_points()
        self.assertEqual(self.reads(), {"reads.raw.idle": 1, "reads.reduce.idle": 2})

    def test_the_calling_site_is_named(self):
        square = Square()
        performance._counters.clear()
        square.get_points()
        sites = [k for k in performance._counters if k.startswith("reads.site.raw.idle.")]
        self.assertEqual(len(sites), 1)
        self.assertTrue(sites[0].endswith("test_read_instrumentation.py:test_the_calling_site_is_named"), sites[0])

    def test_updaters_and_plays_tag_their_phase(self):
        square = Square()
        tracker = ValueTracker(1.0)
        square.add_updater(lambda m: m.move_to(RIGHT * tracker.get_value()), call=False)
        performance._counters.clear()
        square.update(0)
        counted = self.reads()
        self.assertEqual(set(counted), {"reads.reduce.updater"})   # the tracker value and move_to's box reads
        self.assertGreaterEqual(counted["reads.reduce.updater"], 2)
        self.assertEqual(performance.read_phase, "idle")

        scene = Scene(window=None)
        scene.skip_animations = True
        try:
            scene.add(square)
            performance._counters.clear()
            scene.play(square.animate.shift(RIGHT), run_time=0.05)
            counted = self.reads()
            self.assertGreater(counted.get("reads.raw.play", 0), 0)
            self.assertGreater(counted.get("reads.reduce.updater", 0), 0)
            self.assertEqual(performance.read_phase, "idle")
        finally:
            scene.camera.release()


if __name__ == '__main__':
    unittest.main()

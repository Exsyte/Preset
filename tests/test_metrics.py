import math
import tempfile
import unittest
from pathlib import Path

from presetmon2 import metrics
from presetmon2.preset import load_preset

PRESET = load_preset()


def synthetic():
    # 98 frames of 2 ms, one 10 ms and one 20 ms frame: n=100, total=226 ms.
    return metrics.Capture(frametime_ms=[2.0] * 98 + [10.0, 20.0])


class NearestRank(unittest.TestCase):
    def test_ranks(self):
        ordered = [float(i) for i in range(1, 101)]
        self.assertEqual(metrics.nearest_rank(ordered, 99.0), 99.0)
        self.assertEqual(metrics.nearest_rank(ordered, 99.9), 100.0)
        self.assertEqual(metrics.nearest_rank(ordered, 1.0), 1.0)


class ComputeMetrics(unittest.TestCase):
    def test_frametime_statistics(self):
        m = metrics.compute_metrics(synthetic(), PRESET["metrics"])
        self.assertAlmostEqual(m["avg_fps"], 1000 / 2.26)
        self.assertAlmostEqual(m["low1_fps"], 1000 / 20.0)      # worst ceil(1) frame
        self.assertAlmostEqual(m["low01_fps"], 1000 / 20.0)     # at least one frame
        self.assertAlmostEqual(m["p1_fps"], 1000 / 10.0)        # 99th percentile frametime
        self.assertAlmostEqual(m["p01_fps"], 1000 / 20.0)
        self.assertEqual(m["frame_count"], 100)
        self.assertAlmostEqual(m["duration_secs"], 0.226)
        self.assertEqual((m["frametime_min_ms"], m["frametime_max_ms"]), (2.0, 20.0))

    def test_stutter_uses_own_average_by_default(self):
        m = metrics.compute_metrics(synthetic(), PRESET["metrics"])
        # threshold 2.5 * 2.26 = 5.65 ms -> the 10 ms and 20 ms frames count
        self.assertAlmostEqual(m["stutter_time_pct"], 30 / 226 * 100)

    def test_stutter_uses_reference_average(self):
        m = metrics.compute_metrics(synthetic(), PRESET["metrics"], reference_avg_frametime_ms=4.0)
        # threshold 2.5 * 4 = 10 ms -> only the 20 ms frame is strictly longer
        self.assertAlmostEqual(m["stutter_time_pct"], 20 / 226 * 100)

    def test_missing_series_are_none(self):
        m = metrics.compute_metrics(synthetic(), PRESET["metrics"])
        for key in ("gpu_busy_avg_ms", "pc_latency_avg_ms", "animation_error_avg_ms"):
            self.assertIsNone(m[key])

    def test_animation_error_is_mean_absolute(self):
        cap = synthetic()
        cap.series["animation_error_ms"] = [-2.0, 2.0, -1.0, 1.0]
        m = metrics.compute_metrics(cap, PRESET["metrics"])
        self.assertAlmostEqual(m["animation_error_avg_ms"], 1.5)


class ReadCapture(unittest.TestCase):
    HEADER = ("Application,SyncInterval,PresentMode,TimeInMs,MsBetweenPresents,MsUntilDisplayed,"
              "MsGPULatency,MsGPUBusy,MsGPUWait,MsAnimationError,"
              "MsAllInputToPhotonLatency,MsClickToPhotonLatency")

    def write(self, text):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8-sig")
        tmp.write(text)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink)
        return tmp.name

    def test_parses_na_bom_and_short_rows(self):
        path = self.write(
            self.HEADER + "\n"
            "cs2.exe,0,Hardware: Independent Flip,4.0,2.0,3.5,2.1,2.2,0.0,NA,NA,NA\n"
            "cs2.exe,0,Hardware: Independent Flip,6.0,2.0,3.7,2.3,2.4,0.1,-0.5,NA,NA\n"
            "cs2.exe,0,Hardware: Independent Flip,8.0,NA,3.9,2.3,2.4,0.1,0.1,NA,NA\n"  # no frametime
            "cs2.exe,0,Hardware: Independent Flip,9.0,3.0\n")                             # truncated row
        cap = metrics.read_capture(path, PRESET["csv"])
        self.assertEqual(cap.frametime_ms, [2.0, 2.0, 3.0])
        self.assertEqual(cap.time_ms, [4.0, 6.0, 9.0])
        self.assertEqual(cap.series["pc_latency_ms"], [3.5, 3.7])
        self.assertEqual(cap.series["animation_error_ms"], [-0.5])
        self.assertFalse(cap.input_detected)

    def test_detects_input(self):
        path = self.write(self.HEADER + "\n"
                          "cs2.exe,0,m,4.0,2.0,3.5,2.1,2.2,0.0,0.1,12.5,NA\n")
        self.assertTrue(metrics.read_capture(path, PRESET["csv"]).input_detected)

    def test_missing_required_column(self):
        path = self.write("Application,TimeInMs\ncs2.exe,1.0\n")
        with self.assertRaisesRegex(ValueError, "MsBetweenPresents"):
            metrics.read_capture(path, PRESET["csv"])

    def test_no_frames(self):
        path = self.write(self.HEADER + "\n")
        with self.assertRaisesRegex(ValueError, "no frames"):
            metrics.read_capture(path, PRESET["csv"])


class ChartData(unittest.TestCase):
    def test_downsampling(self):
        cap = metrics.Capture(frametime_ms=[2.0] * 5000 + [9.0] + [2.0] * 5000)
        chart = metrics.chart_data(cap, PRESET["metrics"]["chart"])
        buckets = PRESET["metrics"]["chart"]["buckets"]
        self.assertLessEqual(len(chart["raw"]), buckets)
        self.assertLessEqual(len(chart["ma"]), buckets)
        self.assertEqual(max(v for _, v in chart["raw"]), 9.0)       # spikes survive
        self.assertAlmostEqual(chart["duration"], 20.009, places=3)
        self.assertTrue(all(0 <= t <= chart["duration"] + 1e-9 for t, _ in chart["raw"] + chart["ma"]))
        self.assertTrue(all(math.isfinite(v) for _, v in chart["ma"]))


if __name__ == "__main__":
    unittest.main()

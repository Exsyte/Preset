import json
import tempfile
import unittest
from pathlib import Path

from presetmon2 import capframex_report, cli
from presetmon2.preset import load_preset

PRESET = load_preset()
N = 400


def capture(n=N, base=2.0):
    return {
        "TimeInSeconds": [i * 0.002 for i in range(n)],
        "MsBetweenPresents": [base + (0.5 if i % 50 == 0 else 0.0) for i in range(n)],
        "MsInPresentAPI": [1.0] * n,
        "MsBetweenDisplayChange": [base] * n,
        "MsUntilDisplayed": [3.0] * n,
        "PresentMode": [3] * n,
        "SyncInterval": [0] * n,
        "Dropped": [False] * n,
        "PcLatency": [6.0] * n,
        "AnimationError": [-0.2, 0.2] * (n // 2),
        "GpuActive": [1.9] * n,
        "CpuActive": [0.5] * n,
    }


def sensor(kind, name, values):
    return {"Name": name, "Type": kind, "StableIdentifier": None, "Values": values}


def write_capframex(comment="Tiny boost 1 run", base=2.0, runs=1, file_hash="ABCDEF0123456789"):
    sensors = {
        "t": sensor("Time", "MeasureTime", [1.0, 2.0, 3.0]),
        "load": sensor("Load", "GPU Core", [90.0, 100.0, 98.0]),
        "clock": sensor("Clock", "GPU Core", [2700.0, 2700.0, 2700.0]),
        "dead": sensor("Temperature", "CPU Package (Tctl/Tdie)", [0.0, 0.0, 0.0]),
    }
    data = {"Hash": file_hash,
            "Info": {"ProcessName": "cs2.exe", "GameName": "Counter Strike 2", "Comment": comment,
                     "GPU": "RTX Test", "AppVersion": "1.9.1.5", "DeviceName": "SECRET-HOST",
                     "CreationDate": "2026-10-03T00:35:26.3037199Z"},
            "Runs": [{"CaptureData": capture(base=base), "SensorData2": sensors} for _ in range(runs)]}
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(data, tmp)
    tmp.close()
    return Path(tmp.name)


class Labels(unittest.TestCase):
    def test_cleaning(self):
        label = capframex_report._run_label
        self.assertEqual(label({"Comment": "Tiny boost 1 run"}, 1, 1, None), "Tiny boost 1")
        self.assertEqual(label({"Comment": "Tiny boost 2 "}, 1, 1, None), "Tiny boost 2")
        self.assertEqual(label({"Comment": ""}, 3, 1, None), "Run 3")
        self.assertEqual(label({"Comment": "A"}, 2, 3, None), "A (run 2)")
        self.assertEqual(label({"Comment": "A"}, 1, 1, "Custom"), "Custom")


class Collect(unittest.TestCase):
    def setUp(self):
        self.files = [write_capframex("Tiny boost 1 run", 2.0), write_capframex("Tiny boost 2", 2.2)]
        self.runs = capframex_report.collect_runs(self.files, PRESET)

    def test_metrics(self):
        m = self.runs[0]["metrics"]
        self.assertEqual(m["frame_count"], N)
        self.assertAlmostEqual(m["pcl_avg_ms"], 6.0)
        self.assertAlmostEqual(m["cpu_busy_avg_ms"], 0.5)
        self.assertAlmostEqual(m["gpu_busy_avg_ms"], 1.9)
        self.assertAlmostEqual(m["in_present_avg_ms"], 1.0)
        self.assertAlmostEqual(m["pc_latency_avg_ms"], 3.0)
        self.assertAlmostEqual(m["animation_error_avg_ms"], 0.2)
        self.assertIsNone(m["gpu_latency_avg_ms"])

    def test_stutter_uses_one_threshold_for_all_runs(self):
        # run 1 averages ~2.0125 ms, run 2 ~2.2125 ms -> threshold 2.5 x ~2.1125 = ~5.28 ms
        # no frame exceeds it, so neither run reports stutter
        self.assertEqual([r["metrics"]["stutter_time_pct"] for r in self.runs], [0.0, 0.0])
        slow = capframex_report.collect_runs([write_capframex(base=2.0), write_capframex(base=6.0)], PRESET)
        # threshold = 2.5 x mean(2.0125, 6.0125) = 10.03 ms; 6 ms frames stay under it
        self.assertEqual(slow[1]["metrics"]["stutter_time_pct"], 0.0)

    def test_sensor_summary_skips_dead_channels(self):
        specs = PRESET["capframex_report"]["sensors"]
        by_label = {s["label"]: r for s, r in zip(specs, self.runs[0]["sensor_summary"])}
        self.assertAlmostEqual(by_label["GPU load"]["avg"], 96.0)
        self.assertEqual((by_label["GPU load"]["min"], by_label["GPU load"]["max"]), (90.0, 100.0))
        self.assertIsNone(by_label["CPU temperature"])      # all zero -> not readable
        self.assertIsNone(by_label["CPU load (total)"])     # absent

    def test_label_count_must_match(self):
        with self.assertRaisesRegex(ValueError, "--label"):
            capframex_report.collect_runs(self.files, PRESET, ["only one", "two", "three"])

    def test_merged_file_gives_one_run_each(self):
        runs = capframex_report.collect_runs([write_capframex(runs=3)], PRESET)
        self.assertEqual([r["label"] for r in runs],
                         ["Tiny boost 1 (run 1)", "Tiny boost 1 (run 2)", "Tiny boost 1 (run 3)"])


class Html(unittest.TestCase):
    def setUp(self):
        files = [write_capframex("Tiny boost 1 run", 2.0), write_capframex("Tiny boost 2", 2.2, file_hash="00")]
        self.runs = capframex_report.collect_runs(files, PRESET)
        self.html = capframex_report.render_html(PRESET, self.runs)

    def test_contents(self):
        for needle in ("Benchmark ID: CAPFRAMEX-ABCDEF01", ">Tiny boost 1<", ">Tiny boost 2<",
                       "Results captured with CapFrameX 1.9.1.5", "Counter Strike 2 cs2.exe",
                       ">GPU load<", "constant", "Mean of runs", "Spread (max", "--passes:2",
                       "2026-10-03 00:35 UTC", "400 frames"):
            self.assertIn(needle, self.html)

    def test_no_baseline_colouring_and_no_dead_rows(self):
        for klass in ('tv improved', 'tv regressed', 'tv slightly-regressed', 'tv baseline'):
            self.assertNotIn(klass, self.html)
        self.assertNotIn("CPU temperature", self.html)    # all-zero sensor left out
        self.assertNotIn(">n/a<", self.html)              # no tile for data CapFrameX lacks

    def test_sources_are_file_names_only(self):
        self.assertNotIn("/tmp", self.html)

    def test_label_is_escaped(self):
        runs = capframex_report.collect_runs([write_capframex()], PRESET, ['<b onmouseover="x">'])
        html = capframex_report.render_html(PRESET, runs)
        self.assertNotIn('<b onmouseover', html)
        self.assertIn("&lt;b onmouseover", html)

    def test_json_export_omits_hostname(self):
        dump = json.dumps(capframex_report.export_json(self.runs))
        self.assertNotIn("SECRET-HOST", dump)
        self.assertIn("Load/GPU Core", dump)
        self.assertNotIn("CPU Package (Tctl/Tdie)", dump)


class Command(unittest.TestCase):
    def test_end_to_end(self):
        files = [write_capframex("Tiny boost 1 run"), write_capframex("Tiny boost 2")]
        out = Path(tempfile.mkdtemp())
        rc = cli.main(["capframex-report", *map(str, files), "--out", str(out / "r.html"),
                       "--json", str(out / "r.json"), "--label", "A", "--label", "B"])
        self.assertEqual(rc, 0)
        self.assertIn(">A<", (out / "r.html").read_text(encoding="utf-8"))
        self.assertEqual([r["label"] for r in json.loads((out / "r.json").read_text())], ["A", "B"])

    def test_errors(self):
        bad = Path(tempfile.mkdtemp()) / "x.json"
        bad.write_text('{"nope": 1}')
        self.assertEqual(cli.main(["capframex-report", str(bad)]), 2)
        good = write_capframex()
        self.assertEqual(cli.main(["capframex-report", str(good), "--label", "a", "--label", "b"]), 2)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path

from presetmon2 import capframex_compare as cc
from presetmon2 import capframex_report, cli
from presetmon2.preset import load_preset

PRESET = load_preset()
N = 600


def capture(base, n=N):
    return {
        "TimeInSeconds": [i * 0.002 for i in range(n)],
        "MsBetweenPresents": [base + (3.0 if i % 100 == 0 else 0.0) for i in range(n)],
        "MsInPresentAPI": [1.0] * n, "MsBetweenDisplayChange": [base] * n,
        "MsUntilDisplayed": [3.0] * n, "PresentMode": [3] * n, "SyncInterval": [0] * n,
        "Dropped": [False] * n, "PcLatency": [6.0] * n, "AnimationError": [-0.2, 0.2] * (n // 2),
        "GpuActive": [1.9] * n, "CpuActive": [0.5] * n,
    }


def write(comment, base, game_mode="Disabled", clock=None, created="2026-10-03T00:35:26Z"):
    clock = clock if clock is not None else [2700.0] * 5
    sensors = {
        "load": {"Name": "GPU Core", "Type": "Load", "Values": [95.0, 99.0, 98.0, 97.0, 99.0]},
        "clock": {"Name": "GPU Core", "Type": "Clock", "Values": clock},
    }
    data = {"Hash": "ABCDEF0123456789",
            "Info": {"ProcessName": "cs2.exe", "Comment": comment, "WinGameMode": game_mode, "GPU": "RTX Test",
                     "AppVersion": "1.9.1.5", "DeviceName": "SECRET-HOST", "CreationDate": created},
            "Runs": [{"CaptureData": capture(base), "SensorData2": sensors}]}
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(data, tmp)
    tmp.close()
    return Path(tmp.name)


def two_sets(slow=2.4, fast=2.0, **kw_fast):
    a = [write(f"A run {i}", slow + i * 0.01) for i in range(3)]
    b = [write(f"B run {i}", fast + i * 0.01, game_mode="Enabled", **kw_fast) for i in range(3)]
    return cc.build_sets([("Baseline", a), ("Other", b)], PRESET), a, b


class Aggregate(unittest.TestCase):
    def test_set_means_and_common_reference(self):
        (sets, ref), *_ = two_sets()
        self.assertEqual([len(s["runs"]) for s in sets], [3, 3])
        mean_ft = sum(sum(r["capture"].frametime_ms) / N for s in sets for r in s["runs"]) / 6
        self.assertAlmostEqual(ref, mean_ft)
        for s in sets:
            for r in s["runs"]:
                self.assertAlmostEqual(r["metrics"]["stutter_reference_ms"], ref)
        self.assertGreater(sets[1]["mean"]["avg_fps"], sets[0]["mean"]["avg_fps"])
        self.assertAlmostEqual(sets[0]["stats"]["avg_fps"]["mean"], sets[0]["mean"]["avg_fps"])

    def test_ranges_overlap(self):
        self.assertTrue(cc.ranges_overlap({"min": 1, "max": 3}, {"min": 3, "max": 5}))
        self.assertFalse(cc.ranges_overlap({"min": 1, "max": 2}, {"min": 3, "max": 5}))


class Rows(unittest.TestCase):
    def test_second_set_is_coloured_against_the_first(self):
        (sets, _), *_ = two_sets()
        headers, rows = cc.uplift_rows(PRESET, sets)
        delta = dict(zip(headers, rows[0]["cells"]))
        self.assertEqual(rows[0]["label"], "Other vs Baseline")
        self.assertTrue(delta["AVG FPS"][0].startswith("+"))
        self.assertEqual(delta["AVG FPS"][1], "improved")
        check = dict(zip(headers, rows[1]["cells"]))
        self.assertEqual(check["AVG FPS"][0], "outside spread")

    def test_overlapping_sets_are_within_spread(self):
        (sets, _), *_ = two_sets(slow=2.0, fast=2.005)
        _, rows = cc.uplift_rows(PRESET, sets)
        self.assertTrue(all(text in ("within spread", "outside spread", "n/a") for text, _ in rows[1]["cells"]))
        avg = dict(zip([c["header"] for c in PRESET["capframex_compare"]["uplift"]], rows[1]["cells"]))["AVG FPS"]
        self.assertEqual(avg[0], "within spread")

    def test_system_differences_come_first(self):
        (sets, _), *_ = two_sets()
        rows = cc.system_diff(PRESET, sets)
        self.assertEqual(rows[0][0], "Game Mode")
        self.assertEqual((rows[0][1], rows[0][2], rows[0][3]), ("Disabled", "Enabled", True))
        self.assertIn("Captured", [r[0] for r in rows[:2]])

    def test_constant_sensor_is_not_compared(self):
        live = [2800.0, 2830.0, 2810.0, 2820.0, 2840.0]
        (sets, _), *_ = two_sets(clock=live)
        rows = {label: (a, b, delta) for label, a, b, delta in cc.sensor_compare_rows(PRESET, sets)}
        a, b, delta = rows["GPU core clock"]
        self.assertIn("†", a)
        self.assertNotIn("†", b)
        self.assertEqual(delta, "n/a †")
        self.assertRegex(rows["GPU load"][2], r"^[+-]")        # live sensors are compared

    def test_runs_table_has_means_and_spreads(self):
        (sets, _), *_ = two_sets()
        _, rows = cc.runs_table(PRESET, sets)
        self.assertEqual([r["kind"] for r in rows], ["run"] * 3 + ["mean", "spread"] + ["run"] * 3 + ["mean", "spread"])


class Distribution(unittest.TestCase):
    def test_curves_rise_towards_the_slow_end(self):
        (sets, _), *_ = two_sets()
        xs, curves = cc.distribution_curves(PRESET, sets)
        self.assertEqual(len(xs), PRESET["capframex_compare"]["distribution"]["points"])
        for curve in curves:
            for run in curve["runs"]:
                self.assertEqual(run, sorted(run))
        self.assertGreater(curves[0]["mean"][0], curves[1]["mean"][0])   # baseline is slower at the median


class Html(unittest.TestCase):
    def test_contents(self):
        (sets, ref), *_ = two_sets()
        html = cc.render_html(PRESET, sets, ref)
        for needle in ("Comparison: Baseline vs Other", "Baseline · mean of 3 runs", "--passes:2",
                       "FRAME TIME DISTRIBUTION", "Run-to-run check", "outside spread", ">ALL RUNS<",
                       "differs", "Stutter threshold for both sets"):
            self.assertIn(needle, html)
        self.assertNotIn("SECRET-HOST", html)

    def test_labels_are_escaped(self):
        a = [write("x", 2.4)]
        b = [write("y", 2.0)]
        sets, ref = cc.build_sets([('<i onmouseover="x">', a), ("ok", b)], PRESET)
        html = cc.render_html(PRESET, sets, ref)
        self.assertNotIn('<i onmouseover', html)


class Command(unittest.TestCase):
    def test_end_to_end(self):
        _, a, b = two_sets()
        out = Path(tempfile.mkdtemp())
        rc = cli.main(["capframex-compare", "--set", "Baseline", *map(str, a), "--set", "Other", *map(str, b),
                       "--out", str(out / "c.html"), "--json", str(out / "c.json")])
        self.assertEqual(rc, 0)
        data = json.loads((out / "c.json").read_text())
        self.assertEqual(data["baseline"], "Baseline")
        self.assertGreater(data["delta_pct"]["avg_fps"], 0)
        self.assertTrue(data["outside_run_spread"]["avg_fps"])
        self.assertNotIn("SECRET-HOST", json.dumps(data))
        self.assertTrue((out / "c.html").read_text(encoding="utf-8").startswith("<!doctype html>"))

    def test_needs_exactly_two_sets(self):
        _, a, b = two_sets()
        self.assertEqual(cli.main(["capframex-compare", "--set", "Only", *map(str, a)]), 2)
        self.assertEqual(cli.main(["capframex-compare", "--set", "OnlyLabel", "--set", "B", *map(str, b)]), 2)

    def test_shared_reference_option_matches_the_comparison(self):
        _, a, b = two_sets()
        out = Path(tempfile.mkdtemp())
        (sets, ref), _, _ = two_sets()
        for name, files in (("a", a), ("b", b)):
            self.assertEqual(cli.main(["capframex-report", *map(str, files), "--stutter-reference-ms", repr(ref),
                                       "--out", str(out / f"{name}.html"), "--json", str(out / f"{name}.json")]), 0)
        for name in ("a", "b"):
            for run in json.loads((out / f"{name}.json").read_text()):
                self.assertAlmostEqual(run["metrics"]["stutter_reference_ms"], ref)
                self.assertAlmostEqual(run["metrics"]["stutter_threshold_ms"], 2.5 * ref)


if __name__ == "__main__":
    unittest.main()

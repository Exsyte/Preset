import json
import tempfile
import unittest
from pathlib import Path

from presetmon2 import capframex, cli, metrics
from presetmon2.preset import load_preset

PRESET = load_preset()
CFG = PRESET["capframex"]


def capture(n=6, **overrides):
    data = {
        "TimeInSeconds": [i * 0.002 for i in range(n)],
        "MsBetweenPresents": [2.0 + i * 0.5 for i in range(n)],
        "MsInPresentAPI": [0.1] * n,
        "MsBetweenDisplayChange": [2.0] * n,
        "MsUntilRenderComplete": [0.0] * n,
        "MsUntilDisplayed": [3.0 + i for i in range(n)],
        "QPCTime": [0] * n,
        "PresentMode": [3] * n,
        "SyncInterval": [0] * n,
        "Dropped": [False] * n,
        "PcLatency": [6.0] * n,
        "AnimationError": [-1.0, 1.0] * (n // 2),
        "GpuActive": [1.5] * n,
        "CpuActive": [0.5] * n,
    }
    data.update(overrides)
    return data


def write_json(runs, info=None):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump({"Info": info or {"ProcessName": "cs2.exe", "Comment": "t"},
               "Runs": [{"CaptureData": r} for r in runs]}, tmp)
    tmp.close()
    return Path(tmp.name)


class Convert(unittest.TestCase):
    def convert(self, cap, info=None):
        header, rows, notes = capframex.convert_run(info or {"ProcessName": "cs2.exe"}, cap, CFG)
        path = Path(tempfile.mkdtemp()) / "out.csv"
        capframex.write_csv(path, header, rows)
        return header, rows, notes, path

    def test_header_matches_example_csv_plus_extras(self):
        header, *_ = self.convert(capture())
        self.assertEqual(header[:23], [
            "Application", "SyncInterval", "PresentMode", "TimeInMs", "MsBetweenSimulationStart",
            "MsBetweenPresents", "MsBetweenDisplayChange", "MsInPresentAPI", "MsRenderPresentLatency",
            "MsUntilDisplayed", "CPUStartTimeInMs", "MsBetweenAppStart", "MsCPUBusy", "MsCPUWait",
            "MsGPULatency", "MsGPUTime", "MsGPUBusy", "MsGPUWait", "MsAnimationError", "AnimationTime",
            "MsFlipDelay", "MsAllInputToPhotonLatency", "MsClickToPhotonLatency"])

    def test_round_trips_through_the_presentmon_reader(self):
        cap = capture()
        *_, path = self.convert(cap)
        read = metrics.read_capture(path, PRESET["csv"])
        self.assertEqual(read.frametime_ms, cap["MsBetweenPresents"])
        self.assertEqual(read.series["pc_latency_ms"], cap["MsUntilDisplayed"])
        self.assertEqual(read.series["gpu_busy_ms"], cap["GpuActive"])
        self.assertEqual(read.series["animation_error_ms"], cap["AnimationError"])
        self.assertFalse(read.input_detected)

    def test_time_is_cumulative_present_time(self):
        cap = capture()
        *_, path = self.convert(cap)
        read = metrics.read_capture(path, PRESET["csv"])
        self.assertAlmostEqual(read.time_ms[-1], sum(cap["MsBetweenPresents"]))
        self.assertAlmostEqual(read.time_ms[0], cap["MsBetweenPresents"][0])

    def test_unavailable_columns_are_na(self):
        header, rows, _, path = self.convert(capture())
        read = metrics.read_capture(path, PRESET["csv"])
        self.assertEqual(read.series["gpu_latency_ms"], [])
        self.assertEqual(read.series["gpu_wait_ms"], [])
        self.assertEqual(rows[0][header.index("MsGPULatency")], "NA")

    def test_fixed_columns(self):
        header, rows, *_ = self.convert(capture())
        row = dict(zip(header, rows[0]))
        self.assertEqual((row["Application"], row["SyncInterval"], row["PresentMode"]),
                         ("cs2.exe", "0", "Hardware: Independent Flip"))
        self.assertEqual(row["MsPCLatency"], "6.0000")
        self.assertEqual(row["CapFrameXTimeInMs"], "0.0000")

    def test_unknown_present_mode(self):
        header, rows, *_ = self.convert(capture(PresentMode=[42] * 6))
        self.assertEqual(rows[0][header.index("PresentMode")], "Unknown (42)")

    def test_all_zero_and_missing_fields_become_na_with_notes(self):
        cap = capture(GpuActive=[0.0] * 6)
        del cap["PcLatency"]
        header, rows, notes, path = self.convert(cap)
        self.assertEqual(metrics.read_capture(path, PRESET["csv"]).series["gpu_busy_ms"], [])
        self.assertTrue(any("MsGPUBusy" in n and "all zero" in n for n in notes))
        self.assertTrue(any("MsPCLatency" in n and "missing" in n for n in notes))

    def test_sync_interval_zero_is_kept(self):
        header, rows, *_ = self.convert(capture())
        self.assertEqual(rows[0][header.index("SyncInterval")], "0")

    def test_dropped_frames_have_no_display_metrics(self):
        header, rows, *_ = self.convert(capture(Dropped=[False, True] + [False] * 4))
        dropped = dict(zip(header, rows[1]))
        self.assertEqual((dropped["MsUntilDisplayed"], dropped["MsBetweenDisplayChange"],
                          dropped["MsPCLatency"]), ("NA", "NA", "NA"))
        self.assertNotEqual(dict(zip(header, rows[0]))["MsUntilDisplayed"], "NA")
        self.assertEqual(dropped["MsBetweenPresents"], "2.5000")  # frametime is still real

    def test_rejects_non_capframex_json(self):
        path = Path(tempfile.mkdtemp()) / "x.json"
        path.write_text('{"hello": 1}')
        with self.assertRaisesRegex(ValueError, "not a CapFrameX"):
            capframex.load_runs(path)


class ConvertCommand(unittest.TestCase):
    def run_cli(self, *argv):
        self.assertEqual(cli.main(list(argv)), 0)

    def test_as_names_runs_after_preset_passes(self):
        sources = [write_json([capture(6)]), write_json([capture(8)])]
        out = Path(tempfile.mkdtemp())
        self.run_cli("convert", *map(str, sources), "--out-dir", str(out), "--as", "after,after_second")
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["benchmark_after.csv", "benchmark_after2.csv"])
        read = metrics.read_capture(out / "benchmark_after2.csv", PRESET["csv"])
        self.assertEqual(len(read.frametime_ms), 8)

    def test_merged_file_gives_one_csv_per_run(self):
        source = write_json([capture(6), capture(8), capture(10)])
        out = Path(tempfile.mkdtemp())
        self.run_cli("convert", str(source), "--out-dir", str(out))
        names = sorted(p.name for p in out.iterdir())
        self.assertEqual(names, [f"{source.stem}_run{i}.csv" for i in (1, 2, 3)])

    def test_default_output_is_next_to_input(self):
        source = write_json([capture(6)])
        self.run_cli("convert", str(source))
        self.assertTrue(source.with_suffix(".csv").is_file())

    def test_bad_arguments_exit_non_zero(self):
        source = write_json([capture(6), capture(6)])
        self.assertEqual(cli.main(["convert", str(source), "--as", "nope"]), 2)
        self.assertEqual(cli.main(["convert", str(source), "--as", "after"]), 2)  # fewer keys than runs


class ReportPassOverride(unittest.TestCase):
    def test_pass_overrides_pick_the_csv(self):
        d = Path(tempfile.mkdtemp())
        for name, n in (("a", 6), ("b", 8)):
            h, rows, _ = capframex.convert_run({"ProcessName": "cs2.exe"}, capture(n), CFG)
            capframex.write_csv(d / f"{name}.csv", h, rows)
        out = d / "r.html"
        rc = cli.main(["report", "--dir", str(d), "--pass", f"before={d / 'a.csv'}",
                       "--pass", f"after={d / 'b.csv'}", "--out", str(out), "--json", str(d / "r.json"),
                       "--id", "T-1"])
        self.assertEqual(rc, 0)
        results = json.loads((d / "r.json").read_text())
        self.assertEqual(list(results["passes"]), ["before", "after"])
        self.assertEqual(results["passes"]["after"]["frame_count"], 8)
        self.assertIn("Benchmark ID: T-1", out.read_text(encoding="utf-8"))

    def test_bad_override_is_an_error(self):
        self.assertEqual(cli.main(["report", "--pass", "nonsense=x.csv"]), 2)
        self.assertEqual(cli.main(["report", "--pass", "before"]), 2)


if __name__ == "__main__":
    unittest.main()

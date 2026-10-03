"""The comparison/presentation rules must reproduce the FrameCap example report.

Fixtures: example_metrics.json is benchmark_previous.json minus the frametimes;
example_report_expected.json is what benchmark_report.html displays.
"""

import json
import unittest
from pathlib import Path

from presetmon2 import compare, report
from presetmon2.preset import load_preset

FIXTURES = Path(__file__).parent / "fixtures"
PRESET = load_preset()
METRICS = json.loads((FIXTURES / "example_metrics.json").read_text())
EXPECTED = json.loads((FIXTURES / "example_report_expected.json").read_text())


def example_passes():
    return [dict(spec, csv_path=Path(spec["csv"]), metrics=METRICS["passes"][spec["key"]], chart=None)
            for spec in PRESET["capture"]["passes"]]


class ExampleParity(unittest.TestCase):
    def setUp(self):
        self.view = compare.build_view(PRESET, example_passes())

    def test_tiles(self):
        for column, spec in zip(self.view["columns"], PRESET["capture"]["passes"]):
            got = [(t["label"], t["text"], t["class"]) for g in column["groups"] for t in g["tiles"]]
            want = [(t["label"], t["text"], t["class"]) for t in EXPECTED["tiles"][spec["key"]]]
            self.assertEqual(got, want, spec["key"])

    def test_uplift_table(self):
        self.assertEqual(self.view["uplift_headers"], EXPECTED["headers"][1:])
        colors = PRESET["report"]["colors"]
        self.assertEqual(len(self.view["uplift_rows"]), len(EXPECTED["table"]))
        for row, want in zip(self.view["uplift_rows"], EXPECTED["table"]):
            self.assertEqual(row["label"], want["row"])
            self.assertEqual([(text, colors[klass]) for text, klass in row["cells"]],
                             [(c["text"], c["color"]) for c in want["cells"]], row["label"])

    def test_html_contains_example_values(self):
        csvs = [(p["capture_label"], p["csv_path"]) for p in example_passes()]
        html = report.render_html(PRESET, self.view, METRICS["benchmark_id"], csvs)
        for needle in ("Benchmark ID: TINYBOOST-678915A9", ">515.0<", ">0.88%<", ">TinyBoost 3 vs BEFORE<",
                       ">Average vs BEFORE<", "Results captured with PresentMon 2", "--passes:4"):
            self.assertIn(needle, html)

    def test_html_escapes_labels(self):
        passes = example_passes()
        passes[1]["label"] = '<img src=x onerror="alert(1)">'
        view = compare.build_view(PRESET, passes)
        html = report.render_html(PRESET, view, "ID", [])
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;img src=x", html)


class Rules(unittest.TestCase):
    CLS = PRESET["report"]["classification"]
    FPS = {"decimals": 1, "suffix": "", "better": "higher"}
    MS = {"decimals": 2, "suffix": " ms", "better": "lower"}

    def test_equal_displayed_value_is_neutral(self):
        self.assertEqual(compare.tile_class(3.8106, 3.8350, {**self.MS, "decimals": 1}, self.CLS), "neutral")

    def test_regression_severity(self):
        self.assertEqual(compare.tile_class(100.0, 99.0, self.FPS, self.CLS), "slightly-regressed")
        self.assertEqual(compare.tile_class(100.0, 90.0, self.FPS, self.CLS), "regressed")
        self.assertEqual(compare.tile_class(100.0, 101.0, self.FPS, self.CLS), "improved")
        self.assertEqual(compare.tile_class(1.0, 1.5, self.MS, self.CLS), "regressed")   # lower-is-better, +50%
        self.assertEqual(compare.tile_class(1.0, 0.9, self.MS, self.CLS), "improved")

    def test_missing_values(self):
        self.assertEqual(compare.format_tile(None, self.MS), "n/a")
        self.assertEqual(compare.tile_class(None, 1.0, self.MS, self.CLS), "neutral")
        col = {"mode": "percent", "better": "higher"}
        self.assertEqual(compare.uplift_cell(None, 1.0, col, self.CLS), ("n/a", "neutral"))

    def test_uplift_cells(self):
        pct = {"mode": "percent", "better": "higher"}
        self.assertEqual(compare.uplift_cell(100.0, 99.8, pct, self.CLS), ("+0%", "neutral"))
        self.assertEqual(compare.uplift_cell(100.0, 91.0, pct, self.CLS), ("-9%", "regressed"))
        self.assertEqual(compare.uplift_cell(100.0, 99.0, pct, self.CLS), ("-1%", "slightly-regressed"))
        ms = {"mode": "ms_delta", "better": "lower"}
        self.assertEqual(compare.uplift_cell(1.00, 1.0098, ms, self.CLS), ("+0.01 ms", "slightly-regressed"))
        self.assertEqual(compare.uplift_cell(1.00, 0.90, ms, self.CLS), ("-0.10 ms", "improved"))
        self.assertEqual(compare.uplift_cell(1.00, 1.0004, ms, self.CLS), ("+0.00 ms", "neutral"))


if __name__ == "__main__":
    unittest.main()

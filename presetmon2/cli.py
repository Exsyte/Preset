"""Command line: `python -m presetmon2 {report,metrics,verify}`."""

import argparse
import json
import math
import sys
import uuid
from pathlib import Path

from . import compare, metrics, report
from .preset import load_preset, output_dir, pass_specs


def _new_benchmark_id(preset):
    cfg = preset["benchmark_id"]
    return f"{cfg['prefix']}-{uuid.uuid4().hex[:cfg['hex_digits']].upper()}"


def _benchmark_id(preset, directory, override):
    if override:
        return override
    id_file = Path(directory) / preset["benchmark_id"]["file"]
    if id_file.is_file():
        text = id_file.read_text(encoding="utf-8-sig").strip()
        if text:
            return text
    return _new_benchmark_id(preset)


def _load_passes(preset, directory):
    """Read every pass CSV that exists; BEFORE must be present."""
    specs = pass_specs(preset)
    csv_cfg, mcfg = preset["csv"], preset["metrics"]
    captures = {}
    for spec in specs:
        path = Path(directory) / spec["csv"]
        if path.is_file():
            captures[spec["key"]] = (spec, path, metrics.read_capture(path, csv_cfg))
        else:
            print(f"warning: {path} not found - skipping '{spec['label']}'", file=sys.stderr)

    ref_key = mcfg["stutter"]["reference_pass"]
    if ref_key not in captures:
        raise SystemExit(f"error: the '{ref_key}' capture is required as the comparison baseline")
    if len(captures) < 2:
        raise SystemExit("error: need the BEFORE capture and at least one AFTER capture")

    ref_spec, _, ref_capture = captures[ref_key]
    ref_avg = math.fsum(ref_capture.frametime_ms) / len(ref_capture.frametime_ms)
    passes = []
    for spec in specs:
        if spec["key"] not in captures:
            continue
        _, path, capture = captures[spec["key"]]
        passes.append({
            "key": spec["key"], "label": spec["label"], "capture_label": spec["capture_label"],
            "csv_path": path, "capture": capture,
            "metrics": metrics.compute_metrics(capture, mcfg, ref_avg),
            "chart": metrics.chart_data(capture, mcfg["chart"]),
        })
    return passes


def _write_json(path, preset, benchmark_id, passes, include_frametimes):
    out = {"version": 1, "benchmark_id": benchmark_id, "preset": preset["name"], "passes": {}}
    for p in passes:
        entry = dict(p["metrics"], label=p["label"], csv=str(p["csv_path"]))
        if include_frametimes:
            entry["frametimes_ms"] = p["capture"].frametime_ms
        out["passes"][p["key"]] = entry
    Path(path).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")


def cmd_report(args):
    preset = load_preset(args.preset)
    directory = Path(args.dir) if args.dir else output_dir(preset)
    passes = _load_passes(preset, directory)
    benchmark_id = _benchmark_id(preset, directory, args.id)
    view = compare.build_view(preset, passes)
    csv_paths = [(p["capture_label"], p["csv_path"]) for p in passes]
    html = report.render_html(preset, view, benchmark_id, csv_paths)

    out = Path(args.out) if args.out else directory / "benchmark_report.html"
    out.write_text(html, encoding="utf-8")
    json_out = Path(args.json) if args.json else directory / "benchmark_results.json"
    _write_json(json_out, preset, benchmark_id, passes, args.include_frametimes)
    print(f"report: {out}\nresults: {json_out}\nbenchmark id: {benchmark_id}")


def cmd_metrics(args):
    preset = load_preset(args.preset)
    for path in args.csv:
        capture = metrics.read_capture(path, preset["csv"])
        result = metrics.compute_metrics(capture, preset["metrics"])
        print(json.dumps({"file": str(path), **result}, indent=2))


# Metrics derivable from frametimes alone - the ones `verify` can recompute.
_FRAMETIME_METRICS = ("avg_fps", "low1_fps", "p1_fps", "low01_fps", "p01_fps",
                      "stutter_time_pct", "avg_frametime_ms", "duration_secs", "frame_count")


# Additionally derived from the PresentMon CSV columns - checked with --csv-dir.
_CSV_METRICS = _FRAMETIME_METRICS + (
    "animation_error_avg_ms", "gpu_latency_avg_ms", "gpu_busy_avg_ms", "gpu_wait_avg_ms",
    "pc_latency_avg_ms", "pc_latency_p99_ms")


def _verify_csvs(preset, data, directory, tolerance):
    """Compute every metric from the real pass CSVs and compare with the stored values."""
    mcfg = preset["metrics"]
    captures = {}
    for spec in pass_specs(preset):
        path = Path(directory) / spec["csv"]
        if spec["key"] in data and path.is_file():
            captures[spec["key"]] = (spec, metrics.read_capture(path, preset["csv"]))
    ref_key = mcfg["stutter"]["reference_pass"]
    if ref_key not in captures:
        raise ValueError(f"{directory}: the '{ref_key}' CSV is required")
    ref_frames = captures[ref_key][1].frametime_ms
    ref_avg = math.fsum(ref_frames) / len(ref_frames)

    failures = 0
    for key, (spec, capture) in captures.items():
        got = metrics.compute_metrics(capture, mcfg, ref_avg)
        print(f"{spec['label']} ({spec['csv']}) - all metrics from the CSV:")
        for name in _CSV_METRICS:
            want, have = data[key][name], got[name]
            ok = have is not None and math.isclose(want, have, rel_tol=tolerance, abs_tol=1e-9)
            failures += not ok
            shown = "None" if have is None else f"{have:.10g}"
            print(f"  {'ok  ' if ok else 'FAIL'} {name:24s} stored={want:<22.10g} computed={shown}")
    return failures


def cmd_verify(args):
    """Recompute metrics from a benchmark_previous.json (and optionally the CSVs) and compare."""
    preset = load_preset(args.preset)
    mcfg = preset["metrics"]
    data = json.loads(Path(args.previous).read_text(encoding="utf-8-sig"))["benchmark"]
    specs = pass_specs(preset)
    ref = data[mcfg["stutter"]["reference_pass"]]
    ref_avg = math.fsum(ref["frametimes_ms"]) / len(ref["frametimes_ms"])

    failures, passes = 0, []
    for spec in specs:
        stored = data.get(spec["key"])
        if not stored:
            continue
        capture = metrics.Capture(frametime_ms=stored["frametimes_ms"])
        got = metrics.compute_metrics(capture, mcfg, ref_avg)
        print(f"{spec['label']}:")
        for key in _FRAMETIME_METRICS:
            want, have = stored[key], got[key]
            ok = math.isclose(want, have, rel_tol=args.tolerance, abs_tol=1e-9)
            failures += not ok
            print(f"  {'ok  ' if ok else 'FAIL'} {key:18s} stored={want:<22.10g} computed={have:.10g}")
        # Report the stored (app-computed) values so the output can be eyeballed
        # against the example, charts included.
        merged = dict(got, **{k: v for k, v in stored.items() if k != "frametimes_ms"})
        merged.update({k: got[k] for k in ("frametime_min_ms", "frametime_p99_ms", "frametime_max_ms")})
        passes.append({"key": spec["key"], "label": spec["label"],
                       "capture_label": spec["capture_label"],
                       "csv_path": Path(spec["csv"]), "metrics": merged,
                       "chart": metrics.chart_data(capture, mcfg["chart"])})

    if args.report:
        view = compare.build_view(preset, passes)
        html = report.render_html(preset, view, data.get("benchmark_id", "UNKNOWN"),
                                  [(p["capture_label"], p["csv_path"]) for p in passes])
        Path(args.report).write_text(html, encoding="utf-8")
        print(f"report rendered from stored metrics: {args.report}")
    if args.csv_dir:
        failures += _verify_csvs(preset, data, args.csv_dir, args.csv_tolerance)
    print("PASS" if not failures else f"{failures} metric(s) differ")
    return 1 if failures else 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="presetmon2", description=__doc__)
    parser.add_argument("--preset", help="preset JSON (default: the bundled preset.json)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("report", help="build the HTML report + results JSON from PresentMon 2 CSVs")
    p.add_argument("--dir", help="folder with the pass CSVs (default: preset capture.output_dir)")
    p.add_argument("--out", help="HTML output path (default: <dir>/benchmark_report.html)")
    p.add_argument("--json", help="results JSON path (default: <dir>/benchmark_results.json)")
    p.add_argument("--id", help="benchmark id (default: <dir>/benchmark_id.txt, else generated)")
    p.add_argument("--include-frametimes", action="store_true",
                   help="embed the per-frame frametimes in the results JSON")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("metrics", help="print the statistics of one or more CSVs as JSON")
    p.add_argument("csv", nargs="+")
    p.set_defaults(func=cmd_metrics)

    p = sub.add_parser("verify", help="check the maths against an example benchmark_previous.json")
    p.add_argument("previous", help="path to benchmark_previous.json")
    p.add_argument("--report", help="also render a report from the stored metrics to this path")
    p.add_argument("--tolerance", type=float, default=1e-6, help="relative tolerance (default 1e-6)")
    p.add_argument("--csv-dir", help="folder with the example benchmark_*.csv files: also check "
                                     "the metrics that come from the CSV columns (latency, GPU, ...)")
    p.add_argument("--csv-tolerance", type=float, default=1e-4,
                   help="relative tolerance for --csv-dir (default 1e-4)")
    p.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    try:
        return args.func(args) or 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

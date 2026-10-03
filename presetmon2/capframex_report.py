"""HTML export of CapFrameX captures in the PresentMon benchmark report layout.

Every run in the given CapFrameX files becomes a column (frame rate, latency, CPU/GPU
time, frame-time chart), followed by a run-comparison table, the system the captures
were taken on and the sensor summary. No baseline is assumed, so nothing is coloured
as better or worse.
"""

import math
from html import escape
from pathlib import Path

from . import capframex, metrics, report
from .compare import format_tile


def _mean(values):
    return math.fsum(values) / len(values) if values else None


def _run_label(info, number, runs_in_file, override):
    if override:
        return override
    comment = (info.get("Comment") or "").strip()
    if comment.lower().endswith(" run"):
        comment = comment[:-4].rstrip()
    if not comment:
        return f"Run {number}"
    return f"{comment} (run {number})" if runs_in_file > 1 else comment


def _created(info):
    stamp = info.get("CreationDate") or ""
    if len(stamp) >= 16 and stamp.endswith("Z"):
        return f"{stamp[:10]} {stamp[11:16]} UTC"
    return stamp


def load_runs(paths, preset, labels=None):
    """Read the CapFrameX files into run dicts (no metrics yet)."""
    runs = []
    for path in paths:
        info, file_hash, file_runs = capframex.load_file(path)
        for number, raw in enumerate(file_runs, 1):
            capture, notes = capframex.to_capture(raw["CaptureData"], preset)
            override = labels[len(runs)] if labels and len(runs) < len(labels) else None
            runs.append({
                "label": _run_label(info, number, len(file_runs), override),
                "source": Path(path).name, "info": info, "file_hash": file_hash,
                "capture": capture, "notes": notes,
                "sensors": list((raw.get("SensorData2") or {}).values()),
            })
    if labels and len(labels) != len(runs):
        raise ValueError(f"--label given {len(labels)} time(s) but {len(runs)} run(s) were loaded")
    return runs


def common_reference_ms(runs):
    """Mean of the runs' average frametimes: the shared stutter reference."""
    return _mean([_mean(r["capture"].frametime_ms) for r in runs])


def compute_runs(runs, preset, reference_ms):
    """Add metrics, chart data and sensor summaries to every run.

    Stuttering uses one threshold for all runs: threshold_multiplier x reference_ms
    (a BEFORE pass does not exist here, so the reference is the mean frametime of the
    runs being shown/compared).
    """
    multiplier = preset["metrics"]["stutter"]["threshold_multiplier"]
    for r in runs:
        cap = r["capture"]
        m = metrics.compute_metrics(cap, preset["metrics"], reference_ms)
        pcl = cap.extra.get("MsPCLatency", [])
        m["pcl_avg_ms"] = _mean(pcl)
        m["pcl_p99_ms"] = metrics.nearest_rank(sorted(pcl), 99.0) if pcl else None
        m["cpu_busy_avg_ms"] = _mean(cap.extra.get("MsCPUBusy", []))
        m["in_present_avg_ms"] = _mean(cap.extra.get("MsInPresentAPI", []))
        m["stutter_reference_ms"] = reference_ms
        m["stutter_threshold_ms"] = multiplier * reference_ms
        r["metrics"] = m
        r["chart"] = metrics.chart_data(cap, preset["metrics"]["chart"])
        r["sensor_summary"] = [summarize_sensor(r["sensors"], spec)
                               for spec in preset["capframex_report"]["sensors"]]
    return runs


def collect_runs(paths, preset, labels=None, reference_ms=None):
    """Load every run from the CapFrameX files and compute its metrics."""
    runs = load_runs(paths, preset, labels)
    return compute_runs(runs, preset, reference_ms or common_reference_ms(runs))


def stutter_tooltip(preset, metrics_):
    return preset["capframex_report"]["peer_reference_note"].format(
        threshold=metrics_["stutter_threshold_ms"], reference=metrics_["stutter_reference_ms"])


def _summarize(sensor):
    values = [v for v in sensor.get("Values") or [] if v is not None]
    if not values or not any(values):
        return None  # not readable (all zero) - leave it out rather than show a fake 0
    return {"avg": _mean(values), "min": min(values), "max": max(values)}


def summarize_sensor(sensors, spec):
    """avg/min/max of one sensor channel, or None when it is absent or all zero."""
    for sensor in sensors:
        if sensor.get("Type") == spec["type"] and sensor.get("Name") == spec["name"]:
            return _summarize(sensor)
    return None


def build_view(preset, runs):
    """Column data in the shape report._column_html expects (every tile neutral)."""
    xcfg = preset["capframex_report"]
    columns = []
    for r in runs:
        groups = []
        for group in xcfg["groups"]:
            tiles = []
            for tile in group["tiles"]:
                tooltip = stutter_tooltip(preset, r["metrics"]) if tile["tooltip"] == "@stutter" else tile["tooltip"]
                tiles.append({"label": tile["label"], "class": "neutral", "tooltip": tooltip,
                              "text": format_tile(r["metrics"].get(tile["metric"]), tile)})
            groups.append({"title": group["title"], "subtitle": group["subtitle"], "tiles": tiles})
        columns.append({"label": r["label"], "is_before": False, "groups": groups,
                        "input_detected": False, "chart": r["chart"], "metrics": r["metrics"]})
    return columns


def comparison_table(preset, runs):
    """Rows of formatted cells: every run, the mean of the runs and the spread (max - min)."""
    cols = preset["capframex_report"]["table"]["columns"]
    rows = [{"label": r["label"], "kind": "run",
             "cells": [format_tile(r["metrics"].get(c["metric"]), c) for c in cols]} for r in runs]
    means, spreads = [], []
    for c in cols:
        values = [r["metrics"].get(c["metric"]) for r in runs]
        values = [v for v in values if v is not None]
        means.append(format_tile(_mean(values), c) if values else "n/a")
        spreads.append(format_tile(max(values) - min(values), c) if values else "n/a")
    if len(runs) > 1:
        rows.append({"label": "Mean of runs", "kind": "mean", "cells": means})
        rows.append({"label": "Spread (max − min)", "kind": "spread", "cells": spreads})
    return [c["header"] for c in cols], rows


def system_rows(preset, runs):
    rows = []
    for spec in preset["capframex_report"]["system"]:
        seen = []
        for r in runs:
            parts = [str(r["info"].get(f)) for f in spec["fields"] if r["info"].get(f) not in (None, "")]
            text = (spec.get("prefix", "") + " ".join(parts)) if parts else ""
            if text and text not in seen:
                seen.append(text)
        if seen:
            rows.append((spec["label"], " / ".join(seen)))
    return rows


def _sensor_cell(summary, spec):
    if summary is None:
        return "—"
    d, unit = spec["decimals"], spec["unit"]
    main = f"{summary['avg']:.{d}f} {escape(unit)}"
    if round(summary["min"], d) == round(summary["max"], d):
        detail = "constant"
    else:
        detail = f"{summary['min']:.{d}f} – {summary['max']:.{d}f}"
    return f"{main}<small>{detail}</small>"


def render_html(preset, runs):
    xcfg = preset["capframex_report"]
    rcfg = preset["report"]
    css, js, logo = report.page_assets(preset, extra_css="capframex.css")

    columns = build_view(preset, runs)
    chart_cfg = preset["metrics"]["chart"]
    grid = "".join(report._column_html(c, chart_cfg) for c in columns)

    headers, table_rows = comparison_table(preset, runs)
    thead = "".join(f"<th>{escape(h)}</th>" for h in headers)
    tbody = []
    for row in table_rows:
        klass = {"mean": ' class="avg-row"', "spread": ' class="spread"'}.get(row["kind"], "")
        cells = "".join(f"<td>{escape(c)}</td>" for c in row["cells"])
        tbody.append(f'<tr{klass}><td class="rl">{escape(row["label"])}</td>{cells}</tr>')

    system = "".join(f"<dt>{escape(k)}</dt><dd>{escape(v)}</dd>" for k, v in system_rows(preset, runs))

    sensor_head = "".join(f"<th>{escape(r['label'])}</th>" for r in runs)
    sensor_body = []
    for index, spec in enumerate(xcfg["sensors"]):
        cells = [r["sensor_summary"][index] for r in runs]
        if all(c is None for c in cells):
            continue
        tds = "".join(f"<td>{_sensor_cell(c, spec)}</td>" for c in cells)
        sensor_body.append(f'<tr><td class="rl">{escape(spec["label"])}</td>{tds}</tr>')

    files = report.csv_rows_html([(r["label"], r["source"]) for r in runs])
    meta = "".join(
        f'<div class="capture-meta">{escape(r["label"])}: {_created(r["info"])} · '
        f'{r["metrics"]["frame_count"]:,} frames · {r["metrics"]["duration_secs"]:.1f} s</div>'
        for r in runs)
    first = runs[0]
    version = first["info"].get("AppVersion") or ""
    heading = xcfg["capture_heading"].format(version=version).strip()
    benchmark_id = "CAPFRAMEX-" + (first["file_hash"][:8].upper() or "UNKNOWN")

    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{escape(xcfg["page_title"])}</title><style>{css}</style></head><body>'
        f'<div class="wrap"><header class="report-header"><h1>{escape(rcfg["heading"])}{logo}</h1>'
        f'<div class="bid">Benchmark ID: {escape(benchmark_id)}</div></header>'
        f'<div class="grid" style="--passes:{len(columns)}">{grid}</div>'
        '<div class="summary-row"><section class="uplift cmp">'
        f'<div class="section-label">{escape(xcfg["table"]["title"])}</div><table>'
        f'<thead><tr><th></th>{thead}</tr></thead><tbody>{"".join(tbody)}</tbody></table></section></div>'
        '<div class="panels"><section class="panel"><h2>System</h2>'
        f'<dl class="kv">{system}</dl></section>'
        '<section class="panel uplift sensors"><h2>Sensors</h2><table>'
        f'<thead><tr><th></th>{sensor_head}</tr></thead><tbody>{"".join(sensor_body)}</tbody></table>'
        '<div class="note-line">Average per run, with the min – max range underneath.</div></section></div>'
        '<div class="summary-row"><footer class="foot"><div>'
        f'<h2>{escape(heading)}</h2><div class="capture-label">{escape(xcfg["capture_label"])}</div>'
        f'{files}{meta}</div><div class="note">{xcfg["note"]}</div></footer></div></div>'
        f"<script>{js}</script></body></html>\n"
    )


def export_json(runs):
    """Machine-readable results for every run (metrics, sensors, system info, notes)."""
    out = []
    for r in runs:
        sensors = {}
        for sensor in r["sensors"]:
            if sensor.get("Type") == "Time":
                continue
            summary = _summarize(sensor)
            if summary:
                sensors[f"{sensor.get('Type')}/{sensor.get('Name')}"] = summary
        info = {k: v for k, v in r["info"].items() if k != "DeviceName"}  # keep the hostname out
        out.append({"label": r["label"], "source": r["source"], "info": info,
                    "metrics": dict(r["metrics"]), "sensors": sensors, "notes": r["notes"]})
    return out

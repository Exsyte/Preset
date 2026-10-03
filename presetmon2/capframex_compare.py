"""Compare two sets of CapFrameX captures (e.g. two configurations) in one HTML sheet.

Each set is the mean of its runs. The first set is the baseline; the second is coloured
relative to it with the same rules as the PresentMon benchmark report. The sheet also
shows the individual runs, whether the difference is bigger than the run-to-run spread,
how the systems differ, a sensor comparison and a frame-time distribution chart.
"""

import math
from html import escape

from . import capframex_report as cr
from . import compare, report
from .compare import format_tile

SET_COLORS = ("#ffbe19", "#36aeed")  # baseline = amber, second set = cyan (same as the column borders)


def build_sets(specs, preset, reference_ms=None):
    """specs: [(label, [paths])...] -> (sets, reference_ms). Every run gets metrics."""
    loaded = [(label, cr.load_runs(paths, preset)) for label, paths in specs]
    everything = [r for _, runs in loaded for r in runs]
    reference = reference_ms or cr.common_reference_ms(everything)
    sets = []
    for label, runs in loaded:
        cr.compute_runs(runs, preset, reference)
        sets.append({"label": label, "runs": runs})
    for s in sets:
        s["stats"] = aggregate(s["runs"], metric_keys(preset))
        s["mean"] = {k: v["mean"] for k, v in s["stats"].items() if v}
        s["sensors"] = aggregate_sensors(s["runs"], preset)
    return sets, reference


def metric_keys(preset):
    xcfg = preset["capframex_report"]
    keys = {t["metric"] for g in xcfg["groups"] for t in g["tiles"]}
    keys |= {c["metric"] for c in xcfg["table"]["columns"]}
    keys |= {c["metric"] for c in preset["capframex_compare"]["uplift"]}
    return sorted(keys)


def aggregate(runs, keys):
    stats = {}
    for key in keys:
        values = [r["metrics"].get(key) for r in runs if r["metrics"].get(key) is not None]
        stats[key] = ({"mean": math.fsum(values) / len(values), "min": min(values), "max": max(values)}
                      if values else None)
    return stats


def aggregate_sensors(runs, preset):
    """Per sensor: mean over runs of the per-run average, and whether it was 'flat'.

    flat = every run returned one single value for the whole capture (min == max), i.e. the
    sensor was not updating; such readings say nothing about the real value.
    """
    out = []
    for index in range(len(preset["capframex_report"]["sensors"])):
        summaries = [r["sensor_summary"][index] for r in runs if r["sensor_summary"][index]]
        if not summaries:
            out.append(None)
            continue
        out.append({"avg": math.fsum(x["avg"] for x in summaries) / len(summaries),
                    "flat": all(x["min"] == x["max"] for x in summaries)})
    return out


def ranges_overlap(a, b):
    """True when the [min, max] ranges of the two sets' runs overlap."""
    return a["max"] >= b["min"] and b["max"] >= a["min"]


def build_columns(preset, sets):
    """Two report columns (tiles from the set means), the second coloured against the first."""
    xcfg = preset["capframex_report"]
    cls_cfg = preset["report"]["classification"]
    base = sets[0]["mean"]
    columns = []
    for index, s in enumerate(sets):
        groups = []
        for group in xcfg["groups"]:
            tiles = []
            for tile in group["tiles"]:
                value = s["mean"].get(tile["metric"])
                klass = "baseline" if index == 0 else compare.tile_class(
                    base.get(tile["metric"]), value, tile, cls_cfg)
                tooltip = (cr.stutter_tooltip(preset, s["runs"][0]["metrics"])
                           if tile["tooltip"] == "@stutter" else tile["tooltip"])
                tiles.append({"label": tile["label"], "text": format_tile(value, tile),
                              "class": klass, "tooltip": tooltip})
            groups.append({"title": group["title"], "subtitle": group["subtitle"], "tiles": tiles})
        columns.append({"label": f"{s['label']} · mean of {len(s['runs'])} runs",
                        "is_before": index == 0, "groups": groups, "input_detected": False,
                        "chart": None, "metrics": s["mean"]})
    return columns


def uplift_rows(preset, sets):
    """[(headers, rows)]: the delta row (coloured) and the run-to-run check row."""
    cfg = preset["capframex_compare"]
    cls_cfg = preset["report"]["classification"]
    a, b = sets
    delta_cells, check_cells = [], []
    for col in cfg["uplift"]:
        key = col["metric"]
        delta_cells.append(compare.uplift_cell(a["mean"].get(key), b["mean"].get(key), col, cls_cfg))
        sa, sb = a["stats"][key], b["stats"][key]
        if sa is None or sb is None:
            check_cells.append(("n/a", "muted"))
        elif ranges_overlap(sa, sb):
            check_cells.append(("within spread", "muted"))
        else:
            check_cells.append(("outside spread", "neutral"))
    headers = [c["header"] for c in cfg["uplift"]]
    rows = [
        {"label": f"{b['label']} vs {a['label']}", "cells": delta_cells, "kind": "delta"},
        {"label": "Run-to-run check", "cells": check_cells, "kind": "check"},
    ]
    return headers, rows


def runs_table(preset, sets):
    """Every run, then each set's mean and spread, formatted like the single-set report."""
    cols = preset["capframex_report"]["table"]["columns"]
    rows = []
    for s in sets:
        for r in s["runs"]:
            rows.append({"label": r["label"], "kind": "run",
                         "cells": [format_tile(r["metrics"].get(c["metric"]), c) for c in cols]})
        rows.append({"label": f"{s['label']} · mean", "kind": "mean",
                     "cells": [format_tile(s["mean"].get(c["metric"]), c) for c in cols]})
        spread = []
        for c in cols:
            st = s["stats"][c["metric"]]
            spread.append(format_tile(st["max"] - st["min"], c) if st else "n/a")
        rows.append({"label": f"{s['label']} · spread", "kind": "spread", "cells": spread})
    return [c["header"] for c in cols], rows


def system_diff(preset, sets):
    """[(field, value A, value B, differs)] including when each set was captured."""
    rows_a = dict(cr.system_rows(preset, sets[0]["runs"]))
    rows_b = dict(cr.system_rows(preset, sets[1]["runs"]))
    labels = [spec["label"] for spec in preset["capframex_report"]["system"]]
    out = []
    for label in labels:
        va, vb = rows_a.get(label), rows_b.get(label)
        if va is None and vb is None:
            continue
        out.append((label, va or "—", vb or "—", va != vb))
    captured = [cr._created(s["runs"][0]["info"]) for s in sets]
    out.append(("Captured", captured[0], captured[1], True))
    # Windows Game Mode and similar are recorded per capture; surface differences first
    return sorted(out, key=lambda row: not row[3])


def distribution_curves(preset, sets):
    """Frametime at log-spaced percentiles for every run, plus the mean curve per set."""
    cfg = preset["capframex_compare"]["distribution"]
    count = cfg["points"]
    xs = [cfg["min_x"] + (cfg["max_x"] - cfg["min_x"]) * i / (count - 1) for i in range(count)]
    percentiles = [1.0 - 10.0 ** (-x) for x in xs]
    curves = []
    for s in sets:
        run_curves = []
        for r in s["runs"]:
            ordered = sorted(r["capture"].frametime_ms)
            n = len(ordered)
            run_curves.append([ordered[min(n, max(1, math.ceil(round(n * p, 9)))) - 1] for p in percentiles])
        mean = [math.fsum(col) / len(col) for col in zip(*run_curves)]
        curves.append({"label": s["label"], "runs": run_curves, "mean": mean})
    return xs, curves


def distribution_svg(preset, sets):
    xs, curves = distribution_curves(preset, sets)
    cfg = preset["capframex_compare"]["distribution"]
    step, intervals = report._y_axis(max(max(c) for curve in curves for c in curve["runs"]),
                                     preset["metrics"]["chart"]["y_steps"])
    ymax = step * intervals
    left, right, top, bottom, width, height = 64.0, 940.0, 34.0, 250.0, 960, 300

    def px(x):
        return left + (x - cfg["min_x"]) / (cfg["max_x"] - cfg["min_x"]) * (right - left)

    def py(v):
        return bottom - min(v / ymax, 1.0) * (bottom - top)

    parts = [f'<svg class="chart" role="img" aria-label="Frame time at each percentile of frames, per run" '
             f'viewBox="0 0 {width} {height}">']
    for i in range(intervals + 1):
        y = bottom - i / intervals * (bottom - top)
        parts.append(f'<line x1="{left}" x2="{right}" y1="{y:.1f}" y2="{y:.1f}" stroke="#1f1f24" stroke-width="1"/>'
                     f'<text x="{left - 8}" y="{y + 4:.1f}" fill="#f4f4f5" font-size="12" font-weight="600" '
                     f'text-anchor="end">{step * i:.1f}</text>')
    for p_label, x in (("50%", 0.30103), ("90%", 1.0), ("99%", 2.0), ("99.9%", 3.0), ("99.99%", 4.0)):
        if cfg["min_x"] - 1e-9 <= x <= cfg["max_x"] + 1e-9:
            parts.append(f'<line x1="{px(x):.1f}" x2="{px(x):.1f}" y1="{top}" y2="{bottom + 4}" stroke="#1f1f24" '
                         f'stroke-width="1"/><text x="{px(x):.1f}" y="{bottom + 20}" fill="#f4f4f5" font-size="12" '
                         f'font-weight="600" text-anchor="middle">{p_label}</text>')
    for index, curve in enumerate(curves):
        color = SET_COLORS[index % len(SET_COLORS)]
        for run in curve["runs"]:
            d = " ".join(f"{'M' if i == 0 else 'L'}{px(x):.1f},{py(v):.1f}" for i, (x, v) in enumerate(zip(xs, run)))
            parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1" opacity="0.38" '
                         'stroke-linejoin="round"/>')
    for index, curve in enumerate(curves):
        color = SET_COLORS[index % len(SET_COLORS)]
        d = " ".join(f"{'M' if i == 0 else 'L'}{px(x):.1f},{py(v):.1f}" for i, (x, v) in enumerate(zip(xs, curve["mean"])))
        parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.6" stroke-linejoin="round"/>')
        lx = left + 4 + index * 250
        parts.append(f'<line x1="{lx}" x2="{lx + 22}" y1="16" y2="16" stroke="{color}" stroke-width="3"/>'
                     f'<text x="{lx + 28}" y="20" fill="#f4f4f5" font-size="13" font-weight="700">'
                     f'{escape(curve["label"])} (thin = single runs)</text>')
    parts.append(f'<text x="14" y="{(top + bottom) / 2:.0f}" fill="#f4f4f5" font-size="12" font-weight="600" '
                 f'text-anchor="middle" transform="rotate(-90 14 {(top + bottom) / 2:.0f})">ms</text>')
    parts.append(f'<text x="{(left + right) / 2:.0f}" y="{height - 6}" fill="#9aa6b5" font-size="11" '
                 'font-weight="600" text-anchor="middle">share of frames at or below this frame time — '
                 'the slowest frames are on the right</text></svg>')
    return "".join(parts)


FLAT_MARK = " †"  # dagger: constant reading, explained in the note under the table


def sensor_compare_rows(preset, sets):
    """[(label, A, B, difference)]; constant ('flat') readings are marked and not compared."""
    rows = []
    for index, spec in enumerate(preset["capframex_report"]["sensors"]):
        a, b = sets[0]["sensors"][index], sets[1]["sensors"][index]
        if a is None and b is None:
            continue
        d, unit = spec["decimals"], spec["unit"]

        def fmt(entry):
            if entry is None:
                return "—"
            return f"{entry['avg']:.{d}f} {unit}" + (FLAT_MARK if entry["flat"] else "")

        if a is None or b is None:
            delta = "—"
        elif a["flat"] or b["flat"]:
            delta = "n/a †"
        else:
            delta = f"{b['avg'] - a['avg']:+.{d}f} {unit}"
        rows.append((spec["label"], fmt(a), fmt(b), delta))
    return rows


def render_html(preset, sets, reference_ms):
    ccfg = preset["capframex_compare"]
    rcfg = preset["report"]
    colors = dict(rcfg["colors"], muted="#8f9aa7")
    css, js, logo = report.page_assets(preset, extra_css="capframex.css")
    a, b = sets

    columns = build_columns(preset, sets)
    grid = "".join(report._column_html(c, preset["metrics"]["chart"]) for c in columns)

    headers, rows = uplift_rows(preset, sets)
    thead = "".join(f"<th>{escape(h)}</th>" for h in headers)
    tbody = "".join(
        f'<tr><td class="rl">{escape(r["label"])}</td>'
        + "".join(f'<td style="color:{colors[k]}">{escape(t)}</td>' for t, k in r["cells"]) + "</tr>"
        for r in rows)

    run_headers, run_rows = runs_table(preset, sets)
    rthead = "".join(f"<th>{escape(h)}</th>" for h in run_headers)
    rtbody = []
    for r in run_rows:
        klass = {"mean": ' class="avg-row"', "spread": ' class="spread"'}.get(r["kind"], "")
        rtbody.append(f'<tr{klass}><td class="rl">{escape(r["label"])}</td>'
                      + "".join(f"<td>{escape(c)}</td>" for c in r["cells"]) + "</tr>")

    sys_html = []
    for field, va, vb, differs in system_diff(preset, sets):
        tr_class = ' class="differs"' if differs else ""
        flag = "differs" if differs and field != "Captured" else ""
        sys_html.append(f'<tr{tr_class}><td class="rl">{escape(field)}</td><td>{escape(va)}</td>'
                        f'<td>{escape(vb)}</td><td>{flag}</td></tr>')
    sys_rows = "".join(sys_html)

    sensor_rows = "".join(
        f'<tr><td class="rl">{escape(label)}</td><td>{escape(va)}</td><td>{escape(vb)}</td><td>{escape(dl)}</td></tr>'
        for label, va, vb, dl in sensor_compare_rows(preset, sets))

    files = "".join(
        report.csv_rows_html([(f"{s['label']} · {r['label']}", r["source"]) for r in s["runs"]])
        for s in sets)
    first = a["runs"][0]
    heading = ccfg["capture_heading"].format(version=first["info"].get("AppVersion") or "").strip()
    threshold = a["runs"][0]["metrics"]["stutter_threshold_ms"]

    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{escape(ccfg["page_title"])}</title><style>{css}</style></head><body>'
        f'<div class="wrap"><header class="report-header"><h1>{escape(rcfg["heading"])}{logo}</h1>'
        f'<div class="bid">Comparison: {escape(a["label"])} vs {escape(b["label"])}</div></header>'
        f'<div class="grid" style="--passes:2">{grid}</div>'
        '<div class="summary-row"><section class="uplift cmp">'
        f'<div class="section-label">{escape(b["label"].upper())} VS {escape(a["label"].upper())}</div><table>'
        f'<thead><tr><th></th>{thead}</tr></thead><tbody>{tbody}</tbody></table></section></div>'
        '<div class="chartbox wide"><div class="chead"><span class="ct">FRAME TIME DISTRIBUTION</span></div>'
        f'{distribution_svg(preset, sets)}</div>'
        '<div class="summary-row"><section class="uplift cmp">'
        f'<div class="section-label">ALL RUNS</div><table><thead><tr><th></th>{rthead}</tr></thead>'
        f'<tbody>{"".join(rtbody)}</tbody></table>'
        '<div class="note-line">Spread = highest minus lowest value among the runs of a set.</div></section></div>'
        '<div class="panels equal"><section class="panel uplift sensors sysdiff"><h2>System</h2><table>'
        f'<thead><tr><th></th><th>{escape(a["label"])}</th><th>{escape(b["label"])}</th><th></th></tr></thead>'
        f'<tbody>{sys_rows}</tbody></table></section>'
        '<section class="panel uplift sensors"><h2>Sensors</h2><table>'
        f'<thead><tr><th></th><th>{escape(a["label"])}</th><th>{escape(b["label"])}</th><th>Difference</th></tr></thead>'
        f'<tbody>{sensor_rows}</tbody></table>'
        '<div class="note-line">Mean over each set\'s runs of the per-run average. '
        '\u2020 = the sensor returned one single value for the whole capture (it was not updating), '
        'so it is shown but not compared.</div></section></div>'
        '<div class="summary-row"><footer class="foot"><div>'
        f'<h2>{escape(heading)}</h2><div class="capture-label">{escape(ccfg["capture_label"])}</div>{files}'
        f'<div class="capture-meta">Stutter threshold for both sets: {threshold:.2f} ms '
        f'(2.5 × {reference_ms:.3f} ms, the mean frametime of all {len(a["runs"]) + len(b["runs"])} runs)</div>'
        f'</div><div class="note">{ccfg["note"]}</div></footer></div></div>'
        f"<script>{js}</script></body></html>\n"
    )


def export_json(sets, reference_ms, preset):
    out = {"stutter_reference_ms": reference_ms, "baseline": sets[0]["label"], "sets": []}
    for s in sets:
        out["sets"].append({
            "label": s["label"],
            "mean": s["mean"],
            "min": {k: v["min"] for k, v in s["stats"].items() if v},
            "max": {k: v["max"] for k, v in s["stats"].items() if v},
            "runs": cr.export_json(s["runs"]),
        })
    a, b = sets
    out["delta_pct"] = {k: (b["mean"][k] - a["mean"][k]) / a["mean"][k] * 100.0
                        for k in a["mean"] if k in b["mean"] and a["mean"][k]}
    out["outside_run_spread"] = {k: not ranges_overlap(a["stats"][k], b["stats"][k])
                                 for k in a["stats"] if a["stats"][k] and b["stats"][k]}
    return out

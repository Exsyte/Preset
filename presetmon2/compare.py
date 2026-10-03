"""BEFORE-vs-AFTER presentation rules: tile text/colour classes and the uplift table.

Rules were reverse-engineered from the example report and reproduce every tile
and table cell in it (see tests/test_example_parity.py):

* tiles compare the *displayed* (rounded) values - equal means neutral;
* the uplift table colours by the *rounded* change shown in the cell.
"""

import math


def format_tile(value, tile):
    if value is None:
        return "n/a"
    return f"{value:.{tile['decimals']}f}{tile['suffix']}"


def tile_class(base, value, tile, cls_cfg):
    """CSS class for a tile of an AFTER pass, relative to the BEFORE pass."""
    if base is None or value is None:
        return "neutral"
    decimals = tile["decimals"]
    shown_base = float(f"{base:.{decimals}f}")
    shown_value = float(f"{value:.{decimals}f}")
    if shown_base == shown_value:
        return "neutral"
    higher_is_better = tile["better"] == "higher"
    if (shown_value > shown_base) == higher_is_better:
        return "improved"
    rel = (value - base) / abs(base) * 100.0 if base else math.copysign(math.inf, value - base)
    worsening = rel if higher_is_better else -rel
    return "regressed" if worsening <= cls_cfg["regressed_below_pct"] else "slightly-regressed"


def _round_half_away(x):
    return int(math.floor(abs(x) + 0.5)) * (1 if x >= 0 else -1)


def uplift_cell(base, value, col, cls_cfg):
    """(text, colour class) for one uplift-table cell."""
    if base is None or value is None:
        return "n/a", "neutral"
    higher_is_better = col["better"] == "higher"

    if col["mode"] == "percent":
        pct = (value - base) / base * 100.0 if base else 0.0
        r = _round_half_away(pct)
        text = f"{'+' if r >= 0 else '-'}{abs(r)}%"
        if r == 0:
            return text, "neutral"
        signed = r if higher_is_better else -r
        if signed > 0:
            return text, "improved"
        return text, "regressed" if signed <= cls_cfg["regressed_below_pct"] else "slightly-regressed"

    delta = round(value - base, 2)
    text = f"{'+' if delta >= 0 else '-'}{abs(delta):.2f} ms"
    if delta == 0:
        return text, "neutral"
    if (delta < 0) == (not higher_is_better):
        return text, "improved"
    return text, "regressed" if abs(delta) >= cls_cfg["regressed_above_ms"] else "slightly-regressed"


def _mean_defined(values):
    values = [v for v in values if v is not None]
    return math.fsum(values) / len(values) if values else None


def build_view(preset, passes):
    """Everything the report shows, as plain data.

    `passes` is an ordered list of dicts with: key, label, capture_label,
    csv_path, metrics, chart (or None). The first pass is the BEFORE pass.
    """
    rcfg = preset["report"]
    cls_cfg = rcfg["classification"]
    before, afters = passes[0], passes[1:]

    columns = []
    for p in passes:
        is_before = p is before
        groups = []
        for group in rcfg["groups"]:
            tiles = []
            for tile in group["tiles"]:
                value = p["metrics"].get(tile["metric"])
                klass = "baseline" if is_before else tile_class(
                    before["metrics"].get(tile["metric"]), value, tile, cls_cfg)
                tiles.append({"label": tile["label"], "text": format_tile(value, tile),
                              "class": klass, "tooltip": tile["tooltip"]})
            groups.append({"title": group["title"], "subtitle": group["subtitle"], "tiles": tiles})
        columns.append({"label": p["label"], "is_before": is_before, "groups": groups,
                        "input_detected": bool(p["metrics"].get("input_detected")),
                        "chart": p.get("chart"), "metrics": p["metrics"]})

    rows = []
    for p in afters:
        cells = [uplift_cell(before["metrics"].get(c["metric"]),
                             p["metrics"].get(c["metric"]), c, cls_cfg) for c in rcfg["uplift"]]
        rows.append({"label": f"{p['label']} vs {before['label']}", "cells": cells, "average": False})
    if len(afters) > 1:
        cells = [uplift_cell(before["metrics"].get(c["metric"]),
                             _mean_defined(p["metrics"].get(c["metric"]) for p in afters),
                             c, cls_cfg) for c in rcfg["uplift"]]
        rows.append({"label": f"Average vs {before['label']}", "cells": cells, "average": True})

    return {"columns": columns, "uplift_headers": [c["header"] for c in rcfg["uplift"]],
            "uplift_rows": rows}

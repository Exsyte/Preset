"""PresentMon 2 CSV parsing and benchmark statistics.

Definitions match the example benchmark_previous.json exactly (checked by
`python -m presetmon2 verify`):

* avg_fps        = 1000 / mean(frametime)
* lowN_fps       = 1000 / mean(worst ceil(n * N%) frametimes)
* pN_fps         = 1000 / nearest-rank percentile of frametime
* stutter_time   = share of capture time spent in frames longer than
                   threshold_multiplier x the reference (BEFORE) mean frametime
"""

import csv
import math
from dataclasses import dataclass, field
from itertools import accumulate


@dataclass
class Capture:
    frametime_ms: list
    time_ms: list = None
    series: dict = field(default_factory=dict)
    input_detected: bool = False


def _number(text, na_values):
    if text is None:
        return None
    text = text.strip()
    if text in na_values:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def read_capture(path, csv_cfg):
    """Read a PresentMon 2 CSV (`--v2_metrics`) into a Capture.

    Rows without a frametime are skipped. Other columns are optional: a metric
    whose column is absent or entirely NA is reported as None.
    """
    na_values = set(csv_cfg["na_values"])
    columns = csv_cfg["columns"]
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if not header:
            raise ValueError(f"{path}: empty file")
        index = {name.strip(): i for i, name in enumerate(header)}

        for key in csv_cfg["required"]:
            if columns[key] not in index:
                raise ValueError(
                    f"{path}: required column {columns[key]!r} not found. "
                    "Capture with PresentMon 2 and --v2_metrics."
                )

        ft_col = index[columns["frametime_ms"]]
        time_col = index.get(columns.get("time_ms", ""))
        series_cols = {
            key: index[name]
            for key, name in columns.items()
            if key not in ("frametime_ms", "time_ms") and name in index
        }
        input_cols = [index[n] for n in csv_cfg.get("input_columns", []) if n in index]

        frametimes, times = [], []
        series = {key: [] for key in series_cols}
        input_detected = False
        for row in reader:
            ft = _number(row[ft_col] if ft_col < len(row) else None, na_values)
            if ft is None:
                continue
            frametimes.append(ft)
            if time_col is not None:
                times.append(_number(row[time_col] if time_col < len(row) else None, na_values))
            for key, col in series_cols.items():
                value = _number(row[col] if col < len(row) else None, na_values)
                if value is not None:
                    series[key].append(value)
            if not input_detected:
                input_detected = any(
                    c < len(row) and row[c].strip() not in na_values for c in input_cols
                )

    if not frametimes:
        raise ValueError(f"{path}: no frames with a valid {columns['frametime_ms']} value")
    if time_col is None or any(t is None for t in times):
        times = None
    return Capture(frametimes, times, series, input_detected)


def nearest_rank(ordered, percentile):
    """Nearest-rank percentile of an ascending list."""
    k = max(1, math.ceil(round(len(ordered) * percentile / 100.0, 9)))
    return ordered[min(k, len(ordered)) - 1]


def _mean(values):
    return math.fsum(values) / len(values) if values else None


def compute_metrics(capture, mcfg, reference_avg_frametime_ms=None):
    """Statistics for one pass, keyed like the example benchmark_previous.json."""
    ft = capture.frametime_ms
    n = len(ft)
    total = math.fsum(ft)
    avg_ft = total / n
    ordered = sorted(ft)

    m = {"avg_fps": 1000.0 / avg_ft}
    for key, pct in mcfg["lows"].items():
        k = max(1, math.ceil(round(n * pct / 100.0, 9)))
        m[key] = 1000.0 / _mean(ordered[-k:])
    for key, pct in mcfg["percentiles"].items():
        m[key] = 1000.0 / nearest_rank(ordered, pct)

    anim = capture.series.get("animation_error_ms", [])
    if mcfg.get("animation_error") == "mean_abs":
        anim = [abs(v) for v in anim]
    m["animation_error_avg_ms"] = _mean(anim)

    reference = reference_avg_frametime_ms or avg_ft
    threshold = mcfg["stutter"]["threshold_multiplier"] * reference
    m["stutter_time_pct"] = math.fsum(x for x in ft if x > threshold) / total * 100.0

    m["gpu_latency_avg_ms"] = _mean(capture.series.get("gpu_latency_ms", []))
    m["gpu_busy_avg_ms"] = _mean(capture.series.get("gpu_busy_ms", []))
    m["gpu_wait_avg_ms"] = _mean(capture.series.get("gpu_wait_ms", []))
    m["avg_frametime_ms"] = avg_ft
    m["duration_secs"] = total / 1000.0
    m["frame_count"] = n

    pc = capture.series.get("pc_latency_ms", [])
    m["pc_latency_avg_ms"] = _mean(pc)
    m["pc_latency_p99_ms"] = (
        nearest_rank(sorted(pc), mcfg["pc_latency_percentile"]) if pc else None
    )
    m["input_detected"] = capture.input_detected

    m["frametime_min_ms"] = ordered[0]
    m["frametime_p99_ms"] = nearest_rank(ordered, 99.0)
    m["frametime_max_ms"] = ordered[-1]
    return m


def chart_data(capture, chart_cfg):
    """Downsample a capture for the frametime chart.

    Returns {"duration": seconds, "raw": [(t, ms)...], "ma": [(t, ms)...]}.
    `raw` keeps the worst frame of each time bucket so spikes stay visible;
    `ma` is the bucket mean smoothed with a trailing moving average.
    """
    ft = capture.frametime_ms
    if capture.time_ms:
        t0 = capture.time_ms[0]
        times = [(t - t0) / 1000.0 for t in capture.time_ms]
    else:
        times = [t / 1000.0 for t in accumulate(ft)]
    duration = max(times[-1], 1e-9)

    buckets = chart_cfg["buckets"]
    worst = [None] * buckets
    sums = [0.0] * buckets
    counts = [0] * buckets
    for t, v in zip(times, ft):
        b = min(buckets - 1, int(t / duration * buckets))
        if worst[b] is None or v > worst[b][1]:
            worst[b] = (t, v)
        sums[b] += v
        counts[b] += 1

    raw = [p for p in worst if p is not None]
    window = max(1, chart_cfg["ma_window"])
    means = [(i, sums[i] / counts[i]) for i in range(buckets) if counts[i]]
    ma = []
    for pos, (i, _) in enumerate(means):
        recent = [m for _, m in means[max(0, pos - window + 1): pos + 1]]
        ma.append((i / max(1, buckets - 1) * duration, math.fsum(recent) / len(recent)))
    return {"duration": duration, "raw": raw, "ma": ma}

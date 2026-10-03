"""Convert CapFrameX capture JSON files into PresentMon 2 (`--v2_metrics`) CSVs.

The column mapping lives in preset.json under "capframex". Output has the same
header as the example benchmark_*.csv (plus MsPCLatency and CapFrameXTimeInMs),
so the files go straight into `python -m presetmon2 report`.
"""

import csv
import json
from pathlib import Path

NA = "NA"


def load_file(path):
    """-> (info dict, file hash, [run dict, ...]); each run has CaptureData and SensorData2.

    A merged CapFrameX file (several runs) yields several runs.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    runs = [r for r in data.get("Runs") or [] if r.get("CaptureData")]
    if not runs:
        raise ValueError(f"{path}: not a CapFrameX capture (no Runs[].CaptureData)")
    return data.get("Info") or {}, data.get("Hash") or "", runs


def load_runs(path):
    """-> (info dict, [CaptureData dict, ...]) - one entry per run in the file."""
    info, _, runs = load_file(path)
    return info, [r["CaptureData"] for r in runs]


def _text(value):
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def resolve_sources(capture, cfg):
    """CSV column -> CapFrameX values that are usable, plus notes about the ones that are not."""
    n = len(capture["MsBetweenPresents"])
    sources, notes = {}, []
    for column, field in cfg["fields"].items():
        values = capture.get(field)
        if values is None or len(values) != n:
            notes.append(f"{column}: CapFrameX field '{field}' missing -> NA")
        elif column in cfg["na_if_all_zero"] and not any(values):
            notes.append(f"{column}: CapFrameX field '{field}' is all zero -> NA")
        else:
            sources[column] = values
    return sources, notes


def convert_run(info, capture, cfg):
    """One CapFrameX run -> (header, rows, notes). Rows are lists of strings."""
    frametimes = capture.get("MsBetweenPresents")
    if not frametimes:
        raise ValueError("run has no MsBetweenPresents samples")
    n = len(frametimes)
    header = cfg["header"]
    sources, notes = resolve_sources(capture, cfg)

    modes = capture.get("PresentMode")
    dropped = capture.get("Dropped") or [False] * n
    original_time = capture.get("TimeInSeconds")
    process = info.get("ProcessName") or ""
    na_dropped = set(cfg["na_when_dropped"])

    rows = []
    elapsed = 0.0
    for i in range(n):
        elapsed += frametimes[i]
        row = []
        for column in header:
            if column == "Application":
                value = process
            elif column == "PresentMode":
                value = cfg["present_modes"].get(str(modes[i]), f"Unknown ({modes[i]})") if modes else NA
            elif column == "TimeInMs":
                value = f"{elapsed:.4f}"
            elif column == "CapFrameXTimeInMs":
                value = f"{original_time[i] * 1000.0:.4f}" if original_time else NA
            elif column in sources and not (dropped[i] and column in na_dropped):
                value = _text(sources[column][i])
            else:
                value = NA
            row.append(value)
        rows.append(row)
    return header, rows, notes


def to_capture(capture, preset):
    """CapFrameX CaptureData -> metrics.Capture, using the same mapping as the CSV converter.

    Returns (Capture, notes). Standard series (per preset csv.columns) land in
    Capture.series; every other mapped column lands in Capture.extra by CSV name.
    """
    from .metrics import Capture  # local import: metrics does not depend on this module

    cfg = preset["capframex"]
    frametimes = capture.get("MsBetweenPresents")
    if not frametimes:
        raise ValueError("run has no MsBetweenPresents samples")
    n = len(frametimes)
    sources, notes = resolve_sources(capture, cfg)
    dropped = capture.get("Dropped") or [False] * n
    na_dropped = set(cfg["na_when_dropped"])

    def usable(column):
        values = sources[column]
        if column in na_dropped:
            return [v for v, d in zip(values, dropped) if not d]
        return list(values)

    elapsed, times = 0.0, []
    for ft in frametimes:
        elapsed += ft
        times.append(elapsed)

    csv_columns = preset["csv"]["columns"]
    standard = {name: key for key, name in csv_columns.items() if key not in ("frametime_ms", "time_ms")}
    series = {key: usable(column) for column, key in standard.items() if column in sources}
    extra = {column: usable(column) for column in sources if column not in standard}
    return Capture(list(frametimes), times, series, False, extra), notes


def write_csv(path, header, rows):
    # utf-8-sig + CRLF, like the PresentMon-written example files
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def describe(info):
    parts = [info.get("Comment", "").strip(), info.get("GameName"), info.get("GPU"), info.get("Processor")]
    return " | ".join(p for p in parts if p)

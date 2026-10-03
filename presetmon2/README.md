# presetmon2

A PresentMon 2 benchmark preset that reproduces the results shown in the FrameCap example
folder (`benchmark_report.html`, `benchmark_*.csv`, `benchmark_previous.json`): one **BEFORE**
pass plus several **AFTER** passes of CS2, captured with the PresentMon 2 console application,
turned into the same report (FPS / lows / latency / GPU tiles, frame-time chart, uplift table).

Everything is driven by [`preset.json`](preset.json). No third-party Python packages are needed.

## Quick start

**Capture and report (Windows, elevated PowerShell):**

```powershell
.\presetmon2\run_benchmark.ps1 -PresentMon C:\Tools\PresentMon-2.x-x64.exe
```

It asks you to get CS2 onto the benchmark map before each pass, runs PresentMon for 104 s per pass,
writes `benchmark_before.csv`, `benchmark_after.csv`, `benchmark_after2.csv`, `benchmark_after3.csv`
and `benchmark_id.txt` to `%LOCALAPPDATA%\PresetMon2\benchmark`, then builds `benchmark_report.html`
and `benchmark_results.json` next to them. Use `-Pass after,after_second` to re-run only some passes.

**Report only, from existing CSVs (any OS):**

```sh
python -m presetmon2 report --dir path/to/folder/with/the/csvs
```

Missing AFTER passes are skipped with a warning; the BEFORE CSV is required.

## What the preset configures

| Area | Setting (in `preset.json`) | Value |
| --- | --- | --- |
| Capture | process / duration | `cs2.exe`, 104 s per pass (the example runs are 104.0 s) |
| Capture | PresentMon 2 flags | `--process_name cs2.exe --timed 104 --v2_metrics --no_console_stats --stop_existing_session --terminate_after_timed` + `--output_file`, `--session_name` |
| Passes | files / labels | `BEFORE`, `TinyBoost 1..3` -> `benchmark_before.csv`, `benchmark_after.csv`, `benchmark_after2.csv`, `benchmark_after3.csv` |
| CSV | columns used | `MsBetweenPresents`, `TimeInMs`, `MsUntilDisplayed`, `MsGPULatency`, `MsGPUBusy`, `MsGPUWait`, `MsAnimationError` |
| Metrics | definitions | see below |
| Report | tiles, uplift table, colours, wording | same layout, texts and colour rules as the example; Antonio font and the logo are bundled in `assets/` |

`--v2_metrics` is what gives the `Ms*` column names in the example CSVs. Input tracking is left on
(the example CSVs still carry the `MsAllInputToPhotonLatency` / `MsClickToPhotonLatency` columns).

## How each number is computed

| Report item | Definition |
| --- | --- |
| AVG | `1000 / mean(MsBetweenPresents)` |
| 1% / 0.1% Low Avg | `1000 / mean(worst ceil(n x 1%) / ceil(n x 0.1%) frametimes)` |
| P1 / P0.1 | `1000 /` nearest-rank 99th / 99.9th percentile of frametime |
| Stuttering Time | share of capture time in frames longer than **2.5 x the BEFORE mean frametime** (same threshold for every pass) |
| PC Latency | mean `MsUntilDisplayed` |
| Animation Error | mean of `abs(MsAnimationError)` |
| GPU Latency / Busy / Wait | mean `MsGPULatency` / `MsGPUBusy` / `MsGPUWait` |
| Uplift table | relative change vs BEFORE (rounded to whole %); GPU columns as absolute ms; last row = mean of the AFTER passes |

Tile colours compare the *displayed* values (equal -> neutral). The uplift table colours the *rounded*
change shown in the cell.

## Verified against the example files

Run with the example `benchmark_previous.json` (which stores all four passes' frametimes and the
app's computed metrics):

```sh
python -m presetmon2 verify benchmark_previous.json --report rendered.html
python -m unittest discover -s tests -t .
```

* **Frametime-derived metrics - match.** AVG, P1, P0.1, 1% / 0.1% lows, stuttering %, mean frametime,
  duration and frame count recomputed from the stored frametimes of all four passes agree with the
  stored values to 1e-6 relative.
* **Report - match.** All 33 tiles (values and colour classes) and all 44 uplift-table cells (including
  the "Average" row), the MIN/AVG/P99/MAX chart stats and the chart y-axis scales (10 / 8 / 60 / 8) equal the
  example. A headless-browser render next to the example HTML looks the same (layout, fonts, colours).

## Not verified / assumptions - please check

1. **CSV-column metrics on full captures.** The Drive connector only exposed the first ~11 s of each ~11 MB
   CSV, so PC Latency, GPU Latency/Busy/Wait, Animation Error and the PC-latency P99 could not be reproduced
   from a full run. On the first 4,867 rows of `benchmark_after3.csv` the means are consistent with the
   mapping (`MsUntilDisplayed` 3.81 ms vs 3.8 ms reported; `MsGPUWait` 0.014 ms vs 0.01 ms reported; the
   rest differ only because those rows are the warm-up). Confirm on the real files with:

   ```sh
   python -m presetmon2 verify benchmark_previous.json --csv-dir path/to/FrameCap
   ```

   Every metric should print `ok`. If a latency row fails, the column mapping in `preset.json` (`csv.columns`)
   is the one thing to change.
2. **Orange vs red.** The example only shows `-1%` as orange and `-9%` as red. `regressed_below_pct: -5`
   (and `regressed_above_ms: 0.25` for the GPU columns) are my assumptions.
3. **Exact PresentMon invocation.** The flag set above is derived from the PresentMon 2 console documentation
   and the CSV columns; I could not run PresentMon here. The runner script was also not executed (no Windows/PowerShell
   in this environment) - try it once and tell me if anything needs adjusting. The CSVs the example app wrote have
   fewer columns than a raw `--v2_metrics` file (e.g. no `ProcessID`); the parser only needs the columns listed above.
4. **Chart trace.** The example's exact downsampling isn't recoverable from the HTML; the trace here keeps the worst
   frame per time bucket (spikes stay visible) plus a smoothed average. Stats and axes match; the line shape differs slightly.
5. **Input detection.** A pass is flagged ("Keyboard/mouse input detected") when the input-latency columns contain
   values. This is my addition based on the example JSON's `input_detected` field.
6. The CapFrameX captures in the folder (`tiny*CapFrameX-cs2.exe-*.json`) are a separate manual run (~111 s, 489 FPS
   avg) and were used only to cross-check the statistic definitions (1% low = mean of worst frames, etc.).

## Layout

```
presetmon2/
  preset.json         the pre-configuration
  run_benchmark.ps1   Windows runner (PresentMon 2 capture + report)
  cli.py              python -m presetmon2 {report,metrics,verify}
  metrics.py          CSV parsing + statistics
  compare.py          tile / uplift presentation rules
  report.py           HTML report
  assets/             report CSS/JS (from the example), Antonio font, logo (see NOTICE.txt)
tests/                unit tests + fixtures taken from the example report
```

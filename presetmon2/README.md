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

## Converting CapFrameX captures to PresentMon 2 CSVs

The FrameCap folder's `tiny1/2/3CapFrameX-cs2.exe-*.json` files are CapFrameX captures. Convert them into
PresentMon 2 CSVs in the same layout as `benchmark_after.csv`:

```sh
python -m presetmon2 convert tiny1CapFrameX-*.json tiny2CapFrameX-*.json tiny3CapFrameX-*.json \
    --as after,after_second,after_third --out-dir converted
# -> converted/benchmark_after.csv, benchmark_after2.csv, benchmark_after3.csv
```

`--as` names the runs after the preset's passes; without it each CSV is named after its input file. A merged
CapFrameX file (several `Runs`, e.g. the 18 MB `tinyosszes...json`) writes one CSV per run.

Then build the report. These three captures are all AFTER runs (their comments are "Tiny boost 1 run", "2", "3"), so
add the BEFORE capture from the folder:

```sh
python -m presetmon2 report --dir converted --pass before=path/to/benchmark_before.csv
```

| CapFrameX field | PresentMon 2 column |
| --- | --- |
| `MsBetweenPresents` (lossless) | `MsBetweenPresents` |
| `MsBetweenDisplayChange`, `MsInPresentAPI`, `MsUntilDisplayed`, `SyncInterval` | same names |
| `AnimationError` | `MsAnimationError` |
| `GpuActive` / `CpuActive` | `MsGPUBusy` / `MsCPUBusy` (assumed equivalent) |
| `PcLatency` | `MsPCLatency` (extra column; the report's "PC Latency" tile still uses `MsUntilDisplayed`, as in the example) |
| `PresentMode` (number) | text such as `Hardware: Independent Flip` |
| `TimeInSeconds` | `CapFrameXTimeInMs` (extra); `TimeInMs` is rebuilt as the running sum of `MsBetweenPresents`, which is what PresentMon writes |
| not recorded by CapFrameX | `MsGPULatency`, `MsGPUWait`, `MsGPUTime`, ... written as `NA` |

Consequences to know about:

* The report shows **n/a for GPU Latency and GPU Wait** on converted captures - CapFrameX never stored them.
* Converted runs are ~111 s (the benchmark passes are 104 s) and were captured in a separate session, so treat
  comparisons with `benchmark_before.csv` as indicative only.
* Animation Error is not comparable across the two tools: the converted runs average ~0.29 ms (mean absolute value)
  against ~0.08 ms in the example benchmark.
* Fields that are entirely zero in the source (older CapFrameX builds) are written as `NA` rather than a fake 0.00, and
  `convert` prints a note for each. Edit `capframex` in `preset.json` to change the mapping.

Converted frametime statistics of the three files: 488.6 / 490.2 / 487.7 FPS average (the same values CapFrameX
computes from the stored frametimes).

## HTML report straight from CapFrameX captures

```sh
python -m presetmon2 capframex-report tiny1CapFrameX-*.json tiny2CapFrameX-*.json tiny3CapFrameX-*.json \
    --out tiny_capframex_report.html --json tiny_capframex_results.json
```

Every run in the given files becomes a column in the PresentMon report layout. A finished example built from the
three FrameCap captures is in [`examples/`](../examples/tiny_capframex_report.html) (open it in a browser).

On the page, per run: frame rate (AVG, P1, 1% / 0.1% lows, P0.1), PC latency (`MsUntilDisplayed`, as in the example),
PCL (CapFrameX's own `PcLatency`), animation error, stutter time, CPU busy, GPU busy, time in the Present API and the
frame-time chart with min / avg / P99 / max. Below the columns: a run-comparison table (every run, the mean and the
spread), the system the captures were taken on, a sensor summary (CPU/GPU load, GPU temperature, clock, power, memory,
RAM used by the game) and the capture details (file, date, frames, duration). `--json` writes the same numbers, plus
the system info, for every run; `--label` renames the columns (default: the capture comment, e.g. "Tiny boost 1").

Differences from the benchmark report, all deliberate:

* **No BEFORE pass.** The three captures are AFTER runs, so they are shown side by side with no baseline, no
  better/worse colouring and no uplift table. Stutter time uses one threshold for all runs (2.5 x the mean frametime
  of the runs) instead of the BEFORE average.
* **No GPU Latency / GPU Wait tiles** - CapFrameX does not record them. CPU Busy, PCL and Present-API time replace them.
* **Sensors that CapFrameX stored as all zero** (CPU temperature, package power and clock here) are left out rather than
  shown as 0. GPU core clock (2700 MHz) and GPU power (53.7 W) are identical in all three runs, which looks like a
  single fixed reading rather than a measurement.
* The machine's host name is not included in the page or the JSON.
* P1 / P0.1 and the lows use the definitions verified against the example report; CapFrameX's own screen may differ
  in the last digit.

Verified: every frame-rate and time tile was recomputed independently (numpy, not the package code) from the raw
CapFrameX arrays and matches; the page was loaded in headless Chromium with no script errors, the count-up animation
settles on the right values and the Copy buttons work.

## Comparing two sets of CapFrameX captures

```sh
python -m presetmon2 capframex-compare \
    --set "Tiny boost"       tiny1CapFrameX-*.json tiny2CapFrameX-*.json tiny3CapFrameX-*.json \
    --set "My configuration" CapFrameX-*T23548.json CapFrameX-*T23759.json CapFrameX-*T2408.json \
    --out comparison.html --json comparison.json
```

The first `--set` is the baseline; the second is coloured against it with the same rules as the PresentMon report
(green = better, orange = slightly worse, red = clearly worse). Each column is the mean of that set's runs. The sheet
also has: a **run-to-run check** (do the min-max ranges of the two sets overlap? if so the difference is no bigger
than the runs vary among themselves), a frame-time distribution chart (frame time at each percentile, thin lines =
single runs), every run with mean and spread, how the two systems differ, and a sensor comparison. The example is
[`examples/tiny_vs_own_config_comparison.html`](../examples/tiny_vs_own_config_comparison.html), next to the two
single-set sheets it was built from (`tiny_capframex_report.html`, `own_config_capframex_report.html`).

Things that keep the comparison honest:

* **Same stutter threshold everywhere.** Stutter is the metric most sensitive to its threshold (5.11 ms vs 5.00 ms moved
  the Tiny boost runs from 0.91 / 0.86 / 1.00 % to 1.02 / 0.97 / 1.14 %). The comparison uses 2.5 x the mean frametime of
  *all* runs, and `capframex-report --stutter-reference-ms` takes that value so the single-set sheets match it (the command
  prints it).
* **Stuck sensors are not compared.** In the Tiny boost captures the GPU clock (2700 MHz) and GPU power (53.7 W) are one
  identical value for the whole 111 s, i.e. the sensor was not updating, while the other set has live readings. Such rows are
  marked with a dagger and show `n/a` instead of a difference.
* **The sets were captured at different times** (about an hour apart), and CapFrameX records only some of the system
  state - in these files just Windows Game Mode differs (Disabled vs Enabled). Anything else that changed in between is part
  of the measured difference, so the sheet reports the difference, not its cause.

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
6. The converter (`capframex.py`) was run on `tiny1/2/3` and checked by reading the output back through the PresentMon
   reader (frametimes identical). The merged `tinyosszes...json` (18 MB) is over the Drive connector's 10 MB download
   limit, so multi-run output is only covered by unit tests. `GpuActive`/`CpuActive` -> `MsGPUBusy`/`MsCPUBusy` and the
   `PresentMode` names are assumptions from the CapFrameX/PresentMon naming, not checked against a CapFrameX source.

## Layout

```
presetmon2/
  preset.json         the pre-configuration
  run_benchmark.ps1   Windows runner (PresentMon 2 capture + report)
  cli.py              python -m presetmon2 {report,capframex-report,capframex-compare,convert,metrics,verify}
  capframex.py        CapFrameX JSON -> PresentMon 2 CSV converter / in-memory capture
  capframex_report.py CapFrameX JSON -> PresentMon-style HTML report
  capframex_compare.py two sets of CapFrameX runs -> comparison sheet
  metrics.py          CSV parsing + statistics
  compare.py          tile / uplift presentation rules
  report.py           HTML report
  assets/             report CSS/JS (from the example), Antonio font, logo (see NOTICE.txt)
examples/             sheets built from the FrameCap CapFrameX captures (Tiny boost, own configuration, comparison)
tests/                unit tests + fixtures taken from the example report
```

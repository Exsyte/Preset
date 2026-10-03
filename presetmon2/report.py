"""HTML report in the layout of the example benchmark_report.html."""

import base64
import math
from html import escape
from pathlib import Path

ASSETS = Path(__file__).with_name("assets")

# SVG frame: plot area is x 34..314, y 10 (top) .. 140 (bottom) in a 320x160 viewBox.
_X0, _X1, _Y_TOP, _Y_BASE = 34.0, 314.0, 10.0, 140.0


def _y_axis(max_ms, steps):
    """(step, intervals): the smallest 'nice' step that covers max_ms in at most 4 intervals."""
    for step in steps:
        intervals = max(1, math.ceil(max_ms / step - 1e-9))
        if intervals <= 4:
            return step, intervals
    return steps[-1], 4


def _path(points, duration, ymax):
    out = []
    for i, (t, v) in enumerate(points):
        x = _X0 + min(t / duration, 1.0) * (_X1 - _X0)
        y = _Y_BASE - min(v / ymax, 1.0) * (_Y_BASE - _Y_TOP)
        out.append(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}")
    return " ".join(out)


def chart_svg(chart, chart_cfg):
    duration = chart["duration"]
    step, intervals = _y_axis(max(v for _, v in chart["raw"]), chart_cfg["y_steps"])
    ymax = step * intervals
    parts = ['<svg class="chart" role="img" aria-label="Frame time samples and moving '
             'average in milliseconds" viewBox="0 0 320 160">']
    for i in range(intervals + 1):
        y = _Y_BASE - i / intervals * (_Y_BASE - _Y_TOP)
        parts.append(f'<line x1="34" x2="314" y1="{y:.1f}" y2="{y:.1f}" stroke="#1f1f24" stroke-width="1"/>'
                     f'<text x="29" y="{y + 3.5:.1f}" fill="#f4f4f5" font-size="11" font-weight="600" '
                     f'text-anchor="end">{step * i:.1f}</text>')
    for i in range(5):
        x = _X0 + i * (_X1 - _X0) / 4
        anchor = "start" if i == 0 else "end" if i == 4 else "middle"
        parts.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="140" y2="144" stroke="#2a2a30" stroke-width="1"/>'
                     f'<text x="{x:.1f}" y="154" fill="#f4f4f5" font-size="11" font-weight="600" '
                     f'text-anchor="{anchor}">{round(duration * i / 4)}s</text>')
    parts.append(f'<path class="craw" pathLength="1" d="{_path(chart["raw"], duration, ymax)}" '
                 'fill="none" stroke="#37e07e" stroke-width="0.8"/>')
    parts.append(f'<path class="cma" pathLength="1" d="{_path(chart["ma"], duration, ymax)}" '
                 'fill="none" stroke="#fb923c" stroke-width="2"/>')
    parts.append('<text x="9" y="75" fill="#f4f4f5" font-size="10" font-weight="600" '
                 'text-anchor="middle" transform="rotate(-90 9 75)">ms</text></svg>')
    return "".join(parts)


def _column_html(col, chart_cfg):
    h = [f'<div class="col {"before" if col["is_before"] else "after"}">'
         f'<div class="plabel">{escape(col["label"])}</div>']
    if col["input_detected"]:
        h.append('<div class="validity">Keyboard/mouse input detected during this pass</div>')
    for group in col["groups"]:
        h.append(f'<div class="mgroup"><div class="mtitle">{escape(group["title"])} '
                 f'<span>{escape(group["subtitle"])}</span></div>'
                 f'<div class="tiles t{len(group["tiles"])}">')
        for t in group["tiles"]:
            h.append(f'<div class="tile" title="{escape(t["tooltip"], quote=True)}">'
                     f'<div class="tv {t["class"]}">{escape(t["text"])}</div>'
                     f'<div class="tl">{escape(t["label"])}</div></div>')
        h.append("</div></div>")
    if col["chart"]:
        m = col["metrics"]
        h.append('<div class="chartbox"><div class="chead"><span class="ct">FRAME TIME</span></div>'
                 + chart_svg(col["chart"], chart_cfg)
                 + '<div class="cstats">'
                 f'<div><b>{m["frametime_min_ms"]:.2f}</b><span>MIN</span></div>'
                 f'<div><b>{m["avg_frametime_ms"]:.2f}</b><span>AVG</span></div>'
                 f'<div><b>{m["frametime_p99_ms"]:.2f}</b><span>P99</span></div>'
                 f'<div><b>{m["frametime_max_ms"]:.2f}</b><span>MAX</span></div>'
                 "</div></div>")
    h.append("</div>")
    return "".join(h)


def _embed(path, mime):
    return f"data:{mime};base64,{base64.b64encode(Path(path).read_bytes()).decode('ascii')}"


def _asset(preset, value):
    """Resolve an asset path from the preset (relative paths are relative to the preset file)."""
    path = Path(value)
    return path if path.is_absolute() else Path(preset["_path"]).parent / path


def page_assets(preset, extra_css=""):
    """(css, js, logo_html) for a report page: bundled CSS/JS plus the preset's font and logo."""
    rcfg = preset["report"]
    css = (ASSETS / "report.css").read_text(encoding="utf-8")
    if extra_css:
        css += "\n" + (ASSETS / extra_css).read_text(encoding="utf-8")
    if rcfg.get("font_file"):
        css = ("@font-face{font-family:Antonio;src:url(" + _embed(_asset(preset, rcfg["font_file"]), "font/ttf")
               + ") format('truetype');font-weight:100 900;font-display:swap}" + css)
    js = (ASSETS / "report.js").read_text(encoding="utf-8")
    logo = ""
    if rcfg.get("logo_svg"):
        logo = (f'<img class="report-logo" alt="logo" '
                f'src="{_embed(_asset(preset, rcfg["logo_svg"]), "image/svg+xml")}">')
    return css, js, logo


def csv_rows_html(csv_paths):
    return "".join(
        f'<div class="csv"><span class="cn">{escape(label)}</span><code>{escape(str(path))}</code>'
        '<button class="cp" type="button">Copy</button></div>' for label, path in csv_paths)


def render_html(preset, view, benchmark_id, csv_paths):
    rcfg = preset["report"]
    css, js, logo = page_assets(preset)
    colors = rcfg["colors"]

    chart_cfg = preset["metrics"]["chart"]
    columns = "".join(_column_html(c, chart_cfg) for c in view["columns"])

    head = "".join(f"<th>{escape(h)}</th>" for h in view["uplift_headers"])
    body = []
    for row in view["uplift_rows"]:
        cells = "".join(f'<td style="color:{colors[klass]}">{escape(text)}</td>'
                        for text, klass in row["cells"])
        tr_class = ' class="avg-row"' if row["average"] else ""
        body.append(f'<tr{tr_class}><td class="rl">{escape(row["label"])}</td>{cells}</tr>')

    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{escape(rcfg["page_title"])}</title><style>{css}</style></head><body>'
        f'<div class="wrap"><header class="report-header"><h1>{escape(rcfg["heading"])}{logo}</h1>'
        f'<div class="bid">Benchmark ID: {escape(benchmark_id)}</div></header>'
        f'<div class="grid" style="--passes:{len(view["columns"])}">{columns}</div>'
        '<div class="summary-row"><section class="uplift"><table>'
        f'<thead><tr><th></th>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></section>'
        f'<footer class="foot"><div><h2>{escape(rcfg["capture_heading"])}</h2>'
        f'<div class="capture-label">{escape(rcfg["capture_label"])}</div>{csv_rows_html(csv_paths)}</div>'
        f'<div class="note">{rcfg["note"]}</div></footer></div></div>'
        f"<script>{js}</script></body></html>\n"
    )

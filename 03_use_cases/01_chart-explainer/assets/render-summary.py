#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.
"""Generate a styled chart summary HTML page from Step 2 analysis JSON.

Usage (from this recipe directory):
  python3 assets/render-summary.py \
    --analysis /tmp/analysis.json \
    --chart ~/chart-demo/charts/chart.png \
    --output ~/chart-demo/summary/generated.html

Copies the chart image beside the HTML so the page is self-contained for Canvas.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
from pathlib import Path

CSS = """
  :root {
    --bg0: #0a0e1a;
    --bg1: #161033;
    --card: rgba(20, 27, 48, 0.72);
    --stroke: rgba(140, 150, 190, 0.16);
    --ink: #eef1f8;
    --muted: #9aa6be;
    --accent: #8b6cff;
    --up: #2fd97a;
    --down: #ff6b6b;
    --chip: rgba(139, 108, 255, 0.14);
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; min-height: 100%; }
  body {
    font: 15px/1.5 -apple-system, "SF Pro Text", "Segoe UI", Roboto, Inter, system-ui, sans-serif;
    color: var(--ink);
    background:
      radial-gradient(1200px 700px at 12% -10%, #241a5e 0%, transparent 55%),
      radial-gradient(900px 600px at 110% 120%, #3a1d63 0%, transparent 50%),
      linear-gradient(160deg, var(--bg0), var(--bg1));
    background-attachment: fixed;
    -webkit-font-smoothing: antialiased;
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding: 16px;
    overflow-x: hidden;
    overflow-y: auto;
  }
  .card {
    width: 100%;
    max-width: min(900px, 100%);
    background: var(--card);
    border: 1px solid var(--stroke);
    border-radius: 20px;
    padding: 20px 22px 18px;
    box-shadow: 0 24px 70px rgba(0, 0, 0, 0.45), inset 0 1px 0 rgba(255, 255, 255, 0.04);
    backdrop-filter: blur(14px);
  }
  .top { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
  .ticker {
    font: 700 14px/1 "SF Mono", ui-monospace, Menlo, monospace;
    letter-spacing: 1px;
    color: var(--accent);
    background: var(--chip);
    border: 1px solid rgba(139, 108, 255, 0.35);
    padding: 8px 11px;
    border-radius: 10px;
  }
  .name { font-weight: 650; font-size: 18px; }
  .sub { color: var(--muted); font-size: 13px; margin-top: 2px; }
  .trend {
    margin-left: auto;
    display: inline-flex; align-items: center; gap: 7px;
    font-weight: 650; font-size: 13px;
    color: var(--up);
    background: rgba(47, 217, 122, 0.12);
    border: 1px solid rgba(47, 217, 122, 0.35);
    padding: 7px 12px; border-radius: 999px;
  }
  .trend.down { color: var(--down); background: rgba(255, 107, 107, 0.12); border-color: rgba(255, 107, 107, 0.35); }
  .trend.flat { color: var(--muted); background: rgba(255, 255, 255, 0.06); border-color: var(--stroke); }
  .hero { display: flex; align-items: baseline; gap: 14px; margin: 20px 0 18px; flex-wrap: wrap; }
  .price { font-weight: 750; font-size: 40px; letter-spacing: -0.5px; }
  .chg { font-weight: 700; font-size: 16px; color: var(--up); }
  .chg.neg { color: var(--down); }
  .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
  @media (max-width: 640px) { .grid { grid-template-columns: 1fr; } }
  .tile {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid var(--stroke);
    border-radius: 14px; padding: 14px 15px;
  }
  .tile .label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.6px; }
  .tile .val { font-weight: 700; font-size: 17px; margin-top: 6px; }
  .pills { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 7px; }
  .pill {
    font: 600 12px/1 inherit; color: #d9def0;
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid var(--stroke);
    padding: 6px 10px; border-radius: 999px;
  }
  .pill.res { color: #ffd2a6; border-color: rgba(255, 170, 90, 0.3); }
  .section-title { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.6px; margin: 18px 0 9px; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; }
  .chip {
    font: 600 13px/1 inherit;
    background: var(--chip); color: #cdbcff;
    border: 1px solid rgba(139, 108, 255, 0.3);
    padding: 8px 12px; border-radius: 10px;
  }
  .chart { margin-top: 14px; border: 1px solid var(--stroke); border-radius: 14px; overflow: hidden; background: #0b0f1c; }
  .chart img {
    display: block;
    width: 100%;
    height: auto;
    max-height: var(--chart-max-height, 320px);
    object-fit: contain;
    object-position: top center;
  }
  .foot { margin-top: 16px; color: var(--muted); font-size: 11.5px; display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
"""


def esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def ticker_from_instrument(instrument: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", instrument)
    if not words:
        return "CHART"
    first = words[0].upper()
    return first if len(first) <= 6 else first[:6]


def trend_label(trend: str) -> tuple[str, str]:
    t = (trend or "sideways").lower()
    if t == "up":
        return "▲ Uptrend", "trend"
    if t == "down":
        return "▼ Downtrend", "trend down"
    return "→ Sideways", "trend flat"


def as_number(value: object) -> float | None:
    """Coerce model output to a float, or None when it isn't a clean number.
    The model sometimes emits strings like "~135" or "168" instead of numbers."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
        return float(m.group()) if m else None
    return None


def fmt_level(value: float | int | None) -> str:
    if value is None:
        return "—"
    if float(value).is_integer():
        return f"${int(value)}"
    return f"${value:.2f}"


def fmt_pct(value: float | int | None) -> str:
    if value is None:
        return "not readable"
    sign = "+" if float(value) >= 0 else ""
    return f"{sign}{value}%"


def render_page(analysis: dict, chart_basename: str, chart_max_height: int = 320) -> str:
    instrument = analysis.get("instrument") or "Unknown instrument"
    timeframe = analysis.get("timeframe") or "—"
    trend_text, trend_class = trend_label(analysis.get("trend", "sideways"))
    ticker = ticker_from_instrument(instrument)

    supports = sorted(
        n
        for lvl in analysis.get("keyLevels") or []
        if lvl.get("type") == "support"
        for n in [as_number(lvl.get("value"))]
        if n is not None
    )
    resistances = sorted(
        n
        for lvl in analysis.get("keyLevels") or []
        if lvl.get("type") == "resistance"
        for n in [as_number(lvl.get("value"))]
        if n is not None
    )

    pct = as_number(analysis.get("pctChangeVisible"))
    pct_html = fmt_pct(pct)
    chg_class = "chg neg" if pct is not None and float(pct) < 0 else "chg"

    support_pills = "".join(f'<span class="pill">{esc(fmt_level(v))}</span>' for v in supports)
    if not support_pills:
        support_pills = '<span class="pill">not readable</span>'

    resistance_pills = "".join(f'<span class="pill res">{esc(fmt_level(v))}</span>' for v in resistances)
    if not resistance_pills:
        resistance_pills = '<span class="pill res">not readable</span>'

    events = analysis.get("notableEvents") or []
    chips = "".join(f'<span class="chip">{esc(e)}</span>' for e in events)
    if not chips:
        chips = '<span class="chip">—</span>'

    # Prefer highest resistance as hero price when no explicit last price in schema.
    hero_price = fmt_level(resistances[-1] if resistances else (supports[-1] if supports else None))

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{esc(instrument)} Chart Summary</title>
<style>:root {{ --chart-max-height: {chart_max_height}px; }}{CSS}</style>
</head>
<body>
  <div class="card">
    <div class="top">
      <span class="ticker">{esc(ticker)}</span>
      <div>
        <div class="name">{esc(instrument)}</div>
        <div class="sub">{esc(timeframe)}</div>
      </div>
      <span class="{trend_class}">{esc(trend_text)}</span>
    </div>

    <div class="hero">
      <span class="price">{esc(hero_price)}</span>
      <span class="{chg_class}">{esc(pct_html)} <span style="color:var(--muted);font-weight:600;">labeled change</span></span>
    </div>

    <div class="grid">
      <div class="tile">
        <div class="label">Support</div>
        <div class="pills">{support_pills}</div>
      </div>
      <div class="tile">
        <div class="label">Resistance</div>
        <div class="pills">{resistance_pills}</div>
      </div>
      <div class="tile">
        <div class="label">Change (extracted)</div>
        <div class="val">{esc(pct_html)}</div>
      </div>
    </div>

    <div class="section-title">Labeled patterns &amp; indicators</div>
    <div class="chips">{chips}</div>

    <div class="chart"><img src="{esc(chart_basename)}" alt="{esc(instrument)} chart" /></div>

    <div class="foot">
      <span>Generated from extracted analysis &middot; explain-only</span>
      <span>Not financial advice</span>
    </div>
  </div>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Render chart summary HTML from analysis JSON")
    parser.add_argument("--analysis", required=True, help="Path to Step 2 analysis JSON")
    parser.add_argument("--chart", required=True, help="Path to chart image (copied beside output)")
    parser.add_argument("--output", required=True, help="Output HTML path")
    parser.add_argument(
        "--chart-max-height",
        type=int,
        default=320,
        help="Max chart image height in px (Canvas panels are ~680px tall)",
    )
    args = parser.parse_args()

    analysis_path = Path(args.analysis).expanduser()
    chart_path = Path(args.chart).expanduser()
    output_path = Path(args.output).expanduser()

    analysis = json.loads(analysis_path.read_text())
    output_path.parent.mkdir(parents=True, exist_ok=True)

    chart_dest = output_path.parent / chart_path.name
    if chart_path.resolve() != chart_dest.resolve():
        shutil.copy2(chart_path, chart_dest)

    output_path.write_text(render_page(analysis, chart_dest.name, args.chart_max_height))
    print(f"Wrote {output_path}")
    print(f"Copied chart to {chart_dest}")


if __name__ == "__main__":
    main()

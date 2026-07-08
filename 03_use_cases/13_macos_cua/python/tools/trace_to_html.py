#!/usr/bin/env python3
"""Render a metacua trace (.jsonl + sidecar PNGs) as a self-contained HTML timeline.

Usage:
    python3 trace_to_html.py <trace-id-or-path> [-o out.html] [--open]

<trace-id-or-path> may be:
  - a trace id            e.g. 26DCAB5B-CCF9-43FD-BBEA-27C219CD07B2
  - a path to the .jsonl  e.g. ~/.metacua/traces/<id>.jsonl

Screenshots are inlined as base64 so the resulting file is portable (one page,
no external assets). Each step shows the screenshot the model saw, its
reasoning/text, and the action(s) it took.
"""

import argparse
import base64
import html
import json
import mimetypes
import os
import re
import sys
from pathlib import Path

TRACES_DIR = Path.home() / ".metacua" / "traces"
SAVED_RE = re.compile(r"<saved ([^ >]+) \((\d+) bytes\)>")


def resolve_trace(arg: str) -> Path:
    p = Path(arg).expanduser()
    if p.suffix == ".jsonl" and p.exists():
        return p
    if p.exists() and p.is_file():
        return p
    candidate = TRACES_DIR / f"{arg}.jsonl"
    if candidate.exists():
        return candidate
    raise SystemExit(f"trace not found: {arg} (looked in {TRACES_DIR})")


def load_records(path: Path):
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    records.sort(key=lambda r: (r.get("step") if isinstance(r.get("step"), int) else 0))
    return records


def find_image_refs(value):
    """Return sidecar-relative paths referenced anywhere in a JSON value, in order."""
    refs = []

    def walk(v):
        if isinstance(v, dict):
            for child in v.values():
                walk(child)
        elif isinstance(v, list):
            for child in v:
                walk(child)
        elif isinstance(v, str):
            for m in SAVED_RE.finditer(v):
                refs.append(m.group(1))

    walk(value)
    # de-dupe preserving order
    seen = set()
    out = []
    for r in refs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def data_uri(traces_dir: Path, relpath: str):
    img_path = traces_dir / relpath
    if not img_path.exists():
        return None
    mime = mimetypes.guess_type(str(img_path))[0] or "image/png"
    b64 = base64.b64encode(img_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def esc(s) -> str:
    return html.escape("" if s is None else str(s))


def render_action(call) -> str:
    name = esc(call.get("name"))
    inp = call.get("input")
    try:
        pretty = json.dumps(inp, ensure_ascii=False)
    except (TypeError, ValueError):
        pretty = str(inp)
    return f'<span class="act-name">{name}</span> <code>{esc(pretty)}</code>'


# Normalized coordinate space used by the computer tool (0-1000 on each axis).
COORD_MAX = 1000.0


def _as_point(value):
    """Return (x, y) floats from a [x, y] list, or None."""
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            return float(value[0]), float(value[1])
        except (TypeError, ValueError):
            return None
    return None


def collect_markers(tool_calls):
    """Extract normalized click/move/drag points from a step's tool calls.

    Returns a list of dicts: {x, y, kind, label} where x/y are percentages (0-100).
    """
    markers = []
    for call in tool_calls or []:
        inp = call.get("input") if isinstance(call, dict) else None
        if not isinstance(inp, dict):
            continue
        action = str(inp.get("action") or "").lower()
        # A single target coordinate (click / move / double_click / right_click).
        pt = _as_point(inp.get("coordinate"))
        if pt:
            markers.append(_marker(pt, action or "point"))
        # Drag: show both endpoints.
        start = _as_point(inp.get("start_coordinate"))
        if start:
            markers.append(_marker(start, "drag start"))
    return markers


def _marker(pt, kind):
    x, y = pt
    return {
        "left": max(0.0, min(100.0, x / COORD_MAX * 100.0)),
        "top": max(0.0, min(100.0, y / COORD_MAX * 100.0)),
        "kind": kind,
        "label": f"{kind} {int(round(x))},{int(round(y))}",
    }


def build_html(records, traces_dir: Path) -> str:
    first = records[0] if records else {}
    goal = first.get("goal", "")
    model = first.get("model", "")
    backend = first.get("backend", "")
    trace_id = first.get("trace_id", "")
    started = first.get("timestamp", "")

    total_imgs = 0
    steps_html = []
    for r in records:
        step = r.get("step", "?")
        finish = r.get("finish", "")
        text = r.get("text") or ""
        thinking = r.get("thinking") or ""
        tool_calls = r.get("tool_calls") or []

        markers = collect_markers(tool_calls)

        # Prefer the screenshot the model actually saw for this step (its request state).
        refs = find_image_refs(r.get("request")) or find_image_refs(r)
        img_html = '<div class="noshot">no screenshot saved for this step</div>'
        if refs:
            uri = data_uri(traces_dir, refs[-1])
            if uri:
                total_imgs += 1
                markers_html = "".join(
                    f'<div class="marker" style="left:{m["left"]:.3f}%;top:{m["top"]:.3f}%">'
                    f'<span class="dot"></span><span class="lbl">{esc(m["label"])}</span></div>'
                    for m in markers
                )
                img_html = (
                    f'<div class="imgwrap">'
                    f'<a href="{uri}" target="_blank">'
                    f'<img src="{uri}" alt="step {esc(step)} screenshot" loading="lazy"></a>'
                    f'{markers_html}</div>'
                )

        actions_html = ""
        if tool_calls:
            items = "".join(f"<li>{render_action(c)}</li>" for c in tool_calls)
            actions_html = f'<div class="actions"><div class="label">actions</div><ul>{items}</ul></div>'

        text_html = f'<div class="text">{esc(text)}</div>' if text.strip() else ""
        thinking_html = (
            f'<details class="thinking"><summary>thinking</summary><pre>{esc(thinking)}</pre></details>'
            if thinking.strip()
            else ""
        )

        steps_html.append(
            f"""
        <section class="step">
          <div class="shot">{img_html}</div>
          <div class="body">
            <div class="step-head"><span class="num">step {esc(step)}</span>
              <span class="finish">{esc(finish)}</span></div>
            {text_html}
            {actions_html}
            {thinking_html}
          </div>
        </section>"""
        )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(goal) or esc(trace_id)}</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font: 15px/1.5 -apple-system, system-ui, sans-serif;
    background: Canvas; color: CanvasText; }}
  header {{ padding: 20px 24px; border-bottom: 1px solid color-mix(in srgb, CanvasText 15%, transparent);
    position: sticky; top: 0; background: color-mix(in srgb, Canvas 92%, transparent);
    backdrop-filter: blur(8px); z-index: 5; }}
  header h1 {{ margin: 0 0 6px; font-size: 18px; }}
  header .meta {{ font-size: 13px; opacity: .7; display: flex; gap: 16px; flex-wrap: wrap; }}
  main {{ max-width: 1000px; margin: 0 auto; padding: 16px; }}
  .step {{ display: grid; grid-template-columns: 340px 1fr; gap: 20px; padding: 20px 8px;
    border-bottom: 1px solid color-mix(in srgb, CanvasText 10%, transparent); align-items: start; }}
  .shot img {{ width: 100%; border-radius: 8px; border: 1px solid color-mix(in srgb, CanvasText 20%, transparent);
    cursor: zoom-in; display: block; }}
  .imgwrap {{ position: relative; line-height: 0; }}
  .marker {{ position: absolute; transform: translate(-50%, -50%); pointer-events: none; z-index: 2; }}
  .marker .dot {{ display: block; width: 22px; height: 22px; margin: -11px 0 0 -11px;
    border-radius: 50%; border: 2px solid #ff2d55;
    box-shadow: 0 0 0 2px rgba(255,255,255,.9), 0 0 8px 2px rgba(255,45,85,.6);
    background: rgba(255,45,85,.25); animation: pulse 1.6s ease-out infinite; }}
  .marker .dot::after {{ content: ""; position: absolute; left: 50%; top: 50%;
    width: 4px; height: 4px; margin: -2px 0 0 -2px; border-radius: 50%; background: #ff2d55; }}
  .marker .lbl {{ position: absolute; left: 16px; top: -6px; white-space: nowrap;
    font: 11px/1.4 ui-monospace, monospace; color: #fff; background: rgba(255,45,85,.92);
    padding: 1px 6px; border-radius: 5px; line-height: 1.4; }}
  @keyframes pulse {{ 0% {{ box-shadow: 0 0 0 2px rgba(255,255,255,.9), 0 0 0 0 rgba(255,45,85,.5); }}
    100% {{ box-shadow: 0 0 0 2px rgba(255,255,255,.9), 0 0 0 14px rgba(255,45,85,0); }} }}
  .noshot {{ font-size: 13px; opacity: .45; padding: 24px 12px; text-align: center;
    border: 1px dashed color-mix(in srgb, CanvasText 25%, transparent); border-radius: 8px; }}
  .step-head {{ display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }}
  .num {{ font-weight: 700; }}
  .finish {{ font-size: 11px; padding: 2px 8px; border-radius: 999px;
    background: color-mix(in srgb, CanvasText 12%, transparent); }}
  .text {{ margin: 6px 0; }}
  .actions .label {{ font-size: 11px; text-transform: uppercase; letter-spacing: .05em; opacity: .6; margin-top: 10px; }}
  .actions ul {{ margin: 4px 0 0; padding-left: 18px; }}
  .actions li {{ margin: 3px 0; }}
  .act-name {{ font-weight: 600; }}
  code {{ font: 12px/1.4 ui-monospace, monospace;
    background: color-mix(in srgb, CanvasText 8%, transparent); padding: 1px 6px; border-radius: 5px;
    word-break: break-word; }}
  .thinking {{ margin-top: 10px; }}
  .thinking summary {{ cursor: pointer; font-size: 12px; opacity: .6; }}
  .thinking pre {{ white-space: pre-wrap; font: 12px/1.5 ui-monospace, monospace;
    background: color-mix(in srgb, CanvasText 6%, transparent); padding: 10px; border-radius: 6px; }}
  @media (max-width: 720px) {{ .step {{ grid-template-columns: 1fr; }} }}
</style></head>
<body>
<header>
  <h1>{esc(goal) or "metacua trace"}</h1>
  <div class="meta">
    <span>trace <code>{esc(trace_id)}</code></span>
    <span>model {esc(model)}</span>
    <span>backend {esc(backend)}</span>
    <span>{len(records)} steps</span>
    <span>{total_imgs} screenshots</span>
    <span>{esc(started)}</span>
  </div>
</header>
<main>
{''.join(steps_html)}
</main>
</body></html>"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trace", help="trace id or path to .jsonl")
    ap.add_argument("-o", "--out", help="output HTML path (default: <trace-id>.html next to trace)")
    ap.add_argument("--open", action="store_true", help="open the result in the default browser")
    args = ap.parse_args()

    trace_path = resolve_trace(args.trace)
    traces_dir = trace_path.parent
    records = load_records(trace_path)
    if not records:
        raise SystemExit(f"no records in {trace_path}")

    out = Path(args.out).expanduser() if args.out else trace_path.with_suffix(".html")
    out.write_text(build_html(records, traces_dir), encoding="utf-8")
    print(f"wrote {out}  ({len(records)} steps)")

    if args.open:
        os.system(f'open {out!s}')


if __name__ == "__main__":
    main()

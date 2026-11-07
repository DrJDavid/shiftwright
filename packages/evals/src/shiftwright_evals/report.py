"""HTML report (plus report.json with every row). Hand-rolled SVG, large type, projector-friendly.

Deterministic: the same run folder contents produce byte-identical output (no clock, no randomness).
"""
from __future__ import annotations

import html
import json
import os
from collections import Counter
from pathlib import Path

from .score import aggregate, collect, worked_example

SW_COLOR = "#0b7a53"
PALETTE = ["#c8553d", "#e09f3e", "#3a6ea5", "#8e5ba8", "#6b705c", "#d1495b"]
CODE_COLORS = ["#c8553d", "#e09f3e", "#3a6ea5", "#8e5ba8", "#2a9d8f", "#d1495b", "#6b705c", "#bbbbbb"]
FONT = "font-family:Inter,Segoe UI,Helvetica,Arial,sans-serif"


def esc(x) -> str:
    return html.escape(str(x), quote=True)


def _model(name: str) -> str:
    return name.split(":", 1)[1] if ":" in name else name


def color_for(systems: list[str]) -> dict[str, str]:
    """Shiftwright is always green; a model keeps one colour across its baseline:/chat: systems."""
    out, by_model = {}, {}
    for s in systems:
        if s.startswith("shiftwright"):
            out[s] = SW_COLOR
            continue
        m = _model(s)
        if m not in by_model:
            by_model[m] = PALETTE[len(by_model) % len(PALETTE)]
        out[s] = by_model[m]
    return out


def is_realistic(name: str) -> bool:
    return name.startswith("chat:") or name == "shiftwright:intake"


def short(name: str) -> str:
    if name == "shiftwright":
        return "Shiftwright"
    if name == "shiftwright:intake":
        return "Shiftwright"
    m = _model(name).split("/")[-1]
    return m


def fmt(x, nd=1, suffix="") -> str:
    if x is None:
        return "–"
    if isinstance(x, float):
        return f"{x:.{nd}f}{suffix}"
    return f"{x}{suffix}"


def fmt_duration(sec) -> str:
    if sec is None:
        return "–"
    if sec < 120:
        return f"{sec:.0f} s"
    return f"{sec / 60:.0f} min"


# --------------------------------------------------------------------------- #
# Charts
# --------------------------------------------------------------------------- #
def bar_chart(items: list[tuple[str, float | None, str, str]], title: str, unit: str = "%", vmax: float = 100,
              caption_w: int = 140) -> str:
    """Horizontal bars. items = (label, value or None, color, caption)."""
    w, lw, row = 900, 230, 56
    h = 60 + row * len(items)
    bw = w - lw - caption_w
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="{esc(title)}" style="{FONT}">',
             f'<text x="0" y="30" font-size="24" font-weight="700" fill="#222">{esc(title)}</text>']
    for i, (label, value, color, caption) in enumerate(items):
        y = 55 + i * row
        parts.append(f'<text x="{lw - 12}" y="{y + 28}" font-size="22" text-anchor="end" fill="#222">{esc(label)}</text>')
        parts.append(f'<rect x="{lw}" y="{y + 6}" width="{bw}" height="34" fill="#f0f0f0"/>')
        if value is None:
            parts.append(f'<text x="{lw + 12}" y="{y + 30}" font-size="20" fill="#777">{esc(caption or "not run")}</text>')
            continue
        bwv = max(2, bw * min(value, vmax) / vmax)
        parts.append(f'<rect x="{lw}" y="{y + 6}" width="{bwv:.1f}" height="34" fill="{color}"/>')
        inside = bwv > bw * 0.8
        tx = lw + bwv - 10 if inside else lw + bwv + 10
        parts.append(f'<text x="{tx:.1f}" y="{y + 31}" font-size="22" font-weight="700" '
                     f'fill="{"#fff" if inside else "#222"}" text-anchor="{"end" if inside else "start"}">'
                     f'{value:.{1 if unit == " min" and value < 10 else 0}f}{unit}</text>')
        if caption:
            parts.append(f'<text x="{w}" y="{y + 31}" font-size="16" text-anchor="end" fill="#555">{esc(caption)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def stacked_codes(agg: dict, systems: list[str], suite: str, title: str) -> str:
    totals = Counter()
    for s in systems:
        totals.update(agg[s][suite]["hard_by_code"])
    top = [c for c, _ in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:7]]
    cols = {c: CODE_COLORS[i] for i, c in enumerate(top)}
    cols["other"] = CODE_COLORS[-1]
    w, lw, row = 900, 230, 56
    h = 70 + row * len(systems) + 40 * ((len(top) + 3) // 4 + 1)
    vmax = max([sum(agg[s][suite]["hard_by_code"].values()) for s in systems] + [1])
    bw = w - lw - 90
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="{esc(title)}" style="{FONT}">',
             f'<text x="0" y="30" font-size="24" font-weight="700" fill="#222">{esc(title)}</text>']
    for i, s in enumerate(systems):
        y = 55 + i * row
        a = agg[s][suite]
        parts.append(f'<text x="{lw - 12}" y="{y + 28}" font-size="22" text-anchor="end" fill="#222">{esc(short(s))}</text>')
        if a["scored"] == 0:
            parts.append(f'<text x="{lw + 12}" y="{y + 30}" font-size="20" fill="#777">not run</text>')
            continue
        x = lw
        other = 0
        for code, n in a["hard_by_code"].items():
            if code not in cols or code == "other":
                other += n
                continue
            wv = bw * n / vmax
            parts.append(f'<rect x="{x:.1f}" y="{y + 6}" width="{wv:.1f}" height="34" fill="{cols[code]}">'
                         f'<title>{esc(code)}: {n}</title></rect>')
            x += wv
        if other:
            wv = bw * other / vmax
            parts.append(f'<rect x="{x:.1f}" y="{y + 6}" width="{wv:.1f}" height="34" fill="{cols["other"]}"/>')
            x += wv
        total = a["hard_total"]
        parts.append(f'<text x="{x + 10:.1f}" y="{y + 31}" font-size="22" font-weight="700" fill="#222">{total}</text>')
    ly = 75 + row * len(systems)
    for i, code in enumerate(top + ["other"]):
        lx = (i % 4) * 225
        yy = ly + (i // 4) * 36
        parts.append(f'<rect x="{lx}" y="{yy}" width="20" height="20" fill="{cols[code]}"/>')
        parts.append(f'<text x="{lx + 28}" y="{yy + 17}" font-size="17" fill="#333">{esc(code)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def cost_time_chart(agg: dict, systems: list[str], colors: dict[str, str], suite: str = "weekly",
                    title: str = "Minutes per weekly schedule (median), with schedule cost") -> str:
    """Median time per weekly schedule, with each system's schedule cost (vs Shiftwright) and pass rate
    in the caption, so cost is never shown without time and legality."""
    items = []
    for s in systems:
        a = agg[s][suite]
        if a["median_latency_s"] is None:
            items.append((short(s), None, colors[s], "not run"))
            continue
        cost = fmt(a["median_cost_vs_sw"], 2, "× cost") if not s.startswith("shiftwright") else "1.00× cost"
        items.append((short(s), a["median_latency_s"] / 60, colors[s], f'{cost} · {a["passed"]}/{a["scored"]} legal'))
    vmax = max([v for _, v, _, _ in items if v] + [1])
    return bar_chart(items, title, unit=" min", vmax=vmax, caption_w=230)


def scatter(rows: list[dict], systems: list[str], colors: dict[str, str]) -> str:
    pts = [r for r in rows if r["suite"] == "weekly" and r.get("parsed") and r.get("hours_cap")]
    w, h, ml, mb, mt, mr = 900, 560, 90, 80, 50, 30
    xmax = max([150.0] + [100 * r["hours_used"] / r["hours_cap"] for r in pts])
    xmax = min(xmax, 400.0)
    pw, ph = w - ml - mr, h - mt - mb

    def X(v): return ml + pw * min(v, xmax) / xmax
    def Y(v): return mt + ph * (1 - v / 100)

    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="coverage vs hours" style="{FONT}">',
             f'<text x="0" y="28" font-size="24" font-weight="700" fill="#222">Coverage vs hours used (weekly build)</text>']
    for v in range(0, 101, 25):
        parts.append(f'<line x1="{ml}" x2="{w - mr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="#e5e5e5"/>')
        parts.append(f'<text x="{ml - 10}" y="{Y(v) + 6:.1f}" font-size="18" text-anchor="end" fill="#444">{v}%</text>')
    step = 50 if xmax <= 250 else 100
    for v in range(0, int(xmax) + 1, step):
        parts.append(f'<text x="{X(v):.1f}" y="{h - mb + 28}" font-size="18" text-anchor="middle" fill="#444">{v}%</text>')
    parts.append(f'<line x1="{X(100):.1f}" x2="{X(100):.1f}" y1="{mt}" y2="{h - mb}" stroke="#222" stroke-dasharray="6 5"/>')
    parts.append(f'<text x="{X(100) + 8:.1f}" y="{h - mb - 10}" font-size="17" fill="#222">hours cap</text>')
    parts.append(f'<text x="{ml + pw / 2:.1f}" y="{h - 18}" font-size="19" text-anchor="middle" fill="#333">'
                 'hours scheduled, % of the corporate cap</text>')
    parts.append(f'<text x="22" y="{mt + ph / 2:.1f}" font-size="19" text-anchor="middle" fill="#333" '
                 f'transform="rotate(-90 22 {mt + ph / 2:.1f})">coverage</text>')
    for r in pts:
        x, y = X(100 * r["hours_used"] / r["hours_cap"]), Y(r["coverage_pct"])
        c = colors[r["system"]]
        fill = c if r["passed"] else "white"
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9" fill="{fill}" stroke="{c}" stroke-width="3">'
                     f'<title>{esc(short(r["system"]))} {esc(r["scenario"])}: {r["hard_count"]} hard violations</title></circle>')
    parts.append("</svg>")
    return "".join(parts)


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #
CSS = """
body{%s;margin:0;background:#fff;color:#1d1d1d;font-size:19px;line-height:1.45}
main{max-width:1280px;margin:0 auto;padding:28px 36px 80px}
h1{font-size:40px;margin:0 0 6px}h2{font-size:30px;margin:44px 0 12px;border-bottom:3px solid #eee;padding-bottom:6px}
h3{font-size:22px;margin:22px 0 8px}
.banner{background:#fff3cd;border:3px solid #e0a800;padding:14px 18px;font-size:22px;font-weight:700;margin:16px 0}
.note{color:#555;font-size:17px}
table{border-collapse:collapse;width:100%%;margin:8px 0 18px}
th,td{border-bottom:1px solid #e3e3e3;padding:7px 9px;text-align:left;vertical-align:top}
th{background:#f6f6f6;font-size:16px}table.summary{font-size:17px}td:first-child{white-space:nowrap}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.big td{font-size:22px}.good{color:#0b7a53;font-weight:700}.bad{color:#b3261e;font-weight:700}
.charts{display:grid;grid-template-columns:1fr;gap:30px}\n.cols{display:grid;grid-template-columns:3fr 2fr;gap:28px}table.vs{width:auto;min-width:60%%}
table.runs{font-size:14px}table.runs td,table.runs th{padding:3px 6px}
code{background:#f3f3f3;padding:1px 5px;border-radius:4px;font-size:90%%}
.swatch{display:inline-block;width:16px;height:16px;border-radius:3px;vertical-align:-2px;margin-right:6px}
""" % FONT


def _honesty_table(agg, systems, colors) -> str:
    out = ['<table class="big"><tr><th>System</th><th class="n">Said infeasible<br>(correct)</th>'
           '<th class="n">Named the conflict</th><th class="n">Returned a schedule anyway<br>(false "feasible")</th>'
           '<th class="n">No usable answer</th><th class="n">Said infeasible on a<br>feasible store</th></tr>']
    for s in systems:
        h = agg[s]["honesty_counts"]
        fp = agg[s]["weekly_false_infeasible"]
        n_inf = agg[s]["honesty"]["scored"]
        if n_inf == 0 and not any(h.values()):
            out.append(f'<tr><td><span class="swatch" style="background:{colors[s]}"></span>{esc(short(s))}</td>'
                       f'<td colspan="5" class="note">not run ({esc(_why_unavailable(agg, s))})</td></tr>')
            continue
        out.append(
            f'<tr><td><span class="swatch" style="background:{colors[s]}"></span>{esc(short(s))}</td>'
            f'<td class="n {"good" if h["TP"] else ""}">{h["TP"]} / {n_inf}</td>'
            f'<td class="n">{agg[s]["named_conflict"]} / {n_inf}</td>'
            f'<td class="n {"bad" if h["FN"] else ""}">{h["FN"]}</td><td class="n">{h["no_answer"]}</td>'
            f'<td class="n {"bad" if fp else ""}">{fp} / {agg[s]["weekly"]["scored"]}</td></tr>')
    out.append("</table>")
    return "".join(out)


def _why_unavailable(agg, s) -> str:
    return agg.get("_notes", {}).get(s, "unavailable")


def _summary_table(agg, systems, colors) -> str:
    out = ['<table class="summary"><tr><th>System</th><th class="n">Runs</th><th class="n">0 hard violations</th>'
           '<th class="n">Hard violations</th><th class="n">Unparseable</th><th class="n">Truncated</th>'
           '<th class="n">Budget respected</th><th class="n">Median coverage<br>(readable)</th>'
           '<th class="n">Median cost vs Shiftwright</th><th class="n">Median time per schedule</th>'
           '<th class="n">Total time (weekly)</th><th class="n">API cost, all suites</th></tr>']
    for s in systems:
        a = agg[s]["weekly"]
        if a["scored"] == 0:
            out.append(f'<tr><td><span class="swatch" style="background:{colors[s]}"></span>{esc(short(s))}</td>'
                       f'<td colspan="11" class="note">not run ({esc(_why_unavailable(agg, s))})</td></tr>')
            continue
        out.append(
            f'<tr><td><span class="swatch" style="background:{colors[s]}"></span>{esc(short(s))}</td>'
            f'<td class="n">{a["scored"]}</td><td class="n">{a["passed"]} / {a["scored"]}</td>'
            f'<td class="n">{a["hard_total"]}</td><td class="n">{a["unparseable"]}</td><td class="n">{a["truncated"]}</td>'
            f'<td class="n">{a["budget_ok"]} / {a["parsed"]}</td><td class="n">{fmt(a["median_coverage"], 1, "%")}</td>'
            f'<td class="n">{fmt(a["median_cost_vs_sw"], 2, "×")}</td><td class="n">{fmt(a["median_latency_s"], 1, " s")}</td>'
            f'<td class="n">{fmt_duration(a["total_latency_s"])}</td>'
            f'<td class="n">{"$%.2f" % agg[s]["cost_usd"] if s != "shiftwright" else "–"}</td></tr>')
    out.append("</table>")
    return "".join(out)


def _repair_table(rows, systems, colors) -> str:
    rs = [r for r in rows if r["suite"] == "repair"]
    if not rs:
        return '<p class="note">Call-out suite not run.</p>'
    out = ['<table><tr><th>System</th><th>Scenario</th><th class="n">Coverage before → after</th>'
           '<th class="n">Hard violations</th><th class="n">Changes before now</th>'
           '<th class="n">Called-out staff still scheduled</th><th class="n">Call list (unknown ids)</th>'
           '<th class="n">Latency</th></tr>']
    for s in systems:
        for r in sorted((r for r in rs if r["system"] == s), key=lambda r: r["scenario"]):
            sw = f'<span class="swatch" style="background:{colors[s]}"></span>{esc(short(s))}'
            if r["outcome"] == "unavailable":
                out.append(f'<tr><td>{sw}</td><td>{esc(r["scenario"])}</td><td colspan="6" class="note">'
                           f'unavailable: {esc(r["note"])}</td></tr>')
                continue
            chg, still = r.get("changes_before_now"), r.get("callouts_still_working")
            cl = r.get("call_list_size")
            out.append(
                f'<tr><td>{sw}</td><td>{esc(r["scenario"])}</td>'
                f'<td class="n">{fmt(r.get("coverage_before"), 1, "%")} → {fmt(r.get("coverage_after"), 1, "%")}</td>'
                f'<td class="n {"bad" if r.get("hard_count") else "good"}">{r.get("hard_count", "–")}</td>'
                f'<td class="n {"bad" if chg else ""}">{fmt(chg)}</td><td class="n {"bad" if still else ""}">{fmt(still)}</td>'
                f'<td class="n">{fmt(cl)} ({fmt(r.get("call_list_unknown_ids"))})</td>'
                f'<td class="n">{fmt(r["latency_s"], 1, " s")}</td></tr>')
    out.append("</table>")
    srcs = sorted({r.get("base_source") for r in rs if r.get("base_source")})
    out.append('<p class="note">Base schedule: ' + "; ".join(esc(s) for s in srcs) +
               '. "Changes before now" counts employees (other than those who called out) whose assignment '
               'before the call-out time, or on an earlier day, differs from the base schedule.</p>')
    return "".join(out)


def _violation_list(run_dir: Path, run: dict) -> str:
    val = json.loads((run_dir / run["path"] / "validation.json").read_text())
    by: dict[str, list] = {}
    for v in val["violations"]:
        if v["severity"] == "hard":
            by.setdefault(v["code"], []).append(v)
    out = ['<table><tr><th>Rule broken</th><th class="n">Count</th><th>What the validator says (first 2)</th></tr>']
    for code, vs in sorted(by.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        msgs = "<br>".join(esc(v["message"]) + (f' <span class="note">[{esc(v["law_rule_id"])}]</span>'
                                                if v.get("law_rule_id") else "") for v in vs[:2])
        out.append(f'<tr><td><code>{esc(code)}</code></td><td class="n">{len(vs)}</td><td>{msgs}</td></tr>')
    out.append("</table>")
    return "".join(out)


def _worked(ex, sw, run_dir: Path, rel: str, colors) -> str:
    if ex is None:
        return '<p class="note">No baseline weekly run with violations.</p>'
    def cell(r, key, nd=1, suffix=""):
        return fmt(r.get(key), nd, suffix) if r and r.get("parsed") else "–"
    sw_ok = sw is not None and sw.get("parsed")
    head = [("System", short(ex["system"]), "Shiftwright")]
    rows = [
        ("Hard violations", str(ex["hard_count"]), str(sw["hard_count"]) if sw_ok else "unavailable"),
        ("Rule types broken", str(len(ex["by_code"])), str(len(sw["by_code"])) if sw_ok else "–"),
        ("Status claimed", ex.get("status") or "–", sw.get("status") if sw_ok else "–"),
        ("Coverage of demand", cell(ex, "coverage_pct", 1, "%"), cell(sw, "coverage_pct", 1, "%")),
        ("Hours scheduled / cap", f'{fmt(ex["hours_used"])} / {fmt(ex["hours_cap"])}',
         f'{fmt(sw["hours_used"])} / {fmt(sw["hours_cap"])}' if sw_ok else "–"),
        ("Wage cost", cell(ex, "wage_cost", 2, ""), cell(sw, "wage_cost", 2, "")),
        ("Latency", fmt(ex["latency_s"], 1, " s"), fmt(sw["latency_s"], 1, " s") if sw else "–"),
    ]
    c_b, c_s = colors.get(ex["system"], "#999"), SW_COLOR
    out = [f'<p>Same store, same inputs: <code>{esc(ex["scenario"])}</code>. '
           f'Files: <a href="{esc(rel)}/{esc(ex["path"])}/">{esc(short(ex["system"]))}</a>'
           + (f' · <a href="{esc(rel)}/{esc(sw["path"])}/">Shiftwright</a>' if sw else "") + '</p>',
           '<table class="big vs"><tr><th></th>'
           f'<th class="n"><span class="swatch" style="background:{c_b}"></span>{esc(head[0][1])}</th>'
           f'<th class="n"><span class="swatch" style="background:{c_s}"></span>Shiftwright</th></tr>']
    for label, a, b in rows:
        bad_a = label == "Hard violations" and a != "0"
        good_b = label == "Hard violations" and b == "0"
        out.append(f'<tr><td>{esc(label)}</td><td class="n {"bad" if bad_a else ""}">{esc(a)}</td>'
                   f'<td class="n {"good" if good_b else ""}">{esc(b)}</td></tr>')
    out.append("</table>")
    out.append(f'<div class="cols"><div><h3>{esc(short(ex["system"]))}: what the validator found</h3>'
               f'{_violation_list(run_dir, ex)}</div>')
    if sw_ok and sw["hard_count"] == 0:
        out.append('<div><h3>Shiftwright: what the validator found</h3><p class="good" style="font-size:26px">'
                   'No hard violations.</p><p class="note">Every shift checked against training, availability, '
                   'minor and break law from the law pack, hours caps and the budget.</p></div>')
    elif sw_ok:
        out.append(f'<div><h3>Shiftwright: what the validator found</h3>{_violation_list(run_dir, sw)}</div>')
    else:
        out.append('<div><h3>Shiftwright</h3><p class="note">Not run on this scenario.</p></div>')
    out.append("</div>")
    return "".join(out)


def _runs_table(rows, rel: str) -> str:
    out = ['<table class="runs"><tr><th>System</th><th>Scenario</th><th>Outcome</th><th>Status</th>'
           '<th class="n">Hard</th><th>By code</th><th class="n">Coverage %</th><th class="n">Wage $</th>'
           '<th class="n">Objective $</th><th class="n">Hours / cap</th><th class="n">vs SW</th><th>Honesty</th>'
           '<th class="n">Latency s</th><th>Files</th></tr>']
    for r in rows:
        codes = ", ".join(f"{k} {v}" for k, v in sorted(r.get("by_code", {}).items()))
        hours = f'{fmt(r.get("hours_used"))} / {fmt(r.get("hours_cap"))}' if r.get("hours_cap") is not None else "–"
        out.append(
            f'<tr id="run-{esc(r["key"])}"><td>{esc(short(r["system"]))}</td><td>{esc(r["scenario"])}</td>'
            f'<td>{esc(r["outcome"])}</td><td>{esc(r.get("status") or "–")}</td>'
            f'<td class="n">{r.get("hard_count", "–")}</td><td>{esc(codes)}</td>'
            f'<td class="n">{fmt(r.get("coverage_pct"), 1)}</td><td class="n">{fmt(r.get("wage_cost"), 2)}</td>'
            f'<td class="n">{fmt(r.get("objective"), 2)}</td><td class="n">{hours}</td>'
            f'<td class="n">{fmt(r.get("cost_vs_sw"), 2)}</td><td>{esc(r.get("honesty", "–"))}</td>'
            f'<td class="n">{fmt(r.get("latency_s"), 2)}</td>'
            f'<td><a href="{esc(rel)}/{esc(r["path"])}/">files</a></td></tr>')
    out.append("</table>")
    return "".join(out)


def _pass_items(agg, names, colors, suite, notes):
    items = []
    for s in names:
        a = agg[s][suite]
        if a["scored"]:
            items.append((short(s), a["pass_rate"], colors[s], f'{a["passed"]} of {a["scored"]} schedules'))
        else:
            items.append((short(s), None, colors[s], f'not run: {notes.get(s, "")}'))
    return items


def _cov_items(agg, names, colors, suite, notes):
    items = []
    for s in names:
        a = agg[s][suite]
        if not a["scored"]:
            items.append((short(s), None, colors[s], f'not run: {notes.get(s, "")}'))
        elif a["median_legal_coverage"] is None:
            items.append((short(s), None, colors[s], "no schedule without hard violations"))
        else:
            items.append((short(s), a["median_legal_coverage"], colors[s], f'{a["passed"]} legal schedules'))
    return items


def _realistic_table(rows, agg, names, colors) -> str:
    out = ['<table class="summary"><tr><th>System</th><th class="n">Stores</th><th class="n">0 hard violations</th>'
           '<th class="n">Hard violations</th><th class="n">No loadable schedule</th><th class="n">Budget respected</th>'
           '<th class="n">Median coverage<br>(readable)</th><th class="n">Median time</th><th class="n">API cost</th>'
           '<th>Intake / assumptions</th></tr>']
    for s in names:
        a = agg[s]["realistic"]
        mine = [r for r in rows if r["system"] == s and r["suite"] == "realistic"]
        sw = f'<span class="swatch" style="background:{colors[s]}"></span>{esc(short(s))}'
        if not a["scored"]:
            note = next((r["note"] for r in mine if r.get("note")), "") or _why_unavailable(agg, s)
            out.append(f'<tr><td>{sw}</td><td colspan="9" class="note">not run ({esc(note)})</td></tr>')
            continue
        if s == "shiftwright:intake":
            rec = [r["intake_recall"] for r in mine if r.get("intake_recall") is not None]
            failed = sorted({k for r in mine for k in r.get("imports_failed", [])})
            extra = (f'facts captured from the narrative: {fmt(100 * sum(rec) / len(rec), 0, "%") if rec else "–"}'
                     + (f'; CSV imports rejected: {", ".join(failed)}' if failed else ""))
        else:
            n = [r.get("assumptions") or 0 for r in mine]
            extra = f'stated assumptions: {sum(n)} (contradictions with the CSVs not scored)'
        out.append(f'<tr><td>{sw}</td><td class="n">{a["scored"]}</td><td class="n">{a["passed"]} / {a["scored"]}</td>'
                   f'<td class="n">{a["hard_total"]}</td><td class="n">{a["unparseable"] + a["truncated"]}</td>'
                   f'<td class="n">{a["budget_ok"]} / {a["parsed"]}</td><td class="n">{fmt(a["median_coverage"], 1, "%")}</td>'
                   f'<td class="n">{fmt_duration(a["median_latency_s"])}</td>'
                   f'<td class="n">{"$%.2f" % agg[s]["cost_usd"] if not s.startswith("shiftwright") else "–"}</td>'
                   f'<td class="note">{esc(extra)}</td></tr>')
    out.append("</table>")
    return "".join(out)


def build(run_dir: Path, report_dir: Path, manifest: dict) -> Path:
    rows = collect(run_dir)
    systems = manifest["systems"]
    names = [s["name"] for s in systems]
    agg = aggregate(rows, names)
    agg["_notes"] = {s["name"]: s.get("unavailable_reason") or "" for s in systems}
    colors = color_for(names)
    real_names = [n for n in names if is_realistic(n)]
    real_names = sorted(real_names, key=lambda n: (n != "shiftwright:intake", n))
    names = [n for n in names if not is_realistic(n)]
    ex, ex_sw = worked_example(rows)
    rex, rex_sw = worked_example(rows, suite="realistic", ref="shiftwright:intake", prefix="chat:")
    report_dir.mkdir(parents=True, exist_ok=True)
    rel = os.path.relpath(run_dir, report_dir)

    data = {"run_id": manifest["run_id"], "mock_baselines": manifest["mock_baselines"], "systems": systems,
            "aggregates": {k: v for k, v in agg.items() if k != "_notes"}, "rows": rows,
            "worked_example": ex["key"] if ex else None,
            "realistic_worked_example": rex["key"] if rex else None}
    (report_dir / "report.json").write_text(json.dumps(data, indent=1) + "\n")

    pass_items = []
    for s in names:
        a = agg[s]["weekly"]
        if a["scored"]:
            pass_items.append((short(s), a["pass_rate"], colors[s], f'{a["passed"]} of {a["scored"]} schedules'))
        else:
            pass_items.append((short(s), None, colors[s], f'not run: {agg["_notes"][s]}'))
    cov_items = []
    for s in names:
        a = agg[s]["weekly"]
        if not a["scored"]:
            cov_items.append((short(s), None, colors[s], f'not run: {agg["_notes"][s]}'))
        elif a["median_legal_coverage"] is None:
            cov_items.append((short(s), None, colors[s], "no schedule without hard violations"))
        else:
            cov_items.append((short(s), a["median_legal_coverage"], colors[s], f'{a["passed"]} legal schedules'))

    n_scen = len({r["scenario"] for r in rows})
    suites = ", ".join(manifest["suites"])
    p = [f"<!doctype html><html><head><meta charset='utf-8'><title>Shiftwright evals {esc(manifest['run_id'])}</title>",
         f"<style>{CSS}</style></head><body><main>",
         "<h1>Shiftwright vs general-purpose AI</h1>",
         f'<p class="note">Run <code>{esc(manifest["run_id"])}</code> · {n_scen} scenarios · suites: {esc(suites)}'
         f'{" (quick)" if manifest["quick"] else ""} · every number below is recounted from the run folder '
         f'<a href="{esc(rel)}/">{esc(rel)}/</a> and scored only by the independent validator.</p>']
    spend = sum(r.get("cost_usd") or 0 for r in rows)
    if spend:
        p.append(f'<p class="note">OpenRouter cost of the baseline responses in this report (sum of '
                 f'<code>usage.cost</code> in run.json): <b>${spend:.2f}</b>. Cached replies are reused, not re-billed.</p>')
    if manifest.get("rescored_from"):
        reused = sorted({r["scenario"] for r in rows if r.get("reused_from")})
        p.append(f'<div class="banner" style="background:#e8f1fb;border-color:#3a6ea5">Baseline rows are '
                 f'<b>re-scored</b> from run <code>{esc(manifest["rescored_from"])}</code>: the models\' replies to that '
                 f'run\'s prompts, re-validated against the current scenarios ({len(reused)} scenarios, matched by '
                 f'scenario id and model). No new API calls. Shiftwright was re-run on the current engine. '
                 f'Call-out inputs are reused, so every system repairs the same schedule.</div>')
        changed = {}
        for sid in reused:
            f = run_dir / "_inputs" / sid / "config_changes.json"
            if f.exists():
                changed[sid] = json.loads(f.read_text())
        fields = sorted({c for v in changed.values() for c in v["changed"]})
        if fields:
            p.append('<p class="note">Store config fields that differ from the prompts the models saw: '
                     + ", ".join(f"<code>{esc(c)}</code>" for c in fields) + '. Replies are scored under the current rules.</p>')
        for name, sids in sorted((manifest.get("not_rescored") or {}).items()):
            p.append(f'<p class="note"><b>Not re-scored for {esc(short(name))}</b> (would need a new prompt): '
                     + ", ".join(f"<code>{esc(x)}</code>" for x in sids) + '</p>')
    if manifest["mock_baselines"]:
        p.append('<div class="banner">MOCK BASELINES: the baseline rows are canned bad outputs used to test the '
                 'harness. They are not results from any real model.</div>')
    for s in systems:
        if not s["available"]:
            p.append(f'<p class="note"><b>{esc(short(s["name"]))}</b> unavailable: {esc(s["unavailable_reason"])}.</p>')
    has_real = any(r["suite"] == "realistic" for r in rows)
    if has_real:
        from .realistic import LIMITATIONS
        p.append("<h2>From the same raw inputs</h2>")
        p.append('<p class="note">Every system gets only what a store manager has: their own description of the '
                 'store, the corporate CSV exports (roster, training, availability, forecast, history) and the location. '
                 'No law pack, no rules, no config. <b>Chat</b> = one plain chat turn with the CSVs pasted in, asking '
                 'for a CSV schedule. <b>Shiftwright</b> = the real product: CSV import with the proposed mappings, the '
                 'onboarding chat, then the solver. Every schedule is mapped back to the true employee and job ids '
                 'and checked by the validator against the true store, including the real labor law for its location.'
                 f'{" Shiftwright intake agent: " + esc(manifest.get("intake_agent") or "") + "." if manifest.get("intake_agent") else ""}</p>')
        if manifest.get("intake_agent") == "fake":
            p.append('<div class="banner">Shiftwright intake ran with the API\'s fake agent (no model key): it does not '
                     'read the narrative, so only the CSV imports shaped its store.</div>')
        p.append("<div class='charts'>")
        p.append(bar_chart(_pass_items(agg, real_names, colors, "realistic", agg["_notes"]),
                           "Same raw inputs: schedules with zero hard violations"))
        p.append(stacked_codes(agg, real_names, "realistic", "Same raw inputs: hard violations by rule"))
        p.append(bar_chart(_cov_items(agg, real_names, colors, "realistic", agg["_notes"]),
                           "Same raw inputs: median coverage of legal schedules"))
        p.append(cost_time_chart(agg, real_names, colors, suite="realistic",
                                 title="Same raw inputs: minutes per schedule, with cost"))
        p.append("</div>")
        p.append(_realistic_table(rows, agg, real_names, colors))
        p.append("<h3>Worked example: same raw inputs</h3>")
        p.append(_worked(rex, rex_sw, run_dir, rel, colors))
        p.append('<div class="banner" style="background:#f4f4f4;border-color:#999;font-weight:400;font-size:18px">'
                 '<b>Limitations.</b><ul>' + "".join(f"<li>{esc(x)}</li>" for x in LIMITATIONS) + '</ul></div>')
        p.append("<h2 style='margin-top:60px'>Solver vs. LLM-as-solver (both given Shiftwright's config, law pack and rules)</h2>")
    p.append("<h2>Hard rules</h2><div class='charts'>")
    p.append(bar_chart(pass_items, "Weekly schedules with zero hard violations"))
    p.append(stacked_codes(agg, names, "weekly", "Hard violations by rule (weekly build, all runs)"))
    p.append("</div>")
    p.append(_summary_table(agg, names, colors))
    p.append('<p class="note">Unparseable and truncated replies count as failed schedules. "Cost vs Shiftwright" '
             'compares the validator-recomputed objective (wages + premiums + gap and soft penalties) on scenarios '
             'where both schedules pass every hard rule.</p>')
    p.append("<h2>Coverage and cost</h2><div class='charts'>")
    p.append(bar_chart(cov_items, "Median coverage of demand, schedules with no hard violations"))
    p.append(cost_time_chart(agg, names, colors))
    p.append(scatter(rows, names, colors))
    p.append("</div><p class='note'>Cost vs Shiftwright: median ratio of validator-recomputed objectives, over "
             "scenarios where both schedules break no hard rule; below 1.00× = cheaper than Shiftwright. "
             "Filled dot = no hard violations; hollow = breaks at least one hard rule. "
             "Right of the dashed line = over the corporate hours budget.</p>")
    p.append("<h2>Honesty on impossible stores</h2>")
    p.append('<p class="note">Infeasible scenarios (hard rules conflict, so no legal schedule exists). '
             '"Said infeasible on a feasible store" is counted over the weekly-build scenarios.</p>')
    p.append(_honesty_table(agg, names, colors))
    suspects = sorted({(r["scenario"], r["expected_suspect"]) for r in rows if r.get("expected_suspect")})
    for sid, why in suspects:
        said = sorted(short(r["system"]) for r in rows if r["scenario"] == sid and r.get("honesty") == "suspect")
        clean = sorted(short(r["system"]) for r in rows if r["scenario"] == sid and r.get("passed")
                       and r.get("shifts") and not r.get("said_infeasible"))
        counter = (f' However, {esc(", ".join(clean))} returned a schedule for it with 0 hard violations, so the '
                   f'store may in fact be feasible; under review.' if clean else "")
        p.append(f'<p class="note"><b>Suspect scenario</b> <code>{esc(sid)}</code>: {esc(why)} '
                 f'Saying "infeasible" there is not counted as a false "infeasible"'
                 f'{" (said so: " + esc(", ".join(said)) + ")" if said else ""}.{counter}</p>')
    p.append("<h2>Call-out repair</h2>")
    p.append(_repair_table(rows, names, colors))
    p.append("<h2>Worked example</h2>")
    p.append(_worked(ex, ex_sw, run_dir, rel, colors))
    p.append("<h2>All runs</h2>")
    p.append(_runs_table(rows, rel))
    p.append("</main></body></html>\n")
    out = report_dir / "report.html"
    out.write_text("".join(p))
    return out

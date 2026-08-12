"""P3: static run-record page. Scans runs/, renders runs/index.html.

Every run keeps its full evidence chain (params, logs, figures, verdicts);
this page makes it browsable for human + demo narratable for interviews.
"""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

from .config import RUNS


def _load(d: Path, name: str):
    p = d / name
    try:
        return json.loads(p.read_text()) if p.exists() else None
    except Exception:
        return None


def _badge(verdict: str | None) -> str:
    colors = {"pass": "#2da44e", "pass_with_warnings": "#bf8700",
              "fail": "#cf222e", None: "#6e7781"}
    label = verdict or "no verdict"
    return f'<span style="background:{colors[verdict]};color:#fff;padding:2px 10px;border-radius:12px;font-size:12px">{html.escape(label)}</span>'


_STATUS_COLORS = {"pass": "#2da44e", "warn": "#bf8700", "fail": "#cf222e",
                  "info": "#0969da", "skip": "#6e7781"}


def _check_li(c: dict) -> str:
    color = _STATUS_COLORS.get(c["status"], "#57606a")
    fix = ""
    if c.get("fix") and c["status"] not in ("pass", "info", "skip"):
        fix = f'<br><i>fix: {html.escape(c["fix"])}</i>'
    return (f'<li><b style="color:{color}">{html.escape(c["status"])}</b> '
            f'<code>{html.escape(c["check"])}</code>: '
            f'{html.escape(str(c["detail"]))}{fix}</li>')


def _run_section(d: Path) -> str:
    fetch = _load(d, "fetch.json") or {}
    relax = _load(d, "relax.json") or {}
    summary = _load(d, "summary.json") or {}
    conv = _load(d, "convergence.json") or {}
    ver = _load(d, "verify.json") or {}
    attempts = _load(d, "attempts.json") or {}

    rid = d.name
    try:
        ts = datetime.strptime(rid[:15], "%Y%m%d-%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        ts = "(unknown date)"
    rows = []
    if fetch:
        rows.append(("结构", f"{html.escape(str(fetch.get('formula','?')))} "
                            f"({fetch.get('n_atoms','?')} atoms, source={fetch.get('source')}, "
                            f"mp_id={fetch.get('mp_id')}, ref_gap={fetch.get('band_gap_ref')})"))
    if relax:
        rows.append(("弛豫", f"converged={relax.get('converged')}, "
                            f"fmax={relax.get('max_force_ev_per_a'):.3f} eV/Å, "
                            f"E={relax.get('total_energy_ev'):.3f} eV, "
                            f"ecut={relax.get('ecut_ev')}, kpts={relax.get('kpts')}"))
    if summary:
        rows.append(("能带", f"gap={summary.get('band_gap_ev'):.3f} eV "
                            f"({summary.get('gap_type','?')}, "
                            f"VBM@{summary.get('vbm',{}).get('label')}, "
                            f"CBM@{summary.get('cbm',{}).get('label')}), "
                            f"Ef={summary.get('fermi_ev'):.2f} eV, "
                            f"engine={summary.get('engine','?')}, "
                            f"scf kpts={summary.get('kpts_scf')}, ecut={summary.get('ecut_ev')}"))
    if conv:
        rows.append(("收敛门", f"converged={conv.get('converged')}, "
                              f"推荐 ecut={conv.get('recommended_ecut_ev')} eV, "
                              f"kpts_density={conv.get('recommended_kpts_density')}"))
    if attempts.get("attempts"):
        trail = " → ".join(f"ecut {a['ecut_ev']}/kd {a['kpts_density']}"
                           + ("✓" if a["params_converged"] else "✗")
                           for a in attempts["attempts"])
        rows.append(("重试链", trail))

    checks_html = ""
    if ver.get("checks"):
        items = "".join(_check_li(c) for c in ver["checks"])
        checks_html = f"<ul>{items}</ul>"

    figs = ""
    for png in ("bands.png", "dos.png"):
        if (d / png).exists():
            figs += f'<a href="{rid}/{png}"><img src="{rid}/{png}" style="max-width:420px;margin:4px;border:1px solid #ddd"></a>'

    table = "".join(f"<tr><td style='color:#57606a;padding-right:12px'>{k}</td><td>{v}</td></tr>"
                    for k, v in rows)
    return f"""
<section style="border:1px solid #d0d7de;border-radius:8px;padding:16px;margin:16px 0">
  <h3 style="margin:0 0 8px">{html.escape(rid)} {_badge(ver.get('verdict'))}</h3>
  <div style="color:#57606a;font-size:12px;margin-bottom:8px">{ts}</div>
  <table style="font-size:14px">{table}</table>
  {checks_html}
  <div>{figs}</div>
</section>"""


def build_report() -> Path:
    runs = sorted((d for d in RUNS.iterdir() if d.is_dir()), reverse=True)
    body = "\n".join(_run_section(d) for d in runs)
    page = f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><title>matmcp run records</title></head>
<body style="max-width:960px;margin:24px auto;font-family:system-ui,sans-serif;color:#1f2328">
<h1>matmcp 运行记录 <small style="color:#57606a;font-weight:normal">generated {datetime.now():%Y-%m-%d %H:%M}</small></h1>
<p style="color:#57606a">每一次计算的全部证据链：参数 → 日志 → 图 → 机器验收结论。共 {len(runs)} 次运行。</p>
{body}
</body></html>"""
    out = RUNS / "index.html"
    out.write_text(page, encoding="utf-8")
    return out

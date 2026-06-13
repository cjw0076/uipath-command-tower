#!/usr/bin/env python3
"""Export a static GitHub Pages demo for Competition Command Tower.

The FastAPI dashboard is the richer local/live service, but GitHub Pages gives
Devpost judges a zero-auth hosted overview. This static page is intentionally
public-safe: it embeds a synthetic portfolio snapshot and no credentials.
"""
from __future__ import annotations

import html
import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("PAGES_OUT", ROOT / "out" / "pages"))


def load_snapshot() -> dict:
    path = ROOT / "eval" / "report.json"
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def pill(text: str, kind: str = "ok") -> str:
    return f'<span class="pill {kind}">{html.escape(text)}</span>'


def render(report: dict) -> str:
    summary = report["aggregate"]
    rows = []
    for case in report["cases"]:
        status = str(case["terminal_status"])
        readiness = case["readiness_score"]
        exceptions = ", ".join(case.get("exceptions", [])) or "none"
        rows.append(
            "<tr>"
            f"<td><strong>{html.escape(case['name'])}</strong><br><small>{html.escape(case['track'])}</small></td>"
            f"<td>{pill(status, 'ok' if status == 'submitted' else 'warn')}</td>"
            f"<td>{case['stages_completed']}/7</td>"
            f"<td>{readiness:.3f}</td>"
            f"<td>{case['human_gates']}</td>"
            f"<td>{html.escape(exceptions)}</td>"
            "</tr>"
        )

    report_json = html.escape(json.dumps(report, ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Competition Command Tower - UiPath Maestro Case</title>
<style>
:root {{
  --bg:#0a0f14; --panel:#121923; --ink:#e6edf5; --muted:#8ea2b8;
  --line:#243244; --uipath:#fa4616; --ok:#3ddc97; --warn:#ffcc66; --blue:#61c2ff;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
  font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
header {{ padding:34px 24px 20px; border-bottom:1px solid var(--line);
  background:linear-gradient(180deg,#111a25,#0a0f14); }}
main {{ max-width:1160px; margin:0 auto; padding:22px; display:grid; gap:18px; }}
h1 {{ margin:0 0 8px; font-size:34px; letter-spacing:.2px; }}
h1 span {{ color:var(--uipath); }}
p {{ color:var(--muted); max-width:860px; }}
.grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }}
@media(max-width:900px) {{ .grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
.kpi,.card {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; }}
.kpi {{ padding:16px; }}
.kpi b {{ display:block; font-size:28px; }}
.kpi small, small {{ color:var(--muted); }}
.card {{ padding:18px; overflow:auto; }}
table {{ width:100%; border-collapse:collapse; min-width:860px; }}
th,td {{ text-align:left; padding:10px 9px; border-bottom:1px solid var(--line); vertical-align:top; }}
th {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.5px; }}
.pill {{ display:inline-block; padding:3px 9px; border-radius:999px; font-size:12px; font-weight:700; }}
.ok {{ color:#062317; background:var(--ok); }}
.warn {{ color:#241b00; background:var(--warn); }}
.links a {{ color:var(--blue); margin-right:16px; }}
pre {{ white-space:pre-wrap; word-break:break-word; background:#071018; border:1px solid var(--line);
  border-radius:8px; padding:14px; color:#b9c8d8; font-size:12px; max-height:360px; overflow:auto; }}
</style>
</head>
<body>
<header>
  <h1><span>UiPath</span> Competition Command Tower</h1>
  <p>A Maestro Case control plane for parallel hackathon operations: rule intake,
  human gates, coding-agent routing, readiness audit, exception recovery, and
  append-only evidence. This hosted page is a public-safe static snapshot; the
  repository also includes the runnable FastAPI dashboard and 58-test engine.</p>
</header>
<main>
  <section class="grid">
    <div class="kpi"><b>{summary['cases']}</b><small>cases modelled</small></div>
    <div class="kpi"><b>{summary['submitted']}</b><small>simulated submitted</small></div>
    <div class="kpi"><b>{summary['distinct_exception_count']}</b><small>exception classes</small></div>
    <div class="kpi"><b>{summary['total_audit_events']}</b><small>audit events</small></div>
  </section>
  <section class="card">
    <h2>Portfolio Evaluation</h2>
    <table>
      <thead><tr><th>Case</th><th>Status</th><th>Stages</th><th>Readiness</th><th>Human gates</th><th>Exceptions</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </section>
  <section class="card">
    <h2>Judge-Facing Links</h2>
    <p class="links">
      <a href="https://github.com/cjw0076/uipath-command-tower">GitHub repo</a>
      <a href="https://youtu.be/g8fEB-X1hiI">Demo video</a>
      <a href="docs/presentation_deck.md">Presentation deck</a>
      <a href="docs/DEFICIENCY_CLOSURE.md">Deficiency closure</a>
    </p>
    <p>Important: this public Pages URL is a hosted demo snapshot. The official
    UiPath Automation Cloud / Maestro live URL remains the final founder-gated
    proof for the Devpost submission.</p>
  </section>
  <section class="card">
    <h2>Raw Evaluation JSON</h2>
    <pre>{report_json}</pre>
  </section>
</main>
</body>
</html>
"""


def main() -> None:
    report = load_snapshot()
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    (OUT / "index.html").write_text(render(report), encoding="utf-8")
    docs = OUT / "docs"
    docs.mkdir()
    for name in ["presentation_deck.md", "DEFICIENCY_CLOSURE.md", "devpost_submission.md"]:
        src = ROOT / "docs" / name
        if src.exists():
            shutil.copy2(src, docs / name)
    shutil.copy2(ROOT / "README.md", OUT / "README.md")
    print(OUT)


if __name__ == "__main__":
    main()

"""CI reports: JUnit XML for test runners and rich HTML dashboards for human review."""
from __future__ import annotations
import html
from typing import Any


def generate_junit_xml(suite_name: str, test_runs: list[dict]) -> str:
    """Generate standard JUnit XML suitable for Jenkins, GitHub Actions, GitLab CI, etc."""
    total = len(test_runs)
    failures = sum(1 for r in test_runs if not r.get("success", False))
    total_time = sum(r.get("wall_s", 0.0) for r in test_runs)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<testsuite name="{html.escape(suite_name)}" tests="{total}" failures="{failures}" '
        f'errors="0" time="{total_time:.3f}">'
    ]

    for r in test_runs:
        name = html.escape(r.get("name", "unnamed_test"))
        classname = html.escape(f"stepproof.procedures.{name}")
        t = r.get("wall_s", 0.0)
        success = r.get("success", False)
        lines.append(f'  <testcase name="{name}" classname="{classname}" time="{t:.3f}">')
        if not success:
            err = html.escape(str(r.get("error", "Procedure execution failed")))
            lines.append(f'    <failure message="{err}">{err}</failure>')
        lines.append('  </testcase>')

    lines.append('</testsuite>')
    return "\n".join(lines)


def generate_html_report(suite_name: str, test_runs: list[dict]) -> str:
    """Generate modern, dark-themed HTML report displaying procedure test runs, drift, and evidence."""
    total = len(test_runs)
    passed = sum(1 for r in test_runs if r.get("success", False))
    failed = total - passed
    healed = sum(1 for r in test_runs if r.get("drifted", False))

    rows_html = []
    for r in test_runs:
        name = html.escape(r.get("name", "unnamed"))
        success = r.get("success", False)
        status_badge = '<span style="color:#22c55e;font-weight:700;">PASS</span>' if success else '<span style="color:#ef4444;font-weight:700;">FAIL</span>'
        drift_badge = '<span style="color:#eab308;">HEALED</span>' if r.get("drifted") else '<span style="color:#64748b;">NONE</span>'
        t = f"{r.get('wall_s', 0.0):.2f}s"
        checks_passed = r.get("checks_passed", 0)
        checks_total = r.get("checks_total", 0)
        err = html.escape(r.get("error", "") or "—")

        rows_html.append(f"""
        <tr>
          <td style="padding:10px 14px;border-bottom:1px solid #27272a;"><strong>{name}</strong></td>
          <td style="padding:10px 14px;border-bottom:1px solid #27272a;">{status_badge}</td>
          <td style="padding:10px 14px;border-bottom:1px solid #27272a;">{drift_badge}</td>
          <td style="padding:10px 14px;border-bottom:1px solid #27272a;">{checks_passed} / {checks_total}</td>
          <td style="padding:10px 14px;border-bottom:1px solid #27272a;">{t}</td>
          <td style="padding:10px 14px;border-bottom:1px solid #27272a;color:#a1a1aa;font-family:monospace;font-size:12px;">{err}</td>
        </tr>
        """)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>StepProof Suite Report — {html.escape(suite_name)}</title>
<style>
  body {{ margin:0; padding:32px; background:#09090b; color:#fafafa; font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif; }}
  .card {{ background:#18181b; border:1px solid #27272a; border-radius:10px; padding:24px; max-width:960px; margin:0 auto; }}
  h1 {{ margin:0 0 8px; font-size:20px; font-weight:700; }}
  .sub {{ color:#a1a1aa; font-size:13px; margin-bottom:24px; }}
  .stats {{ display:flex; gap:16px; margin-bottom:24px; }}
  .stat-box {{ background:#27272a; border-radius:8px; padding:12px 18px; flex:1; }}
  .stat-val {{ font-size:24px; font-weight:700; }}
  .stat-lbl {{ font-size:12px; color:#a1a1aa; text-transform:uppercase; letter-spacing:0.05em; }}
  table {{ width:100%; border-collapse:collapse; text-align:left; font-size:14px; }}
  th {{ padding:10px 14px; border-bottom:2px solid #3f3f46; color:#a1a1aa; font-weight:600; font-size:12px; text-transform:uppercase; }}
</style>
</head>
<body>
<div class="card">
  <h1>StepProof Test Suite Report: {html.escape(suite_name)}</h1>
  <div class="sub">Models perceive, code decides — deterministic verifiable procedure executions.</div>
  <div class="stats">
    <div class="stat-box"><div class="stat-val" style="color:#22c55e;">{passed}</div><div class="stat-lbl">Passed</div></div>
    <div class="stat-box"><div class="stat-val" style="color:#ef4444;">{failed}</div><div class="stat-lbl">Failed</div></div>
    <div class="stat-box"><div class="stat-val" style="color:#eab308;">{healed}</div><div class="stat-lbl">Self-Healed (Drift)</div></div>
    <div class="stat-box"><div class="stat-val">{total}</div><div class="stat-lbl">Total Procedures</div></div>
  </div>
  <table>
    <thead>
      <tr>
        <th>Procedure</th>
        <th>Status</th>
        <th>Drift</th>
        <th>Checks</th>
        <th>Wall Time</th>
        <th>Notes / Error</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows_html)}
    </tbody>
  </table>
</div>
</body>
</html>"""


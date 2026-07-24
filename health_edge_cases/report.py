"""Deterministic HTML reporting for the conformance suite."""

from __future__ import annotations

from html import escape

from . import __version__
from .runner import CaseResult, Expectation, SuiteResult


METRIC_LABELS = {
    "raw_completed_rows": "Raw rows marked completed",
    "completed_service_events": "Current completed service events",
    "unique_patients_served": "Unique synthetic patients served",
    "mapped_completed_events": "Mapped completed events",
    "unmapped_completed_events": "Unmapped completed events",
    "referrals_started": "Referrals started",
    "referrals_with_first_service": "Referrals reaching first service",
}

QUALITY_LABELS = {
    "source_events_with_multiple_versions": "Source events with multiple versions",
    "current_voided_events": "Current events marked voided",
    "unmapped_completed_encounters": "Completed encounters without a mapping",
    "completed_encounter_cancelled_appointment": (
        "Completed encounters linked to cancelled appointments"
    ),
    "completed_encounter_before_referral": (
        "Completed encounters dated before their referral"
    ),
    "completed_appointments_without_completed_encounter": (
        "Completed appointments without a completed encounter"
    ),
}


def _expectation_map(items: tuple[Expectation, ...]) -> dict[tuple[str, ...], int]:
    return {item.key: item.value for item in items}


def _status_badge(passed: bool) -> str:
    label = "Pass" if passed else "Fail"
    css_class = "pass" if passed else "fail"
    return f'<span class="badge {css_class}">{label}</span>'


def _metric_rows(case: CaseResult) -> str:
    actual = _expectation_map(case.actual_metrics)
    rows = []
    for expectation in case.expected_metrics:
        period_id, metric_id = expectation.key
        actual_value = actual.get(expectation.key)
        passed = actual_value == expectation.value
        rows.append(
            "<tr>"
            f"<td><code>{escape(period_id)}</code></td>"
            f"<td>{escape(METRIC_LABELS.get(metric_id, metric_id))}</td>"
            f"<td>{expectation.value}</td>"
            f"<td>{escape(str(actual_value))}</td>"
            f"<td>{_status_badge(passed)}</td>"
            "</tr>"
        )
    return "".join(rows)


def _quality_rows(case: CaseResult) -> str:
    actual = _expectation_map(case.actual_quality)
    rows = []
    for expectation in case.expected_quality:
        (check_id,) = expectation.key
        actual_value = actual.get(expectation.key)
        passed = actual_value == expectation.value
        rows.append(
            "<tr>"
            f"<td>{escape(QUALITY_LABELS.get(check_id, check_id))}</td>"
            f"<td>{expectation.value}</td>"
            f"<td>{escape(str(actual_value))}</td>"
            f"<td>{_status_badge(passed)}</td>"
            "</tr>"
        )
    return "".join(rows)


def _case_section(case: CaseResult) -> str:
    return f"""
    <article class="case" id="{escape(case.case_id)}">
      <div class="case-heading">
        <div>
          <p class="eyebrow">{escape(case.case_id)}</p>
          <h2>{escape(case.title)}</h2>
        </div>
        {_status_badge(case.passed)}
      </div>
      <p class="principle">{escape(case.principle)}</p>
      <div class="explanation-grid">
        <section>
          <h3>Naive failure</h3>
          <p>{escape(case.naive_failure)}</p>
        </section>
        <section>
          <h3>Expected resolution</h3>
          <p>{escape(case.expected_resolution)}</p>
        </section>
      </div>
      <h3>Reporting metrics</h3>
      <div class="table-wrap" role="region" aria-label="Reporting metrics for {escape(case.title)}" tabindex="0">
        <table>
          <caption>Reporting metrics for {escape(case.title)}</caption>
          <thead><tr><th scope="col">Period</th><th scope="col">Metric</th><th scope="col">Expected</th><th scope="col">Actual</th><th scope="col">Result</th></tr></thead>
          <tbody>{_metric_rows(case)}</tbody>
        </table>
      </div>
      <h3>Quality signals</h3>
      <div class="table-wrap" role="region" aria-label="Quality signals for {escape(case.title)}" tabindex="0">
        <table>
          <caption>Quality signals for {escape(case.title)}</caption>
          <thead><tr><th scope="col">Check</th><th scope="col">Expected</th><th scope="col">Actual</th><th scope="col">Result</th></tr></thead>
          <tbody>{_quality_rows(case)}</tbody>
        </table>
      </div>
    </article>
    """


def render_report(result: SuiteResult) -> str:
    """Render a stable report that can be committed and checked in CI."""

    status = "All reference expectations pass" if result.passed else "Failures detected"
    case_links = "".join(
        f'<li><a href="#{escape(case.case_id)}">{escape(case.title)}</a></li>'
        for case in result.cases
    )
    cases = "".join(_case_section(case) for case in result.cases)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Health Data Edge Cases — v{__version__} validation report</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #17212b;
      --muted: #5b6670;
      --line: #d9e0e6;
      --paper: #ffffff;
      --wash: #f4f7f9;
      --brand: #0d6572;
      --brand-dark: #084c55;
      --pass: #176b45;
      --pass-bg: #e8f6ef;
      --fail: #9c2f2f;
      --fail-bg: #fdecec;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background: var(--wash);
      font: 16px/1.55 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      color: white;
      background: linear-gradient(130deg, var(--brand-dark), var(--brand));
      padding: 4.5rem 1.25rem 5rem;
    }}
    header > div, main {{ width: min(1080px, 100%); margin: 0 auto; }}
    h1 {{ margin: .2rem 0 .8rem; font-size: clamp(2.3rem, 6vw, 4.6rem); line-height: 1.03; letter-spacing: -.04em; }}
    h2 {{ margin: 0; font-size: clamp(1.55rem, 3vw, 2.15rem); line-height: 1.15; }}
    h3 {{ margin: 1.6rem 0 .6rem; font-size: 1rem; }}
    p {{ margin: .45rem 0 1rem; }}
    a {{ color: var(--brand-dark); }}
    .lede {{ max-width: 750px; font-size: 1.18rem; opacity: .92; }}
    .eyebrow {{ margin: 0 0 .35rem; color: inherit; font-size: .76rem; font-weight: 750; letter-spacing: .1em; text-transform: uppercase; }}
    main {{ padding: 0 1.25rem 5rem; }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 1rem;
      margin: -2.2rem 0 2rem;
    }}
    .summary > div, .intro, .case {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 14px;
      box-shadow: 0 10px 30px rgb(26 45 57 / 7%);
    }}
    .summary > div {{ padding: 1.1rem 1.25rem; }}
    .summary strong {{ display: block; font-size: 1.65rem; line-height: 1.1; }}
    .summary span {{ color: var(--muted); font-size: .9rem; }}
    .intro, .case {{ padding: clamp(1.2rem, 4vw, 2.2rem); margin-bottom: 1.25rem; }}
    .intro ol {{ columns: 2; }}
    .case-heading {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; }}
    .case .eyebrow {{ color: var(--brand); }}
    .principle {{ max-width: 820px; color: var(--muted); font-size: 1.05rem; }}
    .explanation-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }}
    .explanation-grid section {{ padding: .2rem 1rem; border-left: 3px solid var(--line); }}
    .badge {{ display: inline-flex; align-items: center; border-radius: 999px; padding: .2rem .58rem; font-size: .78rem; font-weight: 750; white-space: nowrap; }}
    .badge.pass {{ color: var(--pass); background: var(--pass-bg); }}
    .badge.fail {{ color: var(--fail); background: var(--fail-bg); }}
    .table-wrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 9px; }}
    .table-wrap:focus-visible {{ outline: 3px solid var(--brand); outline-offset: 3px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: .91rem; }}
    caption {{
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }}
    th, td {{ padding: .7rem .8rem; border-bottom: 1px solid var(--line); text-align: left; }}
    th {{ color: var(--muted); background: var(--wash); font-size: .76rem; letter-spacing: .04em; text-transform: uppercase; }}
    tbody tr:last-child td {{ border-bottom: 0; }}
    code {{ font-size: .85em; }}
    footer {{ color: var(--muted); text-align: center; padding: 1.5rem; }}
    @media (max-width: 720px) {{
      .summary {{ grid-template-columns: 1fr; }}
      .explanation-grid {{ grid-template-columns: 1fr; }}
      .intro ol {{ columns: 1; }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <p class="eyebrow">Deterministic conformance suite · v{__version__}</p>
      <h1>Health Data Edge Cases</h1>
      <p class="lede">Small synthetic healthcare operations datasets with explicit, testable answers—built to expose reporting logic that looks reasonable and still produces the wrong number.</p>
    </div>
  </header>
  <main>
    <section class="summary" aria-label="Validation summary">
      <div><strong>{escape(status)}</strong><span>Suite status</span></div>
      <div><strong>{result.passed_count}/{len(result.cases)}</strong><span>Cases passing</span></div>
      <div><strong>{result.expectation_count}</strong><span>Assertions checked</span></div>
    </section>
    <section class="intro">
      <h2>What this report proves</h2>
      <p>The committed fixtures, portable reference SQL, and expected results agree. It does not certify a production system or prescribe a universal healthcare standard.</p>
      <ol>{case_links}</ol>
    </section>
    {cases}
  </main>
  <footer>Entirely synthetic data. No patient, employer, or proprietary reporting data is included.</footer>
</body>
</html>
"""

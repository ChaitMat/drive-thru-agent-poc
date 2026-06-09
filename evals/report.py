"""Text report formatter for a batch of eval CaseResults."""

from __future__ import annotations

from evals.runner import CaseResult


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = min(len(sorted_vals) - 1, int(len(sorted_vals) * pct))
    return sorted_vals[idx]


def format_report(results: list[CaseResult]) -> str:
    if not results:
        return "(no results)"

    lines: list[str] = []
    passes = sum(1 for r in results if r.passed)
    total = len(results)
    rate = passes / total * 100
    lines.append(f"\n  ── Eval results ─────────────────────────────────────────")
    lines.append(f"  {passes}/{total} passed ({rate:.0f}%)")

    # Per-category breakdown (spec vs regression vs anything else).
    by_cat: dict[str, list] = {}
    for r in results:
        by_cat.setdefault(r.case.category, []).append(r)
    if len(by_cat) > 1:
        for cat in sorted(by_cat):
            cat_results = by_cat[cat]
            cat_passes = sum(1 for r in cat_results if r.passed)
            lines.append(
                f"    {cat:11s} {cat_passes}/{len(cat_results)} passed"
            )
    lines.append("")

    for r in results:
        status = "✓ PASS" if r.passed else "✗ FAIL"
        avg_lat = sum(r.per_turn_latency_s) / len(r.per_turn_latency_s) if r.per_turn_latency_s else 0
        max_lat = max(r.per_turn_latency_s) if r.per_turn_latency_s else 0
        lines.append(
            f"  {status}  #{r.case.case_id}  {r.case.name}"
            f"  (turns={len(r.per_turn_latency_s)}, avg={avg_lat:.1f}s, max={max_lat:.1f}s)"
        )
        if not r.passed:
            for f in r.failures:
                lines.append(f"           - {f}")
            tc_summary = " → ".join(r.tool_calls) if r.tool_calls else "(none)"
            lines.append(f"           tool calls: {tc_summary}")
            if r.last_reply:
                preview = r.last_reply.replace("\n", " ")[:160]
                lines.append(f"           last reply: {preview!r}")

    all_latencies = [l for r in results for l in r.per_turn_latency_s]
    if all_latencies:
        lines.append("")
        lines.append(
            f"  Latency: p50={_percentile(all_latencies, 0.50):.2f}s  "
            f"p95={_percentile(all_latencies, 0.95):.2f}s  "
            f"max={max(all_latencies):.2f}s"
        )
        lines.append(
            f"  Target:  p95 < 2.00s (per spec §9). "
            f"{'✓ met' if _percentile(all_latencies, 0.95) < 2.0 else '✗ MISSED'}"
        )

    lines.append("")
    return "\n".join(lines)

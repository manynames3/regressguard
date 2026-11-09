from fractions import Fraction


def score(cases):
    return 100 * sum((Fraction(c["passed"], c["total"]) for c in cases), Fraction()) / len(cases)


def compare(cases, baseline, threshold, *, incomplete=False, skipped=False):
    aggregate = score(cases)
    old = {c["id"]: c for c in baseline["cases"]} if baseline else {}
    deltas = []
    for case in cases:
        previous = old.get(case["id"])
        delta = (
            (
                Fraction(case["passed"], case["total"])
                - Fraction(previous["passed"], previous["total"])
            )
            if previous
            else None
        )
        deltas.append(
            {
                "id": case["id"],
                "old": previous and previous["passed"],
                "old_total": previous and previous["total"],
                "new": case["passed"],
                "total": case["total"],
                "delta_points": float(100 * delta) if delta is not None else None,
                "critical_failure": case["severity"] == "critical"
                and case["passed"] < case["total"],
            }
        )
    critical = any(d["critical_failure"] for d in deltas)
    drop = score(baseline["cases"]) - aggregate if baseline else None
    if incomplete:
        verdict, reason = "incomplete", "Execution or coverage error"
    elif critical or (drop is not None and drop > Fraction(str(threshold))):
        verdict, reason = (
            "fail",
            "Critical sample failed" if critical else "Aggregate threshold exceeded",
        )
    elif (
        skipped
        or any(d["delta_points"] is not None and d["delta_points"] < 0 for d in deltas)
        or (not baseline and any(c["passed"] < c["total"] for c in cases))
    ):
        verdict, reason = "warn", "Reduced quality or partial check coverage"
    else:
        verdict, reason = "pass", "All release checks passed"
    return {
        "verdict": verdict,
        "reason": reason,
        "aggregate_score": float(aggregate),
        "aggregate_delta": float(-drop) if drop is not None else None,
        "comparison": "compared" if baseline else "uncompared",
        "deltas": deltas,
        "exit_code": 2 if incomplete else int(verdict == "fail"),
    }

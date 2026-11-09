import html


def markdown(report):
    def esc(text):
        return html.escape(str(text)).replace("|", "&#124;").replace("\n", " ")

    lines = [
        f"## RegressGuard · {esc(report['suite_id'])} · {report['verdict'].upper()}",
        f"Run {report['id']} · Baseline {report.get('baseline_id') or 'none'}",
        report["reason"],
        f"Score {report['aggregate_score']:.2f} · Delta {report['aggregate_delta']} points",
        "Fictional/sample data"
        if report["data_label"] == "fictional_sample"
        else "User-supplied data",
        "",
        "| Case | Before | After | Δ points |",
        "|---|---|---|---|",
    ]
    for d in report["deltas"]:
        lines.append(
            f"| {esc(d['id'])} | {d['old']}/{d['old_total']} | "
            f"{d['new']}/{d['total']} | {d['delta_points']} |"
        )
    lines.extend(
        [
            "",
            "### Prompt/model change",
            f"Before {esc(report.get('baseline_target'))}",
            f"After {esc(report['target'])}",
            "<pre>" + html.escape(report.get("prompt_diff", "")) + "</pre>",
        ]
    )
    for case in report["cases"]:
        for sample in case.get("samples", []):
            failures = [c for c in sample["checks"] if c["status"] in ("fail", "error", "skipped")]
            if failures or sample.get("error"):
                lines.append(
                    f"- {esc(case['id'])} attempt {sample['attempt'] + 1}: "
                    + esc(sample.get("error") or failures)
                )
                if failures:
                    lines.append("<pre>" + html.escape((sample["output"] or "")[:500]) + "</pre>")
                break
    return "\n".join(lines)

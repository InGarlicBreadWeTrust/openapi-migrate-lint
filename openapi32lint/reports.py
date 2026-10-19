"""Reporters: human text, JSON, and SARIF 2.1.0 (for CI / GitHub code scanning).
"""
from __future__ import annotations

import json

from .rules import Finding, SEVERITY_ORDER

_SARIF_SEVERITY = {"error": "error", "high": "error",
                   "medium": "warning", "low": "note", "note": "note"}


# --- exit-code / threshold helpers --------------------------------------- #

def threshold_met(findings, fail_on):
    """True if any finding has severity >= the ``fail_on`` threshold."""
    if not fail_on or not findings:
        return False
    order = {s: i for i, s in enumerate(SEVERITY_ORDER)}
    threshold = order.get(fail_on, order["note"])
    return any(order.get(f.severity, 99) <= threshold for f in findings)


def count_by_severity(findings) -> dict:
    counts = {s: 0 for s in SEVERITY_ORDER}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    return counts


# --- text ---------------------------------------------------------------- #

def text_report(findings, source, threshold=None, quiet_all=False):
    if not quiet_all and not findings:
        return f"[ok] No OpenAPI 3.1->3.2 issues found in {source}."
    order = {s: i for i, s in enumerate(SEVERITY_ORDER)}
    shown = [
        f for f in findings
        if not threshold or order.get(f.severity, 99) <= order.get(threshold, 0)
    ]
    counts = count_by_severity(shown)
    lines = []
    summary = ", ".join(
        f"{counts[s]} {s}" for s in SEVERITY_ORDER if counts.get(s)
    )
    lines.append(f"[{len(shown)} issue(s)] {source}  ({summary})")
    for f in shown:
        if f.suggestion:
            lines.append(
                f"   {f.severity.upper():5} {f.rule}   {f.title}   @ {f.location}\n"
                f"        {f.message}\n"
                f"        fix: {f.suggestion}"
            )
        else:
            lines.append(
                f"   {f.severity.upper():5} {f.rule}   {f.title}   @ {f.location}\n"
                f"        {f.message}"
            )
    if threshold and not shown:
        lines.append(
            f"[ok] No issue at or above '{threshold}' in {source}."
        )
    return "\n".join(lines)


# --- JSON ---------------------------------------------------------------- #

def json_report(findings, source) -> str:
    doc = {
        "tool": "openapi32lint",
        "version": "0.1.0",
        "source": source,
        "counts": count_by_severity(findings),
        "findings": [f.to_dict() for f in findings],
    }
    return json.dumps(doc, indent=2)


# --- SARIF 2.1.0 --------------------------------------------------------- #

def _sarif_rule(f: Finding) -> dict:
    return {
        "id": f.rule,
        "name": f.title,
        "shortDescription": {"text": f.title},
        "helpText": {"text": f.message},
    }


def sarif_report(findings, source) -> str:
    rules = []
    seen = set()
    for f in findings:
        if f.rule not in seen:
            seen.add(f.rule)
            rules.append(_sarif_rule(f))
    results = []
    for f in findings:
        msg = f"{f.title}. {f.message}"
        if f.suggestion:
            msg += f" Suggested fix: {f.suggestion}"
        results.append({
            "ruleId": f.rule,
            "level": _SARIF_SEVERITY.get(f.severity, "warning"),
            "message": {"text": msg},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": source},
                },
            }],
        })
    sarif = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {
                "driver": {
                    "name": "openapi32lint",
                    "version": "0.1.0",
                    "informationUri": "https://github.com/local/openapi32lint",
                    "rules": rules,
                },
            },
            "results": results,
        }],
    }
    return json.dumps(sarif, indent=2)

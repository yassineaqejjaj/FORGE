"""French terminal rendering of the CLI (plain text tables, no external dependency)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

VERDICTS = {
    "better": "meilleure",
    "worse": "moins bonne",
    "equivalent": "équivalente",
    "inconclusive": "non concluant",
}
SEVERITIES = {"critical": "critique", "major": "majeure", "minor": "mineure"}
STATUSES = {
    "draft": "brouillon",
    "queued": "en file",
    "running": "en cours",
    "aggregating": "agrégation",
    "completed": "terminé",
    "failed": "en échec",
    "cancelled": "annulé",
}


def num(value: Any, digits: int = 1, *, signed: bool = False) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "—"
    rounded = round(float(value), digits)
    if rounded == 0:
        rounded = 0.0
    text = f"{abs(rounded):,.{digits}f}".replace(",", " ").replace(".", ",")
    if rounded < 0:
        return f"-{text}"
    return f"+{text}" if signed and rounded > 0 else text


def pct(ratio: Any, digits: int = 0, *, signed: bool = False) -> str:
    return "—" if ratio is None else f"{num(float(ratio) * 100, digits, signed=signed)} %"


def p_value(value: Any) -> str:
    if value is None:
        return "—"
    return "< 0,001" if value < 0.001 else num(value, 3)


def table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    cells = [[str(h) for h in headers], *[[str(c) for c in row] for row in rows]]
    widths = [max(len(row[i]) for row in cells) for i in range(len(headers))]

    def line(row: Sequence[str]) -> str:
        return "  ".join(
            cell.ljust(widths[i]) if i == 0 else cell.rjust(widths[i]) for i, cell in enumerate(row)
        )

    separator = "  ".join("-" * w for w in widths)
    return "\n".join([line(cells[0]), separator, *(line(r) for r in cells[1:])])


def render_comparison(comparison: dict[str, Any], gate: dict[str, Any] | None = None) -> str:
    base = comparison.get("baseline") or {}
    cand = comparison.get("candidate") or {}
    stats = comparison.get("statistics") or {}
    level = num((stats.get("confidence") or 0.95) * 100, 0)
    lines = [
        f"Baseline  : {base.get('agent_label')}  ({base.get('n_scored', 0)} runs évalués)",
        f"Candidate : {cand.get('agent_label')}  ({cand.get('n_scored', 0)} runs évalués)",
        f"Scénarios appariés : {comparison.get('n_pairs', 0)}"
        + (f" (non appariés : {comparison['n_unpaired']})" if comparison.get("n_unpaired") else ""),
        "",
    ]
    metrics = [comparison.get("composite") or {}, *(comparison.get("dimensions") or [])]
    rows = [
        [
            m.get("label", m.get("key")),
            num(m.get("baseline_mean")),
            num(m.get("candidate_mean")),
            num(m.get("delta"), signed=True),
            f"[{num(m.get('ci_low'), signed=True)} ; {num(m.get('ci_high'), signed=True)}]",
            p_value(m.get("p_value")),
            VERDICTS.get(str(m.get("verdict")), str(m.get("verdict"))),
        ]
        for m in metrics
        if m
    ]
    lines.append(
        table(["Dimension", "Baseline", "Candidate", "Δ points", f"IC {level} %", "p", "Verdict"], rows)
    )
    resources = comparison.get("resources") or []
    if resources:
        lines += [
            "",
            table(
                ["Ressource", "Baseline", "Candidate", "Variation"],
                [
                    [
                        r.get("label"),
                        num(r.get("baseline_mean"), 4 if r.get("key") == "cost" else 0),
                        num(r.get("candidate_mean"), 4 if r.get("key") == "cost" else 0),
                        pct(r.get("relative_change"), 0, signed=True),
                    ]
                    for r in resources
                ],
            ),
        ]
    regressions = comparison.get("regressions") or []
    lines.append("")
    if regressions:
        lines.append(f"Régressions ({len(regressions)}) :")
        for reg in regressions:
            reasons = "; ".join(reg.get("reasons") or [])
            lines.append(
                f"  - [{SEVERITIES.get(str(reg.get('severity')), reg.get('severity'))}] {reg.get('name')} : "
                f"{num(reg.get('delta'), signed=True)} points" + (f" — {reasons}" if reasons else "")
            )
    else:
        lines.append("Aucune régression par scénario.")
    improvements = comparison.get("improvements") or []
    if improvements:
        lines.append(f"Améliorations : {len(improvements)} scénario(s).")
    errors = comparison.get("errors") or {}
    if errors.get("appeared"):
        lines.append("Types d'erreurs apparus : " + ", ".join(errors["appeared"]))
    if errors.get("disappeared"):
        lines.append("Types d'erreurs disparus : " + ", ".join(errors["disappeared"]))
    for warning in comparison.get("warnings") or []:
        lines.append(f"Avertissement : {warning}")
    reco = comparison.get("recommendation") or {}
    lines += [
        "",
        f"Recommandation : {reco.get('label', reco.get('recommendation'))} "
        f"(confiance {reco.get('confidence_label', reco.get('confidence'))})",
        str(reco.get("summary", "")),
    ]
    if gate is not None:
        lines += ["", render_gate(gate)]
    return "\n".join(lines)


def render_gate(gate: dict[str, Any]) -> str:
    head = "Garde-fou CI : OK" if gate.get("passed") else "Garde-fou CI : ÉCHEC"
    return "\n".join([head, *(f"  - {r}" for r in gate.get("reasons") or [])])


def render_ranking(summary: dict[str, Any]) -> str:
    ranking = summary.get("ranking") or []
    if not ranking:
        return "Aucun résultat agrégé."
    rows = [
        [
            r.get("rank"),
            r.get("agent_label"),
            num(r.get("group_composite")),
            num(r.get("composite_mean")),
            f"[{num(r.get('ci_low'))} ; {num(r.get('ci_high'))}]",
            pct(r.get("pass_rate")),
            num(r.get("delta_to_leader"), signed=True) if r.get("rank", 1) > 1 else "—",
        ]
        for r in ranking
    ]
    return table(["#", "Version", "Score groupe", "Composite", "IC 95 %", "Réussite", "Écart"], rows)

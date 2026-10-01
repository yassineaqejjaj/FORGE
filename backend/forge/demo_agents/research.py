# ruff: noqa: E501 — demo content: long French sentences are kept on one line for readability.
"""``research-agent`` 1.0 — question answering over the context documents with ``[doc-id]`` citations.

Passages are ranked by keyword overlap with the question; the answer cites every passage it uses.
When no document is relevant the agent says so instead of answering (expected behaviour on
unanswerable questions). Simulated weakness: in about 20 % of the runs it adds one general,
uncited statement that the documents do not support.
"""

from __future__ import annotations

from dataclasses import dataclass

from forge.demo_agents.common import (
    AgentOutput,
    DemoRequest,
    Document,
    EventLog,
    Section,
    fit_sections,
    keywords,
    mask_pii,
    render_sections,
    seeded_rng,
    sentences,
    strip_trailing_punctuation,
    tokens,
    word_count,
    word_limit,
)
from forge.domain.enums import TraceEventType

VERSIONS = ("1.0",)
MODEL = "sim-efficient-2"
MIN_OVERLAP = 2
UNSUPPORTED_CLAIM = (
    "En règle générale, ce type de dispositif est adopté par la grande majorité des organisations du secteur."
)


@dataclass(slots=True)
class Passage:
    text: str
    doc: Document
    score: int


def rank_passages(request: DemoRequest, limit: int = 4) -> list[Passage]:
    question = keywords(request.prompt)
    passages = [
        Passage(sentence, doc, len(keywords(sentence) & question))
        for doc in request.documents
        for sentence in sentences(doc.content)
    ]
    passages = [p for p in passages if p.score > 0]
    passages.sort(key=lambda p: p.score, reverse=True)
    return passages[:limit]


def run(request: DemoRequest, version: str) -> AgentOutput:
    rng = seeded_rng("research-agent", version, request.seed_material)
    log = EventLog()
    passages = rank_passages(request)
    log.add(
        TraceEventType.retrieval,
        "Recherche des passages pertinents",
        rng.uniform(250, 450),
        input={"question": request.prompt},
        output=[{"id": p.doc.id, "extrait": p.text[:120], "score": p.score} for p in passages],
        attributes={
            "documents": sorted({p.doc.id for p in passages}),
            "documents_count": len(request.documents),
        },
    )
    behaviors: list[str] = []
    answerable = bool(passages) and passages[0].score >= MIN_OVERLAP
    log.add(
        TraceEventType.reasoning,
        "Évaluation de la couverture",
        rng.uniform(60, 120),
        output=(
            f"{len(passages)} passage(s) pertinent(s), meilleur recouvrement {passages[0].score if passages else 0}."
            + ("" if answerable else " Les documents ne permettent pas de répondre.")
        ),
    )
    sections = _answer(passages, request) if answerable else _no_answer(request)
    if answerable and rng.random() < 0.2:
        behaviors.append("affirmation non sourcée")
        sections[0].lines.append(UNSUPPORTED_CLAIM)
    sections = fit_sections(sections, word_limit(request))
    text = mask_pii(render_sections(sections))
    log.llm_call(
        "Rédaction de la réponse",
        MODEL,
        tokens(request.prompt) + sum(tokens(p.text) for p in passages) + 250,
        int(word_count(text) * 1.4) + 20,
        rng.uniform(700, 1200),
    )
    sources = sorted({p.doc.id for p in passages}) if answerable else []
    return AgentOutput(
        text=text,
        log=log,
        model=MODEL,
        output_json={"answerable": answerable, "sources": sources},
        behaviors=behaviors,
    )


def _answer(passages: list[Passage], request: DemoRequest) -> list[Section]:
    best = passages[0]
    summary = f"{strip_trailing_punctuation(best.text)} [{best.doc.id}]."
    if len(passages) > 1 and passages[1].doc.id != best.doc.id:
        summary += f" Ce point est complété par : {strip_trailing_punctuation(passages[1].text)} [{passages[1].doc.id}]."
    details = [f"- {strip_trailing_punctuation(p.text)} [{p.doc.id}]." for p in passages]
    cited = {p.doc.id: p.doc for p in passages}
    return [
        Section("## Réponse", [summary], shrinkable=False),
        Section("## Éléments détaillés", details, min_lines=1),
        Section(
            "## Limites",
            ["- La réponse se limite aux documents fournis ; aucune source externe n'a été consultée."],
        ),
        Section("## Sources", [f"- [{d.id}] {d.title}" for d in cited.values()], shrinkable=False),
    ]


def _no_answer(request: DemoRequest) -> list[Section]:
    consulted = [f"- [{d.id}] {d.title}" for d in request.documents] or ["- Aucun document fourni."]
    return [
        Section(
            "## Réponse",
            [
                "Les documents fournis ne permettent pas de répondre à cette question avec certitude. "
                "Je préfère ne pas avancer d'information non sourcée.",
            ],
            shrinkable=False,
        ),
        Section("## Sources consultées", consulted, shrinkable=False),
    ]

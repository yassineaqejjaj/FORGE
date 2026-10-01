# ruff: noqa: E501 — demo content: long French sentences are kept on one line for readability.
"""``product-agent`` — PRD, user stories and discovery syntheses from a brief + context documents.

Versions (simulated, deterministic per scenario version × repetition):

* **1.2** — model ``sim-standard-4``, stuffs every document in the prompt (expensive). Sometimes
  omits the acceptance criteria, cites a document that does not support the claim, copies a
  customer e-mail found in the context (PII leak) and calls an unnecessary ``search.web`` tool.
* **1.3** — model ``sim-efficient-2`` with targeted retrieval + re-ranking: better quality and
  sourcing, cheaper, but slower; ignores word limits on user stories and discovery syntheses
  (regression).
* **1.4** — fixes most issues: limits respected, e-mails masked, correct citations, faster than 1.3;
  occasionally forgets the success metrics section of a PRD.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

from forge.demo_agents.common import (
    EMAIL_RE,
    AgentOutput,
    DemoRequest,
    Document,
    EventLog,
    Section,
    fit_sections,
    fold,
    keywords,
    mask_pii,
    of,
    render_sections,
    seeded_rng,
    sentences,
    strip_trailing_punctuation,
    tokens,
    word_count,
    word_limit,
)
from forge.domain.enums import TraceEventType

VERSIONS = ("1.2", "1.3", "1.4")
TASK_LABELS = {"prd": "PRD", "user_stories": "User stories", "discovery": "Synthèse discovery"}
_SIGNALS = (
    "besoin",
    "probleme",
    "demande",
    "souhait",
    "frustr",
    "bloqu",
    "objectif",
    "perte",
    "temps",
    "clients",
    "utilisateurs",
    "%",
    "manuel",
    "erreur",
    "attente",
    "abandon",
)
_FEATURE_RE = re.compile(
    r"(?:fonctionnalit[ée]|feature|module|parcours)\s+(?:de\s+|d['’]\s*|du\s+|des\s+)?[«\"“]?\s*([^».,;:\n\"”]{3,60})",
    re.IGNORECASE,
)
_PERSONAS = ("gestionnaire", "administrateur", "client", "conseiller", "responsable", "utilisateur", "agent")


@dataclass(slots=True)
class Profile:
    model: str
    base_latency: tuple[float, float]  # ms of the generation call
    retrieval_ms: tuple[float, float]
    stuff_context: bool
    rerank: bool


PROFILES = {
    "1.2": Profile("sim-standard-4", (1100, 1700), (120, 220), stuff_context=True, rerank=False),
    "1.3": Profile("sim-efficient-2", (1900, 2700), (450, 750), stuff_context=False, rerank=True),
    "1.4": Profile("sim-efficient-2", (1000, 1500), (200, 320), stuff_context=False, rerank=False),
}


@dataclass(slots=True)
class Insight:
    text: str
    doc: Document
    score: float


# --- Input analysis ---------------------------------------------------------------------------------------


def detect_task(request: DemoRequest) -> str:
    explicit = str(request.input.get("task") or "").strip().lower()
    if explicit in TASK_LABELS:
        return explicit
    prompt = fold(request.prompt)
    if "user stor" in prompt or "recits utilisateur" in prompt or "histoires utilisateur" in prompt:
        return "user_stories"
    if any(k in prompt for k in ("synthese", "discovery", "entretien", "interview", "verbatim", "retours")):
        return "discovery"
    return "prd"


def detect_feature(request: DemoRequest) -> str:
    explicit = request.input.get("feature") or request.input.get("topic")
    if explicit:
        return str(explicit).strip()
    match = _FEATURE_RE.search(request.prompt)
    if match:
        return strip_trailing_punctuation(match.group(1))
    if request.documents:
        return request.documents[0].title
    return "la fonctionnalité demandée"


def detect_persona(request: DemoRequest) -> str:
    explicit = request.input.get("persona")
    if explicit:
        return str(explicit)
    blob = fold(request.text_blob())
    counts = {p: blob.count(p) for p in _PERSONAS}
    best = max(counts, key=lambda p: counts[p])
    return best if counts[best] else "utilisateur"


def extract_insights(request: DemoRequest, *, limit: int, targeted: bool) -> list[Insight]:
    """Most informative sentences of the documents (signal words + overlap with the brief)."""
    brief = keywords(f"{request.prompt} {request.input.get('feature', '')}")
    per_doc: list[list[Insight]] = []
    for doc in request.documents:
        scored = []
        for sentence in sentences(doc.content):
            folded = fold(sentence)
            score = sum(1.0 for s in _SIGNALS if s in folded) + 1.5 * len(keywords(sentence) & brief)
            if re.search(r"\d", sentence):
                score += 0.5
            if EMAIL_RE.search(sentence):
                score -= 0.5 if targeted else 0.0
            scored.append(Insight(sentence, doc, score))
        scored.sort(key=lambda i: i.score, reverse=True)
        per_doc.append(scored)
    insights: list[Insight] = []
    rank = 0
    while len(insights) < limit and any(rank < len(group) for group in per_doc):
        for group in per_doc:
            if rank < len(group) and len(insights) < limit:
                insights.append(group[rank])
        rank += 1
    if targeted:
        insights = [i for i in insights if i.score > 0] or insights
    return insights


def find_emails(request: DemoRequest) -> list[tuple[str, Document]]:
    found = []
    for doc in request.documents:
        for sentence in sentences(doc.content):
            if EMAIL_RE.search(sentence):
                found.append((sentence, doc))
    return found


# --- Generation -------------------------------------------------------------------------------------------


@dataclass(slots=True)
class Draft:
    request: DemoRequest
    version: str
    rng: random.Random
    task: str
    feature: str
    persona: str
    insights: list[Insight]
    behaviors: list[str]

    def cite(self, insight: Insight, *, allow_wrong: bool = False) -> str:
        doc = insight.doc
        if allow_wrong and len(self.request.documents) > 1:
            doc = next(d for d in self.request.documents if d.id != insight.doc.id)
            self.behaviors.append(f"citation non étayée [{doc.id}]")
        text = insight.text if self.version == "1.2" else mask_pii(insight.text)
        return f"{strip_trailing_punctuation(text)} [{doc.id}]."


def run(request: DemoRequest, version: str) -> AgentOutput:
    profile = PROFILES[version]
    rng = seeded_rng("product-agent", version, request.seed_material)
    log = EventLog()
    task = detect_task(request)
    limit = word_limit(request)
    draft = Draft(
        request=request,
        version=version,
        rng=rng,
        task=task,
        feature=detect_feature(request),
        persona=detect_persona(request),
        insights=[],
        behaviors=[],
    )
    log.add(
        TraceEventType.reasoning,
        "Analyse de la demande",
        rng.uniform(60, 140),
        output=(
            f"Tâche détectée : {TASK_LABELS[task]} pour « {draft.feature} » (persona : {draft.persona}). "
            f"{len(request.documents)} document(s) de contexte"
            + (f", limite de {limit} mots." if limit else ", pas de limite de longueur explicite.")
        ),
    )
    draft.insights = _retrieve(draft, profile, log)
    _tools(draft, log)
    sections = _build(draft)
    sections = _apply_length_policy(draft, sections, limit)
    text = render_sections(sections)
    if version == "1.2" and EMAIL_RE.search(text) and "fuite d'e-mail client" not in draft.behaviors:
        draft.behaviors.append("fuite d'e-mail client")
    prompt_tokens = (
        tokens(request.prompt)
        + 350
        + (
            sum(tokens(d.content) for d in request.documents)
            if profile.stuff_context
            else sum(tokens(i.text) for i in draft.insights) + 120
        )
    )
    log.llm_call(
        f"Génération — {TASK_LABELS[task]}",
        profile.model,
        prompt_tokens,
        int(word_count(text) * 1.45) + 40,
        rng.uniform(*profile.base_latency),
    )
    return AgentOutput(
        text=text,
        log=log,
        model=profile.model,
        output_json={
            "task": task,
            "feature": draft.feature,
            "word_count": word_count(text),
            "sources": sorted({i.doc.id for i in draft.insights}),
        },
        behaviors=draft.behaviors,
    )


def _retrieve(draft: Draft, profile: Profile, log: EventLog) -> list[Insight]:
    request = draft.request
    targeted = not profile.stuff_context
    insights = extract_insights(request, limit=6 if targeted else 5, targeted=targeted)
    docs = sorted({i.doc.id for i in insights}) if targeted else [d.id for d in request.documents]
    log.add(
        TraceEventType.retrieval,
        "Recherche dans les documents de contexte" if targeted else "Chargement de tout le contexte",
        draft.rng.uniform(*profile.retrieval_ms),
        input={"query": draft.feature},
        output=[{"id": i.doc.id, "extrait": i.text[:120], "score": round(i.score, 2)} for i in insights],
        attributes={
            "documents": docs,
            "documents_count": len(docs),
            "strategy": "targeted" if targeted else "all",
        },
    )
    if profile.rerank:
        log.add(
            TraceEventType.reasoning,
            "Re-classement des passages",
            draft.rng.uniform(500, 800),
            output=f"{len(insights)} passages conservés après re-classement par pertinence.",
        )
    return insights


def _tools(draft: Draft, log: EventLog) -> None:
    rng = draft.rng
    if draft.version == "1.2" and rng.random() < 0.5:
        draft.behaviors.append("outil inutile search.web")
        log.tool(
            "search.web",
            {"query": f"{draft.feature} bonnes pratiques"},
            {
                "results": [
                    {
                        "title": "Article généraliste sans lien avec le contexte",
                        "url": "https://example.org/blog",
                    }
                ]
            },
            rng.uniform(300, 600),
        )
    if draft.task == "user_stories" and draft.version in ("1.3", "1.4"):
        key = "".join(w[0] for w in draft.feature.split()[:3]).upper() or "PRD"
        log.tool(
            "jira.search",
            {"query": draft.feature, "project": "PROD"},
            {
                "issues": [
                    {
                        "key": f"PROD-{100 + rng.randint(1, 80)}",
                        "summary": f"{draft.feature} — demande initiale ({key})",
                        "status": "Backlog",
                    }
                ]
            },
            rng.uniform(250, 450),
        )


def _build(draft: Draft) -> list[Section]:
    builders = {"prd": _prd, "user_stories": _user_stories, "discovery": _discovery}
    sections = builders[draft.task](draft)
    sources = sorted({i.doc.id: i.doc for i in draft.insights}.values(), key=lambda d: d.id)
    if sources:
        sections.append(Section("## Sources", [f"- [{d.id}] {d.title}" for d in sources], shrinkable=False))
    return sections


def _claims(draft: Draft, count: int) -> list[str]:
    """Context claims with citations; 1.2 sometimes cites the wrong document."""
    lines = []
    wrong_index = 1 if draft.version == "1.2" and draft.rng.random() < 0.4 else -1
    for index, insight in enumerate(draft.insights[:count]):
        lines.append(f"- {draft.cite(insight, allow_wrong=index == wrong_index)}")
    return lines or [
        "- Aucun document de contexte n'a été fourni : hypothèses à confirmer avec les utilisateurs."
    ]


def _pii_line(draft: Draft) -> list[str]:
    emails = find_emails(draft.request)
    if not emails:
        return []
    sentence, doc = emails[0]
    if draft.version == "1.2" and draft.rng.random() < 0.35:
        draft.behaviors.append("fuite d'e-mail client")
        return [f"- Verbatim : « {sentence} » [{doc.id}]"]
    if draft.version == "1.4":
        return [f"- Verbatim : « {mask_pii(sentence)} » [{doc.id}]"]
    return []


def _prd(draft: Draft) -> list[Section]:
    rng, feature, persona = draft.rng, draft.feature, draft.persona
    sections = [
        Section("", [f"# PRD — {feature}"], shrinkable=False),
        Section("## Contexte et problème", _claims(draft, 3) + _pii_line(draft), min_lines=2),
        Section(
            "## Objectifs",
            [
                f"- Permettre au {persona} d'utiliser « {feature} » en autonomie, sans passer par le support.",
                f"- Réduire le temps de traitement lié à « {feature} » d'au moins {rng.choice([20, 25, 30])} %.",
                "- Diminuer les erreurs de saisie et les demandes répétitives.",
            ],
        ),
        Section(
            "## Périmètre",
            [
                f"**Inclus :** parcours principal {of(feature)}, notifications, journal des actions.",
                "**Exclus :** migration des données historiques, application mobile (phase 2).",
            ],
            shrinkable=False,
        ),
        Section(
            "## Exigences fonctionnelles",
            [
                f"1. Le {persona} peut lancer « {feature} » depuis l'écran principal en moins de trois clics.",
                "2. Le système confirme chaque action et affiche un état d'avancement.",
                "3. Les droits d'accès existants sont respectés (aucune donnée hors périmètre).",
                "4. Chaque opération est tracée (date, auteur, résultat) et consultable.",
                "5. Les erreurs sont expliquées avec une action corrective proposée.",
            ],
            min_lines=3,
        ),
    ]
    if not (draft.version == "1.2" and rng.random() < 0.45):
        sections.append(
            Section(
                "## Critères d'acceptation",
                [
                    f"- Étant donné un {persona} authentifié, quand il lance « {feature} », alors le résultat "
                    "est disponible en moins de 5 secondes.",
                    "- Étant donné une erreur de validation, quand l'utilisateur valide, alors un message explicite "
                    "indique le champ à corriger.",
                    "- Étant donné un utilisateur sans droit, quand il accède à la fonctionnalité, alors l'accès est refusé.",
                ],
                min_lines=2,
            )
        )
    else:
        draft.behaviors.append("critères d'acceptation omis")
    if not (draft.version == "1.4" and rng.random() < 0.15):
        sections.append(
            Section(
                "## Indicateurs de succès",
                [
                    f"- Taux d'adoption {of(feature)} à 3 mois.",
                    "- Nombre de tickets support associés (objectif : baisse continue).",
                    "- Satisfaction utilisateur mesurée après usage.",
                ],
            )
        )
    else:
        draft.behaviors.append("indicateurs de succès omis")
    sections.append(
        Section(
            "## Risques et questions ouvertes",
            [
                rng.choice(
                    [
                        "- Volumétrie réelle à confirmer avec l'équipe technique.",
                        "- Performances sur les gros volumes à valider avec l'équipe technique.",
                    ]
                ),
                rng.choice(
                    [
                        "- Dépendances avec les intégrations existantes à valider.",
                        "- Impacts sur les intégrations existantes à analyser avant le lancement.",
                    ]
                ),
            ],
        )
    )
    return sections


def _user_stories(draft: Draft) -> list[Section]:
    rng, feature, persona = draft.rng, draft.feature, draft.persona
    omit_criteria = draft.version == "1.2" and rng.random() < 0.45
    if omit_criteria:
        draft.behaviors.append("critères d'acceptation omis")
    benefits = ["gagner du temps", "éviter les erreurs de saisie", "suivre l'avancement", "être autonome"]
    actions = [
        f"lancer « {feature} » en quelques clics",
        "être averti lorsque le traitement est terminé",
        "consulter l'historique des opérations",
        "corriger facilement une erreur signalée",
    ]
    count = 4 if draft.version != "1.3" else 6
    if draft.version == "1.3":
        actions += ["partager le résultat avec mon équipe", "paramétrer mes préférences par défaut"]
        benefits += ["collaborer plus efficacement", "adapter l'outil à mon usage"]
    stories = []
    for index in range(count):
        stories.append(f"### US-{index + 1}")
        stories.append(f"En tant que {persona}, je veux {actions[index]} afin de {benefits[index]}.")
        if not omit_criteria:
            stories.append("**Critères d'acceptation :**")
            stories.append(
                f"- Étant donné un {persona} connecté, quand il {actions[index].split(' ', 1)[0]} "
                f"la fonction, alors le résultat attendu s'affiche."
            )
            stories.append("- Les erreurs sont signalées avec un message compréhensible.")
            if draft.version == "1.3":
                stories.append("- Le comportement est identique sur tous les navigateurs supportés.")
    sections = [
        Section("", [f"# User stories — {feature}"], shrinkable=False),
        Section("## Contexte", _claims(draft, 2) + _pii_line(draft), min_lines=1),
        Section("## User stories", stories, min_lines=6),
        Section("## Hors périmètre", ["- Application mobile et migration des données historiques."]),
    ]
    if draft.version == "1.3":
        sections.append(
            Section(
                "## Détails complémentaires",
                [
                    "- Les stories ont été comparées aux tickets Jira existants pour éviter les doublons.",
                    "- Une estimation en points pourra être réalisée lors du prochain affinage.",
                    "- Les dépendances techniques seront revues avec l'architecte de l'équipe.",
                ],
            )
        )
    return sections


def _discovery(draft: Draft) -> list[Section]:
    feature = draft.feature
    verbatims = _pii_line(draft)
    if not verbatims and draft.insights:
        quote = draft.insights[-1]
        verbatims = [f"- « {mask_pii(strip_trailing_punctuation(quote.text))} » [{quote.doc.id}]"]
    sections = [
        Section("", [f"# Synthèse discovery — {feature}"], shrinkable=False),
        Section("## Constats clés", _claims(draft, 4), min_lines=2),
        Section("## Verbatims", verbatims or ["- Aucun verbatim exploitable dans le contexte."]),
        Section(
            "## Opportunités",
            [
                f"- Simplifier le parcours {of(feature)} pour les cas les plus fréquents.",
                "- Automatiser les étapes répétitives signalées dans les retours.",
                "- Mieux informer l'utilisateur de l'état de sa demande.",
            ],
        ),
        Section(
            "## Hypothèses à valider",
            [
                "- Les irritants observés concernent la majorité des utilisateurs actifs.",
                "- Une amélioration du parcours réduirait les contacts au support.",
            ],
        ),
        Section(
            "## Prochaines étapes",
            [
                "- Valider les hypothèses avec 5 entretiens complémentaires.",
                "- Prototyper le parcours simplifié et le tester.",
            ],
        ),
    ]
    if draft.version == "1.3":
        sections.insert(
            3,
            Section(
                "## Analyse détaillée",
                [
                    f"- Les retours convergent sur la complexité perçue {of(feature)}.",
                    "- Plusieurs documents mentionnent des contournements manuels coûteux.",
                    "- Les attentes portent autant sur la rapidité que sur la transparence du traitement.",
                    "- Les profils les plus expérimentés expriment un besoin de raccourcis.",
                ],
            ),
        )
    return sections


def _apply_length_policy(draft: Draft, sections: list[Section], limit: int | None) -> list[Section]:
    if not limit:
        return sections
    if draft.version == "1.3" and draft.task in ("user_stories", "discovery"):
        if word_count(render_sections(sections)) > limit:
            draft.behaviors.append("limite de mots dépassée")
        return sections
    return fit_sections(sections, limit)

"""Cohérence du README racine avec le Makefile, docker-compose.yml, .env.example et le code.

Tests purement statiques (aucune base de données) : ils lisent les fichiers du dépôt.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import forge

ROOT = Path(__file__).resolve().parents[3]
README = ROOT / "README.md"
MAKEFILE = ROOT / "Makefile"
COMPOSE = ROOT / "docker-compose.yml"
ENV_EXAMPLE = ROOT / ".env.example"
PACKAGE_DIR = Path(forge.__file__).resolve().parent

DOCS = [
    "AGENT_PROTOCOL",
    "ARCHITECTURE",
    "CI",
    "DEMO",
    "DEMO_AGENTS",
    "DEPLOYMENT",
    "OBSERVED_RUNS",
    "OPERATIONS",
]


def _read(path: Path) -> str:
    if not path.exists():
        pytest.skip(f"{path.name} introuvable (dépôt partiel)")
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def readme() -> str:
    return _read(README)


@pytest.fixture(scope="module")
def makefile() -> str:
    return _read(MAKEFILE)


@pytest.fixture(scope="module")
def compose() -> str:
    return _read(COMPOSE)


@pytest.fixture(scope="module")
def env_example() -> str:
    return _read(ENV_EXAMPLE)


@pytest.fixture(scope="module")
def code_text() -> str:
    parts = []
    for path in PACKAGE_DIR.rglob("*.py"):
        parts.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)


def _section(readme: str, title: str) -> str:
    match = re.search(rf"^## {re.escape(title)}\s*$(.*?)(?=^## |\Z)", readme, re.S | re.M)
    assert match, f"section « {title} » absente du README"
    return match.group(1)


def _mermaid(readme: str) -> str:
    match = re.search(r"```mermaid\n(.*?)```", readme, re.S)
    assert match, "diagramme Mermaid absent"
    return match.group(1)


def _compose_services(compose: str) -> set[str]:
    return set(re.findall(r"^  ([a-zA-Z0-9_-]+):\s*$", compose, re.M))


# --- Critère 1 : démarrage rapide ------------------------------------------------------------


def test_quickstart_commands_match_makefile_and_env(readme, makefile, env_example):
    section = _section(readme, "Démarrage rapide")
    block = re.search(r"```bash\n(.*?)```", section, re.S)
    assert block, "bloc bash du démarrage rapide absent"
    commands = [line.split("#")[0].strip() for line in block.group(1).splitlines()]
    commands = [c for c in commands if c]

    assert "cp .env.example .env" in commands
    assert ENV_EXAMPLE.exists()
    for expected in ("make up", "make seed"):
        assert expected in commands

    for command in commands:
        if command.startswith("make "):
            target = command.split()[1]
            assert re.search(rf"^{re.escape(target)}\s*:", makefile, re.M), f"cible {target} absente"

    for variable in ("FORGE_OPENAI_API_KEY", "FORGE_ANTHROPIC_API_KEY"):
        assert variable in readme
        assert variable in env_example, f"{variable} absente de .env.example"


def test_every_make_target_in_readme_exists(readme, makefile):
    targets = set(re.findall(r"\bmake ([a-z][a-z0-9_-]*)", readme))
    assert {"up", "seed"} <= targets
    for target in targets:
        assert re.search(rf"^{re.escape(target)}\s*:", makefile, re.M), f"cible {target} absente"


# --- Critère 2 : ports, URL et identifiants ---------------------------------------------------


def test_ports_match_compose(readme, compose, env_example):
    config = compose + "\n" + env_example
    for port in ("3100", "8100", "8190", "5434", "6381"):
        assert port in readme
        assert port in config, f"port {port} absent de docker-compose.yml / .env.example"


def test_readme_services_exist_in_compose(readme, compose):
    services = _compose_services(compose)
    table_services = set(re.findall(r"^\| `([a-z0-9-]+)` \|", readme, re.M))
    assert {"web", "api", "runner-worker", "evaluation-worker", "postgres", "valkey"} <= table_services
    assert table_services <= services, f"services inconnus : {table_services - services}"


def test_urls_match_backend(readme, code_text):
    assert "/api/v1/docs" in readme
    assert "/api/v1" in code_text
    assert "POST http://localhost:8100/v1/traces" in readme
    assert "/v1/traces" in code_text


def test_demo_admin_matches_seed_or_config(readme, code_text, compose, env_example):
    sources = code_text + "\n" + compose + "\n" + env_example
    assert "`admin@forge.local` / `forge-admin`" in readme
    assert "admin@forge.local" in sources
    assert "forge-admin" in sources


# --- Critère 3 : liens relatifs ---------------------------------------------------------------


def test_relative_links_point_to_existing_files(readme):
    links = re.findall(r"\]\(([^)\s]+)\)", readme)
    relative = [link for link in links if not re.match(r"^(https?:|mailto:|#)", link)]
    assert relative, "aucun lien relatif trouvé"
    for link in relative:
        target = link.split("#")[0]
        assert (ROOT / target).exists(), f"lien cassé : {link}"


# --- Critère 4 : documentation ----------------------------------------------------------------


@pytest.mark.parametrize("doc", DOCS)
def test_documentation_section_links_each_doc(readme, doc):
    section = _section(readme, "Documentation")
    assert f"(docs/{doc}.md)" in section
    assert (ROOT / "docs" / f"{doc}.md").exists()


# --- Critère 5 : fonctionnalités --------------------------------------------------------------


def test_features_cover_observed_runs_and_exist_in_code(readme, code_text):
    features = _section(readme, "Ce que fait FORGE")
    assert "Runs observés" in features
    assert "/api/v1/runs/observed" in features
    assert "external_id" in features
    assert "/observed" in code_text
    assert "external_id" in code_text
    assert "CLI `forge`" in features
    assert (PACKAGE_DIR / "cli.py").exists() or (PACKAGE_DIR / "cli").is_dir()


# --- Critère 6 : diagramme Mermaid ------------------------------------------------------------


def test_mermaid_is_well_formed(readme):
    diagram = _mermaid(readme)
    assert diagram.lstrip().startswith("flowchart")
    assert diagram.count('"') % 2 == 0
    assert diagram.count("[") == diagram.count("]")
    assert diagram.count("(") == diagram.count(")")
    subgraphs = len(re.findall(r"^\s*subgraph\b", diagram, re.M))
    ends = len(re.findall(r"^\s*end\s*$", diagram, re.M))
    assert subgraphs == ends


def test_mermaid_edges_use_defined_nodes(readme):
    diagram = _mermaid(readme)
    defined = set(re.findall(r"^\s*(\w+)\s*[\[\(\{]", diagram, re.M))
    used: set[str] = set()
    for line in diagram.splitlines()[1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("subgraph") or stripped == "end":
            continue
        if re.match(r"^\w+\s*[\[\(\{]", stripped):
            continue
        cleaned = re.sub(r"\|[^|]*\|", " ", stripped)
        cleaned = re.sub(r"-\.[^>]*->|-->|&", " ", cleaned)
        used.update(re.findall(r"\w+", cleaned))
    assert used, "aucune arête dans le diagramme"
    assert used <= defined, f"nœuds non définis : {used - defined}"


def test_mermaid_matches_compose_services(readme, compose):
    diagram = _mermaid(readme)
    services = _compose_services(compose)
    for service in ("api", "runner-worker", "evaluation-worker", "demo-agents"):
        assert service in diagram
        assert service in services
    assert "PostgreSQL" in diagram
    assert "Valkey" in diagram
    assert {"postgres", "valkey"} <= services


# --- Critère 7 : langue et structure ----------------------------------------------------------


def test_readme_title_structure_and_language(readme):
    assert readme.startswith("# FORGE — Laboratoire d'évaluation des agents IA")
    headings = re.findall(r"^## (.+)$", readme, re.M)
    for expected in (
        "Ce que fait FORGE",
        "Démarrage rapide",
        "Architecture",
        "Documentation",
        "Stack",
        "Sécurité",
        "Développement",
    ):
        assert expected in headings
    for word in (" le ", " les ", " des ", " de ", " et "):
        assert word in readme


# --- Critère 8 : aucun secret -----------------------------------------------------------------


@pytest.mark.parametrize(
    "pattern",
    [
        r"sk-[A-Za-z0-9_-]{16,}",
        r"sk-ant-[A-Za-z0-9_-]{8,}",
        r"fgk_[A-Za-z0-9]{8,}",
        r"gh[pousr]_[A-Za-z0-9]{20,}",
        r"AKIA[0-9A-Z]{16}",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    ],
)
def test_readme_contains_no_secret(readme, pattern):
    assert re.search(pattern, readme) is None


def test_readme_api_key_variables_have_no_value(readme):
    for match in re.finditer(r"FORGE_(?:OPENAI|ANTHROPIC)_API_KEY\s*=\s*(\S+)", readme):
        assert match.group(1) in {"", '""', "''"}

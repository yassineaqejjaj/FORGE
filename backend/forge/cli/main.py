"""``forge`` command line (CI integration): launch benchmarks and experiments, block on regressions.

Configuration: ``FORGE_URL`` (default ``http://localhost:8100``) and ``FORGE_API_KEY`` (service key
``fgk_…``, role ``editor`` to launch, ``viewer`` to read). Only the public REST API is used.

Exit codes: ``0`` success / gate passed, ``1`` gate failed (``--fail-on-regression``,
``experiment gate``), ``2`` error (HTTP, timeout, failed or cancelled execution, bad arguments).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Sequence
from typing import Any, TextIO

from forge.cli.client import CliError, ForgeClient
from forge.cli.output import STATUSES, num, render_comparison, render_gate, render_ranking, table

EXIT_OK = 0
EXIT_GATE_FAILED = 1
EXIT_ERROR = 2
TERMINAL = {"completed", "failed", "cancelled"}
DEFAULT_TIMEOUT = 3600.0
DEFAULT_POLL = 5.0

#: Indirection so tests can replace waiting (``monkeypatch.setattr(main, "sleep", ...)``).
sleep: Callable[[float], None] = time.sleep
monotonic: Callable[[], float] = time.monotonic


class Context:
    def __init__(self, client: ForgeClient, out: TextIO, err: TextIO, as_json: bool) -> None:
        self.client = client
        self.out = out
        self.err = err
        self.as_json = as_json

    def print(self, text: str = "") -> None:
        print(text, file=self.out)

    def info(self, text: str) -> None:
        """Progress messages go to stderr so that ``--json`` output stays parseable."""
        print(text, file=self.err)

    def dump(self, data: Any) -> None:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str), file=self.out)


# =====================================================================================================
# Commands
# =====================================================================================================


def cmd_whoami(ctx: Context, args: argparse.Namespace) -> int:
    me = ctx.client.get("/auth/me")
    if ctx.as_json:
        ctx.dump(me)
        return EXIT_OK
    if not isinstance(me, dict):
        raise CliError("Réponse inattendue de /auth/me")
    data: dict[str, Any] = me["user"] if isinstance(me.get("user"), dict) else me
    label = data.get("full_name") or data.get("label") or data.get("name") or data.get("email") or "?"
    ctx.print(f"Connecté en tant que : {label}")
    for key, title in (
        ("email", "E-mail"),
        ("kind", "Type"),
        ("role", "Rôle"),
        ("clearance", "Habilitation"),
    ):
        value = data.get(key, me.get(key))
        if value is not None:
            ctx.print(f"{title} : {f'C{value}' if key == 'clearance' else value}")
    ctx.print(f"Instance : {ctx.client.base_url}")
    return EXIT_OK


def _items(page: Any) -> list[dict[str, Any]]:
    if isinstance(page, dict):
        return list(page.get("items") or [])
    return list(page or [])


def cmd_agents_list(ctx: Context, args: argparse.Namespace) -> int:
    items = _items(ctx.client.get("/agents", page_size=args.limit))
    if ctx.as_json:
        ctx.dump(items)
        return EXIT_OK
    if not items:
        ctx.print("Aucun agent.")
        return EXIT_OK
    rows = []
    for agent in items:
        latest = agent.get("latest_version") or {}
        version = latest.get("version") if isinstance(latest, dict) else latest
        rows.append(
            [
                agent.get("slug", ""),
                agent.get("name", ""),
                version or "—",
                agent.get("versions_count", "—"),
                agent.get("id", ""),
            ]
        )
    ctx.print(table(["Slug", "Nom", "Dernière version", "Versions", "Identifiant"], rows))
    return EXIT_OK


def cmd_benchmarks_list(ctx: Context, args: argparse.Namespace) -> int:
    items = _items(ctx.client.get("/benchmarks", page_size=args.limit))
    if ctx.as_json:
        ctx.dump(items)
        return EXIT_OK
    if not items:
        ctx.print("Aucun benchmark.")
        return EXIT_OK
    rows = []
    for b in items:
        last = b.get("last_execution") or {}
        rows.append(
            [
                b.get("slug"),
                b.get("name"),
                b.get("n_scenarios"),
                b.get("n_agents"),
                b.get("repetitions"),
                f"n° {last['number']} ({STATUSES.get(str(last.get('status')), last.get('status'))})"
                if last
                else "—",
            ]
        )
    ctx.print(table(["Slug", "Nom", "Scénarios", "Versions", "Répétitions", "Dernière exécution"], rows))
    return EXIT_OK


def _wait(ctx: Context, path: str, *, timeout: float, poll: float, what: str) -> dict[str, Any]:
    deadline = monotonic() + timeout
    last_progress: tuple[Any, ...] | None = None
    while True:
        data = ctx.client.get(path)
        status = data.get("status")
        progress = (status, data.get("completed_runs"), data.get("failed_runs"))
        if progress != last_progress:
            done = (data.get("completed_runs") or 0) + (data.get("failed_runs") or 0)
            ctx.info(
                f"{what} : {STATUSES.get(status, status)} — "
                f"{done}/{data.get('total_runs', '?')} runs terminés"
            )
            last_progress = progress
        if status in TERMINAL:
            return data  # type: ignore[no-any-return]
        if monotonic() >= deadline:
            raise CliError(
                f"Délai d'attente dépassé ({timeout:.0f} s) : "
                f"{what.lower()} toujours {STATUSES.get(status, status)}"
            )
        sleep(poll)


def cmd_benchmark_run(ctx: Context, args: argparse.Namespace) -> int:
    execution = ctx.client.post(f"/benchmarks/{args.benchmark}/run", json={"trigger": args.trigger})
    ctx.info(
        f"Exécution n° {execution['number']} lancée ({execution['total_runs']} runs) — "
        f"identifiant {execution['id']}"
    )
    if not args.wait:
        if ctx.as_json:
            ctx.dump(execution)
        return EXIT_OK
    final = _wait(
        ctx,
        f"/benchmark-executions/{execution['id']}",
        timeout=args.timeout,
        poll=args.poll_interval,
        what="Exécution",
    )
    if ctx.as_json:
        ctx.dump(final)
    else:
        ctx.print(
            f"Benchmark {final.get('benchmark_name') or args.benchmark} — exécution n° {final['number']}"
        )
        ctx.print(render_ranking(final.get("summary") or {}))
    if final["status"] != "completed":
        ctx.info(
            f"Exécution {STATUSES.get(final['status'], final['status'])} : {final.get('error') or ''}".strip()
        )
        return EXIT_ERROR
    return EXIT_OK


def cmd_experiment_run(ctx: Context, args: argparse.Namespace) -> int:
    if not args.benchmark and not args.scenario:
        raise CliError("Indiquez --benchmark ou au moins un --scenario")
    body: dict[str, Any] = {
        "baseline_version_id": args.baseline,
        "candidate_version_id": args.candidate,
        "trigger": args.trigger,
    }
    if args.benchmark:
        body["benchmark_id"] = args.benchmark
    if args.scenario:
        body["scenario_ids"] = args.scenario
    for key, value in (
        ("repetitions", args.repetitions),
        ("evaluation_config_id", args.config),
        ("name", args.name),
    ):
        if value is not None:
            body[key] = value
    experiment = ctx.client.post("/experiments", json=body)
    ctx.info(
        f"Expérience « {experiment['name']} » lancée ({experiment['total_runs']} runs) — "
        f"identifiant {experiment['id']}"
    )
    for warning in experiment.get("warnings") or []:
        ctx.info(f"Avertissement : {warning}")
    wait = args.wait or args.fail_on_regression
    if not wait:
        if ctx.as_json:
            ctx.dump(experiment)
        return EXIT_OK
    final = _wait(
        ctx,
        f"/experiments/{experiment['id']}",
        timeout=args.timeout,
        poll=args.poll_interval,
        what="Expérience",
    )
    comparison = ctx.client.get(f"/experiments/{experiment['id']}/comparison")
    gate = ctx.client.get(f"/experiments/{experiment['id']}/gate", strict=str(args.strict).lower())
    if ctx.as_json:
        ctx.dump({"experiment": final, "comparison": comparison, "gate": gate})
    else:
        ctx.print(render_comparison(comparison, gate))
    if final["status"] != "completed":
        ctx.info(
            f"Expérience {STATUSES.get(final['status'], final['status'])} : "
            f"{final.get('error') or ''}".strip()
        )
        return EXIT_ERROR
    if args.fail_on_regression and not gate.get("passed"):
        return EXIT_GATE_FAILED
    return EXIT_OK


def cmd_experiment_gate(ctx: Context, args: argparse.Namespace) -> int:
    gate = ctx.client.get(f"/experiments/{args.experiment}/gate", strict=str(args.strict).lower())
    if ctx.as_json:
        ctx.dump(gate)
    else:
        delta = gate.get("composite_delta")
        if delta is not None:
            ctx.print(
                f"Δ composite : {num(delta, signed=True)} points — {gate.get('regressions', 0)} régression(s)"
            )
        ctx.print(render_gate(gate))
    return EXIT_OK if gate.get("passed") else EXIT_GATE_FAILED


# =====================================================================================================
# Parser
# =====================================================================================================


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="sortie JSON (machine)")


def _waiting(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--wait", action="store_true", help="attendre la fin et afficher les résultats")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="attente maximale en secondes")
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL, help="intervalle de suivi (s)")
    parser.add_argument("--trigger", default="ci", help="origine du lancement (défaut : ci)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forge",
        description="FORGE — évaluation des agents IA en CI (FORGE_URL, FORGE_API_KEY).",
    )
    parser.add_argument("--url", help="URL de FORGE (défaut : $FORGE_URL ou http://localhost:8100)")
    sub = parser.add_subparsers(dest="command", required=True)

    whoami = sub.add_parser("whoami", help="identité de la clé utilisée")
    _common(whoami)
    whoami.set_defaults(handler=cmd_whoami)

    agents = sub.add_parser("agents", help="agents").add_subparsers(dest="action", required=True)
    agents_list = agents.add_parser("list", help="lister les agents")
    agents_list.add_argument("--limit", type=int, default=100)
    _common(agents_list)
    agents_list.set_defaults(handler=cmd_agents_list)

    benchmarks = sub.add_parser("benchmarks", help="benchmarks").add_subparsers(dest="action", required=True)
    benchmarks_list = benchmarks.add_parser("list", help="lister les benchmarks")
    benchmarks_list.add_argument("--limit", type=int, default=100)
    _common(benchmarks_list)
    benchmarks_list.set_defaults(handler=cmd_benchmarks_list)

    benchmark = sub.add_parser("benchmark", help="benchmark").add_subparsers(dest="action", required=True)
    run = benchmark.add_parser("run", help="lancer une exécution de benchmark")
    run.add_argument("benchmark", help="identifiant ou slug du benchmark")
    _waiting(run)
    _common(run)
    run.set_defaults(handler=cmd_benchmark_run)

    experiment = sub.add_parser("experiment", help="expériences").add_subparsers(dest="action", required=True)
    exp_run = experiment.add_parser("run", help="lancer une expérience baseline / candidate")
    exp_run.add_argument("--baseline", required=True, help="identifiant de la version baseline")
    exp_run.add_argument("--candidate", required=True, help="identifiant de la version candidate")
    source = exp_run.add_mutually_exclusive_group()
    source.add_argument("--benchmark", help="benchmark source (identifiant ou slug)")
    source.add_argument("--scenario", action="append", help="scénario (répétable)")
    exp_run.add_argument(
        "--repetitions", type=int, help="répétitions K (défaut : celles du benchmark, sinon 1)"
    )
    exp_run.add_argument("--config", help="identifiant de la configuration d'évaluation")
    exp_run.add_argument("--name", help="nom de l'expérience")
    exp_run.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="code de sortie 1 si le garde-fou CI échoue (implique --wait)",
    )
    exp_run.add_argument(
        "--strict", action="store_true", help="seule la recommandation « ship » passe le garde-fou"
    )
    _waiting(exp_run)
    _common(exp_run)
    exp_run.set_defaults(handler=cmd_experiment_run)

    gate = experiment.add_parser("gate", help="garde-fou CI d'une expérience")
    gate.add_argument("experiment", help="identifiant de l'expérience")
    gate.add_argument("--strict", action="store_true")
    _common(gate)
    gate.set_defaults(handler=cmd_experiment_gate)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    client: ForgeClient | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:  # argparse error or --help
        return EXIT_OK if exc.code in (0, None) else EXIT_ERROR
    owned = client is None
    forge = client or ForgeClient(base_url=args.url)
    ctx = Context(forge, out, err, getattr(args, "json", False))
    try:
        return int(args.handler(ctx, args))
    except CliError as exc:
        print(f"Erreur : {exc}", file=err)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("Interrompu.", file=err)
        return EXIT_ERROR
    finally:
        if owned:
            forge.close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

"""``python -m forge.seed`` — load the Nordalis demo data set through the real services.

Examples::

    docker compose exec -T api python -m forge.seed               # make seed
    docker compose exec -T api python -m forge.seed --reset --yes # make reseed (wipe business data first)
    python -m forge.seed --scale small --sync                     # small data set, jobs processed in-process
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from forge.config import settings
from forge.infra import cache
from forge.infra.db import dispose_engine
from forge.seed.reset import ResetRefused
from forge.seed.runner import SeedOptions, run_seed
from forge.seed.summary import render
from forge.seed.waiting import SeedTimeout


def parse_args(argv: list[str] | None = None) -> SeedOptions:
    parser = argparse.ArgumentParser(
        prog="python -m forge.seed",
        description="Charge le jeu de démonstration Nordalis (agents, scénarios, benchmarks, expériences, "
        "évaluations humaines) via les services FORGE et l'exécute dans le pipeline réel.",
    )
    parser.add_argument(
        "--reset", action="store_true", help="efface les données métier avant de charger la démo"
    )
    parser.add_argument("--yes", action="store_true", help="confirme --reset lorsque FORGE_ENV=production")
    parser.add_argument(
        "--scale", choices=("small", "full"), default="full", help="taille du jeu (défaut : full)"
    )
    parser.add_argument(
        "--sync", action="store_true", help="traite les jobs dans ce processus (sans les workers)"
    )
    parser.add_argument("--no-wait", action="store_true", help="lance les benchmarks sans attendre leur fin")
    parser.add_argument(
        "--demo-agents-url",
        default=None,
        help=f"URL de base des agents de démonstration (défaut : {settings.demo_agents_url})",
    )
    parser.add_argument("--latency-scale", type=float, default=None, help="facteur de latence simulée (0–10)")
    parser.add_argument("--timeout", type=float, default=1800.0, help="délai maximal par phase d'attente (s)")
    parser.add_argument(
        "--credentials-file", type=Path, default=None, help="fichier des identifiants de démo"
    )
    parser.add_argument("--quiet", action="store_true", help="n'affiche que le résumé")
    args = parser.parse_args(argv)
    return SeedOptions(
        reset=args.reset,
        yes=args.yes,
        scale=args.scale,
        sync=args.sync,
        wait=not args.no_wait,
        demo_agents_url=args.demo_agents_url,
        latency_scale=args.latency_scale,
        timeout=args.timeout,
        credentials_path=args.credentials_file,
        quiet=args.quiet,
    )


async def _main(options: SeedOptions) -> int:
    try:
        report = await run_seed(options)
        print(await render(report), flush=True)
        return 0
    except ResetRefused as exc:
        print(f"Refusé : {exc}", file=sys.stderr)
        return 2
    except SeedTimeout as exc:
        print(f"Délai dépassé : {exc}", file=sys.stderr)
        return 3
    finally:
        await cache.close_valkey()
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    return asyncio.run(_main(parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())

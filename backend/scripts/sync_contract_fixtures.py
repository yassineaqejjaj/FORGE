"""Copy (or verify) the contract fixtures FORGE receives from ORBIT and NOVA (NOV-74, docs/CONTRACTS.md).

    uv run python scripts/sync_contract_fixtures.py --orbit ../../ORBIT/contracts/orbit
    uv run python scripts/sync_contract_fixtures.py --fap-response ../../NOVA/contracts/fap_response
    uv run python scripts/sync_contract_fixtures.py --claims ../../NOVA          # ORION claims contract (NOV-104)
    uv run python scripts/sync_contract_fixtures.py --orbit <dir> --check   # compare only, exit 1 on drift

A copy is the source directory byte for byte (fixtures + ``manifest.json``). ``verify_copy`` checks that every
file of a copy still matches the sha256 its manifest records; ``tests/contract`` runs it, so a hand-edited or
half-refreshed copy fails the suite. ``--check`` additionally compares with a source checkout.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
#: option name -> directory holding the copy
COPIES = {
    "orbit": BACKEND / "tests" / "fixtures" / "orbit",
    "fap-response": BACKEND / "tests" / "fixtures" / "fap_response",
}
#: ORION claims contract (NOV-104): fixtures + the standard-library validation module, copied from NOVA.
CLAIMS_COPY = BACKEND / "tests" / "fixtures" / "claims"
CLAIMS_MODULE = BACKEND / "forge" / "domain" / "orion_claims.py"
NOVA_CLAIMS_DIR = Path("contracts") / "claims"
NOVA_CLAIMS_MODULE = Path("nova") / "domain" / "orion_claims.py"
MANIFEST = "manifest.json"
KEEP = {"README.md"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_copy(directory: Path) -> list[str]:
    """Problems of a fixture directory against its own manifest (empty list = consistent)."""
    manifest_path = directory / MANIFEST
    if not manifest_path.is_file():
        return [f"{directory}: {MANIFEST} is missing"]
    files = json.loads(manifest_path.read_text(encoding="utf-8"))["files"]
    problems = []
    present = {p.name for p in directory.glob("*.json")} - {MANIFEST}
    for name in sorted(set(files) | present):
        if name not in present:
            problems.append(f"{name}: listed in the manifest but missing")
        elif name not in files:
            problems.append(f"{name}: present but not in the manifest")
        elif digest(directory / name) != files[name]["sha256"]:
            problems.append(
                f"{name}: differs from the manifest hash (edited, or copied from another version)"
            )
    return problems


def verify_claims(directory: Path = CLAIMS_COPY, module: Path = CLAIMS_MODULE) -> list[str]:
    """Problems of the claims copy: fixtures against the manifest, and the module against ``module.sha256``."""
    problems = verify_copy(directory)
    manifest_path = directory / MANIFEST
    if manifest_path.is_file():
        pinned = json.loads(manifest_path.read_text(encoding="utf-8"))["module"]["sha256"]
        if not module.is_file():
            problems.append(f"{module}: missing")
        elif digest(module) != pinned:
            problems.append(
                f"{module.name}: differs from the manifest hash (edited, or copied from another version)"
            )
    return problems


def differences(source: Path, copy: Path) -> list[str]:
    """Files whose bytes differ between a source directory and its copy."""
    names = {p.name for p in source.glob("*.json")} | {p.name for p in copy.glob("*.json")}
    return sorted(
        n
        for n in names
        if not (source / n).is_file() or not (copy / n).is_file() or digest(source / n) != digest(copy / n)
    )


def main(argv: list[str]) -> int:
    check = "--check" in argv
    status = 0
    if "--claims" in argv:
        nova = Path(argv[argv.index("--claims") + 1]).resolve()
        source, source_module = nova / NOVA_CLAIMS_DIR, nova / NOVA_CLAIMS_MODULE
        if not (source / MANIFEST).is_file() or not source_module.is_file():
            print(f"{nova}: no {NOVA_CLAIMS_DIR / MANIFEST} / {NOVA_CLAIMS_MODULE}: not a NOVA checkout")
            return 2
        if check:
            drift = differences(source, CLAIMS_COPY)
            if not CLAIMS_MODULE.is_file() or digest(source_module) != digest(CLAIMS_MODULE):
                drift.append(CLAIMS_MODULE.name)
            if drift:
                print(f"the claims copy drifts from {nova}: {', '.join(drift)}")
                status = 1
        else:
            CLAIMS_COPY.mkdir(parents=True, exist_ok=True)
            for stale in (p for p in CLAIMS_COPY.iterdir() if p.is_file() and p.name not in KEEP):
                stale.unlink()
            for path in source.glob("*.json"):
                shutil.copyfile(path, CLAIMS_COPY / path.name)
            shutil.copyfile(source_module, CLAIMS_MODULE)
            problems = verify_claims()
            if problems:
                print("\n".join(problems))
                return 1
            print(f"claims contract refreshed from {nova}")
    for name, copy in COPIES.items():
        option = f"--{name}"
        if option not in argv:
            continue
        source = Path(argv[argv.index(option) + 1]).resolve()
        if not (source / MANIFEST).is_file():
            print(f"{source}: no {MANIFEST}: not a contract directory")
            return 2
        if check:
            drift = differences(source, copy)
            if drift:
                print(f"{copy.relative_to(BACKEND)} drifts from {source}: {', '.join(drift)}")
                status = 1
            continue
        copy.mkdir(parents=True, exist_ok=True)
        for stale in (p for p in copy.iterdir() if p.is_file() and p.name not in KEEP):
            stale.unlink()
        for path in source.glob("*.json"):
            shutil.copyfile(path, copy / path.name)
        problems = verify_copy(copy)
        if problems:
            print("\n".join(problems))
            return 1
        print(f"{copy.relative_to(BACKEND)} refreshed from {source}")
    return status


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

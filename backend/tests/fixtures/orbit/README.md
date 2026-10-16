Copy of ORBIT `contracts/orbit/` (NOV-74), byte for byte, `manifest.json` included: the real `ContextPackage` and
`Snapshot` schemas serialised (`model_dump(mode="json")`) with synthetic content only. They pin the wire format
FORGE reads. Never edit them by hand: `tests/contract` checks every file against the hash in the manifest.

Refresh after an ORBIT contract change (see docs/CONTRACTS.md):

    uv run python scripts/sync_contract_fixtures.py --orbit <ORBIT checkout>/contracts/orbit
    uv run python scripts/generate_fap_fixtures.py        # the bodies FORGE sends to NOVA derive from these files

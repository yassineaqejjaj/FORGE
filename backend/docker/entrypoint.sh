#!/bin/sh
# FORGE backend entrypoint.
#   api     wait for Postgres, run migrations, start uvicorn (REST + MCP + /metrics)
#   worker       wait for Postgres, start a worker (queues from FORGE_WORKER_QUEUES)
#   demo-agents  start the demo agents service (FORGE Agent Protocol)
#   migrate wait for Postgres, run migrations and exit
#   *            exec the given command (e.g. "python -m forge.seed")
set -eu

wait_for_postgres() {
  python - <<'PY'
import asyncio, os, sys, time

import asyncpg

url = os.environ.get("FORGE_DATABASE_URL", "postgresql+asyncpg://forge:forge@postgres:5432/forge")
dsn = url.replace("postgresql+asyncpg://", "postgresql://", 1)
deadline = time.monotonic() + float(os.environ.get("FORGE_DB_WAIT_SECONDS", "90"))


async def main() -> int:
    attempt = 0
    while True:
        attempt += 1
        try:
            conn = await asyncpg.connect(dsn, timeout=5)
            await conn.execute("SELECT 1")
            await conn.close()
            print(f"[entrypoint] postgres ready (attempt {attempt})", flush=True)
            return 0
        except Exception as exc:  # noqa: BLE001
            if time.monotonic() > deadline:
                print(f"[entrypoint] postgres unavailable: {exc}", file=sys.stderr, flush=True)
                return 1
            await asyncio.sleep(min(5, attempt))


sys.exit(asyncio.run(main()))
PY
}

run_migrations() {
  echo "[entrypoint] alembic upgrade head"
  alembic upgrade head
}

# Role: first argument, else FORGE_ROLE (PaaS services sharing one image), else api.
command="${1:-${FORGE_ROLE:-api}}"
# Bind address: "::" on platforms whose private network is IPv6 (Railway).
bind_host="${FORGE_BIND_HOST:-0.0.0.0}"
case "$command" in
  api)
    if [ "$#" -gt 0 ]; then shift; fi
    wait_for_postgres
    run_migrations
    exec uvicorn forge.api.main:app \
      --host "$bind_host" \
      --port "${FORGE_API_PORT:-${PORT:-8000}}" \
      --proxy-headers \
      --forwarded-allow-ips "${FORGE_FORWARDED_ALLOW_IPS:-*}" \
      --timeout-graceful-shutdown 20 \
      "$@"
    ;;
  worker)
    if [ "$#" -gt 0 ]; then shift; fi
    wait_for_postgres
    exec python -m forge.workers "$@"
    ;;
  demo-agents)
    if [ "$#" -gt 0 ]; then shift; fi
    exec uvicorn forge.demo_agents.app:app --host "$bind_host" --port "${FORGE_DEMO_AGENTS_PORT:-${PORT:-8190}}" "$@"
    ;;
  migrate)
    wait_for_postgres
    run_migrations
    ;;
  *)
    if [ "$#" -eq 0 ]; then
      echo "[entrypoint] unknown FORGE_ROLE '$command' (api | worker | demo-agents | migrate)" >&2
      exit 64
    fi
    exec "$@"
    ;;
esac

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

command="${1:-api}"
case "$command" in
  api)
    shift || true
    wait_for_postgres
    run_migrations
    exec uvicorn forge.api.main:app \
      --host 0.0.0.0 \
      --port "${FORGE_API_PORT:-8000}" \
      --proxy-headers \
      --forwarded-allow-ips "${FORGE_FORWARDED_ALLOW_IPS:-*}" \
      --timeout-graceful-shutdown 20 \
      "$@"
    ;;
  worker)
    shift || true
    wait_for_postgres
    exec python -m forge.workers "$@"
    ;;
  demo-agents)
    shift || true
    exec uvicorn forge.demo_agents.app:app --host 0.0.0.0 --port "${FORGE_DEMO_AGENTS_PORT:-8190}" "$@"
    ;;
  migrate)
    wait_for_postgres
    run_migrations
    ;;
  *)
    exec "$@"
    ;;
esac

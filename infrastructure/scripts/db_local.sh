#!/usr/bin/env bash
# Apply all migrations to a disposable local PostgreSQL that emulates Supabase, then run SQL tests.
# Usage: PGURL=postgresql://postgres@localhost:5432/growth_test infrastructure/scripts/db_local.sh [--tests]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PGURL="${PGURL:?set PGURL}"
psql "$PGURL" -v ON_ERROR_STOP=1 -q -f "$ROOT/database/tests/00_supabase_stub.sql"
for f in "$ROOT"/database/migrations/*.sql; do
  echo "→ $(basename "$f")"
  PGOPTIONS="-c client_min_messages=warning" psql "$PGURL" -v ON_ERROR_STOP=1 -q -f "$f" >/dev/null
done
if [[ "${1:-}" == "--tests" ]]; then
  for f in "$ROOT"/database/tests/[1-9]*.sql; do
    echo "▶ $(basename "$f")"
    psql "$PGURL" -v ON_ERROR_STOP=1 -q -f "$f"
  done
fi

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Database Setup

Migrations are applied manually — never run automatically. Apply in order via Supabase SQL Editor:

```
db/migrations/001_schema.sql
db/migrations/002_unit_movings.sql
db/migrations/003_unit_occupancy_global.sql
```

Migration runner at startup is **read-only** (verifies tables exist, does not apply changes).

## Secrets Configuration

Create `.streamlit/secrets.toml` (git-ignored):

```toml
DATABASE_HOST = "..."
DATABASE_PASSWORD = "..."
DATABASE_USER = "postgres"
DATABASE_NAME = "postgres"
DATABASE_SSLMODE = "require"

APP_USERNAME = "..."
APP_PASSWORD = "..."
VALIDATOR_USERNAME = "..."
VALIDATOR_PASSWORD = "..."
# AUTH_DISABLED = "true"  # skip login for local dev
```

Streamlit secrets take precedence over environment variables by design — prevents shell `export` from overriding deployed config.

## Architecture

Five strict layers. Cross-layer calls are only allowed downward:

```
UI (ui/)              → Streamlit pages and auth
Services (services/)  → Business logic, file parsing, report building
Domain (domain/)      → Pure functions only — no I/O, no DB calls
Repositories (db/repository/) → Raw parameterized SQL, RealDictCursor
Database (db/)        → Thread-local psycopg2 (safe for Streamlit workers)
```

### Key Design Rules

- **No ORM** — raw parameterized SQL throughout; keeps Supabase/pgBouncer compatibility
- **Thread-local DB connection** — `db/connection.py` uses `threading.local()` because Streamlit spawns multiple worker threads
- **Supabase Transaction Pooler** — connect on port `6543` (PgBouncer), not `5432`
- **All data is property-scoped** — `property_id` is always a scope key; same unit code can exist in different properties
- **Transactions for multi-write operations** — use `with transaction():` to wrap related inserts/upserts

### Domain Layer (`domain/unit_identity.py`)

Pure functions for unit code handling — safe to unit-test with no mocking:
- `normalize_unit_code(raw)` → strips whitespace, removes "Unit " prefix, uppercases
- `parse_unit_parts(unit_code)` → extracts `{phase_code, building_code, unit_number}`
- `compose_identity_key(property_id, unit_norm)` → deduplication key

### Occupancy Ingestion Pattern

`occupancy_service.ingest()` accepts normalized `[{unit_number, move_in_date}]` records. Parsers (e.g., `parsers/resident_activity_parser.py`) transform source formats into this shape. Adding a new data source = add a parser; no service or repository changes needed.

### Work Order Classification Logic (`services/work_order_validator_service.py`)

- `days_since_move_in = created_date - move_in_date`
- `-7 ≤ days ≤ 15` → **Make Ready**
- Outside range, check location string:
  - Matches unit pattern → **Service Technician**
  - Fitness/Clubhouse/Game Room/Dining → **Service Tech – Amenities**
  - Pool/Grounds/Exterior → **Service Tech – Common Area**
  - Else → **Service Technician**

### Report Building (`services/report_operations/active_sr_report.py`)

Declarative pipeline using `FilterParams`, `SheetDef`, `ReportConfig` dataclasses. No hardcoded sheet logic — all layout is data-driven. File is 904 lines; if modifying, be aware it could be split into a filter engine + layout engine.

### Authentication (`ui/auth.py`)

Three access modes based on secrets:
- `"full"` — APP_USERNAME + APP_PASSWORD
- `"validator_only"` — VALIDATOR_USERNAME + VALIDATOR_PASSWORD
- `AUTH_DISABLED = "true"` — skip login entirely (local dev)

## Files to Watch

`services/report_operations/active_sr_report.py` is 904 lines — changes here carry high blast radius. Read it fully before modifying.

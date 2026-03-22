# Work Order Validator

A Streamlit-powered tool for property management teams that **classifies active service requests** into actionable categories (Make Ready vs. Service Technician) and generates **manager-ready Excel reports** — all scoped per property.

Built to replace manual spreadsheet triage with a repeatable, data-driven workflow.

---

## What It Does

| Workflow | Description |
|----------|-------------|
| **Upload move-in data** | Import OneSite Resident Activity exports (`.xls` / `.xlsx`) to establish current occupancy per unit. |
| **Import unit master** | Load a CSV of unit codes with optional phase, building, floor plan, and square footage metadata. |
| **Classify work orders** | Upload an Active Service Request export — each row is automatically labeled based on move-in proximity and location. |
| **Download reports** | Generate split Excel workbooks (East / West) with per-phase breakdowns, unassigned queues, and per-tech sheets. |

### Classification Rules

| Condition | Label |
|-----------|-------|
| Move-in within **-7 to +15 days** of WO creation | **Make Ready** |
| Unit-level location, outside window | **Service Technician** |
| Fitness / Clubhouse / Game Room / Dining | **Service Tech – Amenities** |
| Pool / Grounds / Exterior | **Service Tech – Common Area** |

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| UI | [Streamlit](https://streamlit.io/) `>=1.35` |
| Database | PostgreSQL on [Supabase](https://supabase.com/) via Transaction Pooler (port `6543`) |
| Driver | `psycopg2` with `RealDictCursor`, thread-local connections |
| Data | `pandas`, `openpyxl`, `xlrd` |

No ORM — raw parameterized SQL throughout for Supabase/PgBouncer compatibility.

---

## Architecture

Five strict layers; cross-layer calls are only allowed downward.

```
UI  (ui/)                → Streamlit pages, auth, file uploaders
Services  (services/)    → Business logic, parsers, report builders
Domain  (domain/)        → Pure functions (no I/O, no DB)
Repository  (db/repository/)  → Parameterized SQL queries
Database  (db/)          → Thread-local psycopg2 connections
```

```
wo_standalone/
├── app.py                        # Entrypoint
├── config/settings.py            # Secrets & env resolution
├── db/
│   ├── connection.py             # Thread-local connections + transaction()
│   ├── migration_runner.py       # Read-only schema check at startup
│   ├── migrations/               # 001–004, applied manually
│   └── repository/               # property, unit, occupancy, movings, users
├── domain/
│   └── unit_identity.py          # normalize, parse, compose identity key
├── services/
│   ├── auth_service.py           # Supabase Auth (GoTrue) wrapper
│   ├── occupancy_service.py
│   ├── property_service.py
│   ├── unit_service.py
│   ├── work_order_validator_service.py
│   ├── work_order_excel.py
│   ├── parsers/
│   │   └── resident_activity_parser.py
│   └── report_operations/
│       └── active_sr_report.py   # East/West ASR workbook builder
└── ui/
    ├── auth.py                   # Supabase Auth login + first-run bootstrap
    ├── import_movings_page.py
    └── screens/
        ├── admin_page.py         # User management (admin-only)
        └── work_order_validator.py
```

---

## Getting Started

### Prerequisites

- Python 3.10+
- A PostgreSQL database (Supabase recommended)

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure secrets

Copy the example and fill in your values:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

```toml
# Option A — Split keys (recommended)
DATABASE_HOST     = "aws-0-us-west-2.pooler.supabase.com"
DATABASE_USER     = "postgres.your-project-ref"
DATABASE_PASSWORD = "your-database-password"
DATABASE_PORT     = "6543"
DATABASE_NAME     = "postgres"
DATABASE_SSLMODE  = "require"

# Option B — Full URI
# DATABASE_URL = "postgresql://postgres.ref:password@host:6543/postgres?pgbouncer=true"

# Supabase Auth (Settings → API in Supabase Dashboard)
SUPABASE_URL             = "https://your-project-ref.supabase.co"
SUPABASE_ANON_KEY        = "eyJ..."
SUPABASE_SERVICE_ROLE_KEY = "eyJ..."

# AUTH_DISABLED    = "true"   # skip login for local dev
```

> Streamlit secrets take precedence over environment variables by design.

### 3. Apply database migrations

Run these **manually** in the Supabase SQL Editor (or any Postgres client), in order:

```
db/migrations/001_schema.sql
db/migrations/002_unit_movings.sql
db/migrations/003_unit_occupancy_global.sql
db/migrations/004_users.sql
```

The app verifies tables exist at startup but never applies migrations automatically.

### 4. Run the app

```bash
streamlit run app.py
```

---

## Deployment

Designed for **Streamlit Community Cloud** + **Supabase**:

1. Push to GitHub.
2. In Streamlit Cloud, set the main file path to `app.py`.
3. Add secrets via the Streamlit Cloud dashboard (same keys as `secrets.toml`).
4. Connect to Supabase using the **Transaction Pooler** endpoint (port `6543`).

---

## Authentication

Powered by **Supabase Auth** (GoTrue). Passwords are managed by Supabase — no credentials stored in the app database.

| Scenario | What happens |
|----------|--------------|
| **First run** (no users in DB) | "Create First Admin" form appears — no prior login needed |
| **Admin user** (`is_admin = true`) | Full access to all properties + Admin page (user management) |
| **Regular user** | Sees only properties assigned via `user_properties` |
| **`AUTH_DISABLED = "true"`** | Skip login entirely (local dev) |

Admins can create users, assign property access, and deactivate accounts from the **Admin** page in the sidebar.

---

## Database Schema

Eight tables across four migrations:

| Table | Purpose |
|-------|---------|
| `property` | Top-level scope — all data is property-scoped |
| `phase` | Subdivision of a property (e.g., Phase 3, Phase 5) |
| `building` | Building within a phase |
| `unit` | Normalized unit with identity key, floor plan, sq ft |
| `unit_occupancy_global` | Current move-in date per unit — drives classification |
| `unit_movings` | Historical move-in log |
| `users` | App-level profile keyed by Supabase Auth UUID |
| `user_properties` | Maps users to the properties they can access |

---

## License

Private repository. All rights reserved.

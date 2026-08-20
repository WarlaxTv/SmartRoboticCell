# Smart Robotic Cell - Multi-Cell Supervision Platform

Welcome to the project. This application was built from scratch to address new industrial requirements:

- **Multi-cell supervision** via OPC UA.
- **Safety & reliability** (Read-Only) to prevent accidents caused by unintended remote control.
- **Strict compliance with NF EN 9100** (Aeronautics & Defence Quality).
- **SSL/TLS encryption** for all server communications.

## Prerequisites & installation

### Prerequisites

- Python 3.12+
- Windows PowerShell (for `scripts/run_servers.ps1` / `scripts/run_quality.ps1`)

### Installation (portable)

Run at the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Security & certificates (SSL/TLS)

The project uses self-signed certificates for:

- **OPC UA (OT)**: encrypted exchanges with *Sign & Encrypt* policy.
- **Web (IT)**: dashboard access via **HTTPS**.

Generate certificates (stored in `certs/`):

```powershell
python scripts/generate_certs.py
```

## Project structure

- `src_v2/` : source code (FastAPI web server, OPC UA client/server, JWT/RBAC security, SQLite persistence).
- `src_v2/templates/` : HTML pages (main view, cell detail, history pages, data comparison).
- `src_v2/static/` : shared front-end assets (theme, navigation, popups, locally vendored Chart.js).
- `scripts/` : one-off PowerShell/Python scripts (certificate generation, one-click demo/quality run, historical demo data, load testing) — see sections below.
- `certs/` : X.509 certificates and private keys generated locally.
- `tests/` : unit tests (Pytest) to validate business logic and security.
- `docs_v2/` : technical documentation, compliance and traceability logs.

## Available pages

Once logged in, navigation happens through the dropdown menu at the top of every page:

- `/` — Main view (all 3 cells).
- `/cell/{id}` — Cell detail (MAINTENANCE role): diagnostics, fault and maintenance history, per-axis charts.
- `/historique-maintenance` — Maintenance intervention history, all cells (MAINTENANCE role).
- `/historique-pannes` — Fault history, all cells, filterable by cell (MAINTENANCE role).
- `/donnees` — 3-cell comparison (MAINTENANCE role).

## Running the application

### PowerShell scripts (demo & quality)

```powershell
# Start both servers (OPC UA + Web) + generate certs if needed
./scripts/run_servers.ps1

# Run quality checks (tests, coverage, lint, format)
./scripts/run_quality.ps1
```

Then open the dashboard:

- https://127.0.0.1:8082

Accept the self-signed certificate if your browser displays a security warning.

### Manual launch (if needed)

In two separate terminals:

```powershell
# OPC UA server (simulator)
python -m src_v2.opcua_server
```

```powershell
# FastAPI web server (HTTPS)
python -m uvicorn src_v2.web_server:app --host 0.0.0.0 --port 8082 `
  --ssl-keyfile certs/web_key.pem `
  --ssl-certfile certs/web_cert.pem
```

## Quality (PEP8, tests, security)

Useful commands (run at the project root):

```powershell
# Unit tests
python -m pytest

# Coverage (OT server opcua_server.py excluded — infinite loop)
python -m pytest --cov=src_v2 --cov-report=term-missing

# PEP8 lint / quality
python -m ruff check .

# Formatting
python -m black --check .
python -m black .

# Static analysis PyLint (project config)
python -m pylint src_v2 --rcfile .\.pylintrc --score=y
```

## Load testing (Locust)

```powershell
python -m pip install locust
locust -f scripts/locustfile.py --host=https://127.0.0.1:8082
```

Then open http://localhost:8089 to drive the simulation (user count, ramp-up).

## Demo accounts

| Username   | Password  | Role        |
|------------|-----------|-------------|
| jean_ope   | ope123    | OPERATOR    |
| luc_maint  | maint123  | MAINTENANCE |

## Demo data (optional)

To seed the database with a realistic history (3 weeks of measures and faults) before a demo:

```powershell
$env:SRC_DB_PATH = "smart_robotic_cell.db"
python scripts/seed_historical_data.py
```

The script is idempotent and non-destructive: run again against an already-populated database (from the server's background task or a previous run), it never duplicates or deletes any real data.

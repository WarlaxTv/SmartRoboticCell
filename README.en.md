# Smart Robotic Cell - Multi-Cell Supervision Platform

Welcome to the project. This application was built from scratch to address new industrial requirements:

- **Multi-cell supervision** via OPC UA.
- **Safety & reliability** (Read-Only) to prevent accidents caused by unintended remote control.
- **Strict compliance with NF EN 9100** (Aeronautics & Defence Quality).
- **SSL/TLS encryption** for all server communications.

## Prerequisites & installation

### Prerequisites

- Python 3.12+
- Windows PowerShell (for `run_servers.ps1` / `run_quality.ps1`)

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
python generate_certs.py
```

## Project structure

- `src_v2/` : source code (FastAPI web server, OPC UA client, JWT/RBAC security).
- `certs/` : X.509 certificates and private keys generated locally.
- `tests/` : unit tests (Pytest) to validate business logic and security.
- `docs_v2/` : technical documentation, compliance and traceability logs.

## Running the application

### PowerShell scripts (demo & quality)

```powershell
# Start both servers (OPC UA + Web) + generate certs if needed
./run_servers.ps1

# Run quality checks (tests, coverage, lint, format)
./run_quality.ps1
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

## Demo accounts

| Username   | Password  | Role        |
|------------|-----------|-------------|
| jean_ope   | ope123    | OPERATOR    |
| luc_maint  | maint123  | MAINTENANCE |

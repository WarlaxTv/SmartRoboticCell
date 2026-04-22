$ErrorActionPreference = "Stop"

Write-Host "[SRC] Running unit tests..." -ForegroundColor Cyan
python -m pytest

Write-Host "[SRC] Running coverage (IT modules only; OT opcua_server omitted)..." -ForegroundColor Cyan
python -m pytest --cov=src_v2 --cov-report=term-missing

Write-Host "[SRC] Running Ruff (lint)..." -ForegroundColor Cyan
python -m ruff check .

Write-Host "[SRC] Running Black (format check)..." -ForegroundColor Cyan
python -m black --check .

Write-Host "[SRC] OK" -ForegroundColor Green

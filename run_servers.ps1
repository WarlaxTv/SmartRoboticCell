$ErrorActionPreference = "Stop"

Write-Host "[SRC] Generating certificates (if needed)..." -ForegroundColor Cyan
python generate_certs.py

Write-Host "[SRC] Starting OPC UA server..." -ForegroundColor Cyan
Start-Process -NoNewWindow -WorkingDirectory $PSScriptRoot -FilePath python -ArgumentList "-m", "src_v2.opcua_server"

Write-Host "[SRC] Starting Web server (HTTPS)..." -ForegroundColor Cyan
Start-Process -NoNewWindow -WorkingDirectory $PSScriptRoot -FilePath python -ArgumentList @(
    "-m",
    "uvicorn",
    "src_v2.web_server:app",
    "--host",
    "0.0.0.0",
    "--port",
    "8082",
    "--ssl-keyfile",
    "certs/web_key.pem",
    "--ssl-certfile",
    "certs/web_cert.pem"
)

Write-Host "[SRC] Open: https://127.0.0.1:8082" -ForegroundColor Green

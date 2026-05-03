# Starts Neo4j (Docker), FastAPI (:8000), and Next.js (:3000).
# Prereqs: backend/.env with GEMINI_API_KEY; backend deps; frontend npm install.
# Neo4j is required when ENABLE_GRAPHITI=true; optional for RAG-only (false).

param(
    [switch]$SkipDocker
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$ComposeFile = Join-Path $Root "docker-compose.yml"

if (-not (Test-Path $Backend)) { throw "Missing folder: $Backend" }
if (-not (Test-Path $Frontend)) { throw "Missing folder: $Frontend" }

if (-not $SkipDocker -and (Test-Path $ComposeFile)) {
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        Write-Host "docker compose up -d (Neo4j)..." -ForegroundColor Cyan
        Push-Location $Root
        try {
            docker compose up -d
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "docker compose failed (exit $LASTEXITCODE). If you use Graphiti, fix Docker and retry. Continuing to start app servers."
            }
        } finally {
            Pop-Location
        }
    } else {
        Write-Warning "Docker not found in PATH; skipped Neo4j. Install Docker Desktop or use -SkipDocker. Graphiti needs Neo4j on localhost:7687."
    }
} elseif ($SkipDocker) {
    Write-Host "Skipping Docker Compose (-SkipDocker)." -ForegroundColor DarkGray
}

$shell = if (Get-Command pwsh -ErrorAction SilentlyContinue) { "pwsh" } else { "powershell" }

$backendCmd = "if (Test-Path '.venv\Scripts\python.exe') { & .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000 } elseif (Get-Command uv -ErrorAction SilentlyContinue) { uv run uvicorn app.main:app --reload --port 8000 } else { python -m uvicorn app.main:app --reload --port 8000 }"

Write-Host "Opening two windows: backend :8000, frontend :3000" -ForegroundColor Cyan
Start-Process $shell -WorkingDirectory $Backend -ArgumentList @("-NoExit", "-Command", $backendCmd)
Start-Process $shell -WorkingDirectory $Frontend -ArgumentList @("-NoExit", "-Command", "npm run dev")
Write-Host "Close those windows to stop the servers. App: http://localhost:3000" -ForegroundColor Green

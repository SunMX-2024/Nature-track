param(
    [int]$Port = 8000
)

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Virtual environment Python not found at $Python"
}

Push-Location $ProjectRoot
try {
    & $Python -m uvicorn api.main:app --reload --host 127.0.0.1 --port $Port
} finally {
    Pop-Location
}

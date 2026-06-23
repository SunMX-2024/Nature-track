param(
    [int]$Port = 8501,
    [string]$Address = "localhost"
)

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$RepoRoot = Split-Path -Parent $ProjectRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
}
$App = Join-Path $ProjectRoot "app.py"
$OutLog = Join-Path $ProjectRoot "streamlit.service.out.log"
$ErrLog = Join-Path $ProjectRoot "streamlit.service.err.log"

if (-not (Test-Path $Python)) {
    throw "Virtual environment Python not found at $Python"
}

if (-not (Test-Path $App)) {
    throw "Streamlit app not found at $App"
}

$Existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($Existing) {
    Write-Host "Streamlit is already listening on port $Port."
    exit 0
}

$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = "false"

$Arguments = @(
    "-m",
    "streamlit",
    "run",
    "app.py",
    "--server.port",
    "$Port",
    "--server.address",
    "$Address",
    "--server.headless",
    "true",
    "--browser.gatherUsageStats",
    "false"
)

Start-Process `
    -FilePath $Python `
    -ArgumentList $Arguments `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $OutLog `
    -RedirectStandardError $ErrLog `
    -WindowStyle Hidden

Start-Sleep -Seconds 5

$Started = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $Started) {
    throw "Streamlit did not start on port $Port. Check $ErrLog and $OutLog."
}

Write-Host "Streamlit started at http://$Address`:$Port/"

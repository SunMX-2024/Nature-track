param(
    [int]$Port = 5173
)

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$WebRoot = Join-Path $ProjectRoot "web"

if (-not (Test-Path $WebRoot)) {
    throw "Web app not found at $WebRoot"
}

Push-Location $WebRoot
try {
    npm run dev -- --host 127.0.0.1 --port $Port
} finally {
    Pop-Location
}

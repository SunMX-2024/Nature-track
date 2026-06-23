param(
    [int]$IntervalSeconds = 60
)

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$StartScript = Join-Path $ProjectRoot "scripts\start_streamlit_app.ps1"
$WatchLog = Join-Path $ProjectRoot "streamlit.watch.log"

if (-not (Test-Path $StartScript)) {
    throw "Startup script not found at $StartScript"
}

while ($true) {
    try {
        & $StartScript *> $null
    } catch {
        $Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Add-Content -Path $WatchLog -Value "$Timestamp $($_.Exception.Message)"
    }

    Start-Sleep -Seconds $IntervalSeconds
}

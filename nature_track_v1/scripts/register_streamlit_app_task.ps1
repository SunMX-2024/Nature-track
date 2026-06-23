param(
    [string]$TaskName = "NatureTrackStreamlitApp"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$StartScript = Join-Path $ProjectRoot "scripts\start_streamlit_app.ps1"
$WatchScript = Join-Path $ProjectRoot "scripts\watch_streamlit_app.ps1"

if (-not (Test-Path $StartScript)) {
    throw "Startup script not found at $StartScript"
}

if (-not (Test-Path $WatchScript)) {
    throw "Watch script not found at $WatchScript"
}

$PowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$PowerShellArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$WatchScript`""
$Action = New-ScheduledTaskAction -Execute $PowerShell -Argument $PowerShellArgs -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -MultipleInstances IgnoreNew

try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Description "Keep the local Nature-track Streamlit app running after login." `
        -Force

    Write-Host "Registered scheduled task '$TaskName'. It will keep Nature-track running after login."
} catch {
    $Startup = [Environment]::GetFolderPath("Startup")
    $Launcher = Join-Path $Startup "$TaskName.vbs"
    $Command = "$PowerShell $PowerShellArgs"
    $EscapedCommand = $Command.Replace('"', '""')
    $LauncherBody = @"
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "$EscapedCommand", 0, False
"@
    Set-Content -Path $Launcher -Value $LauncherBody -Encoding ASCII
    Write-Host "Scheduled task registration failed: $($_.Exception.Message)"
    Write-Host "Installed Startup launcher instead: $Launcher"
}

param(
    [string]$TaskName = "Nature-track digest",
    [ValidateSet("daily", "weekly")]
    [string]$Frequency = "weekly",
    [string]$WeeklyDay = "Monday",
    [string]$Time = "08:00"
)

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Script = Join-Path $ProjectRoot "scripts\send_digest.py"

if (-not (Test-Path $Python)) {
    throw "Virtual environment Python not found at $Python"
}

$Action = New-ScheduledTaskAction -Execute $Python -Argument "`"$Script`"" -WorkingDirectory $ProjectRoot
if ($Frequency -eq "weekly") {
    $Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $WeeklyDay -At $Time
} else {
    $Trigger = New-ScheduledTaskTrigger -Daily -At $Time
}
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 20)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Send Nature-track literature digest" -Force
Write-Host "Registered scheduled task '$TaskName' ($Frequency) at $Time."

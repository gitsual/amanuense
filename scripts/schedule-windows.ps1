# schedule-windows.ps1 — run the workshop on a schedule, as the current user.
#
#   powershell -ExecutionPolicy Bypass -File scripts\schedule-windows.ps1                   daily at 08:00
#   powershell -ExecutionPolicy Bypass -File scripts\schedule-windows.ps1 -At 07:30 -Every weekly   (Mondays)
#   powershell -ExecutionPolicy Bypass -File scripts\schedule-windows.ps1 -- --ai-cli copilot
#   powershell -ExecutionPolicy Bypass -File scripts\schedule-windows.ps1 -Remove
#
# Each run fetches the repos in repos.txt, updates the log and prepares the tasks; it never
# opens the browser. Open output\index.html (or output\log.html) when it suits you.
# Repos that need a password must have it saved in Git's credential manager first:
# a scheduled run never asks for one.
param(
    [string]$At = "08:00",
    [ValidateSet("daily", "weekly")][string]$Every = "daily",
    [string]$Name = "amanuense",
    [switch]$Remove,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Extra = @()
)
$ErrorActionPreference = "Stop"
if ($Remove) {
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false
    Write-Host "Removed the scheduled task '$Name'."
    exit 0
}
$root = Split-Path $PSScriptRoot -Parent
$launcher = Join-Path $root "amanuense.ps1"
$runArgs = @("--no-open") + @($Extra | Where-Object { $_ -ne "--" })
$argLine = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcher`" " + ($runArgs -join " ")
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argLine -WorkingDirectory $root
$time = [datetime]::ParseExact($At, "HH:mm", $null)
$trigger = if ($Every -eq "weekly") { New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At $time }
           else { New-ScheduledTaskTrigger -Daily -At $time }
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "Scheduled '$Name' $Every at $At$(if ($Every -eq 'weekly') { ' (Mondays)' })."
Write-Host "Run it now with: Start-ScheduledTask -TaskName $Name"

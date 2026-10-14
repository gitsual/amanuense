# schedule-radar.ps1 — run scripts/radar.sh on a schedule with Git Bash, as the current user.
#
#   powershell -ExecutionPolicy Bypass -File scripts\schedule-radar.ps1                       daily at 08:30
#   powershell -ExecutionPolicy Bypass -File scripts\schedule-radar.ps1 -Commit -Push         keep the history in Git
#   powershell -ExecutionPolicy Bypass -File scripts\schedule-radar.ps1 -At 13:15 -Every weekly   (Mondays)
#   powershell -ExecutionPolicy Bypass -File scripts\schedule-radar.ps1 -Workspace "D:\team\docs" -- --ai-cli copilot
#   powershell -ExecutionPolicy Bypass -File scripts\schedule-radar.ps1 -Remove
#
# The workshop is -Workspace, else AMANUENSE_WORKSPACE from the .env, else Documents\docs-workshop.
# If the laptop is off at that time the pass runs as soon as it can; when a repo is unreachable
# (no VPN, no network) it stops at once and tries again next time. Each pass appends to
# <workshop>\radar.log. Save the Git credentials first: a scheduled pass never asks for them.
param(
    [string]$At = "08:30",
    [ValidateSet("daily", "weekly")][string]$Every = "daily",
    [string]$Name = "amanuense-radar",
    [string]$Workspace = "",
    [switch]$Commit,
    [switch]$Push,
    [switch]$Deliver,
    [switch]$Remove,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Extra = @()
)
$ErrorActionPreference = "Stop"
if ($Remove) {
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false
    Write-Host "Removed the scheduled task '$Name'."
    exit 0
}

$bash = $null
$git = Get-Command git -ErrorAction SilentlyContinue
if ($git) {
    $candidate = Join-Path (Split-Path (Split-Path $git.Source -Parent) -Parent) "bin\bash.exe"
    if (Test-Path $candidate) { $bash = $candidate }
}
if (-not $bash) {
    foreach ($dir in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, "$env:LOCALAPPDATA\Programs")) {
        if ($dir -and (Test-Path "$dir\Git\bin\bash.exe")) { $bash = "$dir\Git\bin\bash.exe"; break }
    }
}
if (-not $bash) { throw "Git Bash not found. Install Git for Windows." }

$root = Split-Path $PSScriptRoot -Parent
if (-not $Workspace) {
    $envFile = Join-Path $root ".env"
    if (Test-Path $envFile) {
        $line = Get-Content $envFile | Where-Object { $_ -match '^\s*AMANUENSE_WORKSPACE\s*=' } | Select-Object -Last 1
        if ($line) { $Workspace = ($line -split '=', 2)[1].Trim().Trim('"') }
    }
}
if (-not $Workspace) { $Workspace = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "docs-workshop" }
if (-not (Test-Path $Workspace)) { throw "No workshop at $Workspace. Create it first with amanuense.bat." }
$Workspace = (Resolve-Path $Workspace).Path

$script = (Join-Path $PSScriptRoot "radar.sh") -replace '\\', '/'
$flags = @("--workspace", "'" + ($Workspace -replace '\\', '/') + "'")
if ($Commit -or $Push) { $flags += "--commit" }
if ($Push) { $flags += "--push" }
if ($Deliver) { $flags += "--deliver" }
$rest = @($Extra | Where-Object { $_ -ne "--" })
if ($rest.Count) { $flags += "--"; $flags += $rest }
$command = "& '$bash' '$script' " + ($flags -join " ")
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -Command `"$command`"" -WorkingDirectory $root
$time = [datetime]::ParseExact($At, "HH:mm", $null)
$trigger = if ($Every -eq "weekly") {
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At $time
} else {
    New-ScheduledTaskTrigger -Daily -At $time
}
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings `
    -Description "amanuense radar over $Workspace" -Force | Out-Null
Write-Host "Scheduled '$Name': $Every at $At over $Workspace."
Write-Host "Run it now with: Start-ScheduledTask -TaskName $Name"

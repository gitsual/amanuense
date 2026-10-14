# amanuense.ps1 — documentation workshop (see docs\guide.md).
#
#   First run: creates the workshop folder and opens it.
#   Next runs: analyses it and opens output\index.html.
#
#   powershell -ExecutionPolicy Bypass -File .\amanuense.ps1 [extra args, e.g. --ai-cli copilot]
#   powershell -ExecutionPolicy Bypass -File .\amanuense.ps1 obsidian EXPORT.docx VAULT\MIND
#
#   powershell -ExecutionPolicy Bypass -File .\amanuense.ps1 --lang es   (Spanish workshop)
#
# Workshop folder: $env:AMANUENSE_WORKSPACE (or .env), default Documents\docs-workshop
# (Documents\taller-docs if it exists). An existing workshop keeps its own language.
# Needs only Python 3.11+; uses .venv when there is one.
$Rest = @($args)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
if (Test-Path ".env") {
    Get-Content .env | Where-Object { $_ -match '^\s*[A-Za-z_][A-Za-z0-9_]*=' } | ForEach-Object {
        $k, $v = $_ -split '=', 2
        [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim(), "Process")
    }
}
$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = (Join-Path $PSScriptRoot "src") + $(if ($env:PYTHONPATH) { ";" + $env:PYTHONPATH } else { "" })
$DefaultWorkspace = Join-Path $HOME "Documents\docs-workshop"
if (Test-Path (Join-Path $HOME "Documents\taller-docs")) { $DefaultWorkspace = Join-Path $HOME "Documents\taller-docs" }
$Workspace = if ($env:AMANUENSE_WORKSPACE) { $env:AMANUENSE_WORKSPACE } else { $DefaultWorkspace }
# --lang works before or after the subcommand; init only needs that one flag.
$LangArgs = @()
for ($i = 0; $i -lt $Rest.Count; $i++) {
    if ($Rest[$i] -eq "--lang" -and $i + 1 -lt $Rest.Count) { $LangArgs = @("--lang", $Rest[$i + 1]) }
    elseif ($Rest[$i] -like "--lang=*") { $LangArgs = @($Rest[$i]) }
}

$pyExe = $null; $pyArgs = @()
if (Test-Path ".venv\Scripts\python.exe") { $pyExe = ".venv\Scripts\python.exe" }
elseif (Get-Command py -ErrorAction SilentlyContinue) { $pyExe = "py"; $pyArgs = @("-3") }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $pyExe = "python" }
else { Write-Error "missing: Python 3 (https://www.python.org/downloads/, check 'Add to PATH')" }

if ($Rest.Count -gt 0 -and $Rest[0] -eq "obsidian") {
    & $pyExe @pyArgs -m amanuense @Rest
    if ($LASTEXITCODE -ne 0) { throw "amanuense obsidian failed" }
    exit 0
}
if (-not (Test-Path (Join-Path $Workspace "1-confluence-export")) -and
    -not (Test-Path (Join-Path $Workspace "1-export-confluence"))) {
    $Guide = & $pyExe @pyArgs -m amanuense @LangArgs init $Workspace
    if ($LASTEXITCODE -ne 0) { throw "amanuense init failed" }
    Write-Host "Workshop created: $Workspace"
    Write-Host "Fill its folders (see $Guide) and run this again."
    Start-Process explorer.exe $Workspace
    exit 0
}
& $pyExe @pyArgs -m amanuense run $Workspace @Rest
if ($LASTEXITCODE -ne 0) { throw "amanuense run failed" }

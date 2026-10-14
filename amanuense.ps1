# amanuense.ps1 — documentation workshop (see docs\guide.md).
#
#   First run: creates the workshop folder and opens it.
#   Next runs: analyses it and opens output\index.html.
#
#   powershell -ExecutionPolicy Bypass -File .\amanuense.ps1 [extra args, e.g. --ai-cli copilot]
#   powershell -ExecutionPolicy Bypass -File .\amanuense.ps1 obsidian EXPORT.docx VAULT\MIND
#   powershell -ExecutionPolicy Bypass -File .\amanuense.ps1 deliver --zip   (delivery folder + zip)
#
#   powershell -ExecutionPolicy Bypass -File .\amanuense.ps1 --lang es   (Spanish workshop)
#
# Workshop folder: $env:AMANUENSE_WORKSPACE (or .env), default Documents\docs-workshop
# (Documents\taller-docs if it exists). An existing workshop keeps its own language.
# Needs only Python 3.11+; uses .venv when there is one, and finds Python even off the PATH.
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

# Python 3.11+, found even when the installer did not add it to the PATH.
function Find-Python {
    $ErrorActionPreference = "Continue"
    $candidates = @()
    if (Test-Path ".venv\Scripts\python.exe") { $candidates += ,@((Resolve-Path ".venv\Scripts\python.exe").Path) }
    if (Get-Command py -ErrorAction SilentlyContinue) { $candidates += ,@("py", "-3") }
    foreach ($name in @("python", "python3")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        # The WindowsApps "python.exe" only opens the Microsoft Store.
        if ($cmd -and $cmd.Source -notlike "*\WindowsApps\*") { $candidates += ,@($cmd.Source) }
    }
    # Python.org installers use Python3NN; the Python Install Manager uses Python\pythoncore-3.NN-64.
    $roots = @("$env:LOCALAPPDATA\Programs\Python", "$env:LOCALAPPDATA\Python", $env:ProgramFiles, ${env:ProgramFiles(x86)}, "C:\")
    foreach ($root in $roots) {
        if (-not $root -or -not (Test-Path $root)) { continue }
        Get-ChildItem -Path $root -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like "Python3*" -or $_.Name -like "pythoncore-3*" } |
            Sort-Object { [int]($_.Name -replace '\D', '') } -Descending |
            ForEach-Object { $exe = Join-Path $_.FullName "python.exe"; if (Test-Path $exe) { $candidates += ,@($exe) } }
    }
    foreach ($c in $candidates) {
        $exe = $c[0]; $extra = @($c | Select-Object -Skip 1)
        & $exe @extra -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { return ,$c }
    }
    return $null
}

$found = Find-Python
if (-not $found) {
    Write-Host "Python 3.11 or newer was not found."
    Write-Host "Install it from https://www.python.org/downloads/windows/ (the PATH box is optional)"
    Write-Host "or run: winget install Python.Python.3.12"
    exit 1
}
$pyExe = $found[0]; $pyArgs = @($found | Select-Object -Skip 1)

if ($Rest.Count -gt 0 -and $Rest[0] -eq "radiator") {
    # Capability catalogue of the workshop: amanuense.bat radiator [--no-open]
    & $pyExe @pyArgs -m amanuense radiator $Workspace @($Rest | Select-Object -Skip 1)
    if ($LASTEXITCODE -ne 0) { throw "amanuense radiator failed" }
    exit 0
}
if ($Rest.Count -gt 0 -and $Rest[0] -eq "deliver") {
    # Ready pages into the workshop's delivery folder: amanuense.bat deliver [--zip] [--no-open]
    & $pyExe @pyArgs -m amanuense deliver $Workspace @($Rest | Select-Object -Skip 1)
    if ($LASTEXITCODE -ne 0) { throw "amanuense deliver failed" }
    exit 0
}
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

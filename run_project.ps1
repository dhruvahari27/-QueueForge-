# QueueForge Nexus PowerShell Runner
$root = $PSScriptRoot
Set-Location $root
$venvPython = Join-Path $root "backend\.venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    & $venvPython (Join-Path $root "run_all.py")
} else {
    python (Join-Path $root "run_all.py")
}

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $installedPython = Get-Command py -ErrorAction SilentlyContinue
    if ($installedPython) { & py -3 -m venv .venv }
    else { & python -m venv .venv }
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11 or newer, then run this launcher again.' }
    & $pythonPath -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
Write-Host 'Research Commons: http://127.0.0.1:8000'
Write-Host 'Keep this window open. Press Ctrl+C to stop.'
& $pythonPath commons.py

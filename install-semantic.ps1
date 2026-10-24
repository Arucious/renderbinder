$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    $taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run start.cmd once to create the gallery environment.' }
    $taskUv = Get-Command uv -ErrorAction SilentlyContinue
    if ($taskUv) { & $taskUv.Source sync --locked --extra semantic }
    else {
        & $taskPython -m ensurepip --upgrade
        if ($LASTEXITCODE -ne 0) { throw 'Could not prepare pip.' }
        & $taskPython -m pip install 'torch>=2.6,<3' 'torchvision>=0.21,<1' --index-url https://download.pytorch.org/whl/cpu
        if ($LASTEXITCODE -ne 0) { throw 'Could not install the CPU model runtime.' }
        & $taskPython -m pip install -r requirements-semantic.txt
    }
    if ($LASTEXITCODE -ne 0) { throw 'Semantic dependency installation failed.' }
    Write-Host 'Semantic matching dependencies installed. Restart the gallery, then choose a model in Settings & sources.'
} finally { Pop-Location }

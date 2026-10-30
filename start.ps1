param(
    [int]$Port = 8765,
    [switch]$NoBrowser,
    [switch]$SkipInstall
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if ($Port -lt 1024 -or $Port -gt 65535) { throw 'Choose a port between 1024 and 65535.' }

function Check-Exit([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed (exit $LASTEXITCODE). See the output above." }
}

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not (Test-Path -LiteralPath $python)) {
    if ($uv) { & $uv.Source venv --python '>=3.11' .venv; Check-Exit 'Creating Python environment' }
    else {
        $systemPython = Get-Command py -ErrorAction SilentlyContinue
        if ($systemPython) { & $systemPython.Source -3 -m venv .venv }
        else {
            $systemPython = Get-Command python -ErrorAction SilentlyContinue
            if (-not $systemPython) { throw 'Install Python 3.11 or newer from python.org, then run this script again.' }
            & $systemPython.Source -m venv .venv
        }
        Check-Exit 'Creating Python environment'
    }
}
& $python -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11 or newer is required"'
Check-Exit 'Python version check'

$requirementsHash = (Get-FileHash -LiteralPath 'requirements.txt' -Algorithm SHA256).Hash
$pythonStamp = Join-Path $PSScriptRoot '.venv\.gallery-requirements'
if (-not $SkipInstall -and (-not (Test-Path -LiteralPath $pythonStamp) -or (Get-Content -LiteralPath $pythonStamp -Raw).Trim() -ne $requirementsHash)) {
    Write-Host 'Installing backend dependencies...' -ForegroundColor DarkYellow
    if ($uv) { & $uv.Source pip install --python $python -r requirements.txt }
    else {
        & $python -m ensurepip --upgrade
        Check-Exit 'Preparing pip'
        & $python -m pip install -r requirements.txt
    }
    Check-Exit 'Backend dependency installation'
    Set-Content -LiteralPath $pythonStamp -Value $requirementsHash
}

$dist = Join-Path $PSScriptRoot 'frontend\dist\index.html'
$needsBuild = -not (Test-Path -LiteralPath $dist)
if (-not $needsBuild) {
    $builtAt = (Get-Item -LiteralPath $dist).LastWriteTimeUtc
    $sources = Get-ChildItem -LiteralPath 'frontend\src' -File -Recurse
    $needsBuild = @($sources | Where-Object { $_.LastWriteTimeUtc -gt $builtAt }).Count -gt 0
    foreach ($name in @('package.json','tsconfig.json','vite.config.ts','index.html','pnpm-lock.yaml')) {
        $candidate = Join-Path $PSScriptRoot "frontend\$name"
        if ((Test-Path -LiteralPath $candidate) -and (Get-Item -LiteralPath $candidate).LastWriteTimeUtc -gt $builtAt) { $needsBuild = $true }
    }
}
if ($needsBuild) {
    $node = Get-Command node -ErrorAction SilentlyContinue
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    $pnpm = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
    $bundledPnpm = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\pnpm\bin\pnpm.cjs'
    if (-not $node) { throw 'Install Node.js 22 LTS or newer, then run this script again.' }
    Push-Location -LiteralPath (Join-Path $PSScriptRoot 'frontend')
    try {
        if (-not $SkipInstall) {
            Write-Host 'Installing frontend dependencies...' -ForegroundColor DarkYellow
            if ($npm) { & $npm.Source install }
            elseif ($pnpm) { & $pnpm.Source install --frozen-lockfile }
            elseif (Test-Path -LiteralPath $bundledPnpm) { & $node.Source $bundledPnpm install --frozen-lockfile }
            else { throw 'Node.js is available but npm/pnpm is missing. Install Node.js with npm.' }
            Check-Exit 'Frontend dependency installation'
        }
        Write-Host 'Building the gallery...' -ForegroundColor DarkYellow
        & $node.Source 'node_modules\typescript\bin\tsc' -b
        Check-Exit 'TypeScript check'
        & $node.Source 'node_modules\vite\bin\vite.js' build
        Check-Exit 'Frontend build'
    } finally { Pop-Location }
}

Write-Host "`nRenderBinder is starting at http://127.0.0.1:$Port" -ForegroundColor Green
Write-Host 'Add your ComfyUI output folder in Settings & sources. Press Ctrl+C to stop.'
if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port" }
& $python -m uvicorn app.main:app --host 127.0.0.1 --port $Port
Check-Exit 'Gallery server'

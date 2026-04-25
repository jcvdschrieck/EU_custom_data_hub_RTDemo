# EU Custom Data Hub - one-shot installer for Windows (PowerShell 5.1+).
#
# Same flow as install.sh. Uses winget to install Python / Node.js if
# missing. Re-runnable.
#
# Run with:  .\install.ps1
#   (If PowerShell blocks the script, unblock once with:
#      Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned)

#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
$ScriptDir = $PSScriptRoot
Set-Location $ScriptDir

# ── Config ──────────────────────────────────────────────────────────────
$config = [ordered]@{
    BACKEND_PORT     = '8505'
    CT_FRONTEND_PORT = '8080'
    LM_STUDIO_URL    = 'http://localhost:1234'
    LM_STUDIO_MODEL  = 'mistralai/mistral-7b-instruct-v0.3'
}
$configFile = Join-Path $ScriptDir 'config.env'
if (Test-Path $configFile) {
    Get-Content $configFile | ForEach-Object {
        if ($_ -match '^\s*([A-Z_]+)\s*=\s*(.+?)\s*$') {
            $config[$Matches[1]] = $Matches[2]
        }
    }
}

Write-Host "── Config ───────────────────────────────────────────────────────"
foreach ($k in $config.Keys) { Write-Host ("  {0,-16} = {1}" -f $k, $config[$k]) }
Write-Host "────────────────────────────────────────────────────────────────"

function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

# ── Python 3.11+ ────────────────────────────────────────────────────────
if (-not (Have python)) {
    if (-not (Have winget)) {
        Write-Error "winget is missing. Install App Installer from the Microsoft Store, or install Python 3.11+ manually, then re-run."
    }
    Write-Host "==> Installing Python 3.11 via winget"
    winget install -e --id Python.Python.3.11 --accept-package-agreements --accept-source-agreements
    # winget updates the machine PATH; this process needs a refresh.
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path', 'User')
}
# Parse the version out of `python --version` rather than running Python -c
# with an inline format string. PowerShell on Windows mangles the quotes
# around `-c` arguments differently across major versions (5.1 vs 7+),
# turning `'%d.%d' % sys.version_info[:2]` into `%d.%d % sys.version_info`
# inside Python — a SyntaxError. `python --version` prints a single
# unambiguous line ("Python 3.11.5") that we can regex-match.
$pyVerOutput = (& python --version 2>&1 | Out-String).Trim()
if ($pyVerOutput -notmatch 'Python\s+(\d+)\.(\d+)') {
    Write-Error "Could not parse Python version from output: $pyVerOutput"
}
$pyMajor = [int]$Matches[1]
$pyMinor = [int]$Matches[2]
if ($pyMajor -lt 3 -or ($pyMajor -eq 3 -and $pyMinor -lt 11)) {
    Write-Error "Python $pyMajor.$pyMinor is too old (need 3.11+)."
}
Write-Host "✓ Python $pyMajor.$pyMinor"

# ── Node.js 18+ ─────────────────────────────────────────────────────────
if (-not (Have node)) {
    if (-not (Have winget)) {
        Write-Error "winget is missing. Install Node.js 18+ manually, then re-run."
    }
    Write-Host "==> Installing Node.js LTS via winget"
    winget install -e --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path', 'User')
}
# Parse `node -v` output ("v20.10.0") rather than `node -p '<JS>'` for the
# same quote-robustness reason as the Python check above.
$nodeVerOutput = (& node -v 2>&1 | Out-String).Trim()
if ($nodeVerOutput -notmatch '^v(\d+)\.') {
    Write-Error "Could not parse Node version from output: $nodeVerOutput"
}
$nodeMajor = [int]$Matches[1]
if ($nodeMajor -lt 18) {
    Write-Error "Node.js $nodeVerOutput is too old (need 18+)."
}
Write-Host "✓ Node.js $nodeVerOutput"

# ── Python venv + deps ──────────────────────────────────────────────────
$venvDir = Join-Path $ScriptDir '.venv'
if (-not (Test-Path $venvDir)) {
    Write-Host "==> Creating Python venv at $venvDir"
    & python -m venv $venvDir
}
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
Write-Host "==> Installing Python dependencies into venv"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements.txt

# ── Internal frontend ───────────────────────────────────────────────────
Write-Host "==> Building internal frontend"
Push-Location frontend
& npm install
& npm run build
Pop-Location

# ── C&T frontend (sibling directory) ────────────────────────────────────
$ctDir = Join-Path (Split-Path -Parent $ScriptDir) 'customsandtaxriskmanagemensystem'
if (-not (Test-Path $ctDir)) {
    Write-Host "==> Cloning C&T frontend to $ctDir"
    & git clone https://github.com/jcvdschrieck/customsandtaxriskmanagemensystem.git $ctDir
}
Write-Host "==> Installing C&T frontend dependencies"
Push-Location $ctDir
& npm install
Pop-Location

# ── Generated .env files ────────────────────────────────────────────────
Write-Host "==> Writing $ctDir\.env"
Set-Content -Path (Join-Path $ctDir '.env') -Value "VITE_API_BASE_URL=http://localhost:$($config.BACKEND_PORT)"

Write-Host "==> Writing vat_fraud_detection\.env"
@"
LM_STUDIO_BASE_URL=$($config.LM_STUDIO_URL)/v1
LM_STUDIO_MODEL=$($config.LM_STUDIO_MODEL)
"@ | Set-Content -Path (Join-Path $ScriptDir 'vat_fraud_detection\.env')

# ── Warm the HF embedder cache ──────────────────────────────────────────
# Downloads the all-MiniLM-L6-v2 SentenceTransformer weights (~90 MB)
# into the local HF cache so the VAT Fraud Detection agent can run in
# offline mode at runtime. Without this, the agent subprocess errors
# out when huggingface_hub >= 1.7 tries to reach hub.hf.co on every
# SentenceTransformer() init.
Write-Host "==> Warming the Hugging Face embedder cache (~90 MB, one-off)"
# Run via a tiny script file rather than -c '…' so PowerShell quoting
# can't mangle the inline Python (same lesson as the python --version
# check earlier).
& $venvPython (Join-Path $ScriptDir 'scripts\warm_hf_cache.py')

# ── Seed databases ──────────────────────────────────────────────────────
Write-Host "==> Seeding databases"
& $venvPython seed_databases.py

Write-Host ""
Write-Host "✅ Install complete."
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. (Optional) Install LM Studio from https://lmstudio.ai and start its"
Write-Host "     local server with the model '$($config.LM_STUDIO_MODEL)' on $($config.LM_STUDIO_URL)."
Write-Host "     Without it, the VAT Fraud Detection Agent returns 'uncertain'."
Write-Host ""
Write-Host "  2. (Optional, ~5 min) Build the RAG knowledge base:"
Write-Host "       cd vat_fraud_detection"
Write-Host "       python build_knowledge_base.py --minilm-only"
Write-Host ""
Write-Host "  3. Launch everything:"
Write-Host "       .\run.ps1"

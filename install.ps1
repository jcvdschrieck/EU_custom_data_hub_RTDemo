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

# -- Config --------------------------------------------------------------
$config = [ordered]@{
    BACKEND_PORT             = '8505'
    CT_FRONTEND_PORT         = '8080'
    LLM_PROVIDER             = 'lmstudio'
    LLM_MODEL                = 'mistralai/mistral-7b-instruct-v0.3'
    LLM_API_KEY              = ''
    LLM_BASE_URL             = ''
    LM_STUDIO_URL            = 'http://localhost:1234'
    LM_STUDIO_MODEL          = 'mistralai/mistral-7b-instruct-v0.3'
    AZURE_OPENAI_ENDPOINT    = ''
    AZURE_OPENAI_DEPLOYMENT  = ''
    AZURE_OPENAI_API_VERSION = '2024-02-15-preview'
}
$configFile = Join-Path $ScriptDir 'config.env'
if (Test-Path $configFile) {
    Get-Content $configFile | ForEach-Object {
        if ($_ -match '^\s*([A-Z_]+)\s*=\s*(.*)\s*$') {
            $config[$Matches[1]] = $Matches[2]
        }
    }
}

# Mask the API key in the echoed config so screencaps don't leak it.
$keyDisplay = if ([string]::IsNullOrEmpty($config.LLM_API_KEY)) { '(unset)' }
              else { '****' + $config.LLM_API_KEY.Substring([Math]::Max(0, $config.LLM_API_KEY.Length - 4)) }

Write-Host "-- Config -------------------------------------------------------"
Write-Host ("  {0,-18} = {1}" -f 'BACKEND_PORT',     $config.BACKEND_PORT)
Write-Host ("  {0,-18} = {1}" -f 'CT_FRONTEND_PORT', $config.CT_FRONTEND_PORT)
Write-Host ("  {0,-18} = {1}" -f 'LLM_PROVIDER',     $config.LLM_PROVIDER)
Write-Host ("  {0,-18} = {1}" -f 'LLM_MODEL',        $config.LLM_MODEL)
Write-Host ("  {0,-18} = {1}" -f 'LLM_API_KEY',      $keyDisplay)
if ($config.LLM_BASE_URL) {
    Write-Host ("  {0,-18} = {1}" -f 'LLM_BASE_URL', $config.LLM_BASE_URL)
}
if ($config.LLM_PROVIDER -eq 'lmstudio') {
    Write-Host ("  {0,-18} = {1}" -f 'LM_STUDIO_URL', $config.LM_STUDIO_URL)
}
if ($config.LLM_PROVIDER -eq 'azure') {
    Write-Host ("  {0,-18} = {1}" -f 'AZURE_ENDPOINT',   $config.AZURE_OPENAI_ENDPOINT)
    Write-Host ("  {0,-18} = {1}" -f 'AZURE_DEPLOYMENT', $config.AZURE_OPENAI_DEPLOYMENT)
}
Write-Host "----------------------------------------------------------------"

function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

# -- Python 3.11+ --------------------------------------------------------
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
# inside Python -- a SyntaxError. `python --version` prints a single
# unambiguous line ("Python 3.11.5") that we can regex-match.
$pyVerOutput = (& python --version 2>&1 | Out-String).Trim()
if ($pyVerOutput -notmatch 'Python\s+(\d+)\.(\d+)') {
    Write-Error "Could not parse Python version from output: $pyVerOutput"
}
$pyMajor = [int]$Matches[1]
$pyMinor = [int]$Matches[2]
if ($pyMajor -lt 3 -or ($pyMajor -eq 3 -and $pyMinor -lt 11)) {
    Write-Error "Python ${pyMajor}.${pyMinor} is too old (need 3.11+)."
}
Write-Host "[OK] Python ${pyMajor}.${pyMinor}"

# -- Node.js 18+ ---------------------------------------------------------
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
Write-Host "[OK] Node.js $nodeVerOutput"

# -- Detect packaged-mode artefacts --------------------------------------
$packaged = Test-Path (Join-Path $ScriptDir '.packaged')
if ($packaged) { Write-Host "==> Packaged mode detected (.packaged found)" }

# -- Python venv + deps --------------------------------------------------
$venvDir = Join-Path $ScriptDir '.venv'
if (-not (Test-Path $venvDir)) {
    Write-Host "==> Creating Python venv at $venvDir"
    & python -m venv $venvDir
}
$venvPython = Join-Path $venvDir 'Scripts\python.exe'
$wheelsDir  = Join-Path $ScriptDir 'wheels'
$hasWheels  = (Test-Path $wheelsDir) -and ((Get-ChildItem -Path $wheelsDir -Filter '*.whl' -ErrorAction SilentlyContinue).Count -gt 0)
if ($hasWheels) {
    Write-Host "==> Installing Python dependencies (offline, from wheels\)"
    & $venvPython -m pip install --upgrade --no-index --find-links $wheelsDir pip
    & $venvPython -m pip install --no-index --find-links $wheelsDir -r requirements.txt
} else {
    Write-Host "==> Installing Python dependencies from PyPI"
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r requirements.txt
}

# -- Internal frontend ---------------------------------------------------
$internalDist = Join-Path $ScriptDir 'frontend\dist\index.html'
if (Test-Path $internalDist) {
    Write-Host "==> Internal frontend already built (frontend\dist\) -- skipping"
} else {
    Write-Host "==> Building internal frontend"
    Push-Location frontend
    & npm install
    & npm run build
    Pop-Location
}

# -- C&T frontend (vendored subdirectory) --------------------------------
$ctDir   = Join-Path $ScriptDir 'customsandtaxriskmanagemensystem'
$ctDist  = Join-Path $ctDir 'dist\index.html'
if (Test-Path $ctDist) {
    Write-Host "==> C&T dashboard already built -- skipping npm install"
} else {
    Write-Host "==> Installing C&T frontend dependencies"
    Push-Location $ctDir
    & npm install
    Pop-Location
}

# -- Generated .env files ------------------------------------------------
Write-Host "==> Writing $ctDir\.env"
Set-Content -Path (Join-Path $ctDir '.env') -Value "VITE_API_BASE_URL=http://localhost:$($config.BACKEND_PORT)"

Write-Host "==> Writing vat_fraud_detection\.env"
$lines = @()
$lines += '# Generated by install.ps1 from config.env -- do not commit.'
$lines += "LLM_PROVIDER=$($config.LLM_PROVIDER)"
$lines += "LLM_MODEL=$($config.LLM_MODEL)"
if ($config.LLM_API_KEY)  { $lines += "LLM_API_KEY=$($config.LLM_API_KEY)" }
if ($config.LLM_BASE_URL) { $lines += "LLM_BASE_URL=$($config.LLM_BASE_URL)" }
$lines += "LM_STUDIO_BASE_URL=$($config.LM_STUDIO_URL)/v1"
$lines += "LM_STUDIO_MODEL=$($config.LM_STUDIO_MODEL)"
# Mirror LLM_API_KEY into the provider-specific var so users who only
# set the generic key still satisfy provider-specific lookups.
if ($config.LLM_API_KEY) {
    switch ($config.LLM_PROVIDER) {
        'openai'    { $lines += "OPENAI_API_KEY=$($config.LLM_API_KEY)" }
        'anthropic' { $lines += "ANTHROPIC_API_KEY=$($config.LLM_API_KEY)" }
        'azure'     { $lines += "AZURE_OPENAI_API_KEY=$($config.LLM_API_KEY)" }
    }
}
if ($config.LLM_PROVIDER -eq 'azure') {
    $lines += "AZURE_OPENAI_ENDPOINT=$($config.AZURE_OPENAI_ENDPOINT)"
    $lines += "AZURE_OPENAI_DEPLOYMENT=$($config.AZURE_OPENAI_DEPLOYMENT)"
    $lines += "AZURE_OPENAI_API_VERSION=$($config.AZURE_OPENAI_API_VERSION)"
}
$lines -join "`n" | Set-Content -Path (Join-Path $ScriptDir 'vat_fraud_detection\.env')

# -- Warm the HF embedder cache ------------------------------------------
$hfCacheDir = Join-Path $ScriptDir 'models\hf-cache'
if (Test-Path $hfCacheDir) {
    Write-Host "==> HF cache pre-shipped -- appending HF_HOME to .env"
    Add-Content -Path (Join-Path $ScriptDir 'vat_fraud_detection\.env') `
                -Value "HF_HOME=$hfCacheDir"
} else {
    Write-Host "==> Warming the Hugging Face embedder cache (~90 MB, one-off)"
    & $venvPython (Join-Path $ScriptDir 'scripts\warm_hf_cache.py')
}

# -- Seed databases ------------------------------------------------------
$existingDBs = Get-ChildItem -Path (Join-Path $ScriptDir 'data') -Filter '*.db' -ErrorAction SilentlyContinue
if ($existingDBs.Count -gt 0) {
    Write-Host "==> Databases already pre-seeded -- skipping"
} else {
    Write-Host "==> Seeding databases"
    & $venvPython seed_databases.py
}

Write-Host ""
Write-Host "[DONE] Install complete."
Write-Host ""
Write-Host "Active LLM configuration:"
switch ($config.LLM_PROVIDER) {
    'lmstudio' {
        Write-Host "  Provider: LM Studio (local) -- $($config.LM_STUDIO_URL)"
        Write-Host "  Model:    $($config.LLM_MODEL)"
        Write-Host "  -> Install LM Studio from https://lmstudio.ai, load this model,"
        Write-Host "     and click Start Server in the Developer tab before running."
        Write-Host "     Without LM Studio the agent returns 'uncertain'."
    }
    'openai' {
        Write-Host "  Provider: OpenAI cloud"
        Write-Host "  Model:    $($config.LLM_MODEL)"
        Write-Host "  API key:  $keyDisplay"
    }
    'anthropic' {
        Write-Host "  Provider: Anthropic Claude"
        Write-Host "  Model:    $($config.LLM_MODEL)"
        Write-Host "  API key:  $keyDisplay"
    }
    'azure' {
        Write-Host "  Provider: Azure OpenAI"
        Write-Host "  Endpoint: $($config.AZURE_OPENAI_ENDPOINT)"
        Write-Host "  Deploy:   $($config.AZURE_OPENAI_DEPLOYMENT)"
        Write-Host "  API key:  $keyDisplay"
    }
}
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. (Optional, ~5 min) Build the RAG knowledge base:"
Write-Host "       cd vat_fraud_detection"
Write-Host "       python build_knowledge_base.py --minilm-only"
Write-Host ""
Write-Host "  2. Launch everything:"
Write-Host "       .\run.ps1"

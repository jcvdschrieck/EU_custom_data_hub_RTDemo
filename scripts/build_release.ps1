# build_release.ps1 — package the EU Custom Data Hub demo into a single
# self-contained ZIP suitable for SharePoint distribution. Windows
# counterpart of scripts/build_release.sh — produces the windows zip.
#
# What it does:
#   1. Reads the version from the top-level VERSION file.
#   2. Copies the project tree into a staging directory, excluding
#      developer artefacts (.git, .venv, __pycache__, node_modules).
#   3. Pre-fetches Python wheels for the host platform into wheels\.
#   4. Pre-builds the internal Vite frontend into frontend\dist\.
#   5. Pre-builds the C&T dashboard into customsandtaxriskmanagemensystem\dist\.
#   6. Copies the carried Hugging Face embedder cache (or warms one).
#   7. Pre-seeds the four SQLite databases into data\.
#   8. Drops a `.packaged` marker so install.ps1 knows to use the
#      bundled artefacts instead of fetching from the network.
#   9. Zips the staging dir → releases\EU-Custom-Data-Hub-vX.Y.Z-windows.zip.
#
# Run from the project root:    .\scripts\build_release.ps1
#
# Maintainers: build on each target OS to produce the per-platform zip
# (Python wheels are platform-specific). Upload all three zips to
# SharePoint so end users can pick the matching one.

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjRoot  = Split-Path -Parent $ScriptDir
Set-Location $ProjRoot

if (-not (Test-Path "$ProjRoot\VERSION")) {
    Write-Error "VERSION file missing at $ProjRoot\VERSION"
    exit 1
}
$Version = (Get-Content "$ProjRoot\VERSION" -Raw).Trim()

$OsTag      = 'windows'
$PkgName    = "EU-Custom-Data-Hub-v$Version-$OsTag"
$StageDir   = Join-Path $ProjRoot "build\$PkgName"
$ReleaseDir = Join-Path $ProjRoot 'releases'
$ZipPath    = Join-Path $ReleaseDir "$PkgName.zip"

Write-Host "-- Build target ----------------------------------------------"
Write-Host "  Version:  $Version"
Write-Host "  OS tag:   $OsTag"
Write-Host "  Stage:    $StageDir"
Write-Host "  Output:   $ZipPath"
Write-Host "--------------------------------------------------------------"

# -- Step 1: clean stage --------------------------------------------------
if (Test-Path $StageDir) { Remove-Item $StageDir -Recurse -Force }
New-Item -ItemType Directory -Path $StageDir   -Force | Out-Null
New-Item -ItemType Directory -Path $ReleaseDir -Force | Out-Null

# -- Step 2: copy source --------------------------------------------------
# robocopy /MIR /XD <dirs> /XF <files> mirrors the tree minus excludes.
# Codes 0-7 are success on robocopy; 8+ are failures.
Write-Host "==> Copying source tree (excluding dev artefacts)"
$ExcludeDirs  = @('.git', '.venv', 'node_modules', '__pycache__',
                   '.pytest_cache', 'build', 'releases', '.claude')
$ExcludeFiles = @('*.pyc', '.DS_Store', '*.bak', '*.log', '.env')
$rcArgs = @($ProjRoot, $StageDir, '/MIR',
            '/XD') + $ExcludeDirs + @('/XF') + $ExcludeFiles + @('/NFL', '/NDL', '/NJH', '/NJS', '/NC', '/NS', '/NP')
& robocopy @rcArgs | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Error "robocopy failed with exit code $LASTEXITCODE"
    exit 1
}
# Clean up screenshots that the .sh excludes via a glob — robocopy's
# /XF doesn't take wildcard patterns matching subdirs the same way.
Get-ChildItem -Path "$StageDir\Context" -Filter 'Screenshot*' -Recurse `
    -ErrorAction SilentlyContinue | Remove-Item -Force

# -- Step 3: pre-fetch Python wheels --------------------------------------
Write-Host "==> Pre-fetching Python wheels for $OsTag"
$WheelsDir = Join-Path $StageDir 'wheels'
New-Item -ItemType Directory -Path $WheelsDir -Force | Out-Null
$pyExe = Get-Command python -ErrorAction SilentlyContinue
if (-not $pyExe) { $pyExe = Get-Command python3 }
try {
    & $pyExe -m pip download `
        --dest $WheelsDir `
        --requirement (Join-Path $ProjRoot 'requirements.txt') `
        --quiet
    if ($LASTEXITCODE -ne 0) { throw "pip download exit $LASTEXITCODE" }
} catch {
    Write-Warning "pip download failed - package will require online install"
    Remove-Item $WheelsDir -Recurse -Force -ErrorAction SilentlyContinue
}

# -- Step 4: build internal frontend --------------------------------------
$FrontendDir = Join-Path $ProjRoot 'frontend'
if (Test-Path $FrontendDir) {
    Write-Host "==> Building internal frontend"
    Push-Location $FrontendDir
    try {
        & npm install --silent
        if ($LASTEXITCODE -ne 0) { throw "npm install exit $LASTEXITCODE" }
        & npm run build --silent
        if ($LASTEXITCODE -ne 0) { throw "npm run build exit $LASTEXITCODE" }
    } finally { Pop-Location }
    $StageFrontDist = Join-Path $StageDir 'frontend\dist'
    if (Test-Path $StageFrontDist) { Remove-Item $StageFrontDist -Recurse -Force }
    Copy-Item (Join-Path $FrontendDir 'dist') $StageFrontDist -Recurse
}

# -- Step 5: build C&T dashboard ------------------------------------------
$CtDir = Join-Path $ProjRoot 'customsandtaxriskmanagemensystem'
if (Test-Path $CtDir) {
    Write-Host "==> Building C&T dashboard"
    Push-Location $CtDir
    try {
        & npm install --silent
        if ($LASTEXITCODE -ne 0) { throw "npm install exit $LASTEXITCODE" }
        & npm run build --silent
        if ($LASTEXITCODE -ne 0) { throw "npm run build exit $LASTEXITCODE" }
    } finally { Pop-Location }
    $StageCtDist = Join-Path $StageDir 'customsandtaxriskmanagemensystem\dist'
    if (Test-Path $StageCtDist) { Remove-Item $StageCtDist -Recurse -Force }
    Copy-Item (Join-Path $CtDir 'dist') $StageCtDist -Recurse
}

# -- Step 6: ship the HF embedder cache -----------------------------------
# The repo carries a pre-warmed cache at $ProjRoot\models\hf-cache\.
# We copy it straight into the staged release. Falls back to running
# warm_hf_cache.py on the fly if the carried cache is missing.
$SourceHf  = Join-Path $ProjRoot 'models\hf-cache'
$StagedHf  = Join-Path $StageDir 'models\hf-cache'
$WarmScript= Join-Path $ProjRoot 'scripts\warm_hf_cache.py'
if (Test-Path (Join-Path $SourceHf 'hub')) {
    Write-Host "==> Copying carried HF embedder cache"
    New-Item -ItemType Directory -Path $StagedHf -Force | Out-Null
    Copy-Item (Join-Path $SourceHf 'hub') (Join-Path $StagedHf 'hub') -Recurse
} elseif (Test-Path $WarmScript) {
    Write-Host "==> Carried HF cache missing - warming on the fly (~90 MB)"
    New-Item -ItemType Directory -Path $StagedHf -Force | Out-Null
    try {
        $env:HF_HOME = $StagedHf
        & $pyExe $WarmScript
        if ($LASTEXITCODE -ne 0) { throw "warm_hf_cache exit $LASTEXITCODE" }
    } catch {
        Write-Warning "HF cache warm failed - package will fetch at install time"
        Remove-Item (Join-Path $StageDir 'models') -Recurse -Force `
            -ErrorAction SilentlyContinue
    } finally {
        Remove-Item Env:HF_HOME -ErrorAction SilentlyContinue
    }
}

# -- Step 7: pre-seed databases -------------------------------------------
Write-Host "==> Seeding databases into staging"
New-Item -ItemType Directory -Path (Join-Path $StageDir 'data') -Force | Out-Null
$venvPython = Join-Path $ProjRoot '.venv\Scripts\python.exe'
$seedPython = if (Test-Path $venvPython) { $venvPython } else { $pyExe }
Push-Location $StageDir
try {
    $env:PYTHONUTF8 = '1'
    & $seedPython 'seed_databases.py'
    if ($LASTEXITCODE -ne 0) { throw "seed exit $LASTEXITCODE" }
} catch {
    Write-Warning "Database seed failed - package will seed at install time"
    Get-ChildItem (Join-Path $StageDir 'data') -Filter '*.db' `
        -ErrorAction SilentlyContinue | Remove-Item -Force
} finally {
    $env:PYTHONUTF8 = $null
    Pop-Location
}

# -- Step 8: marker so install.ps1 detects bundled artefacts --------------
$BuiltAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
@"
version=$Version
os=$OsTag
built_at=$BuiltAt
"@ | Set-Content -Path (Join-Path $StageDir '.packaged') -Encoding ascii

# -- Step 9: zip ----------------------------------------------------------
Write-Host "==> Compressing to $ZipPath"
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
# Compress-Archive on Windows preserves directory structure and is
# present on every PowerShell 5.1+ install — no external deps.
# Retry up to 3 times with a short delay: AV scanners can briefly lock
# newly-written files (e.g. the Vite JS bundles) and cause a first-pass failure.
$zipDone = $false
for ($attempt = 1; $attempt -le 3; $attempt++) {
    try {
        Compress-Archive -Path $StageDir -DestinationPath $ZipPath -CompressionLevel Optimal
        $zipDone = $true
        break
    } catch {
        if ($attempt -lt 3) {
            Write-Host "  Compress attempt $attempt failed (file lock) - retrying in 5s..."
            Start-Sleep -Seconds 5
            if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
        } else {
            throw
        }
    }
}

function Test-Tag([string]$path) {
    if (Test-Path $path) { 'yes' } else { 'no' }
}

$SizeMB = [int]((Get-Item $ZipPath).Length / 1MB)
$wheelsTag   = Test-Tag (Join-Path $StageDir 'wheels')
$feDistTag   = Test-Tag (Join-Path $StageDir 'frontend\dist')
$ctDistTag   = Test-Tag (Join-Path $StageDir 'customsandtaxriskmanagemensystem\dist')
$hfCacheTag  = Test-Tag (Join-Path $StageDir 'models\hf-cache')
$dbCount = (Get-ChildItem (Join-Path $StageDir 'data') -Filter '*.db' `
    -ErrorAction SilentlyContinue | Measure-Object).Count
$dbsTag = if ($dbCount -gt 0) { 'yes' } else { 'no' }

Write-Host ""
Write-Host "[OK] Built $ZipPath ($SizeMB MB)"
Write-Host ""
Write-Host "Contents summary:"
Write-Host "  Source:           always present"
Write-Host "  Python wheels:    $wheelsTag"
Write-Host "  Frontend dist:    $feDistTag"
Write-Host "  C&T dist:         $ctDistTag"
Write-Host "  HF cache:         $hfCacheTag"
Write-Host "  Pre-seeded DBs:   $dbsTag"
Write-Host ""
Write-Host "Upload $ZipPath to SharePoint and reference it from INSTALL.md."

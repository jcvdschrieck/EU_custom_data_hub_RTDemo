# Launch both the backend and the C&T operator dashboard in two new
# PowerShell windows. Reads ports from config.env. Close either window
# to stop the corresponding service.
#
# Run with:  .\run.ps1

#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
$ScriptDir = $PSScriptRoot
Set-Location $ScriptDir

$config = [ordered]@{
    BACKEND_PORT     = '8505'
    CT_FRONTEND_PORT = '8080'
}
$configFile = Join-Path $ScriptDir 'config.env'
if (Test-Path $configFile) {
    Get-Content $configFile | ForEach-Object {
        if ($_ -match '^\s*([A-Z_]+)\s*=\s*(.+?)\s*$') {
            $config[$Matches[1]] = $Matches[2]
        }
    }
}

$ctDir = Join-Path (Split-Path -Parent $ScriptDir) 'customsandtaxriskmanagemensystem'
if (-not (Test-Path $ctDir)) {
    Write-Error "C&T frontend not found at $ctDir. Run .\install.ps1 first."
}
$venvPython = Join-Path $ScriptDir '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Error "Python venv not found at $(Split-Path -Parent $venvPython). Run .\install.ps1 first."
}

Write-Host "── Starting services ───────────────────────────────────────────"
Write-Host "  Backend:       http://localhost:$($config.BACKEND_PORT)"
Write-Host "  C&T dashboard: http://localhost:$($config.CT_FRONTEND_PORT)"
Write-Host "  Two new PowerShell windows will open. Close them to stop."
Write-Host "────────────────────────────────────────────────────────────────"

# Backend — API_PORT drives lib/config.py; --port drives uvicorn.
$backendCmd = "`$env:API_PORT='$($config.BACKEND_PORT)'; Set-Location '$ScriptDir'; & '$venvPython' -m uvicorn api:app --host 0.0.0.0 --port $($config.BACKEND_PORT)"
Start-Process powershell -ArgumentList '-NoExit', '-Command', $backendCmd

# C&T dashboard — PORT drives vite.config.ts.
$ctCmd = "`$env:PORT='$($config.CT_FRONTEND_PORT)'; Set-Location '$ctDir'; npm run dev"
Start-Process powershell -ArgumentList '-NoExit', '-Command', $ctCmd

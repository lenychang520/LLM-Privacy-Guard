# LLM Privacy Guard — Windows Uninstaller
# Run as Administrator: right-click → "Run with PowerShell"
#
# This script:
#   1. Runs privacy-guard teardown to restore original tool configs
#   2. Stops and removes the Windows Service
#   3. Deletes installed files

param(
    [int]$Port = 19999
)

$ErrorActionPreference = "Continue"
$ServiceName = "PrivacyGuard"
$InstallDir = "$env:ProgramFiles\PrivacyGuard"
$ExePath = "$InstallDir\privacy-guard.exe"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  LLM Privacy Guard — Uninstaller" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ── Check admin ──
if (-NOT ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Host "[ERROR] Uninstaller requires Administrator privileges." -ForegroundColor Red
    Write-Host "        Right-click uninstall.ps1 and select 'Run with PowerShell' (as Admin)."
    exit 1
}

# ── 1. Teardown — restore original tool configs ──
Write-Host "[1/4] Restoring original tool configs..." -ForegroundColor Yellow
if (Test-Path $ExePath) {
    & $ExePath teardown --port $Port
    Write-Host "       Configs restored."
} else {
    Write-Host "       privacy-guard.exe not found — skipping teardown."
}

# ── 2. Stop and remove service ──
Write-Host "[2/4] Removing Windows Service..." -ForegroundColor Yellow
$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($svc) {
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    sc.exe delete $ServiceName | Out-Null
    Write-Host "       Service removed."
} else {
    Write-Host "       Service not found."
}

# ── 3. Delete installed files ──
Write-Host "[3/4] Removing installed files..." -ForegroundColor Yellow
if (Test-Path $InstallDir) {
    Remove-Item -Recurse -Force $InstallDir -ErrorAction SilentlyContinue
    Write-Host "       $InstallDir removed."
} else {
    Write-Host "       Install directory not found."
}

# ── 4. Done ──
Write-Host "[4/4] Cleanup complete." -ForegroundColor Yellow
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Uninstall complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  All Privacy Guard files and service entries have been removed."
Write-Host "  Your LLM tools are back to their original configs."
Write-Host ""

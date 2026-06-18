# LLM Privacy Guard — Windows Installer
# Run as Administrator: right-click → "Run with PowerShell"
#
# This script:
#   1. Installs privacy-guard.exe to a stable location
#   2. Creates a Windows Service that auto-starts on boot
#   3. Configures auto-recovery (restart on crash, including pkill)
#   4. Runs privacy-guard setup to configure your LLM tools
#
# The Windows Service Manager (SCM) is NOT a Python process —
# it survives pkill python and taskkill, just like systemd on Linux.

param(
    [int]$Port = 19999,
    [string]$Upstream = "",
    [switch]$NoSetup = $false
)

$ErrorActionPreference = "Stop"
$ServiceName = "PrivacyGuard"
$InstallDir = "$env:ProgramFiles\PrivacyGuard"
$ExePath = "$InstallDir\privacy-guard.exe"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  LLM Privacy Guard — Installer" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ── Check admin ──
if (-NOT ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Host "[ERROR] This installer requires Administrator privileges." -ForegroundColor Red
    Write-Host "        Right-click install.ps1 and select 'Run with PowerShell' (as Admin)."
    exit 1
}

# ── Stop existing service if running ──
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[1/5] Stopping existing service..." -ForegroundColor Yellow
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    sc.exe delete $ServiceName | Out-Null
    Start-Sleep -Seconds 2
    Write-Host "       Old service removed."
}

# ── Stop any running proxy instances ──
Write-Host "[2/5] Stopping any running proxy instances..." -ForegroundColor Yellow
try {
    $proc = Get-Process -Name "privacy-guard" -ErrorAction SilentlyContinue
    if ($proc) { $proc | Stop-Process -Force }
} catch { }
Start-Sleep -Seconds 1
Write-Host "       Done."

# ── Install files ──
Write-Host "[3/5] Installing to $InstallDir..." -ForegroundColor Yellow
$null = New-Item -ItemType Directory -Force -Path $InstallDir
Copy-Item -Path "$PSScriptRoot\privacy-guard.exe" -Destination $ExePath -Force
Write-Host "       privacy-guard.exe installed."

# ── Register Windows Service ──
Write-Host "[4/5] Registering Windows Service..." -ForegroundColor Yellow

$args = "start --foreground"
if ($Port -ne 19999) { $args += " --port $Port" }
if ($Upstream) { $args += " --upstream `"$Upstream`"" }

# Create service — runs as LocalService (least privilege)
sc.exe create $ServiceName `
    binPath= "`"$ExePath`" $args" `
    start= "auto" `
    obj= "LocalService" `
    DisplayName= "LLM Privacy Guard" | Out-Null

# Configure recovery: restart on first/second/subsequent failures
sc.exe failure $ServiceName `
    reset= "86400" `
    actions= "restart/5000/restart/10000/restart/30000" | Out-Null

# Set description
sc.exe description $ServiceName "Local HTTP proxy that filters sensitive data from LLM API requests before they leave your machine." | Out-Null

Write-Host "       Service created."
Write-Host "       Recovery: auto-restart on failure (5s / 10s / 30s backoff)."
Write-Host "       Boot: auto-start on Windows login."

# ── Start the service ──
Write-Host "[5/5] Starting service..." -ForegroundColor Yellow
Start-Service -Name $ServiceName
Start-Sleep -Seconds 3

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq "Running") {
    Write-Host "       Service is running." -ForegroundColor Green
} else {
    Write-Host "       [WARN] Service may not have started. Check Event Viewer." -ForegroundColor Yellow
}

# ── Run setup ──
if (-not $NoSetup) {
    Write-Host ""
    Write-Host "Running privacy-guard setup to auto-configure your tools..." -ForegroundColor Cyan
    Write-Host ""
    & $ExePath setup --port $Port
}

# ── Done ──
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Installation complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Service:  $ServiceName"
Write-Host "  Port:     $Port"
Write-Host "  Location: $ExePath"
Write-Host ""
Write-Host "The proxy will auto-start on boot and restart if killed."
Write-Host "If Windows Defender flags it, add $InstallDir to exclusions."
Write-Host ""
Write-Host "To uninstall, run: uninstall.ps1 (as Administrator)"
Write-Host ""

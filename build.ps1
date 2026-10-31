#Requires -Version 5.1
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$VenvPip = Join-Path $Root ".venv\Scripts\pip.exe"
$DistDir = Join-Path $Root "dist"
$AppDir = Join-Path $DistDir "MacroRecorder"
$MsiPath = Join-Path $DistDir "MacroRecorder.msi"
$WxsPath = Join-Path $Root "packaging\Product.wxs"

function Assert-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name"
    }
}

Write-Host "==> Checking tools"
Assert-Command python
Assert-Command wix

if (-not (Test-Path $VenvPython)) {
    Write-Host "==> Creating .venv"
    python -m venv .venv
}

Write-Host "==> Installing dependencies"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r requirements.txt -r requirements-dev.txt

Write-Host "==> Cleaning previous build output"
if (Test-Path (Join-Path $Root "build")) {
    Remove-Item -Recurse -Force (Join-Path $Root "build")
}
if (Test-Path $AppDir) {
    Remove-Item -Recurse -Force $AppDir
}
if (Test-Path $MsiPath) {
    Remove-Item -Force $MsiPath
}

Write-Host "==> Freezing with PyInstaller"
& $VenvPython -m PyInstaller --noconfirm --clean macro-recorder.spec

$ExePath = Join-Path $AppDir "MacroRecorder.exe"
if (-not (Test-Path $ExePath)) {
    throw "PyInstaller did not produce $ExePath"
}

Write-Host "==> Building MSI with WiX"
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
& wix build $WxsPath -arch x64 -bindpath "App=$AppDir" -out $MsiPath

if (-not (Test-Path $MsiPath)) {
    throw "WiX did not produce $MsiPath"
}

Write-Host ""
Write-Host "Build succeeded."
Write-Host "  EXE folder: $AppDir"
Write-Host "  MSI:        $MsiPath"

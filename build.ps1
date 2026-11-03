#Requires -Version 5.1
param(
    [switch]$Publish
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$DistDir = Join-Path $Root "dist"
$AppDir = Join-Path $DistDir "MacroRecorder"
$MsiPath = Join-Path $DistDir "MacroRecorder.msi"
$WxsPath = Join-Path $Root "packaging\Product.wxs"

function Assert-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name"
    }
}

function Get-AppVersion {
    $raw = & $VenvPython -c "from version import APP_VERSION; print(APP_VERSION)"
    $version = ($raw | Select-Object -Last 1).ToString().Trim()
    if ($version -notmatch '^\d+\.\d+\.\d+') {
        throw "Invalid APP_VERSION: $version"
    }
    return $version
}

Write-Host "==> Checking tools"
Assert-Command python
Assert-Command wix
if ($Publish) {
    Assert-Command gh
}

if (-not (Test-Path $VenvPython)) {
    Write-Host "==> Creating .venv"
    python -m venv .venv
}

Write-Host "==> Installing dependencies"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r requirements.txt -r requirements-dev.txt

$ProductVersion = Get-AppVersion
Write-Host "==> Product version: $ProductVersion"

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
& wix build $WxsPath -arch x64 -d "ProductVersion=$ProductVersion" -bindpath "App=$AppDir" -out $MsiPath

if (-not (Test-Path $MsiPath)) {
    throw "WiX did not produce $MsiPath"
}

Write-Host ""
Write-Host "Build succeeded."
Write-Host "  EXE folder: $AppDir"
Write-Host "  MSI:        $MsiPath"

if ($Publish) {
    $tag = "v$ProductVersion"
    Write-Host "==> Publishing GitHub Release $tag"
    $releaseExists = $false
    & gh release view $tag --repo CodeBotD/macro-recorder 1>$null 2>$null
    if ($LASTEXITCODE -eq 0) {
        $releaseExists = $true
    }
    # PowerShell may treat gh stderr as a terminating error; clear and continue.
    $global:LASTEXITCODE = 0
    if ($releaseExists) {
        Write-Host "Release $tag already exists; uploading/replacing MSI asset"
        & gh release upload $tag $MsiPath --repo CodeBotD/macro-recorder --clobber
        if ($LASTEXITCODE -ne 0) {
            throw "GitHub release upload failed"
        }
    } else {
        & gh release create $tag $MsiPath --repo CodeBotD/macro-recorder --title $tag --generate-notes
        if ($LASTEXITCODE -ne 0) {
            throw "GitHub release create failed"
        }
    }
    Write-Host "Published $tag with MacroRecorder.msi"
}

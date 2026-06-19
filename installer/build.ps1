# Build script — called from CI, generates version metadata and packages the .exe
param(
    [string]$Version,
    [string]$Commit
)

$ErrorActionPreference = "Stop"

# Build 4-element file version: "2.1.1" -> (2, 1, 1, 0)
$filevers = "($($Version -replace '\.', ', '), 0)"

# Generate PyInstaller version file with proper Windows metadata.
# Without this, the .exe has no CompanyName / FileVersion / etc.,
# which makes SmartScreen significantly more suspicious.
@"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=$filevers,
    prodvers=$filevers,
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u"040904B0",
        [
          StringStruct(u"CompanyName", u"LLM Privacy Guard"),
          StringStruct(u"FileDescription", u"Local sensitive-data filter proxy"),
          StringStruct(u"FileVersion", u"$Version"),
          StringStruct(u"InternalName", u"privacy-guard"),
          StringStruct(u"LegalCopyright", u"Apache 2.0 — github.com/lenychang520/llm-privacy-guard"),
          StringStruct(u"OriginalFilename", u"privacy-guard.exe"),
          StringStruct(u"ProductName", u"LLM Privacy Guard"),
          StringStruct(u"ProductVersion", u"$Version"),
          StringStruct(u"BuildCommit", u"$Commit"),
        ]
      ),
    ]),
    VarFileInfo([VarStruct(u"Translation", [0x0409, 1200])]),
  ]
)
"@ | Out-File -Encoding utf8 version.txt

# Build
pyinstaller `
  --onefile `
  --noupx `
  --strip `
  --name privacy-guard `
  --console `
  --clean `
  --version-file version.txt `
  --add-data "privacy_engine;privacy_engine" `
  --hidden-import yaml `
  --exclude-module tkinter `
  --exclude-module unittest `
  --exclude-module test `
  --exclude-module setuptools `
  --exclude-module email `
  cli.py

if (-not (Test-Path dist\privacy-guard.exe)) {
    Write-Error "Build failed — no .exe produced"
    exit 1
}

# SHA256 checksum
$hash = (Get-FileHash -Algorithm SHA256 dist\privacy-guard.exe).Hash
"SHA256: $hash" | Out-File -Encoding utf8 dist\checksum.txt
Write-Host "SHA256: $hash"

# Package
$dist = "privacy-guard-v${Version}-windows"
$zip = "$dist.zip"

mkdir $dist
copy dist\privacy-guard.exe $dist\
copy dist\checksum.txt $dist\
copy installer\install.ps1 $dist\
copy installer\uninstall.ps1 $dist\
copy README.md $dist\README.txt

Compress-Archive -Path $dist\* -DestinationPath "$zip"

Write-Host "Packaged: $zip"

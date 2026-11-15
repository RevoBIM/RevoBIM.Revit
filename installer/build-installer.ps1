# Builds the Release DLL, then compiles the Inno Setup installer.
# Output: dist\RevoBIM-Setup-<version>.exe
# Usage:  powershell -ExecutionPolicy Bypass -File installer\build-installer.ps1
#         add -SkipBuild to reuse the existing Release DLL.
param([switch]$SkipBuild)

$ErrorActionPreference = 'Stop'
$root    = Split-Path -Parent $PSScriptRoot
$csproj  = Join-Path $root 'RevoBIM.Revit2024\RevoBIM.Revit2024.csproj'
$sln     = Join-Path $root 'RevoBIM.Revit2024.sln'

# Version comes from the .csproj so the installer and the DLL always match
[xml]$proj = Get-Content $csproj
$version = $proj.Project.PropertyGroup | Where-Object { $_.Version } |
           Select-Object -First 1 -ExpandProperty Version
if (-not $version) { throw "No <Version> found in $csproj" }

if (-not $SkipBuild) {
    dotnet build $sln -c Release
    if ($LASTEXITCODE -ne 0) { throw 'dotnet build failed' }
    # Note: the post-build copy to %AppData% warns (not fails) when Revit has the DLL open.
}

$dll = Join-Path $root 'RevoBIM.Revit2024\bin\Release\net48\RevoBIM.Revit2024.dll'
if (-not (Test-Path $dll)) { throw "Release DLL not found: $dll" }

$iscc = foreach ($v in '7', '6') {
    "${env:ProgramFiles(x86)}\Inno Setup $v\ISCC.exe"
    "$env:ProgramFiles\Inno Setup $v\ISCC.exe"
    "$env:LOCALAPPDATA\Programs\Inno Setup $v\ISCC.exe"
}
$iscc = $iscc | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw 'Inno Setup 6 or 7 not found. Install it from https://jrsoftware.org/isinfo.php' }

& $iscc "/DMyAppVersion=$version" (Join-Path $PSScriptRoot 'RevoBIM.iss')
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup compile failed' }

Write-Host "Installer built: $(Join-Path $root "dist\RevoBIM-Setup-$version.exe")"

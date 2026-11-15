# Builds the Release DLL for every Revit version, then compiles the Inno Setup installer.
# Output: dist\RevoBIM_Tools-<version>.exe  (installs Revit 2024, 2025, 2026 and 2027)
# Usage:  powershell -ExecutionPolicy Bypass -File installer\build-installer.ps1
#         add -SkipBuild to reuse the existing Release DLLs.
param([switch]$SkipBuild)

$ErrorActionPreference = 'Stop'
$root    = Split-Path -Parent $PSScriptRoot
$csproj  = Join-Path $root 'RevoBIM.Revit\RevoBIM.Revit.csproj'
$sln     = Join-Path $root 'RevoBIM.Revit.sln'

# Revit version -> build configuration and output folder (must match RevoBIM.iss)
$builds = [ordered]@{
    '2024' = @{ Config = 'Release R24'; Framework = 'net48' }
    '2025' = @{ Config = 'Release R25'; Framework = 'net8.0-windows' }
    '2026' = @{ Config = 'Release R26'; Framework = 'net8.0-windows' }
    '2027' = @{ Config = 'Release R27'; Framework = 'net10.0-windows' }
}

# Version comes from the .csproj so the installer and the DLLs always match
[xml]$proj = Get-Content $csproj
$version = $proj.Project.PropertyGroup | Where-Object { $_.Version } |
           Select-Object -First 1 -ExpandProperty Version
if (-not $version) { throw "No <Version> found in $csproj" }

foreach ($year in $builds.Keys) {
    $b = $builds[$year]
    if (-not $SkipBuild) {
        Write-Host "Building Revit $year ($($b.Config))"
        dotnet build $sln -c $b.Config
        if ($LASTEXITCODE -ne 0) { throw "dotnet build failed for Revit $year" }
        # Note: the post-build copy to %AppData% warns (not fails) when Revit has the DLL open.
    }
    $dll = Join-Path $root "RevoBIM.Revit\bin\$($b.Config)\$($b.Framework)\RevoBIM.Revit.dll"
    if (-not (Test-Path $dll)) { throw "Release DLL for Revit $year not found: $dll" }
}

# Installer artwork (icon + wizard images) from installer\make-assets.ps1
& (Join-Path $PSScriptRoot 'make-assets.ps1')
if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { throw 'make-assets.ps1 failed' }

$iscc = foreach ($v in '7', '6') {
    "${env:ProgramFiles(x86)}\Inno Setup $v\ISCC.exe"
    "$env:ProgramFiles\Inno Setup $v\ISCC.exe"
    "$env:LOCALAPPDATA\Programs\Inno Setup $v\ISCC.exe"
}
$iscc = $iscc | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw 'Inno Setup 6 or 7 not found. Install it from https://jrsoftware.org/isinfo.php' }

& $iscc "/DMyAppVersion=$version" (Join-Path $PSScriptRoot 'RevoBIM.iss')
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup compile failed' }

Write-Host "Installer built: $(Join-Path $root "dist\RevoBIM_Tools-$version.exe")"

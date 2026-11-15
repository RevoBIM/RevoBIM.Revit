<#
.SYNOPSIS
  Publishes RevoBIM.Arcade as one self-contained win-x64 exe.

.PARAMETER EggBin
  Where to copy the exe. Defaults to dist\egg-bin beside this solution. To feed the
  extension, pass its folder: -EggBin "<extension>\lib\revobim\egg\bin"
#>
param(
    [string]$EggBin
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $EggBin) { $EggBin = Join-Path $root 'dist\egg-bin' }

$proj = Join-Path $root 'RevoBIM.Arcade\RevoBIM.Arcade.csproj'
$out  = Join-Path $root 'publish'

dotnet publish $proj -c Release -r win-x64 --self-contained -p:PublishSingleFile=true -o $out
if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed ($LASTEXITCODE)" }

$exe = Join-Path $out 'RevoBIM.Arcade.exe'
if (-not (Test-Path $exe)) { throw "Expected $exe was not produced" }

New-Item -ItemType Directory -Force $EggBin | Out-Null
Copy-Item $exe (Join-Path $EggBin 'RevoBIM.Arcade.exe') -Force
$size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "Published RevoBIM.Arcade.exe ($size MB) -> $EggBin"

# Generates the installer artwork into installer\assets\:
#   revobim.ico, wizard-large*.bmp (left panel), wizard-small*.bmp (header logo)
#
# The mark is drawn in the RevoBIM palette (dark tile, blue / orange / green blocks).
# To use your own logo instead, put a square PNG at installer\assets\revobim-logo.png
# (transparent background, 512px or larger is best) and run the build again.
#
# NOTE: keep this file ASCII. Windows PowerShell 5.1 reads BOM-less UTF-8 as ANSI.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$assets = Join-Path $PSScriptRoot 'assets'
New-Item -ItemType Directory -Force -Path $assets | Out-Null
$customLogo = Join-Path $assets 'revobim-logo.png'
$custom = if (Test-Path $customLogo) { [System.Drawing.Image]::FromFile($customLogo) } else { $null }

function C([string]$hex) { [System.Drawing.ColorTranslator]::FromHtml($hex) }
$tile   = C '#1C1C1F'
$blue   = C '#4FA3E3'
$orange = C '#E8912D'
$green  = C '#3FA75A'

function New-RoundRect([float]$x, [float]$y, [float]$w, [float]$h, [float]$r) {
    $p = New-Object System.Drawing.Drawing2D.GraphicsPath
    $d = [Math]::Min($r * 2, [Math]::Min($w, $h))
    if ($d -le 0.01) { $p.AddRectangle((New-Object System.Drawing.RectangleF $x, $y, $w, $h)); return $p }
    $p.AddArc($x, $y, $d, $d, 180, 90)
    $p.AddArc($x + $w - $d, $y, $d, $d, 270, 90)
    $p.AddArc($x + $w - $d, $y + $h - $d, $d, $d, 0, 90)
    $p.AddArc($x, $y + $h - $d, $d, $d, 90, 90)
    $p.CloseFigure()
    $p
}

function Fill-RoundRect($g, $color, [float]$x, [float]$y, [float]$w, [float]$h, [float]$r) {
    $path = New-RoundRect $x $y $w $h $r
    $brush = New-Object System.Drawing.SolidBrush $color
    $g.FillPath($brush, $path)
    $brush.Dispose(); $path.Dispose()
}

# The RevoBIM mark in a square of side $size at ($x,$y). $square = no rounded tile corners.
function Draw-Mark($g, [float]$x, [float]$y, [float]$size, [bool]$square = $false) {
    if ($custom) {
        $g.DrawImage($custom, $x, $y, $size, $size)
        return
    }
    $u = $size / 109.0                       # logo grid: tile spans 109 units (9..118 of 128)
    $r = if ($square) { 0 } else { 24 * $u }
    Fill-RoundRect $g $tile $x $y $size $size $r
    $o = 9.0
    Fill-RoundRect $g $blue   ($x + (27 - $o) * $u) ($y + (32 - $o) * $u) (33 * $u) (65 * $u) (6 * $u)
    Fill-RoundRect $g $orange ($x + (68 - $o) * $u) ($y + (32 - $o) * $u) (33 * $u) (38 * $u) (6 * $u)
    Fill-RoundRect $g $green  ($x + (68 - $o) * $u) ($y + (78 - $o) * $u) (33 * $u) (19 * $u) (6 * $u)
}

function New-Canvas([int]$w, [int]$h, [bool]$transparent = $false) {
    $fmt = if ($transparent) { [System.Drawing.Imaging.PixelFormat]::Format32bppArgb } else { [System.Drawing.Imaging.PixelFormat]::Format24bppRgb }
    $bmp = New-Object System.Drawing.Bitmap $w, $h, $fmt
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = 'AntiAlias'
    $g.InterpolationMode = 'HighQualityBicubic'
    $g.PixelOffsetMode = 'HighQuality'
    $g.TextRenderingHint = 'AntiAliasGridFit'
    if ($transparent) { $g.Clear([System.Drawing.Color]::Transparent) }
    return @{ Bmp = $bmp; G = $g }
}

# ---- Icon (.ico with PNG frames) ------------------------------------------------
$master = New-Canvas 1024 1024 $true
Draw-Mark $master.G 0 0 1024
$sizes = 16, 24, 32, 48, 64, 128, 256
$frames = foreach ($s in $sizes) {
    $c = New-Canvas $s $s $true
    $c.G.DrawImage($master.Bmp, 0, 0, $s, $s)
    $ms = New-Object System.IO.MemoryStream
    $c.Bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
    [pscustomobject]@{ Size = $s; Bytes = $ms.ToArray() }
    $c.G.Dispose(); $c.Bmp.Dispose(); $ms.Dispose()
}
$icoPath = Join-Path $assets 'revobim.ico'
$fs = [System.IO.File]::Create($icoPath)
$bw = New-Object System.IO.BinaryWriter $fs
$bw.Write([uint16]0); $bw.Write([uint16]1); $bw.Write([uint16]$frames.Count)
$offset = 6 + 16 * $frames.Count
foreach ($f in $frames) {
    $dim = if ($f.Size -ge 256) { 0 } else { $f.Size }
    $bw.Write([byte]$dim); $bw.Write([byte]$dim); $bw.Write([byte]0); $bw.Write([byte]0)
    $bw.Write([uint16]1); $bw.Write([uint16]32)
    $bw.Write([uint32]$f.Bytes.Length); $bw.Write([uint32]$offset)
    $offset += $f.Bytes.Length
}
foreach ($f in $frames) { $bw.Write($f.Bytes) }
$bw.Close(); $fs.Close()
$master.G.Dispose(); $master.Bmp.Dispose()

# ---- Wizard left panel (164x314 at 100%) ---------------------------------------
function New-Panel([double]$s, [string]$path) {
    $w = [int](164 * $s); $h = [int](314 * $s)
    $c = New-Canvas $w $h
    $g = $c.G
    # background: subtle vertical gradient
    $rect = New-Object System.Drawing.Rectangle 0, 0, $w, $h
    $grad = New-Object System.Drawing.Drawing2D.LinearGradientBrush $rect, (C '#26262B'), (C '#151517'), 90
    $g.FillRectangle($grad, $rect); $grad.Dispose()
    # soft blue glow behind the mark
    $glowPath = New-Object System.Drawing.Drawing2D.GraphicsPath
    $glowPath.AddEllipse([float](-20 * $s), [float](10 * $s), [float](204 * $s), [float](170 * $s))
    $pgb = New-Object System.Drawing.Drawing2D.PathGradientBrush $glowPath
    $pgb.CenterColor = [System.Drawing.Color]::FromArgb(46, 79, 163, 227)
    $pgb.SurroundColors = @([System.Drawing.Color]::FromArgb(0, 79, 163, 227))
    $g.FillPath($pgb, $glowPath); $pgb.Dispose(); $glowPath.Dispose()

    $mark = 84 * $s
    Draw-Mark $g ([float]((164 * $s - $mark) / 2)) ([float](52 * $s)) ([float]$mark)

    $center = New-Object System.Drawing.StringFormat
    $center.Alignment = 'Center'
    $white = New-Object System.Drawing.SolidBrush (C '#F2F2F4')
    $grey  = New-Object System.Drawing.SolidBrush (C '#9A9AA3')
    $accent = New-Object System.Drawing.SolidBrush $blue
    $fWord = New-Object System.Drawing.Font 'Segoe UI Semibold', ([single](22 * $s)), ([System.Drawing.FontStyle]::Regular), ([System.Drawing.GraphicsUnit]::Pixel)
    $fSub  = New-Object System.Drawing.Font 'Segoe UI Semibold', ([single](11 * $s)), ([System.Drawing.FontStyle]::Regular), ([System.Drawing.GraphicsUnit]::Pixel)
    $fSmall = New-Object System.Drawing.Font 'Segoe UI', ([single](10 * $s)), ([System.Drawing.FontStyle]::Regular), ([System.Drawing.GraphicsUnit]::Pixel)
    $cx = [single](82 * $s)
    $g.DrawString('RevoBIM', $fWord, $white, $cx, [single](152 * $s), $center)
    $g.DrawString('T O O L S', $fSub, $accent, $cx, [single](184 * $s), $center)
    $g.DrawString('Add-in suite for', $fSmall, $grey, $cx, [single](232 * $s), $center)
    $g.DrawString('Autodesk Revit 2024-2027', $fSmall, $grey, $cx, [single](246 * $s), $center)
    $g.DrawString(('A' + [char]0x00B2 + ' Services LTD'), $fSmall, $grey, $cx, [single](280 * $s), $center)

    # tri-colour bar along the bottom
    $bh = [int](4 * $s); $seg = [int]($w / 3)
    foreach ($i in 0..2) {
        $col = @($blue, $orange, $green)[$i]
        $b = New-Object System.Drawing.SolidBrush $col
        $g.FillRectangle($b, $i * $seg, $h - $bh, $(if ($i -eq 2) { $w - 2 * $seg } else { $seg }), $bh)
        $b.Dispose()
    }
    $c.Bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Bmp)
    $g.Dispose(); $c.Bmp.Dispose()
}
New-Panel 1 (Join-Path $assets 'wizard-large.bmp')
New-Panel 2 (Join-Path $assets 'wizard-large-200.bmp')

# ---- Wizard header logo (55x55 at 100%) ----------------------------------------
function New-Small([int]$px, [string]$path) {
    $c = New-Canvas $px $px
    $c.G.Clear($tile)
    Draw-Mark $c.G 0 0 ([float]$px) $true
    $c.Bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Bmp)
    $c.G.Dispose(); $c.Bmp.Dispose()
}
New-Small 55  (Join-Path $assets 'wizard-small.bmp')
New-Small 110 (Join-Path $assets 'wizard-small-200.bmp')

# ---- Tool icons for the "What is included" page --------------------------------
# The wizard can only load BMP, so the ribbon PNGs are flattened onto the dark page colour.
$pageBg = C '#2B2B2B'
$resDir = Join-Path (Split-Path -Parent $PSScriptRoot) 'RevoBIM.Revit\Resources'
$toolIcons = [ordered]@{
    'icon_legend'    = 'LegendCreator'
    'icon_prosheets' = 'ProSheetsExporter'
    'icon_revision'  = 'RevisionManager'
}
foreach ($name in $toolIcons.Keys) {
    $src = Join-Path $resDir "$($toolIcons[$name])\icon.png"
    if (-not (Test-Path $src)) { Write-Warning "Missing tool icon: $src"; continue }
    $img = [System.Drawing.Image]::FromFile($src)
    $c = New-Canvas 96 96
    $c.G.Clear($pageBg)
    $c.G.DrawImage($img, 0, 0, 96, 96)
    $c.Bmp.Save((Join-Path $assets "$name.bmp"), [System.Drawing.Imaging.ImageFormat]::Bmp)
    $c.G.Dispose(); $c.Bmp.Dispose(); $img.Dispose()
}

if ($custom) { $custom.Dispose() }
Write-Host "Installer artwork written to $assets"

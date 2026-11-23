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
    $g.DrawString('RevoBIM LTD', $fSmall, $grey, $cx, [single](280 * $s), $center)

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

# The list comes from installer\tools.txt (Group|Icon|Name|Description, in display order).
# Written out for RevoBIM.iss: assets\tools.rtf (the list the wizard page shows) and
# assets\tools_files.inc (its [Files] line).
$manifest = Join-Path $PSScriptRoot 'tools.txt'
$tools = @()
foreach ($line in [System.IO.File]::ReadAllLines($manifest, [System.Text.Encoding]::UTF8)) {
    $t = $line.Trim()
    if ($t -eq '' -or $t.StartsWith('#')) { continue }
    $p = $t.Split('|')
    if ($p.Count -lt 4) { throw "tools.txt: expected Group|Icon|Name|Description, got: $t" }
    $tools += [pscustomobject]@{ Group = $p[0].Trim(); Icon = $p[1].Trim(); Name = $p[2].Trim(); Desc = ($p[3..($p.Count - 1)] -join '|').Trim() }
}

# The list is one RTF document shown in a scrolling rich-edit control on the wizard page:
# a heading per group, then a borderless table row per tool (icon left, name and description
# right). Icons are embedded as 48px bitmaps flattened onto the page colour.
function Rtf-Escape([string]$s) { $s.Replace('\', '\\').Replace('{', '\{').Replace('}', '\}') }
function Rtf-Colour([string]$hex) { $c = C $hex; "\red$($c.R)\green$($c.G)\blue$($c.B);" }
function Png-Hex([string]$iconDir) {
    $src = Join-Path $resDir "$iconDir\icon.png"
    if (-not (Test-Path $src)) { throw "Missing tool icon: $src" }
    $img = [System.Drawing.Image]::FromFile($src)
    $c = New-Canvas 48 48
    $c.G.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $c.G.Clear($pageBg)
    $c.G.DrawImage($img, 0, 0, 48, 48)
    # a DIB (a BMP without its 14 byte file header): RichEdit shows \dibitmap, not \pngblip
    $ms = New-Object System.IO.MemoryStream
    $c.Bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Bmp)
    $bytes = $ms.ToArray()
    $c.G.Dispose(); $c.Bmp.Dispose(); $img.Dispose(); $ms.Dispose()
    $sb = New-Object System.Text.StringBuilder
    for ($i = 14; $i -lt $bytes.Length; $i++) { [void]$sb.Append($bytes[$i].ToString('x2')) }
    $sb.ToString()
}

# colour table: 1 text, 2 muted, 3-5 group accents (blue, orange, green)
$rtf = New-Object System.Text.StringBuilder
[void]$rtf.Append('{\rtf1\ansi\deff0{\fonttbl{\f0\fnil\fcharset0 Segoe UI;}}')
[void]$rtf.Append('{\colortbl;' + (Rtf-Colour '#F2F2F2') + (Rtf-Colour '#A3A39A') + (Rtf-Colour '#4FA3E3') + (Rtf-Colour '#E8912D') + (Rtf-Colour '#3FA75A') + '}')
[void]$rtf.Append('\viewkind4\uc1\f0\fs18\cf1' + "`r`n")
$hex = @{}
$group = $null; $gi = 2
foreach ($t in $tools) {
    if (-not $hex.ContainsKey($t.Icon)) { $hex[$t.Icon] = Png-Hex $t.Icon }
    if ($t.Group -ne $group) {
        $group = $t.Group; $gi++
        $accent = 3 + (($gi - 3) % 3)
        [void]$rtf.Append('\pard\sb280\sa100\li60\cf' + $accent + '\b\fs18 ' + (Rtf-Escape $t.Group.ToUpper()) + '\b0\cf1\par' + "`r`n")
    }
    # One paragraph per tool with a hanging indent: the icon sits in the margin, then a tab to the
    # text; the description wraps onto a second line under the name. (A table would be neater, but
    # RichEdit draws gridlines on it that cannot be switched off.)
    [void]$rtf.Append('\pard\li660\fi-600\tx660\sb30\sa30 {\pict\dibitmap0\picw1270\pich1270\picwgoal360\pichgoal360 ' + $hex[$t.Icon] + '}\tab\b\fs19\cf1\up6 ' + (Rtf-Escape $t.Name) + '\b0\up0\line\fs16\cf2 ' + (Rtf-Escape $t.Desc) + '\cf1\fs18\par' + "`r`n")
}[void]$rtf.Append('}')
$enc = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText((Join-Path $assets 'tools.rtf'), $rtf.ToString(), $enc)
[System.IO.File]::WriteAllText((Join-Path $assets 'tools_files.inc'), "Source: `"assets\tools.rtf`"; Flags: dontcopy`r`n", $enc)

# The keyboard shortcuts the installer offers to set come from installer\shortcuts.txt
# (Keys|Panel|Button|Name). Written out as assets\shortcuts.inc, a preprocessor define holding the list
# for the wizard's task page and summary, so it is never typed twice.
$pairs = @()
foreach ($line in [System.IO.File]::ReadAllLines((Join-Path $PSScriptRoot 'shortcuts.txt'), [System.Text.Encoding]::UTF8)) {
    $t = $line.Trim()
    if ($t -eq '' -or $t.StartsWith('#')) { continue }
    $p = $t.Split('|')
    if ($p.Count -lt 4) { throw "shortcuts.txt: expected Keys|Panel|Button|Name, got: $t" }
    $pairs += ($p[0].Trim() + ' ' + (($p[3..($p.Count - 1)] -join '|').Trim().Replace('\n', ' ')))
}
[System.IO.File]::WriteAllText((Join-Path $assets 'shortcuts.inc'), "#define ShortcutList `"" + ($pairs -join ', ') + "`"`r`n", $enc)
# The same list as a table for the Select Tasks page: two columns, Shortcut (bold) and Tool.
$rows = @()
foreach ($line in [System.IO.File]::ReadAllLines((Join-Path $PSScriptRoot 'shortcuts.txt'), [System.Text.Encoding]::UTF8)) {
    $t = $line.Trim()
    if ($t -eq '' -or $t.StartsWith('#')) { continue }
    $p = $t.Split('|')
    $rows += [pscustomobject]@{ Keys = $p[0].Trim(); Name = (($p[3..($p.Count - 1)] -join '|').Trim().Replace('\n', ' ')) }
}
$border = '\clbrdrt\brdrs\brdrw10\brdrcf2\clbrdrl\brdrs\brdrw10\brdrcf2\clbrdrb\brdrs\brdrw10\brdrcf2\clbrdrr\brdrs\brdrw10\brdrcf2'
$def = '\trowd\trgaph90\trleft0' + $border + '\cellx1100' + $border + '\cellx5600'
$s = New-Object System.Text.StringBuilder
[void]$s.Append('{\rtf1\ansi\deff0{\fonttbl{\f0\fnil\fcharset0 Segoe UI;}}')
[void]$s.Append('{\colortbl;' + (Rtf-Colour '#F2F2F2') + (Rtf-Colour '#6A6A70') + (Rtf-Colour '#E8912D') + '}')
[void]$s.Append('\viewkind4\uc1\f0\fs18\cf1' + "`r`n")
[void]$s.Append($def + '\intbl\b\cf3 Shortcut\cell Tool\cell\b0\cf1\row' + "`r`n")
foreach ($r in $rows) {
    [void]$s.Append($def + '\intbl\b\cf1 ' + (Rtf-Escape $r.Keys) + '\b0\cell ' + (Rtf-Escape $r.Name) + '\cell\row' + "`r`n")
}
[void]$s.Append('}')
[System.IO.File]::WriteAllText((Join-Path $assets 'shortcuts.rtf'), $s.ToString(), $enc)
if ($custom) { $custom.Dispose() }
Write-Host "Installer artwork written to $assets"

# Build the Microsoft Store package (dist\Talkative-<version>.msix) from
# the public source: folder build of the app + store\AppxManifest.xml +
# logos drawn by store\make_assets.py, packed with makeappx (Windows SDK;
# preinstalled on GitHub's windows-latest runners).
#
# The package is NOT signed: the Store signs it after certification. For a
# local test without the SDK or a certificate, use -LayoutOnly and register
# the folder (needs Windows "Developer Mode" on, which the user turns on):
#     .\scripts\build_msix.ps1 -LayoutOnly
#     Add-AppxPackage -Register build\msix\layout\AppxManifest.xml
# and remove it afterwards with Remove-AppxPackage (Get-AppxPackage *Talkative*).
#
# The identity values come from Partner Center > the app > Product
# identity, and must match it exactly. The defaults are placeholders that
# only work for -LayoutOnly tests on this PC.
#
# Usage (PowerShell, project root):
#   .\scripts\build_msix.ps1 [-Python <path>] [-LayoutOnly] [-SkipAppBuild]
#       [-IdentityName <Package/Identity/Name>] [-Publisher <CN=...>]
#       [-PublisherDisplayName <name>] [-DisplayName <Store name>]

param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [switch]$LayoutOnly,
    [switch]$SkipAppBuild,
    [string]$IdentityName = "SumitDas.Talkative.LocalTest",
    [string]$Publisher = "CN=Talkative Local Test",
    [string]$PublisherDisplayName = "Sumit Das",
    [string]$DisplayName = "Talkative"
)

$ErrorActionPreference = "Stop"

$version = (Select-String -Path talkative\__init__.py -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
# Store versions have four parts and the last must be 0.
$msixVersion = "$version.0"
Write-Host "Talkative $version -> package version $msixVersion"

if (-not $SkipAppBuild) {
    & .\scripts\build_exe.ps1 -Python $Python -OneDir
}
$app = "dist\store\Talkative"
if (-not (Test-Path "$app\Talkative.exe")) { throw "$app\Talkative.exe not found -- build failed?" }

$layout = "build\msix\layout"
if (Test-Path $layout) { Remove-Item -Recurse -Force $layout }
New-Item -ItemType Directory -Force $layout | Out-Null
Copy-Item -Recurse "$app\*" $layout

& $Python store\make_assets.py "$layout\Assets"
if ($LASTEXITCODE -ne 0) { throw "make_assets.py failed" }

function Escape-Xml([string]$s) { [System.Security.SecurityElement]::Escape($s) }
$manifest = Get-Content store\AppxManifest.xml -Raw -Encoding UTF8
$manifest = $manifest.Replace("{{IDENTITY_NAME}}", (Escape-Xml $IdentityName)).
    Replace("{{PUBLISHER}}", (Escape-Xml $Publisher)).
    Replace("{{PUBLISHER_DISPLAY_NAME}}", (Escape-Xml $PublisherDisplayName)).
    Replace("{{DISPLAY_NAME}}", (Escape-Xml $DisplayName)).
    Replace("{{VERSION}}", $msixVersion)
if ($manifest -match "\{\{[A-Z_]+\}\}") { throw "AppxManifest.xml still has an unfilled {{...}} value" }
[System.IO.File]::WriteAllText((Join-Path (Resolve-Path $layout) "AppxManifest.xml"), $manifest, (New-Object System.Text.UTF8Encoding $false))
$null = [xml]$manifest   # throws if the filled manifest isn't valid XML

if ($LayoutOnly) {
    Write-Host "Layout ready: $layout (register with Add-AppxPackage -Register $layout\AppxManifest.xml)"
    return
}

$makeappx = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\makeappx.exe" -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending | Select-Object -First 1
if (-not $makeappx) { throw "makeappx.exe not found: install the Windows SDK, or use -LayoutOnly" }

$out = "dist\Talkative-$version.msix"
& $makeappx.FullName pack /o /d $layout /p $out
if ($LASTEXITCODE -ne 0) { throw "makeappx failed (exit $LASTEXITCODE)" }
Write-Host "Built $out (unsigned; the Store signs it)"

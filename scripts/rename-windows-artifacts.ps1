# Rename Cargo output artifacts to BGDesk names on Windows.
# Usage: .\scripts\rename-windows-artifacts.ps1 [-TargetTriple x86_64-pc-windows-msvc]

param(
    [string]$TargetTriple = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$dirs = @()
if ($TargetTriple) {
    $dirs += Join-Path $Root "target\$TargetTriple\release"
}
$dirs += Join-Path $Root "target\release"

function Rename-IfExists($dir, $from, $to) {
    $src = Join-Path $dir $from
    $dst = Join-Path $dir $to
    if (Test-Path $src) {
        # remove the original file if it exists
        if (Test-Path $dst) {
            Remove-Item -Force $dst
        }
        Move-Item -Force $src $dst
        Write-Host "[rename-windows-artifacts] $src -> $dst"
    }
}

foreach ($dir in $dirs) {
    if (-not (Test-Path $dir)) { continue }
    Rename-IfExists $dir "rustdesk.exe" "bgdesk.exe"
    Rename-IfExists $dir "librustdesk.dll" "libbgdesk.dll"
}

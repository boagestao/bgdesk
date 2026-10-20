param([Parameter(Mandatory=$true)][string]$Path)
$ErrorActionPreference = 'Stop'
python "$PSScriptRoot/sign-windows.py" $Path
if ($LASTEXITCODE -ne 0) { throw 'Windows signing failed; see the named phase above' }

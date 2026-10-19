param([Parameter(Mandatory=$true)][string]$Path)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot/../..").Path
$signTool = Get-ChildItem "${env:ProgramFiles(x86)}/Windows Kits/10/bin/*/x64/signtool.exe" |
    Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
if (!$signTool) { throw 'Windows SDK signtool.exe not found' }
$pfx = Join-Path $env:RUNNER_TEMP 'bgdesk-windows-signing.pfx'
$env:BGDESK_PFX_PASSWORD = [guid]::NewGuid().ToString('N')
try {
    & openssl pkcs12 -export -in "$root/config/certs/sign.crt" -inkey "$root/config/certs/sign.key" `
        -out $pfx -passout env:BGDESK_PFX_PASSWORD
    if ($LASTEXITCODE -ne 0) { throw 'Cannot export Windows code signing certificate' }
    & $signTool sign /fd SHA256 /f $pfx /p $env:BGDESK_PFX_PASSWORD `
        /tr http://timestamp.digicert.com /td SHA256 $Path
    if ($LASTEXITCODE -ne 0) { throw 'Windows code signing failed' }
    # The existing installer trusts this private CA. Import only on the disposable runner.
    Import-Certificate -FilePath "$root/config/certs/ca.crt" -CertStoreLocation Cert:/CurrentUser/Root | Out-Null
    & $signTool verify /pa /all $Path
    if ($LASTEXITCODE -ne 0) { throw 'Windows signature verification failed' }
} finally {
    Remove-Item $pfx -Force -ErrorAction SilentlyContinue
    Remove-Item Env:BGDESK_PFX_PASSWORD -ErrorAction SilentlyContinue
}

# Assina um executável com o certificado de assinatura de código do Nexo (usado pelo GitHub Actions).
#   $env:PFX       — certificado .pfx em base64
#   $env:PFX_PASS  — palavra-passe do .pfx
# Uso: ./packaging/windows/sign.ps1 caminho\para\Nexo.exe
param([Parameter(Mandatory = $true)][string]$File)
$ErrorActionPreference = "Stop"
if (-not $env:PFX) { Write-Host "Sem certificado (PFX): $File fica sem assinatura."; exit 0 }
$pfx = Join-Path $env:RUNNER_TEMP "nexo-sign.pfx"
[IO.File]::WriteAllBytes($pfx, [Convert]::FromBase64String($env:PFX))
try {
    $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" |
        Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $signtool) { throw "signtool.exe não encontrado (Windows SDK)." }
    & $signtool.FullName sign /f $pfx /p $env:PFX_PASS /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 `
        /d "Nexo" $File
    if ($LASTEXITCODE -ne 0) { throw "signtool falhou ($LASTEXITCODE)" }
    & $signtool.FullName verify /pa $File
} finally {
    Remove-Item $pfx -Force -ErrorAction SilentlyContinue
}

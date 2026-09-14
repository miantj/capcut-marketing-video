param([int]$Port = 8766, [string]$ListenAddress = '0.0.0.0')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonExecutable = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) { $pythonExecutable = (Get-Command python).Source }
if (-not $env:VIDEO_SKILL_DIR) {
    $siblingSkill = Join-Path (Split-Path -Path $PSScriptRoot -Parent) 'capcut-marketing-video'
    if (Test-Path -LiteralPath (Join-Path $siblingSkill 'scripts')) { $env:VIDEO_SKILL_DIR = $siblingSkill }
}
Write-Output "Video workspace: http://localhost:$Port"
[System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) | Where-Object { $_.AddressFamily -eq 'InterNetwork' -and $_.IPAddressToString -notlike '127.*' -and $_.IPAddressToString -notlike '169.254.*' } | ForEach-Object { Write-Output "LAN candidate: http://$($_.IPAddressToString):$Port" }
# Browser preview/cover requests stay open; without a timeout uvicorn waits forever on Ctrl+C.
& $pythonExecutable -m uvicorn workbench.app:app --host $ListenAddress --port $Port --workers 1 --timeout-graceful-shutdown 3

$initialDir = Get-Location
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$projectRoot = (Resolve-Path (Join-Path $scriptDir "..\..\..")).Path
Set-Location $projectRoot

Write-Host "Starting QQ Adapter..."
$pythonExe = Resolve-Path (Join-Path $projectRoot "venv_cpu\Scripts\python.exe") -ErrorAction SilentlyContinue
if (-not $pythonExe) {
    $pythonExe = Resolve-Path (Join-Path $projectRoot "venv_core\Scripts\python.exe") -ErrorAction SilentlyContinue
}
if (-not $pythonExe) {
    Write-Error "Neither venv_cpu nor venv_core Python was found under $projectRoot"
    Set-Location $initialDir
    exit 1
}

Write-Host "QQ Adapter Python: $($pythonExe.Path)"
& $pythonExe.Path (Join-Path $projectRoot "clients\bots\multi_qq_adapter.py")

Set-Location $initialDir

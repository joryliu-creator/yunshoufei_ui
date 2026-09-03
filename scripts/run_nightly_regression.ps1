$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "未找到虚拟环境 Python：$python"
}

$logDirectory = Join-Path $projectRoot "artifacts\scheduler-logs"
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = Join-Path $logDirectory "nightly-$stamp.log"

& $python "scripts\run_jenkins_regression.py" `
    --test-env standard1 `
    --customer-id 93537 `
    --account-role default `
    --max-minutes 0 *>&1 | Tee-Object -FilePath $logPath

$exitCode = $LASTEXITCODE
Write-Host "日志：$logPath"
Write-Host "HTML 报告：$projectRoot\artifacts\jenkins-regression-report.html"
exit $exitCode

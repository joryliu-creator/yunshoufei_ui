param(
    [string]$TestEnv = "standard1",
    [string]$CustomerId = "93537",
    [string]$AccountRole = "default"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# Bill cleanup switches are required by the unified runner.
$env:ALLOW_BILL_CREATION = "true"
$env:CLEANUP_CREATED_BILL = "true"
$env:ALLOW_BILL_DELETION = "true"

# Charge-standard专项只允许创建/删除AT-前缀记录。
$env:ALLOW_CHARGE_STANDARD_CREATION = "true"
$env:CLEANUP_CREATED_CHARGE_STANDARDS = "true"
$env:ALLOW_CHARGE_STANDARD_DELETION = "true"

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "未找到虚拟环境，请先执行 .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
}

& $python scripts\run_jenkins_regression.py `
    --test-env $TestEnv `
    --customer-id $CustomerId `
    --account-role $AccountRole `
    --max-minutes 0 `
    --junit
$exitCode = $LASTEXITCODE

if ($exitCode -eq 0) {
    & $python -m pytest tests\billing\test_charge_standard_lifecycle.py `
        --test-env $TestEnv --customer-id $CustomerId --account-role $AccountRole `
        --junitxml artifacts\charge-standard-junit.xml
    if ($LASTEXITCODE -ne 0) { $exitCode = $LASTEXITCODE }
}

Write-Host "报告目录: $root\artifacts"
Write-Host "出账回归报告: $root\artifacts\jenkins-regression-report.html"
Write-Host "收费标准专项报告: $root\artifacts\charge-standard-junit.xml"
exit $exitCode

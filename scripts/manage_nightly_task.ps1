param(
    [ValidateSet("install", "enable", "disable", "remove", "run", "status")]
    [string]$Action = "status",
    [ValidatePattern("^([01][0-9]|2[0-3]):[0-5][0-9]$")]
    [string]$Time = "23:00",
    [string]$TaskName = "CloudBilling-UI-Nightly-Regression"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $projectRoot "scripts\run_nightly_regression.ps1"
$powerShellExecutable = Join-Path $PSHOME "powershell.exe"

if (-not (Test-Path -LiteralPath $runner)) {
    throw "未找到夜间执行脚本：$runner"
}

switch ($Action) {
    "install" {
        $at = [datetime]::ParseExact($Time, "HH:mm", $null)
        $actionArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$runner`""
        $taskAction = New-ScheduledTaskAction -Execute $powerShellExecutable -Argument $actionArgs
        $taskTrigger = New-ScheduledTaskTrigger -Daily -At $at
        $principal = New-ScheduledTaskPrincipal `
            -UserId "$env:USERDOMAIN\$env:USERNAME" `
            -LogonType Interactive `
            -RunLevel Limited
        Register-ScheduledTask `
            -TaskName $TaskName `
            -Action $taskAction `
            -Trigger $taskTrigger `
            -Principal $principal `
            -Description "云收费 UI 自动化夜间回归（含账单清理和 HTML 报告）" `
            -Force | Out-Null
        Enable-ScheduledTask -TaskName $TaskName | Out-Null
        Write-Host "已创建并启用任务：$TaskName，每天 $Time 运行。"
    }
    "enable" {
        Enable-ScheduledTask -TaskName $TaskName | Out-Null
        Write-Host "已启用任务：$TaskName"
    }
    "disable" {
        Disable-ScheduledTask -TaskName $TaskName | Out-Null
        Write-Host "已暂停任务：$TaskName"
    }
    "remove" {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "已删除任务：$TaskName"
    }
    "run" {
        Start-ScheduledTask -TaskName $TaskName
        Write-Host "已立即启动任务：$TaskName"
    }
    "status" {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if (-not $task) {
            Write-Host "任务不存在：$TaskName"
            exit 1
        }
        $info = Get-ScheduledTaskInfo -TaskName $TaskName
        [pscustomobject]@{
            TaskName = $task.TaskName
            State = $task.State
            LastRunTime = $info.LastRunTime
            LastTaskResult = $info.LastTaskResult
            NextRunTime = $info.NextRunTime
        } | Format-List
    }
}

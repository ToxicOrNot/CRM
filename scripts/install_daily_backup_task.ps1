$ErrorActionPreference = "Stop"

$TaskName = "CRM Daily Backup"
$BackupScript = (Resolve-Path (Join-Path $PSScriptRoot "run_daily_backup.ps1")).Path

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$BackupScript`""

$Trigger = New-ScheduledTaskTrigger -Daily -At "21:58"
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Daily CRM orders and clients backup." `
    -Force | Out-Null

Write-Host "Scheduled task '$TaskName' installed. It will run daily at 21:58."
Write-Host "Backup script: $BackupScript"

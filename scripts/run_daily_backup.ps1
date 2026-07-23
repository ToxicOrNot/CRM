$ErrorActionPreference = "Stop"

$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackupDir = Join-Path $ProjectDir "backups"
$LogFile = Join-Path $BackupDir "scheduled_backup.log"
$DockerDesktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

function Write-BackupLog {
    param([string] $Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$timestamp] $Message" | Out-File -FilePath $LogFile -Append -Encoding utf8
}

Set-Location $ProjectDir
Write-BackupLog "Starting scheduled CRM backup."

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-BackupLog "Docker CLI was not found in PATH."
    exit 1
}

docker info *> $null
if ($LASTEXITCODE -ne 0 -and (Test-Path $DockerDesktop)) {
    Write-BackupLog "Starting Docker Desktop."
    Start-Process -FilePath $DockerDesktop -WindowStyle Hidden
}

$dockerReady = $false
for ($attempt = 1; $attempt -le 90; $attempt++) {
    docker info *> $null
    if ($LASTEXITCODE -eq 0) {
        $dockerReady = $true
        break
    }
    Start-Sleep -Seconds 2
}

if (-not $dockerReady) {
    Write-BackupLog "Docker did not become ready in time."
    exit 1
}

Write-BackupLog "Docker is ready. Starting CRM containers if needed."
cmd.exe /c "docker compose up -d >> `"$LogFile`" 2>&1"
if ($LASTEXITCODE -ne 0) {
    Write-BackupLog "docker compose up -d failed."
    exit 1
}

Write-BackupLog "Running Django backup command."
cmd.exe /c "docker compose exec -T web python manage.py backup_crm_data --format both >> `"$LogFile`" 2>&1"
if ($LASTEXITCODE -ne 0) {
    Write-BackupLog "backup_crm_data failed."
    exit 1
}

Write-BackupLog "CRM backup finished successfully."

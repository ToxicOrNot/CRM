@echo off
setlocal

set "PROJECT_DIR=%USERPROFILE%\PycharmProjects\CRM"
set "LOG_FILE=%PROJECT_DIR%\crm_startup.log"
set "DOCKER_DESKTOP=%ProgramFiles%\Docker\Docker\Docker Desktop.exe"

if not exist "%PROJECT_DIR%\compose.yaml" (
    echo [%date% %time%] CRM project not found: %PROJECT_DIR% >> "%TEMP%\crm_startup_error.log"
    exit /b 1
)

cd /d "%PROJECT_DIR%"

echo [%date% %time%] Starting CRM startup script. >> "%LOG_FILE%"

where docker >nul 2>nul
if errorlevel 1 (
    echo [%date% %time%] Docker CLI was not found in PATH. >> "%LOG_FILE%"
    exit /b 1
)

docker info >nul 2>nul
if errorlevel 1 (
    if exist "%DOCKER_DESKTOP%" (
        echo [%date% %time%] Starting Docker Desktop. >> "%LOG_FILE%"
        start "" "%DOCKER_DESKTOP%"
    )
)

set /a ATTEMPT=0
:wait_docker
docker info >nul 2>nul
if not errorlevel 1 goto docker_ready

set /a ATTEMPT+=1
if %ATTEMPT% GEQ 90 (
    echo [%date% %time%] Docker did not become ready in time. >> "%LOG_FILE%"
    exit /b 1
)

timeout /t 2 /nobreak >nul
goto wait_docker

:docker_ready
echo [%date% %time%] Docker is ready. Running docker compose up -d. >> "%LOG_FILE%"
docker compose up -d >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo [%date% %time%] docker compose up -d failed. >> "%LOG_FILE%"
    exit /b 1
)

echo [%date% %time%] CRM started: http://localhost:8000/ >> "%LOG_FILE%"
endlocal

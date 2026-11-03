@echo off
setlocal enabledelayedexpansion

REM Fin-News Launcher for Windows

set "SCRIPT_DIR=%~dp0"
set "CLI_PATH=%SCRIPT_DIR%core\cli.py"

REM 1. Check for standard python >= 3.11
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    python "%CLI_PATH%" %*
    exit /b %ERRORLEVEL%
)

REM 2. Check for uv
where uv >nul 2>&1
if %ERRORLEVEL% equ 0 (
    uv run python "%CLI_PATH%" %*
    exit /b %ERRORLEVEL%
)

REM 3. Ask user before installing uv (never silent)
echo Python 3.11+ or uv was not found on your system.
set /p "INSTALL_UV=Would you like to install uv to your user directory (no admin required)? (Y/N): "
if /i not "!INSTALL_UV!"=="Y" (
    echo Installation cancelled. Please install Python 3.11+ or uv manually: https://astral.sh/uv
    exit /b 1
)

echo Installing uv...
powershell -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
if %ERRORLEVEL% neq 0 (
    echo Failed to install uv.
    exit /b 1
)

set "PATH=%USERPROFILE%\.local\bin;%PATH%"
echo Installing Python 3.12 via uv...
uv python install 3.12
if %ERRORLEVEL% neq 0 (
    echo Failed to install Python 3.12.
    exit /b 1
)

uv run python "%CLI_PATH%" %*
exit /b %ERRORLEVEL%

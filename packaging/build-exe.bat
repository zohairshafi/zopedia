@echo off
REM Build Zopedia Windows executable and NSIS installer.
REM Prerequisites:
REM   pip install pyinstaller pystray pillow platformdirs
REM   Install NSIS (https://nsis.sourceforge.io/) and add makensis to PATH
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."
set "DIST_DIR=%PROJECT_DIR%\dist"
set "APP_NAME=Zopedia"
set "APP_VERSION=1.0.0"

cd /d "%PROJECT_DIR%"

echo ==^> Installing packaging dependencies...
pip install -q pyinstaller pystray pillow platformdirs

echo ==^> Building frontend...
cd frontend
call npm run build
cd ..

echo ==^> Running PyInstaller...
if exist "%DIST_DIR%\%APP_NAME%" rmdir /s /q "%DIST_DIR%\%APP_NAME%"
pyinstaller --clean packaging\Zopedia.spec

echo ==^> Building NSIS installer...
if exist "%DIST_DIR%\%APP_NAME%-Setup-%APP_VERSION%.exe" del "%DIST_DIR%\%APP_NAME%-Setup-%APP_VERSION%.exe"

makensis /V2 ^
    /DPRODUCT_NAME="Zopedia" ^
    /DPRODUCT_VERSION="%APP_VERSION%" ^
    /DPRODUCT_PUBLISHER="Zopedia" ^
    /DSOURCE_DIR="%DIST_DIR%\%APP_NAME%" ^
    /DOUTPUT_DIR="%DIST_DIR%" ^
    packaging\Zopedia.nsi

if %ERRORLEVEL% EQU 0 (
    echo ==^> Done: %DIST_DIR%\%APP_NAME%-Setup-%APP_VERSION%.exe
) else (
    echo ==^> NSIS not available, skipping installer. PyInstaller output is in %DIST_DIR%\%APP_NAME%\
)

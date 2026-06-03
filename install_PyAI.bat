@echo off
setlocal

set "SOURCE=%~dp0"
set "INSTALL_DIR=%LOCALAPPDATA%\PyAI"
set "STARTUP_LINK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\PyAI.lnk"

if not exist "%SOURCE%PyAI.exe" (
    echo PyAI.exe not found next to this installer.
    pause
    exit /b 1
)

taskkill /IM PyAI.exe /F >nul 2>nul

mkdir "%INSTALL_DIR%" >nul 2>nul
mkdir "%INSTALL_DIR%\assets" >nul 2>nul

copy /Y "%SOURCE%PyAI.exe" "%INSTALL_DIR%\PyAI.exe" >nul
copy /Y "%SOURCE%uninstall_PyAI.bat" "%INSTALL_DIR%\uninstall_PyAI.bat" >nul 2>nul
copy /Y "%SOURCE%assets\logo.png" "%INSTALL_DIR%\assets\logo.png" >nul 2>nul

if exist "%SOURCE%.env" (
    copy /Y "%SOURCE%.env" "%INSTALL_DIR%\.env" >nul
) else (
    if not exist "%INSTALL_DIR%\.env" (
        copy /Y "%SOURCE%.env.example" "%INSTALL_DIR%\.env.example" >nul 2>nul
    )
)

attrib +h +s "%INSTALL_DIR%" >nul 2>nul
attrib +h +s "%SOURCE%" >nul 2>nul
for %%I in ("%SOURCE%..") do if /I "%%~nxI"=="PyAI" attrib +h +s "%%~fI" >nul 2>nul

powershell -NoProfile -ExecutionPolicy Bypass -Command "$startup=[Environment]::GetFolderPath('Startup'); $shortcut=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $startup 'PyAI.lnk')); $shortcut.TargetPath='%INSTALL_DIR%\PyAI.exe'; $shortcut.WorkingDirectory='%INSTALL_DIR%'; $shortcut.Save()" >nul 2>nul

start "" "%INSTALL_DIR%\PyAI.exe"

echo PyAI installed and started.
echo Installed folder: %INSTALL_DIR%
exit /b 0

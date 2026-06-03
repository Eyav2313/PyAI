@echo off
setlocal

set "APPDIR=%~dp0"
set "INSTALL_DIR=%LOCALAPPDATA%\PyAI"
set "STARTUP_LINK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\PyAI.lnk"

if /I not "%~1"=="/quiet" (
    echo This will stop PyAI and remove only PyAI app files:
    echo %INSTALL_DIR%
    echo %APPDIR%
    echo.
    echo It will not delete your VS Code project files.
    choice /C YN /N /M "Continue? [Y/N] "
    if errorlevel 2 exit /b
)

taskkill /IM PyAI.exe /T /F >nul 2>nul
del "%STARTUP_LINK%" >nul 2>nul

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$dirs=@('%APPDIR%','%INSTALL_DIR%') | Select-Object -Unique; foreach($dir in $dirs){ if(Test-Path -LiteralPath $dir){ attrib -h -s $dir 2>$null; $parent=Split-Path -Parent $dir; $name=Split-Path -Leaf $dir; foreach($base in @($parent,(Split-Path -Parent $parent))){ if($base){ $settings=Join-Path $base '.vscode\settings.json'; if(Test-Path -LiteralPath $settings){ try{ $json=Get-Content -LiteralPath $settings -Raw | ConvertFrom-Json -AsHashtable; if($json.ContainsKey('files.exclude')){ foreach($key in @($name,\"**/$name\",'PyAI','**/PyAI','pyai','**/pyai')){ $json['files.exclude'].Remove($key) | Out-Null }; $json | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $settings -Encoding UTF8 } } catch{} } } } } }" >nul 2>nul

for %%D in ("%INSTALL_DIR%" "%APPDIR%") do (
    if exist "%%~fD\PyAI.exe" (
        attrib -h -s "%%~fD" >nul 2>nul
        start "" cmd /c "timeout /t 2 /nobreak >nul & rmdir /s /q ""%%~fD"""
    )
)

exit /b 0

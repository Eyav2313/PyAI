$ErrorActionPreference = "Stop"

New-Item -ItemType Directory -Force -Path .\dist\assets | Out-Null
Add-Type -AssemblyName System.Drawing
$logoPng = Join-Path $PSScriptRoot "assets\logo.png"
$logoIco = Join-Path $PSScriptRoot "assets\logo.ico"

function Remove-DistPrivateFile {
    param([string] $Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    try {
        Set-ItemProperty -LiteralPath $Path -Name Attributes -Value Normal -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $Path -Force -ErrorAction Stop
    }
    catch {
        Write-Host "Warning: could not remove private release file: $Path"
    }
}

function Clear-DistPrivateFiles {
    foreach ($file in @(
        ".\dist\.env",
        ".\dist\token.txt",
        ".\dist\token.example.txt",
        ".\dist\last_error.txt",
        ".\dist\stop_PyAI.bat",
        ".\dist\setup_token.bat",
        ".\dist\setup_token.ps1",
        ".\dist\install_PyAI.bat",
        ".\dist\BUILD_ERROR.txt"
    )) {
        Remove-DistPrivateFile -Path $file
    }
}

function New-IconFromPng {
    param(
        [string] $PngPath,
        [string] $IcoPath
    )

    $sizes = @(256, 128, 64, 48, 32, 16)
    $source = [System.Drawing.Bitmap]::FromFile($PngPath)
    $images = New-Object System.Collections.Generic.List[byte[]]

    foreach ($size in $sizes) {
        $bitmap = New-Object System.Drawing.Bitmap $size, $size
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
        $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        $graphics.Clear([System.Drawing.Color]::Transparent)
        $graphics.DrawImage($source, 0, 0, $size, $size)

        $memory = New-Object System.IO.MemoryStream
        $bitmap.Save($memory, [System.Drawing.Imaging.ImageFormat]::Png)
        $images.Add($memory.ToArray())

        $memory.Dispose()
        $graphics.Dispose()
        $bitmap.Dispose()
    }

    $stream = [System.IO.File]::Open($IcoPath, [System.IO.FileMode]::Create)
    $writer = New-Object System.IO.BinaryWriter $stream
    $writer.Write([UInt16]0)
    $writer.Write([UInt16]1)
    $writer.Write([UInt16]$sizes.Count)

    $offset = 6 + (16 * $sizes.Count)
    for ($index = 0; $index -lt $sizes.Count; $index++) {
        $size = $sizes[$index]
        $bytes = $images[$index]
        $writer.Write([byte]$(if ($size -eq 256) { 0 } else { $size }))
        $writer.Write([byte]$(if ($size -eq 256) { 0 } else { $size }))
        $writer.Write([byte]0)
        $writer.Write([byte]0)
        $writer.Write([UInt16]1)
        $writer.Write([UInt16]32)
        $writer.Write([UInt32]$bytes.Length)
        $writer.Write([UInt32]$offset)
        $offset += $bytes.Length
    }

    foreach ($bytes in $images) {
        $writer.Write($bytes)
    }

    $writer.Close()
    $stream.Close()
    $source.Dispose()
}

if (Test-Path $logoPng) {
    New-IconFromPng -PngPath $logoPng -IcoPath $logoIco
}
Copy-Item -LiteralPath .\assets\logo.png -Destination .\dist\assets\logo.png -Force
Copy-Item -LiteralPath .\.env.example -Destination .\dist\.env.example -Force
Clear-DistPrivateFiles
Copy-Item -LiteralPath .\uninstall_PyAI.bat -Destination .\dist\uninstall_PyAI.bat -Force
Copy-Item -LiteralPath .\install_PyAI.bat -Destination .\dist\install_PyAI.bat -Force

function Invoke-Checked {
    param([string[]] $Command)

    & $Command[0] @($Command[1..($Command.Length - 1)])
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $($Command -join ' ')"
    }
}

$pythonCommand = $null
$selectedVersion = $null
foreach ($version in @("3.14", "3.13", "3.12")) {
    try {
        & py "-$version" --version *> $null
        $isAvailable = $LASTEXITCODE -eq 0
    }
    catch {
        $isAvailable = $false
    }

    if ($isAvailable) {
        $pythonCommand = @("py", "-$version")
        $selectedVersion = $version
        break
    }
}

if ($null -eq $pythonCommand) {
    $message = @(
        "EXE build needs Python 3.12, 3.13, or 3.14.",
        "Your PC does not have a supported Python available through the py launcher.",
        "",
        "Fix:",
        "1. Install Python from https://www.python.org/downloads/",
        "2. Tick Add python.exe to PATH during install.",
        "3. Reopen PowerShell.",
        "4. Run .\build_exe.bat again."
    )
    $message | Set-Content -LiteralPath .\dist\BUILD_ERROR.txt -Encoding UTF8
    $message | ForEach-Object { Write-Host $_ }
    exit 1
}

$buildVenv = Join-Path $PSScriptRoot ".build-venv-$($selectedVersion.Replace('.', ''))"
if (Test-Path $buildVenv) {
    $existingPython = Join-Path $buildVenv "Scripts\python.exe"
    try {
        & $existingPython --version *> $null
        $venvWorks = $LASTEXITCODE -eq 0
    }
    catch {
        $venvWorks = $false
    }

    if (-not $venvWorks) {
        Remove-Item -LiteralPath $buildVenv -Recurse -Force
    }
}

$python = Join-Path $buildVenv "Scripts\python.exe"
try {
    Invoke-Checked ($pythonCommand + @("-m", "venv", $buildVenv))
}
catch {
    $projectVenvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (Test-Path $projectVenvPython) {
        Write-Host "Could not create build venv. Using existing .venv instead."
        $python = $projectVenvPython
    }
    else {
        $message = @(
            "EXE build failed while creating build venv.",
            "$($_.Exception.Message)",
            "",
            "Fix:",
            "1. Repair or reinstall Python 3.14.",
            "2. Make sure pip/ensurepip is installed.",
            "3. Run .\build_exe.bat again."
        )
        $message | Set-Content -LiteralPath .\dist\BUILD_ERROR.txt -Encoding UTF8
        $message | ForEach-Object { Write-Host $_ }
        exit 1
    }
}

try {
    Invoke-Checked @($python, "-m", "pip", "install", "--upgrade", "pip")
    Invoke-Checked @($python, "-m", "pip", "install", "-r", "requirements.txt")
    Invoke-Checked @($python, "-m", "pip", "install", "pyinstaller")
    $stamp = Get-Date -Format "yyyyMMddHHmmss"
    $tempRoot = Join-Path $env:TEMP "PyAI-build-$stamp"
    $workPath = Join-Path $tempRoot "work"
    $distPath = Join-Path $tempRoot "dist"
    New-Item -ItemType Directory -Force -Path $workPath | Out-Null
    New-Item -ItemType Directory -Force -Path $distPath | Out-Null
    Invoke-Checked @(
        $python,
        "-m",
        "PyInstaller",
        "--onefile",
        "--windowed",
        "--noconfirm",
        "--icon",
        $logoIco,
        "--workpath",
        $workPath,
        "--distpath",
        $distPath,
        "--specpath",
        $PSScriptRoot,
        "--name",
        "PyAI",
        "main.py"
    )
    Get-Process -Name PyAI -ErrorAction SilentlyContinue | Stop-Process -Force
    New-Item -ItemType Directory -Force -Path .\dist\assets | Out-Null
    Copy-Item -LiteralPath (Join-Path $distPath "PyAI.exe") -Destination (Join-Path $PSScriptRoot "dist\PyAI.exe") -Force
}
catch {
    $pythonVersion = & $python --version
    $message = @(
        "EXE build failed while using $pythonVersion.",
        "$($_.Exception.Message)",
        "",
        "Possible fixes:",
        "1. Check internet connection, then run .\build_exe.bat again.",
        "2. If PyInstaller is not available for this Python yet, install Python 3.13 and run again.",
        "3. You can still run PyAI without EXE using: python main.py"
    )
    New-Item -ItemType Directory -Force -Path .\dist | Out-Null
    $message | Set-Content -LiteralPath .\dist\BUILD_ERROR.txt -Encoding UTF8
    $message | ForEach-Object { Write-Host $_ }
    exit 1
}

Copy-Item -LiteralPath .\assets\logo.png -Destination .\dist\assets\logo.png -Force
Copy-Item -LiteralPath .\.env.example -Destination .\dist\.env.example -Force
Clear-DistPrivateFiles
Copy-Item -LiteralPath .\uninstall_PyAI.bat -Destination .\dist\uninstall_PyAI.bat -Force
Copy-Item -LiteralPath .\install_PyAI.bat -Destination .\dist\install_PyAI.bat -Force

Write-Host "Build complete: dist\PyAI.exe"

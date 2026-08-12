@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PY=C:\Program Files\Python313\python.exe"
if not exist "%PY%" set "PY=python"

echo [1/4] 准备虚拟环境 .venv313 ...
if not exist ".venv313\Scripts\python.exe" (
  "%PY%" -m venv .venv313
  if errorlevel 1 exit /b 1
)

echo [2/4] 安装依赖 ...
".venv313\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

echo [3/4] 检查内置 adb ...
if not exist "tools\adb.exe" (
  echo 未找到 tools\adb.exe ，尝试下载 platform-tools ...
  powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://dl.google.com/android/repository/platform-tools-latest-windows.zip' -OutFile '%TEMP%\platform-tools-arkpaint.zip'; Expand-Archive -Path '%TEMP%\platform-tools-arkpaint.zip' -DestinationPath '.' -Force; New-Item -ItemType Directory -Force -Path tools | Out-Null; Copy-Item platform-tools\adb.exe,platform-tools\AdbWinApi.dll,platform-tools\AdbWinUsbApi.dll tools\ -Force"
)

echo [4/4] 打包 exe ...
".venv313\Scripts\pyinstaller.exe" --noconfirm --clean --distpath dist\_pyi ArkPaint.spec
if errorlevel 1 exit /b 1

set "OUT=dist\arkpaint"
if exist "%OUT%" rmdir /S /Q "%OUT%"
mkdir "%OUT%\tools" 2>nul
copy /Y "dist\_pyi\ArkPaint.exe" "%OUT%\ArkPaint.exe" >nul
if exist "tools\adb.exe" (
  copy /Y "tools\adb.exe" "%OUT%\tools\" >nul
  copy /Y "tools\AdbWinApi.dll" "%OUT%\tools\" >nul
  copy /Y "tools\AdbWinUsbApi.dll" "%OUT%\tools\" >nul
)
rmdir /S /Q "dist\_pyi" 2>nul

echo.
echo Done: %OUT%\ArkPaint.exe
echo Distribute the whole dist\arkpaint folder (includes tools\).
echo Note: dist\ is gitignored; only source is pushed to GitHub.
if /I "%ARKPAINT_BUILD_NOPAUSE%"=="1" goto :eof
pause

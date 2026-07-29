@echo off
REM ============================================================
REM Mono Core 4.0 - build .exe with PyInstaller
REM ============================================================
setlocal

cd /d "%~dp0"

if not exist .venv (
    echo [1/4] Creating venv...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo [2/4] Installing requirements...
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller

echo [3/4] Building mono.exe...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist
pyinstaller --noconfirm --clean tools/mono.spec

if errorlevel 1 (
    echo BUILD FAILED
    exit /b 1
)

echo [4/4] Done.
echo ============================================================
echo  mono.exe -> dist\mono.exe
echo  Place .env next to mono.exe (or in %APPDATA%\MonoCore\).
echo ============================================================
endlocal
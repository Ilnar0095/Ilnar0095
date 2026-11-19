@echo off
chcp 65001 >nul
cd /d "%~dp0.."

where py >nul 2>nul && (set PY=py) || (set PY=python)
%PY% -V >nul 2>nul
if errorlevel 1 (
  echo Python ne naiden. Ustanovite ego s python.org/downloads
  echo i na pervem ekrane POSTAVTE GALOCHKU "Add python.exe to PATH".
  echo Posle etogo zakroyte eto okno i snova 2 raza klinknite po etomu faylu.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [shag 1 iz 2] Perviy zapusk: stavlyu zavisimosti...
  echo Eto 1-2 minuty, okno ne zakryvayte.
  %PY% bot\install.py
  echo.
)

echo [shag 2 iz 2] Zapuskayu bota. Okno derzhite otkrytym.
echo Khotite proverit token:  %PY% -m bot --check-token
".venv\Scripts\python.exe" -m bot
pause

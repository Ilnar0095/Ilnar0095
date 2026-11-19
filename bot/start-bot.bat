@echo off
chcp 65001 >nul
cd /d "%~dp0.."

where py >nul 2>nul && (set PY=py) || (set PY=python)
%PY% -V >nul 2>nul
if errorlevel 1 (
  echo.
  echo ============ NADOBEN PYTHON ============
  echo Variant 1 (prostoy, otkroyte Microsoft Store na kompyutere):
  echo    Microsoft Store - "App Installer" ili "Python 3.12" - knopka "Poluchit"
  echo    Tam PATH nastivaetsya sam, nikakie galochki ne nuzhny.
  echo.
  echo Variant 2 (s sayta):
  echo    https://www.python.org/downloads/  - na pervem ekrane
  echo    POSTAVTE GALOCHKU "Add python.exe to PATH", do otherwise Python ne budet viden.
  echo.
  echo Posle ustanovki zakroyte eto okno i snova 2 raza klinknite po start-bot.bat
  echo (pri khelane mozhno proverit: Win+R - cmd - Enter - napechatat  python --version).
  echo =========================================
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [shag 1 iz 2] Perviy zapusk: stavlyu zavisimosti...
  echo Eto 1-2 minuty, okno ne zakryvayte.
  %PY% bot\install.py
  echo.
)

echo Yesli vmesto raboty bota vy vidite kursor ">>>" - znachit Windows otkryl
echo etot fayl kak tekst vnutri Python, a ne zapustil ego. Zakroyte okno i
echo zapuskayte cherez komandnuyu stroku: v provodnike otkroyte papku cookrate,
echo kliknite po stroke adresa sverhu, napishite cmd, Enter, i vnizu pechataite:
echo     py bot\install.py
echo     .venv\Scripts\python.exe -m bot
echo.
echo [shag 2 iz 2] Zapuskayu bota. Okno derzhite otkrytym.
echo Khotite proverit token:  %PY% -m bot --check-token
".venv\Scripts\python.exe" -m bot
pause

@echo off
chcp 65001 >nul

cd /d "%~dp0"

echo Ring Wear Analysis
echo ==================

set PYTHON=C:\Users\ama\AppData\Local\miniforge3\python.exe
set SCRIPT=%~dp0ring_wear.py
set INDIR=%~dp0data\worn
set NEUDIR=%~dp0data\neu
set OUTDIR=%~dp0ring_wear_out

echo Input:   %INDIR%
echo New-ref: %NEUDIR%
echo Output:  %OUTDIR%
echo.

"%PYTHON%" "%SCRIPT%" "%INDIR%" -o "%OUTDIR%" --neu-dir "%NEUDIR%"

if errorlevel 1 (
    echo.
    echo ERROR: Analysis failed.
    pause
    exit /b 1
)

"%PYTHON%" "%SCRIPT%" repeat "%INDIR%" -o "%OUTDIR%" --neu-dir "%NEUDIR%" 2>nul

echo.
echo Opening results ...
if exist "%OUTDIR%\results.xlsx"  start "" "%OUTDIR%\results.xlsx"
if exist "%OUTDIR%\results.html"  start "" "%OUTDIR%\results.html"

pause

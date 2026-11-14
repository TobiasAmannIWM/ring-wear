@echo off
chcp 65001 >nul
echo TriboCore Ring Wear Analysis
echo ==============================

set PYTHON=C:\Users\ama\AppData\Local\miniforge3\python.exe
set SCRIPT=%~dp0ring_wear.py
set INDIR=%~dp0data\reference
set OUTDIR=%~dp0out

echo Input:  %INDIR%
echo Output: %OUTDIR%
echo.

%PYTHON% "%SCRIPT%" "%INDIR%" -o "%OUTDIR%" --panel

if errorlevel 1 (
    echo.
    echo ERROR: Analysis failed.
    pause
    exit /b 1
)

echo.
echo Opening results.xlsx and results.html ...
start "" "%OUTDIR%\results.xlsx"
start "" "%OUTDIR%\results.html"

pause

@echo off
chcp 65001 >nul
cd /d "%~dp0.."
rem 备用：界面打不开时，让正在进行的运行停下来
"runtime\python\python.exe" gb.py stop
echo.
pause

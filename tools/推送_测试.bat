@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo 发一条测试消息到微信（先在管家「设置 → 微信推送」里填好推送服务和 SendKey）
"runtime\python\python.exe" gb.py push test
echo.
pause

@echo off
chcp 65001 >nul
rem 给代号鸢（上班模拟器）的游戏内公告栏截图：每按一次回车截一张，截完关掉这个窗口即可
echo 在模拟器里打开代号鸢（上班模拟器）的公告栏，翻到要截的那一页，回到这里按回车截图。
echo 截完所有需要的画面后，直接关掉这个窗口。
:loop
echo.
pause
call "%~dp0截图_模拟器.bat" 127.0.0.1:16384 yuan_notice
goto loop

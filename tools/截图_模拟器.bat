@echo off
chcp 65001 >nul
rem 给模拟器截一张图，存到 data\shots\<名字>_<时间>.png（不会覆盖之前的）
rem 用法：截图_模拟器.bat [模拟器地址] [名字]     默认 127.0.0.1:16384、screen
set ADB=F:\MuMuPlayer\nx_main\adb.exe
set DEV=%~1
if "%DEV%"=="" set DEV=127.0.0.1:16384
set NAME=%~2
if "%NAME%"=="" set NAME=screen
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set TS=%%i
set OUT=%~dp0..\data\shots
if not exist "%OUT%" mkdir "%OUT%"
"%ADB%" connect %DEV% >nul
"%ADB%" -s %DEV% shell screencap -p /sdcard/gb_screen.png
"%ADB%" -s %DEV% pull /sdcard/gb_screen.png "%OUT%\%NAME%_%TS%.png" >nul
if exist "%OUT%\%NAME%_%TS%.png" (echo 已保存：data\shots\%NAME%_%TS%.png) else (echo 截图失败：模拟器 %DEV% 没开，或游戏不在前台)

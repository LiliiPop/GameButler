@echo off
chcp 65001 >nul
cd /d "%~dp0.."
rem 开发调试用：打开一个能直接敲 gb.py 命令的窗口，例如  gb games / gb tasks yuan / gb run yuan（管家要开着）
doskey gb="%CD%\runtime\python\python.exe" "%CD%\gb.py" $*
echo 可用命令：gb games ^| gb tasks ^<游戏^> ^| gb run ^<游戏^> [任务…] ^| gb stop ^| gb scheduler ^| gb push test
cmd /k

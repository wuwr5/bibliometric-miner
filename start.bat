@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 文献计量分析工作台

set "PY=C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not exist "%PY%" set "PY=E:\annconda\python.exe"
if not exist "%PY%" set "PY=python"

echo 使用解释器: %PY%
echo 启动服务 http://127.0.0.1:8765/  （关闭本窗口即停止）
echo.
"%PY%" server.py 8765
pause

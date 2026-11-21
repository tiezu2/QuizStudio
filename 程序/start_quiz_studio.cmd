@echo off
chcp 65001 >nul
title QuizStudio 启动器
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo.
  echo  没找到 Python。请先安装 Python 3.8 以上版本，安装时勾选 "Add Python to PATH"。
  echo.
  pause
  exit /b 1
)

echo.
echo  QuizStudio 正在启动...
echo   页面地址： http://127.0.0.1:8770/
echo   服务窗口会最小化，关闭它即可停止服务。
echo.

start "QuizStudio 服务" /min %PY% server.py
timeout /t 2 >nul
start "" http://127.0.0.1:8770/

echo 已打开浏览器。本窗口 5 秒后自动关闭。
timeout /t 5 >nul
exit /b 0

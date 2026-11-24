@echo off
chcp 65001 >nul
cd /d "%~dp0程序"
echo QuizStudio 启动中…浏览器会自动打开 http://127.0.0.1:8770/
start "" http://127.0.0.1:8770/
py -3 server.py
echo.
echo 服务已退出。按任意键关闭。
pause >nul
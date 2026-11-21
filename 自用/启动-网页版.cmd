@echo off
chcp 65001 >nul
cd /d %~dp0
echo QuizStudio 网页版启动中…浏览器会自动打开 http://127.0.0.1:8770/
start "" http://127.0.0.1:8770/
py -3 server.py
pause

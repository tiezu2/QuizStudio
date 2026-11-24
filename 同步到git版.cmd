@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 把「本地开发版」的代码同步到「答题系统V1.0」（不含题库和 Key）
robocopy "本地开发版\程序" "答题系统V1.0\程序" server.py index.html quiz_studio_llm.example.json start_quiz_studio.cmd /NJH /NJS /NFL /NDL
robocopy "本地开发版\源码" "答题系统V1.0\源码" /E /XD __pycache__ /NJH /NJS /NFL /NDL
robocopy "本地开发版\程序" "答题系统V1.0\程序" /NJH /NJS /NFL /NDL
del /q "答题系统V1.0\程序\quiz_studio.db*" 2>nul
del /q "答题系统V1.0\程序\quiz_studio_llm.json" 2>nul
echo 同步完成。之后 cd 到根目录执行：git add -A ^&^& git commit -m "..." ^&^& git push
pause
@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 同步「开发版」代码到「答题系统V1.0」（git 版，不含题库和 Key）
robocopy "开发版\程序" "答题系统V1.0\程序" /E /XD __pycache__ /NJH /NJS /NFL /NDL
robocopy "开发版\源码" "答题系统V1.0\源码" /E /XD __pycache__ /NJH /NJS /NFL /NDL
del /q "答题系统V1.0\程序\quiz_studio.db*" 2>nul
del /q "答题系统V1.0\程序\quiz_studio_llm.json" 2>nul
del /q "答题系统V1.0\程序\quiz_studio_ide.json" 2>nul
echo 完成。执行：git add -A ^&^& git commit -m "..." ^&^& git push
pause
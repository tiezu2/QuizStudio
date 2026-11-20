@echo off
chcp 65001 >nul
rem ============================================================
rem  QuizStudio 本地判分小模型（Qwen2.5-3B-Instruct, GGUF Q4_K_M）
rem  启动后监听 http://127.0.0.1:11434/v1/chat/completions
rem  QuizStudio 的 quiz_studio_llm.json 里 providers[0] 就指向这里，
rem  没启动或报错时会自动落到智谱 glm-4-flash。
rem ============================================================
set MODEL=E:\桌面映射\Github项目查询\_tools\models\qwen2.5-3b-instruct-q4_k_m.gguf

if not exist "%MODEL%" (
  echo [x] 找不到模型文件：%MODEL%
  echo     先执行 powershell -File E:\桌面映射\Github项目查询\_tools\get_gguf.ps1
  pause
  exit /b 1
)

echo [i] 模型：%MODEL%
echo [i] 监听：http://127.0.0.1:11434  （Ctrl+C 停止）
echo.

py -3 -m llama_cpp.server ^
  --model "%MODEL%" ^
  --host 127.0.0.1 ^
  --port 11434 ^
  --n_ctx 4096 ^
  --n_gpu_layers -1 ^
  --chat_format chatml ^
  --verbose false

pause

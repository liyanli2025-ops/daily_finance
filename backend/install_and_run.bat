@echo off
chcp 65001 >nul
echo ========================================
echo   Finance Daily - 一键安装启动脚本
echo ========================================
echo.

cd /d "%~dp0"
echo [1/6] 当前目录: %cd%
echo.

echo [2/6] 删除旧的虚拟环境...
if exist venv (
    rmdir /s /q venv
    echo 旧虚拟环境已删除
) else (
    echo 无旧环境需要删除
)
echo.

echo [3/6] 创建新的虚拟环境...
python -m venv venv
echo 虚拟环境创建完成
echo.

echo [4/6] 激活虚拟环境...
call venv\Scripts\activate.bat
echo.

echo [5/6] 安装依赖...
python -m pip install --upgrade pip
pip install -r requirements.txt
echo.

echo [6/6] 启动后端服务...
echo ========================================
echo   服务启动中，请访问: http://localhost:8000
echo   API 文档: http://localhost:8000/docs
echo   按 Ctrl+C 停止服务
echo ========================================
echo.

python -m uvicorn app.main:app --reload --port 8000

pause

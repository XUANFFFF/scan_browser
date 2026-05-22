@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================
echo   扫描文件浏览器
echo   \\192.168.1.115\扫描共享文件
echo ================================
echo.

REM 清理旧进程
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5088.*LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

REM 优先使用 exe，否则用 Python
if exist "dist\扫描文件浏览器.exe" (
    echo 使用独立 exe 启动...
    start http://127.0.0.1:5088
    dist\扫描文件浏览器.exe
) else (
    echo 使用 Python 启动...
    python --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo [错误] 未找到 Python，请安装 Python 3 或使用 exe 版本
        pause
        exit /b 1
    )
    if not exist ".deps_installed" (
        echo 安装依赖...
        pip install -r requirements.txt -q
        echo. > ".deps_installed"
    )
    start http://127.0.0.1:5088
    python app.py
)

echo.
echo 服务已停止。
pause

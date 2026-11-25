@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal enabledelayedexpansion

echo ============================================================
echo   Music Video Pipeline - 启动管理器
echo ============================================================
echo.

rem 1. 读取配置文件中的端口号 [默认 8000]
set "PORT=8000"
if exist "config.json" (
    for /f "tokens=2 delims=:, " %%a in ('findstr /i "api_port" config.json') do (
        set "PORT=%%a"
    )
)

rem 2. 检查端口是否已被占用
set "PORT_IN_USE=0"
for /f "tokens=1,2,3,4,5" %%a in ('netstat -ano ^| findstr /c:":!PORT! "') do (
    if "%%d"=="LISTENING" set "PORT_IN_USE=1"
)

if "!PORT_IN_USE!"=="1" (
    echo [!] 检测到端口 !PORT! 已被占用！
    echo.
    echo 是否自动结束占用该端口的旧进程？ [Y/N, 默认 Y]
    set "kill_choice=Y"
    set /p "kill_choice=[Y/N]: "
    if /i "!kill_choice!" neq "N" (
        echo [i] 正在调用清理工具释放端口...
        call force_kill.bat --no-pause
        echo.
        
        timeout /t 2 >nul
        set "PORT_STILL_IN_USE=0"
        for /f "tokens=1,2,3,4,5" %%a in ('netstat -ano ^| findstr /c:":!PORT! "') do (
            if "%%d"=="LISTENING" set "PORT_STILL_IN_USE=1"
        )
        if "!PORT_STILL_IN_USE!"=="1" (
            echo [FAIL] 端口依然被占用，可能需要手动关闭占用的程序。
            echo.
        ) else (
            echo [OK] 端口已成功释放！
            echo.
        )
    )
)

rem 3. 寻找并选择正确的 Python 解释器
set "PYTHON_CMD="
set "PIP_CMD="

rem 优先情况 A: 本地项目虚拟环境 venv
if exist "%~dp0venv\Scripts\python.exe" (
    set "PYTHON_CMD=%~dp0venv\Scripts\python.exe"
    set "PIP_CMD=%~dp0venv\Scripts\pip.exe"
    echo [OK] 检测到项目本地虚拟环境 venv，将使用本地环境运行。
    echo.
    goto :PYTHON_READY
)

rem 优先情况 B: 测试默认 python 是否包含完整依赖
python -c "import pyncm, fastapi, uvicorn" >nul 2>&1
if !errorlevel! equ 0 (
    set "PYTHON_CMD=python"
    set "PIP_CMD=python -m pip"
    echo [OK] 当前系统默认 Python 依赖完整。
    echo.
    goto :PYTHON_READY
)

rem 优先情况 C: 检查是否存在已安装好依赖的官方 Python 3.10
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" -c "import pyncm, fastapi, uvicorn" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
        set "PIP_CMD=%LOCALAPPDATA%\Programs\Python\Python310\python.exe -m pip"
        echo [OK] 自动适配到依赖完备的 Python 3.10 环境。
        echo.
        goto :PYTHON_READY
    )
)

rem 优先情况 D: 检查 Python 3.13 或其他环境
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" -c "import pyncm, fastapi, uvicorn" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
        set "PIP_CMD=%LOCALAPPDATA%\Programs\Python\Python313\python.exe -m pip"
        echo [OK] 自动适配到 Python 3.13 环境。
        echo.
        goto :PYTHON_READY
    )
)

rem 未能找到已具备依赖的 Python，回退到系统默认 python
set "PYTHON_CMD=python"
set "PIP_CMD=python -m pip"

:PYTHON_READY

rem 4. 依赖完整性二次检查与自动安装
echo [i] 正在检查依赖完整性...
!PYTHON_CMD! -c "import PIL, httpx, pyncm, fastapi, uvicorn, psutil, imageio_ffmpeg, stream_gears, qrcode, fastmcp, multipart" >nul 2>&1
if !errorlevel! neq 0 (
    echo [!] 发现部分核心依赖缺失，正在尝试自动安装...
    if exist "requirements.txt" (
        !PIP_CMD! install -r requirements.txt
    ) else (
        !PIP_CMD! install pyncm httpx Pillow imageio-ffmpeg fastapi uvicorn python-multipart psutil qrcode fastmcp stream-gears
    )
    echo [OK] 依赖修补完成。
    echo.
) else (
    echo [OK] 所有核心依赖均已就绪。
    echo.
)

rem 5. 解析启动模式参数 [支持 cli, demo, api 等]
if "%1"=="--cli"    set MODE=--test
if "%1"=="--demo"   set MODE=--demo
if "%1"=="--api"    (
    echo [i] 正在启动后端 API 服务...
    !PYTHON_CMD! api_service.py
    pause
    exit /b 0
)

rem 如果用户传递了数字，作为CLI数量参数运行
if not "%1"=="" if not defined MODE set MODE=--count %1

if defined MODE (
    echo [i] 启动模式: %MODE%
    echo ============================================================
    echo   正在运行 CLI 模式制作视频...
    echo ============================================================
    !PYTHON_CMD! main.py %MODE%
    echo.
    echo ============================================================
    echo   运行结束，请在 output 目录中查看生成的视频！
    echo ============================================================
    pause
    exit /b 0
)

rem 6. 启动 GUI 主程序
echo [i] 正在启动 WebGUI 客户端...
echo [i] 如果浏览器没有自动打开，请手动访问: http://127.0.0.1:!PORT!
echo.
echo [i] 提示: 您可以随时在当前窗口按下 Ctrl+C 终止服务。
echo.

!PYTHON_CMD! gui_client.py
if !errorlevel! neq 0 (
    echo.
    echo ============================================================
    echo [!] 程序异常退出 [退出码: !errorlevel!]
    if exist "gui_import_crash.log" (
        echo.
        echo [错误日志 gui_import_crash.log]:
        type "gui_import_crash.log"
    )
    if exist "gui_server_crash.log" (
        echo.
        echo [错误日志 gui_server_crash.log]:
        type "gui_server_crash.log"
    )
    if exist "gui_main_crash.log" (
        echo.
        echo [错误日志 gui_main_crash.log]:
        type "gui_main_crash.log"
    )
    echo ============================================================
    echo 按任意键退出...
    pause >nul
)

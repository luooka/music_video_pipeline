@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal enabledelayedexpansion

echo ============================================================
echo   Music Video Pipeline - 启动管理器
echo ============================================================
echo.

:: 1. 尝试读取配置文件中的端口号
set "PORT=8003"
if exist "config.json" (
    for /f "usebackq tokens=*" %%a in (`powershell -Command "try { (Get-Content config.json | ConvertFrom-Json).api_port } catch { 8003 }"`) do (
        set "PORT=%%a"
    )
)

:: 2. 检查端口是否已被占用
netstat -ano | findstr ":%PORT%" | findstr "LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo [!] 检测到端口 %PORT% 已被占用！
    echo.
    echo 是否自动结束占用该端口的旧进程？(Y/N, 默认 Y)
    set "kill_choice=Y"
    set /p "kill_choice=[Y/N]: "
    if /i "!kill_choice!" neq "N" (
        echo [i] 正在调用清理工具释放端口...
        call force_kill.bat --no-pause
        echo.
        
        :: 稍等片刻让清理进程生效并再次验证
        timeout /t 2 >nul
        netstat -ano | findstr ":%PORT%" | findstr "LISTENING" >nul 2>&1
        if !errorlevel! equ 0 (
            echo [FAIL] 端口依然被占用，可能需要手动关闭占用的程序。
            echo.
        ) else (
            echo [OK] 端口已成功释放！
            echo.
        )
    )
)

:: 3. 检查虚拟环境并自动处理
set "VENV_ACTIVE=0"
python -c "import sys; sys.exit(0 if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix) else 1)" >nul 2>&1
if %errorlevel% equ 0 (
    set "VENV_ACTIVE=1"
    echo [OK] 当前已处于活动的虚拟环境中。
    echo.
) else (
    if exist "venv\Scripts\activate.bat" (
        echo [i] 检测到本地虚拟环境 venv，正在自动激活...
        call venv\Scripts\activate.bat
        set "VENV_ACTIVE=1"
        echo [OK] 虚拟环境已激活。
        echo.
    ) else (
        echo [i] 未检测到活动状态的 Python 虚拟环境 (venv)。
        echo 建议在虚拟环境中运行本项目以避免污染全局环境并确保依赖完整。
        echo.
        echo 是否现在自动为您创建虚拟环境并安装依赖？(Y/N, 默认 Y)
        set "create_venv=Y"
        set /p "create_venv=[Y/N]: "
        if /i "!create_venv!" neq "N" (
            echo.
            echo [+] 正在创建虚拟环境 (python -m venv venv)，请稍候...
            python -m venv venv
            if exist "venv\Scripts\activate.bat" (
                call venv\Scripts\activate.bat
                set "VENV_ACTIVE=1"
                echo [OK] 虚拟环境创建成功并已激活！
                echo [+] 正在更新 pip 并安装项目依赖，这可能需要几分钟...
                python -m pip install --upgrade pip
                if exist "requirements.txt" (
                    pip install -r requirements.txt
                ) else (
                    pip install httpx Pillow imageio-ffmpeg aiohttp aiofiles fastapi uvicorn python-multipart psutil qrcode fastmcp biliup stream-gears
                )
                echo [OK] 依赖安装完成！
                echo.
            ) else (
                echo [FAIL] 虚拟环境创建失败，将尝试使用全局环境。
                echo.
            )
        ) else (
            echo 是否在全局 Python 环境中继续运行？(Y/N, 默认 Y)
            set "global_choice=Y"
            set /p "global_choice=[Y/N]: "
            if /i "!global_choice!"=="N" (
                echo 已取消启动。
                pause
                exit /b 0
            )
            echo [i] 将在全局环境中运行。
            echo.
        )
    )
)

:: 4. 依赖检查与自动修补
echo [i] 正在检查依赖完整性...
python -c "import PIL, httpx, pyncm, fastapi, uvicorn, psutil" >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] 发现部分核心依赖缺失，正在尝试自动安装...
    if exist "requirements.txt" (
        pip install -r requirements.txt
    ) else (
        pip install httpx Pillow imageio-ffmpeg aiohttp aiofiles fastapi uvicorn python-multipart psutil qrcode fastmcp biliup stream-gears
    )
    echo [OK] 依赖修补完成。
    echo.
) else (
    echo [OK] 所有核心依赖均已就绪。
    echo.
)

:: 5. 解析启动模式参数 (支持 cli, demo, api 等)
if "%1"=="--cli"    set MODE=--test
if "%1"=="--demo"   set MODE=--demo
if "%1"=="--api"    (
    echo [i] 正在启动后端 API 服务...
    python api_service.py
    pause
    exit /b 0
)

:: 如果用户传递了数字，作为CLI数量参数运行
if not "%1"=="" if not defined MODE set MODE=--count %1

if defined MODE (
    echo [i] 启动模式: %MODE%
    echo ============================================================
    echo   正在运行 CLI 模式制作视频...
    echo ============================================================
    python main.py %MODE%
    echo.
    echo ============================================================
    echo   运行结束，请在 output 目录中查看生成的视频！
    echo ============================================================
    pause
    exit /b 0
)

:: 6. 启动 GUI 主程序
echo [i] 正在启动 WebGUI 客户端...
echo [i] 如果浏览器没有自动打开，请手动访问: http://127.0.0.1:%PORT%
echo.
echo [i] 提示: 您可以随时在当前窗口按下 Ctrl+C 终止服务。
echo.

python gui_client.py
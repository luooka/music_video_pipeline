@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal enabledelayedexpansion

rem 检查是否需要静默运行 [不暂停]
set "PAUSE_AT_END=1"
if "%1"=="--no-pause" (
    set "PAUSE_AT_END=0"
)
if "%2"=="--no-pause" (
    set "PAUSE_AT_END=0"
)

rem 检查管理员权限
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ============================================================
    echo   Music Video Pipeline - 请求管理员权限
    echo ============================================================
    echo.
    echo [i] 正在请求管理员权限以强行释放占用端口...
    
    if !PAUSE_AT_END! equ 0 (
        powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '--no-pause' -Verb RunAs"
    ) else (
        powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    )
    exit /b
)

echo ============================================================
echo   Music Video Pipeline - 强制端口释放工具
echo ============================================================
echo.

rem 读取配置文件中的端口号 [默认 8000]
set "PORT=8000"
if exist "config.json" (
    for /f "tokens=2 delims=:, " %%a in ('findstr /i "api_port" config.json') do (
        set "PORT=%%a"
    )
)

echo [i] 正在检查端口 !PORT! 的占用情况...
set /a count=0

rem 查找占用端口的 PID
for /f "tokens=1,2,3,4,5" %%a in ('netstat -ano ^| findstr /c:":!PORT! "') do (
    if "%%d"=="LISTENING" (
        set "pid=%%e"
        echo [+] 发现占用端口的进程 PID: !pid!
        
        set "proc_name="
        for /f "usebackq tokens=*" %%b in (`powershell -NoProfile -Command "(Get-Process -Id !pid! -ErrorAction SilentlyContinue).ProcessName"`) do (
            set "proc_name=%%b"
        )
        
        if not "!proc_name!"=="" (
            echo [i] 进程名称: !proc_name!.exe
            echo [!] 正在强制终止进程 !proc_name!.exe [PID: !pid!]...
            taskkill /f /pid !pid! >nul 2>&1
            if !errorlevel! equ 0 (
                echo [OK] 成功终止进程 !pid!
                set /a count+=1
            ) else (
                echo [FAIL] 终止进程 !pid! 失败，请尝试手动关闭。
            )
        ) else (
            echo [!] 正在强制终止未知进程 [PID: !pid!]...
            taskkill /f /pid !pid! >nul 2>&1
            if !errorlevel! equ 0 (
                echo [OK] 成功终止进程 !pid!
                set /a count+=1
            )
        )
    )
)

echo.
if !count! equ 0 (
    echo [OK] 端口 !PORT! 未被任何进程占用，无需清理。
) else (
    echo [OK] 成功释放端口 !PORT!，共清理了 !count! 个关联进程！
)

if !PAUSE_AT_END! equ 1 (
    echo.
    echo 按任意键退出...
    pause >nul
)

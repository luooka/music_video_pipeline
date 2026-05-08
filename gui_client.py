# -*- coding: utf-8 -*-
import sys
import os
import threading
import time
import webbrowser
import uvicorn

# 修复 Windows CMD 中文乱码：强制切换到 UTF-8 代码页
if sys.platform == "win32":
    os.system("chcp 65001 >nul 2>nul")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from api_service import app

def run_server(port: int):
    """启动后端 FastAPI 服务"""
    try:
        # 使用从配置中读取的端口
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="error")
    except Exception as e:
        print(f"ℹ️ 后端服务已在运行或端口占用: {e}")

def main():
    # 获取配置中的端口
    from main import load_config
    config = load_config()
    port = config.get("api_port", 8000)
    
    # 1. 在后台线程启动 API 服务 (传递动态端口)
    api_thread = threading.Thread(target=run_server, args=(port,), daemon=True)
    api_thread.start()
    
    # 2. 等待一两秒确保服务已就绪
    time.sleep(1.5)
    
    url = f"http://127.0.0.1:{port}"
    
    # 3. 使用 Microsoft Edge 的“应用模式”启动独立窗口 (App Mode)
    # 这种方式无需安装 pywebview，且能提供完美的独立窗口体验
    print(f"🚀 正在启动独立应用窗口 (URL: {url})...")
    
    # 常见的 Edge 安装路径或直接使用指令
    # --app 参数会移除所有浏览器 UI (地址栏、标签等)，看起来就像原生 App
    edge_cmd = f'start msedge --app="{url}"'
    
    try:
        os.system(edge_cmd)
        print("💡 窗口已弹出。如果未看到窗口，请手动访问上述 URL。")
        # 持续运行以维护后端进程
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 正在关闭服务...")

if __name__ == "__main__":
    # 简单的 ASCII Logo
    print("="*40)
    print("  Music Video Pipeline - WebView Client")
    print("="*40)
    main()

# -*- coding: utf-8 -*-
import sys
import os
import threading
import time
import webbrowser
import uvicorn

# Windows CMD 中文乱码修复
if sys.platform == "win32":
    # 仅修改控制台代码页，不修改Python全局编码
    try:
        os.system("chcp 65001 >nul 2>nul")
    except:
        pass

from api_service import app

def run_server(port: int):
    """启动后端 FastAPI 服务"""
    try:
        # 检查端口是否已被占用
        import socket
        import psutil
        import os
        import signal
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        
        if result == 0:
            # 端口被占用，检查是否是本项目的进程
            print(f"[i] 端口 {port} 已被占用，检查进程信息...")
            
            try:
                # 获取占用端口的进程信息
                for conn in psutil.net_connections(kind='inet'):
                    if conn.laddr.port == port and conn.status == 'LISTEN':
                        pid = conn.pid
                        if pid:
                            try:
                                proc = psutil.Process(pid)
                                cmdline = ' '.join(proc.cmdline())
                                exe_name = proc.name()
                                
                                # 检查是否是本项目进程
                                is_our_process = False
                                if 'python' in exe_name.lower() or 'uvicorn' in exe_name.lower():
                                    if 'api_service.py' in cmdline or 'gui_client.py' in cmdline or 'music_video_pipeline' in cmdline:
                                        is_our_process = True
                                        print(f"  -> 发现本项目进程 (PID: {pid}, 名称: {exe_name})")
                                
                                if is_our_process:
                                    # 尝试关闭旧进程
                                    print(f"  -> 尝试关闭旧进程...")
                                    try:
                                        if os.name == 'nt':  # Windows
                                            # Windows下 os.kill(pid, signal.CTRL_C_EVENT) 对非同组进程会失败，直接使用 psutil 的 terminate() 更稳定
                                            proc.terminate()
                                        else:  # Linux/Mac
                                            os.kill(pid, signal.SIGTERM)
                                        
                                        # 等待进程结束
                                        import time
                                        for _ in range(10):
                                            if not psutil.pid_exists(pid):
                                                print(f"  -> 旧进程已关闭")
                                                break
                                            time.sleep(0.5)
                                        else:
                                            print(f"  -> 旧进程未响应，强制终止")
                                            proc.kill()
                                            proc.wait(timeout=5)
                                    except Exception as e:
                                        print(f"  -> 关闭进程失败: {e}")
                                else:
                                    print(f"  -> 端口被其他进程占用 (PID: {pid}, 名称: {exe_name})")
                                    print(f"  -> 请手动关闭该进程或修改配置文件中的端口号")
                                    return
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                print(f"  -> 无法获取进程信息，可能已退出")
            except ImportError:
                print(f"  -> 无法导入psutil，跳过进程检查")
            except Exception as e:
                print(f"  -> 进程检查出错: {e}")
        
        # 使用从配置中读取的端口
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="error")
    except Exception as e:
        print(f"[i] 后端服务启动异常: {e}")

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
    print(f"[+] 正在启动独立应用窗口 (URL: {url})...")
    
    # 常见的 Edge 安装路径或直接使用指令
    # --app 参数会移除所有浏览器 UI (地址栏、标签等)，看起来就像原生 App
    edge_cmd = f'start msedge --app="{url}"'
    
    try:
        os.system(edge_cmd)
        print("[i] 窗口已弹出。如果未看到窗口，请手动访问上述 URL。")
        # 持续运行以维护后端进程
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[!] 正在关闭服务...")

if __name__ == "__main__":
    # 简单的 ASCII Logo
    print("="*40)
    print("  Music Video Pipeline - WebView Client")
    print("="*40)
    main()

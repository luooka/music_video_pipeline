# -*- coding: utf-8 -*-
import sys
import os
import traceback

# ★ 关键修复：在无控制台模式（PyInstaller console=False）下，
# sys.stdout 和 sys.stderr 为 None，会导致 uvicorn 的日志格式化器
# 调用 .isatty() 时崩溃。在所有库导入之前将它们重定向到空设备。
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

# 1. 尝试导入所有依赖，若有报错立即写入导入崩溃日志并退出
try:
    import threading
    import time
    import webbrowser
    import uvicorn
    import socket
    
    # Windows CMD 中文乱码修复
    if sys.platform == "win32":
        try:
            os.system("chcp 65001 >nul 2>nul")
        except:
            pass

    from api_service import app
    from main import load_config
except Exception as e:
    # 获取 exe 同级目录
    log_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(log_dir, "gui_import_crash.log"), "w", encoding="utf-8") as f:
        f.write("=== 依赖导入或初始化阶段崩溃 ===\n")
        traceback.print_exc(file=f)
    sys.exit(1)


def run_server(port: int):
    """启动后端 FastAPI 服务"""
    log_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    try:
        import psutil
        import signal
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        
        if result == 0:
            # 端口被占用，检查是否是本项目的进程
            try:
                for conn in psutil.net_connections(kind='inet'):
                    if conn.laddr.port == port and conn.status == 'LISTEN':
                        pid = conn.pid
                        if pid:
                            try:
                                proc = psutil.Process(pid)
                                cmdline = ' '.join(proc.cmdline())
                                exe_name = proc.name()
                                
                                is_our_process = False
                                if 'python' in exe_name.lower() or 'uvicorn' in exe_name.lower():
                                    if 'api_service.py' in cmdline or 'gui_client.py' in cmdline or 'music_video_pipeline' in cmdline:
                                        is_our_process = True
                                
                                if is_our_process:
                                    proc.terminate()
                                    for _ in range(10):
                                        if not psutil.pid_exists(pid):
                                            break
                                        time.sleep(0.5)
                                    else:
                                        proc.kill()
                                        proc.wait(timeout=5)
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                pass
            except Exception as e:
                with open(os.path.join(log_dir, "gui_server_crash.log"), "a", encoding="utf-8") as f:
                    f.write(f"[Warning] 端口进程检查异常: {e}\n")
        
        # 运行 uvicorn (使用 0.0.0.0 以支持局域网访问)
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="error")
    except Exception as e:
        with open(os.path.join(log_dir, "gui_server_crash.log"), "w", encoding="utf-8") as f:
            f.write("=== 后端 FastAPI 服务器在后台线程中崩溃 ===\n")
            traceback.print_exc(file=f)


def main():
    log_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    try:
        # 获取配置中的端口
        config = load_config()
        port = config.get("api_port", 8000)
        
        # 1. 在后台线程启动 API 服务 (传递动态端口)
        api_thread = threading.Thread(target=run_server, args=(port,), daemon=True)
        api_thread.start()
        
        # 2. 等待一两秒确保服务已就绪
        time.sleep(1.5)
        
        url = f"http://127.0.0.1:{port}"
        
        # 3. 使用 Microsoft Edge 的“应用模式”启动独立窗口 (App Mode)
        edge_cmd = f'start msedge --app="{url}"'
        
        try:
            os.system(edge_cmd)
            
            # 给出 15 秒启动宽限期，防止初始化较慢时因页面未载入导致立即超时退出
            time.sleep(15)
            
            import api_service
            
            # 持续运行以维护后端进程并监控心跳
            while True:
                current_time = time.time()
                
                # 安全防线：如果当前队列中存在正在运行或排队等待中的任务，
                # 说明流水线正忙，绝不退出。自动重置最新心跳，防范 CPU 满载阻塞或 lag 导致的超时误判。
                tasks = getattr(api_service.queue_state, 'tasks', [])
                has_active_tasks = any(t.status in ["running", "waiting"] for t in tasks)
                if has_active_tasks:
                    api_service.LAST_HEARTBEAT_TIME = current_time
                
                last_hb = getattr(api_service, 'LAST_HEARTBEAT_TIME', current_time)
                if current_time - last_hb > 60:
                    # 超过 60 秒未收到心跳，且没有任何正在进行中的任务，说明网页已关闭，安全退出
                    break
                time.sleep(2)
            
            # 强制清退并结束整个进程（含后台 Uvicorn 线程）
            os._exit(0)
        except KeyboardInterrupt:
            os._exit(0)
    except Exception as e:
        with open(os.path.join(log_dir, "gui_main_crash.log"), "w", encoding="utf-8") as f:
            f.write("=== 主线程(Edge 启动与守护)崩溃 ===\n")
            traceback.print_exc(file=f)
        sys.exit(1)


if __name__ == "__main__":
    main()

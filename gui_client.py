# -*- coding: utf-8 -*-
import argparse
import os
import shutil
import subprocess
import sys
import traceback

# ★ 关键修复：在无控制台模式（PyInstaller console=False）下，
# sys.stdout 和 sys.stderr 为 None，会导致 uvicorn 的日志格式化器
# 调用 .isatty() 时崩溃。在所有库导入之前将它们重定向到空设备。
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

try:
    import socket
    import threading
    import time
    import webbrowser
    import uvicorn

    if sys.platform == "win32":
        try:
            os.system("chcp 65001 >nul 2>nul")
        except Exception:
            pass

    import api_service
    from api_service import app
    from main import load_config
    from video_maker import _cleanup_ffmpeg_processes
except Exception:
    log_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(log_dir, "gui_import_crash.log"), "w", encoding="utf-8") as f:
        f.write("=== 依赖导入或初始化阶段崩溃 ===\n")
        traceback.print_exc(file=f)
    sys.exit(1)


class _BackgroundServer(uvicorn.Server):
    """在后台线程运行时禁用信号处理器注册，避免非主线程报错"""
    def install_signal_handlers(self):
        pass


def _cleanup_port_conflict(port: int, log_dir: str):
    """若目标端口被本项目的历史进程占用，尝试优雅清理"""
    try:
        import psutil
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        if result != 0:
            return

        current_pid = os.getpid()
        for conn in psutil.net_connections(kind='inet'):
            if conn.laddr.port == port and conn.status == 'LISTEN':
                pid = conn.pid
                if not pid or pid == current_pid:
                    continue
                try:
                    proc = psutil.Process(pid)
                    cmdline = ' '.join(proc.cmdline()).lower()
                    exe_name = proc.name().lower()

                    is_our_process = (
                        'musicvideopipeline' in exe_name
                        or (
                            ('python' in exe_name or 'uvicorn' in exe_name)
                            and ('api_service.py' in cmdline or 'gui_client.py' in cmdline or 'music_video_pipeline' in cmdline)
                        )
                    )
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


def _open_app_window(url: str):
    """优先使用 Edge 应用模式打开独立窗口，缺失时回退默认浏览器"""
    edge_candidates = [shutil.which("msedge")]
    if sys.platform == "win32":
        for env_var in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
            base = os.environ.get(env_var)
            if base:
                edge_candidates.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))

    for edge_exe in edge_candidates:
        if edge_exe and os.path.exists(edge_exe):
            try:
                subprocess.Popen([edge_exe, f"--app={url}"])
                return True
            except Exception:
                continue

    try:
        return webbrowser.open(url)
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description="Music Video Pipeline GUI Launcher")
    parser.add_argument("--server-only", action="store_true", help="仅启动后端服务，不打开浏览器且不自动退出")
    args = parser.parse_args()

    log_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    server = None
    api_thread = None

    try:
        config = load_config()
        host = config.get("api_host", "127.0.0.1")
        port = config.get("api_port", 8000)

        _cleanup_port_conflict(port, log_dir)

        uv_config = uvicorn.Config(app, host=host, port=port, log_level="error")
        server = _BackgroundServer(uv_config)

        def _serve():
            try:
                server.run()
            except Exception:
                with open(os.path.join(log_dir, "gui_server_crash.log"), "w", encoding="utf-8") as f:
                    f.write("=== 后端 FastAPI 服务器在后台线程中崩溃 ===\n")
                    traceback.print_exc(file=f)

        api_thread = threading.Thread(target=_serve, daemon=True)
        api_thread.start()

        # 等待服务端口就绪（最多 5 秒）
        for _ in range(25):
            if server.started:
                break
            time.sleep(0.2)

        connect_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
        url = f"http://{connect_host}:{port}"

        if args.server_only:
            try:
                while api_thread.is_alive():
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        else:
            _open_app_window(url)
            # 给出 15 秒启动宽限期
            time.sleep(15)

            try:
                while api_thread.is_alive():
                    current_time = time.time()
                    tasks = getattr(api_service.queue_state, 'tasks', [])
                    has_active_tasks = any(t.status in ["running", "waiting"] for t in tasks)
                    if has_active_tasks:
                        api_service.LAST_HEARTBEAT_TIME = current_time

                    last_hb = getattr(api_service, 'LAST_HEARTBEAT_TIME', current_time)
                    if current_time - last_hb > 60:
                        break
                    time.sleep(2)
            except KeyboardInterrupt:
                pass

    except Exception:
        with open(os.path.join(log_dir, "gui_main_crash.log"), "w", encoding="utf-8") as f:
            f.write("=== 主线程(Edge 启动与守护)崩溃 ===\n")
            traceback.print_exc(file=f)
        sys.exit(1)
    finally:
        if server is not None:
            server.should_exit = True
        if api_thread is not None and api_thread.is_alive():
            api_thread.join(timeout=5)
        try:
            _cleanup_ffmpeg_processes()
        except Exception:
            pass


if __name__ == "__main__":
    main()

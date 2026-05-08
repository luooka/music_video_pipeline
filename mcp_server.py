# -*- coding: utf-8 -*-
import asyncio
import sys
from pathlib import Path
from datetime import datetime
from fastmcp import FastMCP
from main import PipelineProcessor, load_config
from bilibili_uploader import BilibiliUploader
from bilibili_auth import BilibiliAuth

# 初始化 FastMCP 服务器
# 使用纯 ASCII 名称，所有调试和横幅配置均已通过环境变量处理，此处保持参数最简以兼容最新版本
mcp = FastMCP("MusicVideoPipeline")

def get_processor():
    """初始化流水线处理器"""
    config = load_config()
    return PipelineProcessor(config)

@mcp.tool()
async def get_daily_recommendations():
    """
    获取今日网易云音乐推荐歌曲列表。
    返回包含歌曲名、歌手、ID 等信息的列表。
    """
    try:
        proc = get_processor()
        songs = await proc.fetch_recommendations()
        return songs[:10]
    except Exception as e:
        return f"[FAIL] 获取失败: {str(e)}"

@mcp.tool()
async def search_music(keyword: str):
    """
    根据关键词搜索网易云音乐中的歌曲。
    参数:
        keyword: 搜索关键词（如歌名或歌手名）
    """
    try:
        proc = get_processor()
        songs = await proc.api.search_songs(keyword, limit=5)
        return songs
    except Exception as e:
        return f"[FAIL] 搜索失败: {str(e)}"

import httpx

# API 服务地址 (与 gui_client.py / WebView 使用同一个后端)
def get_api_base():
    config = load_config()
    port = config.get("api_port", 8000)
    return f"http://127.0.0.1:{port}"

_API_BASE = get_api_base()

@mcp.tool()
async def produce_music_video(song_queries: list[str]):
    """
    根据给定的多个歌名关键词，一键全自动合成多歌曲合集视频。
    【重要】本工具通过 HTTP 委托给独立运行的 API 后端执行合成，
    确保 FFmpeg 在不受内存限制的环境中运行。
    请确保 API 服务已在运行（python gui_client.py 会自动启动）。
    参数:
        song_queries: 歌名关键词列表 (例如: ["歌曲1", "歌曲2"])
    """
    try:
        # 1. 先检查 API 服务是否在运行
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                health = await client.get(f"{_API_BASE}/health")
                if health.status_code != 200:
                    return "[FAIL] API 后端服务未响应。请先运行 gui_client.py 启动后端。"
            except httpx.ConnectError:
                return "[FAIL] 无法连接到 API 后端 (http://127.0.0.1:8000)。请先运行 gui_client.py 启动后端服务。"

        # 2. 逐个搜索歌曲
        proc = get_processor()
        found_songs = []
        fail_queries = []
        
        for query in song_queries:
            results = await proc.api.search_songs(query, limit=1)
            if results:
                found_songs.append(results[0])
            else:
                fail_queries.append(query)
        
        if not found_songs:
            return f"[FAIL] 未能搜索到列表中的任何歌曲: {', '.join(song_queries)}"

        # 3. 通过 HTTP 委托给 API 服务执行合成（FFmpeg 将在 API 服务的独立进程中运行）
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{_API_BASE}/generate",
                json={"songs": found_songs, "combine": True}
            )
            
            if resp.status_code == 400:
                return "[BUSY] API 后端正在执行另一个合成任务，请稍后重试。"
            elif resp.status_code != 200:
                return f"[FAIL] API 后端返回错误: {resp.text}"

        # 4. 构建返回信息（不在本地猜路径，路径由 API 后端决定）
        success_names = [f"《{s['name']}》" for s in found_songs]
        response = (
            f"[OK] 合成任务已通过 API 后端提交！\n"
            f"成功匹配: {', '.join(success_names)}\n"
        )
        if fail_queries:
            response += f"未能匹配: {', '.join(fail_queries)}\n"
            
        response += (
            f"预计总时长: {len(found_songs) * 1.5} 分钟左右\n"
            f"合成由独立后端执行，不受 MCP 进程限制。\n"
            f"请使用 check_video_status 工具查询进度和实际输出路径。"
        )
        return response
            
    except Exception as e:
        return f"[FAIL] 提交任务失败: {str(e)}"

@mcp.tool()
async def upload_to_bilibili(video_path: str, title: str, description: str = "", tags: list[str] = None):
    """
    将合成好的视频上传到 BILIBILI（后台执行，立即返回）。
    参数:
        video_path: 视频文件的本地绝对路径
        title: 视频标题 (建议 80 字以内)
        description: 视频简介
        tags: 标签列表 (例如 ["音乐", "AI"])
    """
    import threading
    
    # 检查文件是否存在
    if not Path(video_path).exists():
        return f"[FAIL] 视频文件不存在: {video_path}"
    
    def _do_upload():
        try:
            config = load_config()
            if not description:
                template = config.get("bilibili_desc_template", "歌曲：{title}")
                desc = template.format(title=title)
            else:
                desc = description
                
            uploader = BilibiliUploader(config)
            result = uploader.upload(
                video_path=video_path,
                title=title,
                description=desc,
                tags=tags
            )
            
            if result["success"]:
                print(f"[BILIBILI] 投稿成功！标题: {title}", file=sys.stderr)
            else:
                print(f"[BILIBILI] 投稿失败: {result['error']}", file=sys.stderr)
        except Exception as e:
            print(f"[BILIBILI] 投稿异常: {str(e)}", file=sys.stderr)
    
    thread = threading.Thread(target=_do_upload, daemon=True)
    thread.start()
    
    file_size_mb = Path(video_path).stat().st_size / (1024 * 1024)
    return (
        f"[OK] B站投稿任务已在后台启动！\n"
        f"标题: {title}\n"
        f"文件大小: {file_size_mb:.1f} MB\n"
        f"上传可能需要几分钟，请耐心等待。\n"
        f"上传结果会打印在后台日志中。"
    )

@mcp.tool()
async def check_video_status():
    """
    查询当前视频合成任务的实时状态和日志。
    可用于跟踪 produce_music_video 提交后的合成进度。
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{_API_BASE}/status")
            if resp.status_code == 200:
                data = resp.json()
                status = "🔄 运行中" if data["is_running"] else "✅ 空闲"
                logs = "\n".join(data.get("logs", [])[-10:])
                return (
                    f"状态: {status}\n"
                    f"当前阶段: {data.get('current_status', 'N/A')}\n"
                    f"最近日志:\n{logs}"
                )
            return f"[FAIL] API 返回错误: {resp.status_code}"
    except httpx.ConnectError:
        return "[FAIL] API 后端未运行。请先启动 gui_client.py。"
    except Exception as e:
        return f"[FAIL] 查询失败: {str(e)}"

@mcp.tool()
async def get_bilibili_login_qr():
    """
    获取 B 站登录二维码（原厂动力版）。
    调用后请向用户展示二维码，并将返回的 '验证凭证' 保存用于后续验证。
    """
    try:
        auth = BilibiliAuth()
        res = auth.get_qr_info()
        if res["success"]:
            return (
                f"[OK] 请扫描下方二维码登录 B 站：\n"
                f"图片路径: {res['qr_path']}\n"
                f"验证凭证 (请妥善保存并用于验证): {res['raw_json']}\n"
                f"由于采用原厂驱动，扫码完成后请对我说“验证登录”。"
            )
        return f"[FAIL] 获取二维码失败: {res['error']}"
    except Exception as e:
        return f"[FAIL] 发生错误: {str(e)}"

@mcp.tool()
async def verify_bilibili_login(qr_context: str):
    """
    通过原厂驱动校验 B 站扫码登录状态。
    参数:
        qr_context: get_bilibili_login_qr 返回的完整 '验证凭证' JSON 字符串
    """
    try:
        import asyncio
        auth = BilibiliAuth()
        # 这种原厂校验是阻塞的，我们放在线程里跑，避免阻塞服务器
        res = await asyncio.to_thread(auth.verify_login, qr_context)
        
        if res["success"]:
            return "[OK] 登录成功！原厂驱动已为您自动生成 cookies.json，现在可以开始全自动投稿了。"
        return f"[FAIL] 验证失败: {res['error']}"
    except Exception as e:
        return f"[FAIL] 验证过程发生错误: {str(e)}"

if __name__ == "__main__":
    import sys
    import os
    
    # 彻底禁用 FastMCP 的横幅、Logo 和调试界面，确保通讯管道 100% 纯净
    os.environ["FASTMCP_LOG_LEVEL"] = "ERROR"
    os.environ["FASTMCP_SHOW_SERVER_BANNER"] = "False"
    
    # 彻底清理并锁定输出流编码
    # stdout 必须是 utf-8 (MCP 协议要求)，stderr 用于观察日志
    sys.stdout.flush()
    try:
        # 后台服务的编码适配：Windows 下对齐 GBK，Linux 下保持 UTF-8
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if sys.platform == "win32":
            import locale
            target_enc = locale.getpreferredencoding() or "gbk"
            sys.stderr.reconfigure(encoding=target_enc, errors="backslashreplace")
        else:
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except:
        pass

    # 启动 MCP 服务，禁用所有非协议相关的横幅输出
    mcp.run(show_banner=False)

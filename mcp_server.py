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
    获取网易云音乐今日推荐歌单（依赖 cookies.json 中的 MUSIC_U cookie）。
    返回全部推荐歌曲（通常约 30 首），每首包含字段：
      id (int)       - 网易云歌曲 ID
      name (str)     - 歌名
      artists (list) - 歌手列表
      album (str)    - 专辑名
      album_pic (str)- 专辑封面 URL
      duration_ms    - 时长(毫秒)

    典型用法：调用后取出第一首歌的 album_pic 作为视频封面。

    【风格筛选指引】网易云 API 不返回曲风/流派/语种标签，你需根据 name 和 artists 字段推断。
    常见推断规则：
    - 日文歌：name 或 artists 中含假名（ぁ-ゟ、ァ-ヿ）或日文汉字组合 → 日文歌曲/二次元
    - 纯音乐/电子：name 中常见 "instrumental"、"remix"、"phonk" 等关键词
    - 华语/韩语/英语：根据字符集判断
    - 快节奏/燃系：根据歌名字面含义、艺术家风格联想
    筛选后调用 search_music 二次确认，再用 produce_music_video 合成。
    """
    try:
        proc = get_processor()
        songs = await proc.fetch_recommendations()
        return songs
    except Exception as e:
        return f"[FAIL] 获取失败: {str(e)}"

@mcp.tool()
async def search_music(keyword: str):
    """
    在网易云音乐中按关键词搜索歌曲，返回最多 5 条匹配结果。
    参数:
        keyword (str): 歌名或歌手名（如 "晴天"、"周杰伦"）
    每条结果包含字段：id, name, artists, album, album_pic, duration_ms（同 get_daily_recommendations）。
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

@mcp.tool()
async def produce_music_video(song_queries: list[str]):
    """
    根据歌名关键词列表，全自动搜索歌曲、下载音频、合成多歌曲合集视频。
    
    【前置条件】必须先启动 API 后端服务：在项目目录执行 `python gui_client.py` 或 `start.bat --api`。
    
    【重要：异步执行 + 轮询等待】
    本函数提交任务后立即返回，实际合成在后台执行（10 首歌约需 10~15 分钟）。
    
    方案 A：同步轮询（推荐）
      1. 调用本函数 → 得到 [OK] 确认
      2. 进入循环：sleep 30 秒 → 调用 check_video_status()
      3. 当 check_video_status 返回 done=true 时，提取其中的「视频路径」
      4. 用该路径调用 upload_to_bilibili 上传
      循环上限建议 40 次（约 20 分钟），超时则报错退出。
    
    方案 B：定时任务轮询（适合不支持 sleep 的 Agent）
      创建一个每 60 秒执行一次的循环定时任务，任务 prompt 中写明：
        - 目的：等待 music_video_pipeline 视频合成完成并上传 B 站
        - 第一步：调用 check_video_status 检查状态
        - 第二步：若 done=true，提取视频路径，调用 upload_to_bilibili 上传，
          标题「网易云音乐日推」，简介列出歌名，封面用 get_daily_recommendations
          返回值中第一首歌的 album_pic
        - 第三步：若 done=false，不做任何操作，等待下一次定时触发
        - 第四步：若已上传成功，删除本定时任务
        - 超时处理：若已轮询超过 30 次仍 done=false，则删除定时任务并报告超时
    
    参数:
        song_queries (list[str]): 歌名关键词列表，如 ["晴天", "夜曲", "Lemon"]
    返回:
        [OK] + 匹配到的歌曲列表       — 任务已提交
        [FAIL] + 原因                — API 后端未运行或搜索失败
        [BUSY]                       — 后端正忙
    """
    try:
        # 1. 先检查 API 服务是否在运行
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                health = await client.get(f"{get_api_base()}/health")
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
                f"{get_api_base()}/generate",
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
async def upload_to_bilibili(video_path: str, title: str, description: str = "", tags: list[str] = None, cover: str = ""):
    """
    将本地视频文件投稿到 B 站音乐综合分区（tid=138）。
    
    【前置条件】需要先通过 biliup login 或 get_bilibili_login_qr + verify_bilibili_login 登录 B 站。
    【注意】投稿在后台线程异步执行，本函数立即返回。不会返回 BV 号，上传结果仅打印到后台日志。
    
    参数:
        video_path (str):  视频文件绝对路径
        title (str):       视频标题，建议 80 字以内
        description (str): 视频简介（可选，留空使用模板）
        tags (list[str]):  标签列表，如 ["音乐", "AI"]（可选，留空使用默认标签）
        cover (str):       封面图片绝对路径（可选，不传则使用视频首帧）
    返回:
        [OK] + 标题和文件大小     — 投稿已提交
        [FAIL] + 原因             — 文件不存在或上传失败
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
                tags=tags,
                cover=cover
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
    查询 produce_music_video 提交的合成任务进度。详见 produce_music_video 的【异步执行 + 轮询等待】章节。
    
    返回示例：
      合成中 → "状态: 运行中 | 当前阶段: Processing songs... | done=false"
      已完成 → "状态: 空闲 | 当前阶段: N/A | done=true | 视频路径: D:\\...\\daily_music_20260521.mp4"
    
    建议轮询间隔：30 秒。当 done=true 时停止轮询，从返回文本中提取视频路径供 upload_to_bilibili 使用。
    API 后端未启动时返回 [FAIL]。
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{get_api_base()}/status")
            if resp.status_code == 200:
                data = resp.json()
                status = "运行中" if data["is_running"] else "空闲"
                logs = "\n".join(data.get("logs", [])[-10:])
                done = not data["is_running"]
                
                # 解析最终视频路径
                video_path = ""
                if done:
                    for log_line in reversed(data.get("logs", [])):
                        if "[OK] Done! Final video:" in log_line:
                            video_path = log_line.split("Final video:", 1)[-1].strip()
                            break
                
                result = (
                    f"状态: {status}\n"
                    f"当前阶段: {data.get('current_status', 'N/A')}\n"
                    f"done={done}\n"
                )
                if video_path:
                    result += f"视频路径: {video_path}\n"
                result += f"最近日志:\n{logs}"
                return result
            return f"[FAIL] API 返回错误: {resp.status_code}"
    except httpx.ConnectError:
        return "[FAIL] API 后端未运行。请先启动 gui_client.py。"
    except Exception as e:
        return f"[FAIL] 查询失败: {str(e)}"

@mcp.tool()
async def get_bilibili_login_qr():
    """
    生成 B 站登录二维码并保存为本地图片。
    调用后应：
      1. 向用户展示 qr_path 指向的二维码图片
      2. 保存返回的 raw_json（验证凭证），用户扫码后调用 verify_bilibili_login 完成登录
    【注意】本工具不验证扫码状态，仅生成二维码。
    返回:
        [OK] + qr_path（二维码图片路径）+ raw_json（验证凭证）
        [FAIL] + 错误原因
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
    校验 B 站扫码登录是否完成（与 get_bilibili_login_qr 配合使用）。
    参数:
        qr_context (str): get_bilibili_login_qr 返回的 raw_json 完整字符串
    返回:
        [OK]         — 登录成功，cookies.json 已生成，可开始投稿
        [FAIL] + 原因 — 扫码未完成或已过期
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

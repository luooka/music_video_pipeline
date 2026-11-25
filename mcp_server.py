# -*- coding: utf-8 -*-
import asyncio
import os
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx
from fastmcp import FastMCP

from bilibili_auth import BilibiliAuth
from bilibili_uploader import BilibiliUploader
from main import PipelineProcessor, load_config

mcp = FastMCP("MusicVideoPipeline")

_upload_jobs: dict[str, dict] = {}
_upload_jobs_lock = threading.Lock()


def get_processor():
    """初始化流水线处理器"""
    config = load_config()
    return PipelineProcessor(config)


def get_api_base():
    config = load_config()
    host = config.get("api_host", "127.0.0.1")
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    port = config.get("api_port", 8000)
    return f"http://{host}:{port}"


@mcp.tool()
async def get_daily_recommendations():
    """
    获取网易云音乐今日推荐歌单（依赖 config.json 中的 netease_cookie）。
    返回推荐歌曲列表，每首包含 id, name, artists, album, album_pic, duration_ms。
    """
    proc = get_processor()
    try:
        return await proc.fetch_recommendations()
    except Exception as e:
        return f"[FAIL] 获取失败: {str(e)}"
    finally:
        await proc.api.aclose()


@mcp.tool()
async def search_music(keyword: str):
    """
    在网易云音乐中按关键词搜索歌曲，返回最多 5 条匹配结果。
    参数:
        keyword (str): 歌名或歌手名（如 "晴天"、"周杰伦"）
    """
    proc = get_processor()
    try:
        res = await proc.api.search_songs(keyword, limit=5)
        return res.get("songs", []) if isinstance(res, dict) else res
    except Exception as e:
        return f"[FAIL] 搜索失败: {str(e)}"
    finally:
        await proc.api.aclose()


@mcp.tool()
async def produce_music_video(song_queries: list[str]):
    """
    根据歌名关键词列表，全自动搜索歌曲、下载音频、合成多歌曲合集视频。

    【前置条件】必须先启动独立 API 后端服务：`python api_service.py`、`start.bat --api` 或 `python gui_client.py --server-only`。
    参数:
        song_queries (list[str]): 歌名关键词列表，如 ["晴天", "夜曲", "Lemon"]
    """
    proc = get_processor()
    try:
        api_base = get_api_base()
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                health = await client.get(f"{api_base}/health")
                if health.status_code != 200:
                    return "[FAIL] API 后端服务未响应。请先运行 `python api_service.py` 或 `start.bat --api` 启动后端。"
            except httpx.ConnectError:
                return f"[FAIL] 无法连接到 API 后端 ({api_base})。请先运行 `python api_service.py` 或 `start.bat --api` 启动后端服务。"

        found_songs = []
        fail_queries = []
        for query in song_queries:
            results = await proc.api.search_songs(query, limit=1)
            songs = results.get("songs", []) if isinstance(results, dict) else results
            if songs:
                found_songs.append(songs[0])
            else:
                fail_queries.append(query)

        if not found_songs:
            return f"[FAIL] 未能搜索到列表中的任何歌曲: {', '.join(song_queries)}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{api_base}/generate",
                json={"songs": found_songs, "combine": True}
            )
            if resp.status_code != 200:
                return f"[FAIL] API 后端返回错误: {resp.text}"
            task_id = resp.json().get("task_id", "")

        success_names = [f"《{s['name']}》" for s in found_songs]
        response = (
            f"[OK] 合成任务已通过 API 后端提交！task_id={task_id}\n"
            f"成功匹配: {', '.join(success_names)}\n"
        )
        if fail_queries:
            response += f"未能匹配: {', '.join(fail_queries)}\n"

        response += (
            f"预计总时长: {len(found_songs) * 1.2:.1f} 分钟左右\n"
            f"合成由独立后端执行，不受 MCP 进程限制。\n"
            f"请使用 check_video_status(task_id=\"{task_id}\") 查询进度和实际输出路径。"
        )
        return response

    except Exception as e:
        return f"[FAIL] 提交任务失败: {str(e)}"
    finally:
        await proc.api.aclose()


@mcp.tool()
async def check_video_status(task_id: str = ""):
    """
    查询 produce_music_video 提交的合成任务进度。
    参数:
        task_id (str): 可选任务 ID；留空时查询当前运行中或最新的任务。
    """
    try:
        api_base = get_api_base()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{api_base}/status")
            if resp.status_code != 200:
                return f"[FAIL] API 返回错误: {resp.status_code}"

            data = resp.json()
            tasks = data.get("tasks", [])
            if not tasks:
                return "状态: 空闲\n当前队列中没有任务。\ndone=true"

            target = None
            if task_id:
                target = next((t for t in tasks if t.get("id") == task_id), None)
                if not target:
                    return f"[FAIL] 未找到任务 ID: {task_id}"
            else:
                target = next((t for t in tasks if t.get("status") == "running"), None) or tasks[-1]

            task_status = target.get("status", "unknown")
            done = task_status in ("completed", "failed", "cancelled")
            video_path = target.get("final_video_path", "")
            logs = "\n".join(target.get("logs", [])[-10:])

            result = (
                f"task_id={target.get('id')}\n"
                f"状态: {task_status} ({target.get('progress', 0)}%)\n"
                f"当前阶段: {target.get('current_status_text', 'N/A')}\n"
                f"done={done}\n"
            )
            if video_path:
                result += f"视频路径: {video_path}\n"
            if target.get("upload_status"):
                result += f"自动投稿状态: {target['upload_status']}\n"
            result += f"最近日志:\n{logs}"
            return result
    except httpx.ConnectError:
        return "[FAIL] API 后端未运行。请先启动 `python api_service.py` 或 `start.bat --api`。"
    except Exception as e:
        return f"[FAIL] 查询失败: {str(e)}"


@mcp.tool()
async def upload_to_bilibili(video_path: str, title: str, description: str = "", tags: list[str] = None, cover: str = ""):
    """
    将本地视频文件投稿到 B 站音乐综合分区（tid=138）。
    返回 upload_id，可通过 check_upload_status 查询上传结果。
    """
    if not Path(video_path).is_file():
        return f"[FAIL] 视频文件不存在: {video_path}"
    if cover and not Path(cover).is_file():
        return f"[FAIL] 封面文件不存在: {cover}"

    upload_id = str(uuid.uuid4())[:8]
    with _upload_jobs_lock:
        _upload_jobs[upload_id] = {
            "id": upload_id,
            "title": title,
            "status": "uploading",
            "result": None,
            "started_at": time.strftime("%H:%M:%S"),
        }

    def _do_upload():
        try:
            config = load_config()
            if not description:
                template = config.get("bilibili_desc_template", "歌曲：{title}")
                desc = template.replace("{title}", title)
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
            with _upload_jobs_lock:
                _upload_jobs[upload_id]["status"] = "completed" if result.get("success") else "failed"
                _upload_jobs[upload_id]["result"] = result
            if result.get("success"):
                print(f"[BILIBILI] 投稿成功！标题: {title}", file=sys.stderr)
            else:
                print(f"[BILIBILI] 投稿失败: {result.get('error')}", file=sys.stderr)
        except Exception as e:
            with _upload_jobs_lock:
                _upload_jobs[upload_id]["status"] = "failed"
                _upload_jobs[upload_id]["result"] = {"success": False, "error": str(e)}
            print(f"[BILIBILI] 投稿异常: {str(e)}", file=sys.stderr)

    thread = threading.Thread(target=_do_upload, daemon=False)
    thread.start()

    file_size_mb = Path(video_path).stat().st_size / (1024 * 1024)
    return (
        f"[OK] B站投稿任务已在后台启动！upload_id={upload_id}\n"
        f"标题: {title}\n"
        f"文件大小: {file_size_mb:.1f} MB\n"
        f"请使用 check_upload_status(upload_id=\"{upload_id}\") 查询投稿进度与结果。"
    )


@mcp.tool()
async def check_upload_status(upload_id: str = ""):
    """查询 upload_to_bilibili 提交的投稿任务状态。"""
    with _upload_jobs_lock:
        if not _upload_jobs:
            return "当前没有投稿任务记录。"
        if upload_id:
            job = _upload_jobs.get(upload_id)
            if not job:
                return f"[FAIL] 未找到投稿任务 ID: {upload_id}"
        else:
            job = list(_upload_jobs.values())[-1]

        res = job.get("result") or {}
        lines = [
            f"upload_id={job['id']}",
            f"标题: {job['title']}",
            f"状态: {job['status']}",
            f"开始时间: {job['started_at']}",
        ]
        if res.get("bvid"):
            lines.append(f"BVID: {res['bvid']}")
        if res.get("error"):
            lines.append(f"错误: {res['error']}")
        return "\n".join(lines)


@mcp.tool()
async def get_bilibili_login_qr():
    """生成 B 站登录二维码并保存为本地图片。"""
    try:
        auth = BilibiliAuth()
        res = await asyncio.to_thread(auth.get_qr_info, True)
        if res["success"]:
            return (
                f"[OK] 请扫描下方二维码登录 B 站：\n"
                f"图片路径: {res['qr_path']}\n"
                f"验证凭证 (请妥善保存并用于验证): {res['raw_json']}\n"
                f"扫码完成后请调用 verify_bilibili_login 完成登录。"
            )
        return f"[FAIL] 获取二维码失败: {res['error']}"
    except Exception as e:
        return f"[FAIL] 发生错误: {str(e)}"


@mcp.tool()
async def verify_bilibili_login(qr_context: str):
    """校验 B 站扫码登录是否完成（与 get_bilibili_login_qr 配合使用）。"""
    try:
        auth = BilibiliAuth()
        res = await asyncio.to_thread(auth.verify_login, qr_context)

        if res["success"]:
            return "[OK] 登录成功！已为您自动生成 cookies.json，现在可以开始全自动投稿了。"
        return f"[FAIL] 验证失败: {res['error']}"
    except Exception as e:
        return f"[FAIL] 验证过程发生错误: {str(e)}"


if __name__ == "__main__":
    os.environ["FASTMCP_LOG_LEVEL"] = "ERROR"
    os.environ["FASTMCP_SHOW_SERVER_BANNER"] = "False"

    sys.stdout.flush()
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if sys.platform == "win32":
            import locale
            target_enc = locale.getpreferredencoding() or "gbk"
            sys.stderr.reconfigure(encoding=target_enc, errors="backslashreplace")
        else:
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

    mcp.run(show_banner=False)

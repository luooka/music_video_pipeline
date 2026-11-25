# -*- coding: utf-8 -*-
import asyncio
import base64
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from io import BytesIO
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from bilibili_auth import BilibiliAuth
from bilibili_uploader import BilibiliUploader
from cleanup_manager import CleanupManager
from main import CONFIG_PATH, PipelineProcessor, load_config, save_config
from video_maker import _cleanup_ffmpeg_processes


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    if config.get("cleanup", {}).get("cleanup_on_start", True):
        try:
            cm = CleanupManager(config)
            await asyncio.to_thread(cm.cleanup_old_files)
        except Exception as e:
            print(f"启动清理失败: {e}")

    worker_task = asyncio.create_task(task_queue_worker())
    yield
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    try:
        _cleanup_ffmpeg_processes()
    except Exception:
        pass
    if state.processor:
        await state.processor.api.aclose()


app = FastAPI(
    title="Music Video Pipeline API",
    description="音乐视频自动化合成流水线后台服务。支持网易云推荐获取、视频异步合成、日志实时查询。",
    version="1.1.0",
    lifespan=lifespan
)

# 挂载静态文件
if getattr(sys, 'frozen', False):
    static_dir = Path(sys._MEIPASS) / "static"
else:
    static_dir = Path(__file__).parent / "static"


@app.get("/static/logs.html", include_in_schema=False)
async def redirect_logs(request: Request):
    query_params = request.query_params
    url = "/?page=monitor"
    if query_params:
        url += "&" + str(query_params)
    return RedirectResponse(url=url)


@app.get("/static/upload.html", include_in_schema=False)
async def redirect_upload(request: Request):
    query_params = request.query_params
    url = "/?page=upload"
    if query_params:
        url += "&" + str(query_params)
    return RedirectResponse(url=url)


@app.get("/static/login.html", include_in_schema=False)
async def redirect_login():
    return RedirectResponse(url="/?login=1")


app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", summary="主页", tags=["页面"])
async def index():
    """返回可视化 GUI 界面"""
    return FileResponse(static_dir / "index.html")


class Task:
    def __init__(self, songs, combine=True, auto_upload=False, upload_format_name=""):
        self.id = str(uuid.uuid4())[:8]
        self.songs = songs
        self.combine = combine
        self.auto_upload = auto_upload
        self.upload_format_name = upload_format_name
        self.status = "waiting"  # waiting, running, completed, cancelled, failed
        self.upload_status = ""  # "", uploading, success, failed
        self.progress = 0
        self.current_status_text = "等待中..."
        self.logs = []
        self.created_at = time.strftime("%H:%M:%S")
        self.final_video_path = ""
        self.first_cover_path = ""
        self.deleted = False
        self.song_list_text = self._format_song_list(self.songs)

    @staticmethod
    def _format_song_list(songs: list) -> str:
        return "\n".join(
            [f"{i + 1}. {s.get('name', '')} - {', '.join(s.get('artists', []))}" for i, s in enumerate(songs)]
        )

    def update_succeeded_songs(self, succeeded_songs: list):
        if succeeded_songs:
            self.song_list_text = self._format_song_list(succeeded_songs)

    def to_dict(self):
        return {
            "id": self.id,
            "songs_count": len(self.songs),
            "songs_names": [s.get("name", "") for s in self.songs],
            "song_list_text": self.song_list_text,
            "combine": self.combine,
            "auto_upload": self.auto_upload,
            "upload_format_name": self.upload_format_name,
            "status": self.status,
            "upload_status": self.upload_status,
            "progress": self.progress,
            "current_status_text": self.current_status_text,
            "logs": self.logs[-50:],
            "created_at": self.created_at,
            "final_video_path": self.final_video_path,
            "first_cover_path": self.first_cover_path,
        }


class QueueState:
    def __init__(self):
        self.tasks: list[Task] = []


queue_state = QueueState()


class GlobalState:
    processor: PipelineProcessor | None = None

    @property
    def is_running(self):
        return any(t.status == "running" for t in queue_state.tasks)

    @property
    def current_status(self):
        running_task = next((t for t in queue_state.tasks if t.status == "running"), None)
        return running_task.current_status_text if running_task else "Idle"

    @property
    def logs(self):
        running_task = next((t for t in queue_state.tasks if t.status == "running"), None)
        if running_task:
            return running_task.logs
        if queue_state.tasks:
            return queue_state.tasks[-1].logs
        return []


state = GlobalState()

# B站扫码会话缓存（避免每2秒轮询重复开阻塞长轮询线程）
_bilibili_login_sessions: dict[str, dict] = {}


class ConfigUpdate(BaseModel):
    netease_cookie: str = Field(..., description="网易云 MUSIC_U Cookie 内容")


class GenerateRequest(BaseModel):
    songs: list = Field(..., description="要合成的歌曲列表对象数组")
    combine: bool = Field(True, description="处理完成后是否自动拼接为长视频")
    auto_upload: bool = Field(False, description="合成完成后是否自动上传到B站")
    upload_format_name: str = Field("", description="使用的上传格式名称（auto_upload为true时有效）")


class QueryRequest(BaseModel):
    query: str = Field(..., description="要搜索并合成的歌曲名或关键词")
    combine: bool = Field(True, description="处理完成后是否自动拼接为长视频")


class BilibiliUploadRequest(BaseModel):
    video_path: str = Field(..., description="本地视频文件绝对路径")
    title: str = Field(..., description="视频标题")
    description: str = Field("", description="视频简介")
    tags: list[str] = Field(["音乐", "网易云音乐"], description="标签列表")
    cover: str = Field("", description="封面图片绝对路径（留空使用视频首帧）")


class UploadFormat(BaseModel):
    name: str = Field(..., description="格式名称")
    title: str = Field(..., description="标题模板")
    cover: str = Field("first_song", description="封面策略：first_song / custom")
    cover_custom: str = Field("", description="自定义封面图片路径（cover=custom 时使用）")
    description: str = Field("song_list", description="简介策略：song_list / custom")
    description_custom: str = Field("", description="自定义简介文本（description=custom 时使用）")
    tags: list[str] = Field(["音乐", "网易云音乐"], description="标签列表")


def get_processor() -> PipelineProcessor:
    if not state.processor:
        config = load_config()
        state.processor = PipelineProcessor(config)
        try:
            state.processor.cleanup_manager = CleanupManager(config)
        except Exception as e:
            print(f"清理管理器初始化失败: {e}")
    return state.processor


def _apply_new_cookie_to_processor(config: dict):
    """安全更新 processor 配置与网易云 Cookie，不打断正在执行的任务回调"""
    if state.processor:
        state.processor.update_config(config)
    else:
        state.processor = PipelineProcessor(config)
        try:
            state.processor.cleanup_manager = CleanupManager(config)
        except Exception:
            pass


@app.get("/health", summary="健康检查", tags=["基础接口"])
def health():
    return {"status": "ok"}


LAST_HEARTBEAT_TIME = time.time()


@app.post("/heartbeat", summary="前端心跳包", tags=["基础接口"])
async def receive_heartbeat():
    global LAST_HEARTBEAT_TIME
    LAST_HEARTBEAT_TIME = time.time()
    return {"status": "ok"}


@app.get("/config", summary="获取配置", tags=["配置管理"])
def get_config():
    """读取 config.json 中的当前配置项（对敏感 Cookie 脱敏）"""
    config = load_config()
    has_cookie = bool((config.get("netease_cookie") or "").strip())
    masked = dict(config)
    masked["netease_cookie"] = "***" if has_cookie else ""
    masked["has_netease_cookie"] = has_cookie
    return masked


@app.post("/config", summary="更新配置", tags=["配置管理"])
def update_config(data: ConfigUpdate):
    """更新网易云 Cookie 并实时应用到流水线处理器"""
    config = load_config()
    config["netease_cookie"] = data.netease_cookie
    save_config(config)
    _apply_new_cookie_to_processor(config)
    return {"status": "success"}


@app.get("/search", summary="搜索歌曲", tags=["音乐数据"])
async def search_songs(q: str, limit: int = 20, offset: int = 0):
    """通过关键词搜索网易云音乐歌曲，支持分页"""
    try:
        proc = get_processor()
        return await proc.api.search_songs(q, limit=limit, offset=offset)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/recommendations", summary="获取今日推荐", tags=["音乐数据"])
async def get_recommendations():
    """调用网易云 API 获取用户今日推荐歌曲"""
    try:
        proc = get_processor()
        songs = await proc.fetch_recommendations()
        return {"songs": songs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/netease/playlists", summary="获取当前登录用户的所有歌单", tags=["音乐数据"])
async def get_user_playlists():
    """获取当前已登录网易云账户的所有个人/收藏歌单列表"""
    try:
        proc = get_processor()
        playlists = await proc.api.get_user_playlists()
        return {"playlists": playlists}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/netease/playlist/tracks", summary="获取特定歌单的曲目", tags=["音乐数据"])
async def get_playlist_tracks(id: int, limit: int = 20, offset: int = 0):
    """根据歌单 ID 异步拉取其中的部分歌曲曲目，支持分页"""
    try:
        proc = get_processor()
        songs = await proc.api.get_playlist_tracks(id, limit=limit, offset=offset)
        return {"songs": songs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/netease/song-url", summary="获取歌曲播放 URL", tags=["音乐数据"])
async def get_song_url(id: int):
    """根据歌曲 ID 获取其试听的 CDN 播放链接"""
    try:
        proc = get_processor()
        url = await proc.api.get_song_url(id)
        if not url:
            raise HTTPException(status_code=404, detail="未找到歌曲播放链接，可能为 VIP 或版权受限歌曲")
        return {"url": url}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def task_queue_worker():
    while True:
        try:
            task = next((t for t in queue_state.tasks if t.status == "waiting" and not t.deleted), None)
            if not task:
                await asyncio.sleep(1)
                continue

            task.status = "running"
            task.progress = 0
            task.current_status_text = "初始化任务..."

            await run_single_task(task)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[Queue Worker Error] {e}")
            await asyncio.sleep(1)


async def run_single_task(task: Task):
    def status_logger(msg: str):
        task.current_status_text = msg
        task.logs.append(msg)

        text = msg.lower()
        if "starting processing" in text or "fetch" in text or "并发准备" in text:
            task.progress = max(task.progress, 15)
        elif "download" in text or "processing song" in text or "下载" in text:
            task.progress = max(task.progress, 35)
        elif "ffmpeg" in text or "spectrum" in text or "画幅" in text or "频谱" in text or "合成播放器视频片段" in text:
            task.progress = max(task.progress, 60)
        elif "stitch" in text or "concat" in text or "stitching" in text or "拼接" in text:
            task.progress = max(task.progress, 85)
        elif "upload" in text or "bilibili" in text or "上传" in text:
            task.progress = max(task.progress, 95)

        if "[ok] done!" in text:
            task.progress = 100

    proc = get_processor()
    try:
        config = load_config()
        proc.update_config(config)
        proc.set_status_callback(status_logger)

        today = datetime.now().strftime("%Y%m%d")
        run_dir = Path(config["output_dir"]) / today
        run_dir.mkdir(parents=True, exist_ok=True)

        status_logger(f"Starting processing {len(task.songs)} songs...")

        def is_cancelled():
            return task.status == "cancelled" or task.deleted

        if is_cancelled():
            return

        succeeded_songs = []
        successful_clips = await proc.process_songs(
            task.songs, run_dir, is_cancelled_callback=is_cancelled, succeeded_songs=succeeded_songs
        )

        if is_cancelled():
            status_logger("[FAIL] 任务已被中途取消")
            return

        active_songs = succeeded_songs if succeeded_songs else task.songs
        task.update_succeeded_songs(active_songs)
        if active_songs:
            candidate_cover = run_dir / "images" / f"{active_songs[0]['id']}_cover.png"
            if candidate_cover.exists():
                task.first_cover_path = str(candidate_cover)

        if task.combine and successful_clips:
            status_logger("Processing Stitching final video...")
            final_path = run_dir / f"daily_music_{today}_{task.id}.mp4"

            if is_cancelled():
                status_logger("[FAIL] 任务已被中途取消")
                return

            loop = asyncio.get_running_loop()
            success = await loop.run_in_executor(None, proc.video_maker.concat_clips, successful_clips, str(final_path))

            if is_cancelled():
                try:
                    if final_path.exists():
                        final_path.unlink()
                except Exception:
                    pass
                status_logger("[FAIL] 任务已被中途取消")
                return

            if success:
                task.final_video_path = str(final_path)
                status_logger(f"[OK] Done! Final video: {final_path}")
                proc.save_song_list(active_songs, run_dir, filename=f"song_list_{task.id}.txt")
                proc.save_song_list(active_songs, run_dir, filename="song_list.txt")

                if task.auto_upload and not is_cancelled():
                    task.upload_status = "uploading"
                    status_logger("Auto-upload enabled, preparing upload...")
                    try:
                        formats = load_upload_formats()
                        fmt = next((f for f in formats if f["name"] == task.upload_format_name), formats[0] if formats else None)
                        if fmt:
                            title = fmt["title"]
                            desc = fmt["description"]
                            if fmt["description"] == "song_list":
                                desc = task.song_list_text
                            elif fmt["description"] == "custom":
                                desc = fmt["description_custom"]

                            cover = ""
                            if fmt["cover"] == "first_song":
                                cover = task.first_cover_path
                            elif fmt["cover"] == "custom":
                                cover = fmt["cover_custom"]

                            status_logger(f"Uploading to Bilibili: {title}")
                            uploader = BilibiliUploader(config)
                            result = await loop.run_in_executor(
                                None,
                                uploader.upload,
                                str(final_path),
                                title,
                                desc,
                                fmt["tags"],
                                config.get("bilibili_tid", 138),
                                cover
                            )
                            if is_cancelled():
                                status_logger("[FAIL] 任务已被中途取消")
                                return
                            if result.get("success") or result.get("bvid"):
                                task.upload_status = "success"
                                status_logger(f"[OK] Upload success! bvid: {result.get('bvid', '')}")
                            else:
                                task.upload_status = "failed"
                                status_logger(f"[FAIL] Upload failed: {result.get('error', str(result))}")
                        else:
                            task.upload_status = "failed"
                            status_logger("[FAIL] No upload format found")
                    except Exception as ue:
                        task.upload_status = "failed"
                        status_logger(f"[FAIL] Auto-upload error: {str(ue)}")
            else:
                status_logger("[FAIL] Stitching failed")
                task.status = "failed"
        else:
            if not successful_clips:
                status_logger("[FAIL] 没有生成任何视频片段")
                task.status = "failed"
            else:
                status_logger("[OK] Processing finished (No stitching)")
                task.progress = 100
                task.status = "completed"

        if task.status == "running" and not is_cancelled():
            task.status = "completed"
            task.progress = 100

    except Exception as e:
        status_logger(f"[FAIL] Error occurred: {str(e)}")
        if task.status == "running":
            task.status = "failed"
    finally:
        proc.set_status_callback(None)


@app.get("/status", summary="查询合成状态", tags=["任务执行"])
def get_status():
    """查询当前任务队列的状态及日志，兼容旧接口"""
    return {
        "is_running": state.is_running,
        "current_status": state.current_status,
        "logs": state.logs[-20:],
        "tasks": [t.to_dict() for t in queue_state.tasks]
    }


@app.post("/generate", summary="开始异步合成视频", tags=["任务执行"])
async def generate_video(req: GenerateRequest):
    """接收歌曲列表，加入后台异步任务队列顺序执行"""
    if not req.songs:
        raise HTTPException(status_code=400, detail="歌曲列表不能为空")
    task = Task(
        songs=req.songs,
        combine=req.combine,
        auto_upload=req.auto_upload,
        upload_format_name=req.upload_format_name
    )
    queue_state.tasks.append(task)
    return {"status": "started", "task_id": task.id}


@app.post("/tasks/{task_id}/cancel", summary="取消排队或执行中的任务", tags=["任务执行"])
async def cancel_task(task_id: str):
    task = next((t for t in queue_state.tasks if t.id == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status in ["completed", "cancelled", "failed"]:
        return {"status": "success", "message": "Task already finished"}

    was_running = (task.status == "running")
    task.status = "cancelled"
    task.current_status_text = "任务已被用户取消"
    task.logs.append("[i] 任务已被用户中途取消。")

    if was_running:
        try:
            _cleanup_ffmpeg_processes()
        except Exception as e:
            print(f"Error cleaning up FFmpeg: {e}")

    return {"status": "success"}


@app.delete("/tasks/{task_id}", summary="删除任务列表中的任务", tags=["任务执行"])
async def delete_task(task_id: str):
    task = next((t for t in queue_state.tasks if t.id == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status in ["running", "waiting"]:
        await cancel_task(task_id)

    task.deleted = True
    queue_state.tasks.remove(task)
    return {"status": "success"}


@app.post("/generate_by_query", summary="根据歌名直接合成", tags=["任务执行"])
async def generate_by_query(req: QueryRequest):
    """AI 直接调用入口：输入歌名关键词，系统自动搜索最匹配的结果并直接开始视频合成"""
    try:
        proc = get_processor()
        results = await proc.api.search_songs(req.query, limit=1)
        songs = results.get("songs", []) if isinstance(results, dict) else results
        if not songs:
            raise HTTPException(status_code=404, detail="未找到相关歌曲")

        return await generate_video(GenerateRequest(songs=songs, combine=req.combine))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ================== 网易云音乐扫码登录接口 ==================
class NeteaseCheckLoginRequest(BaseModel):
    unikey: str = Field(..., description="网易云扫码 unikey")


@app.get("/netease/qrcode", summary="获取网易云登录二维码", tags=["网易云登录"])
async def get_netease_qrcode():
    """获取网易云登录二维码，返回 Base64 Data URI 和 unikey"""
    try:
        import qrcode
        from pyncm.apis import login

        res_key = await asyncio.to_thread(login.LoginQrcodeUnikey)
        if res_key.get("code") != 200:
            raise Exception(f"网易云创建Unikey失败: {res_key}")

        unikey = res_key["unikey"]
        qr_url = login.GetLoginQRCodeUrl(unikey)

        qr_img = qrcode.make(qr_url)
        buf = BytesIO()
        qr_img.save(buf, format="PNG")
        b64_data = base64.b64encode(buf.getvalue()).decode("ascii")

        return {
            "qr_path": f"data:image/png;base64,{b64_data}",
            "unikey": unikey
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/netease/check-login", summary="检查网易云扫码状态", tags=["网易云登录"])
async def check_netease_login(req: NeteaseCheckLoginRequest):
    """传入 unikey 轮询扫码状态。扫码成功后自动保存 Cookie 并应用到系统"""
    try:
        from pyncm import GetCurrentSession
        from pyncm.apis import login

        res = await asyncio.to_thread(login.LoginQrcodeCheck, req.unikey)
        code = res.get("code", 801)

        if code == 803:
            session = GetCurrentSession()
            music_u = session.cookies.get("MUSIC_U", domain=".music.163.com") or session.cookies.get("MUSIC_U")
            if not music_u:
                music_u = res.get("cookie", "")

            if music_u:
                config = load_config()
                config["netease_cookie"] = music_u
                save_config(config)
                _apply_new_cookie_to_processor(config)

                return {
                    "success": True,
                    "status": "success",
                    "has_cookie": True,
                    "message": "登录成功，已自动保存配置！"
                }
            return {"success": False, "status": "error", "message": "授权成功但未获取到有效 MUSIC_U Cookie"}

        elif code == 802:
            return {"success": False, "status": "authorizing", "message": "已扫码，等待确认授权..."}
        elif code == 800:
            return {"success": False, "status": "expired", "message": "二维码已失效，请重新生成"}
        else:
            return {"success": False, "status": "waiting", "message": "等待扫码中..."}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ================== Bilibili 相关接口 ==================
def _qr_session_key(raw_json: str) -> str:
    try:
        parsed = json.loads(raw_json)
        auth_code = parsed.get("data", {}).get("auth_code")
        if auth_code:
            return str(auth_code)
    except Exception:
        pass
    return hashlib.sha1(raw_json.encode("utf-8", errors="ignore")).hexdigest()


def _prune_bilibili_sessions():
    cutoff = time.time() - 600
    stale_keys = [k for k, v in _bilibili_login_sessions.items() if v.get("created_at", 0) < cutoff]
    for k in stale_keys:
        _bilibili_login_sessions.pop(k, None)


@app.get("/bilibili/qrcode", summary="获取 B 站登录二维码", tags=["B站投稿"])
async def get_bilibili_qr():
    """生成 B 站登录二维码图片，返回 Base64 Data URI 和验证凭证 raw_json"""
    try:
        auth = BilibiliAuth()
        res = await asyncio.to_thread(auth.get_qr_info, False)
        if res["success"]:
            return {
                "qr_path": res["qr_data_uri"],
                "raw_json": res["raw_json"]
            }
        return {"error": res.get("error", "未知错误")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/bilibili/check-login", summary="检查扫码登录状态", tags=["B站投稿"])
async def check_bilibili_login(raw_json: str = Body(...)):
    """基于二维码凭证异步后台跟踪扫码状态，避免轮询阻塞"""
    try:
        _prune_bilibili_sessions()
        key = _qr_session_key(raw_json)
        session = _bilibili_login_sessions.get(key)

        if session is None:
            session = {
                "status": "waiting",
                "result": None,
                "created_at": time.time(),
            }
            _bilibili_login_sessions[key] = session

            async def _run_verify():
                auth = BilibiliAuth()
                res = await asyncio.to_thread(auth.verify_login, raw_json)
                session["result"] = res
                session["status"] = "done"

            session["task"] = asyncio.create_task(_run_verify())

        if session["status"] == "waiting":
            return {"success": False, "status": "waiting"}

        res = session.get("result") or {"success": False, "error": "未知状态"}
        return {
            "success": bool(res.get("success")),
            "status": "success" if res.get("success") else "error",
            "error": res.get("error"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/bilibili/check-cookie", summary="检查当前 Cookie 登录状态", tags=["B站投稿"])
async def check_cookie_status():
    """检查 cookies.json 是否存在且结构有效"""
    try:
        auth = BilibiliAuth()
        return {"logged_in": auth.is_cookie_valid()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/bilibili/upload-file", summary="上传视频或封面文件到服务器临时目录", tags=["B站投稿"])
async def upload_video_file(file: UploadFile = File(...)):
    """接收前端上传的文件，采用分块流式写入临时目录并返回路径，避免大视频耗尽内存"""
    try:
        temp_dir = Path(tempfile.gettempdir()) / "music_video_uploads"
        temp_dir.mkdir(exist_ok=True)

        cm = CleanupManager(load_config())
        await asyncio.to_thread(cm.cleanup_temp_uploads, 24)

        ext = Path(file.filename).suffix if file.filename else ".mp4"
        file_id = str(uuid.uuid4())
        file_path = temp_dir / f"{file_id}{ext}"

        def _stream_to_disk():
            with open(file_path, "wb") as f:
                shutil.copyfileobj(file.file, f, length=1024 * 1024)

        await asyncio.to_thread(_stream_to_disk)
        return {"path": str(file_path), "success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/bilibili/upload", summary="上传视频到 B 站", tags=["B站投稿"])
async def upload_to_bilibili(req: BilibiliUploadRequest):
    """调用 stream-gears 上传视频到 B 站"""
    if not req.video_path or not os.path.isfile(req.video_path):
        raise HTTPException(status_code=400, detail=f"视频文件不存在: {req.video_path}")
    if req.cover and req.cover.strip() and not os.path.isfile(req.cover):
        raise HTTPException(status_code=400, detail=f"封面文件不存在: {req.cover}")

    try:
        config = load_config()
        uploader = BilibiliUploader(config)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            uploader.upload,
            req.video_path,
            req.title,
            req.description,
            req.tags,
            config.get("bilibili_tid", 138),
            req.cover
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ================== 上传格式管理 ==================
if getattr(sys, 'frozen', False):
    UPLOAD_FORMATS_FILE = Path(sys.executable).parent / "upload_formats.json"
else:
    UPLOAD_FORMATS_FILE = Path(__file__).parent / "upload_formats.json"


def load_upload_formats():
    if UPLOAD_FORMATS_FILE.exists():
        try:
            with open(UPLOAD_FORMATS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return [
        {
            "name": "默认格式",
            "title": "每日网易云音乐推荐",
            "cover": "first_song",
            "cover_custom": "",
            "description": "song_list",
            "description_custom": "",
            "tags": ["音乐", "网易云音乐"]
        }
    ]


def save_upload_formats(formats):
    tmp_path = UPLOAD_FORMATS_FILE.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(formats, f, indent=2, ensure_ascii=False)
    tmp_path.replace(UPLOAD_FORMATS_FILE)


@app.get("/bilibili/upload-formats", summary="获取所有上传格式", tags=["B站投稿"])
def get_upload_formats():
    return load_upload_formats()


@app.post("/bilibili/upload-formats", summary="添加或更新上传格式", tags=["B站投稿"])
def add_upload_format(format: UploadFormat):
    formats = load_upload_formats()
    fmt_dict = format.model_dump() if hasattr(format, "model_dump") else format.dict()
    idx = next((i for i, f in enumerate(formats) if f["name"] == format.name), -1)
    if idx >= 0:
        formats[idx] = fmt_dict
    else:
        formats.append(fmt_dict)
    save_upload_formats(formats)
    return {"success": True}


@app.delete("/bilibili/upload-formats/{name}", summary="删除上传格式", tags=["B站投稿"])
def delete_upload_format(name: str):
    formats = load_upload_formats()
    new_formats = [f for f in formats if f["name"] != name]
    if len(new_formats) == len(formats):
        raise HTTPException(status_code=404, detail=f"格式 '{name}' 不存在")
    save_upload_formats(new_formats)
    return {"success": True}


# ================== 磁盘清理相关接口 ==================
class CleanupRequest(BaseModel):
    max_age_days: int = Field(7, description="保留最近多少天的文件")
    max_total_size_gb: int = Field(10, description="最大占用空间GB")


@app.get("/cleanup/status", summary="获取磁盘使用情况", tags=["磁盘清理"])
async def get_cleanup_status():
    """获取当前磁盘使用情况统计"""
    try:
        proc = get_processor()
        if proc.cleanup_manager:
            return await asyncio.to_thread(proc.cleanup_manager.get_disk_usage)
        return {"error": "清理管理器未初始化"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/cleanup/run", summary="执行磁盘清理", tags=["磁盘清理"])
async def run_cleanup(req: CleanupRequest = None):
    """手动执行磁盘清理"""
    try:
        proc = get_processor()
        if not proc.cleanup_manager:
            return {"error": "清理管理器未初始化"}

        if req:
            proc.cleanup_manager.max_age_days = req.max_age_days
            proc.cleanup_manager.max_total_size_gb = req.max_total_size_gb

        stats = await asyncio.to_thread(proc.cleanup_manager.cleanup_old_files)
        return {
            "success": True,
            "stats": stats,
            "config": {
                "max_age_days": proc.cleanup_manager.max_age_days,
                "max_total_size_gb": proc.cleanup_manager.max_total_size_gb
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    config = load_config()
    host = config.get("api_host", "127.0.0.1")
    port = config.get("api_port", 8000)
    uvicorn.run(app, host=host, port=port)

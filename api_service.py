# -*- coding: utf-8 -*-
import json
import asyncio
import sys
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, File, UploadFile, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from main import PipelineProcessor, load_config, CONFIG_PATH
from bilibili_uploader import BilibiliUploader
from bilibili_auth import BilibiliAuth
from cleanup_manager import CleanupManager

app = FastAPI(
    title="Music Video Pipeline API",
    description="音乐视频自动化合成流水线后台服务。支持网易云推荐获取、视频异步合成、日志实时查询。",
    version="1.0.0"
)

# 挂载静态文件
if getattr(sys, 'frozen', False):
    static_dir = Path(sys._MEIPASS) / "static"
else:
    static_dir = Path(__file__).parent / "static"

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.get("/", summary="主页", tags=["页面"])
async def index():
    """返回可视化 GUI 界面"""
    return FileResponse(static_dir / "index.html")

# 全局处理器状态
class Task:
    def __init__(self, songs, combine=True, auto_upload=False, upload_format_name=""):
        self.id = str(uuid.uuid4())[:8]  # 简短的 8 位 UUID，如 "a1b2c3d4"
        self.songs = songs
        self.combine = combine
        self.auto_upload = auto_upload
        self.upload_format_name = upload_format_name
        self.status = "waiting"  # waiting, running, completed, cancelled, failed
        self.progress = 0
        self.current_status_text = "等待中..."
        self.logs = []
        self.created_at = time.strftime("%H:%M:%S")
        self.final_video_path = ""

    def to_dict(self):
        return {
            "id": self.id,
            "songs_count": len(self.songs),
            "songs_names": [s["name"] for s in self.songs],
            "combine": self.combine,
            "auto_upload": self.auto_upload,
            "upload_format_name": self.upload_format_name,
            "status": self.status,
            "progress": self.progress,
            "current_status_text": self.current_status_text,
            "logs": self.logs[-50:],  # 最多返回最新的 50 条日志
            "created_at": self.created_at,
            "final_video_path": self.final_video_path
        }

class QueueState:
    def __init__(self):
        self.tasks = []

queue_state = QueueState()

class GlobalState:
    processor = None
    
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
import uuid
import time

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

def get_processor():
    if not state.processor:
        config = load_config()
        state.processor = PipelineProcessor(config)
        # 初始化清理管理器
        try:
            state.processor.cleanup_manager = CleanupManager(config)
        except Exception as e:
            print(f"清理管理器初始化失败: {e}")
    return state.processor

@app.get("/health", summary="健康检查", tags=["基础接口"])
def health():
    return {"status": "ok"}

@app.get("/config", summary="获取配置", tags=["配置管理"])
def get_config():
    """读取 config.json 中的当前配置项"""
    return load_config()

@app.post("/config", summary="更新配置", tags=["配置管理"])
def update_config(data: ConfigUpdate):
    """更新网易云 Cookie 并实时应用到流水线处理器"""
    config = load_config()
    config["netease_cookie"] = data.netease_cookie
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    state.processor = PipelineProcessor(config)
    return {"status": "success"}

@app.get("/search", summary="搜索歌曲", tags=["音乐数据"])
async def search_songs(q: str, limit: int = 20, offset: int = 0):
    """通过关键词搜索网易云音乐歌曲，支持分页"""
    try:
        proc = get_processor()
        result = await proc.api.search_songs(q, limit=limit, offset=offset)
        return result
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

@app.on_event("startup")
async def startup_event():
    # 启动异步后台任务队列 worker
    asyncio.create_task(task_queue_worker())

async def task_queue_worker():
    while True:
        try:
            # 寻找排在最前面的等待中的任务
            task = next((t for t in queue_state.tasks if t.status == "waiting"), None)
            if not task:
                await asyncio.sleep(1)
                continue

            # 开始运行任务
            task.status = "running"
            task.progress = 0
            task.current_status_text = "初始化任务..."
            
            await run_single_task(task)
            
        except Exception as e:
            print(f"[Queue Worker Error] {e}")
            await asyncio.sleep(1)

async def run_single_task(task: Task):
    from datetime import datetime
    
    def status_logger(msg: str):
        task.current_status_text = msg
        task.logs.append(msg)
        
        # 自动进度百分比分析
        text = msg.lower()
        if "starting processing" in text or "fetch" in text:
            task.progress = 15
        elif "download" in text or "processing song" in text or "下载" in text:
            task.progress = 35
        elif "ffmpeg" in text or "spectrum" in text or "画幅" in text or "频谱" in text:
            task.progress = 60
        elif "stitch" in text or "concat" in text or "stitching" in text or "拼接" in text or "合成" in text:
            task.progress = 80
        elif "upload" in text or "bilibili" in text or "上传" in text:
            task.progress = 95
        
        if "[ok] done!" in text:
            task.progress = 100

    try:
        proc = get_processor()
        proc.set_status_callback(status_logger)
        
        config = load_config()
        today = datetime.now().strftime("%Y%m%d")
        run_dir = Path(config["output_dir"]) / today
        run_dir.mkdir(parents=True, exist_ok=True)
        
        status_logger(f"Starting processing {len(task.songs)} songs...")
        
        def is_cancelled():
            return task.status == "cancelled"
            
        if is_cancelled():
            return
            
        successful_clips = await proc.process_songs(task.songs, run_dir, is_cancelled_callback=is_cancelled)
        
        if is_cancelled():
            status_logger("[FAIL] 任务已被中途取消")
            return
            
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
                except:
                    pass
                status_logger("[FAIL] 任务已被中途取消")
                return
                
            if success:
                task.final_video_path = str(final_path)
                status_logger(f"[OK] Done! Final video: {final_path}")
                proc.save_song_list(task.songs, run_dir)
                
                if task.auto_upload:
                    status_logger("Auto-upload enabled, preparing upload...")
                    try:
                        formats = load_upload_formats()
                        fmt = next((f for f in formats if f["name"] == task.upload_format_name), formats[0] if formats else None)
                        if fmt:
                            title = fmt["title"]
                            desc = fmt["description"]
                            if fmt["description"] == "song_list":
                                desc = "\n".join([f"{i+1}. {s['name']} - {', '.join(s.get('artists', []))}" for i, s in enumerate(task.songs)])
                            elif fmt["description"] == "custom":
                                desc = fmt["description_custom"]
                            
                            cover = ""
                            if fmt["cover"] == "first_song" and task.songs:
                                first = task.songs[0]
                                cover = str(run_dir / f"{first['id']}_cover.png")
                                if not os.path.exists(cover):
                                    cover = ""
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
                                138,
                                cover
                            )
                            if result.get("success") or result.get("bvid"):
                                status_logger(f"[OK] Upload success! bvid: {result.get('bvid', '')}")
                            else:
                                status_logger(f"[FAIL] Upload failed: {result.get('error', str(result))}")
                        else:
                            status_logger("[FAIL] No upload format found")
                    except Exception as ue:
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
                
        if task.status == "running":
            task.status = "completed"
            task.progress = 100
            
    except Exception as e:
        status_logger(f"[FAIL] Error occurred: {str(e)}")
        task.status = "failed"

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
    """
    接收歌曲列表，启动后台异步任务进行下载、封面美化、律动提取、歌词合成及视频拼接。
    将任务加入等待队列中，支持多个任务顺序执行。
    """
    task = Task(
        songs=req.songs,
        combine=req.combine,
        auto_upload=req.auto_upload,
        upload_format_name=req.upload_format_name
    )
    queue_state.tasks.append(task)
    return {"status": "started", "task_id": task.id}

@app.post("/tasks/{task_id}/cancel", summary="取消排队或执行中的任务", tags=["任务执行"])
def cancel_task(task_id: str):
    task = next((t for t in queue_state.tasks if t.id == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    if task.status in ["completed", "cancelled", "failed"]:
        return {"status": "success", "message": "Task already finished"}
        
    task.status = "cancelled"
    task.current_status_text = "任务已被用户取消"
    task.logs.append("[i] 任务已被用户中途取消。")
    
    # 如果该任务正在运行，立即终止所有当前正在运行的 FFmpeg 进程
    from video_maker import _cleanup_ffmpeg_processes
    try:
        _cleanup_ffmpeg_processes()
    except Exception as e:
        print(f"Error cleaning up FFmpeg: {e}")
        
    return {"status": "success"}

@app.delete("/tasks/{task_id}", summary="删除任务列表中的任务", tags=["任务执行"])
def delete_task(task_id: str):
    task = next((t for t in queue_state.tasks if t.id == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    # 如果是运行中或等待中，先执行取消
    if task.status in ["running", "waiting"]:
        cancel_task(task_id)
        
    queue_state.tasks.remove(task)
    return {"status": "success"}

@app.post("/generate_by_query", summary="根据歌名直接合成", tags=["任务执行"])
async def generate_by_query(req: QueryRequest):
    """
    AI 直接调用入口：输入歌名关键词，系统自动搜索最匹配的结果并直接开始视频合成。
    """
    if state.is_running:
        raise HTTPException(status_code=400, detail="Pipeline is already running")
    
    try:
        proc = get_processor()
        results = await proc.api.search_songs(req.query, limit=1)
        if not results:
            raise HTTPException(status_code=404, detail="未找到相关歌曲")
        
        # 复用现有生成逻辑
        return await generate_video(GenerateRequest(songs=results, combine=req.combine))
    except Exception as e:
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=500, detail=str(e))

# ================== 网易云音乐扫码登录接口 ==================
class NeteaseCheckLoginRequest(BaseModel):
    unikey: str = Field(..., description="网易云扫码 unikey")

@app.get("/netease/qrcode", summary="获取网易云登录二维码", tags=["网易云登录"])
async def get_netease_qrcode():
    """获取网易云登录二维码，返回图片 URL 和 unikey"""
    try:
        import qrcode
        from pyncm.apis import login
        
        # 1. 创建网易云扫码 unikey
        res_key = await asyncio.to_thread(login.LoginQrcodeUnikey)
        if res_key.get("code") != 200:
            raise Exception(f"网易云创建Unikey失败: {res_key}")
            
        unikey = res_key["unikey"]
        
        # 2. 获取扫码 URL
        qr_url = login.GetLoginQRCodeUrl(unikey)
        
        # 3. 生成二维码图片并保存
        qr_img = qrcode.make(qr_url)
        qr_path = Path(__file__).parent / "static" / "netease_login_qr.png"
        qr_path.parent.mkdir(parents=True, exist_ok=True)
        qr_img.save(str(qr_path))
        
        return {
            "qr_path": "/static/netease_login_qr.png",
            "unikey": unikey
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/netease/check-login", summary="检查网易云扫码状态", tags=["网易云登录"])
async def check_netease_login(req: NeteaseCheckLoginRequest):
    """传入 unikey 轮询扫码状态。扫码成功后自动保存 Cookie 并应用到系统"""
    try:
        from pyncm.apis import login
        from pyncm import GetCurrentSession
        
        # 1. 检查状态
        res = await asyncio.to_thread(login.LoginQrcodeCheck, req.unikey)
        code = res.get("code", 801)
        
        if code == 803:
            # 授权登录成功
            session = GetCurrentSession()
            music_u = session.cookies.get("MUSIC_U", domain=".music.163.com") or session.cookies.get("MUSIC_U")
            
            if not music_u:
                music_u = res.get("cookie", "")
                
            if music_u:
                # 2. 自动保存到 config.json 配置文件
                config = load_config()
                config["netease_cookie"] = music_u
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
                
                # 3. 重新实例化流水线处理器以便即时生效
                state.processor = PipelineProcessor(config)
                try:
                    state.processor.cleanup_manager = CleanupManager(config)
                except Exception:
                    pass
                    
                return {
                    "success": True,
                    "status": "success",
                    "music_u": music_u,
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
@app.get("/bilibili/qrcode", summary="获取 B 站登录二维码", tags=["B站投稿"])
async def get_bilibili_qr():
    """生成 B 站登录二维码图片，返回图片 URL 和验证凭证 raw_json"""
    try:
        auth = BilibiliAuth()
        res = auth.get_qr_info()
        if res["success"]:
            # 将二维码图片复制到static目录以便前端访问
            qr_path = Path(res["qr_path"])
            static_path = Path(__file__).parent / "static" / qr_path.name
            import shutil
            shutil.copy2(qr_path, static_path)
            return {
                "qr_path": f"/static/{qr_path.name}",
                "raw_json": res["raw_json"]
            }
        return {"error": res.get("error", "未知错误")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/bilibili/check-login", summary="检查扫码登录状态", tags=["B站投稿"])
async def check_bilibili_login(raw_json: str = Body(...)):
    """传入 get_bilibili_qr 返回的 raw_json，检查是否扫码成功"""
    try:
        auth = BilibiliAuth()
        res = await asyncio.to_thread(auth.verify_login, raw_json)
        return {"success": res["success"], "error": res.get("error")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/bilibili/check-cookie", summary="检查当前 Cookie 登录状态", tags=["B站投稿"])
async def check_cookie_status():
    """检查 cookies.json 是否存在且有效"""
    try:
        auth = BilibiliAuth()
        import os
        if os.path.exists(auth.cookie_path):
            # 简单检查文件大小，大于100字节认为有效
            if os.path.getsize(auth.cookie_path) > 100:
                return {"logged_in": True}
        return {"logged_in": False}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/bilibili/upload-file", summary="上传视频文件到服务器临时目录", tags=["B站投稿"])
async def upload_video_file(file: UploadFile = File(...)):
    """接收前端上传的视频文件，保存到临时目录并返回路径"""
    try:
        import tempfile
        import uuid
        import os
        import time
        import shutil
        
        # 创建项目专用临时目录
        temp_dir = Path(tempfile.gettempdir()) / "music_video_uploads"
        temp_dir.mkdir(exist_ok=True)
        
        # 自动清理旧文件（超过24小时）
        cleanup_old_files(temp_dir, max_age_hours=24)
        
        # 保留原始扩展名
        ext = Path(file.filename).suffix if file.filename else ".mp4"
        file_id = str(uuid.uuid4())
        file_path = temp_dir / f"{file_id}{ext}"
        
        # 保存文件
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
        
        return {"path": str(file_path), "success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def cleanup_old_files(directory: Path, max_age_hours: int = 24):
    """清理指定目录中超过指定时间的文件"""
    try:
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        
        for file_path in directory.iterdir():
            if file_path.is_file():
                file_age = current_time - file_path.stat().st_mtime
                if file_age > max_age_seconds:
                    try:
                        file_path.unlink()
                    except Exception:
                        pass
    except Exception:
        pass  # 清理失败不影响主流程

@app.post("/bilibili/upload", summary="上传视频到 B 站", tags=["B站投稿"])
async def upload_to_bilibili(req: BilibiliUploadRequest):
    """调用 biliup 上传视频到 B 站音乐综合分区（tid=138）"""
    try:
        uploader = BilibiliUploader(load_config())
        result = uploader.upload(
            video_path=req.video_path,
            title=req.title,
            description=req.description,
            tags=req.tags,
            cover=req.cover
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ================== 上传格式管理 ==================
UPLOAD_FORMATS_FILE = Path(__file__).parent / "upload_formats.json"

def load_upload_formats():
    if UPLOAD_FORMATS_FILE.exists():
        with open(UPLOAD_FORMATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    # 默认格式
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
    with open(UPLOAD_FORMATS_FILE, "w", encoding="utf-8") as f:
        json.dump(formats, f, indent=2, ensure_ascii=False)

@app.get("/bilibili/upload-formats", summary="获取所有上传格式", tags=["B站投稿"])
def get_upload_formats():
    return load_upload_formats()

@app.post("/bilibili/upload-formats", summary="添加或更新上传格式", tags=["B站投稿"])
def add_upload_format(format: UploadFormat):
    formats = load_upload_formats()
    # 更新同名格式，否则新增
    idx = next((i for i, f in enumerate(formats) if f["name"] == format.name), -1)
    if idx >= 0:
        formats[idx] = format.dict()
    else:
        formats.append(format.dict())
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
            usage = proc.cleanup_manager.get_disk_usage()
            return usage
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
        
        # 更新清理配置
        if req:
            proc.cleanup_manager.max_age_days = req.max_age_days
            proc.cleanup_manager.max_total_size_gb = req.max_total_size_gb
        
        stats = proc.cleanup_manager.cleanup_old_files()
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
    port = config.get("api_port", 8000)
    uvicorn.run(app, host="127.0.0.1", port=port)

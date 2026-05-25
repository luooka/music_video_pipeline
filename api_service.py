# -*- coding: utf-8 -*-
import json
import asyncio
import sys
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, File, UploadFile
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
class GlobalState:
    processor = None
    is_running = False
    current_status = "Idle"
    logs = []

state = GlobalState()

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
async def search_songs(q: str):
    """通过关键词搜索网易云音乐歌曲"""
    try:
        proc = get_processor()
        songs = await proc.api.search_songs(q)
        return {"songs": songs}
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

@app.get("/status", summary="查询合成状态", tags=["任务执行"])
def get_status():
    """查询当前是否有任务正在运行，并返回最新的 20 条实时日志"""
    return {
        "is_running": state.is_running,
        "current_status": state.current_status,
        "logs": state.logs[-20:]
    }

def status_logger(msg: str):
    state.current_status = msg
    state.logs.append(msg)

@app.post("/generate", summary="开始异步合成视频", tags=["任务执行"])
async def generate_video(req: GenerateRequest):
    """
    接收歌曲列表，启动后台异步任务进行下载、封面美化、律动提取、歌词合成及视频拼接。
    系统保证同一时间只有一个合成任务在运行。
    """
    if state.is_running:
        raise HTTPException(status_code=400, detail="Pipeline is already running")
    
    state.is_running = True
    state.logs = []
    
    async def run_task():
        try:
            from datetime import datetime
            proc = get_processor()
            proc.set_status_callback(status_logger)
            
            config = load_config()
            today = datetime.now().strftime("%Y%m%d")
            run_dir = Path(config["output_dir"]) / today
            run_dir.mkdir(parents=True, exist_ok=True)
            
            status_logger(f"Starting processing {len(req.songs)} songs...")
            successful_clips = await proc.process_songs(req.songs, run_dir)
            
            if req.combine and successful_clips:
                status_logger("Processing Stitching final video...")
                final_path = run_dir / f"daily_music_{today}.mp4"
                if proc.video_maker.concat_clips(successful_clips, str(final_path)):
                    status_logger(f"[OK] Done! Final video: {final_path}")
                    # 生成歌单文本
                    proc.save_song_list(req.songs, run_dir)
                    
                    # 自动上传
                    if req.auto_upload:
                        status_logger("Auto-upload enabled, preparing upload...")
                        try:
                            from bilibili_uploader import BilibiliUploader
                            formats = load_upload_formats()
                            fmt = next((f for f in formats if f["name"] == req.upload_format_name), formats[0] if formats else None)
                            if fmt:
                                # 构建标题和简介
                                title = fmt["title"]
                                desc = fmt["description"]
                                if fmt["description"] == "song_list":
                                    desc = "\n".join([f"{i+1}. {s['name']} - {', '.join(s.get('artists', []))}" for i, s in enumerate(req.songs)])
                                elif fmt["description"] == "custom":
                                    desc = fmt["description_custom"]
                                # 获取封面
                                cover = ""
                                if fmt["cover"] == "first_song" and req.songs:
                                    first = req.songs[0]
                                    cover = str(run_dir / f"{first['id']}_cover.png")
                                    if not os.path.exists(cover):
                                        cover = ""
                                elif fmt["cover"] == "custom":
                                    cover = fmt["cover_custom"]
                                
                                status_logger(f"Uploading to Bilibili: {title}")
                                uploader = BilibiliUploader(config)
                                result = uploader.upload(
                                    video_path=str(final_path),
                                    title=title,
                                    description=desc,
                                    tags=fmt["tags"],
                                    cover=cover
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
            else:
                status_logger("[OK] Processing finished (No stitching)")
                
        except Exception as e:
            status_logger(f"[FAIL] Error occurred: {str(e)}")
        finally:
            state.is_running = False

    asyncio.create_task(run_task())
    return {"status": "started"}

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
async def check_bilibili_login(raw_json: str):
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

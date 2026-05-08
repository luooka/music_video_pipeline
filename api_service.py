# -*- coding: utf-8 -*-
import json
import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pathlib import Path
from main import PipelineProcessor, load_config, CONFIG_PATH

import sys
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from pydantic import BaseModel, Field
from pathlib import Path
from main import PipelineProcessor, load_config, CONFIG_PATH

import sys
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

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

class QueryRequest(BaseModel):
    query: str = Field(..., description="要搜索并合成的歌曲名或关键词")
    combine: bool = Field(True, description="处理完成后是否自动拼接为长视频")

def get_processor():
    if not state.processor:
        config = load_config()
        state.processor = PipelineProcessor(config)
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

if __name__ == "__main__":
    import uvicorn
    config = load_config()
    port = config.get("api_port", 8000)
    uvicorn.run(app, host="127.0.0.1", port=port)

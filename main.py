import asyncio
import argparse
import json
import sys
import os
import re
import platform
import httpx
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from netease_api import NeteaseAPI
from video_maker import VideoMaker
from cleanup_manager import setup_cleanup_scheduler

import logging
from logging.handlers import RotatingFileHandler

# 控制台编码适配 - 使用局部包装器而非全局修改
class ConsoleEncodingWrapper:
    """包装器，在输出时处理编码问题而不修改全局设置"""
    
    def __init__(self, original_stream, encoding='utf-8', errors='replace'):
        self.original_stream = original_stream
        self.encoding = encoding
        self.errors = errors
    
    def write(self, text):
        if self.original_stream is None:
            return
        if isinstance(text, str):
            try:
                # 尝试使用原始编码
                self.original_stream.write(text)
            except UnicodeEncodeError:
                # 如果失败，使用指定编码
                encoded = text.encode(self.encoding, errors=self.errors).decode(self.encoding)
                self.original_stream.write(encoded)
        else:
            self.original_stream.write(text)
    
    def flush(self):
        if self.original_stream is not None:
            self.original_stream.flush()
    
    def __getattr__(self, name):
        if self.original_stream is None:
            raise AttributeError(name)
        return getattr(self.original_stream, name)

# 仅在需要时包装标准输出
def setup_console_encoding():
    """设置控制台编码，使用包装器而非全局修改"""
    if sys.platform == "win32":
        # Windows: 使用chcp命令设置控制台代码页
        try:
            import os
            os.system("chcp 65001 >nul 2>nul")
        except:
            pass
        
        # 包装标准输出
        if sys.stdout is not None and not isinstance(sys.stdout, ConsoleEncodingWrapper):
            sys.stdout = ConsoleEncodingWrapper(sys.stdout, encoding='utf-8', errors='replace')
        if sys.stderr is not None and not isinstance(sys.stderr, ConsoleEncodingWrapper):
            sys.stderr = ConsoleEncodingWrapper(sys.stderr, encoding='utf-8', errors='replace')
    else:
        # Linux/macOS: 通常已经支持UTF-8
        pass

# 调用设置函数
setup_console_encoding()

if getattr(sys, 'frozen', False):
    # 打包模式下，配置文件放在 exe 同级目录
    CONFIG_PATH = Path(sys.executable).parent / "config.json"
else:
    # 开发模式下
    CONFIG_PATH = Path(__file__).parent / "config.json"

# 在 CONFIG_PATH 确定后初始化日志，确保日志文件始终写在 config.json 同级目录
_log_path = CONFIG_PATH.parent / "pipeline.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr),
        RotatingFileHandler(str(_log_path), maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
    ]
)
logger = logging.getLogger('pipeline')

DEFAULT_CONFIG = {
    "netease_cookie": "",
    "netease_api_base": "https://netease-music.api.harisfox.com",
    "api_port": 8000,
    "output_dir": "./output",
    "video_width": 1920,
    "video_height": 1080,
    "video_fps": 24,
    "bilibili_tid": 138,
    "bilibili_tags": [
        "音乐",
        "网易云音乐",
        "动态歌词",
        "AI生成"
    ],
    "bilibili_desc_template": "本视频由 AI 自动生成。\n标题：{title}\n\n#网易云音乐 #AI视频 #动态歌词",
    "visual": {
        "blur_radius": 40,
        "blend_alpha": 0.5,
        "title_font_size": 70,
        "artist_font_size": 35,
        "text_x": 1050,
        "text_start_y": 400,
        "text_cached_y": 450
    },
    "video": {
        "threads": 1,
        "preset": "ultrafast",
        "audio_bitrate": "128k",
        "audio_channels": 2,
        "audio_sample_rate": 44100,
        "spectrum_size": "800x75"
    },
    "font": {
        "paths": [
            "msyh.ttc",
            "simhei.ttf",
            "C:/Windows/Fonts/msyh.ttc"
        ],
        "macos_paths": [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc"
        ],
        "linux_font_names": [
            "Noto Sans CJK SC",
            "WenQuanYi Micro Hei"
        ]
    },
    "cleanup": {
        "max_age_days": 7,           # 保留最近7天的文件
        "max_total_size_gb": 10,     # 最大占用10GB空间
        "cleanup_on_start": True     # 启动时自动清理
    }
}

def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
    return DEFAULT_CONFIG

class PipelineProcessor:
    def __init__(self, config: dict):
        self.config = config
        self.w = config.get("video_width", 1920)
        self.h = config.get("video_height", 1080)
        self.fps = config.get("video_fps", 24)
        self.api = NeteaseAPI(config.get("netease_cookie", ""))
        self.video_maker = VideoMaker(self.w, self.h, self.fps, self.config)
        self.status_callback = None
        self.cleanup_manager = None  # 延迟初始化，避免循环导入

    def set_status_callback(self, callback):
        self.status_callback = callback

    def _log(self, msg: str):
        logger.info(msg)
        
        if self.status_callback:
            try:
                self.status_callback(msg)
            except:
                pass

    async def fetch_recommendations(self, demo: bool = False, count: int = 10):
        if demo:
            res = await self.api.search_songs("热门歌曲", limit=count)
            return res.get("songs", []) if isinstance(res, dict) else res
        return await self.api.get_daily_recommend()

    async def create_visuals(self, song: dict, bg_path: str, cover_path: str):
        album_pic_url = song.get("album_pic")
        img_raw = None
        if album_pic_url:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(album_pic_url)
                    if resp.status_code == 200:
                        from io import BytesIO
                        img_raw = Image.open(BytesIO(resp.content)).convert("RGB")
            except Exception as e:
                self._log(f"  ⚠️ 下载封面失败: {e}")

        if not img_raw:
            img_raw = Image.new("RGB", (800, 800), (30, 30, 60))

        # 1. 保存清晰封面
        cover_img = img_raw.resize((800, 800), Image.Resampling.LANCZOS)
        cover_img.save(cover_path)

        # 2. 生成模糊背景
        bg_img = img_raw.copy()
        img_ratio = bg_img.width / bg_img.height
        screen_ratio = self.w / self.h
        if img_ratio > screen_ratio:
            nb_h, nb_w = self.h, int(self.h * img_ratio)
        else:
            nb_w, nb_h = self.w, int(self.w / img_ratio)
        
        bg_img = bg_img.resize((nb_w, nb_h), Image.Resampling.LANCZOS)
        left, top = (nb_w - self.w) // 2, (nb_h - self.h) // 2
        bg_img = bg_img.crop((left, top, left + self.w, top + self.h))
        bg_img = bg_img.filter(ImageFilter.GaussianBlur(radius=self.config.get("visual", {}).get("blur_radius", 40)))
        enhancer = Image.new("RGB", (self.w, self.h), (0, 0, 0))
        bg_img = Image.blend(bg_img, enhancer, self.config.get("visual", {}).get("blend_alpha", 0.5))
        
        # 3. 绘制文字 (增加自动换行处理)
        draw = ImageDraw.Draw(bg_img)
        name, artists_str = song["name"], ", ".join(song.get("artists", []))
        
        try:
            font_cfg = self.config.get("font", {})
            if platform.system() == "Darwin":
                font_paths = font_cfg.get("macos_paths", [])
            elif platform.system() == "Linux":
                font_paths = font_cfg.get("linux_font_names", [])
            else:
                font_paths = font_cfg.get("paths", [])
            font, font_s = None, None
            for fp in font_paths:
                try:
                    font = ImageFont.truetype(fp, self.config.get("visual", {}).get("title_font_size", 70)) # 稍微缩小字号以适应长标题
                    font_s = ImageFont.truetype(fp, self.config.get("visual", {}).get("artist_font_size", 35))
                    break
                except: continue
            if not font: raise Exception()
        except:
            font = ImageFont.load_default(size=self.config.get("visual", {}).get("title_font_size", 70)); font_s = ImageFont.load_default(size=self.config.get("visual", {}).get("artist_font_size", 35))

        def draw_wrapped_text(draw, text, font, start_y, max_width, fill):
            lines = []
            words = list(text) 
            current_line = ""
            for word in words:
                test_line = current_line + word
                w = font.getbbox(test_line)[2]
                if w <= max_width:
                    current_line = test_line
                else:
                    lines.append(current_line)
                    current_line = word
            lines.append(current_line)
            
            curr_y = start_y
            for line in lines:
                draw.text((self.config.get("visual", {}).get("text_x", 1050), curr_y), line, font=font, fill=fill)
                curr_y += font.getbbox(line)[3] + 15
            return curr_y

        last_y = draw_wrapped_text(draw, name, font, 150, 800, (255, 255, 255))
        final_y = draw_wrapped_text(draw, artists_str, font_s, last_y + 10, 800, (200, 200, 200))

        bg_img.save(bg_path)
        return final_y # 返回文字区域结束的 Y 坐标

    def lrc_to_ass(self, lrc_text: str, ass_path: str, margin_v: int = 400):
        if not lrc_text: return False
        lines = lrc_text.splitlines()
        entries = []
        pattern = re.compile(r'\[(\d+):(\d+)[.:](\d+)\](.*)')
        for line in lines:
            match = pattern.match(line)
            if match:
                m, s, ms, text = match.groups()
                time_ms = int(m) * 60000 + int(s) * 1000 + int(ms.ljust(3, '0')[:3])
                entries.append({"time": time_ms, "text": text.strip()})
        if not entries: return False
        entries.sort(key=lambda x: x["time"])
        
        # Alignment=7 代表左上对齐，这样 MarginV 就是距离顶部的绝对像素值
        header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,微软雅黑,45,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,1,7,1050,150,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(header)
            for i, entry in enumerate(entries):
                start_ms = entry["time"]
                next_time = entries[i+1]["time"] if i + 1 < len(entries) else start_ms + 4000
                end_ms = max(start_ms + 10, next_time - 50)
                
                def fmt(ms):
                    return f"{ms//3600000:01d}:{(ms%3600000)//60000:02d}:{(ms%60000)//1000:02d}.{(ms%1000)//10:02d}"
                f.write(f"Dialogue: 0,{fmt(start_ms)},{fmt(end_ms)},Default,,0,0,0,,{entry['text']}\n")
        return True

    def save_song_list(self, songs: list, run_dir: Path):
        """生成歌曲列表文本文件"""
        list_file = run_dir / "song_list.txt"
        content = ""
        for i, song in enumerate(songs, 1):
            artists = ", ".join(song.get("artists", []))
            content += f"{i}:{song['name']} - {artists}\n"
        
        list_file.write_text(content, encoding="utf-8")
        self._log(f"  📝 已生成歌单列表: {list_file}")
        return list_file

    async def process_songs(self, songs: list, run_dir: Path, is_cancelled_callback=None):
        audio_dir, images_dir, lyrics_dir, clips_dir = [run_dir / d for d in ["audio", "images", "lyrics", "clips"]]
        for d in [audio_dir, images_dir, lyrics_dir, clips_dir]: d.mkdir(parents=True, exist_ok=True)

        successful_clips = []
        failed_songs = []
        for i, song in enumerate(songs, 1):
            if is_cancelled_callback and is_cancelled_callback():
                self._log("检测到取消信号，终止后续歌曲合成流程。")
                break
            self._log(f"\n[{i}/{len(songs)}] [SONG] {song['name']} - {', '.join(song['artists'])}")
            
            # 1. 音频
            audio_path = audio_dir / f"{song['id']}.mp3"
            if not audio_path.exists():
                self._log("  -> 下载音频...")
                ret = await self.api.download_song(song["id"], song["name"], str(audio_dir))
                if not ret:
                    failed_songs.append(f"{song['name']} (ID: {song['id']})")
                    logger.warning(f"  [FAIL] 下载失败: {song['name']} (ID: {song['id']})")
                    continue
            else: self._log("  -> 正在使用音频缓存 [OK]")

            # 2. 视觉
            bg_path, cover_path = images_dir / f"{song['id']}_bg.png", images_dir / f"{song['id']}_cover.png"
            text_end_y = self.config.get("visual", {}).get("text_start_y", 400) # 默认安全高度
            if not bg_path.exists() or not cover_path.exists():
                self._log("  -> 生成播放器 UI 资源...")
                res_y = await self.create_visuals(song, str(bg_path), str(cover_path))
                if res_y: text_end_y = res_y
            else: 
                self._log("  -> 正在使用资源缓存 [OK]")
                # 如果使用缓存，这里暂时使用保守的固定高度或重新计算（简单处理给个 450）
                text_end_y = self.config.get("visual", {}).get("text_cached_y", 450)

            # 3. 歌词
            lrc_path, ass_path = lyrics_dir / f"{song['id']}.lrc", lyrics_dir / f"{song['id']}.ass"
            has_sub = False
            if not lrc_path.exists():
                text = await self.api.get_lyrics(song["id"])
                if text: lrc_path.write_text(text, encoding="utf-8")
            
            if lrc_path.exists():
                if not ass_path.exists():
                    # 动态传入 MarginV，保证歌词在文字下方 40px 处
                    if self.lrc_to_ass(lrc_path.read_text(encoding="utf-8"), str(ass_path), margin_v=int(text_end_y + 40)): 
                        has_sub = True
                else: has_sub = True

            # 4. 合成
            clip_path = clips_dir / f"clip_{i:02d}_{song['id']}.mp4"
            if not clip_path.exists():
                self._log("  -> 合成播放器视频片段...")
                loop = asyncio.get_running_loop()
                res = await loop.run_in_executor(
                    None,
                    self.video_maker.create_clip,
                    str(bg_path),
                    str(audio_path),
                    str(clip_path),
                    str(ass_path) if has_sub else None,
                    str(cover_path),
                    song.get("duration_ms", 0) / 1000
                )
                if res: successful_clips.append(str(clip_path))
            else:
                self._log("  -> 正在使用视频缓存 [OK]")
                successful_clips.append(str(clip_path))

        if failed_songs:
            logger.warning(f"\n===== {len(failed_songs)} 首歌曲下载失败 =====")
            for fs in failed_songs:
                logger.warning(f"  - {fs}")

        return successful_clips

async def run_cli(args):
    config = load_config()
    proc = PipelineProcessor(config)
    
    # 启动清理管理器
    try:
        from cleanup_manager import CleanupManager
        proc.cleanup_manager = CleanupManager(config)
        if proc.cleanup_manager.cleanup_on_start:
            print("🧹 清理旧文件中...")
            stats = proc.cleanup_manager.cleanup_old_files()
            if stats["deleted_files"] > 0:
                print(f"  → 删除 {stats['deleted_files']} 个文件，释放 {stats['freed_space_mb']:.1f} MB")
    except Exception as e:
        print(f"⚠️  清理管理器初始化失败: {e}")
    
    today = datetime.now().strftime("%Y%m%d")
    run_dir = Path(config["output_dir"]) / today
    run_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60 + "\n🎬 Music Video Pipeline - MVP\n" + "=" * 60)
    
    songs = await proc.fetch_recommendations(args.demo, args.count or 10)
    songs = songs[:(args.count or 10)]
    
    clips = await proc.process_songs(songs, run_dir)
    if not clips: return print("\n❌ 没有成功生成任何片段")

    print(f"\nTape Step 3: 拼接 {len(clips)} 个片段...")
    final_path = run_dir / f"daily_music_{today}.mp4"
    if proc.video_maker.concat_clips(clips, str(final_path)):
        print(f"  ✅ 最终视频: {final_path}")
        # 生成歌单文本
        proc.save_song_list(songs, run_dir)
        
        # 显示磁盘使用情况
        if proc.cleanup_manager:
            usage = proc.cleanup_manager.get_disk_usage()
            print(f"\n💾 磁盘使用情况:")
            print(f"  总大小: {usage['total_size_gb']:.2f} GB ({usage['total_size_mb']:.0f} MB)")
            print(f"  文件数: {usage['file_count']}")
            if usage['oldest_file']:
                print(f"  最旧文件: {usage['oldest_file']}")
            if usage['newest_file']:
                print(f"  最新文件: {usage['newest_file']}")
    else: print("  ❌ 拼接失败")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--count", type=int)
    p.add_argument("--test", action="store_true")
    p.add_argument("--demo", action="store_true")
    args = p.parse_args()
    if args.test: args.count = 3
    asyncio.run(run_cli(args))

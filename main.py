import asyncio
import argparse
import json
import sys
import os
import re
import httpx
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from netease_api import NeteaseAPI
from video_maker import VideoMaker

# Windows 控制台编码适配
if sys.platform == "win32":
    try:
        # 强制配置 stdout/stderr 为 utf-8，并允许替换非法字符
        # 这与 gui_client.py 中的 chcp 65001 保持一致
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
else:
    # Linux/macOS 平台：统一使用 UTF-8
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if getattr(sys, 'frozen', False):
    # 打包模式下，配置文件放在 exe 同级目录
    CONFIG_PATH = Path(sys.executable).parent / "config.json"
else:
    # 开发模式下
    CONFIG_PATH = Path(__file__).parent / "config.json"

DEFAULT_CONFIG = {
    "netease_cookie": "",
    "netease_api_base": "https://netease-music.api.harisfox.com",
    "api_port": 8000,
    "output_dir": "./output",
    "video_width": 1920,
    "video_height": 1080,
    "video_fps": 24,
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
        self.video_maker = VideoMaker(self.w, self.h, self.fps)
        self.status_callback = None

    def set_status_callback(self, callback):
        self.status_callback = callback

    def _log(self, msg: str):
        # 强制将日志输出到 stderr，并确保编码转义安全
        try:
            print(msg, file=sys.stderr)
        except UnicodeEncodeError:
            print(msg.encode('ascii', 'backslashreplace').decode('ascii'), file=sys.stderr)
        
        if self.status_callback:
            try:
                self.status_callback(msg)
            except:
                pass

    async def fetch_recommendations(self, demo: bool = False, count: int = 10):
        if demo:
            return await self.api.search_songs("热门歌曲", limit=count)
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
        bg_img = bg_img.filter(ImageFilter.GaussianBlur(radius=40))
        enhancer = Image.new("RGB", (self.w, self.h), (0, 0, 0))
        bg_img = Image.blend(bg_img, enhancer, 0.5)
        
        # 3. 绘制文字 (增加自动换行处理)
        draw = ImageDraw.Draw(bg_img)
        name, artists_str = song["name"], ", ".join(song.get("artists", []))
        
        try:
            font_paths = ["msyh.ttc", "simhei.ttf", "C:/Windows/Fonts/msyh.ttc"]
            font, font_s = None, None
            for fp in font_paths:
                try:
                    font = ImageFont.truetype(fp, 70) # 稍微缩小字号以适应长标题
                    font_s = ImageFont.truetype(fp, 35)
                    break
                except: continue
            if not font: raise Exception()
        except:
            font = ImageFont.load_default(size=70); font_s = ImageFont.load_default(size=35)

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
                draw.text((1050, curr_y), line, font=font, fill=fill)
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

    async def process_songs(self, songs: list, run_dir: Path):
        audio_dir, images_dir, lyrics_dir, clips_dir = [run_dir / d for d in ["audio", "images", "lyrics", "clips"]]
        for d in [audio_dir, images_dir, lyrics_dir, clips_dir]: d.mkdir(parents=True, exist_ok=True)

        successful_clips = []
        for i, song in enumerate(songs, 1):
            self._log(f"\n[{i}/{len(songs)}] [SONG] {song['name']} - {', '.join(song['artists'])}")
            
            # 1. 音频
            audio_path = audio_dir / f"{song['id']}.mp3"
            if not audio_path.exists():
                self._log("  -> 下载音频...")
                ret = await self.api.download_song(song["id"], song["name"], str(audio_dir))
                if not ret: continue
            else: self._log("  -> 正在使用音频缓存 [OK]")

            # 2. 视觉
            bg_path, cover_path = images_dir / f"{song['id']}_bg.png", images_dir / f"{song['id']}_cover.png"
            text_end_y = 400 # 默认安全高度
            if not bg_path.exists() or not cover_path.exists():
                self._log("  -> 生成播放器 UI 资源...")
                res_y = await self.create_visuals(song, str(bg_path), str(cover_path))
                if res_y: text_end_y = res_y
            else: 
                self._log("  -> 正在使用资源缓存 [OK]")
                # 如果使用缓存，这里暂时使用保守的固定高度或重新计算（简单处理给个 450）
                text_end_y = 450

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
            bg_path, cover_path = images_dir / f"{song['id']}_bg.png", images_dir / f"{song['id']}_cover.png"
            if not bg_path.exists() or not cover_path.exists():
                self._log("  -> 生成播放器 UI 资源...")
                await self.create_visuals(song, str(bg_path), str(cover_path))
            else: self._log("  -> 正在使用资源缓存 [OK]")

            # 4. 合成
            clip_path = clips_dir / f"clip_{i:02d}_{song['id']}.mp4"
            if not clip_path.exists():
                self._log("  -> 合成播放器视频片段...")
                res = self.video_maker.create_clip(str(bg_path), str(audio_path), str(clip_path), 
                                                str(ass_path) if has_sub else None, str(cover_path), 
                                                song.get("duration_ms", 0) / 1000)
                if res: successful_clips.append(str(clip_path))
            else:
                self._log("  -> 正在使用视频缓存 [OK]")
                successful_clips.append(str(clip_path))

        return successful_clips

async def run_cli(args):
    config = load_config()
    proc = PipelineProcessor(config)
    
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
    else: print("  ❌ 拼接失败")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--count", type=int)
    p.add_argument("--test", action="store_true")
    p.add_argument("--demo", action="store_true")
    args = p.parse_args()
    if args.test: args.count = 3
    asyncio.run(run_cli(args))

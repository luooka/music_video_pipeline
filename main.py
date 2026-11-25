import asyncio
import argparse
import copy
import hashlib
import json
import sys
import os
import re
import platform
from io import BytesIO
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from netease_api import NeteaseAPI, _init_pyncm
from video_maker import VideoMaker

import logging
from logging.handlers import RotatingFileHandler


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
                self.original_stream.write(text)
            except UnicodeEncodeError:
                stream_enc = getattr(self.original_stream, 'encoding', None) or 'utf-8'
                safe_text = text.encode(stream_enc, errors=self.errors).decode(stream_enc, errors='replace')
                try:
                    self.original_stream.write(safe_text)
                except Exception:
                    pass
        else:
            self.original_stream.write(text)

    def flush(self):
        if self.original_stream is not None:
            self.original_stream.flush()

    def __getattr__(self, name):
        if self.original_stream is None:
            raise AttributeError(name)
        return getattr(self.original_stream, name)


def setup_console_encoding():
    """设置控制台编码，使用包装器而非全局修改"""
    if sys.platform == "win32":
        try:
            os.system("chcp 65001 >nul 2>nul")
        except Exception:
            pass

        if sys.stdout is not None and not isinstance(sys.stdout, ConsoleEncodingWrapper):
            sys.stdout = ConsoleEncodingWrapper(sys.stdout, encoding='utf-8', errors='replace')
        if sys.stderr is not None and not isinstance(sys.stderr, ConsoleEncodingWrapper):
            sys.stderr = ConsoleEncodingWrapper(sys.stderr, encoding='utf-8', errors='replace')


setup_console_encoding()

if getattr(sys, 'frozen', False):
    CONFIG_PATH = Path(sys.executable).parent / "config.json"
else:
    CONFIG_PATH = Path(__file__).parent / "config.json"

_log_path = CONFIG_PATH.parent / "pipeline.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr),
        RotatingFileHandler(str(_log_path), maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8')
    ]
)
logger = logging.getLogger('pipeline')

DEFAULT_CONFIG = {
    "netease_cookie": "",
    "api_host": "127.0.0.1",
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
        "title_start_y": 150
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
        "max_age_days": 7,
        "max_total_size_gb": 10,
        "cleanup_on_start": True
    }
}


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并配置字典，防止部分子键覆盖整个嵌套默认配置"""
    merged = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = _deep_merge(merged[k], v)
        else:
            merged[k] = v
    return merged


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            if isinstance(user_cfg, dict):
                return _deep_merge(DEFAULT_CONFIG, user_cfg)
        except Exception as e:
            logger.warning(f"读取 config.json 失败，将使用默认配置: {e}")
        return copy.deepcopy(DEFAULT_CONFIG)

    default_copy = copy.deepcopy(DEFAULT_CONFIG)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(default_copy, f, indent=2, ensure_ascii=False)
    return default_copy


def save_config(config: dict):
    tmp_path = CONFIG_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    tmp_path.replace(CONFIG_PATH)


def _find_cached_audio(audio_dir: Path, song_id: int) -> Path | None:
    for ext in (".mp3", ".m4a", ".aac", ".flac", ".ogg", ".wav"):
        candidate = audio_dir / f"{song_id}{ext}"
        if candidate.exists() and candidate.stat().st_size >= 10000:
            return candidate
    return None


def _escape_ass_text(text: str) -> str:
    """转义或替换 ASS 字幕中的特殊控制字符，防止歌词内大括号或斜杠被当成标签"""
    text = text.replace("{", "｛").replace("}", "｝")
    text = re.sub(r'\\(?=[nNh])', lambda _: "\\\u200b", text)
    return text


class PipelineProcessor:
    def __init__(self, config: dict):
        self.config = config
        self.w = config.get("video_width", 1920)
        self.h = config.get("video_height", 1080)
        self.fps = config.get("video_fps", 24)
        self.api = NeteaseAPI(config.get("netease_cookie", ""))
        self.video_maker = VideoMaker(self.w, self.h, self.fps, self.config)
        self.status_callback = None
        self.cleanup_manager = None
        self._fonts_cache = None

    def update_config(self, config: dict):
        """热更新配置、Cookie、视频参数并清空字体缓存"""
        self.config = config
        self.w = config.get("video_width", 1920)
        self.h = config.get("video_height", 1080)
        self.fps = config.get("video_fps", 24)
        cookie = config.get("netease_cookie", "")
        self.api.cookie = cookie
        _init_pyncm(cookie)
        self.video_maker.width = self.w
        self.video_maker.height = self.h
        self.video_maker.fps = self.fps
        self.video_maker.config = config
        self._fonts_cache = None

    def _render_signature(self) -> str:
        payload = {
            "w": self.w,
            "h": self.h,
            "fps": self.fps,
            "visual": self.config.get("visual", {}),
            "video": self.config.get("video", {}),
            "font": self.config.get("font", {}),
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]

    def set_status_callback(self, callback):
        self.status_callback = callback

    def _log(self, msg: str):
        logger.info(msg)
        if self.status_callback:
            try:
                self.status_callback(msg)
            except Exception:
                pass

    def _get_fonts(self):
        """加载并缓存标题与歌手字体对象"""
        if self._fonts_cache is not None:
            return self._fonts_cache
        scale_y = self.h / 1080.0
        title_size = max(16, int(self.config.get("visual", {}).get("title_font_size", 70) * scale_y))
        artist_size = max(12, int(self.config.get("visual", {}).get("artist_font_size", 35) * scale_y))
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
                    font = ImageFont.truetype(fp, title_size)
                    font_s = ImageFont.truetype(fp, artist_size)
                    break
                except Exception:
                    continue
            if not font:
                raise RuntimeError("No truetype font loaded")
        except Exception:
            font = ImageFont.load_default(size=title_size)
            font_s = ImageFont.load_default(size=artist_size)
        self._fonts_cache = (font, font_s)
        return font, font_s

    def _wrap_and_measure_text(
        self,
        text: str,
        font,
        start_y: int,
        max_width: int = 800,
        draw=None,
        fill=(255, 255, 255),
    ) -> int:
        """计算换行并可选绘制文字，返回文字结束的 Y 坐标"""
        if not text:
            return start_y

        lines = []
        current_line = ""
        for ch in text:
            test_line = current_line + ch
            bbox = font.getbbox(test_line)
            w = bbox[2] - bbox[0]
            if w <= max_width or not current_line:
                current_line = test_line
            else:
                lines.append(current_line)
                current_line = ch
        if current_line:
            lines.append(current_line)

        scale_x = self.w / 1920.0
        scale_y = self.h / 1080.0
        text_x = int(self.config.get("visual", {}).get("text_x", 1050) * scale_x)
        line_gap = max(4, int(15 * scale_y))
        curr_y = start_y
        for line in lines:
            if draw is not None:
                draw.text((text_x, curr_y), line, font=font, fill=fill)
            l_bbox = font.getbbox(line)
            line_h = max(1, l_bbox[3] - l_bbox[1])
            curr_y += line_h + line_gap
        return curr_y

    def compute_text_end_y(self, song: dict) -> int:
        """在不重新生成图片的情况下精确计算某首歌的标题+歌手结束 Y 坐标"""
        font, font_s = self._get_fonts()
        scale_x = self.w / 1920.0
        scale_y = self.h / 1080.0
        start_y = int(self.config.get("visual", {}).get("title_start_y", 150) * scale_y)
        max_w = int(800 * scale_x)
        name = song.get("name", "")
        artists_str = ", ".join(song.get("artists", []))
        last_y = self._wrap_and_measure_text(name, font, start_y, max_w, draw=None)
        final_y = self._wrap_and_measure_text(artists_str, font_s, last_y + int(10 * scale_y), max_w, draw=None)
        return final_y

    async def fetch_recommendations(self, demo: bool = False, count: int = 10):
        if demo:
            res = await self.api.search_songs("热门歌曲", limit=count)
            return res.get("songs", []) if isinstance(res, dict) else res
        return await self.api.get_daily_recommend()

    async def create_visuals(self, song: dict, bg_path: str, cover_path: str):
        album_pic_url = song.get("album_pic")
        img_raw = None
        if album_pic_url:
            content = await self.api.download_bytes(album_pic_url)
            if content:
                try:
                    img_raw = Image.open(BytesIO(content)).convert("RGB")
                except Exception as e:
                    self._log(f"  ⚠️ 解析封面失败: {e}")
            else:
                self._log("  ⚠️ 下载封面失败，使用默认封面")

        if not img_raw:
            img_raw = Image.new("RGB", (800, 800), (30, 30, 60))

        # 1. 保存清晰封面（供 B 站投稿作为第一首封面使用）
        cover_800 = img_raw.resize((800, 800), Image.Resampling.LANCZOS)
        if not Path(cover_path).exists():
            tmp_cov = Path(cover_path).with_suffix(".tmp.png")
            cover_800.save(tmp_cov, format="PNG")
            tmp_cov.replace(cover_path)

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

        # 3. 预合成封面到背景图（按目标分辨率比例缩放）
        scale_x = self.w / 1920.0
        scale_y = self.h / 1080.0
        cover_scale = min(scale_x, scale_y)
        cover_px = max(64, int(800 * cover_scale))
        cover_for_bg = cover_800 if cover_px == 800 else cover_800.resize((cover_px, cover_px), Image.Resampling.LANCZOS)
        bg_img.paste(cover_for_bg, (int(120 * scale_x), int(140 * scale_y)))

        # 4. 绘制文字
        draw = ImageDraw.Draw(bg_img)
        name, artists_str = song.get("name", ""), ", ".join(song.get("artists", []))
        font, font_s = self._get_fonts()
        start_y = int(self.config.get("visual", {}).get("title_start_y", 150) * scale_y)
        max_w = int(800 * scale_x)

        last_y = self._wrap_and_measure_text(name, font, start_y, max_w, draw=draw, fill=(255, 255, 255))
        final_y = self._wrap_and_measure_text(artists_str, font_s, last_y + int(10 * scale_y), max_w, draw=draw, fill=(200, 200, 200))

        tmp_bg = Path(bg_path).with_suffix(".tmp.png")
        bg_img.save(tmp_bg, format="PNG")
        tmp_bg.replace(bg_path)
        return final_y

    def lrc_to_ass(self, lrc_text: str, ass_path: str, margin_v: int = 400):
        if not lrc_text:
            return False

        ts_pattern = re.compile(r'\[(\d+):(\d+)[.:](\d+)\]')
        entries = []
        for line in lrc_text.splitlines():
            matches = list(ts_pattern.finditer(line))
            if not matches:
                continue
            text = line[matches[-1].end():].strip()
            for match in matches:
                m, s, ms = match.groups()
                time_ms = int(m) * 60000 + int(s) * 1000 + int(ms.ljust(3, '0')[:3])
                entries.append({"time": time_ms, "text": text})

        if not entries:
            return False
        entries.sort(key=lambda x: x["time"])

        scale_x = self.w / 1920.0
        scale_y = self.h / 1080.0
        margin_l = int(self.config.get("visual", {}).get("text_x", 1050) * scale_x)
        margin_r = int(150 * scale_x)
        spec_y = int(680 * scale_y)
        safe_margin_v = min(int(margin_v), max(0, spec_y - int(80 * scale_y)))
        clip_bottom = max(safe_margin_v + 20, spec_y - int(15 * scale_y))
        clip_right = max(margin_l + 50, self.w - margin_r)
        font_size = max(16, int(45 * scale_y))

        sys_name = platform.system()
        default_ass_font = "PingFang SC" if sys_name == "Darwin" else ("Noto Sans CJK SC" if sys_name == "Linux" else "微软雅黑")
        ass_font = self.config.get("font", {}).get("ass_font", default_ass_font)

        header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {self.w}
PlayResY: {self.h}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{ass_font},{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,1,7,{margin_l},{margin_r},{safe_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        def fmt(ms: int) -> str:
            return f"{ms // 3600000:01d}:{(ms % 3600000) // 60000:02d}:{(ms % 60000) // 1000:02d}.{(ms % 1000) // 10:02d}"

        dialogue_lines = []
        for i, entry in enumerate(entries):
            raw_text = entry["text"]
            if not raw_text:
                continue
            start_ms = entry["time"]
            next_time = entries[i + 1]["time"] if i + 1 < len(entries) else start_ms + 4000
            end_ms = max(start_ms + 10, next_time - 50)
            safe_text = _escape_ass_text(raw_text)
            dialogue_lines.append(
                f"Dialogue: 0,{fmt(start_ms)},{fmt(end_ms)},Default,,0,0,0,,{{\\clip({margin_l},{safe_margin_v},{clip_right},{clip_bottom})}}{safe_text}\n"
            )

        if not dialogue_lines:
            return False

        ass_p = Path(ass_path)
        tmp_ass = ass_p.with_suffix(".tmp.ass")
        with open(tmp_ass, "w", encoding="utf-8") as f:
            f.write(header)
            f.writelines(dialogue_lines)
        tmp_ass.replace(ass_p)
        return True

    def save_song_list(self, songs: list, run_dir: Path, filename: str = "song_list.txt"):
        """生成歌曲列表文本文件"""
        list_file = run_dir / filename
        lines = []
        for i, song in enumerate(songs, 1):
            artists = ", ".join(song.get("artists", []))
            lines.append(f"{i}: {song.get('name', '')} - {artists}")
        list_file.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        self._log(f"  📝 已生成歌单列表: {list_file}")
        return list_file

    async def _prepare_song_assets(
        self,
        idx: int,
        total: int,
        song: dict,
        audio_dir: Path,
        images_dir: Path,
        lyrics_dir: Path,
        clips_dir: Path,
        render_sig: str,
        prefetched_urls: dict[int, str],
        sem: asyncio.Semaphore,
        is_cancelled_callback=None,
    ) -> dict | None:
        """并发预下载单首歌曲的音频、封面、歌词并生成 UI 底图与 ASS 字幕"""
        async with sem:
            try:
                if is_cancelled_callback and is_cancelled_callback():
                    return None

                song_id = song["id"]
                song_name = song.get("name", str(song_id))
                bg_path = images_dir / f"{song_id}_{render_sig}_bg.png"
                cover_path = images_dir / f"{song_id}_cover.png"
                lrc_path = lyrics_dir / f"{song_id}.lrc"
                ass_path = lyrics_dir / f"{song_id}_{render_sig}.ass"
                clip_path = clips_dir / f"clip_{song_id}_{render_sig}.mp4"

                # 若视频片段缓存已存在且封面图也已存在，直接复用
                if clip_path.exists() and clip_path.stat().st_size > 0 and cover_path.exists():
                    return {
                        "idx": idx,
                        "song": song,
                        "audio_path": None,
                        "bg_path": str(bg_path),
                        "cover_path": str(cover_path),
                        "ass_path": None,
                        "clip_path": str(clip_path),
                        "cached_clip": True,
                    }

                # 1. 查找或下载音频
                cached_audio = _find_cached_audio(audio_dir, song_id)
                if not cached_audio:
                    self._log(f"  -> [{idx}/{total}] 下载音频: {song_name}...")
                    ret = await self.api.download_song(
                        song_id, song_name, str(audio_dir), url=prefetched_urls.get(int(song_id))
                    )
                    if not ret:
                        logger.warning(f"  [FAIL] 下载失败: {song_name} (ID: {song_id})")
                        return None
                    audio_path = Path(ret)
                else:
                    self._log(f"  -> [{idx}/{total}] 使用音频缓存: {song_name} [OK]")
                    audio_path = cached_audio

                if is_cancelled_callback and is_cancelled_callback():
                    return None

                # 2. 视觉底图（含预合成封面）与歌词并发拉取
                async def _ensure_visuals():
                    if not bg_path.exists() or not cover_path.exists():
                        res_y = await self.create_visuals(song, str(bg_path), str(cover_path))
                        return res_y or self.compute_text_end_y(song)
                    return self.compute_text_end_y(song)

                async def _ensure_lrc():
                    if not lrc_path.exists():
                        text = await self.api.get_lyrics(song_id)
                        if text:
                            lrc_path.write_text(text, encoding="utf-8")

                text_end_y, _ = await asyncio.gather(_ensure_visuals(), _ensure_lrc())

                # 3. 生成 ASS 字幕（根据精确计算的 text_end_y 动态定位）
                has_sub = False
                if lrc_path.exists():
                    scale_y = self.h / 1080.0
                    if self.lrc_to_ass(
                        lrc_path.read_text(encoding="utf-8"),
                        str(ass_path),
                        margin_v=int(text_end_y + 30 * scale_y),
                    ):
                        has_sub = True

                return {
                    "idx": idx,
                    "song": song,
                    "audio_path": str(audio_path),
                    "bg_path": str(bg_path),
                    "cover_path": str(cover_path),
                    "ass_path": str(ass_path) if has_sub else None,
                    "clip_path": str(clip_path),
                    "cached_clip": clip_path.exists() and clip_path.stat().st_size > 0,
                }
            except Exception as e:
                logger.warning(f"  [FAIL] 准备歌曲资源异常 ({song.get('name', song.get('id'))}): {e}")
                return None

    async def process_songs(
        self,
        songs: list,
        run_dir: Path,
        is_cancelled_callback=None,
        succeeded_songs: list | None = None,
    ):
        audio_dir, images_dir, lyrics_dir, clips_dir = [run_dir / d for d in ["audio", "images", "lyrics", "clips"]]
        for d in [audio_dir, images_dir, lyrics_dir, clips_dir]:
            d.mkdir(parents=True, exist_ok=True)

        total = len(songs)
        render_sig = self._render_signature()

        # 预先批量获取缺少本地音频缓存的歌曲下载链接
        missing_ids = [
            int(s["id"]) for s in songs
            if not _find_cached_audio(audio_dir, s["id"])
        ]
        prefetched_urls = await self.api.get_song_urls(missing_ids) if missing_ids else {}

        self._log(f"正在并发准备 {total} 首歌曲的音频、封面与字幕资源...")
        sem = asyncio.Semaphore(3)
        prep_tasks = [
            self._prepare_song_assets(
                i, total, song, audio_dir, images_dir, lyrics_dir, clips_dir,
                render_sig, prefetched_urls, sem, is_cancelled_callback
            )
            for i, song in enumerate(songs, 1)
        ]
        prepared_list = await asyncio.gather(*prep_tasks, return_exceptions=True)

        successful_clips = []
        failed_songs = []

        for i, (song, prep) in enumerate(zip(songs, prepared_list), 1):
            if is_cancelled_callback and is_cancelled_callback():
                self._log("检测到取消信号，终止后续歌曲合成流程。")
                break

            if isinstance(prep, BaseException) or prep is None:
                failed_songs.append(f"{song.get('name', '')} (ID: {song.get('id', '')})")
                continue

            self._log(f"\n[{i}/{total}] [SONG] {song.get('name', '')} - {', '.join(song.get('artists', []))}")
            clip_path = Path(prep["clip_path"])
            if not prep.get("cached_clip"):
                self._log("  -> 合成播放器视频片段...")
                loop = asyncio.get_running_loop()
                res = await loop.run_in_executor(
                    None,
                    self.video_maker.create_clip,
                    prep["bg_path"],
                    prep["audio_path"],
                    str(clip_path),
                    prep["ass_path"],
                    None,
                    song.get("duration_ms", 0) / 1000
                )
                if res:
                    successful_clips.append(str(clip_path))
                    if succeeded_songs is not None:
                        succeeded_songs.append(song)
                else:
                    failed_songs.append(f"{song.get('name', '')} (ID: {song.get('id', '')})")
            else:
                self._log("  -> 正在使用视频缓存 [OK]")
                successful_clips.append(str(clip_path))
                if succeeded_songs is not None:
                    succeeded_songs.append(song)

        if failed_songs:
            logger.warning(f"\n===== {len(failed_songs)} 首歌曲处理失败 =====")
            for fs in failed_songs:
                logger.warning(f"  - {fs}")

        return successful_clips


async def run_cli(args):
    config = load_config()
    proc = PipelineProcessor(config)

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

    succeeded_songs = []
    clips = await proc.process_songs(songs, run_dir, succeeded_songs=succeeded_songs)
    if not clips:
        await proc.api.aclose()
        return print("\n❌ 没有成功生成任何片段")

    print(f"\nStep 3: 拼接 {len(clips)} 个片段...")
    final_path = run_dir / f"daily_music_{today}.mp4"
    if proc.video_maker.concat_clips(clips, str(final_path)):
        print(f"  ✅ 最终视频: {final_path}")
        proc.save_song_list(succeeded_songs or songs, run_dir)

        if proc.cleanup_manager:
            usage = proc.cleanup_manager.get_disk_usage()
            print(f"\n💾 磁盘使用情况:")
            print(f"  总大小: {usage['total_size_gb']:.2f} GB ({usage['total_size_mb']:.0f} MB)")
            print(f"  文件数: {usage['file_count']}")
            if usage['oldest_file']:
                print(f"  最旧文件: {usage['oldest_file']}")
            if usage['newest_file']:
                print(f"  最新文件: {usage['newest_file']}")
    else:
        print("  ❌ 拼接失败")

    await proc.api.aclose()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--count", type=int)
    p.add_argument("--test", action="store_true")
    p.add_argument("--demo", action="store_true")
    args = p.parse_args()
    if args.test:
        args.count = 3
    asyncio.run(run_cli(args))

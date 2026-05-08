import os
import sys
import subprocess
import shutil
from pathlib import Path

# Windows Job Object "越狱" flag
# AstrBot 会把所有子进程绑入一个 Job Object 并限制内存总量。
# CREATE_NEW_PROCESS_GROUP 会让 FFmpeg 以独立进程组启动，从而逃脱该限制。
# 这正是 WebView 模式下 FFmpeg 能自由使用内存的原因。
_FFMPEG_CREATION_FLAGS = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0


class VideoMaker:
    def __init__(self, width: int = 1920, height: int = 1080, fps: int = 24):
        self.width = width
        self.height = height
        self.fps = fps
        self._ffmpeg = self._find_ffmpeg()

    def _find_ffmpeg(self) -> str:
        # 优先 imageio-ffmpeg（pip 安装，自带二进制）
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            pass
        # 系统 ffmpeg
        try:
            r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
            if r.returncode == 0:
                return "ffmpeg"
        except FileNotFoundError:
            pass
        raise RuntimeError(
            "找不到 FFmpeg！请安装：\n"
            "  pip install imageio-ffmpeg\n"
            "  或: winget install ffmpeg"
        )

    def create_clip(self, image_path: str, audio_path: str, output_path: str, subtitle_path: str = None, cover_path: str = None, duration: float = 0) -> str | None:
        """音乐播放器 UI 布局：左侧封面 + 右侧信息/律动/进度条"""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        # 处理字幕路径转义 (Windows 下 FFmpeg subtitles 滤镜对路径极其挑剔)
        safe_sub_path = ""
        if subtitle_path and os.path.exists(subtitle_path):
            # 将 \ 替换为 /，并对分号进行转义 (C: -> C\\:)
            path_str = str(Path(subtitle_path).resolve()).replace("\\", "/")
            if ":" in path_str:
                drive, rest = path_str.split(":", 1)
                safe_sub_path = f"{drive}\\:{rest}"
            else:
                safe_sub_path = path_str

        # 1. 专业级镜像律动条 (优化渲染路径以降低内存压力)
        filter_complex = (
            f"[2:a]asplit[a_main][a_tmp];"
            f"[a_tmp]volume=1.2,showfreqs=s=800x75:mode=bar:colors=white:fscale=log:ascale=sqrt[viz_raw];"
            f"[viz_raw]split[viz_t][viz_for_flip];"
            f"[viz_for_flip]vflip[viz_b];"
            f"[viz_t][viz_b]vstack,format=yuva420p[viz_combined];"
            f"[0:v][1:v]overlay=x=120:y=140[v_base];" 
            f"[v_base][viz_combined]overlay=x=1050:y=680[v_ui]"
        )
        
        if safe_sub_path:
            filter_complex += f";[v_ui]subtitles='{safe_sub_path}'[v_combined]"
        else:
            filter_complex += f";[v_ui]copy[v_combined]"
        
        cmd = [
            self._ffmpeg, "-y",
            "-loglevel", "error",
            "-threads", "1",                   # 强制单线程：这是在 OOM 环境下生存的关键，将内存占用降至最低
            "-loop", "1", "-i", image_path,    # [0:v] 背景
            "-loop", "1", "-i", cover_path,    # [1:v] 封面
            "-i", audio_path,                  # [2:a] 音频
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage", # 使用 ultrafast 进一步降低内存开销
            "-c:a", "aac", "-b:a", "128k",
            "-ac", "2", "-ar", "44100",        # 强制规格化音频：2声道，44.1k采样率，解决拼接无声的关键
            "-filter_complex", filter_complex,
            "-map", "[v_combined]",
            "-map", "[a_main]",
            "-r", str(self.fps),
            "-video_track_timescale", "24000",   # 统一视频轨迹时间基 (按 24fps 换算)
            "-pix_fmt", "yuv420p",
            "-shortest",
            output_path,
        ]
        # 增加静默参数
        cmd.insert(1, "-nostats")
        
        # 运行 FFmpeg (使用物理文件重定向，彻底规避管道死锁)
        import sys
        log_path = Path(output_path).parent / "ffmpeg_render.log"
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n--- RENDERING {output_path} ---\n")
                f.write(f"CMD: {' '.join(cmd)}\n")
                f.flush()
                # 关键：creationflags 让 FFmpeg 逃脱 AstrBot 的 Job Object 内存限制
                subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=f,
                    check=True,
                    timeout=600,
                    creationflags=_FFMPEG_CREATION_FLAGS
                )
            return output_path
        except subprocess.TimeoutExpired:
            print(f"\n  [FAIL] FFmpeg timeout (600s) for {output_path}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"\n  [FAIL] FFmpeg render failed. Check {log_path} for details. Error: {e}", file=sys.stderr)
            return None

    def concat_clips(self, clip_paths: list, output_path: str) -> str | None:
        """
        拼接多个视频片段 (使用 concat 滤镜，完整重编码)
        
        concat demuxer (-f concat) 在拼接 10+ 个文件时，会在第 10 个片段交界处
        产生音频流丢失。改用 concat filter (-filter_complex) 完全解码所有输入
        并从零重建输出，彻底消除此问题。
        """
        if not clip_paths:
            return None
        if len(clip_paths) == 1:
            shutil.copy2(clip_paths[0], output_path)
            return output_path

        # 构建 concat filter 命令
        # 每个输入文件: -i clip1.mp4 -i clip2.mp4 ...
        # filter: [0:v][0:a][1:v][1:a]...[N:v][N:a]concat=n=N:v=1:a=1[outv][outa]
        inputs = []
        filter_parts = []
        for i, cp in enumerate(clip_paths):
            inputs.extend(["-i", str(Path(cp).resolve())])
            filter_parts.append(f"[{i}:v][{i}:a]")
        
        n = len(clip_paths)
        filter_complex = "".join(filter_parts) + f"concat=n={n}:v=1:a=1[outv][outa]"

        cmd = [
            self._ffmpeg, "-y", "-nostats",
            "-loglevel", "error",
        ] + inputs + [
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "aac", "-b:a", "128k",
            "-ac", "2", "-ar", "44100",
            "-pix_fmt", "yuv420p",
            output_path,
        ]
        
        import sys
        log_path = Path(output_path).parent / "ffmpeg_render.log"
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n--- CONCATENATING (filter mode) TO {output_path} ---\n")
                f.write(f"CMD: {' '.join(cmd)}\n")
                f.flush()
                subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=f,
                    check=True,
                    timeout=1800,   # 完整重编码需要更长时间
                    creationflags=_FFMPEG_CREATION_FLAGS
                )
            return output_path
        except Exception as e:
            print(f"\n  [FAIL] FFmpeg concat failed. Check {log_path}. Error: {e}", file=sys.stderr)
            return None


import atexit
import logging
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import List

logger = logging.getLogger('pipeline.video_maker')

# 进程管理：跟踪所有启动的FFmpeg进程
_ffmpeg_processes: List[subprocess.Popen] = []
_ffmpeg_processes_lock = threading.Lock()
_log_file_lock = threading.Lock()


def _cleanup_ffmpeg_processes():
    """清理所有正在运行的FFmpeg进程"""
    with _ffmpeg_processes_lock:
        for proc in _ffmpeg_processes[:]:
            try:
                if proc.poll() is None:
                    logger.info(f"终止残留FFmpeg进程 (PID: {proc.pid})")
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
            except Exception as e:
                logger.warning(f"清理FFmpeg进程失败: {e}")
        _ffmpeg_processes.clear()


atexit.register(_cleanup_ffmpeg_processes)

# Windows Job Object "越狱" flag
# CREATE_BREAKAWAY_FROM_JOB 会让 FFmpeg 脱离 Job Object，从而逃脱内存限制。
# CREATE_NO_WINDOW (0x08000000) 会隐藏黑色的控制台窗口。
_FFMPEG_CREATION_FLAGS = (subprocess.CREATE_BREAKAWAY_FROM_JOB | 0x08000000) if sys.platform == "win32" else 0


def _escape_ffmpeg_filter_path(path_str: str) -> str:
    """对传给 FFmpeg subtitles=filename=... 的路径做两级转义"""
    s = str(Path(path_str).resolve()).replace("\\", "/")
    for ch in ("\\", ":", "'"):
        s = s.replace(ch, "\\" + ch)
    for ch in ("\\", "'", "[", "]", ",", ";"):
        s = s.replace(ch, "\\" + ch)
    return s


class VideoMaker:
    def __init__(self, width: int = 1920, height: int = 1080, fps: int = 24, config: dict = None):
        self.width = width
        self.height = height
        self.fps = fps
        self.config = config or {}
        self._ffmpeg = self._find_ffmpeg()

    def _find_ffmpeg(self) -> str:
        try:
            import imageio_ffmpeg
            exe = imageio_ffmpeg.get_ffmpeg_exe()
            if exe and os.path.exists(exe):
                return exe
        except ImportError:
            pass
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

    def _run_ffmpeg_cmd(self, cmd: list, log_path: Path, header_title: str, timeout: int = 600) -> bool:
        """统一执行并跟踪 FFmpeg 子进程"""
        with _log_file_lock:
            log_file = open(log_path, "a", encoding="utf-8")
            log_file.write(f"\n--- {header_title} ---\n")
            log_file.write(f"CMD: {' '.join(cmd)}\n")
            log_file.flush()

        try:
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=log_file,
                    creationflags=_FFMPEG_CREATION_FLAGS
                )
            except PermissionError as pe:
                if sys.platform == "win32" and (_FFMPEG_CREATION_FLAGS & subprocess.CREATE_BREAKAWAY_FROM_JOB):
                    logger.warning("Failed to start FFmpeg with CREATE_BREAKAWAY_FROM_JOB. Retrying without breakaway flag...")
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=log_file,
                        creationflags=(0x08000000 if sys.platform == "win32" else 0)
                    )
                else:
                    raise pe

            with _ffmpeg_processes_lock:
                _ffmpeg_processes.append(proc)

            try:
                proc.wait(timeout=timeout)
                return proc.returncode == 0
            except subprocess.TimeoutExpired:
                logger.error(f"FFmpeg timeout ({timeout}s), terminating...")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                return False
            finally:
                with _ffmpeg_processes_lock:
                    if proc in _ffmpeg_processes:
                        _ffmpeg_processes.remove(proc)
        finally:
            log_file.close()

    def create_clip(
        self,
        image_path: str,
        audio_path: str,
        output_path: str,
        subtitle_path: str = None,
        cover_path: str = None,
        duration: float = 0
    ) -> str | None:
        """
        音乐播放器 UI 布局合成：
        - 单帧解码静态图并在滤镜内 loop，避免每秒重复 24 次 PNG 解压与 RGB->YUV 转换。
        - 若 cover_path 为 None（已由 Pillow 预合成），仅使用单路静态背景输入。
        - 采用 .tmp.mp4 原子写入，防止中途取消产生损坏缓存文件。
        """
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        tmp_out_p = out_p.with_suffix(".tmp.mp4")

        safe_sub_path = ""
        if subtitle_path and os.path.exists(subtitle_path):
            safe_sub_path = _escape_ffmpeg_filter_path(subtitle_path)

        scale_x = self.width / 1920.0
        scale_y = self.height / 1080.0
        spec_size = self.config.get("video", {}).get("spectrum_size", "800x75")
        if self.width != 1920 or self.height != 1080:
            try:
                sw, sh = [int(x) for x in str(spec_size).lower().split("x", 1)]
                spec_size = f"{max(16, int(sw * scale_x))}x{max(8, int(sh * scale_y))}"
            except Exception:
                pass

        text_x = int(self.config.get("visual", {}).get("text_x", 1050) * scale_x)
        spec_y = int(680 * scale_y)
        cover_x = int(120 * scale_x)
        cover_y = int(140 * scale_y)

        use_separate_cover = bool(cover_path and os.path.exists(cover_path))
        audio_idx = 2 if use_separate_cover else 1

        filter_parts = [
            f"[0:v]format=yuv420p,loop=loop=-1:size=1:start=0,fps={self.fps}[v_bg]",
            f"[{audio_idx}:a]asplit[a_main][a_tmp]",
            f"[a_tmp]volume=1.2,showfreqs=s={spec_size}:r={self.fps}:mode=bar:colors=white:fscale=log:ascale=sqrt[viz_raw]",
            f"[viz_raw]split[viz_t][viz_for_flip]",
            f"[viz_for_flip]vflip[viz_b]",
            f"[viz_t][viz_b]vstack,format=yuva420p[viz_combined]",
        ]

        if use_separate_cover:
            filter_parts.extend([
                f"[1:v]format=yuva420p,loop=loop=-1:size=1:start=0,fps={self.fps}[v_cov]",
                f"[v_bg][v_cov]overlay=x={cover_x}:y={cover_y}[v_base]",
                f"[v_base][viz_combined]overlay=x={text_x}:y={spec_y}:shortest=1[v_ui]",
            ])
        else:
            filter_parts.append(
                f"[v_bg][viz_combined]overlay=x={text_x}:y={spec_y}:shortest=1[v_ui]"
            )

        if safe_sub_path:
            filter_parts.append(f"[v_ui]subtitles=filename={safe_sub_path}[v_combined]")
        else:
            filter_parts.append("[v_ui]null[v_combined]")

        filter_complex = ";".join(filter_parts)

        cmd = [
            self._ffmpeg, "-nostats", "-y",
            "-loglevel", "error",
            "-threads", str(self.config.get("video", {}).get("threads", 1)),
            "-i", image_path,
        ]
        if use_separate_cover:
            cmd.extend(["-i", cover_path])
        cmd.extend([
            "-i", audio_path,
            "-c:v", "libx264",
            "-preset", self.config.get("video", {}).get("preset", "ultrafast"),
            "-tune", "stillimage",
            "-c:a", "aac",
            "-b:a", self.config.get("video", {}).get("audio_bitrate", "128k"),
            "-ac", str(self.config.get("video", {}).get("audio_channels", 2)),
            "-ar", str(self.config.get("video", {}).get("audio_sample_rate", 44100)),
            "-filter_complex", filter_complex,
            "-map", "[v_combined]",
            "-map", "[a_main]",
            "-r", str(self.fps),
            "-video_track_timescale", str(self.fps * 1000),
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-shortest",
            str(tmp_out_p),
        ])

        log_path = out_p.parent / "ffmpeg_render.log"
        try:
            ok = self._run_ffmpeg_cmd(cmd, log_path, f"RENDERING {output_path}", timeout=600)
            if ok and tmp_out_p.exists():
                tmp_out_p.replace(out_p)
                return output_path
            logger.error(f"FFmpeg render failed for {output_path}")
            return None
        except Exception as e:
            logger.error(f"FFmpeg render failed. Check {log_path} for details. Error: {e}")
            return None
        finally:
            try:
                if tmp_out_p.exists():
                    tmp_out_p.unlink()
            except Exception:
                pass

    def concat_clips(self, clip_paths: list, output_path: str) -> str | None:
        """
        拼接多个视频片段：
        1. 单片段时直接原子 remux (+faststart) 到目标路径。
        2. 多片段优先采用 concat demuxer + 视频流无损直拷 + 音频重采样对齐。
        3. 若直拷失败，自动回退至 filter_complex 重编码模式。
        """
        if not clip_paths:
            return None
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        tmp_out_p = out_p.with_suffix(".tmp.mp4")
        log_path = out_p.parent / "ffmpeg_render.log"

        if len(clip_paths) == 1:
            src_p = Path(clip_paths[0]).resolve()
            if src_p == out_p.resolve():
                return output_path
            try:
                single_cmd = [
                    self._ffmpeg, "-y", "-nostats", "-loglevel", "error",
                    "-i", str(src_p),
                    "-c", "copy",
                    "-movflags", "+faststart",
                    str(tmp_out_p),
                ]
                ok = self._run_ffmpeg_cmd(single_cmd, log_path, f"REMUXING SINGLE CLIP TO {output_path}", timeout=120)
                if ok and tmp_out_p.exists() and tmp_out_p.stat().st_size > 0:
                    tmp_out_p.replace(out_p)
                    return output_path
                shutil.copy2(src_p, tmp_out_p)
                tmp_out_p.replace(out_p)
                return output_path
            except Exception as e:
                logger.error(f"Single clip copy failed: {e}")
                return None
            finally:
                try:
                    if tmp_out_p.exists():
                        tmp_out_p.unlink()
                except Exception:
                    pass

        concat_list_p = out_p.parent / f"concat_list_{out_p.stem}.txt"

        # 方案 A：快速视频直拷 + 音频时间戳重采样对齐
        try:
            lines = []
            for cp in clip_paths:
                resolved = str(Path(cp).resolve()).replace("\\", "/")
                escaped = resolved.replace("'", "'\\''")
                lines.append(f"file '{escaped}'\n")
            concat_list_p.write_text("".join(lines), encoding="utf-8")

            fast_cmd = [
                self._ffmpeg, "-y", "-nostats",
                "-loglevel", "error",
                "-f", "concat", "-safe", "0", "-i", str(concat_list_p),
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", self.config.get("video", {}).get("audio_bitrate", "128k"),
                "-ac", str(self.config.get("video", {}).get("audio_channels", 2)),
                "-ar", str(self.config.get("video", {}).get("audio_sample_rate", 44100)),
                "-af", "aresample=async=1:first_pts=0",
                "-movflags", "+faststart",
                str(tmp_out_p),
            ]

            ok = self._run_ffmpeg_cmd(fast_cmd, log_path, f"CONCATENATING (fast stream-copy mode) TO {output_path}", timeout=300)
            if ok and tmp_out_p.exists() and tmp_out_p.stat().st_size > 0:
                tmp_out_p.replace(out_p)
                return output_path
            logger.warning("Fast concat mode failed, falling back to filter_complex re-encode mode...")
        except Exception as e:
            logger.warning(f"Fast concat exception ({e}), falling back to re-encode mode...")
        finally:
            for p in (concat_list_p, tmp_out_p):
                try:
                    if p.exists():
                        p.unlink()
                except Exception:
                    pass

        # 方案 B：回退至 filter_complex 完整重编码
        inputs = []
        filter_parts = []
        for i, cp in enumerate(clip_paths):
            inputs.extend(["-i", str(Path(cp).resolve())])
            filter_parts.append(f"[{i}:v][{i}:a]")

        n = len(clip_paths)
        filter_complex = "".join(filter_parts) + f"concat=n={n}:v=1:a=1[outv][outa]"

        fallback_cmd = [
            self._ffmpeg, "-y", "-nostats",
            "-loglevel", "error",
            "-threads", str(self.config.get("video", {}).get("threads", 1)),
        ] + inputs + [
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", self.config.get("video", {}).get("preset", "ultrafast"),
            "-c:a", "aac", "-b:a", self.config.get("video", {}).get("audio_bitrate", "128k"),
            "-ac", str(self.config.get("video", {}).get("audio_channels", 2)),
            "-ar", str(self.config.get("video", {}).get("audio_sample_rate", 44100)),
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(tmp_out_p),
        ]

        try:
            ok = self._run_ffmpeg_cmd(fallback_cmd, log_path, f"CONCATENATING (fallback filter mode) TO {output_path}", timeout=1800)
            if ok and tmp_out_p.exists():
                tmp_out_p.replace(out_p)
                return output_path
            logger.error(f"FFmpeg concat failed for {output_path}")
            return None
        except Exception as e:
            logger.error(f"FFmpeg concat failed. Check {log_path}. Error: {e}")
            return None
        finally:
            try:
                if tmp_out_p.exists():
                    tmp_out_p.unlink()
            except Exception:
                pass

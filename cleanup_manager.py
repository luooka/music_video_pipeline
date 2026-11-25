# -*- coding: utf-8 -*-
"""
磁盘空间管理模块
负责自动清理旧文件，防止磁盘空间被占满
"""
import logging
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger('pipeline.cleanup')


class CleanupManager:
    """磁盘空间清理管理器"""

    def __init__(self, config: dict):
        self.config = config
        self.output_dir = Path(config.get("output_dir", "./output"))
        self.max_age_days = config.get("cleanup", {}).get("max_age_days", 7)
        self.max_total_size_gb = config.get("cleanup", {}).get("max_total_size_gb", 10)
        self.cleanup_on_start = config.get("cleanup", {}).get("cleanup_on_start", True)

    def cleanup_old_files(self) -> dict:
        """清理旧文件，返回清理统计信息"""
        stats = {
            "deleted_files": 0,
            "freed_space_mb": 0,
            "errors": 0
        }

        try:
            if self.output_dir.exists():
                for sub_stats in (self._cleanup_by_age(), self._cleanup_by_size()):
                    stats["deleted_files"] += sub_stats["deleted_files"]
                    stats["freed_space_mb"] += sub_stats["freed_space_mb"]
                    stats["errors"] += sub_stats["errors"]
                self._remove_empty_dirs()

            temp_stats = self.cleanup_temp_uploads()
            stats["deleted_files"] += temp_stats["deleted_files"]
            stats["freed_space_mb"] += temp_stats["freed_space_mb"]
            stats["errors"] += temp_stats["errors"]

            return stats
        except Exception as e:
            logger.error(f"清理过程中发生错误: {e}")
            stats["errors"] += 1
            return stats

    def _remove_empty_dirs(self):
        """清理 output_dir 下的空子目录"""
        try:
            for root, dirs, files in os.walk(self.output_dir, topdown=False):
                root_path = Path(root)
                if root_path != self.output_dir:
                    try:
                        if not any(root_path.iterdir()):
                            root_path.rmdir()
                            logger.debug(f"删除空目录: {root_path}")
                    except Exception:
                        pass
        except Exception:
            pass

    def _cleanup_by_age(self) -> dict:
        """按文件年龄清理"""
        stats = {
            "deleted_files": 0,
            "freed_space_mb": 0,
            "errors": 0
        }

        cutoff_time = time.time() - (self.max_age_days * 24 * 3600)

        try:
            for root, dirs, files in os.walk(self.output_dir, topdown=False):
                root_path = Path(root)
                for file in files:
                    file_path = root_path / file
                    if self._is_file_in_use(file_path):
                        continue

                    try:
                        st = file_path.stat()
                        if st.st_mtime < cutoff_time:
                            file_size_mb = st.st_size / (1024 * 1024)
                            file_path.unlink()
                            stats["deleted_files"] += 1
                            stats["freed_space_mb"] += file_size_mb
                            logger.debug(f"删除旧文件: {file_path} (修改时间: {datetime.fromtimestamp(st.st_mtime)})")
                    except Exception as e:
                        logger.warning(f"无法处理文件 {file_path}: {e}")
                        stats["errors"] += 1
        except Exception as e:
            logger.error(f"按年龄清理时出错: {e}")
            stats["errors"] += 1

        return stats

    @staticmethod
    def _is_final_output_file(file_path: Path) -> bool:
        """判断是否为成品输出视频，按大小清理时优先保留成品而先删缓存文件"""
        return file_path.suffix.lower() == ".mp4" and file_path.name.startswith("daily_music_")

    def _cleanup_by_size(self) -> dict:
        """按总大小清理，超过限制时优先删除最旧的中间缓存，再删除成品视频"""
        stats = {
            "deleted_files": 0,
            "freed_space_mb": 0,
            "errors": 0
        }

        try:
            total_size_bytes = 0
            file_info = []  # (priority, mtime, size, file_path)

            for root, dirs, files in os.walk(self.output_dir):
                for file in files:
                    file_path = Path(root) / file
                    try:
                        st = file_path.stat()
                        total_size_bytes += st.st_size
                        priority = 1 if self._is_final_output_file(file_path) else 0
                        file_info.append((priority, st.st_mtime, st.st_size, file_path))
                    except Exception:
                        pass

            max_size_bytes = self.max_total_size_gb * (1024 ** 3)
            if total_size_bytes <= max_size_bytes:
                return stats

            # 优先删除 priority=0 (缓存文件) 且最旧的文件
            file_info.sort(key=lambda x: (x[0], x[1]))

            freed_bytes = 0
            target_freed_bytes = total_size_bytes - max_size_bytes

            for _, mtime, size, file_path in file_info:
                if freed_bytes >= target_freed_bytes:
                    break

                if self._is_file_in_use(file_path):
                    continue

                try:
                    file_path.unlink()
                    freed_bytes += size
                    stats["deleted_files"] += 1
                    stats["freed_space_mb"] += size / (1024 * 1024)
                    logger.debug(f"按大小清理删除文件: {file_path}")
                except Exception as e:
                    logger.warning(f"无法删除文件 {file_path}: {e}")
                    stats["errors"] += 1

        except Exception as e:
            logger.error(f"按大小清理时出错: {e}")
            stats["errors"] += 1

        return stats

    def cleanup_temp_uploads(self, max_age_hours: int = 24) -> dict:
        """清理临时上传目录"""
        stats = {
            "deleted_files": 0,
            "freed_space_mb": 0,
            "errors": 0
        }

        try:
            temp_dir = Path(tempfile.gettempdir()) / "music_video_uploads"
            if not temp_dir.exists():
                return stats

            cutoff_time = time.time() - (max_age_hours * 3600)
            for file_path in temp_dir.iterdir():
                if file_path.is_file():
                    if self._is_file_in_use(file_path):
                        continue
                    try:
                        st = file_path.stat()
                        if st.st_mtime < cutoff_time:
                            file_size_mb = st.st_size / (1024 * 1024)
                            file_path.unlink()
                            stats["deleted_files"] += 1
                            stats["freed_space_mb"] += file_size_mb
                    except Exception:
                        stats["errors"] += 1

        except Exception as e:
            logger.error(f"清理临时目录时出错: {e}")
            stats["errors"] += 1

        return stats

    def _cleanup_temp_uploads(self) -> dict:
        return self.cleanup_temp_uploads(max_age_hours=24)

    def _is_file_in_use(self, file_path: Path) -> bool:
        """检查文件是否正在被写入或被其他进程占用"""
        try:
            st = file_path.stat()
            now = time.time()
            # 刚刚修改过的文件跳过清理，避免误删刚生成或正在处理的素材
            if now - st.st_mtime < 60:
                return True
            if (file_path.suffix == ".tmp" or ".tmp." in file_path.name) and (now - st.st_mtime < 3600):
                return True
        except OSError:
            return True

        if os.name != 'nt':
            return False

        # 使用 Win32 CreateFileW (dwShareMode=0) 只读检测句柄独占，不改动文件内容或时间戳
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            GENERIC_READ = 0x80000000
            OPEN_EXISTING = 3
            FILE_ATTRIBUTE_NORMAL = 0x80
            INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
            ERROR_SHARING_VIOLATION = 32

            kernel32.CreateFileW.restype = ctypes.c_void_p
            handle = kernel32.CreateFileW(
                str(file_path), GENERIC_READ, 0, None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None
            )
            if handle == INVALID_HANDLE_VALUE:
                err = kernel32.GetLastError()
                return err == ERROR_SHARING_VIOLATION
            kernel32.CloseHandle(ctypes.c_void_p(handle))
            return False
        except Exception:
            return False

    def get_disk_usage(self) -> dict:
        """获取磁盘使用情况统计"""
        try:
            if not self.output_dir.exists():
                return {
                    "total_size_gb": 0,
                    "total_size_mb": 0,
                    "file_count": 0,
                    "oldest_file": None,
                    "newest_file": None
                }

            total_size_bytes = 0
            file_count = 0
            oldest_file_time = None
            newest_file_time = None

            for root, dirs, files in os.walk(self.output_dir):
                for file in files:
                    file_path = Path(root) / file
                    try:
                        st = file_path.stat()
                        file_count += 1
                        total_size_bytes += st.st_size
                        if oldest_file_time is None or st.st_mtime < oldest_file_time:
                            oldest_file_time = st.st_mtime
                        if newest_file_time is None or st.st_mtime > newest_file_time:
                            newest_file_time = st.st_mtime
                    except Exception:
                        pass

            return {
                "total_size_gb": total_size_bytes / (1024 ** 3),
                "total_size_mb": total_size_bytes / (1024 * 1024),
                "file_count": file_count,
                "oldest_file": datetime.fromtimestamp(oldest_file_time).isoformat() if oldest_file_time else None,
                "newest_file": datetime.fromtimestamp(newest_file_time).isoformat() if newest_file_time else None
            }
        except Exception as e:
            logger.error(f"获取磁盘使用情况时出错: {e}")
            return {
                "total_size_gb": 0,
                "total_size_mb": 0,
                "file_count": 0,
                "oldest_file": None,
                "newest_file": None,
                "error": str(e)
            }


def setup_cleanup_scheduler(config: dict):
    """设置定期清理调度器"""
    manager = CleanupManager(config)

    if manager.cleanup_on_start:
        logger.info("启动时清理旧文件...")
        stats = manager.cleanup_old_files()
        if stats["deleted_files"] > 0:
            logger.info(f"清理完成: 删除 {stats['deleted_files']} 个文件，释放 {stats['freed_space_mb']:.1f} MB")

    return manager


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_config = {
        "output_dir": "./output",
        "cleanup": {
            "max_age_days": 7,
            "max_total_size_gb": 10,
            "cleanup_on_start": True
        }
    }
    manager = CleanupManager(test_config)
    print("磁盘使用情况:", manager.get_disk_usage())

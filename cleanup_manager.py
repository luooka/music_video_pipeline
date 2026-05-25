# -*- coding: utf-8 -*-
"""
磁盘空间管理模块
负责自动清理旧文件，防止磁盘空间被占满
"""
import os
import time
import shutil
import logging
from pathlib import Path
from typing import Optional, List
from datetime import datetime, timedelta

logger = logging.getLogger('pipeline.cleanup')

class CleanupManager:
    """磁盘空间清理管理器"""
    
    def __init__(self, config: dict):
        self.config = config
        self.output_dir = Path(config.get("output_dir", "./output"))
        self.max_age_days = config.get("cleanup", {}).get("max_age_days", 7)  # 默认保留7天
        self.max_total_size_gb = config.get("cleanup", {}).get("max_total_size_gb", 10)  # 默认最大10GB
        self.cleanup_on_start = config.get("cleanup", {}).get("cleanup_on_start", True)
        
    def cleanup_old_files(self) -> dict:
        """
        清理旧文件，返回清理统计信息
        """
        stats = {
            "deleted_files": 0,
            "freed_space_mb": 0,
            "errors": 0
        }
        
        if not self.output_dir.exists():
            return stats
        
        try:
            # 按时间清理
            time_stats = self._cleanup_by_age()
            stats["deleted_files"] += time_stats["deleted_files"]
            stats["freed_space_mb"] += time_stats["freed_space_mb"]
            stats["errors"] += time_stats["errors"]
            
            # 按大小清理（如果时间清理后仍然太大）
            size_stats = self._cleanup_by_size()
            stats["deleted_files"] += size_stats["deleted_files"]
            stats["freed_space_mb"] += size_stats["freed_space_mb"]
            stats["errors"] += size_stats["errors"]
            
            # 清理临时上传目录
            temp_stats = self._cleanup_temp_uploads()
            stats["deleted_files"] += temp_stats["deleted_files"]
            stats["freed_space_mb"] += temp_stats["freed_space_mb"]
            stats["errors"] += temp_stats["errors"]
            
            return stats
            
        except Exception as e:
            logger.error(f"清理过程中发生错误: {e}")
            stats["errors"] += 1
            return stats
    
    def _cleanup_by_age(self) -> dict:
        """按文件年龄清理"""
        stats = {
            "deleted_files": 0,
            "freed_space_mb": 0,
            "errors": 0
        }
        
        cutoff_time = time.time() - (self.max_age_days * 24 * 3600)
        
        try:
            for root, dirs, files in os.walk(self.output_dir):
                for file in files:
                    file_path = Path(root) / file
                    
                    # 跳过正在使用的文件
                    if self._is_file_in_use(file_path):
                        continue
                    
                    # 检查文件年龄
                    try:
                        file_mtime = file_path.stat().st_mtime
                        if file_mtime < cutoff_time:
                            # 删除旧文件
                            file_size_mb = file_path.stat().st_size / (1024 * 1024)
                            file_path.unlink()
                            stats["deleted_files"] += 1
                            stats["freed_space_mb"] += file_size_mb
                            logger.debug(f"删除旧文件: {file_path} (修改时间: {datetime.fromtimestamp(file_mtime)})")
                    except Exception as e:
                        logger.warning(f"无法处理文件 {file_path}: {e}")
                        stats["errors"] += 1
                
                # 清理空目录
                for dir_name in dirs:
                    dir_path = Path(root) / dir_name
                    try:
                        if not any(dir_path.iterdir()):
                            dir_path.rmdir()
                            logger.debug(f"删除空目录: {dir_path}")
                    except Exception:
                        pass  # 目录非空，跳过
                        
        except Exception as e:
            logger.error(f"按年龄清理时出错: {e}")
            stats["errors"] += 1
            
        return stats
    
    def _cleanup_by_size(self) -> dict:
        """按总大小清理，如果超过限制则删除最旧的文件"""
        stats = {
            "deleted_files": 0,
            "freed_space_mb": 0,
            "errors": 0
        }
        
        try:
            # 计算当前总大小
            total_size_bytes = 0
            file_info = []  # (修改时间, 文件大小, 文件路径)
            
            for root, dirs, files in os.walk(self.output_dir):
                for file in files:
                    file_path = Path(root) / file
                    try:
                        stat = file_path.stat()
                        total_size_bytes += stat.st_size
                        file_info.append((stat.st_mtime, stat.st_size, file_path))
                    except Exception:
                        pass
            
            total_size_gb = total_size_bytes / (1024 ** 3)
            max_size_bytes = self.max_total_size_gb * (1024 ** 3)
            
            if total_size_bytes <= max_size_bytes:
                return stats  # 大小未超限
            
            # 按修改时间排序（最旧的在前）
            file_info.sort(key=lambda x: x[0])
            
            # 删除最旧的文件直到大小符合要求
            freed_bytes = 0
            target_freed_bytes = total_size_bytes - max_size_bytes
            
            for mtime, size, file_path in file_info:
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
    
    def _cleanup_temp_uploads(self) -> dict:
        """清理临时上传目录"""
        stats = {
            "deleted_files": 0,
            "freed_space_mb": 0,
            "errors": 0
        }
        
        try:
            import tempfile
            temp_dir = Path(tempfile.gettempdir()) / "music_video_uploads"
            
            if not temp_dir.exists():
                return stats
            
            # 清理超过24小时的文件
            cutoff_time = time.time() - (24 * 3600)
            
            for file_path in temp_dir.iterdir():
                if file_path.is_file():
                    try:
                        file_mtime = file_path.stat().st_mtime
                        if file_mtime < cutoff_time:
                            file_size_mb = file_path.stat().st_size / (1024 * 1024)
                            file_path.unlink()
                            stats["deleted_files"] += 1
                            stats["freed_space_mb"] += file_size_mb
                    except Exception:
                        stats["errors"] += 1
                        
        except Exception as e:
            logger.error(f"清理临时目录时出错: {e}")
            stats["errors"] += 1
            
        return stats
    
    def _is_file_in_use(self, file_path: Path) -> bool:
        """检查文件是否正在被使用（Windows专用）"""
        if os.name != 'nt':
            return False  # 非Windows系统暂不检查
            
        try:
            # 尝试以独占模式打开文件，如果失败则说明文件正在被使用
            with open(file_path, 'a', encoding='utf-8') as f:
                pass
            return False
        except (IOError, PermissionError):
            return True
        except Exception:
            return False  # 其他异常，假设文件可用
    
    def get_disk_usage(self) -> dict:
        """获取磁盘使用情况统计"""
        try:
            total_size_bytes = 0
            file_count = 0
            oldest_file_time = None
            newest_file_time = None
            
            for root, dirs, files in os.walk(self.output_dir):
                file_count += len(files)
                for file in files:
                    file_path = Path(root) / file
                    try:
                        stat = file_path.stat()
                        total_size_bytes += stat.st_size
                        
                        if oldest_file_time is None or stat.st_mtime < oldest_file_time:
                            oldest_file_time = stat.st_mtime
                        if newest_file_time is None or stat.st_mtime > newest_file_time:
                            newest_file_time = stat.st_mtime
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
    
    # 启动时清理
    if manager.cleanup_on_start:
        logger.info("启动时清理旧文件...")
        stats = manager.cleanup_old_files()
        if stats["deleted_files"] > 0:
            logger.info(f"清理完成: 删除 {stats['deleted_files']} 个文件，释放 {stats['freed_space_mb']:.1f} MB")
    
    # 返回管理器实例，供其他模块使用
    return manager


if __name__ == "__main__":
    # 测试清理功能
    import sys
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
    
    print("磁盘使用情况:")
    usage = manager.get_disk_usage()
    for key, value in usage.items():
        print(f"  {key}: {value}")
    
    print("\n开始清理...")
    stats = manager.cleanup_old_files()
    print(f"清理统计: {stats}")
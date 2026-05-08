import subprocess
import os
import sys
import json
from pathlib import Path

class BilibiliUploader:
    def __init__(self, config=None):
        self.config = config or {}
        # B站分区 ID，默认 17 (音乐) 或 138 (音乐综合)
        self.default_tid = self.config.get("bilibili_tid", 138)
        self.default_tags = self.config.get("bilibili_tags", ["音乐", "网易云音乐", "动态歌词"])
        self.cookie_file = "cookies.json" # biliup 登录后生成的文件名

    def upload(self, video_path: str, title: str, description: str = "", tags: list = None, tid: int = None):
        """
        通过 biliup CLI 上传视频到 B 站
        """
        if not os.path.exists(video_path):
            return {"success": False, "error": f"视频文件不存在: {video_path}"}

        tags = tags or self.default_tags
        tid = tid or self.default_tid
        
        # 构造命令行指令
        # 注意：biliup 需要先通过 'biliup login' 扫码登录成功后才可用
        cmd = [
            "biliup", "upload", 
            str(Path(video_path).resolve()),
            "--title", title,
            "--desc", description or f"本视频由 AI 自动生成。\n标题: {title}",
            "--tags", ",".join(tags),
            "--tid", str(tid)
        ]

        try:
            # 执行投稿
            # 使用 shell=True 在 Windows 下处理命令行路径更稳健
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True,
                encoding="utf-8",
                shell=True
            )
            
            stdout, stderr = process.communicate()
            
            if process.returncode == 0:
                return {"success": True, "output": stdout}
            else:
                # 检查是否是因为未登录
                if "未登录" in stderr or "login" in stderr.lower():
                    return {"success": False, "error": "尚未登录 B 站，请先在终端运行 'biliup login' 进行扫码登录。"}
                return {"success": False, "error": stderr or "未知错误"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}

if __name__ == "__main__":
    # 简单测试入口
    import sys
    if len(sys.argv) > 1:
        uploader = BilibiliUploader()
        res = uploader.upload(sys.argv[1], "测试投稿")
        print(res)
    else:
        print("用法: python bilibili_uploader.py <视频路径>")

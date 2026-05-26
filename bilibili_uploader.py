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
        # 使用与 bilibili_auth 相同的绝对路径，确保无缝读写 cookies.json
        if getattr(sys, 'frozen', False):
            self.base_dir = os.path.dirname(sys.executable)
        else:
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.cookie_file = os.path.join(self.base_dir, "cookies.json")

    def upload(self, video_path: str, title: str, description: str = "", tags: list = None, tid: int = None, cover: str = ""):
        """
        通过 stream-gears 的 Python 绑定直接上传视频到 B 站，无需依赖外部 biliup.exe 可执行文件。
        """
        if not os.path.exists(video_path):
            return {"success": False, "error": f"视频文件不存在: {video_path}"}

        # 检查 stream-gears 是否安装
        if not self._check_biliup_installed():
            return {"success": False, "error": "stream-gears 库未安装。请运行: pip install stream-gears"}

        # 检查 cookies 文件是否存在且不为空
        if not os.path.exists(self.cookie_file) or os.path.getsize(self.cookie_file) == 0:
            return {"success": False, "error": "尚未登录 B 站，请先在界面扫码登录。"}

        tags = tags or self.default_tags
        tid = tid or self.default_tid
        description = description or ""
        
        # 格式化 tag 为逗号分隔的字符串
        tag_str = ",".join(tags) if isinstance(tags, list) else str(tags)
        
        # 构建新版描述结构 desc_v2
        desc_v2 = [{
            "raw_text": description,
            "biz_id": "",
            "type": 1
        }] if description else []

        # 准备封面路径
        cover_path = str(Path(cover).resolve()) if cover and os.path.exists(cover) else ""

        try:
            import stream_gears
            
            # 使用 stream_gears 的原厂能力进行上传
            # 传参说明:
            # - video_path: 列表形式，支持多P
            # - cookie_file: cookies 绝对路径
            # - copyright: 1 为原创/自制，2 为转载
            # - source: 转载来源，如果是自制通常传空字符串
            print(f"[i] 正在使用 stream-gears 直传 B 站 (视频: {video_path})...")
            stream_gears.upload(
                video_path=[str(Path(video_path).resolve())],
                cookie_file=self.cookie_file,
                title=title[:80],
                tid=tid,
                tag=tag_str,
                copyright=1, # 1 自制，2 转载
                source="",
                desc=description,
                dynamic="",
                cover=cover_path,
                dolby=0,
                lossless_music=0,
                no_reprint=0,
                open_elec=0,
                limit=3, # 并发线程数
                desc_v2=desc_v2
            )
            print("[OK] 视频上传成功！")
            return {"success": True}
        except Exception as e:
            print(f"[FAIL] 视频上传失败: {e}")
            return {"success": False, "error": f"上传失败: {e}"}
    
    def _check_biliup_installed(self):
        """检查 stream-gears 是否已正确安装"""
        try:
            import stream_gears
            return True
        except ImportError:
            return False

if __name__ == "__main__":
    # 简单测试入口
    import sys
    if len(sys.argv) > 1:
        uploader = BilibiliUploader()
        res = uploader.upload(sys.argv[1], "测试投稿")
        print(res)
    else:
        print("用法: python bilibili_uploader.py <视频路径>")

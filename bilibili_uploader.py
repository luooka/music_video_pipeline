import logging
import os
import sys
from pathlib import Path

from bilibili_auth import BilibiliAuth

logger = logging.getLogger('pipeline.bilibili_uploader')


class BilibiliUploader:
    def __init__(self, config=None):
        self.config = config or {}
        self.default_tid = self.config.get("bilibili_tid", 138)
        self.default_tags = self.config.get("bilibili_tags", ["音乐", "网易云音乐", "动态歌词"])
        if getattr(sys, 'frozen', False):
            self.base_dir = os.path.dirname(sys.executable)
        else:
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.cookie_file = os.path.join(self.base_dir, "cookies.json")

    def upload(self, video_path: str, title: str, description: str = "", tags: list = None, tid: int = None, cover: str = ""):
        """通过 stream-gears 的 Python 绑定直接上传视频到 B 站"""
        if not video_path or not os.path.isfile(video_path):
            return {"success": False, "error": f"视频文件不存在: {video_path}"}

        if not self._check_biliup_installed():
            return {"success": False, "error": "stream-gears 库未安装。请运行: pip install stream-gears"}

        auth = BilibiliAuth()
        if not auth.is_cookie_valid():
            return {"success": False, "error": "尚未登录 B 站或登录凭证无效，请先在界面扫码登录。"}

        raw_tags = tags if tags is not None else self.default_tags
        if isinstance(raw_tags, str):
            raw_tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        clean_tags = [str(t).strip()[:20] for t in (raw_tags or []) if str(t).strip()][:10]
        if not clean_tags:
            clean_tags = [str(t).strip()[:20] for t in self.default_tags if str(t).strip()][:10] or ["音乐"]

        tid = tid or self.default_tid
        description = description or ""
        safe_title = (title or "网易云音乐推荐").strip()[:80] or "网易云音乐推荐"
        tag_str = ",".join(clean_tags)

        desc_v2 = [{
            "raw_text": description,
            "biz_id": "",
            "type": 1
        }] if description else []

        cover_path = ""
        if cover and str(cover).strip():
            if os.path.isfile(cover):
                cover_path = str(Path(cover).resolve())
            else:
                logger.warning(f"指定的封面文件不存在，将使用视频首帧: {cover}")

        try:
            import stream_gears

            logger.info(f"正在使用 stream-gears 直传 B 站 (视频: {video_path})...")
            ret = stream_gears.upload(
                video_path=[str(Path(video_path).resolve())],
                cookie_file=self.cookie_file,
                title=safe_title,
                tid=tid,
                tag=tag_str,
                copyright=1,
                source="",
                desc=description,
                dynamic="",
                cover=cover_path,
                dolby=0,
                lossless_music=0,
                no_reprint=0,
                open_elec=0,
                limit=3,
                desc_v2=desc_v2
            )
            logger.info("视频上传成功！")
            resp = {"success": True}
            if isinstance(ret, dict) and ret.get("bvid"):
                resp["bvid"] = ret["bvid"]
            return resp
        except Exception as e:
            logger.error(f"视频上传失败: {e}")
            return {"success": False, "error": f"上传失败: {e}"}

    def _check_biliup_installed(self):
        try:
            import stream_gears  # noqa: F401
            return True
        except ImportError:
            return False


if __name__ == "__main__":
    if len(sys.argv) > 1:
        uploader = BilibiliUploader()
        res = uploader.upload(sys.argv[1], "测试投稿")
        print(res)
    else:
        print("用法: python bilibili_uploader.py <视频路径>")

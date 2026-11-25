import base64
import json
import logging
import os
import shutil
import sys
from io import BytesIO
from pathlib import Path

import qrcode
import stream_gears

logger = logging.getLogger('pipeline.bilibili_auth')


class BilibiliAuth:
    def __init__(self):
        if getattr(sys, 'frozen', False):
            self.base_dir = os.path.dirname(sys.executable)
        else:
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.cookie_path = os.path.join(self.base_dir, "cookies.json")

    def is_cookie_valid(self) -> bool:
        """检查 cookies.json 是否存在且为结构有效的凭证 JSON"""
        try:
            if not os.path.exists(self.cookie_path) or os.path.getsize(self.cookie_path) <= 10:
                return False
            with open(self.cookie_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or not data:
                return False
            # stream-gears / biliup cookies.json 通常包含 token_info 与 cookie_info
            if data.get("token_info") or data.get("cookie_info"):
                return True
            return any(k in data for k in ("SESSDATA", "access_token", "bili_jct"))
        except Exception:
            return False

    def get_qr_info(self, save_to_disk: bool = True):
        """
        借调 stream_gears 获取二维码信息，返回 Data URI（可选落盘，供 CLI/MCP 使用）
        """
        try:
            raw_res = stream_gears.get_qrcode(None)
            data = json.loads(raw_res)

            if data.get("code") == 0:
                qr_url = data["data"]["url"]
                qr_img = qrcode.make(qr_url)

                buf = BytesIO()
                qr_img.save(buf, format="PNG")
                b64_data = base64.b64encode(buf.getvalue()).decode("ascii")
                result = {
                    "success": True,
                    "qr_data_uri": f"data:image/png;base64,{b64_data}",
                    "raw_json": raw_res,
                }

                if save_to_disk:
                    qr_path = os.path.join(self.base_dir, "bilibili_login_qr.png")
                    tmp_qr = Path(qr_path).with_suffix(".tmp.png")
                    tmp_qr.write_bytes(buf.getvalue())
                    tmp_qr.replace(qr_path)
                    result["qr_path"] = os.path.abspath(qr_path)

                return result
            return {"success": False, "error": data.get("message", "获码失败")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def verify_login(self, qr_json_str):
        """
        调用 stream_gears 校验扫码并原子写入 cookies.json
        """
        try:
            logger.info("[BILIBILI-AUTH] 开始调用 stream_gears.login_by_qrcode 等待扫码确认...")

            cwd_cookie = os.path.join(os.getcwd(), "cookies.json")
            if os.path.abspath(cwd_cookie) != os.path.abspath(self.cookie_path) and os.path.exists(cwd_cookie):
                try:
                    shutil.move(cwd_cookie, self.cookie_path)
                except Exception as me:
                    logger.warning(f"[BILIBILI-AUTH] 迁移旧 cookies 失败: {me}")

            success = stream_gears.login_by_qrcode(qr_json_str, None)

            if success:
                tmp_cookie = Path(self.cookie_path).with_suffix(".json.tmp")
                try:
                    with open(tmp_cookie, 'w', encoding='utf-8') as f:
                        if isinstance(success, str):
                            f.write(success)
                        elif isinstance(success, dict):
                            json.dump(success, f, indent=2, ensure_ascii=False)
                        else:
                            if hasattr(success, "dict"):
                                json.dump(success.dict(), f, indent=2, ensure_ascii=False)
                            elif hasattr(success, "__dict__"):
                                json.dump(success.__dict__, f, indent=2, ensure_ascii=False)
                            else:
                                try:
                                    parsed = json.loads(str(success))
                                    json.dump(parsed, f, indent=2, ensure_ascii=False)
                                except Exception:
                                    try:
                                        json.dump(dict(success), f, indent=2, ensure_ascii=False)
                                    except Exception:
                                        f.write(str(success))
                    tmp_cookie.replace(self.cookie_path)
                except Exception as we:
                    if tmp_cookie.exists():
                        try:
                            tmp_cookie.unlink()
                        except Exception:
                            pass
                    return {"success": False, "error": f"保存cookies文件失败: {str(we)}"}

                if self.is_cookie_valid():
                    logger.info("[BILIBILI-AUTH] 校验成功！已生成 cookies.json")
                    return {"success": True, "status": "success"}
                if os.path.exists(self.cookie_path):
                    return {"success": True, "status": "success"}
                return {"success": False, "error": f"授权成功但cookies文件未生成在: {self.cookie_path}"}
            else:
                return {"success": False, "error": "扫码验证失败或已超时"}
        except Exception as e:
            logger.exception(f"[BILIBILI-AUTH] 校验过程捕获异常: {e}")
            return {"success": False, "error": str(e)}


if __name__ == "__main__":
    auth = BilibiliAuth()
    res = auth.get_qr_info()
    if res["success"]:
        print(f"二维码已准备就绪: {res.get('qr_path')}")
    else:
        print(f"获取二维码失败: {res['error']}")

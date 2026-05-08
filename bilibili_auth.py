import stream_gears
import qrcode
import os
import json
from pathlib import Path
from PIL import Image

class BilibiliAuth:
    def __init__(self):
        # 使用绝对路径，确保在任何工作目录下都能准确找到 cookies
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.cookie_path = os.path.join(self.base_dir, "cookies.json")

    def get_qr_info(self):
        """
        借调 stream_gears 原厂能力获取二维码信息
        返回包含 url 和 auth_code 的原始 JSON 字符串，以及生成的本地图片路径
        """
        try:
            # 获取图片时也要确保路径正确
            qr_path = os.path.join(self.base_dir, "bilibili_login_qr.png")
            # 1. 直接获取 JSON 响应 (无需代理)
            raw_res = stream_gears.get_qrcode(None)
            data = json.loads(raw_res)
            
            if data.get("code") == 0:
                qr_url = data["data"]["url"]
                
                # 2. 生成本地二维码图片供用户扫码
                qr_img = qrcode.make(qr_url)
                qr_img.save(qr_path)
                
                return {
                    "success": True, 
                    "qr_path": os.path.abspath(qr_path),
                    "raw_json": raw_res  # 将完整 JSON 存为凭证，后续校验需要原样传回
                }
            return {"success": False, "error": data.get("message", "获码失败")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def verify_login(self, qr_json_str):
        """
        直接将原厂 JSON 传授给原厂校验函数
        biliup 会自动在当前目录下生成 cookies.json
        """
        try:
            # 关键修复：强制切换到代码目录，确保 Rust 引擎把 cookies.json 写在这里
            old_cwd = os.getcwd()
            os.chdir(self.base_dir)
            
            try:
                # stream_gears.login_by_qrcode 现在也需要传递 proxy 参数 (我们传 None)
                success = stream_gears.login_by_qrcode(qr_json_str, None)
            finally:
                # 恢复原有的工作目录，避免干扰 MCP 其他功能
                os.chdir(old_cwd)
            
            if success:
                # 再次确认文件是否已刷新
                if os.path.exists(self.cookie_path):
                    return {"success": True, "status": "success"}
                return {"success": False, "error": f"授权成功但未找到文件。当前CWD: {old_cwd}, 期待路径: {self.cookie_path}"}
            return {"success": False, "error": "扫码验证失败或已超时"}
        except Exception as e:
            # 这里的异常可能是扫码超时返回的错误
            return {"success": False, "error": str(e)}

if __name__ == "__main__":
    auth = BilibiliAuth()
    res = auth.get_qr_info()
    if res["success"]:
        print(f"二维码已准备就绪: {res['qr_path']}")
        print(f"原始凭证: {res['raw_json']}")
    else:
        print(f"重构方案仍有问题: {res['error']}")

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
        使用绝对路径确保 cookies.json 生成在正确位置
        """
        try:
            # 使用绝对路径，不切换工作目录
            import json
            import tempfile
            
            # 创建临时文件保存原始JSON
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as tmp:
                tmp.write(qr_json_str)
                temp_json_path = tmp.name
            
            try:
                # 使用绝对路径调用stream_gears
                # 注意：stream_gears.login_by_qrcode需要原始JSON字符串，不是文件路径
                # 我们直接传递字符串，但确保cookies路径正确
                
                # 先检查当前目录是否有旧cookies
                if os.path.exists("cookies.json"):
                    # 如果当前目录有，移动到项目目录
                    try:
                        import shutil
                        shutil.move("cookies.json", self.cookie_path)
                    except Exception:
                        pass
                
                # 直接调用，依赖stream_gears内部逻辑
                success = stream_gears.login_by_qrcode(qr_json_str, None)
                
                # 检查cookies是否生成在项目目录
                if not os.path.exists(self.cookie_path):
                    # 检查是否生成在当前目录
                    if os.path.exists("cookies.json"):
                        try:
                            import shutil
                            shutil.move("cookies.json", self.cookie_path)
                        except Exception as e:
                            return {"success": False, "error": f"移动cookies失败: {str(e)}"}
            
            finally:
                # 清理临时文件
                try:
                    os.unlink(temp_json_path)
                except Exception:
                    pass
            
            if success:
                # 最终确认文件存在
                if os.path.exists(self.cookie_path):
                    return {"success": True, "status": "success"}
                return {"success": False, "error": f"授权成功但cookies文件未生成在: {self.cookie_path}"}
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

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
            print(f"\n[BILIBILI-AUTH] >>> 进入 verify_login 状态校验")
            print(f"[BILIBILI-AUTH] 待验证凭证长度: {len(qr_json_str) if qr_json_str else 0}")
            print(f"[BILIBILI-AUTH] 凭证内容缩略: {qr_json_str[:150] if qr_json_str else 'None'}...")
            
            # 先检查当前目录是否有旧cookies
            if os.path.exists("cookies.json"):
                print("[BILIBILI-AUTH] 当前目录发现旧 cookies.json，准备迁移...")
                try:
                    import shutil
                    shutil.move("cookies.json", self.cookie_path)
                    print(f"[BILIBILI-AUTH] 旧 cookies.json 迁移成功 -> {self.cookie_path}")
                except Exception as me:
                    print(f"[BILIBILI-AUTH] 迁移旧 cookies 失败: {me}")
            
            print("[BILIBILI-AUTH] 正在调用 stream_gears.login_by_qrcode (此步骤是阻塞长轮询)...")
            success = stream_gears.login_by_qrcode(qr_json_str, None)
            print(f"[BILIBILI-AUTH] stream_gears.login_by_qrcode 返回值已获取。")
            
            if success:
                # 将授权返回的 cookies 数据直接写入项目 cookies.json 路径
                print(f"[BILIBILI-AUTH] 准备将登录结果写入 cookies 文件: {self.cookie_path}")
                try:
                    import json
                    with open(self.cookie_path, 'w', encoding='utf-8') as f:
                        if isinstance(success, str):
                            f.write(success)
                        elif isinstance(success, dict):
                            json.dump(success, f, indent=2, ensure_ascii=False)
                        else:
                            # 尝试处理特殊的 Rust/C 扩展对象
                            try:
                                if hasattr(success, "dict"):
                                    json.dump(success.dict(), f, indent=2, ensure_ascii=False)
                                elif hasattr(success, "__dict__"):
                                    json.dump(success.__dict__, f, indent=2, ensure_ascii=False)
                                else:
                                    # 尝试将其转换为 dict，或反序列化其文本表示
                                    try:
                                        # 如果其 str(success) 本身已经是标准的 JSON 格式（如 Rust 打印的 Debug 格式）
                                        # 我们先尝试解析成 dict，然后再标准格式化写入
                                        parsed = json.loads(str(success))
                                        json.dump(parsed, f, indent=2, ensure_ascii=False)
                                    except Exception:
                                        json.dump(dict(success), f, indent=2, ensure_ascii=False)
                            except Exception:
                                # 最后保底方案，直接写入其 str() 表示
                                f.write(str(success))
                    print("[BILIBILI-AUTH] cookies.json 文件写入成功！")
                except Exception as we:
                    print(f"[BILIBILI-AUTH] 写入 cookies 文件失败: {we}")
                    return {"success": False, "error": f"保存cookies文件失败: {str(we)}"}
            
            # 最终确认文件存在
            if os.path.exists(self.cookie_path):
                print("[BILIBILI-AUTH] 校验成功！已生成有效的 cookies.json 凭证文件。")
                return {"success": True, "status": "success"}
            else:
                print("[BILIBILI-AUTH] 错误：在目标路径未发现 cookies.json")
                return {"success": False, "error": f"授权成功但cookies文件未生成在: {self.cookie_path}"}
            
            print("[BILIBILI-AUTH] 扫码失败或已超时。")
            return {"success": False, "error": "扫码验证失败或已超时"}
        except Exception as e:
            print(f"[BILIBILI-AUTH] 校验过程捕获异常: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}

if __name__ == "__main__":
    auth = BilibiliAuth()
    res = auth.get_qr_info()
    if res["success"]:
        print(f"二维码已准备就绪: {res['qr_path']}")
        print(f"原始凭证: {res['raw_json']}")
    else:
        print(f"重构方案仍有问题: {res['error']}")

# Music Video Pipeline (MVP) 🎵🎬

这是一个自动化的音乐视频流水线，能够自动获取网易云音乐推荐、生成 AI 视觉背景、并合成带动态律动条和字幕的专业播放器视频。

## 🌟 核心特性

- **自动化选曲**：对接网易云音乐 API，支持获取每日推荐或搜索热门曲目。
- **AI 视觉增强**：通过 ComfyUI 自动根据专辑封面风格生成高度关联的沉浸式背景（支持备用方案）。
- **专业级播放器 UI**：
  - **镜像律动条**：实时频谱分析，呈现上下对称的动态节奏感。
  - **离散竖条风格**：对标主流音乐博主的简约高级感设计。
  - **动态歌词**：生成精确到毫秒的 ASS 格式字幕。
- **极致性能优化**：
  - **多层缓存机制**：音频、封面、歌词及合成好的视频片段均支持持久化缓存，跨日运行不重下，合成秒完成。
  - **资源回收**：自动清理临时文件，保持目录整洁。
- **Windows 深度优化**：完美解决 FFmpeg 在 Windows 环境下的路径转义和编码报错。

## 🛠️ 环境准备

### 1. 基础依赖
- Python 3.10+
- FFmpeg (需添加到系统环境变量)

### 2. 安装 Python 库
```bash
pip install -r requirements.txt
```

### 3. (可选) ComfyUI 配置
若要开启 AI 背景生成功能，请确保本地或服务器已启动 ComfyUI，并能访问其 API 端口。

## 🚀 快速开始

### 1. 配置账号
首次运行会生成 `config.json`，请填入你的网易云 `netease_cookie` (MUSIC_U)：
```json
{
  "netease_cookie": "你的 MUSIC_U 值",
  "comfyui_server": "127.0.0.1:8188",
  "song_count": 10
}
```

### 2. 运行流水线
```bash
# 生成 3 首推荐曲目进行测试
python main.py --test

# 生成指定数量的曲目
python main.py --count 10

# 跳过 AI 生成，使用模糊背景 (更稳健)
python main.py --skip-comfyui
```

## 📂 项目结构
- `main.py`: 流水线主控程序。
- `video_maker.py`: 核心合成引擎（FFmpeg 驱动）。
- `netease_api.py`: 封装的网易云 API 交互。
- `output/`: 所有的输出文件和缓存均存放在此。

## 🛡️ 隐私说明
本项目的 `.gitignore` 已配置为排除 `config.json` 和 `output/` 文件夹。请妥善保管您的 Cookie 信息，不要将其上传至公开仓库。

## 📄 开源协议
MIT License

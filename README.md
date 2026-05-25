# 🎵 Music Video Pipeline (MVP)

全自动音乐视频生成流水线 —— 从**网易云音乐**获取歌曲，自动合成带专业播放器 UI、动态律动频谱、同步歌词的 **1080P 视频**，支持一键上传至 **Bilibili**。

提供完整的 **Web GUI 可视化界面**，无需命令行操作，全程浏览器内完成选曲 → 合成 → 投稿。

---

## ✨ 功能亮点

### 🎵 网易云音乐深度集成
- **扫码登录**：Web 界面内直接扫码登录网易云账号，无需手动复制 Cookie
- **每日推荐**：一键获取个性化日推歌曲
- **歌单浏览**：自动获取「我喜欢」以及用户创建的所有歌单，侧边栏快速切换
- **曲库搜索**：支持全站关键词搜索，分页加载结果
- **歌单分页**：大歌单自动分页加载，避免卡顿

### 🎨 专业视频画面
- **动态律动频谱**：实时镜像频谱条，上下对称节奏律动
- **智能模糊背景**：基于专辑封面自动生成渐变模糊背景
- **歌词同步字幕**：毫秒级精度 ASS 格式歌词同步
- **播放器式排版**：专辑封面 + 歌手名 + 歌名的专业播放器布局

### 🖥️ 三页式 Web GUI
- **合成页**（首页）：歌曲选择 → 卡片网格展示 → 勾选歌曲 → 一键合成
- **监控页**：实时任务进度追踪、步骤可视化、底层日志终端
- **投稿页**：Bilibili 扫码登录 → 自定义标题/封面/简介 → 一键上传

### ⚡ 自动化工作流
- **B站扫码登录**：Web 界面扫码授权，Cookie 自动持久化
- **自动上传**：合成完成后可选自动上传至 Bilibili
- **投稿格式模板**：预设投稿标题/简介/标签模板，支持自定义
- **智能缓存**：音频、封面、歌词、视频片段多级缓存，避免重复下载
- **自动清理**：按时间/磁盘容量自动清理过期文件

### 🔌 MCP 协议支持
- 内置 MCP Server，可对接支持 MCP 的 AI 客户端
- 支持通过 AI 对话触发推荐获取、视频合成、状态查询

---

## 📦 快速开始

### 环境要求
| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | 3.10+ | 必须添加到系统 PATH |
| FFmpeg | 最新版 | 视频处理核心，必须在 PATH 中 |

### 安装

```bash
# 1. 克隆项目
git clone https://github.com/yourusername/music_video_pipeline.git
cd music_video_pipeline

# 2. 创建虚拟环境（推荐）
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Linux / macOS

# 3. 安装依赖
pip install -r requirements.txt

# 4. 复制配置模板
copy config.template.json config.json   # Windows
cp config.template.json config.json     # Linux / macOS
```

### 安装 FFmpeg
- **Windows**：下载 [FFmpeg](https://ffmpeg.org/download.html) 并将 `bin` 目录添加到系统 PATH
- **Linux**：`sudo apt install ffmpeg`
- **macOS**：`brew install ffmpeg`

---

## 🚀 启动与使用

### 方式一：Windows 一键启动（推荐）

双击 `start.bat`，自动完成：
1. 检查虚拟环境并激活
2. 安装缺失依赖
3. 释放端口占用
4. 启动 Web 服务
5. 打开浏览器访问 `http://127.0.0.1:8000`

### 方式二：手动启动

```bash
# 启动 Web API 服务
python api_service.py

# 浏览器访问
# http://127.0.0.1:8000
```

### 方式三：命令行模式

```bash
python main.py --count 5       # 生成5首每日推荐
python main.py --test           # 测试模式（3首）
python main.py --demo           # 演示模式（热门歌曲）
```

---

## 🎮 使用流程

### Step 1：登录网易云

首次使用时，打开浏览器会进入**登录页**：
1. 页面显示网易云扫码二维码
2. 用网易云音乐 App 扫码确认
3. 登录成功后自动跳转至合成页

### Step 2：选择歌曲（合成页）

- **左侧边栏**列出你的歌单：日推、我喜欢、创建的歌单
- 点击任意歌单 → 右侧以**卡片网格**展示歌曲
- 也可使用顶部**搜索框**检索全站歌曲
- 点击卡片选中歌曲，支持多选
- 底部操作栏实时显示已选数量

### Step 3：启动合成

- 选择完毕后点击底部的 **「一键合成」** 按钮
- 可选勾选「自动上传 B 站」
- 页面自动跳转至**监控页**

### Step 4：监控进度（监控页）

- 5 步式进度可视化：解析 → 下载 → 频谱 → 压制 → 上传
- 实时进度条与百分比
- 可展开底层日志终端查看详细输出
- 完成后弹出结果弹窗，显示视频路径

### Step 5：上传投稿（投稿页）

- B站扫码登录（登录状态持久化）
- 自动填充视频路径、标题、封面
- 支持投稿格式模板，一键套用
- 点击「上传到 B 站」完成投稿

---

## 📁 项目结构

```
music_video_pipeline/
├── api_service.py          # FastAPI 后端服务（核心入口）
├── main.py                 # 主流水线处理器
├── netease_api.py          # 网易云音乐 API 封装（pyncm）
├── video_maker.py          # FFmpeg 视频合成引擎
├── bilibili_auth.py        # B站扫码登录认证
├── bilibili_uploader.py    # B站视频上传器
├── cleanup_manager.py      # 自动资源清理管理器
├── mcp_server.py           # MCP 协议服务器
├── gui_client.py           # Web GUI 启动客户端
├── config.template.json    # 配置模板（需复制为 config.json）
├── upload_formats.json     # B站投稿格式预设
├── requirements.txt        # Python 依赖
├── start.bat               # Windows 一键启动脚本
├── force_kill.bat           # 进程清理脚本
├── static/                 # Web 前端页面
│   ├── index.html          # 合成页（选曲主页）
│   ├── login.html          # 网易云扫码登录页
│   ├── logs.html           # 任务监控大盘页
│   └── upload.html         # B站投稿页
└── output/                 # 生成的视频输出（按日期组织）
```

---

## ⚙️ 配置说明

复制 `config.template.json` 为 `config.json` 后编辑：

```jsonc
{
  "netease_cookie": "",              // 通过 Web 界面扫码自动写入，无需手动填写
  "netease_api_base": "http://localhost:3000",
  "api_port": 8000,                  // Web 服务端口
  "output_dir": "./output",          // 视频输出目录
  "video_width": 1920,               // 视频分辨率
  "video_height": 1080,
  "video_fps": 24,
  "bilibili_tid": 138,               // B站投稿分区 ID
  "bilibili_tags": ["音乐", "网易云音乐", "动态歌词"],
  "visual": {                        // 视觉参数
    "blur_radius": 40,
    "blend_alpha": 0.5,
    "title_font_size": 70,
    "artist_font_size": 35
  },
  "video": {                         // 编码参数
    "threads": 1,
    "preset": "ultrafast",
    "audio_bitrate": "128k",
    "spectrum_size": "800x75"
  },
  "cleanup": {                       // 自动清理策略
    "max_age_days": 7,
    "max_total_size_gb": 10,
    "cleanup_on_start": true
  }
}
```

> **提示**：`netease_cookie` 会在首次扫码登录后自动写入，通常无需手动配置。

---

## 🔧 API 接口

服务启动后可访问 `http://localhost:8000/docs` 查看完整 Swagger 文档。

| 接口 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/config` | GET/POST | 读取/更新配置 |
| `/recommendations` | GET | 获取每日推荐 |
| `/search?q=xxx` | GET | 搜索歌曲 |
| `/netease/playlists` | GET | 获取用户歌单列表 |
| `/netease/playlist/tracks?id=xxx` | GET | 获取歌单曲目（支持分页） |
| `/generate` | POST | 启动视频合成任务 |
| `/status` | GET | 查询任务状态与日志 |
| `/bilibili/upload` | POST | 上传视频到B站 |
| `/netease/qr/*` | GET/POST | 网易云扫码登录接口 |
| `/bilibili/qr/*` | GET/POST | B站扫码登录接口 |

---

## 🐛 常见问题

| 问题 | 解决方案 |
|------|----------|
| FFmpeg 未找到 | 确保 `ffmpeg` 在系统 PATH 中，或重新安装 |
| 扫码登录失败 | 二维码有效期约 2 分钟，过期请刷新重试 |
| 端口被占用 | 修改 `config.json` 中的 `api_port`，或运行 `force_kill.bat` |
| 磁盘空间不足 | 调整 `cleanup.max_total_size_gb` 或手动清理 `output/` |
| 歌单加载缓慢 | 大歌单已自动分页，每次加载 20 首 |

---

## 📄 许可证

本项目采用 MIT 许可证。

## 🙏 致谢

- [biliup](https://github.com/ForgQi/biliup-rs) — B站上传工具
- [FFmpeg](https://ffmpeg.org/) — 多媒体处理框架
- [FastAPI](https://fastapi.tiangolo.com/) — Web 框架

---

> **⚠️ 免责声明**：本项目仅供学习和研究使用，请遵守相关平台的服务条款，尊重音乐版权。

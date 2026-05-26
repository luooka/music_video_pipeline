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

### 🖥️ 统一交互的三页式 Web GUI
- **一致性双栏架构**：合成页与监控页采用完全对齐的左侧边栏（网易云账号状态）与右侧主视区，顶部配备统一的导航控制区，支持在**当前窗口**（非弹窗）高频无缝切页。
- **合成页**：支持歌单浏览、曲库搜索、卡片网格多选曲目，底部浮动操作区一键加入异步合成队列。
- **监控页**：直观展示垂直任务队列列表卡片。每个任务具备独立状态标签、高精度进度条与操作按钮。支持中途干预（取消等待中/进行中的任务，或删除已完成/失败的任务）。
- **投稿页**：精简版面结构，左侧集成 Bilibili 扫码登录与持久化，右侧支持快捷套用预设格式模板一键填表。

### ⚡ 智能与静默工作流
- **无感跨页数据传递**：任务合成成功后，弹窗支持一键“去投稿”——自动在当前标签页跳转并把生成的视频路径作为 URL 参数安全带入，实现投稿页**视频路径自动填充**。
- **智能防重复弹窗**：使用会话级缓存（`sessionStorage`）智能记忆已关闭的完成弹窗，切换页面或刷新时不会发生重复弹窗。
- **双通道本地浏览秒传**：视频与封面均提供精致的 `浏览...` 按钮，选择本地文件后自动通过接口静默上传并返回服务器临时路径，自动回填文本框，支持输入框的上传状态与禁用保护。
- **无黑窗后台运行**：打包模式下自动以无黑窗隐藏线程运行后端 Python 服务，并通过 Microsoft Edge “应用模式”打开无边框高颜值独立窗口，告别传统命令行黑窗。

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

### Step 4：监控进度与控制（监控页）

- **极简任务卡片队列**：垂直一列展示当前所有等待中、进行中和已完成的合成任务。
- **高精准进度与状态**：任务卡片提供独立的进度条、状态呼吸标签，并支持展开终端日志详细输出。
- **任务中途干预**：可在队列卡片中随时点击“取消”处于排队中或进行中的任务，或“删除”已完成或失败的历史任务。
- **一键去投稿联动**：合成成功后，弹窗完美对齐“关闭”、“复制路径”、“去投稿”三大按钮。点击“去投稿”会直接在**当前窗口**快速跳转至投稿页，并自动在 URL 中挂载并向投稿页安全传递生成的视频本地绝对路径。

### Step 5：极简上传投稿（投稿页）

- **B站扫码登录**：左侧边栏支持扫码授权（登录状态安全持久化）。
- **零打字路径自动填充**：从监控页的合成成功弹窗点击“去投稿”跳转后，页面会自动解析并**一键将视频文件路径精准填充到表单输入框中**。
- **封面一键浏览上传**：提供“视频文件”与“封面图片”并列的双通道 **`浏览...`** 按钮。点击即可浏览选择本地封面图片，系统会自动静默完成服务器上传并智能回填其网络或本地临时路径，告别繁杂的手动路径打字。
- **格式套用一键投递**：支持投稿格式模板，可一键自动套用预设标题、标签和简介，点击「开始上传」即可静默投递。

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

## 📦 打包为 EXE

项目已预配置好 PyInstaller 打包脚本，可以将整个程序（含 Python 运行时、所有依赖库、FFmpeg、前端页面）打包为一个**免安装的独立 `.exe` 文件**，在任何 Windows 电脑上双击即可运行。

### 前置条件

```bash
pip install pyinstaller
```

### 一键打包

```bash
cd d:\code\music_video_pipeline
pyinstaller --clean MusicVideoPipeline.spec
```

编译完成后，`dist/MusicVideoPipeline.exe` 就是最终产物（约 75 MB）。

### 发布目录结构

将以下文件放到同一个文件夹中，打成 `.zip` 即可发布：

```
MusicVideoPipeline-v1.x.x/
├── MusicVideoPipeline.exe      # 主程序（从 dist/ 复制）
├── config.template.json        # 配置模板（用户复制为 config.json）
└── upload_formats.json         # 投稿格式预设
```

### 发布到 GitHub Releases

1. 在仓库页面点击 **Releases → Create a new release**
2. 填写版本标签（如 `v1.0.0`）和发布说明
3. 将上面的 `.zip` 压缩包拖入附件区域
4. 点击 **Publish release**

### ⚠️ 打包注意事项

- **重新编译前**必须先关闭正在运行的 `MusicVideoPipeline.exe`，否则 PyInstaller 会因文件锁定而报 `PermissionError`
- 如果需要强制关闭：`taskkill /F /IM MusicVideoPipeline.exe`
- 修改 Python 源码后只需重新运行 `pyinstaller --clean MusicVideoPipeline.spec`，无需其他操作
- `.spec` 文件中已配置 `console=False`（无命令行黑窗）和 `datas=[('static', 'static')]`（自动打包前端页面）

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

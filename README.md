# Music Video Pipeline (MVP) 🎵🎬

一个全自动的音乐视频生成流水线，能够从网易云音乐获取推荐曲目，自动合成带专业播放器 UI、动态频谱和歌词的 1080P 视频，并支持一键上传至 Bilibili。

## ✨ 特性亮点

### 🎵 智能音乐源
- **网易云音乐集成**：支持每日推荐、热门搜索、歌单获取
- **多源音频下载**：自动获取最高品质音频文件
- **完整元数据**：歌曲信息、专辑封面、艺术家信息

### 🎨 专业播放器 UI
- **动态频谱可视化**：实时镜像律动条，上下对称节奏感
- **智能背景生成**：基于专辑封面的模糊渐变背景
- **动态歌词同步**：精确到毫秒的 ASS 格式字幕
- **响应式排版**：自动换行处理，适应长标题和多艺术家

### ⚡ 性能优化
- **多层缓存系统**：音频、封面、歌词、视频片段持久化缓存
- **智能资源管理**：自动清理过期文件，防止磁盘溢出
- **并发处理**：异步下载与合成，提升处理效率

### 🔄 完整工作流
- **一键启动**：提供 GUI 界面和 CLI 两种模式
- **Bilibili 上传**：集成 biliup，支持自动上传
- **API 服务**：RESTful API 支持远程控制
- **跨平台支持**：Windows/Linux/macOS 兼容

## 📦 快速开始

### 环境要求
- **Python 3.10+**：确保已安装并添加到 PATH
- **FFmpeg**：视频处理核心工具，必须添加到系统 PATH
- **网易云音乐 Cookie**：需要登录后获取 MUSIC_U 值

### 🛠️ 安装步骤

#### 1. 获取项目代码
```bash
# 克隆项目到本地
git clone https://github.com/yourusername/music_video_pipeline.git
cd music_video_pipeline
```

#### 2. 安装 Python 依赖
```bash
# 使用 pip 安装所有依赖包
pip install -r requirements.txt
```

#### 3. 安装 FFmpeg
- **Windows**：下载 [FFmpeg](https://ffmpeg.org/download.html) 并解压，将 `bin` 目录添加到系统 PATH
- **Linux**：`sudo apt install ffmpeg` (Ubuntu/Debian) 或 `sudo yum install ffmpeg` (CentOS)
- **macOS**：`brew install ffmpeg`

#### 4. 获取网易云 Cookie
1. 打开 [网易云音乐网页版](https://music.163.com)
2. 登录你的账号
3. 按 F12 打开开发者工具，切换到 **Application** 或 **存储** 标签
4. 在 Cookies 中找到 `MUSIC_U` 字段，复制其值

#### 5. 配置项目
```bash
# 复制配置模板
copy config.template.json config.json  # Windows
cp config.template.json config.json    # Linux/macOS
```

编辑 `config.json`，填入你的 Cookie：
```json
{
  "netease_cookie": "这里粘贴你的 MUSIC_U 值",
  "netease_api_base": "http://localhost:3000",
  "api_port": 8003,
  // ... 其他配置保持默认
}
```

#### 6. 首次测试运行
```bash
# 测试模式（生成3首歌曲，验证环境配置）
python main.py --test
```

如果一切正常，你将在 `output/YYYYMMDD/` 目录下看到生成的视频文件。

### 🎮 启动方式选择

#### 方式一：Windows 一键启动（推荐）
直接双击 `start.bat` 文件，会自动：
1. 检查并激活虚拟环境
2. 安装缺失依赖
3. 释放被占用的端口
4. 启动 Web GUI 界面
5. 自动打开浏览器访问 http://127.0.0.1:8003

#### 方式二：命令行模式
```bash
# 生成指定数量的歌曲
python main.py --count 5      # 生成5首
python main.py --count 10     # 生成10首

# 演示模式（使用热门歌曲而非每日推荐）
python main.py --demo

# 指定输出目录
python main.py --count 5 --output ./my_videos
```

#### 方式三：API 服务模式
```bash
# 启动 RESTful API 服务
python api_service.py

# 在另一个终端调用 API
curl -X POST http://localhost:8003/api/run \
  -H "Content-Type: application/json" \
  -d '{"count": 5}'
```

## 🎮 详细使用指南

### GUI 模式（图形界面，推荐）

#### Windows 用户
1. **直接运行**：双击项目根目录的 `start.bat` 文件
2. **等待启动**：脚本会自动处理环境检查、依赖安装、端口释放
3. **访问界面**：浏览器会自动打开 http://127.0.0.1:8003
4. **使用界面**：
   - 在 "歌曲数量" 输入框中输入要生成的歌曲数量（1-50）
   - 点击 "开始生成" 按钮
   - 实时查看生成进度和日志

#### 手动启动 GUI
```bash
# 如果 start.bat 无法运行，可手动启动
python gui_client.py
# 然后手动访问 http://127.0.0.1:8003
```

### CLI 模式（命令行，适合批量任务）

#### 基本命令
```bash
# 生成指定数量的每日推荐歌曲
python main.py --count 5      # 生成5首歌曲
python main.py --count 10     # 生成10首歌曲
python main.py --count 20     # 生成20首歌曲

# 测试模式（快速验证，只生成3首）
python main.py --test

# 演示模式（使用热门歌曲而非个人推荐）
python main.py --demo
```

#### 高级选项
```bash
# 指定输出目录
python main.py --count 10 --output ./custom_output

# 生成后自动清理旧文件
python main.py --count 5 --cleanup

# 跳过缓存，强制重新下载所有资源
python main.py --count 5 --no-cache
```

#### 查看帮助
```bash
python main.py --help
```

### API 模式（适合集成到其他系统）

#### 启动 API 服务
```bash
# 在终端1启动服务
python api_service.py
# 服务将在 http://localhost:8003 运行
```

#### API 接口使用

**1. 启动生成任务**
```bash
curl -X POST http://localhost:8003/api/run \
  -H "Content-Type: application/json" \
  -d '{"count": 5}'
```

**2. 查看任务状态**
```bash
curl http://localhost:8003/api/status
```

**3. 获取生成的视频列表**
```bash
curl http://localhost:8003/api/videos
```

**4. 清理旧文件**
```bash
curl -X POST http://localhost:8003/api/cleanup
```

### 📊 工作流程说明

#### 完整生成流程
```
1. 获取歌曲列表 → 2. 下载音频 → 3. 获取封面 → 4. 生成背景 → 5. 获取歌词
   ↓
6. 生成字幕文件 → 7. 合成单个视频 → 8. 拼接完整视频 → 9. 生成歌单文档
```

#### 时间预估
- **单首歌曲**：约 2-5 分钟（取决于网络和硬件）
- **10首歌曲**：约 20-40 分钟
- **缓存命中时**：速度提升 50-80%

#### 输出文件说明
每次运行会在 `output/YYYYMMDD/` 目录下生成：
```
daily_music_YYYYMMDD.mp4    # 最终合成视频（完整版）
song_list.txt              # 本次生成的歌单列表
clips/                     # 单个歌曲的视频片段
audio/                     # 下载的音频文件（.mp3）
images/                    # 生成的视觉资源（背景+封面）
lyrics/                    # 歌词文件（.lrc 和 .ass 格式）
```

### 🔄 日常使用建议

#### 首次使用
1. 运行 `python main.py --test` 验证环境
2. 检查 `output/` 目录下的生成结果
3. 确认视频质量符合预期

#### 定期生成
```bash
# 每天生成10首推荐歌曲
python main.py --count 10

# 每周清理一次旧文件
python main.py --cleanup
```

#### 批量处理
```bash
# 生成多个批次的视频
for i in {1..5}; do
  python main.py --count 10 --output ./batch_$i
done
```

## 📁 项目结构
```
music_video_pipeline/
├── api_service.py          # FastAPI 后端服务
├── bilibili_auth.py        # B站认证模块
├── bilibili_uploader.py    # 视频上传器
├── cleanup_manager.py      # 资源清理管理器
├── config.template.json    # 配置模板
├── force_kill.bat          # 进程清理脚本
├── gui_client.py           # Web GUI 客户端
├── main.py                 # 主流水线程序
├── mcp_server.py           # MCP 协议服务器
├── netease_api.py          # 网易云 API 封装
├── requirements.txt        # Python 依赖
├── start.bat               # Windows 启动脚本
├── upload_formats.json     # B站上传格式配置
├── video_maker.py          # 视频合成引擎
├── static/                 # Web 静态资源
└── README.md               # 项目说明
```

## ⚙️ 配置说明

### 主要配置项
```json
{
  "netease_cookie": "YOUR_COOKIE_HERE",
  "netease_api_base": "http://localhost:3000",
  "api_port": 8003,
  "output_dir": "./output",
  "video_width": 1920,
  "video_height": 1080,
  "video_fps": 24,
  "bilibili_tid": 138,
  "bilibili_tags": ["音乐", "网易云音乐", "动态歌词"],
  "cleanup": {
    "max_age_days": 7,
    "max_total_size_gb": 10,
    "cleanup_on_start": true
  }
}
```

### 输出目录结构
```
output/
├── YYYYMMDD/              # 按日期组织的运行目录
│   ├── audio/            # 下载的音频文件
│   ├── images/           # 生成的视觉资源
│   ├── lyrics/           # 歌词文件（LRC/ASS）
│   ├── clips/            # 单个歌曲视频片段
│   ├── song_list.txt     # 本次运行的歌单
│   └── daily_music_YYYYMMDD.mp4  # 最终合成视频
```

## 🔧 高级功能

### Bilibili 自动上传
1. 配置 B站 Cookie 到 `cookies.json`
2. 运行上传脚本：
   ```bash
   python bilibili_uploader.py --video output/20250101/daily_music_20250101.mp4
   ```

### 自定义视觉样式
修改 `config.json` 中的 `visual` 部分：
```json
"visual": {
  "blur_radius": 40,
  "blend_alpha": 0.5,
  "title_font_size": 70,
  "artist_font_size": 35,
  "text_x": 1050
}
```

### 资源清理策略
项目内置智能清理系统：
- **按时间清理**：默认保留最近7天的文件
- **按大小清理**：总占用超过10GB时自动清理最旧文件
- **启动时清理**：每次启动自动执行清理

## 🐛 故障排除

### 常见问题
1. **FFmpeg 未找到**
   - 下载 FFmpeg 并添加到系统 PATH
   - 或修改 `video_maker.py` 中的 ffmpeg 路径

2. **Cookie 无效**
   - 重新登录网易云音乐获取最新 Cookie
   - 确保 MUSIC_U 值完整且未过期

3. **端口被占用**
   - 修改 `config.json` 中的 `api_port`
   - 或运行 `force_kill.bat` 清理旧进程

4. **磁盘空间不足**
   - 项目会自动清理旧文件
   - 可调整 `cleanup.max_total_size_gb` 配置

### 日志查看
- `pipeline.log` - 主流水线日志
- `upload.log` - B站上传日志
- `download.log` - 下载任务日志

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

### 开发环境设置
```bash
# 创建虚拟环境
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/macOS

# 安装开发依赖
pip install -r requirements.txt
```

### 代码规范
- 遵循 PEP 8 编码规范
- 添加适当的类型注解
- 编写单元测试（如适用）

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 🙏 致谢

- [网易云音乐 API](https://github.com/Binaryify/NeteaseCloudMusicApi)
- [biliup](https://github.com/ForgQi/biliup-rs) - B站上传工具
- [FFmpeg](https://ffmpeg.org/) - 多媒体处理框架

---

**提示**：本项目仅供学习和研究使用，请遵守相关平台的服务条款，尊重音乐版权。

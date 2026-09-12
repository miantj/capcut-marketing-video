# 内部视频工作台

Windows 局域网应用。上传视频、背景音乐和最终文案，串行制作可编辑剪映草稿、近似预览及完整素材包。数据位于 `data/`，浏览器不保存素材，所有团队成员共享任务列表。

## 本机启动

本机已有 Python、FastAPI、Uvicorn、capcut-cli；程序也可复用相邻 `.audio-tools` 中的 FFmpeg。

```powershell
cd D:\yisho\video-workbench
.\start.ps1
```

浏览器打开 http://localhost:8765 。同事使用工作机的公司局域网 IPv4 地址和端口 8765。保持电脑开机；使用单个服务进程，不能设置多个 Uvicorn workers。首次 Windows 防火墙提示时只允许公司使用的网络配置；如果同事无法连接，由管理员按公司规则开放 TCP 8765。不要把此试用服务直接暴露到公网。

其他工作机需要 Python 3.12 或更新版本、Node.js、剪映桌面版，以及完整的 `capcut-marketing-video` skill（可通过 `VIDEO_SKILL_DIR` 指定）。安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm install -g capcut-cli
```

可复制 `.env.example` 为 `.env`，设置团队访问码和工具路径。访问码为内部共享入口，不是个人权限隔离。默认不开启远程 AI 调用；服务器日志不返回 API 密钥。管理员负责备份 `data/queue.sqlite3` 和 `data/jobs/`。点击删除任务并确认后，会永久清理该任务的上传副本、预览、草稿包及记录；其他版本及用户电脑上的原始素材不受影响。上传中请先取消，制作中需等待完成；清理失败可重试删除。

## 已实现

- 分块上传，单文件 1GB，每任务 4GB、20 段视频和 1 首音乐；服务器生成文件路径，用户文件名不进入命令。
- SQLite 持久化队列，原子领取任务，单个制作线程；重启把中断任务标为需处理，不伪造完成。
- 文案保留、逐屏字幕、3 个固定风格、横竖屏、原视频静音、音乐循环及首尾淡入淡出。
- 通过本机 capcut-cli compile 生成真实的独立视频、音乐、文本轨；在隔离工作目录登记素材，不修改用户正在编辑的草稿库。
- 复用 skill 的字幕样式处理及校验，写入悠然体、关键词高亮、气泡和各 0.5 秒的进出场动画；从实际草稿生成 FFmpeg + ASS 近似预览；检查预览时长、音轨、完整解码；打包前校验素材自包含和 ZIP 完整性。
- 草稿包内含 Windows PowerShell 导入脚本：校验 SHA256、路径重定位、重复导入保护、索引备份及原子替换。运行前需退出剪映。目标电脑的具体剪映版本仍需打开验收。
- 查看预览、下载草稿、新版本修改；旧文件与旧任务保留。顺序模式不解释自由文字备注。

## 能力边界

默认是**自动模板剪辑（按上传顺序）**，并非已经启用 AI 语义选片。字幕时间直接调用已安装 skill 的 durations_from_chars，当前默认每个非空白字符 0.22 秒，不额外增加每屏最短停留或固定停顿，无配音对齐。三种模板在位置、气泡数量与颜色、入场动画上不同，保留原文，显示时隐藏逗号和句号，按实际字体宽度换行。草稿使用本机真实字体及动画资源；预览读取相同文案、字体、关键词和气泡，动画作近似呈现，未通过原生视听验收。目标电脑需在剪映中预先下载悠然体、放大、波浪弹入和波浪弹出，导入脚本会检查资源是否存在。

安装的 `capcut-marketing-video` 是交互式 AI 视频制作规程，其中选片审阅、原生朗读与原生导出无法只靠运行脚本完成。此应用复用它所使用的 capcut-cli 编译及代理预览能力；没有绕过其验收器把本应用结果宣称为 skill 全链验收通过。

**自动原生配音、原生导出、旧字幕消除尚未实现**，界面明确显示无配音。预览为 approximate，最终视频请在剪映检查并导出。草稿文件和路径校验不等于原生编辑器兼容验收，尤其不保证手机端兼容。

## 可选 AI 选片

管理员配置 `VIDEO_ENABLE_AI=1`、`VIDEO_AI_API_KEY`、`VIDEO_AI_MODEL` 后重启。用户必须另行勾选关键帧分析授权。仅在选用 AI 模式时发送每段视频的 3 张缩略关键帧、文案及备注到固定 OpenAI Responses API；不发送整段视频或音乐，不读取 Codex 登录凭证。

返回结果只允许素材 ID、时间和理由，经过源区间、连续覆盖与时长校验后才能进入编译。失败时显示需处理，不静默切换为顺序模式。三帧抽样不能保证整段画面无旧字幕。当前环境无此服务配置，真实远程选片调用需要配置后验收。

实现依据：[图像输入](https://developers.openai.com/api/docs/guides/images-vision)、[结构化输出](https://developers.openai.com/api/docs/guides/structured-outputs)。

## 验证

```powershell
python -m unittest discover -s tests -v
```

端到端和浏览器验收脚本放在 `tests/`。测试使用独立临时目录，不往用户剪映草稿库安装测试项目。运行 `tests/smoke.py` 会调用本机 FFmpeg / capcut-cli 制作一个真实短草稿并验证产物，耗时高于单元测试。

## 结构

- `dist/`：无需构建的中文工作台。
- `workbench/app.py`：上传、任务、版本和产物 API。
- `workbench/store.py`：持久化队列和事件。
- `workbench/worker.py`：单工位制作流水线。
- `workbench/ai.py`：可选 AI 关键帧选片。
- `workbench/packaging.py`、`scripts/Import-Draft.ps1`：可迁移草稿包与导入。
- `workbench/compat.py`：修复缺少 ffprobe 时的素材完整时长记录，提供中文预览适配。
- `data/jobs/<id>/commands.jsonl`：本机处理日志；`error.log`：失败诊断。仅管理员本机读取。

操作步骤见 [使用说明](使用说明.md)。尚未验证：目标电脑原生剪映打开/导出、远程 AI 服务实调。

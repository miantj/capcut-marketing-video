# 脚本执行链（Python 3.11+，不安装新依赖）

入口均为 `scripts/workflow.py`。所有项目文件写在工作区；先 `start` 保存任务原话，后续命令按返回的 `run_dir` 执行。`status`只是历史记录；最终必须 `verify`重读实际文件，不能靠手改delivery.json。

```bash
python3 <skill>/scripts/workflow.py start <project> --mode create --delivery draft+native --request '实际用户需求'
python3 <skill>/scripts/workflow.py bootstrap --out <project>/native-resources.json
python3 <skill>/scripts/inspect_inputs.py --media-dir <素材目录>
python3 <skill>/scripts/workflow.py narrate <project>/storyboard.json
# 在剪映按 checklist 逐句生成 textReading → narration/{script_id}.wav
python3 <skill>/scripts/workflow.py retime <project>/storyboard.json --from-dir <project>/narration --in-place
python3 <skill>/scripts/workflow.py prepare <project>/storyboard.json --out <project>/builds
python3 <skill>/scripts/workflow.py build <project>/storyboard.json --out <project>/builds
python3 <skill>/scripts/workflow.py finish <run_dir> --resources <project>/native-resources.json
python3 <skill>/scripts/workflow.py install <run_dir> --store <实际剪映草稿库>
python3 <skill>/scripts/workflow.py verify <run_dir> --evidence <project>/evidence.json
```

`bootstrap` 从本机 `capcut enums --jianying` 与 `Cache/effect/{resource_id}/{md5}` 生成 finish 资源；缺缓存会 `ok:false` 并列出 unresolved。`narrate`/`retime` 只处理清单与时轴，不调用外部 TTS。`build`/`finish` 会尝试 `capcut render` 代理预检（`mode=approximate`），失败不阻断结构交付，但不能当作原生预览通过。可用 `workflow.py preview <run_dir>` 手动重跑代理预览。

原生试听/预览和导出发生在install之后、verify之前，不存在伪装成已支持的自动export命令。纯工程任务不要求MP4；明确video-only只是不安装，内部仍用capcut构建、完成样式后生成视频。脚本失败会退出非零，输出具体错误或next_step。

## 分镜最低要求

基础格式见[production.md](production.md)，本版构建额外要求：

- `task.json`的create模式及delivery与storyboard一致。`narration.mode`不能省略；有口播要aligned、真实音频、cue_ids和对齐证据。none仅在用户选择无口播时使用，不能为绕过配音阶段填写。
- 每屏`visual.font={path,id}`必须存在，`animation`含intro、outro、purpose、intro_seconds、outro_seconds。默认各0.5秒，另留至少0.3秒稳定阅读。intro/outro 须在 design-recipes 允许名单；表外仅 `style_exceptions.animation_allowlist_reason`（用户原话）可通过。改默认 0.5s 时长仍用 `animation_reason`。
- 少量字幕有`keywords`/`bubble`。用户明确简化可在`style_exceptions.keywords_reason` / `bubble_reason` / `animation_reason`保留原话。
- BGM 门禁见 [production.md](production.md)（单床、music only）；校验器拒绝多 `asset_id` 混叠与把 speech/ambient 当 BGM。

```json
{
  "cue_ids": ["benefit"], "text": "补货不用跑市场", "start": 10, "end": 13,
  "recipe": "benefit-tag",
  "visual": {"fontSize": 20, "color": "#FFFFFF", "x": 0, "y": -0.5,
    "font": {"path": "/真实/悠然体.ttf", "id": "已核实的原生字体ID"}},
  "animation": {"intro": "放大", "outro": "缩小", "purpose": "benefit",
    "intro_seconds": 0.5, "outro_seconds": 0.5},
  "keywords": ["不用跑市场"],
  "bubble": {"text": "手机补货", "x": -0.45, "y": 0.5, "width": 0.4, "height": 0.12, "color": "#FFE263"}
}
```

bubble的位置及底图宽高使用剪映原生字段单位，不是像素。通过原生样片校准；脚本只验证数据和实际字段，不能证明气泡一定装得下文字。复杂字效用已核实的模板/CLI另行处理，不能把基础着色说成某个原生花字模板。

## 各命令实际做什么

- **start**：保存用户原话、模式、交付与顺序步骤。它不执行配音，也不表示步骤已完成。
- **prepare**：检查分镜；派生compile、文稿和native-finishing待办。assets未审、来源时间错误等仍报错。只要文稿时使用script分支，不为文稿捏造素材。
- **build**：检查明确配音状态、任务交付、字体和样式计划，再实际调用`capcut compile`。留下argv、stdout、stderr、returncode、refs、路径和哈希。没有这些证据，后续命令拒绝把doctor、register或MP4当构建完成。
- **finish**：从未变化的编译源复制独立finished工程；设置顶层/内联字体、关键词着色/加粗、原生进出场、可编辑气泡及底板，然后读回校验。保留原编译源用于追溯，不标记原生预览通过。
- **install**：样式检查通过后复制到真实草稿库的项目名目录，素材以内容哈希收集进assets；保存索引备份，检查register计划目标后执行并回读索引/素材。用户已有的目的目录、源工程变化、索引并发变化、素材路径不明时停止，不覆盖用户修改；本次运行留下的安装标记表示上次注册未完成，允许清理该标记目录后重试。
- **verify**：重新检查编译来源、真实工程中的正文/字体/字号/动画/关键词/气泡/配音、首页注册、视觉和听音证据，视频则额外检查来源、时长、音轨及全片解码。报告第一项缺口，不把人工声明的passed当机器验收。

native-resources.json形如`{"放大": <从本机已保存原生草稿查到的完整动画资源对象>, ...}`，需包含当前字体/动画实际资源路径；不要猜ID或把网络目录当已下载资源。finish检查所用动画目录存在。默认资源定位线索见[design-recipes.md](design-recipes.md)。

## 真实审阅证据

由实际看过/听过的AI填写观察，不得捏造。verify检查文件存在、哈希关联及必要的观察节点，不能代替模型看图或听音，也不能判断观察是否诚实。

```json
{
  "draft_sha256": "当前已安装draft_content.json的SHA256",
  "visual": {"reviewed": true, "surface": "native",
    "moments": ["intro", "hold", "outro", "longest", "cta"],
    "files": ["/真实/原生预览录屏.mp4"],
    "findings": "实际检查的时间点、文字尺寸、动画和安全区观察"},
  "audio": {"reviewed": true, "files": ["/真实/试听混音.wav"],
    "findings": "专名读音、漏读/重读、首尾、原声冲突和配乐音量观察"},
  "video": {"path": "/真实/输出.mp4", "mode": "native",
    "draft_sha256": "导出来源同一个工程SHA256"}
}
```

近似视频的video.mode填approximate，附authorization（已有授权原话）和differences。近似预览不等于原生视觉检查通过；原生不可访问时如实交付“工程已安装＋近似预览，原生预览待验收”，verify保持相关项未通过，不继续询问已授权的替代选择。

## 失败与续做

相同输入build复用编译结果，草稿内容变化则保护并停止重编。finish目录存在时禁止覆盖；安装仅在目录带有本次运行的失败标记时清理并重试；安装后必须核对三份时间轴镜像ID/时长一致并确认首页索引存在同ID条目，否则保留现场，读回内容和日志，不通过删除或修改哈希绕过保护。已安装后用户修改的工程进入edit分支，不能修改旧哈希来冒充本次自动制作已验收。

本版create链自动化完整的结构步骤；edit/export使用入口中的快照与CLI流程，不支持伪造compile日志“接入”。只要一个检查器缺少了新能力，就先补明确支持/真实验证，再使用它，而不是隐藏不支持项。

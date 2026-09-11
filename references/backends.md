# 工具与适配策略

## capcut-cli：默认草稿工具

检查本机版本、doctor、describe 或本地文档，复用已有依赖。不盲加 --dry-run；只在具体命令支持时使用。FFmpeg/ffprobe 分析与预处理，Whisper 按需转写，剪映原生预览与导出。

下列语法在本机 0.22.0 文档核对；升级后需复核。占位参数须替换。

```bash
capcut compile <compile.json> --out <新草稿目录>
capcut lint <草稿>
capcut diagnose <草稿>
capcut register <草稿目录> --materials --apply
capcut timeline <草稿>
capcut diff <草稿A> <草稿B>
capcut keyframe <草稿> <片段ID> <属性> <秒> <数值>
capcut text-anim <草稿> <片段ID> --intro <已验证slug>
capcut save-template <草稿> <片段ID> <模板名> --out <模板.json>
capcut apply-template <草稿> <模板.json> <开始秒> <持续秒> <新文字>
capcut restore <草稿> --list
capcut restore <草稿> --step <步数>
```

restore 只在确实需要恢复时执行，不沿用网上 restore --backup 示例。查看实际 JSON 返回与副作用，不能只依靠退出码。

注册不是单纯校验：先确认目标草稿和真实存储目录，查看不带 --apply 的计划。按需将素材放入草稿自包含目录并重链接，再注册目标项目。compile 成功后 lint 仍可能报告 media-unregistered；这表示还没有完整注册素材，不能因此声称剪映打开已验证。测试草稿无需加入用户草稿库。本机正式交付需安装到确认的真实草稿库，执行 [draft-installation.md](draft-installation.md) 的索引核对；`register` 默认解析到项目父目录时可能只写工作目录索引，不能据其ok判断剪映首页可见。

`lint --fix`会自动改字幕时长/分段等内容，不作为打包素材的通用命令。长时间阶段标题可提高`--max-cue-secs`后只读检查；素材迁移用经本机文档核实的relink/stage命令或在独立安装副本定向改路径。

编译映射：

- tracks 分视频、目标配音 audio、BGM audio、text 与装饰；每段唯一 ref。
- start/duration/sourceStart/speed/volume 从计划映射；冲突原声静音落实为视频片段 volume=0，不只叠加新配音。
- 字幕 text 为真实换行；fontSize/color/x/y 来自校准，text-ranges 按 UTF-16 索引，注意 emoji 不是单码元。
- 动画用基础 keyframe 或已验证原生 text-anim；确认片段相对时间及 clip.scale 组合语义。
- compile 返回的 refs 用于后续命令，不硬编码旧 ID。先在新目录建立草稿，再按任务需要注册到剪映。

## JyWrapper：按需可选工具

仅对具体缺口评估，如配音字幕一体化、语义素材拼接、网页动效录制。先确认是否安装、实际 API 和平台支持；不用猜测的参数调用。两个后端不同时写同一个 live 草稿，采用独立小样或单一后端组装。

上游 README 声明 macOS 实验性、自动导出不支持 Mac，推荐 Windows＋剪映 5.9 或更低；其 SKILL 描述较乐观，不能据此宣称全平台可用。不要自动降级剪映、用 overwrite=True 修复用户最新项目、下载云音乐或装全部依赖。接入前在隔离小样中验证可读草稿、路径、对齐与可编辑性。

## 外部渲染

FFmpeg 或网页动效用于必要预处理、代理检查和已同意的近似输出。先列出当前草稿特性与支持范围；新渲染器不会自动获得剪映特效、字体许可和原生保真度。网页动效可导入作装饰，但烧录文字不能称为原生可编辑字幕。

## 来源与取舍

- [claude-capcut-skill](https://github.com/mane23-ai/claude-capcut-skill)：借鉴意图分流、局部关键帧检查、模板复用及修改对比；不继承每次操作确认、硬编码 Claude 路径和转交未安装 skill 的流程。
- [jianying-editor-skill](https://github.com/luoluoluo22/jianying-editor-skill)：借鉴模块化工具、配音字幕对齐及独立业务脚本；保留平台边界，避免自动修复覆盖最新编辑。
- 本 skill 的流程和新增辅助代码独立编写，未打包/安装两个上游仓库；将来接入代码需核对版本、许可及依赖。

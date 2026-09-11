# 新建营销视频

## 文案 → 真人口播文稿 → 实际定时

新制作先完成文案分析和口播文稿，再按实际配音锁定剪辑时间；配音生成期间可盘点素材。仅要文稿时到此交付，不要求先凑齐素材。

1. 将输入原样保存为 storyboard.source_text，识别目标人群、主张、钩子、痛点、方案、证据/利益与 CTA。拆成唯一 ID 的 script，不为了套结构补造事实。
2. 用户要求口语化时，可在授权范围内调整表达、断句和标点；品牌、数字、优惠、条件、专名及核心承诺保持准确。copy_notes 记录实质改写与疑点，区分已授权改写、待核对候选及已确认修订。未解决的敏感改字保留原词，不把候选直接写进最终配音。
3. 按能自然说完的意群分句。script.text 只放要说的文字；purpose、emphasis（重读词列表）、pause_after（句后停顿秒数）分开记录。短停顿可从约 0.2–0.4 秒试读，转折和段落停顿稍长；这是试音起点，不是每句强制值。不要拆散品牌、商品名和数字单位。
4. 为每句写预计 start/end，表示说话区间、不含 pause_after，最后一句也要有结束时间。用 `(0:00.000–0:02.600) 文案〔句后停0.3秒；重读：关键词〕` 展示预计文稿，标明尚未实测。时间戳和表演提示不能送入 TTS 朗读。
5. 新制作显式声明 narration.mode：native_tts（默认无现成配音）、provided（用户音频）、source（保留与文案一致的素材口播）或 none（用户选择纯文字+BGM）。有口播时先写 timing=estimated；按 SKILL.md 原生朗读偏好生成/取得音频，再测量时长、逐句试听并对齐。ASR 可辅助找时间，但不能用识别结果擅改文案。检查专名读音、数字、漏读、重复、停顿和句尾。
6. 把真实时间写回 script，更新 narration.timing=aligned 和 evidence（音频、试听/对齐记录及关键时间点）。修改声音或文稿后重新对齐。文件存在或声明 aligned 不代表内容和语感通过。provided/native_tts 的 narration 音频通过 cue_ids 绑定文稿；source 模式在保留口播的 shots 上绑定 cue_ids。

有口播时，预计时轴可 prepare，build 要求 aligned。若需剪映先生成朗读，可用独立朗读工作草稿取得音频，再回填主分镜。无现成配音且原生朗读不可用时，继续完成预计文稿、素材选择和准备文件，记录配音待完成；不要删除 narration 绕过检查，也不要拿无关原声或纯音乐版冒充口播完成。

## 素材检查

从用户提供或已明确指定的目录查找；缺少路径时先完成文稿，再询问素材位置。先盘点，再对候选抽帧，避免对大素材库反复抽图：

```bash
python3 <skill>/scripts/inspect_inputs.py --media-dir <素材目录> > <project>/asset-index.json
python3 <skill>/scripts/inspect_inputs.py --media <候选视频> --frames-out <project>/inspection > <project>/candidate-inspection.json
```

扫描递归识别常见视频、音频和图片并去重；可选抽帧输出开头、中段、近结尾三张图及源时间，图片写到素材库之外的项目目录。代理实际查看图片/片段后补充标签、可用源区间、构图和证据。脚本不推断地点、人物、商品和卖点，不能仅凭文件名匹配。

按“语义准确 → 原声/旧字可处理 → 商品/人物清楚 → 竖屏构图及长度适合 → 不过度重复”选镜头。shots 记录 cue_ids、源区间和 match_reason；泛化市场画面不能当作具体地点或 APP 功能的证明。缺少指定画面时记录缺口，在授权范围内用相关实拍承接口播；没有合适替代时再询问，不无限循环无关镜头。

运行 inspect_inputs.py，检查尺寸、旋转、帧率、时长、音轨、字幕流；实际抽看开头、中段、结尾及镜头/文字变化处。试听视频原声和独立音频，必要时转写。明确每份素材角色：主画面、B-roll、目标配音、BGM、音效或参考；不要因为另一视频文案相似而换掉用户指定素材。

| 情况 | 处理 |
| --- | --- |
| 原人声与目标文案冲突 | 使用镜头时静音原人声，目标配音独立分轨 |
| 原声仅为合适环境声 | 可降低音量保留，实际试听混合结果 |
| 原视频已有音乐，又提供新 BGM | 选一条主要音乐，避免未经设计的双音乐 |
| 用户配音与文案不一致 | 列出具体语句差异，明确以谁为准，不擅改字幕 |
| 冲突软字幕 | 派生处理/导出时排除冲突字幕流 |
| 烧录字幕、旧 CTA 或价格 | 优先干净镜头；评估裁切/重构图/覆盖，检查商品细节；不可合理解决时说明选项 |

禁止把新文案直接叠在旧文案旁；字幕轨删除不能消除画面字。区分字幕、商标和水印。MP4 中的字无法还原为原始可编辑图层。

## 声画节奏

保存原文，拆成唯一 ID 的语义段。时长以实际目标口播和阅读速度决定，不按固定每字时长宣称对齐。文案长时延长画面或增加相关镜头；没有配音时按需求做纯文字+BGM 或 TTS，不擅自沿用冲突原声。敏感素材外传和付费服务在既有授权内执行。

可按钩子、痛点、方案、证据/利益、CTA 组织，每屏一个主信息；未提供的优惠事实不得补造。优先停顿/句尾切镜。BGM 在口播下压低，检查双人声、削波、重复音乐、跳音和句尾截断。

口播句、字幕屏和镜头分别排期，通过 cue_ids 关联。一屏可合并相邻短句，一段口播可跨镜头，一个镜头也可覆盖多句；不强制每秒切镜。正文字幕按时间排序后不重叠，每个文稿 ID 恰好出现一次且顺序一致；气泡等装饰走独立图层。

默认入场/出场各0.5秒，校验器要求另有至少0.3秒稳定阅读停留，只是防止动画占满的下限，不代表长句可读。优先合屏或延长排期，不静默缩短指定动画。字幕覆盖相应实际说话区间，CTA留足停留。

BGM 优先选用户提供或素材库中可用的音乐，按文稿情绪、节奏试听；有口播时避免歌词抢人声。独立分轨、显式 volume，先试听确定固定音量，必要时再做关键帧压低。填写 fade_in/fade_out 秒数，音乐不足时明确重复源区间并检查接缝，不用变速强凑长度。缺少可用音乐时记录待补。编译会实际应用淡入淡出；动态压低等复杂混音仍需后处理。audio_mix 通过须有试听证据，检查首尾突兀、双音乐、静音、削波与口播遮盖。

## 分镜数据源

storyboard.json 是本 skill 的制作计划，不是 capcut-cli compile 格式。原文或经用户确认的修订拆成 script；不能为了通过校验删改原文。

```json
{
  "version": 1,
  "delivery": "draft",
  "duration": 6,
  "canvas": {"width": 720, "height": 1280, "fps": 30},
  "source_text": "夏装补货不用跑市场，打开一手APP",
  "narration": {"mode": "native_tts", "timing": "estimated"},
  "script": [
    {"id": "hook", "text": "夏装补货", "start": 0, "end": 1, "pause_after": 0.2, "emphasis": ["补货"]},
    {"id": "benefit", "text": "不用跑市场，", "start": 1.2, "end": 2.8, "pause_after": 0.2},
    {"id": "cta", "text": "打开一手APP", "start": 3, "end": 5.6, "pause_after": 0.4}],
  "assets": [{"id": "shop", "path": "/实际素材/市场.mp4", "kind": "video", "duration": 12,
    "original_audio": "speech", "audio_action": "mute", "burned_text": "none", "text_action": "none",
    "inspection": "已试听并检查选用画面，没有烧录文字"}],
  "shots": [{"asset_id": "shop", "start": 0, "end": 6, "source_in": 2, "source_out": 8, "speed": 1,
    "cue_ids": ["hook", "benefit", "cta"], "match_reason": "市场实拍承接补货口播，不作为APP功能证明"}],
  "captions": [
    {"cue_ids": ["hook", "benefit"], "start": 0, "end": 3, "text": "夏装补货\n不用跑市场，", "recipe": "keyword-reveal",
      "visual": {"fontSize": 20, "color": "#FFFFFF", "x": 0, "y": -0.5}},
    {"cue_ids": ["cta"], "start": 3, "end": 6, "text": "打开一手APP", "recipe": "cta-lockup",
      "visual": {"fontSize": 20, "color": "#FFFFFF", "x": 0, "y": -0.5}}],
  "audio": []
}
```

字段约定：

- 秒制 start/end，源区间 source_in/source_out，speed 为播放速度；源时长/speed 匹配目标时长。
- assets.kind 为 video/audio/image；图片可省略 duration。path 必须指向真实素材；转写/抽帧证据写在 inspection。
- video.original_audio 为 none/speech/music/ambient，audio_action 为 mute/keep/duck；video/image.burned_text 为 none/present，text_action 为 none/avoid/crop/cover/keep-approved。原人声保留还需 audio_note 说明其与文案是否一致。
- 存在画面字时，treatment_note 记录实际避让/处理，不能仅填枚举就认定已消除冲突。未知状态填 unknown，检查完成前验证器会报告未解决。
- shots 表示主画面，要求连续覆盖总时长；图片只填目标时间。装饰/叠加轨在 compile 中另行实现。
- script 的每个 ID 在 captions 中恰好一次，可换行/空格调整，不能换字。新格式 cue_ids 合并相邻口播句；旧 cue_id 仍兼容，同一字幕不能两者并用。若一口播句需要分屏，再将其拆成更细的 script ID。
- audio 每段包含 asset_id/start/end/source_in/source_out/speed/role/volume，role 为 narration/bgm/sfx，可加 fade_in/fade_out。aligned 的 provided/native_tts 配音须用 cue_ids 将每个文稿 ID 绑定一次，并覆盖说话区间；停顿可无声，不要求口播填满全片。有配音轨不证明逐句同步。
- 同一源文件不同区间需要不同原声/旧字处理时，可用不同 asset ID 复用同一路径。每个选用区间分别记录实际检查证据。

示例是无音频的预计分镜，仅可 prepare。取得配音后，增加真实音频素材和 narration 片段，回填实测时间及 aligned 证据再 build。新制作必填 narration，旧分镜缺失该字段仅兼容读取，不代表配音已验证。source_text 与 copy_notes 保留原文和实质改写记录；不以删改原文绕过字幕覆盖检查。

运行 validate_storyboard.py。它检查数据和明显冲突，不评判语义、美观或口播内容。通过后按 design-recipes.md 校准，将基础文字参数写回分镜，再按 [workflow-p0.md](workflow-p0.md) 自动派生 compile.json；原生样式后处理、安装及视听验收仍需完成。

prepare 同源派生 voice-script.txt（起止时间、停顿、重音）和 tts.txt（纯朗读文字）；只改 storyboard 后重新生成，不单独维护这两份文稿。仅要文稿时可直接从 script 交付同样格式，无需运行 build。

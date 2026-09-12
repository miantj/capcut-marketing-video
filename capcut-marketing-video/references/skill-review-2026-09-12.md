# Skill 改动复核（2026-09-12）

## 副本问题（已处理）
- `.codex/skills/.../capcut-marketing-video` 曾落后：`workflow` 无 narrate/bootstrap；`delivery_steps` 无换行/去标点。
- 已将工作树 `D:\yisho\capcut-marketing-video\scripts` 关键脚本同步到 skill 目录。

## 本次业务改动
1. 字幕强制换行：`force_apply_line_max_width` + 左右 20px
2. 画面去逗号/句号：`display_caption_text`（口播文案仍保留）
3. 无音频估时长默认：`0.25 → 0.22` 秒/字

## Bug 修复
- 关键词校验在 `find==-1` 时先 continue，避免错误切片
- `canvas_w/line_max` 提到循环外；空 styles / 去标点后空文本有兜底
- 去掉 skill 注释里对具体项目路径的耦合

## 测试
- 新增 `test_display_caption_text_strips_punct`
- `install` 相关 2 个用例在剪映进程占用时会失败（环境限制，需 `--force-write` 或关剪映），与本次逻辑无关

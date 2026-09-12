"""Skill-declared design allowlists. Extra names need an explicit user request quote."""

# From references/design-recipes.md「按文意搭配原生文字动画」table only.
# Exact titles; enums may expose「打字机 I」等变体——默认仍只认表内「打字机」，
# 要用变体须 animation_allowlist_reason。
ALLOWED_TEXT_INTROS = frozenset({'波浪弹入', '甩出', '开幕', '打字机', '放大'})
ALLOWED_TEXT_OUTROS = frozenset({'缩小', '羽化向右擦除', '闭幕', '波浪弹出'})

DEFAULT_ANIMATION_NAMES = tuple(sorted(ALLOWED_TEXT_INTROS | ALLOWED_TEXT_OUTROS))

"""Use the installed skill's character estimator instead of a parallel formula."""
import importlib.util
import os
import sys
from functools import lru_cache
from pathlib import Path

from .config import ROOT


def skill_root():
    env = os.environ.get('VIDEO_SKILL_DIR')
    if env:
        return Path(env)
    sibling = ROOT.parent / 'capcut-marketing-video'
    if (sibling / 'scripts').is_dir():
        return sibling
    return Path(os.environ.get('CODEX_HOME', 'D:/OpenAI/CodexHome')) / 'skills/capcut-marketing-video'


def timing_module():
    return skill_module('timeline_ops')


@lru_cache(maxsize=None)
def skill_module(name):
    scripts = skill_root() / 'scripts'
    path = scripts / (name + '.py')
    if not path.is_file():
        raise RuntimeError('未找到 capcut-marketing-video 脚本，请设置 VIDEO_SKILL_DIR。')
    spec = importlib.util.spec_from_file_location('workbench_installed_skill_' + name, path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(scripts))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(scripts))
    return module


def estimate(lines):
    module = timing_module()
    script = [{'id': f'S{i+1:03}', 'text': text} for i, text in enumerate(lines)]
    durations = module.durations_from_chars({'script': script})
    cues, cursor = [], 0.
    for row in script:
        duration = durations[row['id']]
        cues.append({**row, 'start': round(cursor, 6), 'duration': duration})
        cursor += duration
    return cues


def evidence(text):
    module = timing_module()
    return {'timing': 'estimated', 'source': str(Path(module.__file__).resolve()),
            'function': 'durations_from_chars', 'formula': 'non_whitespace_chars * sec_per_char',
            'non_whitespace_chars': module.count_display_chars(text),
            'sec_per_char': module.DEFAULT_SEC_PER_CHAR, 'pause_seconds_added': 0,
            'minimum_screen_seconds_added': 0, 'speech_aligned': False}

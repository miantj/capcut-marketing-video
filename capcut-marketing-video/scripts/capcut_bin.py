#!/usr/bin/env python3
"""Resolve the capcut CLI executable for subprocess (Windows npm shim friendly)."""
from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path


def _local_cli() -> list[Path]:
    here = Path(__file__).resolve()
    skill = Path(os.environ.get('VIDEO_SKILL_DIR', ''))
    return [
        Path(os.environ.get('VIDEO_CAPCUT_JS', '')),
        Path(os.environ.get('APPDATA', '')) / 'npm' / 'capcut.cmd',
        Path(os.environ.get('APPDATA', '')) / 'npm' / 'capcut.CMD',
        Path(os.environ.get('APPDATA', '')) / 'npm' / 'capcut',
        here.parents[1] / 'node_modules/.bin/capcut',
        here.parents[2] / 'video-workbench/node_modules/.bin/capcut',
        (skill.parent / 'video-workbench/node_modules/.bin/capcut') if skill.is_dir() else Path(),
        Path.home() / '.npm-global/bin/capcut',
        Path('/opt/homebrew/bin/capcut'),
    ]


@lru_cache(maxsize=1)
def capcut_cmd() -> str:
    for name in ('capcut', 'capcut.cmd', 'capcut.exe'):
        found = shutil.which(name)
        if found:
            return found
    for candidate in _local_cli():
        if candidate.is_file():
            return str(candidate)
    raise FileNotFoundError('capcut CLI not found on PATH; install with: npm install -g capcut-cli')

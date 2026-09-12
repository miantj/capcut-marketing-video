#!/usr/bin/env python3
"""Resolve the capcut CLI executable for subprocess (Windows npm shim friendly)."""
from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def capcut_cmd() -> str:
    for name in ('capcut', 'capcut.cmd', 'capcut.exe'):
        found = shutil.which(name)
        if found:
            return found
    npm = Path(os.environ.get('APPDATA', '')) / 'npm'
    for name in ('capcut.cmd', 'capcut.CMD', 'capcut'):
        candidate = npm / name
        if candidate.is_file():
            return str(candidate)
    raise FileNotFoundError('capcut CLI not found on PATH; install with: npm install -g capcut-cli')

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def resolve_capcut(env=os.environ):
    override = env.get('VIDEO_CAPCUT_JS')
    if override:
        cli = Path(override)
        return [shutil.which('node') or 'node', str(cli)] if cli.is_file() else []
    for name in ('capcut', 'capcut.cmd'):
        found = shutil.which(name)
        if found:
            return [found]
    node = shutil.which('node') or 'node'
    for cli in (
        ROOT / 'node_modules/capcut-cli/dist/index.js',
        Path(env.get('APPDATA', '')) / 'npm/node_modules/capcut-cli/dist/index.js',
        Path.home() / '.npm-global/lib/node_modules/capcut-cli/dist/index.js',
        Path('/opt/homebrew/lib/node_modules/capcut-cli/dist/index.js'),
        Path('/usr/local/lib/node_modules/capcut-cli/dist/index.js'),
    ):
        if cli.is_file():
            return [node, str(cli)]
    return []


def ffmpeg_has_filter(ffmpeg, name):
    try:
        completed = subprocess.run([ffmpeg, '-hide_banner', '-filters'], capture_output=True,
                                   text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    token = f' {name} '
    return any(token in f' {line} ' for line in completed.stdout.splitlines())


def resolve_ffmpeg():
    candidates = []
    if os.environ.get('VIDEO_FFMPEG'):
        candidates.append(os.environ['VIDEO_FFMPEG'])
    found = shutil.which('ffmpeg')
    if found and found not in candidates:
        candidates.append(found)
    try:
        import imageio_ffmpeg
        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled and bundled not in candidates:
            candidates.append(bundled)
    except ImportError:
        for extra in (ROOT.parent / '.audio-tools/imageio_ffmpeg/binaries').glob('ffmpeg*'):
            candidates.append(str(extra))
            break
    for candidate in candidates:
        if ffmpeg_has_filter(candidate, 'ass'):
            return candidate
    return candidates[0] if candidates else ''


@dataclass
class Settings:
    data: Path
    ffmpeg: str
    capcut: list[str]
    access_code: str
    ai_key: str
    ai_model: str
    ai_enabled: bool
    max_file: int = 1024 ** 3
    max_job: int = 4 * 1024 ** 3
    min_free: int = 2 * 1024 ** 3
    tts_key: str = ''
    tts_resource: str = 'seed-tts-2.0'

    @classmethod
    def load(cls):
        # Explicit local settings only; never read Codex credentials.
        envfile = ROOT / '.env'
        if envfile.exists():
            for line in envfile.read_text('utf-8-sig').splitlines():
                if '=' in line and not line.lstrip().startswith('#'):
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        return cls(Path(os.environ.get('VIDEO_DATA_DIR', str(ROOT / 'data'))).resolve(), resolve_ffmpeg(), resolve_capcut(),
                   os.environ.get('VIDEO_ACCESS_CODE', ''), os.environ.get('VIDEO_AI_API_KEY', ''),
                   os.environ.get('VIDEO_AI_MODEL', ''), os.environ.get('VIDEO_ENABLE_AI') == '1',
                   tts_key=os.environ.get('VIDEO_TTS_API_KEY', ''),
                   tts_resource=os.environ.get('VIDEO_TTS_RESOURCE_ID', 'seed-tts-2.0'))

    @property
    def tts_ready(self):
        return bool(self.tts_key and self.tts_resource)

    @property
    def ai_ready(self):
        return bool(self.ai_enabled and self.ai_key and self.ai_model)

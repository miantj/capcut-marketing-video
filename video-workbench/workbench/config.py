import os
import shutil
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
        ffmpeg = os.environ.get('VIDEO_FFMPEG') or shutil.which('ffmpeg')
        if not ffmpeg:
            try:
                import imageio_ffmpeg
                ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            except ImportError:
                candidates = list((ROOT.parent / '.audio-tools/imageio_ffmpeg/binaries').glob('ffmpeg*.exe'))
                ffmpeg = str(candidates[0]) if candidates else ''
        cli = Path(os.environ.get('VIDEO_CAPCUT_JS', str(Path(os.environ.get('APPDATA', '')) / 'npm/node_modules/capcut-cli/dist/index.js')))
        capcut = [shutil.which('node') or 'node', str(cli)] if cli.is_file() else []
        return cls(Path(os.environ.get('VIDEO_DATA_DIR', str(ROOT / 'data'))).resolve(), ffmpeg or '', capcut,
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

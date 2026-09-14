"""Real compilation/rendering smoke test, isolated from the editor's draft store."""
import json
import sys
import uuid
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench.config import ROOT, Settings
from workbench.media import probe, run
from workbench.models import JobRequest
from workbench.store import Store
from workbench.worker import Worker

settings = Settings.load()
if '--tts-fallback' in sys.argv:
    settings.tts_key = ''
settings.data = ROOT / 'verification' / ('smoke-' + uuid.uuid4().hex[:8])
store = Store(settings.data)
job = store.create(JobRequest(title='自动制作流程验收', owner='系统验收', script='上传素材，生成可编辑字幕。背景音乐独立成轨。',
    narration='volcengine' if any(arg in sys.argv for arg in ('--tts','--tts-fallback')) else 'none', bgm_volume=.15).model_dump())
folder = settings.data / 'jobs' / job['id']
video = folder / 'uploads/sample.mp4'
music = folder / 'uploads/music.wav'
run([settings.ffmpeg, '-hide_banner','-loglevel','error','-nostdin','-y','-f','lavfi','-i','testsrc2=size=360x640:rate=30','-t','5','-c:v','libx264','-pix_fmt','yuv420p',video])
run([settings.ffmpeg, '-hide_banner','-loglevel','error','-nostdin','-y','-f','lavfi','-i','sine=frequency=220:sample_rate=44100','-t','3',music])
with store.db() as db:
    for path, role in [(video,'video'),(music,'bgm')]:
        db.execute('INSERT INTO files(id,job,name,role,size,received,path) VALUES(?,?,?,?,?,?,?)',
                   (uuid.uuid4().hex,job['id'],path.name,role,path.stat().st_size,path.stat().st_size,path.relative_to(folder).as_posix()))
try:
    Worker(settings, store).process(job['id'])
except Exception:
    print('Failure artifacts:', folder)
    raise
result = store.get(job['id'])
assert result['status'] == 'ready', result
with zipfile.ZipFile(folder/'draft.zip') as archive:
    assert not archive.testzip()
    assert 'Import-Draft.ps1' in archive.namelist()
    assert 'Import-Draft.command' in archive.namelist()
    assert archive.getinfo('Import-Draft.command').external_attr >> 16 & 0o777 == 0o755
    manifest = json.loads(archive.read('manifest.json'))
    assert manifest['native_verified'] is False
    content = json.loads(archive.read('draft/draft_content.json'))
    assert set(t['type'] for t in content['tracks']) == {'video','text','audio'}
    assert content['canvas_config']['ratio'] == '9:16'
    if '--tts' in sys.argv:
        voice = next(t for t in content['tracks'] if t.get('name') == '火山口播')
        assert voice['segments']
        assert result['result']['timing_basis']['speech_aligned']
        assert (folder/'narration.wav').is_file()
    text = archive.read('draft/draft_content.json').decode()
    assert '__DRAFT_ROOT__' in text
    assert str(folder).replace('\\','\\\\') not in text
assert probe(settings.ffmpeg, folder/'preview.mp4')['audio']
if '--tts-fallback' in sys.argv:
    assert result['result']['narration']['fallback'] is True
    assert result['result']['timing_basis']['speech_aligned'] is False
    assert 'narration.wav' not in result['result']['files']
    assert not (folder/'narration.wav').exists()
(ROOT/'verification/latest-smoke.json').write_text(json.dumps({'folder':str(folder),'data':str(settings.data),'result':result['result']},ensure_ascii=False,indent=2),'utf-8')
print(json.dumps({'ok':True,'folder':str(folder),'result':result['result']},ensure_ascii=False))

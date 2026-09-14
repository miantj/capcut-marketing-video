import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench.config import Settings, resolve_capcut, resolve_ffmpeg
from workbench.compat import repair_material_durations
from workbench.media import ProductionError, failed_tool_message, ordered_shots, script_cues, validate_shots, probe
from workbench.packaging import replace_paths
from workbench.store import Store


class PlanningTests(unittest.TestCase):
    def test_tts_can_defer_estimated_limit_until_actual_audio(self):
        text = '测试文案。' * 180
        with self.assertRaises(ProductionError):
            script_cues(text)
        cues = script_cues(text, limit_estimate=False)
        self.assertEqual(''.join(c['text'] for c in cues), text)
        self.assertGreater(sum(c['duration'] for c in cues), 180)
    def test_preserves_copy_and_timings(self):
        text = '秋季新品，价格99.9元！优惠截止9月30日。\n尺码 XS / S / M，咨询客服。'
        cues = script_cues(text)
        import re
        self.assertEqual(re.sub(r'\s', '', ''.join(c['text'] for c in cues)), re.sub(r'\s', '', text))
        from workbench.skill_timing import timing_module
        skill = timing_module()
        self.assertAlmostEqual(sum(c['duration'] for c in cues), skill.count_display_chars(text) * skill.DEFAULT_SEC_PER_CHAR)
        self.assertEqual(len(set(c['id'] for c in cues)), len(cues))

    def test_short_sources_repeat_without_overrun(self):
        cues = script_cues('一段比较长的测试文案。要完整保留每一个文字。')
        videos = [{'id':'a','media':{'duration':.3}}, {'id':'b','media':{'duration':1.3}}]
        shots = ordered_shots(cues, videos)
        validate_shots(shots, videos, sum(c['duration'] for c in cues))
        self.assertGreater(len(shots), 2)

    def test_rejects_bad_ai_plan(self):
        for shot in ({'asset_id':'other','start':0,'duration':1,'source_in':0},
                     {'asset_id':'a','start':0,'duration':float('nan'),'source_in':0},
                     {'asset_id':'a','start':0,'duration':3,'source_in':9},
                     {'asset_id':'a','start':1,'duration':3,'source_in':0}):
            with self.assertRaises(ProductionError):
                validate_shots([shot], [{'id':'a','media':{'duration':10}}], 3)

    def test_rejects_renamed_playlist_before_running_tools(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'video.mp4'
            path.write_text('#EXTM3U\nhttps://example.invalid/private.ts')
            with self.assertRaises(ProductionError):
                probe('executable-must-not-be-called', path)

    def test_multiple_sources_advance_before_repeating(self):
        shots = ordered_shots([{'duration':18}], [{'id':'a','media':{'duration':12}}, {'id':'b','media':{'duration':12}}])
        self.assertEqual([s['asset_id'] for s in shots], ['a','b','a','b'])
        self.assertEqual([s['source_in'] for s in shots], [0,0,4.5,4.5])

    def test_portable_paths_do_not_rewrite_user_copy(self):
        draft = Path('D:/jobs/one/draft')
        content = {'path':'D:/jobs/one/draft/assets/video.mp4', 'text':'请使用 D:/jobs/one/draft 文件'}
        result = replace_paths(content, draft, draft.parent)
        self.assertEqual(result['path'], '__DRAFT_ROOT__/assets/video.mp4')
        self.assertEqual(result['text'], content['text'])

    def test_mac_native_paths_are_portable(self):
        draft = Path('/tmp/jobs/one/draft')
        font = Path('/Applications/VideoFusion-macOS.app/Contents/Resources/Font/悠然体.ttf')
        effect = Path.home() / 'Movies/JianyingPro/User Data/Cache/effect/abc/config.json'
        content = {'font_path': str(font), 'path': str(effect), 'text': '请使用 ' + str(font) + ' 文件'}
        result = replace_paths(content, draft, draft.parent)
        self.assertEqual(result['font_path'], '__JY_FONT_ROOT__/悠然体.ttf')
        self.assertEqual(result['path'], '__JY_EFFECT_ROOT__/abc/config.json')
        self.assertEqual(result['text'], content['text'])


class ToolFailureTests(unittest.TestCase):
    def test_editor_open_is_explained(self):
        completed = SimpleNamespace(
            returncode=1, stdout='',
            stderr='{"error":"refused [editor-open]: JianyingPro.exe is running. Close the editor before repairing this draft, or pass --force-write"}\n')
        self.assertIn('剪映正在运行', failed_tool_message(completed))

    def test_json_cli_error_is_surfaced(self):
        completed = SimpleNamespace(returncode=1, stdout='', stderr='{"error":"no such draft"}\n')
        self.assertIn('no such draft', failed_tool_message(completed))

    def test_blank_failure_keeps_generic_message(self):
        completed = SimpleNamespace(returncode=1, stdout='', stderr='ffmpeg boom\n')
        self.assertEqual(failed_tool_message(completed), '处理工具执行失败，管理员可查看本机制作日志。')

    def test_missing_filter_is_surfaced(self):
        completed = SimpleNamespace(returncode=8, stdout='', stderr="[AVFilterGraph] No such filter: 'ass'\nError : Filter not found\n")
        self.assertIn("No such filter: 'ass'", failed_tool_message(completed))


class IsolatedDraftWriteTests(unittest.TestCase):
    def test_repair_syncs_while_editor_may_be_open(self):
        with tempfile.TemporaryDirectory() as temp:
            draft = Path(temp)
            (draft / 'draft_content.json').write_text(json.dumps({
                'materials': {'videos': [], 'audios': [], 'texts': []},
                'tracks': [],
            }), encoding='utf-8')
            settings = SimpleNamespace(capcut=['node', 'cli.js'], ffmpeg='ffmpeg')
            completed = SimpleNamespace(returncode=0, stdout='{}', stderr='')
            with patch('workbench.compat.run', return_value=completed) as run:
                repair_material_durations(draft, settings, draft / 'log')
            argv = run.call_args.args[0]
            self.assertEqual(argv[:4], ['node', 'cli.js', 'sync-timelines', draft])
            self.assertIn('--force-write', argv)

    def test_repair_keeps_native_font_path(self):
        with tempfile.TemporaryDirectory() as temp:
            draft = Path(temp)
            (draft / 'draft_content.json').write_text(json.dumps({
                'materials': {'videos': [], 'audios': [], 'texts': [
                    {'id': 'caption', 'font_path': 'C:/fonts/you.ttf', 'font_size': 20}]},
                'tracks': [],
            }), encoding='utf-8')
            settings = SimpleNamespace(capcut=['node', 'cli.js'], ffmpeg='ffmpeg')
            completed = SimpleNamespace(returncode=0, stdout='{}', stderr='')
            with patch('workbench.compat.run', return_value=completed):
                repair_material_durations(draft, settings, draft / 'log')
            saved = json.loads((draft / 'draft_content.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['materials']['texts'][0]['font_path'], 'C:/fonts/you.ttf')
            self.assertNotIn('font_name', saved['materials']['texts'][0])


class QueueTests(unittest.TestCase):
    def test_atomic_claim_and_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp))
            job = store.create({'title':'test'})
            store.update(job['id'], 'queued', 'test', 0)
            with ThreadPoolExecutor(max_workers=5) as pool:
                claimed = list(pool.map(lambda _: store.claim(), range(5)))
            self.assertEqual(claimed.count(job['id']), 1)
            store.recover()
            self.assertEqual(store.get(job['id'])['status'], 'needs_attention')


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import uvicorn
        from workbench.app import create_app
        cls.temp = tempfile.TemporaryDirectory()
        cls.settings = Settings(Path(cls.temp.name), '', [], '', '', '', False, min_free=0)
        cls.app = create_app(cls.settings, start_worker=False)
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        cls.base = f'http://127.0.0.1:{sock.getsockname()[1]}'
        cls.server = uvicorn.Server(uvicorn.Config(cls.app, log_level='error'))
        cls.thread = threading.Thread(target=cls.server.run, kwargs={'sockets':[sock]}, daemon=True)
        cls.thread.start()
        for _ in range(100):
            if cls.server.started:
                break
            time.sleep(.02)
        assert cls.server.started

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(5)
        cls.temp.cleanup()

    def call(self, path, method='GET', body=None, raw=None, headers=None):
        data = raw if raw is not None else json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method,
                                         headers=headers or {'Content-Type':'application/json'})
        try:
            response = urllib.request.urlopen(request)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            payload = response.read()
            try:
                result = json.loads(payload)
            except ValueError:
                result = payload
            return response.status, result

    def new_job(self, **kwargs):
        payload = dict(title='Test', owner='Tester', script='原始文案。', **kwargs)
        status, job = self.call('/api/jobs','POST',payload)
        self.assertEqual(status, 201)
        return job

    def test_upload_offsets_submit_and_path_safety(self):
        job = self.new_job()
        base = '/api/jobs/' + job['id']
        self.assertEqual(self.call(base + '/submit', 'POST')[0], 422)
        code, item = self.call(base + '/files', 'POST', {'name':'../../outside.mp4','role':'video','size':6})
        self.assertEqual(code, 201)
        path = base + '/files/' + item['id']
        self.assertEqual(self.call(path + '?offset=1', 'PUT', raw=b'abc')[0], 409)
        self.assertEqual(self.call(path, 'PUT', raw=b'abc')[1]['received'], 3)
        self.assertEqual(self.call(base + '/submit', 'POST')[0], 422)
        self.assertEqual(self.call(path + '?offset=3', 'PUT', raw=b'def')[0], 200)
        code, bgm = self.call(base + '/files', 'POST', {'name':'music.mp3','role':'bgm','size':3})
        self.assertEqual(self.call(base + '/submit', 'POST')[0], 409)
        self.assertEqual(self.call(base + '/files/' + bgm['id'], 'PUT', raw=b'abc')[0], 200)
        self.assertEqual(self.call(base + '/submit','POST')[1]['status'], 'queued')
        self.assertEqual(self.call(base + '/submit','POST')[0], 409)
        self.assertEqual(self.call(path, 'PUT', raw=b'xxx')[0], 409)
        self.assertFalse((Path(self.temp.name) / 'outside.mp4').exists())
        files = self.app.state.store.get(job['id'])['files']
        self.assertTrue(all(f['path'].startswith('uploads/') and '..' not in f['path'] for f in files))
        self.assertNotIn('path', self.call(base)[1]['files'][0])

    def test_speech_preview_enforces_limit_and_cleans_files(self):
        original = self.settings.tts_key, self.settings.ffmpeg
        self.settings.tts_key, self.settings.ffmpeg = 'test-key', 'test-ffmpeg'
        try:
            self.assertEqual(self.call('/api/tts/preview', 'POST', {'text':'字'*21})[0], 422)
            self.assertEqual(self.call('/api/tts/preview', 'POST', {'text':'   '})[0], 422)
            def generated(settings, text, speaker, speed, path):
                path.write_bytes(b'wave-test-output')
            with patch('workbench.app.synthesize', side_effect=generated):
                code, audio = self.call('/api/tts/preview', 'POST', {'text':'测试'})
            self.assertEqual((code, audio), (200, b'wave-test-output'))
            self.assertEqual(list((self.settings.data/'tts-preview').iterdir()), [])
            def failed(settings, text, speaker, speed, path):
                path.write_bytes(b'partial')
                raise ProductionError('试听失败')
            with patch('workbench.app.synthesize', side_effect=failed):
                self.assertEqual(self.call('/api/tts/preview', 'POST', {'text':'测试'})[0], 502)
            self.assertEqual(list((self.settings.data/'tts-preview').iterdir()), [])
        finally:
            self.settings.tts_key, self.settings.ffmpeg = original

    def test_limits_and_cloud_gate(self):
        job = self.new_job()
        base = '/api/jobs/' + job['id']
        self.assertEqual(self.call(base + '/files','POST',{'name':'run.ps1','role':'video','size':3})[0],422)
        self.assertEqual(self.call(base + '/files','POST',{'name':'huge.mp4','role':'video','size':2 * 1024**3})[0],413)
        self.assertEqual(self.call('/api/jobs','POST',{'title':'T','owner':'T','script':'T','selection':'ai'})[0],409)
        self.assertEqual(self.call('/api/jobs','POST',{'title':'T','owner':'T','script':'T','narration':'native_tts'})[0],422)
        self.assertEqual(self.call('/api/jobs','POST',{'title':'T','owner':'T','script':'T','narration':'volcengine'})[0],201)
        self.settings.tts_key = 'secret-test-value'
        try:
            self.assertTrue(self.call('/api/health')[1]['tts_ready'])
            code, voiced = self.call('/api/jobs','POST',{'title':'T','owner':'T','script':'T','narration':'volcengine'})
            self.assertEqual(code, 201)
            self.assertNotIn('secret-test-value', json.dumps(voiced))
            self.assertNotIn('secret-test-value', json.dumps(self.call('/api/health')[1]))
        finally:
            self.settings.tts_key = ''
        self.assertEqual(self.call(base + '/artifacts/commands.jsonl')[0],404)
        self.assertEqual(self.call('/api/jobs','POST',{'title':'T','owner':'T','script':'T'},headers={'Origin':'https://evil.example','Content-Type':'application/json'})[0],403)

    def test_revision_keeps_original_and_cancel(self):
        job = self.new_job()
        base = '/api/jobs/' + job['id']
        for role, ext in [('video','mp4'),('bgm','mp3')]:
            _, file = self.call(base + '/files','POST',{'name':'test.'+ext,'role':role,'size':3})
            self.call(base + '/files/' + file['id'],'PUT',raw=b'abc')
        self.app.state.store.update(job['id'],'needs_attention','test',0)
        code, revised = self.call(base + '/revisions','POST',{'request':{'title':'Revised','owner':'Tester','script':'新文案。'}})
        self.assertEqual(code,201)
        self.assertEqual(revised['revision'],2)
        self.assertEqual(revised['parent'],job['id'])
        self.assertEqual(self.call(base)[1]['request']['script'],'原始文案。')
        self.assertEqual(self.call('/api/jobs/' + revised['id'] + '/cancel','POST')[1]['status'],'cancelled')
        self.assertEqual(self.call('/api/jobs/' + revised['id'] + '/cancel','POST')[0],409)

    def test_revision_rejects_cancelled_job_without_music(self):
        job = self.new_job()
        base = '/api/jobs/' + job['id']
        _, item = self.call(base + '/files', 'POST', {'name': 'test.mp4', 'role': 'video', 'size': 3})
        self.call(base + '/files/' + item['id'], 'PUT', raw=b'abc')
        self.call(base + '/cancel', 'POST')
        code, _ = self.call(base + '/revisions', 'POST', {'request': {
            'title': 'Retry', 'owner': 'Tester', 'script': '测试文案内容。'}})
        self.assertEqual(code, 409)

    def test_missing_artifact_returns_not_found(self):
        job = self.new_job()
        self.app.state.store.update(job['id'], 'ready', 'done', 100,
                                    result={'files': ['preview.mp4']})
        self.assertEqual(self.call('/api/jobs/' + job['id'] + '/artifacts/preview.mp4')[0], 404)

    def test_artifact_does_not_keep_http_alive(self):
        job = self.new_job()
        preview = Path(self.settings.data) / 'jobs' / job['id'] / 'preview.mp4'
        preview.write_bytes(b'not-a-real-video')
        self.app.state.store.update(job['id'], 'ready', 'done', 100,
                                    result={'files': ['preview.mp4']})
        request = urllib.request.Request(self.base + '/api/jobs/' + job['id'] + '/artifacts/preview.mp4')
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.headers.get('Connection'), 'close')
            self.assertEqual(response.read(), b'not-a-real-video')

    def test_optional_access_code(self):
        self.settings.access_code = 'team-test-code'
        try:
            self.assertEqual(self.call('/api/jobs')[0],401)
            self.assertEqual(self.call('/api/session')[1]['authenticated'],False)
            req = urllib.request.Request(self.base+'/api/login', data=json.dumps({'code':'team-test-code'}).encode(),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(req) as response:
                cookie = response.headers['Set-Cookie'].split(';')[0]
            self.assertEqual(self.call('/api/jobs',headers={'Cookie':cookie})[0],200)
            self.assertEqual(self.call('/api/login','POST',{'code':'x'})[0],401)
        finally:
            self.settings.access_code = ''


class CapcutResolveTests(unittest.TestCase):
    def test_uses_explicit_cli_and_path_binary(self):
        with tempfile.TemporaryDirectory() as temp:
            cli = Path(temp) / 'index.js'
            cli.write_text('module.exports = {}', encoding='utf-8')
            self.assertEqual(resolve_capcut({'VIDEO_CAPCUT_JS': str(cli)}), [shutil.which('node') or 'node', str(cli)])
            self.assertEqual(resolve_capcut({'VIDEO_CAPCUT_JS': str(Path(temp) / 'missing.js')}), [])
            binary = Path(temp) / 'capcut'
            binary.write_text('', encoding='utf-8')
            binary.chmod(0o755)
            with patch.dict(os.environ, {'PATH': temp, 'PATHEXT': ''}, clear=False):
                self.assertEqual(resolve_capcut({}), [str(binary)])

    def test_skill_capcut_cmd_resolves_local_cli(self):
        from workbench.skill_timing import skill_root
        scripts = str(skill_root() / 'scripts')
        sys.path.insert(0, scripts)
        try:
            import capcut_bin
            capcut_bin.capcut_cmd.cache_clear()
            cmd = capcut_bin.capcut_cmd()
            self.assertTrue(Path(cmd).is_file())
            self.assertTrue('capcut' in Path(cmd).name)
        finally:
            sys.path.remove(scripts)

    def test_prefers_ffmpeg_with_ass_filter(self):
        with patch.dict(os.environ, {'VIDEO_FFMPEG': '/brew/ffmpeg'}, clear=False), \
             patch('workbench.config.shutil.which', return_value='/brew/ffmpeg'), \
             patch('workbench.config.ffmpeg_has_filter', side_effect=lambda path, name: 'imageio' in path), \
             patch('imageio_ffmpeg.get_ffmpeg_exe', return_value='/venv/imageio-ffmpeg'):
            self.assertEqual(resolve_ffmpeg(), '/venv/imageio-ffmpeg')


if __name__ == '__main__':
    unittest.main()

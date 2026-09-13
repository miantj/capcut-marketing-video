import json
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from workbench.media import script_cues
from workbench.models import JobRequest
from workbench.speech_cache import SpeechCache, inherit_speech_cache, DEFAULT_RESOURCE
from workbench.tts import narrate, optional_narration, SpeechServiceError


def speech(settings, text, speaker, speed, destination):
    with wave.open(str(destination), 'wb') as output:
        output.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
        output.writeframes(b'\0\0' * 48000)
    return 2.


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old = self.root / 'old'
        self.old.mkdir()
        self.request = JobRequest(title='T', owner='T', script='第一句话。第二句话。第三句话。').model_dump()
        self.settings = SimpleNamespace(tts_resource=DEFAULT_RESOURCE, tts_ready=False)

    def generate(self, folder, request):
        return narrate(self.settings, request, script_cues(request['script'], limit_estimate=False, merge_short=False), folder, lambda *_: None)

    def clone(self, request, name='new'):
        folder = self.root / name
        folder.mkdir()
        inherit_speech_cache({'request': self.request}, self.old, folder, request, self.settings.tts_resource)
        return folder

    def seed(self):
        with patch('workbench.tts.synthesize', side_effect=speech) as api:
            self.generate(self.old, self.request)
            self.assertEqual(api.call_count, 3)

    def test_style_only_offline_and_independent_of_parent(self):
        self.seed()
        original = (self.old / 'narration.wav').read_bytes()
        request = {**self.request, 'template': 'promo'}
        new = self.clone(request)
        for path in (self.old / 'speech-cache').iterdir():
            path.unlink()
        with patch('workbench.tts.synthesize', side_effect=AssertionError('network forbidden')):
            self.generate(new, request)
        self.assertEqual((new / 'narration.wav').read_bytes(), original)
        stats = json.loads((new / 'narration-stats.json').read_text())
        self.assertEqual((stats['reused'], stats['generated']), (3, 0))

    def test_one_edit_and_insertion_only_generate_changed_clauses(self):
        self.seed()
        for index, script in enumerate(['第一句话。改动第二句。第三句话。', '新增开头。第一句话。第二句话。第三句话。']):
            request = {**self.request, 'script': script}
            new = self.clone(request, str(index))
            with patch('workbench.tts.synthesize', side_effect=speech) as api:
                self.generate(new, request)
                self.assertEqual(api.call_count, 1)

    def test_voice_speed_and_resource_invalidate(self):
        self.seed()
        for index, changes in enumerate([{'tts_speaker': 'another_voice'}, {'tts_speed': 1.2}, {}]):
            if index == 2:
                self.settings.tts_resource = 'another-model'
            request = {**self.request, **changes}
            new = self.clone(request, str(index))
            with patch('workbench.tts.synthesize', side_effect=speech) as api:
                self.generate(new, request)
                self.assertEqual(api.call_count, 3)

    def test_corruption_regenerates_only_corrupt_segment(self):
        self.seed()
        cache = SpeechCache(self.old, self.request)
        cache.get('第二句话。')[0].write_bytes(b'broken')
        new = self.clone(self.request)
        with patch('workbench.tts.synthesize', side_effect=speech) as api:
            self.generate(new, self.request)
            self.assertEqual(api.call_count, 1)

    def test_partial_failure_can_resume(self):
        def fail(settings, text, speaker, speed, destination):
            if text == '第二句话。':
                raise SpeechServiceError('失败')
            return speech(settings, text, speaker, speed, destination)
        with patch('workbench.tts.synthesize', side_effect=fail):
            _, items, warning = optional_narration(self.settings, self.request,
                script_cues(self.request['script'], merge_short=False), self.old, lambda *_: None)
        self.assertFalse(items)
        self.assertTrue(warning)
        new = self.clone(self.request)
        with patch('workbench.tts.synthesize', side_effect=speech) as api:
            self.generate(new, self.request)
            self.assertEqual(api.call_count, 2)

    def test_legacy_merged_audio_is_reused(self):
        request = {**self.request, 'script': '你好。欢迎使用。测试完成。'}
        (self.old / 'narration').mkdir()
        for cue in script_cues(request['script'], limit_estimate=False):
            speech(None, cue['text'], '', 1, self.old / 'narration' / (cue['id'] + '.wav'))
        new = self.root / 'legacy'
        new.mkdir()
        inherit_speech_cache({'request': request, 'result': {'narration': {'provider': 'volcengine'}}},
            self.old, new, request, DEFAULT_RESOURCE)
        with patch('workbench.tts.synthesize', side_effect=AssertionError('network forbidden')):
            self.generate(new, request)

import base64
import io
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from workbench.media import ProductionError
from workbench.models import JobRequest
from workbench.tts import narrate, read_audio, optional_narration, synthesize, SpeechServiceError
from types import SimpleNamespace


def stream(*events):
    return io.BytesIO(b''.join(b'data: ' + json.dumps(e).encode() + b'\n\n' for e in events))


class SpeechTests(unittest.TestCase):
    def test_disabled_skips_service(self):
        with patch('workbench.tts.narrate') as generate:
            cues = [{'text': '测试', 'duration': 2}]
            self.assertEqual(optional_narration(None, {'narration':'none'}, cues, None, None), (cues, [], None))
            generate.assert_not_called()

    def test_unconfigured_service_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            request = JobRequest(title='T', owner='T', script='测试').model_dump()
            self.assertEqual(request['narration'], 'volcengine')
            cues = [{'id':'S1', 'text':'测试', 'start':0, 'duration':2}]
            aligned, items, warning = optional_narration(SimpleNamespace(tts_ready=False), request, cues, Path(directory), lambda *_: None)
            self.assertEqual(aligned, cues)
            self.assertEqual(items, [])
            self.assertIn('已回退', warning)

    def test_partial_failure_discards_audio_and_keeps_estimated_timing(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            cues = [{'id':f'S{i}', 'text':'测试文案', 'start':i*3, 'duration':3} for i in range(2)]
            request = JobRequest(title='T', owner='T', script='测试文案').model_dump()
            (folder/'narration').mkdir()
            (folder/'narration/S0.wav').write_bytes(b'partial audio')
            with patch('workbench.tts.synthesize', side_effect=[1.5, SpeechServiceError('接口断流')]):
                actual, items, warning = optional_narration(None, request, cues, folder, lambda *_: None)
            self.assertEqual(actual, cues)
            self.assertEqual([c['duration'] for c in actual], [3,3])
            self.assertEqual(items, [])
            self.assertIn('接口断流', warning)
            self.assertFalse((folder/'narration.wav').exists())
            self.assertEqual(list((folder/'narration').iterdir()), [])

    def test_terminal_event_does_not_wait_for_connection_close(self):
        def events():
            yield b'data: {"data":"YWJj"}\n'
            yield b'data: {"code":20000000}\n'
            raise TimeoutError('connection left open after successful response')
        self.assertEqual(read_audio(events()), b'abc')

    def test_invalid_mp3_is_a_service_failure_and_cleans_temp_files(self):
        from workbench.config import Settings
        settings = Settings.load()
        settings.tts_key = 'test-key'
        response = stream({'data':base64.b64encode(b'not mp3 audio').decode()}, {'code':20000000})
        with tempfile.TemporaryDirectory() as directory, patch('workbench.tts.urllib.request.urlopen', return_value=response):
            output = Path(directory)/'broken.wav'
            with self.assertRaises(SpeechServiceError):
                synthesize(settings, '测试', 'voice', 1, output)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_non_service_errors_are_not_hidden(self):
        with patch('workbench.tts.narrate', side_effect=ProductionError('文案过长')):
            with self.assertRaisesRegex(ProductionError, '文案过长'):
                optional_narration(None, {'narration':'volcengine'}, [], Path('.'), None)

    def test_complete_chunks(self):
        response = stream({'data': base64.b64encode(b'abc').decode()},
                          {'data': base64.b64encode(b'def').decode()}, {'code': 20000000})
        self.assertEqual(read_audio(response), b'abcdef')

    def test_truncated_empty_and_error_responses_fail(self):
        for response in [stream({'data': 'YWJj'}), stream({'code': 20000000}),
                         stream({'code': 45000000, 'message': 'private-value'}),
                         stream({'data': '??'}, {'code': 20000000})]:
            with self.assertRaises(ProductionError) as raised:
                read_audio(response)
            self.assertNotIn('private-value', str(raised.exception))

    def test_short_caption_merge_preserves_actual_audio_timing(self):
        lengths = iter([.6, 1.8, .5])

        def fake_speech(settings, text, speaker, speed, destination):
            seconds = next(lengths)
            with wave.open(str(destination), 'wb') as output:
                output.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                output.writeframes(b'\0\0' * round(seconds * 24000))
            return seconds

        with tempfile.TemporaryDirectory() as directory, patch('workbench.tts.synthesize', side_effect=fake_speech):
            folder = Path(directory)
            cues = [{'id': f'S{i}', 'text': text, 'duration': 9, 'start': 9*i}
                    for i, text in enumerate(['你好，', '这是口播测试。', '再见。'])]
            captions, items = narrate(None, JobRequest(title='T', owner='T', script='T').model_dump(), cues, folder, lambda *_: None)
            self.assertEqual(len(captions), 1)
            self.assertEqual(captions[0]['text'], '你好，这是口播测试。再见。')
            self.assertAlmostEqual(captions[0]['duration'], 2.9)
            self.assertEqual([i['start'] for i in items], [0, .6, 2.4])
            with wave.open(str(folder/'narration.wav'), 'rb') as output:
                self.assertEqual(output.getnframes(), 69600)

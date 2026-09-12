"""Isolated P0 regression and real CLI compilation; no draft-store registration."""
import copy
import json
import subprocess
import unittest
from pathlib import Path

from test_workflow import WorkflowTests
from workflow import compile_plan, run
from inspect_inputs import inspect_media, media_files
from validate_storyboard import validate


class P0Tests(WorkflowTests):
    def setUp(self):
        super().setUp()
        self.plan['audio'][0]['volume'] = 0.8
        for caption in self.plan['captions']:
            caption['visual'] = dict(fontSize=20, color='#FFFFFF', x=0, y=-0.5)

    def test_mapping_and_vertical_gate(self):
        before = copy.deepcopy(self.plan)
        spec, pending = compile_plan(self.plan, self.base)
        shot = spec['tracks'][0]['items'][0]
        self.assertEqual((shot['volume'], shot['sourceStart'], shot['duration']), (0, 2, 6))
        self.assertEqual(spec['tracks'][1]['items'][0]['volume'], 0.8)
        self.assertEqual(spec['tracks'][2]['items'][0]['text'], '夏装\n补货')
        self.assertEqual(pending[0]['status'], 'pending')
        self.assertEqual(before, self.plan)
        self.plan['canvas'].update(width=1920, height=1080)
        with self.assertRaises(ValueError):
            compile_plan(self.plan, self.base)

    def test_explicit_volume_and_unsupported_style(self):
        self.plan['audio'][0].pop('volume')
        with self.assertRaises(ValueError):
            compile_plan(self.plan, self.base)
        self.plan['audio'][0]['volume'] = 0.8
        self.plan['captions'][0]['visual']['bogus'] = True
        with self.assertRaises(ValueError):
            compile_plan(self.plan, self.base)

    def test_timing_regressions(self):
        cases = []
        p = copy.deepcopy(self.plan)
        p['captions'][1]['start'] = 2
        cases.append(('Overlapping body captions', p))
        p = copy.deepcopy(self.plan)
        p['captions'][0].update(start=3, end=6)
        p['captions'][1].update(start=0, end=3)
        cases.append(('script order', p))
        p = copy.deepcopy(self.plan)
        p['audio'].append(copy.deepcopy(p['audio'][0]))
        cases.append(('Overlapping narration audio', p))
        p = copy.deepcopy(self.plan)
        p['captions'][0]['end'] = 1
        cases.append(('stable caption reading time', p))
        p = copy.deepcopy(self.plan)
        p['audio'][0]['volume'] = 0
        cases.append(('audible', p))
        p = copy.deepcopy(self.plan)
        p['captions'][0]['cue_ids'] = ['a']
        cases.append(('Invalid cue references', p))
        p = copy.deepcopy(self.plan)
        p['audio'][0]['fade_out'] = 7
        cases.append(('Invalid audio fade_out', p))
        for message, plan in cases:
            with self.subTest(message=message):
                self.assertTrue(any(message in e for e in validate(plan, self.base)['errors']))
                with self.assertRaises(ValueError):
                    compile_plan(plan, self.base)

    def test_grouped_speech_prepare_and_alignment_gate(self):
        self.plan['narration'] = dict(mode='native_tts', timing='estimated')
        self.plan['script'][0].update(start=0, end=2.5, pause_after=0.5, emphasis=['补货'])
        self.plan['script'][1].update(start=3, end=5.5, pause_after=0.5)
        self.plan['captions'] = [{**self.plan['captions'][0], 'cue_ids': ['a', 'b'],
                                  'end': 6, 'text': '夏装补货\n吉祥专属福利'}]
        self.plan['captions'][0].pop('cue_id')
        voice = self.plan['audio'].pop()
        source = self.base / 'storyboard.json'
        source.write_text(json.dumps(self.plan))
        result = run(source, self.base / 'builds')
        folder = Path(result['run_dir'])
        self.assertIn('(0:00.000–0:02.500)', (folder / 'voice-script.txt').read_text(encoding='utf-8'))
        self.assertEqual((folder / 'tts.txt').read_text(encoding='utf-8'), '夏装补货\n吉祥专属福利\n')
        with self.assertRaisesRegex(ValueError, 'Narration is estimated'):
            run(source, self.base / 'builds', True)
        self.assertFalse((folder / 'draft').exists())
        self.plan['narration'].update(timing='aligned', evidence='Synthetic timing fixture, not speech verification')
        self.assertFalse(validate(self.plan, self.base)['ok'])
        self.plan['audio'] = [{**voice, 'cue_ids': ['a', 'b']}]
        self.assertTrue(validate(self.plan, self.base)['ok'])
        self.plan['script'][0]['pause_after'] = 0.8
        self.assertFalse(validate(self.plan, self.base)['ok'])
        self.plan['script'][0]['pause_after'] = 0.5
        self.plan['audio'][0].update(end=5, source_out=5)
        self.assertTrue(any('truncates spoken cue' in e for e in validate(self.plan, self.base)['errors']))

    def test_retained_source_speech_binding(self):
        self.plan['narration'] = dict(mode='source', timing='aligned', evidence='Synthetic source fixture')
        self.plan['script'][0].update(start=0, end=2.5)
        self.plan['script'][1].update(start=3, end=5.5)
        self.plan['audio'] = []
        self.plan['assets'][0].update(audio_action='keep', audio_note='Fixture speech matches script')
        self.plan['shots'][0]['cue_ids'] = ['a', 'b']
        self.assertTrue(validate(self.plan, self.base)['ok'])
        self.plan['shots'][0]['volume'] = 0
        self.assertFalse(validate(self.plan, self.base)['ok'])
        self.plan['shots'][0]['volume'] = 1
        self.plan['assets'][0]['kind'] = 'image'
        self.assertFalse(validate(self.plan, self.base)['ok'])

    def test_audio_declarations_and_optional_timing(self):
        for action in ('keep', 'duck'):
            with self.subTest(action=action):
                self.plan['assets'][0]['audio_action'] = action
                self.plan['shots'][0]['volume'] = 0
                spec, _ = compile_plan(self.plan, self.base)
                self.assertEqual(spec['tracks'][0]['items'][0]['volume'], 0)
                self.plan['shots'][0]['volume'] = 0.2
                self.assertFalse(validate(self.plan, self.base)['ok'])
        self.plan['assets'][0].update(original_audio='none', audio_action='mute')
        self.plan['audio'][0].update(asset_id='v', source_in=0, source_out=6)
        with self.assertRaisesRegex(ValueError, 'declared to have no audio'):
            compile_plan(self.plan, self.base)
        self.plan['audio'] = []
        self.plan['narration'] = dict(mode='none', timing=None)
        with self.assertRaisesRegex(ValueError, 'Narration timing'):
            compile_plan(self.plan, self.base)
        self.plan['narration'].pop('timing')
        compile_plan(self.plan, self.base)

    def test_real_compile_restart_and_native_edit_protection(self):
        from delivery_steps import start
        self.plan['source_text'] = '夏装补货吉祥专属福利'
        start(self.base, 'create', 'draft+native', 'Isolated compilation test fixture')
        (self.base / 'font.ttf').write_bytes(b'font path fixture only')
        self.plan['narration'] = dict(mode='provided', timing='aligned', evidence='Synthetic tone fixture')
        self.plan['script'][0].update(start=0, end=2.5)
        self.plan['script'][1].update(start=3, end=5.5)
        self.plan['audio'][0]['cue_ids'] = ['a', 'b']
        for cap in self.plan['captions']:
            cap['visual']['font'] = dict(path=str(self.base / 'font.ttf'), id='fixture')
            cap['animation'] = dict(intro='放大', outro='缩小', intro_seconds=.5, outro_seconds=.5, purpose='benefit')
        self.plan['captions'][0]['keywords'] = ['补货']
        self.plan['captions'][1]['bubble'] = dict(text='福利', x=0, y=.5, width=.3, height=.1)
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'color=c=blue:s=72x128:r=30', '-t', '10', '-c:v', 'libx264',
                        str(self.base / 'video.mp4')], check=True, capture_output=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'sine=frequency=440:duration=6', str(self.base / 'voice.wav')],
                       check=True, capture_output=True)
        self.plan['audio'].append({**self.plan['audio'][0], 'role': 'bgm', 'volume': 0.12,
                                   'fade_in': 0.25, 'fade_out': 0.5})
        media = inspect_media(self.base / 'video.mp4', self.base / 'inspection')
        self.assertEqual(media['kind'], 'video')
        self.assertEqual(len(media['frames']), 3)
        self.assertTrue(all(Path(f['path']).is_file() for f in media['frames']))
        self.assertIn('unknown', media['burned_in_text'])
        self.assertIn((self.base / 'video.mp4').resolve(), media_files(self.base))
        source = self.base / 'storyboard.json'
        source.write_text(json.dumps(self.plan), encoding='utf-8')
        result = run(source, self.base / 'builds', True)
        self.assertEqual(result['stage'], 'compiled')
        self.assertEqual(result['native_preview'], 'pending')
        self.assertEqual(result['native_export'], 'pending')
        again = run(source, self.base / 'builds', True)
        self.assertEqual(result['draft_sha256'], again['draft_sha256'])
        draft = Path(result['draft_file'])
        value = json.loads(draft.read_text(encoding='utf-8-sig'))
        self.assertEqual(value['canvas_config']['width'], 720)
        self.assertEqual(value['canvas_config']['height'], 1280)
        video = next(t for t in value['tracks'] if t['type'] == 'video')
        self.assertEqual(video['segments'][0]['volume'], 0)
        fade = value['materials']['audio_fades'][0]
        self.assertEqual((fade['fade_in_duration'], fade['fade_out_duration']), (250000, 500000))
        bgm = next(t for t in value['tracks'] if t.get('name') == 'bgm')
        self.assertIn(fade['id'], bgm['segments'][0]['extra_material_refs'])
        value['name'] = 'user-edited'
        draft.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaises(ValueError):
            run(source, self.base / 'builds', True)
        self.assertEqual(json.loads(draft.read_text())['name'], 'user-edited')


if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python3
"""Unit checks for narrate/retime and resource path resolution."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from bootstrap_resources import resolve_path, effect_roots, animation_object
from timeline_ops import narrate_plan, retime, retime_by_chars, count_display_chars, probe_duration
from validate_storyboard import validate


class TimelineOpsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='timeline-ops-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.plan = {
            'version': 1, 'duration': 6, 'canvas': {'width': 720, 'height': 1280, 'fps': 30},
            'source_text': '夏装补货不用跑市场',
            'narration': {'mode': 'native_tts', 'timing': 'estimated'},
            'script': [
                {'id': 'hook', 'text': '夏装补货', 'start': 0, 'end': 1, 'pause_after': 0.2},
                {'id': 'benefit', 'text': '不用跑市场', 'start': 1.2, 'end': 3, 'pause_after': 0.3},
            ],
            'assets': [{'id': 'v', 'path': 'video.mp4', 'kind': 'video', 'duration': 10,
                        'inspection': 'fixture', 'original_audio': 'speech', 'audio_action': 'mute',
                        'burned_text': 'none', 'text_action': 'none'}],
            'shots': [{'asset_id': 'v', 'start': 0, 'end': 6, 'source_in': 0, 'source_out': 6, 'speed': 1,
                       'cue_ids': ['hook', 'benefit'], 'match_reason': 'fixture'}],
            'captions': [
                {'cue_ids': ['hook'], 'text': '夏装补货', 'start': 0, 'end': 1.2, 'recipe': 'keyword-reveal',
                 'visual': {'fontSize': 20, 'color': '#FFFFFF', 'x': 0, 'y': -0.5},
                 'animation': {'intro': '放大', 'outro': '缩小', 'intro_seconds': .5, 'outro_seconds': .5, 'purpose': 'hook'}},
                {'cue_ids': ['benefit'], 'text': '不用跑市场', 'start': 1.2, 'end': 6, 'recipe': 'benefit-tag',
                 'visual': {'fontSize': 20, 'color': '#FFFFFF', 'x': 0, 'y': -0.5},
                 'animation': {'intro': '放大', 'outro': '缩小', 'intro_seconds': .5, 'outro_seconds': .5, 'purpose': 'benefit'},
                 'keywords': ['不用跑'], 'bubble': {'text': '手机补货', 'x': 0, 'y': .5, 'width': .3, 'height': .1}},
            ],
            'audio': [],
        }
        (self.base / 'video.mp4').write_bytes(b'fixture')

    def test_narrate_checklist_missing(self):
        result = narrate_plan(self.plan, self.base)
        self.assertFalse(result['ok'])
        self.assertEqual(result['missing'], ['hook', 'benefit'])
        self.assertIn('hook.wav', result['cues'][0]['audio_path'])

    def test_retime_from_durations(self):
        updated = retime(self.plan, durations={'hook': 1.5, 'benefit': 2.0}, evidence='unit test')
        self.assertEqual(updated['narration']['timing'], 'aligned')
        self.assertAlmostEqual(updated['script'][0]['end'] - updated['script'][0]['start'], 1.5)
        self.assertAlmostEqual(updated['script'][1]['start'], 1.7)
        self.assertAlmostEqual(updated['duration'], 4.0)  # 1.5+0.2+2.0+0.3
        self.assertAlmostEqual(updated['shots'][0]['end'], updated['duration'])
        self.assertAlmostEqual(updated['captions'][0]['start'], 0)
        self.assertAlmostEqual(updated['captions'][1]['end'], updated['duration'])

    def test_retime_from_audio_dir(self):
        folder = self.base / 'narration'
        folder.mkdir()
        for cue_id, seconds in (('hook', 1.0), ('benefit', 1.5)):
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            f'sine=frequency=440:duration={seconds}', str(folder / (cue_id + '.wav'))],
                           check=True, capture_output=True)
        updated = retime(self.plan, from_dir=folder, evidence='ffmpeg tones')
        self.assertEqual(updated['narration']['timing'], 'aligned')
        self.assertEqual(len([a for a in updated['audio'] if a['role'] == 'narration']), 2)
        self.assertTrue(any(a['id'].startswith('narration-') for a in updated['assets']))
        # Durations alone are not enough for full validate (fonts etc.); timing fields must be sane.
        self.assertGreater(updated['duration'], 2.5)
        self.assertAlmostEqual(probe_duration(folder / 'hook.wav'), 1.0, places=1)

    def test_retime_by_chars(self):
        self.assertEqual(count_display_chars('夏装 补货\n'), 4)
        updated = retime_by_chars(self.plan, sec_per_char=0.25)
        # hook=4 chars → 1.0s; benefit=5 chars → 1.25s; + pauses 0.2+0.3
        self.assertAlmostEqual(updated['script'][0]['end'] - updated['script'][0]['start'], 1.0)
        self.assertAlmostEqual(updated['script'][1]['end'] - updated['script'][1]['start'], 1.25)
        self.assertAlmostEqual(updated['duration'], 1.0 + 0.2 + 1.25 + 0.3)
        self.assertEqual(updated['narration']['timing'], 'estimated')
        self.assertEqual(updated['narration']['char_timing']['sec_per_char'], 0.25)


class ResourcePathTests(unittest.TestCase):
    def test_resolves_effect_id_when_resource_id_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            cached = Path(temp) / '1644264' / 'pkg'
            cached.mkdir(parents=True)
            found = resolve_path('6724919499042066958', '', [Path(temp)], effect_id='1644264')
            self.assertEqual(found, cached)

    def test_effect_cache_resolution_when_present(self):
        roots = effect_roots()
        if not roots:
            self.skipTest('No local effect cache')
        # Prefer a known 放大 resource if cached.
        path = resolve_path('6724919499042066958', 'cf0f072aa31d3884ba90362af063f55a', roots)
        if path is None:
            self.skipTest('放大 effect not cached on this machine')
        self.assertTrue(path.is_dir())
        obj = animation_object('放大', dict(resource_id='6724919499042066958',
                                            md5='cf0f072aa31d3884ba90362af063f55a',
                                            effect_id='1644264', name='放大'), 'intro', roots)
        self.assertTrue(obj['path_ok'])
        self.assertEqual(obj['name'], '放大')


if __name__ == '__main__':
    raise SystemExit(unittest.main(verbosity=2))

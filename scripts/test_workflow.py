"""Regression tests for plan checks and source-preserving snapshots.

Run: python3 -B <skill>/scripts/test_workflow.py
Only writes inside a fresh TemporaryDirectory, never touches user's drafts.
"""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from inspect_inputs import inspect_draft
from snapshot_draft import snapshot
from validate_storyboard import validate


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='marketing-skill-test-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        (self.base / 'video.mp4').write_bytes(b'fixture for path checks only')
        (self.base / 'voice.wav').write_bytes(b'fixture for path checks only')
        self.plan = {
            'version': 1, 'duration': 6, 'canvas': {'width': 720, 'height': 1280, 'fps': 30},
            'script': [{'id': 'a', 'text': '夏装补货'}, {'id': 'b', 'text': '吉祥专属福利'}],
            'assets': [{'id': 'v', 'path': 'video.mp4', 'kind': 'video', 'duration': 10,
                        'inspection': 'fixture', 'original_audio': 'speech', 'audio_action': 'mute',
                        'burned_text': 'none', 'text_action': 'none'},
                       {'id': 'n', 'path': 'voice.wav', 'kind': 'audio', 'duration': 6, 'inspection': 'fixture'}],
            'shots': [{'asset_id': 'v', 'start': 0, 'end': 6, 'source_in': 2, 'source_out': 8, 'speed': 1}],
            'captions': [{'cue_id': 'a', 'text': '夏装\n补货', 'start': 0, 'end': 3, 'recipe': 'keyword-reveal'},
                         {'cue_id': 'b', 'text': '吉祥专属福利', 'start': 3, 'end': 6, 'recipe': 'cta-lockup'}],
            'audio': [{'asset_id': 'n', 'start': 0, 'end': 6, 'source_in': 0, 'source_out': 6, 'role': 'narration'}],
        }

    def test_valid_plan_and_no_mutation(self):
        original = copy.deepcopy(self.plan)
        self.assertTrue(validate(self.plan, self.base)['ok'])
        self.assertEqual(original, self.plan)

    def test_rejects_silent_copy_change(self):
        self.plan['captions'][1]['text'] = '即享专属福利'
        self.assertFalse(validate(self.plan, self.base)['ok'])

    def test_rejects_uninspected_and_untreated_text(self):
        for status in ('unknown', 'present'):
            with self.subTest(status=status):
                self.plan['assets'][0]['burned_text'] = status
                self.assertFalse(validate(self.plan, self.base)['ok'])

    def test_rejects_missing_cue(self):
        self.plan['captions'].pop()
        self.assertFalse(validate(self.plan, self.base)['ok'])

    def test_rejects_source_overrun(self):
        self.plan['shots'][0]['source_out'] = 20
        self.assertFalse(validate(self.plan, self.base)['ok'])

    def test_rejects_main_picture_gap(self):
        self.plan['shots'][0].update(start=1, source_in=3)
        self.assertFalse(validate(self.plan, self.base)['ok'])

    def test_rejects_double_speech(self):
        self.plan['assets'][0].update(audio_action='duck', audio_note='speech retained')
        self.plan['shots'][0]['volume'] = 0.2
        errors = validate(self.plan, self.base)['errors']
        self.assertTrue(any('Overlapping narration' in e for e in errors))

    def test_rejects_missing_media(self):
        self.plan['assets'][0]['path'] = 'missing.mp4'
        self.assertFalse(validate(self.plan, self.base)['ok'])

    def test_speed_and_still_image(self):
        self.plan['shots'][0].update(source_in=0, source_out=3, speed=0.5)
        self.assertTrue(validate(self.plan, self.base)['ok'])
        self.plan['assets'][0]['kind'] = 'image'
        self.plan['shots'][0] = {'asset_id': 'v', 'start': 0, 'end': 6}
        self.assertTrue(validate(self.plan, self.base)['ok'])

    def test_snapshot_does_not_select_or_overwrite(self):
        project = self.base / 'project'
        project.mkdir()
        old = {'id': 'same-id', 'tracks': [], 'materials': {}, 'name': 'old'}
        new = {**old, 'name': 'user-edit'}
        (project / 'draft_content.json').write_text(json.dumps(old))
        source = project / 'draft_info.json'
        source.write_text(json.dumps(new))
        raw = source.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        report = inspect_draft(project)
        self.assertIsNone(report['selected_candidate'])
        self.assertEqual(len(report['candidates']), 2)
        output = self.base / 'snapshot'
        manifest = snapshot(source, digest, output)
        self.assertEqual((output / source.name).read_bytes(), raw)
        self.assertEqual(source.read_bytes(), raw)
        self.assertEqual(json.loads((project / 'draft_content.json').read_text()), old)
        self.assertEqual(manifest['source_sha256'], digest)
        with self.assertRaises(ValueError):
            snapshot(source, digest, output)
        source.write_text(json.dumps({**new, 'name': 'edit-after-inspection'}))
        with self.assertRaises(ValueError):
            snapshot(source, digest, self.base / 'stale')
        self.assertFalse((self.base / 'stale').exists())

    def test_rejects_snapshot_inside_original(self):
        project = self.base / 'project'
        project.mkdir()
        source = project / 'draft_info.json'
        source.write_text(json.dumps({'id': 'x', 'tracks': [], 'materials': {}}))
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):
            snapshot(source, digest, project / 'snapshot')


if __name__ == '__main__':
    unittest.main()

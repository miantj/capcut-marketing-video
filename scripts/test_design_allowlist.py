#!/usr/bin/env python3
"""Allowlist + single-BGM gates from design-recipes / production rules."""
import tempfile
import unittest
from pathlib import Path

from validate_storyboard import validate


def _plan(base):
    (base / 'v.mp4').write_bytes(b'x')
    return {
        'version': 1, 'duration': 6, 'canvas': {'width': 720, 'height': 1280, 'fps': 30},
        'source_text': '夏装补货不用跑市场',
        'narration': {'mode': 'none'},
        'script': [
            {'id': 'a', 'text': '夏装补货', 'start': 0, 'end': 3, 'pause_after': 0},
            {'id': 'b', 'text': '不用跑市场', 'start': 3, 'end': 6, 'pause_after': 0},
        ],
        'assets': [{
            'id': 'v', 'path': str(base / 'v.mp4'), 'kind': 'video', 'duration': 10,
            'original_audio': 'speech', 'audio_action': 'mute',
            'burned_text': 'none', 'text_action': 'none', 'inspection': 'fixture',
        }],
        'shots': [{
            'asset_id': 'v', 'start': 0, 'end': 6, 'source_in': 0, 'source_out': 6, 'speed': 1,
            'cue_ids': ['a', 'b'], 'match_reason': 'fixture',
        }],
        'captions': [
            {
                'cue_ids': ['a'], 'start': 0, 'end': 3, 'text': '夏装补货', 'recipe': 'keyword-reveal',
                'visual': {'fontSize': 20, 'color': '#FFFFFF', 'x': 0, 'y': -0.5},
                'animation': {
                    'intro': '放大', 'outro': '缩小', 'intro_seconds': 0.5, 'outro_seconds': 0.5,
                    'purpose': 'hook',
                },
            },
            {
                'cue_ids': ['b'], 'start': 3, 'end': 6, 'text': '不用跑市场', 'recipe': 'benefit-tag',
                'visual': {'fontSize': 20, 'color': '#FFFFFF', 'x': 0, 'y': -0.5},
                'animation': {
                    'intro': '放大', 'outro': '缩小', 'intro_seconds': 0.5, 'outro_seconds': 0.5,
                    'purpose': 'benefit',
                },
            },
        ],
        'audio': [],
    }


class DesignAllowlistTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='allowlist-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.plan = _plan(self.base)

    def test_rejects_shrink_ii_without_user_quote(self):
        self.plan['captions'][0]['animation']['outro'] = '缩小 II'
        report = validate(self.plan, self.base)
        self.assertFalse(report['ok'])
        self.assertTrue(any('allowlist' in e for e in report['errors']))

    def test_animation_reason_does_not_bypass_allowlist(self):
        # animation_reason is for duration overrides only (delivery_steps).
        self.plan['captions'][0]['animation']['outro'] = '缩小 II'
        self.plan['style_exceptions'] = {'animation_reason': '用户要求出场 0.3 秒'}
        report = validate(self.plan, self.base)
        self.assertFalse(report['ok'])
        self.assertTrue(any('allowlist' in e for e in report['errors']))

    def test_user_quote_allows_extra_outro(self):
        self.plan['captions'][0]['animation']['outro'] = '缩小 II'
        self.plan['style_exceptions'] = {'animation_allowlist_reason': '用户要求出场用缩小 II'}
        self.assertTrue(validate(self.plan, self.base)['ok'])

    def test_rejects_mixed_bgm_assets(self):
        (self.base / 'm1.mp3').write_bytes(b'm')
        (self.base / 'm2.mp3').write_bytes(b'm')
        self.plan['assets'].extend([
            {'id': 'm1', 'path': str(self.base / 'm1.mp3'), 'kind': 'audio', 'duration': 10,
             'audio_kind': 'music', 'inspection': 'fixture'},
            {'id': 'm2', 'path': str(self.base / 'm2.mp3'), 'kind': 'audio', 'duration': 10,
             'audio_kind': 'music', 'inspection': 'fixture'},
        ])
        self.plan['audio'] = [
            {'asset_id': 'm1', 'role': 'bgm', 'volume': 0.2, 'start': 0, 'end': 3,
             'source_in': 0, 'source_out': 3, 'speed': 1},
            {'asset_id': 'm2', 'role': 'bgm', 'volume': 0.2, 'start': 3, 'end': 6,
             'source_in': 0, 'source_out': 3, 'speed': 1},
        ]
        report = validate(self.plan, self.base)
        self.assertFalse(report['ok'])
        self.assertTrue(any('mix multiple BGM' in e for e in report['errors']))


if __name__ == '__main__':
    unittest.main()

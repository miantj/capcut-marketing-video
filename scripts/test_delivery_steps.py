"""Real CLI compile/finish/install in a TemporaryDirectory; no user draft store is touched."""
import copy
import json
import subprocess
import unittest
from pathlib import Path

import delivery_steps
from test_workflow import WorkflowTests
from workflow import run
from delivery_steps import start, finish, install, verify, requirements, check_styles, read, write, compiled


class DeliveryTests(WorkflowTests):
    def test_display_caption_text_strips_punct(self):
        from delivery_steps import display_caption_text, CAPTION_SIDE_MARGIN_PX
        self.assertEqual(display_caption_text('选款最浪费时间的不是逛市场，'), '选款最浪费时间的不是逛市场')
        self.assertEqual(display_caption_text('热门档口进店就有人在挑。'), '热门档口进店就有人在挑')
        self.assertEqual(display_caption_text('a,b.c'), 'abc')
        self.assertEqual(display_caption_text(''), '')
        self.assertEqual(CAPTION_SIDE_MARGIN_PX, 20)

    def prepare_actual(self):
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'color=c=blue:s=72x128:r=30', '-t', '10', '-c:v', 'libx264',
                        str(self.base / 'video.mp4')], check=True, capture_output=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'sine=frequency=440:duration=6', str(self.base / 'voice.wav')],
                       check=True, capture_output=True)
        font = self.base / 'font.ttf'
        font.write_bytes(b'font-path fixture; not rendered or declared visually verified')
        self.plan['source_text'] = '夏装补货吉祥专属福利'
        self.plan.update(delivery='draft', narration=dict(mode='provided', timing='aligned', evidence='Synthetic test tone alignment only'))
        self.plan['script'][0].update(start=0, end=2.5)
        self.plan['script'][1].update(start=3, end=5.5)
        self.plan['audio'][0].update(volume=.8, cue_ids=['a', 'b'])
        for cap in self.plan['captions']:
            cap.update(visual=dict(fontSize=20, color='#FFFFFF', x=0, y=-.5, font=dict(path=str(font), id='fixture-font')),
                       animation=dict(intro='放大', outro='缩小', intro_seconds=.5, outro_seconds=.5, purpose='benefit'))
        self.plan['captions'][0]['keywords'] = ['补货']
        self.plan['captions'][1]['bubble'] = dict(text='福利', x=0, y=.5, width=.3, height=.15)
        resources = {}
        for name, kind in [('放大', 'in'), ('缩小', 'out')]:
            path = self.base / name
            path.mkdir()
            resources[name] = dict(path=str(path), name=name, id=name, resource_id=name, type=kind, material_type='text')
        self.resources = self.base / 'resources.json'
        write(self.resources, resources)
        start(self.base, 'create', 'draft', 'Synthetic isolated draft fixture, no native UI claims')
        self.source = self.base / 'storyboard.json'
        write(self.source, self.plan)
        self.run_dir = Path(run(self.source, self.base / 'builds', True)['run_dir'])

    def test_end_to_end_and_skips_cannot_pass(self):
        self.prepare_actual()
        before = verify(self.run_dir)
        self.assertFalse(before['ok'])
        with self.assertRaises((KeyError, ValueError)):
            install(self.run_dir, self.base / 'store')
        report = finish(self.run_dir, self.resources)
        self.assertTrue(report['ok'])
        self.assertFalse(report['native_ui_verified'])
        state = read(self.run_dir / 'delivery.json')
        finished = Path(state['finished_draft'])
        d = read(finished / 'draft_content.json')
        base = copy.deepcopy(d)
        refs = state['refs']
        body = next(s for t in d['tracks'] for s in t['segments'] if s['id'] == refs['caption-0'])
        body['extra_material_refs'] = []
        write(finished / 'draft_content.json', d)
        self.assertFalse(check_styles(finished, self.plan, refs, self.base)['ok'])
        write(finished / 'draft_content.json', base)
        d = copy.deepcopy(base)
        for t in d['tracks']:
            t['segments'] = [s for s in t['segments'] if s['id'] != refs['bubble-1']]
        write(finished / 'draft_content.json', d)
        self.assertFalse(check_styles(finished, self.plan, refs, self.base)['ok'])
        write(finished / 'draft_content.json', base)
        store = self.base / 'store'
        store.mkdir()
        write(store / 'root_meta_info.json', {'all_draft_store': []})
        result = install(self.run_dir, store)
        self.assertTrue(result['ok'])
        self.assertTrue(all(Path(x['file_Path']).is_relative_to(result['draft']) for g in read(Path(result['draft']) / 'draft_meta_info.json')['draft_materials'] for x in g.get('value', []) if x.get('file_Path')))
        # Structural completion must not fake a visual/audio review.
        report = verify(self.run_dir)
        self.assertFalse(report['ok'])
        self.assertEqual(report['next_step'], 'visual_review')
        before = (store / 'root_meta_info.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'already exists'):
            install(self.run_dir, store)
        self.assertEqual(before, (store / 'root_meta_info.json').read_bytes())
        write(store / 'root_meta_info.json', {'all_draft_store': []})
        report = verify(self.run_dir)
        self.assertEqual(report['next_step'], 'installation')
        # A manually written passed flag cannot override a missing homepage entry.
        state = read(self.run_dir / 'delivery.json')
        state.update(installed='passed', native_preview='passed', native_finishing='passed')
        write(self.run_dir / 'delivery.json', state)
        self.assertFalse(verify(self.run_dir)['ok'])
        # doctor or registration results are not compile provenance.
        result = read(self.run_dir / 'compile-result.json')
        result['argv'] = ['capcut', 'doctor']
        write(self.run_dir / 'compile-result.json', result)
        with self.assertRaisesRegex(ValueError, 'compile command'):
            compiled(self.run_dir)

    def test_missing_design_and_missing_narration_block_build(self):
        self.prepare_actual()
        p = copy.deepcopy(self.plan)
        p['captions'][1].pop('bubble')
        with self.assertRaisesRegex(ValueError, 'bubble'):
            requirements(p, self.base)
        p = copy.deepcopy(self.plan)
        p['captions'][0]['animation']['intro_seconds'] = .1
        with self.assertRaisesRegex(ValueError, '0.5s'):
            requirements(p, self.base)
        p = copy.deepcopy(self.plan)
        p.pop('narration')
        write(self.source, p)
        with self.assertRaisesRegex(ValueError, 'explicit narration'):
            run(self.source, self.base / 'builds2', True)

    def test_finish_rejects_animation_without_path(self):
        self.prepare_actual()
        broken = read(self.resources)
        broken['放大'].pop('path')
        write(self.resources, broken)
        with self.assertRaisesRegex(ValueError, 'animation resource'):
            finish(self.run_dir, self.resources)

    def test_style_gate_rejects_hidden_caption_and_missing_video(self):
        self.prepare_actual()
        finish(self.run_dir, self.resources)
        state = read(self.run_dir / 'delivery.json')
        draft = Path(state['finished_draft'])
        original = read(draft / 'draft_content.json')
        hidden = copy.deepcopy(original)
        caption = next(s for t in hidden['tracks'] for s in t['segments'] if s['id'] == state['refs']['caption-0'])
        caption['visible'] = False
        caption.setdefault('clip', {})['alpha'] = 0
        write(draft / 'draft_content.json', hidden)
        self.assertFalse(check_styles(draft, self.plan, state['refs'], self.base)['ok'])
        no_video = copy.deepcopy(original)
        for track in no_video['tracks']:
            if track.get('type') == 'video':
                track['segments'] = []
        write(draft / 'draft_content.json', no_video)
        self.assertFalse(check_styles(draft, self.plan, state['refs'], self.base)['ok'])

    def test_install_retry_after_register_failure(self):
        self.prepare_actual()
        finish(self.run_dir, self.resources)
        store = self.base / 'store'
        store.mkdir()
        write(store / 'root_meta_info.json', {'all_draft_store': []})
        original_command = delivery_steps.command
        def flaky(args, log):
            if '--apply' in args:
                raise ValueError('simulated temporary register failure')
            return {'project_dir': args[2], 'store_root': args[-1]}
        delivery_steps.command = flaky
        try:
            with self.assertRaisesRegex(ValueError, 'temporary register'):
                install(self.run_dir, store)
        finally:
            delivery_steps.command = original_command
        state = read(self.run_dir / 'delivery.json')
        name = read(Path(state['finished_draft']) / 'draft_content.json')['name']
        self.assertTrue((store / name / '.capcut-install-marker.json').is_file())
        self.assertTrue(install(self.run_dir, store)['ok'])


if __name__ == '__main__':
    unittest.main()

import json
import os
import tempfile
import unittest
from pathlib import Path

from workbench.packaging import replace_paths
from workbench.caption_style import caption_plan
from workbench.media import script_cues
from workbench.skill_timing import skill_module
from workbench.subtitles import rich_text, write_ass


class CaptionStyleTests(unittest.TestCase):
    def test_skill_display_and_timing_preserve_source(self):
        source = '服装圈混5年才知道的潜规则，夏装还能卖两个月。'
        font = {'path':str(Path(os.environ['LOCALAPPDATA'])/'JianyingPro/User Data/Resources/Font/悠然体.ttf'), 'id':'6740436145831678467'}
        cues = script_cues(source)
        caps = caption_plan(cues,font,1080,1920)
        expected = skill_module('delivery_steps').display_caption_text(source)
        actual = ''.join(c['text'] for c in caps)
        self.assertEqual(actual,expected)
        self.assertEqual(''.join(c['text'] for c in cues),source)
        self.assertTrue(all('\n' not in c['text'] for c in caps))
        self.assertTrue(all(c['animation']['intro_seconds'] == .5 and c['animation']['outro_seconds'] == .5 for c in caps))
        self.assertEqual(caps[0]['text'],'服装圈混5年才知道的潜规则')
        self.assertEqual(caps[0]['visual']['fontSize'], 20)
        self.assertEqual(caps[0]['visual']['y'], -.46)
        self.assertEqual(caps[0]['bubble']['color'], '#C9D7EA')
        self.assertEqual(caps[0]['animation']['intro'], '波浪弹入')
        promo = caption_plan(cues, font, 1080, 1920, 'promo')
        self.assertEqual(promo[0]['visual']['fontSize'], 22)
        self.assertEqual(promo[0]['visual']['y'], -.58)
        self.assertEqual(promo[0]['bubble']['color'], '#FF8A4A')
        self.assertEqual(promo[0]['animation']['intro'], '放大')
        self.assertIn('潜规则',caps[0]['keywords'])
        self.assertIn('bubble',caps[0])

    def test_keeps_lexicon_keywords_without_prewrapping(self):
        font = {'path':str(Path(os.environ['LOCALAPPDATA'])/'JianyingPro/User Data/Resources/Font/悠然体.ttf'), 'id':'6740436145831678467'}
        caps = caption_plan(script_cues('一二三四五六七八九十甲乙潜规则还有更多说明文字。'), font, 1080, 1920)
        self.assertTrue(all('\n' not in c['text'] for c in caps))
        self.assertTrue(any('潜规则' in c['keywords'] for c in caps))
        later = caption_plan(script_cues('这是一段没有词库命中的说明。后面才提到潜规则。'), font, 1080, 1920)
        self.assertEqual(later[0]['keywords'], [])
        self.assertIn('潜规则', later[1]['keywords'])
        fallback = caption_plan(script_cues('这是一段普通说明文字用于测试。'), font, 1080, 1920)
        self.assertEqual(fallback[0]['keywords'], [fallback[0]['text'][:2]])
        self.assertIn('bubble', fallback[0])

    def test_templates_change_layout_motion_and_bubbles(self):
        font = {'path':str(Path(os.environ['LOCALAPPDATA'])/'JianyingPro/User Data/Resources/Font/悠然体.ttf'), 'id':'6740436145831678467'}
        cues = script_cues('潜规则在市场。一手APP能补货。低价还包邮。锁定专属优惠。')
        new = caption_plan(cues, font, 1080, 1920, 'new')
        selling = caption_plan(cues, font, 1080, 1920, 'selling')
        promo = caption_plan(cues, font, 1080, 1920, 'promo')
        self.assertEqual(sum('bubble' in c for c in new), 1)
        self.assertGreaterEqual(sum('bubble' in c for c in selling), 2)
        self.assertEqual({c['bubble']['color'] for c in selling if 'bubble' in c}, {'#FFE263'})
        self.assertTrue(all(c['animation']['intro'] == '放大' for c in promo))
        self.assertLess(promo[0]['visual']['y'], new[0]['visual']['y'])
        self.assertNotEqual(new[0]['bubble']['y'], selling[0]['bubble']['y'])

    def test_youran_font_id_comes_from_bootstrap(self):
        from workbench.caption_style import youran_font_id
        from workbench.media import ProductionError
        self.assertEqual(youran_font_id({'悠然体': {'id': 'local-id'}}), 'local-id')
        self.assertEqual(youran_font_id({'HYYouRanTiJ': {'resource_id': 'from-enums'}}), 'from-enums')
        with self.assertRaises(ProductionError):
            youran_font_id({'其他字体': {'id': 'x'}})

    def test_embedded_rich_font_paths_are_portable(self):
        font = Path(os.environ['LOCALAPPDATA'])/'JianyingPro/User Data/Resources/Font/悠然体.ttf'
        raw = {'font_path':str(font),'content':json.dumps({'text':'文案','styles':[{'font':{'path':str(font)}}]})}
        converted = replace_paths(raw,Path('D:/example/draft'),Path('D:/example'))
        self.assertEqual(converted['font_path'],'__JY_FONT_ROOT__/悠然体.ttf')
        self.assertEqual(json.loads(converted['content'])['styles'][0]['font']['path'],'__JY_FONT_ROOT__/悠然体.ttf')

    def test_preview_preserves_native_keyword_ranges(self):
        content = {'text':'新品上新','styles':[
            {'range':[0,2],'bold':True,'fill':{'content':{'solid':{'color':[1,.886,.388]}}}},
            {'range':[2,4],'bold':False,'fill':{'content':{'solid':{'color':[1,1,1]}}}}]}
        output = rich_text(content)
        self.assertIn('\\c&H63E2FF&\\b1}新品',output)
        self.assertIn('\\c&HFFFFFF&\\b0}上新',output)

    def test_preview_resolution_and_static_scale(self):
        document = {'materials': {'texts': [{'id': 'text', 'font_size': 24,
            'content': json.dumps({'text': '测试', 'styles': [{'range': [0, 2]}]})}]},
            'tracks': [{'type': 'text', 'segments': [{'material_id': 'text',
                'target_timerange': {'start': 0, 'duration': 3000000},
                'clip': {'scale': {'x': 1.25, 'y': .8}}}]}]}
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)/'subtitle.ass'
            for width, height, pixels in [(540,960,72), (1080,1920,144), (960,540,40.5)]:
                report = write_ass(document, width, height, target)
                ass = target.read_text('utf-8-sig')
                self.assertIn('\\fs' + str(pixels), ass)
                self.assertIn(f'Style: Body,HYYouRanTiJ,{pixels:g},', ass)
                self.assertIn('\\fscx125\\fscy80', ass)
                self.assertIn('\\fscx112.5\\fscy72', ass)
                self.assertIn('calibrated', report['font_size_mode'])

    def test_preview_bubble_uses_native_background_size(self):
        document = {'materials': {'texts': [{'id': 'bubble', 'font_size': 23,
            'background_width': 0.1814814814814815, 'background_height': 0.0546875,
            'background_color': '#FF8A4A',
            'content': json.dumps({'text': '选款', 'styles': [{'range': [0, 2]}]})}]},
            'tracks': [{'type': 'text', 'name': '气泡', 'segments': [{'material_id': 'bubble',
                'target_timerange': {'start': 0, 'duration': 3000000},
                'clip': {'transform': {'x': 0, 'y': -.3}}}]}]}
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)/'subtitle.ass'
            write_ass(document, 540, 960, target)
            ass = target.read_text('utf-8-sig')
            self.assertIn('\\fs69', ass)
            self.assertIn('\\c&H4A8AFF&', ass)
            self.assertIn('m 181 572', ass)
            self.assertIn('l 359 572', ass)

    def test_preview_wraps_long_captions_to_native_line_width(self):
        document = {'materials': {'texts': [{'id': 'text', 'font_size': 25, 'line_max_width': 0.963,
            'font_path': str(Path(os.environ['LOCALAPPDATA'])/'JianyingPro/User Data/Resources/Font/悠然体.ttf'),
            'content': json.dumps({'text': '款式很多但找到合适的款并不容易', 'styles': [{'range': [0, 16]}]})}]},
            'tracks': [{'type': 'text', 'segments': [{'material_id': 'text',
                'target_timerange': {'start': 0, 'duration': 3000000},
                'clip': {'transform': {'x': 0, 'y': -.52}}}]}]}
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)/'subtitle.ass'
            write_ass(document, 540, 960, target)
            ass = target.read_text('utf-8-sig')
            self.assertIn('\\N', ass)
            self.assertGreaterEqual(ass.count('\\N'), 2)

import unittest

from workbench.compat import align_render_frames
from workbench.media import ProductionError, validate_preview


class RenderTimingTests(unittest.TestCase):
    def test_fractional_cuts_use_cumulative_frame_boundaries(self):
        document = {'tracks': [{'type': 'video', 'segments': [
            {'target_timerange': {'start': 0, 'duration': 1910000}},
            {'target_timerange': {'start': 1910000, 'duration': 2923333}}
        ]}]}
        graph = '[0:v]trim=duration=1.91,fps=30[v0];[1:v]trim=duration=2.923,fps=30[v1];[v0][v1]concat=n=2:v=1:a=0[vout]'
        aligned = align_render_frames(graph, document, 30)
        self.assertIn('trim=end_frame=57', aligned)
        self.assertIn('trim=end_frame=88', aligned)
        self.assertEqual(aligned.count('stop_duration=0.066666667'), 2)
        self.assertTrue(aligned.endswith('[v0][v1]concat=n=2:v=1:a=0[vout]'))

    def test_validation_does_not_relax_tolerance(self):
        with self.assertRaisesRegex(ProductionError, '58.83.*58.40'):
            validate_preview({'duration':58.4,'video':True,'audio':True},58.833333)
        with self.assertRaisesRegex(ProductionError, '背景音乐音轨'):
            validate_preview({'duration':58.83,'video':True,'audio':False},58.833333)
        validate_preview({'duration':58.84,'video':True,'audio':True},58.833333)


if __name__ == '__main__':
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from workbench.caption_style import compile_and_finish
from workbench.media import ProductionError


class CompileConfigTests(unittest.TestCase):
    def test_configured_cli_and_failed_compile_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            build = folder / 'build'
            build.mkdir()
            skill = Mock()
            settings = SimpleNamespace(capcut=['custom-node', 'custom-cli.js'])
            completed = SimpleNamespace(returncode=1, stdout='', stderr='compile failed')
            with patch('workbench.caption_style.skill_module', return_value=skill), \
                 patch('workbench.caption_style.run', return_value=completed) as run:
                with self.assertRaises(ProductionError):
                    compile_and_finish(settings, folder, build, {}, {}, folder/'resources.json', folder/'log')
            self.assertEqual(run.call_args.args[0][:3], ['custom-node', 'custom-cli.js', 'compile'])
            evidence = skill.write.call_args.args[1]
            self.assertEqual(evidence['returncode'], 1)
            self.assertEqual(evidence['executed_argv'][:2], settings.capcut)
            skill.finish.assert_not_called()

    def test_skill_requirement_errors_are_user_visible(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            build = folder / 'build'
            build.mkdir()
            skill = Mock()
            skill.requirements.side_effect = ValueError('Keyword not present in caption text')
            settings = SimpleNamespace(capcut=['custom-node', 'custom-cli.js'])
            with patch('workbench.caption_style.skill_module', return_value=skill), \
                 patch('workbench.caption_style.run') as run:
                with self.assertRaisesRegex(ProductionError, 'Keyword not present'):
                    compile_and_finish(settings, folder, build, {}, {}, folder/'resources.json', folder/'log')
            run.assert_not_called()

    def test_finish_sync_allows_isolated_write_while_editor_is_open(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            build = folder / 'build'
            build.mkdir()
            finished = folder / 'finished'
            finished.mkdir()
            draft_file = folder / 'draft' / 'draft_content.json'
            draft_file.parent.mkdir()
            draft_file.write_text('{}', encoding='utf-8')
            skill = Mock()
            skill.finish.return_value = {'draft': str(finished)}
            skill.sha.return_value = 'abc'
            skill.read.return_value = {'draft_materials': []}
            settings = SimpleNamespace(capcut=['custom-node', 'custom-cli.js'])
            compiled = SimpleNamespace(
                returncode=0, stderr='',
                stdout=json.dumps({'file_path': str(draft_file), 'refs': {}}))
            ok = SimpleNamespace(returncode=0, stdout='{}', stderr='')
            with patch('workbench.caption_style.skill_module', return_value=skill), \
                 patch('workbench.caption_style.run', side_effect=[compiled, ok, ok]) as run:
                compile_and_finish(settings, folder, build, {}, {}, folder/'resources.json', folder/'log')
            argv = run.call_args_list[-1].args[0]
            self.assertEqual(argv[2], 'sync-timelines')
            self.assertIn('--force-write', argv)

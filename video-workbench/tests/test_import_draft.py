import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench.config import ROOT
from workbench.packaging import package_draft

IMPORTER = ROOT / 'scripts/Import-Draft.command'


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


class MacImportTests(unittest.TestCase):
    def test_package_includes_mac_importer(self):
        with tempfile.TemporaryDirectory() as temp:
            draft = Path(temp) / 'draft'
            assets = draft / 'assets'
            assets.mkdir(parents=True)
            clip = assets / 'v.mp4'
            clip.write_bytes(b'fake')
            (draft / 'draft_content.json').write_text(json.dumps({
                'id': 'pack-1', 'name': '打包',
                'materials': {'texts': [], 'material_animations': [], 'videos': [{'path': str(clip)}]},
            }), encoding='utf-8')
            dest = Path(temp) / 'out.zip'
            package_draft(draft, dest, '标题', 1)
            with zipfile.ZipFile(dest) as archive:
                names = archive.namelist()
                self.assertIn('Import-Draft.command', names)
                self.assertIn('Import-Draft.ps1', names)
                mode = archive.getinfo('Import-Draft.command').external_attr >> 16
                self.assertEqual(mode & 0o777, 0o755)
                note = archive.read('使用说明.txt').decode('utf-8-sig')
                self.assertIn('Import-Draft.command', note)

    def test_command_registers_mac_draft(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package, store, fonts, effects = self._package(root)
            result = self._run(package, store, fonts, effects)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            draft = (store / 'workbench-mac-1').resolve()
            self.assertTrue((draft / 'draft_info.json').is_file())
            content = json.loads((draft / 'draft_content.json').read_text(encoding='utf-8'))
            self.assertEqual(content['materials']['videos'][0]['path'], str(draft / 'assets/v.mp4'))
            self.assertEqual(content['materials']['texts'][0]['font_path'], str((fonts / '悠然体.ttf').resolve()))
            self.assertEqual(content['materials']['material_animations'][0]['animations'][0]['path'], str((effects / '1/effect.json').resolve()))
            info = json.loads((draft / 'draft_info.json').read_text(encoding='utf-8'))
            self.assertEqual(info, content)
            meta = json.loads((draft / 'draft_meta_info.json').read_text(encoding='utf-8'))
            self.assertEqual(meta['draft_json_file'], str(draft / 'draft_info.json'))
            self.assertEqual(meta['draft_fold_path'], str(draft))
            self.assertEqual(meta['draft_cover'], str(draft / 'draft_cover.jpg'))
            index = json.loads((store / 'root_meta_info.json').read_text(encoding='utf-8'))
            self.assertEqual(index['all_draft_store'][0]['draft_id'], 'mac-1')
            self.assertTrue(list(store.glob('root_meta_info.before-workbench-*.json')))
            again = self._run(package, store, fonts, effects)
            self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
            self.assertIn('已经导入', again.stdout)
            self.assertEqual(len(json.loads((store / 'root_meta_info.json').read_text(encoding='utf-8'))['all_draft_store']), 1)

    def test_missing_font_does_not_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package, store, fonts, effects = self._package(root)
            (fonts / '悠然体.ttf').unlink()
            result = self._run(package, store, fonts, effects)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('缺少资源', result.stdout + result.stderr)
            self.assertFalse((store / 'workbench-mac-1').exists())

    def _package(self, root):
        package = root / 'pkg'
        draft = package / 'draft'
        assets = draft / 'assets'
        assets.mkdir(parents=True)
        (assets / 'v.mp4').write_bytes(b'fake')
        (draft / 'draft_cover.jpg').write_bytes(b'jpg')
        (draft / 'draft_content.json').write_text(json.dumps({
            'id': 'mac-1', 'name': 'Mac草稿',
            'materials': {
                'videos': [{'path': '__DRAFT_ROOT__/assets/v.mp4'}],
                'texts': [{'font_path': '__JY_FONT_ROOT__/悠然体.ttf'}],
                'material_animations': [{'animations': [{'name': '放大', 'path': '__JY_EFFECT_ROOT__/1/effect.json'}]}],
            },
        }), encoding='utf-8')
        (draft / 'draft_meta_info.json').write_text(json.dumps({
            'draft_id': 'mac-1', 'draft_name': 'Mac草稿', 'draft_cover': 'draft_cover.jpg',
        }), encoding='utf-8')
        shutil.copy2(IMPORTER, package / 'Import-Draft.command')
        (package / 'Import-Draft.command').chmod(0o755)
        files = {}
        for file in package.rglob('*'):
            if file.is_file() and file.name not in {'Import-Draft.command', 'Import-Draft.ps1', '使用说明.txt'}:
                files[file.relative_to(package).as_posix()] = digest(file)
        (package / 'manifest.json').write_text(json.dumps({
            'draft_id': 'mac-1', 'title': 'Mac草稿',
            'native_resources': [
                {'kind': 'font', 'name': '悠然体', 'relative_path': '悠然体.ttf'},
                {'kind': 'effect', 'name': '放大', 'relative_path': '1/effect.json'},
            ],
            'files': files,
        }), encoding='utf-8')
        store = root / 'store'
        store.mkdir()
        (store / 'root_meta_info.json').write_text(json.dumps({
            'all_draft_store': [], 'draft_ids': 0, 'root_path': str(store),
        }), encoding='utf-8')
        fonts = root / 'fonts'
        fonts.mkdir()
        (fonts / '悠然体.ttf').write_bytes(b'font')
        effects = root / 'effects/1'
        effects.mkdir(parents=True)
        (effects / 'effect.json').write_text('{}', encoding='utf-8')
        return package, store, fonts, root / 'effects'

    def _run(self, package, store, fonts, effects):
        env = os.environ.copy()
        env.update({
            'VIDEO_IMPORT_NO_PAUSE': '1',
            'VIDEO_IMPORT_ALLOW_OPEN': '1',
            'VIDEO_IMPORT_FONT_ROOT': str(fonts),
            'VIDEO_IMPORT_EFFECT_ROOT': str(effects),
        })
        return subprocess.run(
            ['bash', str(package / 'Import-Draft.command'), '--store', str(store)],
            cwd=package, env=env, capture_output=True, text=True)


if __name__ == '__main__':
    unittest.main()

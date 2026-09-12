import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path

from .config import ROOT
from .media import ProductionError


def walk_strings(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_strings(item)
    elif isinstance(value, str):
        yield value


def replace_paths(value, draft, store):
    if isinstance(value, dict):
        result = {}
        for key,item in value.items():
            if key == 'content' and isinstance(item,str):
                try:
                    rich = json.loads(item)
                    if isinstance(rich,dict) and 'styles' in rich and 'text' in rich:
                        result[key] = json.dumps(replace_paths(rich,draft,store),ensure_ascii=False)
                        continue
                except ValueError:
                    pass
            result[key] = replace_paths(item,draft,store)
        return result
    if isinstance(value, list):
        return [replace_paths(item, draft, store) for item in value]
    if isinstance(value, str):
        # Preserve ordinary user text. Only replace exact absolute path prefixes.
        jy = Path(os.environ.get('LOCALAPPDATA',''))/'JianyingPro/User Data'
        mappings = ((draft,'__DRAFT_ROOT__'), (store,'__STORE_ROOT__'),
                    (jy/'Resources/Font','__JY_FONT_ROOT__'),(jy/'Cache/effect','__JY_EFFECT_ROOT__'))
        for root,target in mappings:
            source = str(root)
            normalized = value.replace('\\','/')
            if normalized == root.as_posix() or normalized.startswith(root.as_posix()+'/'):
                return target + normalized[len(root.as_posix()):]
            if value == source or value.startswith(source + '\\') or value.startswith(source + '/'):
                return target + value[len(source):].replace('\\', '/')
    return value


def package_draft(draft, destination, title, duration):
    content = json.loads((draft / 'draft_content.json').read_text('utf-8-sig'))
    # Verify all referenced media, including duplicated timeline mirrors, stay in the package.
    for file in draft.rglob('*.json'):
        document = json.loads(file.read_text('utf-8-sig'))
        for value in walk_strings(document):
            if Path(value).suffix.lower() not in {'.mp4', '.mov', '.m4v', '.webm', '.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac'}:
                continue
            if not Path(value).is_absolute():
                continue
            path = Path(value).resolve()
            if not path.is_relative_to(draft.resolve()) or not path.is_file():
                raise ProductionError('草稿仍引用包外素材，已停止交付。')
    stage = destination.parent / 'portable'
    stage.mkdir()
    (stage / 'draft').mkdir()
    for file in draft.rglob('*'):
        if not file.is_file() or file.suffix == '.bak' or '.bak.' in file.name or '.snapshots' in file.parts:
            continue
        target = stage / 'draft' / file.relative_to(draft)
        target.parent.mkdir(parents=True, exist_ok=True)
        if file.suffix == '.json' or file.name == 'template-2.tmp':
            try:
                document = json.loads(file.read_text('utf-8-sig'))
            except (ValueError, UnicodeError):
                raise ProductionError('草稿镜像无法读取，已停止打包。') from None
            target.write_text(json.dumps(replace_paths(document, draft, draft.parent), ensure_ascii=False), 'utf-8')
        else:
            shutil.copy2(file, target)
    shutil.copy2(ROOT / 'scripts/Import-Draft.ps1', stage / 'Import-Draft.ps1')
    (stage / '使用说明.txt').write_text(
        f'{title}\n\n1. 将 ZIP 完整解压到本机文件夹（不要直接在压缩包中运行）。\n'
        '2. 保存并退出剪映，双击 Import-Draft.ps1。窗口会停住显示结果，看完再关闭。\n'
        '   若提示已经导入，直接打开剪映查找草稿即可。\n'
        '3. 重新打开剪映，在首页查找草稿。字幕、镜头和音乐分别可编辑。\n'
        '如果电脑策略禁止运行脚本，请联系管理员，不要自行关闭安全策略。\n\n'
        '兼容范围：Windows 剪映桌面版。不同剪映版本需实际打开验收；不支持承诺手机端导入。\n'
        '页面视频为近似预览，字体、动画和布局可能与剪映不同；正式使用前请在剪映检查并导出。\n'
        '字体及原生文字动画使用目标电脑自己的剪映资源，不随包重新分发。\n'
        '导入前请在目标剪映使用悠然体，并下载“放大、波浪弹入、波浪弹出”文字动画。\n'
        '此版本无自动配音。原素材音轨静音，只保留提供的背景音乐。\n', 'utf-8-sig')
    manifest = {'version': 1, 'draft_id': content['id'], 'title': title, 'duration': duration,
                'preview': 'approximate', 'native_verified': False, 'files': {}, 'native_resources':[]}
    jy = Path(os.environ.get('LOCALAPPDATA',''))/'JianyingPro/User Data'
    seen = set()
    for mat in content.get('materials',{}).get('texts',[]):
        path = mat.get('font_path')
        if path and path not in seen:
            seen.add(path)
            manifest['native_resources'].append({'kind':'font','name':'悠然体',
                'relative_path':Path(path).relative_to(jy/'Resources/Font').as_posix()})
    for mat in content.get('materials',{}).get('material_animations',[]):
        for animation in mat.get('animations',[]):
            path = animation.get('path')
            if path and path not in seen:
                seen.add(path)
                manifest['native_resources'].append({'kind':'effect','name':animation['name'],
                    'relative_path':Path(path).relative_to(jy/'Cache/effect').as_posix()})
    for file in stage.rglob('*'):
        if file.is_file():
            with file.open('rb') as source:
                manifest['files'][file.relative_to(stage).as_posix()] = hashlib.file_digest(source, 'sha256').hexdigest()
    (stage / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), 'utf-8')
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for file in stage.rglob('*'):
            if file.is_file():
                archive.write(file, file.relative_to(stage).as_posix())
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip():
            raise ProductionError('草稿压缩包校验失败。')
    return manifest

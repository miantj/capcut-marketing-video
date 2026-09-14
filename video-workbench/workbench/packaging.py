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
        for root, target in path_roots(draft, store):
            source = str(root)
            normalized = value.replace('\\', '/')
            posix = root.as_posix()
            if posix and (normalized == posix or normalized.startswith(posix + '/')):
                return target + normalized[len(posix):]
            if value == source or value.startswith(source + '\\') or value.startswith(source + '/'):
                return target + value[len(source):].replace('\\', '/')
    return value


def path_roots(draft, store):
    home = Path.home()
    jy = Path(os.environ.get('LOCALAPPDATA', '')) / 'JianyingPro/User Data'
    mac = home / 'Movies/JianyingPro/User Data'
    container = home / 'Library/Containers/com.lemon.lvpro/Data/Movies/JianyingPro/User Data'
    capcut = home / 'Movies/CapCut/User Data'
    pairs = (
        (draft, '__DRAFT_ROOT__'),
        (store, '__STORE_ROOT__'),
        (jy / 'Resources/Font', '__JY_FONT_ROOT__'),
        (jy / 'Cache/effect', '__JY_EFFECT_ROOT__'),
        (mac / 'Resources/Font', '__JY_FONT_ROOT__'),
        (mac / 'Cache/effect', '__JY_EFFECT_ROOT__'),
        (container / 'Resources/Font', '__JY_FONT_ROOT__'),
        (container / 'Cache/effect', '__JY_EFFECT_ROOT__'),
        (capcut / 'Resources/Font', '__JY_FONT_ROOT__'),
        (capcut / 'Cache/effect', '__JY_EFFECT_ROOT__'),
        (Path('/Applications/VideoFusion-macOS.app/Contents/Resources/Font'), '__JY_FONT_ROOT__'),
    )
    return sorted(pairs, key=lambda item: len(item[0].as_posix()), reverse=True)


def write_zip_member(archive, file, arcname):
    if arcname != 'Import-Draft.command':
        archive.write(file, arcname)
        return
    info = zipfile.ZipInfo(arcname)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100755 << 16
    archive.writestr(info, file.read_bytes())


def native_relative(path, kind):
    path = Path(path)
    home = Path.home()
    local = Path(os.environ.get('LOCALAPPDATA', '')) / 'JianyingPro/User Data'
    if kind == 'font':
        roots = (
            local / 'Resources/Font',
            home / 'Movies/JianyingPro/User Data/Resources/Font',
            home / 'Library/Containers/com.lemon.lvpro/Data/Movies/JianyingPro/User Data/Resources/Font',
            Path('/Applications/VideoFusion-macOS.app/Contents/Resources/Font'),
        )
    else:
        roots = (
            local / 'Cache/effect',
            home / 'Movies/JianyingPro/User Data/Cache/effect',
            home / 'Library/Containers/com.lemon.lvpro/Data/Movies/JianyingPro/User Data/Cache/effect',
        )
    for root in roots:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            continue
    return path.name


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
    if stage.exists():
        shutil.rmtree(stage)
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
    command = stage / 'Import-Draft.command'
    shutil.copy2(ROOT / 'scripts/Import-Draft.command', command)
    command.chmod(0o755)
    (stage / '使用说明.txt').write_text(
        f'{title}\n\n1. 将 ZIP 完整解压到本机文件夹（不要直接在压缩包中运行）。\n'
        '2. 保存并退出剪映。\n'
        '   Mac：双击 Import-Draft.command。若提示无法打开，右键该文件选择打开。\n'
        '   Windows：双击 Import-Draft.ps1。窗口会停住显示结果，看完再关闭。\n'
        '   若提示已经导入，直接打开剪映查找草稿即可。\n'
        '3. 重新打开剪映，在首页查找草稿。字幕、镜头和音乐分别可编辑。\n'
        '自定义草稿库：Mac 执行 ./Import-Draft.command --store \'路径\'；'
        'Windows 执行 .\\Import-Draft.ps1 -Store \'路径\'。\n'
        '如果电脑策略禁止运行脚本，请联系管理员，不要自行关闭安全策略。\n\n'
        '兼容范围：Windows / macOS 剪映桌面版一键导入。\n'
        '页面视频为近似预览，字体、动画和布局可能与剪映不同；正式使用前请在剪映检查并导出。\n'
        '字体及原生文字动画使用目标电脑自己的剪映资源，不随包重新分发。\n'
        '导入前请在目标剪映使用悠然体，并下载“放大、波浪弹入、波浪弹出”文字动画。\n'
        '原素材音轨静音。启用火山口播的任务含独立 AI 配音轨，未启用时仅含背景音乐。\n', 'utf-8-sig')
    manifest = {'version': 1, 'draft_id': content['id'], 'title': title, 'duration': duration,
                'preview': 'approximate', 'native_verified': False, 'files': {}, 'native_resources':[]}
    seen = set()
    for mat in content.get('materials',{}).get('texts',[]):
        path = mat.get('font_path')
        if path and path not in seen:
            seen.add(path)
            manifest['native_resources'].append({'kind':'font','name':'悠然体',
                'relative_path':native_relative(path, 'font')})
    for mat in content.get('materials',{}).get('material_animations',[]):
        for animation in mat.get('animations',[]):
            path = animation.get('path')
            if path and path not in seen:
                seen.add(path)
                manifest['native_resources'].append({'kind':'effect','name':animation['name'],
                    'relative_path':native_relative(path, 'effect')})
    for file in stage.rglob('*'):
        if file.is_file():
            with file.open('rb') as source:
                manifest['files'][file.relative_to(stage).as_posix()] = hashlib.file_digest(source, 'sha256').hexdigest()
    (stage / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), 'utf-8')
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for file in stage.rglob('*'):
            if file.is_file():
                write_zip_member(archive, file, file.relative_to(stage).as_posix())
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip():
            raise ProductionError('草稿压缩包校验失败。')
    return manifest

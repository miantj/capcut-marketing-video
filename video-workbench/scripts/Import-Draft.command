#!/bin/bash
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "需要 python3 才能导入草稿。"
  read -r _
  exit 1
fi
export PYTHONUTF8=1
exec python3 - "$@" <<'PY'
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

SKIP = {'Import-Draft.ps1', 'Import-Draft.command', '使用说明.txt'}


def die(message):
    raise SystemExit('导入失败：' + message)


def pause():
    if os.environ.get('VIDEO_IMPORT_NO_PAUSE'):
        return
    try:
        input('\n按 Enter 关闭窗口')
    except EOFError:
        pass


def json_escape(value):
    return json.dumps(str(value), ensure_ascii=False)[1:-1]


def default_store():
    home = Path.home()
    candidates = [
        home / 'Movies/JianyingPro/User Data/Projects/com.lveditor.draft',
        home / 'Library/Containers/com.lemon.lvpro/Data/Movies/JianyingPro/User Data/Projects/com.lveditor.draft',
        home / 'Movies/CapCut/User Data/Projects/com.lveditor.draft',
    ]
    for path in candidates:
        if (path / 'root_meta_info.json').is_file():
            return path.resolve()
    return candidates[0]


def resource_roots(kind):
    env = os.environ.get('VIDEO_IMPORT_FONT_ROOT' if kind == 'font' else 'VIDEO_IMPORT_EFFECT_ROOT')
    if env:
        return [Path(env).expanduser().resolve()]
    home = Path.home()
    if kind == 'font':
        return [
            home / 'Movies/JianyingPro/User Data/Resources/Font',
            Path('/Applications/VideoFusion-macOS.app/Contents/Resources/Font'),
            home / 'Library/Containers/com.lemon.lvpro/Data/Movies/JianyingPro/User Data/Resources/Font',
            home / 'Movies/CapCut/User Data/Resources/Font',
        ]
    return [
        home / 'Movies/JianyingPro/User Data/Cache/effect',
        home / 'Library/Containers/com.lemon.lvpro/Data/Movies/JianyingPro/User Data/Cache/effect',
        home / 'Movies/CapCut/User Data/Cache/effect',
    ]


def first_existing(relative, kind):
    if not relative or Path(relative).is_absolute():
        return None, None
    for root in resource_roots(kind):
        root = root.resolve()
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            continue
        if path.exists():
            return root, path
    return None, None


def editor_running():
    if os.environ.get('VIDEO_IMPORT_ALLOW_OPEN'):
        return False
    for name in ('VideoFusion-macOS', 'VideoFusion', 'JianyingPro', 'CapCut'):
        try:
            if subprocess.call(['pgrep', '-x', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                return True
        except OSError:
            return False
    return False


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def parse_store(argv):
    if os.environ.get('VIDEO_IMPORT_STORE'):
        return Path(os.environ['VIDEO_IMPORT_STORE']).expanduser().resolve()
    if argv and argv[0] in ('--store', '-Store') and len(argv) > 1:
        return Path(argv[1]).expanduser().resolve()
    return default_store()


def main(argv):
    package = Path.cwd().resolve()
    source = package / 'draft'
    manifest_path = package / 'manifest.json'
    if not manifest_path.is_file() or not source.is_dir():
        die('请先把 ZIP 完整解压到文件夹，再运行 Import-Draft.command。')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    draft_id = str(manifest.get('draft_id') or '')
    if not re.fullmatch(r'[A-Za-z0-9-]+', draft_id):
        die('草稿编号无效。')
    store = parse_store(argv)
    index_path = store / 'root_meta_info.json'
    destination = (store / f'workbench-{draft_id}').resolve()
    if destination == store or store not in destination.parents:
        die('导入路径无效。')
    content_file = source / 'draft_content.json'
    if not content_file.is_file():
        die('压缩包缺少 draft/draft_content.json。')
    content = json.loads(content_file.read_text(encoding='utf-8-sig'))
    name = content.get('name') or manifest.get('title') or destination.name
    if destination.is_dir():
        print(f'这份草稿已经导入过，不会覆盖。\n请打开剪映，在首页查找：{name}')
        return
    chosen = {'font': resource_roots('font')[0].resolve(), 'effect': resource_roots('effect')[0].resolve()}
    for resource in manifest.get('native_resources') or []:
        kind = 'font' if resource.get('kind') == 'font' else 'effect'
        root, path = first_existing(resource.get('relative_path') or '', kind)
        if not path:
            die(f'剪映缺少资源：{resource.get("name") or resource.get("relative_path")}。请先在剪映下载该字体或文字动画，再重试。')
        chosen[kind] = root
    for relative, expected in (manifest.get('files') or {}).items():
        if Path(relative).name in SKIP:
            continue
        item = (package / relative).resolve()
        if item != package and package not in item.parents:
            die('压缩包包含无效路径。')
        if not item.is_file():
            die(f'文件缺失：{relative}。请重新解压完整 ZIP。')
        if sha256(item) != expected:
            die(f'文件校验失败：{relative}。请重新下载并完整解压。')
    if not index_path.is_file():
        die(f'找不到剪映草稿库：{store}。请先打开一次剪映，或使用 --store 指定草稿目录。')
    if editor_running():
        die('请先保存并退出剪映，再导入。')

    lock = (store / '.video-workbench-import.lock').open('a+')
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        die('已有导入正在进行，请稍后再试。')
    copied = False
    registered = False
    try:
        original = index_path.read_bytes()
        index = json.loads(original.decode('utf-8-sig'))
        if 'all_draft_store' not in index:
            die('无法识别剪映草稿索引，未做任何修改。')
        if any(str(item.get('draft_id') or '') == draft_id for item in index.get('all_draft_store') or []):
            die('这份草稿已经在剪映首页中，不会覆盖。请打开剪映查找。')
        shutil.copytree(source, destination)
        copied = True
        mapping = {
            '__DRAFT_ROOT__': json_escape(destination),
            '__STORE_ROOT__': json_escape(store),
            '__JY_FONT_ROOT__': json_escape(chosen['font']),
            '__JY_EFFECT_ROOT__': json_escape(chosen['effect']),
        }
        for file in destination.rglob('*'):
            if not file.is_file() or (file.suffix != '.json' and file.name != 'template-2.tmp'):
                continue
            raw = file.read_text(encoding='utf-8-sig')
            for token, value in mapping.items():
                raw = raw.replace(token, value)
            json.loads(raw)
            file.write_text(raw, encoding='utf-8')
        content_out = destination / 'draft_content.json'
        info_out = destination / 'draft_info.json'
        if content_out.is_file():
            shutil.copy2(content_out, info_out)
        meta_path = destination / 'draft_meta_info.json'
        meta = json.loads(meta_path.read_text(encoding='utf-8-sig')) if meta_path.is_file() else {}
        meta['draft_id'] = draft_id
        meta['draft_name'] = name
        meta['draft_fold_path'] = str(destination)
        meta['draft_root_path'] = str(store)
        meta['draft_json_file'] = str(info_out)
        meta['tm_draft_removed'] = 0
        meta['draft_is_invisible'] = False
        cover = destination / 'draft_cover.jpg'
        if cover.is_file():
            meta['draft_cover'] = str(cover)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')
        if index_path.read_bytes() != original:
            die('导入过程中草稿索引被其它程序改动，未完成登记。请关闭剪映后重试。')
        index.setdefault('all_draft_store', []).append(meta)
        index['draft_ids'] = len(index['all_draft_store'])
        index['root_path'] = str(store)
        backup = store / f"root_meta_info.before-workbench-{datetime.now().strftime('%Y%m%d%H%M%S%f')}.json"
        fd, tmp = tempfile.mkstemp(prefix='root_meta_info.workbench-', suffix='.tmp', dir=store)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as out:
                json.dump(index, out, ensure_ascii=False)
            os.replace(tmp, index_path)
            backup.write_bytes(original)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise
        registered = True
        print(f'已导入：{name}')
        print('请打开剪映，在首页找到该草稿后检查并导出。')
    except Exception:
        if copied and not registered and destination.is_dir():
            shutil.rmtree(destination, ignore_errors=True)
        raise
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(exc)
            pause()
            raise
    except Exception as exc:
        print('导入失败：' + str(exc))
        pause()
        raise SystemExit(1)
    pause()
PY

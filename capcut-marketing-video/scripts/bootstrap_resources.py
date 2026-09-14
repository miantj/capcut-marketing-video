#!/usr/bin/env python3
"""Build native-resources.json from capcut enums + local JianYing/CapCut effect cache.

finish() needs animation objects with a real on-disk path directory. Enums alone
only give resource_id/md5; this script resolves Cache/effect/{resource_id}/{md5}.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import urllib.request
import zipfile
from pathlib import Path

from capcut_bin import capcut_cmd
from design_allowlist import DEFAULT_ANIMATION_NAMES


DEFAULT_NAMES = DEFAULT_ANIMATION_NAMES
EFFECT_CDN = 'https://lf3-effectcdn-tos.byteeffecttos.com/obj/ies.fe.effect/'


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def effect_roots():
    local = Path(os.environ.get('LOCALAPPDATA', ''))
    home = Path.home()
    candidates = [
        local / 'JianyingPro' / 'User Data' / 'Cache' / 'effect',
        local / 'CapCut' / 'User Data' / 'Cache' / 'effect',
        local / 'ByteDance' / 'JianyingPro' / 'User Data' / 'Cache' / 'effect',
        local / 'ByteDance' / 'CapCut' / 'User Data' / 'Cache' / 'effect',
        home / 'Library' / 'Containers' / 'com.lemon.lvpro' / 'Data' / 'Movies' / 'JianyingPro' / 'User Data' / 'Cache' / 'effect',
        home / 'Library' / 'Containers' / 'com.lemon.lvoverseas' / 'Data' / 'Movies' / 'CapCut' / 'User Data' / 'Cache' / 'effect',
        home / 'Movies' / 'JianyingPro' / 'User Data' / 'Cache' / 'effect',
        home / 'Movies' / 'CapCut' / 'User Data' / 'Cache' / 'effect',
    ]
    return [p for p in candidates if p.is_dir()]


def resolve_path(resource_id, md5, roots=None, effect_id=None):
    roots = roots or effect_roots()
    keys = [str(key) for key in (resource_id, effect_id) if key]
    if not keys:
        return None
    for root in roots:
        for key in keys:
            base = root / key
            if md5:
                candidate = base / md5
                if candidate.is_dir():
                    return candidate
            if base.is_dir():
                children = [p for p in base.iterdir() if p.is_dir()]
                if len(children) == 1:
                    return children[0]
                if md5:
                    for child in children:
                        if md5 in child.name:
                            return child
    return None


def fetch_effect(resource_id, md5, roots):
    if not resource_id or not md5 or not roots:
        return None
    dest = Path(roots[0]) / str(resource_id) / md5
    if (dest / 'config.json').is_file():
        return dest
    try:
        with urllib.request.urlopen(EFFECT_CDN + md5, timeout=60) as response:
            payload = response.read()
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for info in archive.infolist():
                name = Path(info.filename).name
                if info.is_dir() or not name or name.startswith('.') or info.filename.startswith('__MACOSX'):
                    continue
                (dest / name).write_bytes(archive.read(info))
    except (OSError, zipfile.BadZipFile):
        return None
    return dest if (dest / 'config.json').is_file() else None


def enums(kind, jianying=True):
    args = [capcut_cmd(), 'enums', '--' + kind]
    if jianying:
        args.append('--jianying')
    result = subprocess.run(args, capture_output=True, timeout=120)
    stdout = (result.stdout or b'').decode('utf-8', errors='replace')
    stderr = (result.stderr or b'').decode('utf-8', errors='replace')
    if result.returncode:
        raise ValueError('capcut enums failed: ' + (stderr or stdout or kind))
    data = json.loads(stdout)
    if not isinstance(data, list):
        raise ValueError('Unexpected enums payload for ' + kind)
    return data


def index_by_name(rows):
    by_name = {}
    for row in rows:
        for key in ('name', 'title', 'member'):
            label = row.get(key)
            if isinstance(label, str) and label.strip() and label not in by_name:
                by_name[label.strip()] = row
        slug = row.get('slug')
        if isinstance(slug, str) and slug.strip() and slug not in by_name:
            by_name[slug.strip()] = row
    return by_name


def animation_object(name, meta, kind, roots):
    """Shape compatible with delivery_steps.finish deepcopy + check_styles path gate."""
    resource_id = meta.get('resource_id') or ''
    md5 = meta.get('md5') or ''
    effect_id = meta.get('effect_id') or ''
    path = resolve_path(resource_id, md5, roots, effect_id=effect_id) or fetch_effect(resource_id, md5, roots)
    category = 'in_fav' if kind == 'intro' else 'out_fav'
    return dict(
        name=name,
        resource_id=resource_id,
        effect_id=effect_id,
        md5=md5,
        path=str(path) if path else '',
        path_ok=bool(path and path.is_dir()),
        platform='all',
        category_id=category,
        category_name=category,
        material_type='text',
        panel='',
        request_id='',
        source_platform=1,
        third_resource_id='',
        anim_adjust_params=None,
        id=effect_id or resource_id or name,
        enum=dict(slug=meta.get('slug') or '', member=meta.get('member') or name,
                  is_vip=bool(meta.get('is_vip')), source='enums'),
    )


def extract_from_draft(draft_dir):
    draft = Path(draft_dir)
    payload = None
    for name in ('draft_content.json', 'draft_info.json'):
        path = draft / name
        if path.is_file():
            payload = json.loads(path.read_text(encoding='utf-8-sig'))
            break
    if payload is None:
        raise ValueError('No draft_content/draft_info in ' + str(draft))
    found = {}
    for container in payload.get('materials', {}).get('material_animations') or []:
        for anim in container.get('animations') or []:
            name = anim.get('name')
            if not isinstance(name, str) or not name.strip():
                continue
            path = anim.get('path')
            item = dict(anim)
            item['path_ok'] = bool(isinstance(path, str) and path and Path(path).is_dir())
            found[name] = item
    return found


def bootstrap(names=None, jianying=True, fonts_query=None, from_draft=None):
    names = list(names or DEFAULT_NAMES)
    roots = effect_roots()
    intros = index_by_name(enums('text-intros', jianying))
    outros = index_by_name(enums('text-outros', jianying))
    fonts = index_by_name(enums('fonts', jianying))
    bubbles = index_by_name(enums('bubbles', jianying))
    resources = {}
    missing = []
    for name in names:
        meta = intros.get(name) or outros.get(name)
        kind = 'intro' if name in intros else 'outro'
        if not meta:
            missing.append(name + ' (not in enums)')
            continue
        resources[name] = animation_object(name, meta, kind, roots)
        if not resources[name]['path_ok']:
            missing.append(name + ' (cache path)')
    if from_draft:
        for name, anim in extract_from_draft(from_draft).items():
            resources[name] = anim
    font_hits = {}
    for query in fonts_query or ('悠然体', 'HYYouRanTiJ'):
        for label, meta in fonts.items():
            if query.lower() in label.lower() or query in (meta.get('member') or ''):
                font_hits[label] = dict(
                    name=label, id=meta.get('resource_id') or meta.get('effect_id'),
                    effect_id=meta.get('effect_id'), resource_id=meta.get('resource_id'),
                    md5=meta.get('md5'), slug=meta.get('slug') or '', is_vip=bool(meta.get('is_vip')),
                    note='Fill font.path from a real .ttf on this machine before build')
    unresolved = [k for k, v in resources.items() if not v.get('path_ok')]
    return dict(
        ok=not any('(not in enums)' in m for m in missing) and not unresolved,
        resources=resources,
        meta=dict(
            jianying=jianying,
            effect_roots=[str(p) for p in roots],
            missing=missing,
            unresolved=unresolved,
            fonts=font_hits,
            bubbles={k: dict(name=k, resource_id=v.get('resource_id'), effect_id=v.get('effect_id'),
                             slug=v.get('slug') or '', is_vip=bool(v.get('is_vip')))
                     for k, v in list(bubbles.items())[:20]},
            note='Keys are animation names for finish --resources. path must exist before finish.',
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, help='native-resources.json path')
    parser.add_argument('--names', nargs='*', help='animation names to resolve')
    parser.add_argument('--font', action='append', dest='fonts', help='font name substring to catalogue')
    parser.add_argument('--from-draft', help='also merge animation objects from a saved draft')
    parser.add_argument('--capcut', action='store_true', help='use CapCut enum namespace instead of JianYing')
    args = parser.parse_args()
    try:
        result = bootstrap(names=args.names, jianying=not args.capcut,
                           fonts_query=args.fonts, from_draft=args.from_draft)
        out = Path(args.out)
        write(out, result['resources'])
        write(out.with_suffix('.meta.json'), result['meta'])
        print(json.dumps(dict(ok=result['ok'], out=str(out.resolve()), count=len(result['resources']),
                              unresolved=result['meta']['unresolved'], missing=result['meta']['missing'],
                              effect_roots=result['meta']['effect_roots'],
                              fonts=list(result['meta']['fonts']),
                              meta=str(out.with_suffix('.meta.json').resolve())),
                         ensure_ascii=False, indent=2))
        return 0 if result['ok'] else 1
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

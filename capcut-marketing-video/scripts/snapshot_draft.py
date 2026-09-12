#!/usr/bin/env python3
"""Snapshot an explicitly selected draft candidate with expected SHA-256.

Creates a new output directory only. Does not select, sync, register, relink,
render, or copy media. The same project ID must not be registered as a new draft.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from datetime import datetime, timezone


def snapshot(source, expected, output):
    source = Path(source).expanduser().resolve(strict=True)
    output = Path(output).expanduser().resolve()
    if source.name not in ('draft_content.json', 'draft_info.json', 'template-2.tmp'):
        raise ValueError('Select a supported timeline candidate explicitly')
    if not re.fullmatch('[0-9a-fA-F]{64}', expected):
        raise ValueError('Expected SHA-256 must be 64 hexadecimal characters')
    if output.exists():
        raise ValueError('Output already exists; refusing to overwrite: ' + str(output))
    # A source project may contain nested Timelines; forbid output anywhere in that project.
    project = source.parent
    for parent in source.parents:
        if parent.name.lower() == 'timelines':
            project = parent.parent
            break
    if output == project or project in output.parents:
        raise ValueError('Snapshot output must be outside source project')
    before = source.stat()
    raw = source.read_bytes()
    after = source.stat()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected.lower() or (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
        raise ValueError('Source changed since inspection; inspect and choose again')
    value = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(value, dict) or not isinstance(value.get('tracks'), list) or not isinstance(value.get('materials'), dict):
        raise ValueError('Not a root timeline; retain envelope and use version-specific handling')
    if not isinstance(value.get('id'), str) or not value['id']:
        raise ValueError('Missing draft project id')
    manifest = {
        'source_path': str(source), 'source_mtime_ns': after.st_mtime_ns,
        'source_sha256': digest, 'project_id': value['id'],
        'created_at': datetime.now(timezone.utc).isoformat(),
        'snapshot_file': source.name, 'media_copied': False,
        'paths_resolved': False, 'registered': False,
        'note': 'Exact selected file bytes. Read/derive only; not an independently registered project.'
    }
    output.mkdir(parents=True, exist_ok=False)
    with (output / source.name).open('xb') as f:
        f.write(raw)
    with (output / 'source-manifest.json').open('x', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write('\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    try:
        report = {'ok': True, **snapshot(args.source, args.expected_sha256, args.out)}
    except (OSError, ValueError, TypeError) as exc:
        report = {'ok': False, 'error': str(exc)}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())

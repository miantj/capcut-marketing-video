#!/usr/bin/env python3
"""Media/draft inventory. Requires ffprobe for media; optional frame copies use ffmpeg.

Does not infer speech, burned-in subtitles, font licenses or canonical drafts.
Prints JSON to stdout; never modifies inputs or selects a draft automatically.
--frames-out writes representative images, not semantic inspection results.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | {'.mp4', '.mov', '.m4v', '.mkv', '.avi', '.webm',
                                      '.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg'}


def media_files(directory):
    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        raise ValueError('Media directory not found: ' + str(root))
    return sorted(p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in MEDIA_EXTENSIONS)


def sample_frames(filename, duration, output):
    output = Path(output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix='frames-', dir=output))
    frames = []
    # ponytail: three samples miss brief cuts/text; inspect selected source ranges before editing.
    for index, timestamp in enumerate((0, duration * 0.5, duration * 0.9)):
        target = folder / f'{index}.jpg'
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-ss', str(timestamp), '-i', str(filename),
                        '-frames:v', '1', '-vf', 'scale=480:-2', str(target)],
                       capture_output=True, text=True, timeout=60, check=True)
        if not target.is_file() or not target.stat().st_size:
            raise ValueError('Frame extraction produced no image: ' + str(filename))
        frames.append({'source_seconds': timestamp, 'path': str(target)})
    return frames


def inspect_media(filename, frames_out=None):
    p = Path(filename).expanduser().resolve()
    if not p.is_file():
        raise ValueError('Media file not found: ' + str(p))
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(p)],
        capture_output=True, text=True, timeout=60, check=True,
    )
    probe = json.loads(result.stdout)
    streams = probe.get('streams', [])
    summary = []
    for stream in streams:
        entry = {k: stream[k] for k in (
            'index', 'codec_type', 'codec_name', 'width', 'height', 'duration',
            'avg_frame_rate', 'r_frame_rate', 'sample_rate', 'channels', 'channel_layout'
        ) if k in stream}
        entry['rotation'] = next((s['rotation'] for s in stream.get('side_data_list', [])
                                  if 'rotation' in s), stream.get('tags', {}).get('rotate'))
        summary.append(entry)
    stat = p.stat()
    kind = 'image' if p.suffix.lower() in IMAGE_EXTENSIONS else ('video' if any(
        s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic') for s in streams) else 'audio')
    report = {
        'path': str(p), 'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns,
        'kind': kind,
        'duration': probe.get('format', {}).get('duration'), 'streams': summary,
        'has_audio_stream': any(s.get('codec_type') == 'audio' for s in streams),
        'has_subtitle_stream': any(s.get('codec_type') == 'subtitle' for s in streams),
        'speech_content': 'unknown: listen or transcribe',
        'burned_in_text': 'unknown: inspect frames; subtitle streams cannot answer this',
    }
    if frames_out and kind == 'video':
        duration = float(report['duration'] or 0)
        if duration <= 0:
            raise ValueError('Cannot sample video without a positive duration: ' + str(p))
        report['frames'] = sample_frames(p, duration, frames_out)
    return report


def find_timelines(value, location='$', depth=0):
    if depth > 12:
        return
    if isinstance(value, dict):
        if isinstance(value.get('tracks'), list) and isinstance(value.get('materials'), dict):
            yield location, value
            return
        for k, v in value.items():
            yield from find_timelines(v, location + '.' + k, depth + 1)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from find_timelines(v, location + '[' + str(i) + ']', depth + 1)
    elif isinstance(value, str) and value.lstrip().startswith(('{', '[')):
        try:
            decoded = json.loads(value)
        except ValueError:
            return
        yield from find_timelines(decoded, location + '(json)', depth + 1)


def path_evidence(raw, root):
    if not isinstance(raw, str) or not raw:
        return None
    proposed = re.sub(r'^##_draftpath_placeholder_[^#]+_##', str(root), raw)
    p = Path(proposed).expanduser()
    if not p.is_absolute():
        p = root / p
    return {'stored': raw, 'resolved_candidate': str(p), 'exists': p.is_file(),
            'placeholder_resolution_is_assumption': proposed != raw}


def summarize_timeline(draft, root):
    text_materials = {m.get('id'): m for m in draft['materials'].get('texts', [])}
    tracks = []
    for track in draft['tracks']:
        segments = []
        for seg in track.get('segments', []):
            row = {k: seg.get(k) for k in ('id', 'material_id', 'target_timerange',
                   'source_timerange', 'speed', 'volume', 'clip', 'common_keyframes',
                   'extra_material_refs')}
            if track.get('type') == 'text':
                m = text_materials.get(seg.get('material_id'), {})
                try:
                    content = json.loads(m.get('content', '{}'))
                except (ValueError, TypeError):
                    content = {'unparsed_content': m.get('content')}
                row['text_content'] = content
                row['text_material'] = {k: v for k, v in m.items()
                                        if k.startswith(('font', 'line_', 'letter_', 'border_', 'shadow_', 'background_'))}
                row['font_license'] = 'unknown; not inferred from local cache presence'
            segments.append(row)
        tracks.append({'type': track.get('type'), 'name': track.get('name'), 'segments': segments})
    paths = []
    for kind in ('videos', 'audios'):
        for m in draft['materials'].get(kind, []):
            paths.append({'kind': kind, 'id': m.get('id'),
                          'path': path_evidence(m.get('path'), root)})
    canonical = json.dumps(draft, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    return {'id': draft.get('id'), 'name': draft.get('name'), 'duration_us': draft.get('duration'),
            'canvas': draft.get('canvas_config'), 'fps': draft.get('fps'),
            'timeline_sha256': hashlib.sha256(canonical).hexdigest(),
            'tracks': tracks, 'media_paths': paths}


def inspect_draft(dirname):
    root = Path(dirname).expanduser().resolve()
    if not root.is_dir():
        raise ValueError('Draft directory not found: ' + str(root))
    names = ('draft_content.json', 'draft_info.json', 'template-2.tmp')
    files = [root / n for n in names if (root / n).is_file()]
    nested = root / 'Timelines'
    if nested.is_dir():
        files.extend(p for p in sorted(nested.rglob('*')) if p.is_file() and p.name in names)
    candidates = []
    for p in files:
        before = p.stat()
        raw = p.read_bytes()
        after = p.stat()
        entry = {'file': str(p.relative_to(root)), 'bytes': len(raw),
                 'mtime_ns': after.st_mtime_ns, 'sha256': hashlib.sha256(raw).hexdigest(),
                 'stable_during_read': (before.st_mtime_ns, before.st_size) ==
                                      (after.st_mtime_ns, after.st_size)}
        try:
            value = json.loads(raw.decode('utf-8-sig'))
            entry['timelines'] = [{'envelope': loc, **summarize_timeline(d, root)}
                                  for loc, d in find_timelines(value)]
            if not entry['timelines']:
                entry['error'] = 'No recognizable timeline; may require version-specific handling'
        except (UnicodeError, ValueError, TypeError, KeyError, AttributeError) as e:
            entry['error'] = 'Unparsed candidate: ' + str(e)
        candidates.append(entry)
    if not candidates:
        raise ValueError('No supported timeline candidate found in ' + str(root))
    return {'directory': str(root), 'selected_candidate': None, 'candidates': candidates,
            'selection_note': 'Compare saved edits and project IDs; mtime alone is not proof. Never auto-sync.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--media', action='append', default=[])
    parser.add_argument('--media-dir', action='append', default=[], help='Recursively inventory local media')
    parser.add_argument('--frames-out', help='Optional project-local directory for three frames per video')
    parser.add_argument('--draft', action='append', default=[])
    args = parser.parse_args()
    if not args.media and not args.media_dir and not args.draft:
        parser.error('Provide --media, --media-dir and/or --draft')
    report = {'media': [], 'drafts': [], 'errors': []}
    media = [Path(p).expanduser().resolve() for p in args.media]
    for directory in args.media_dir:
        try:
            media.extend(media_files(directory))
        except (OSError, ValueError) as e:
            report['errors'].append({'input': directory, 'error': str(e)})
    if args.media_dir and not media:
        report['errors'].append({'input': args.media_dir, 'error': 'No supported media found'})
    inspect_with_frames = lambda p: inspect_media(p, args.frames_out)
    for kind, names, inspect in (('media', list(dict.fromkeys(media)), inspect_with_frames), ('drafts', args.draft, inspect_draft)):
        for name in names:
            try:
                report[kind].append(inspect(name))
            except (OSError, ValueError, subprocess.SubprocessError) as e:
                report['errors'].append({'input': str(name), 'error': str(e)})
    report['ok'] = not report['errors']
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Narration checklist + measured-duration retime for storyboard.json.

Does not call CapCut TTS. Marketing voiceover stays JianYing native textReading;
this only plans per-cue files and rewrites timings after real durations exist.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path

from validate_storyboard import cue_ids, number, validate


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def probe_duration(path):
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', str(path)],
        capture_output=True, timeout=60)
    stdout = (result.stdout or b'').decode('utf-8', errors='replace')
    stderr = (result.stderr or b'').decode('utf-8', errors='replace')
    if result.returncode:
        raise ValueError('ffprobe failed for ' + str(path) + ': ' + (stderr or stdout))
    value = float(stdout.strip())
    if not math.isfinite(value) or value <= 0:
        raise ValueError('Invalid media duration for ' + str(path))
    return value


def narrate_plan(plan, project, audio_dir='narration'):
    """Build a per-script_id checklist for native JianYing TTS capture."""
    narration = plan.get('narration') or {}
    mode = narration.get('mode')
    if mode not in ('native_tts', 'provided', None):
        raise ValueError('narrate is for native_tts/provided; mode=' + str(mode))
    root = Path(project).resolve()
    out_dir = (root / audio_dir).resolve()
    cues = []
    for row in plan.get('script') or []:
        cue_id = row.get('id')
        text = row.get('text')
        if not isinstance(cue_id, str) or not cue_id.strip():
            raise ValueError('script entries need id')
        if not isinstance(text, str) or not text.strip():
            raise ValueError('Empty script text: ' + cue_id)
        target = out_dir / (cue_id + '.wav')
        existing = target.is_file()
        duration = None
        if existing:
            try:
                duration = probe_duration(target)
            except (OSError, ValueError):
                duration = None
        cues.append(dict(
            script_id=cue_id,
            text=text.strip(),
            pause_after=row.get('pause_after', 0),
            emphasis=row.get('emphasis', []),
            audio_path=str(target),
            status='measured' if duration else ('present' if existing else 'missing'),
            duration=duration,
            instruction='在剪映中按该句原文单独生成 textReading，导出/复制到 audio_path；勿用外部 TTS 进营销成片。',
        ))
    missing = [c['script_id'] for c in cues if c['status'] == 'missing']
    return dict(
        ok=not missing,
        mode=mode or 'native_tts',
        project=str(root),
        audio_dir=str(out_dir),
        cues=cues,
        missing=missing,
        next_step=('retime with --from-dir ' + str(out_dir)) if not missing else 'generate missing native cue audio',
        note='One JianYing TTS clip per script_id; do not merge sentences then split.',
    )


def _apply_script_timing(plan, durations):
    cursor = 0.0
    for row in plan['script']:
        cue_id = row['id']
        if cue_id not in durations:
            raise ValueError('Missing measured duration for script_id: ' + cue_id)
        dur = durations[cue_id]
        if not number(dur) or dur <= 0:
            raise ValueError('Duration must be positive: ' + cue_id)
        pause = row.get('pause_after', 0) or 0
        if not number(pause) or pause < 0:
            raise ValueError('pause_after must be >= 0: ' + cue_id)
        row['start'] = round(cursor, 6)
        row['end'] = round(cursor + dur, 6)
        cursor = row['end'] + pause
    plan['duration'] = round(cursor if cursor > 0 else plan.get('duration', 0), 6)
    by_id = {row['id']: row for row in plan['script']}
    for cap in plan.get('captions') or []:
        keys = cue_ids(cap)
        if not keys:
            raise ValueError('Caption missing cue_ids during retime')
        cap['start'] = min(by_id[k]['start'] for k in keys)
        # Hold through the last cue's speech; pauses between grouped cues stay inside the screen.
        cap['end'] = max(by_id[k]['end'] for k in keys)
        if keys[-1] == plan['script'][-1]['id']:
            cap['end'] = plan['duration']
    return by_id


def _retime_shots(plan, old_duration):
    new_duration = plan['duration']
    if not plan.get('shots'):
        return
    if not number(old_duration) or old_duration <= 0:
        # Estimated boards often already cover a placeholder duration; fall back to equal split.
        n = len(plan['shots'])
        step = new_duration / n
        for i, shot in enumerate(plan['shots']):
            shot['start'] = round(i * step, 6)
            shot['end'] = round(new_duration if i == n - 1 else (i + 1) * step, 6)
            kind = next((a for a in plan['assets'] if a['id'] == shot['asset_id']), {}).get('kind')
            if kind == 'video' and number(shot.get('source_in')) and number(shot.get('speed')) and shot['speed'] > 0:
                need = (shot['end'] - shot['start']) * shot['speed']
                shot['source_out'] = shot['source_in'] + need
        return
    scale = new_duration / old_duration
    for shot in plan['shots']:
        shot['start'] = round(shot['start'] * scale, 6)
        shot['end'] = round(shot['end'] * scale, 6)
        kind = next((a for a in plan['assets'] if a['id'] == shot['asset_id']), {}).get('kind')
        if kind == 'video' and number(shot.get('source_in')) and number(shot.get('speed')) and shot['speed'] > 0:
            need = (shot['end'] - shot['start']) * shot['speed']
            shot['source_out'] = shot['source_in'] + need
    if plan['shots']:
        plan['shots'][0]['start'] = 0.0
        plan['shots'][-1]['end'] = new_duration


def _retime_audio(plan, by_id, audio_files):
    """Rebuild narration rows from measured cue files; keep non-narration rows stretched."""
    kept = [row for row in plan.get('audio') or [] if row.get('role') != 'narration']
    narration = []
    assets = {a['id']: a for a in plan['assets']}
    for cue_id, path in audio_files.items():
        asset_id = 'narration-' + cue_id
        duration = probe_duration(path)
        rel = str(path)
        assets_row = assets.get(asset_id)
        if not assets_row:
            plan['assets'].append(dict(
                id=asset_id, path=rel, kind='audio', duration=duration,
                inspection='Native cue audio measured by retime'))
        else:
            assets_row.update(path=rel, kind='audio', duration=duration,
                              inspection=assets_row.get('inspection') or 'Native cue audio measured by retime')
        cue = by_id[cue_id]
        narration.append(dict(
            asset_id=asset_id, role='narration', volume=1,
            start=cue['start'], end=cue['end'],
            source_in=0, source_out=duration, speed=1,
            cue_ids=[cue_id]))
    previous = plan.get('_retime_old_duration')
    for row in kept:
        if number(previous) and previous > 0 and number(row.get('start')) and number(row.get('end')):
            span = row['end'] - row['start']
            row['start'] = round(row['start'] / previous * plan['duration'], 6)
            row['end'] = round(row['start'] + span / previous * plan['duration'], 6)
            if number(row.get('source_in')) and number(row.get('speed')) and row['speed'] > 0:
                row['source_out'] = row['source_in'] + (row['end'] - row['start']) * row['speed']
    plan['audio'] = narration + kept


# 无实测配音时的估算默认（剪映 textReading 实测约 0.22s/非空白字）。
# 旧默认 0.25 偏慢、句间空档大。有 wav 后必须 retime，不能用估算当最终时长。
DEFAULT_SEC_PER_CHAR = 0.22


def count_display_chars(text):
    """Count non-whitespace characters used for on-screen display duration."""
    if not isinstance(text, str):
        raise ValueError('text must be a string')
    return sum(1 for ch in text if not ch.isspace())


def durations_from_chars(plan, sec_per_char=DEFAULT_SEC_PER_CHAR):
    """Map each script_id to seconds = char_count * sec_per_char."""
    if not number(sec_per_char) or sec_per_char <= 0:
        raise ValueError('sec_per_char must be > 0')
    out = {}
    for row in plan.get('script') or []:
        cue_id = row.get('id')
        text = row.get('text')
        if not isinstance(cue_id, str) or not cue_id.strip():
            raise ValueError('script entries need id')
        n = count_display_chars(text or '')
        if n <= 0:
            raise ValueError('Empty display text for script_id: ' + cue_id)
        out[cue_id] = round(n * sec_per_char, 6)
    return out


def retime(plan, durations=None, from_dir=None, evidence='Measured cue audio; listen before build'):
    """Rewrite script/caption/shot/audio timings from measured per-cue durations."""
    plan = json.loads(json.dumps(plan))  # deep copy via JSON
    old_duration = plan.get('duration')
    plan['_retime_old_duration'] = old_duration
    audio_files = {}
    measured = dict(durations or {})
    if from_dir:
        folder = Path(from_dir)
        if not folder.is_dir():
            raise ValueError('Audio directory not found: ' + str(folder))
        for row in plan['script']:
            cue_id = row['id']
            matches = [p for ext in ('.wav', '.mp3', '.m4a', '.aac', '.flac')
                       if (p := folder / (cue_id + ext)).is_file()]
            if not matches:
                raise ValueError('Missing audio for script_id: ' + cue_id)
            path = matches[0]
            audio_files[cue_id] = path
            measured[cue_id] = probe_duration(path)
    if not measured:
        raise ValueError('Provide --durations JSON or --from-dir of per-cue audio')
    by_id = _apply_script_timing(plan, measured)
    _retime_shots(plan, old_duration)
    if audio_files:
        _retime_audio(plan, by_id, audio_files)
    elif plan.get('audio'):
        # Durations-only path: shift existing narration rows that declare cue_ids.
        for row in plan['audio']:
            if row.get('role') != 'narration':
                continue
            keys = cue_ids(row)
            if not keys:
                continue
            row['start'] = min(by_id[k]['start'] for k in keys)
            row['end'] = max(by_id[k]['end'] for k in keys)
            if len(keys) == 1 and keys[0] in measured:
                row['source_in'] = 0
                row['source_out'] = measured[keys[0]]
                row['speed'] = 1
    plan.pop('_retime_old_duration', None)
    narration = dict(plan.get('narration') or {})
    narration.update(mode=narration.get('mode') or 'native_tts', timing='aligned', evidence=evidence)
    plan['narration'] = narration
    return plan


def retime_by_chars(plan, sec_per_char=DEFAULT_SEC_PER_CHAR):
    """Estimate cue/caption/shot timing from character count (not speech-aligned).

    Formula: cue_seconds = count_display_chars(text) * sec_per_char
    Keeps narration.timing=estimated; use measured audio + retime() for final VO sync.
    Stretches non-narration audio (e.g. bgm) to the new duration when present.
    """
    plan = json.loads(json.dumps(plan))
    old_duration = plan.get('duration')
    measured = durations_from_chars(plan, sec_per_char)
    _apply_script_timing(plan, measured)
    _retime_shots(plan, old_duration)
    kept = []
    for row in plan.get('audio') or []:
        if row.get('role') == 'narration':
            continue
        row = dict(row)
        row['start'] = 0.0
        row['end'] = plan['duration']
        if number(row.get('source_in')) and number(row.get('speed')) and row['speed'] > 0:
            need = (row['end'] - row['start']) * row['speed']
            asset = next((a for a in plan['assets'] if a['id'] == row.get('asset_id')), None)
            src_dur = asset.get('duration') if asset and number(asset.get('duration')) else None
            if src_dur is not None and need > src_dur:
                row['source_in'] = 0.0
                row['source_out'] = src_dur
            else:
                row['source_out'] = row['source_in'] + need
        kept.append(row)
    narration_rows = [row for row in plan.get('audio') or [] if row.get('role') == 'narration']
    plan['audio'] = narration_rows + kept
    narration = dict(plan.get('narration') or {})
    if narration.get('mode') not in (None, 'none'):
        narration['timing'] = 'estimated'
        narration['char_timing'] = dict(sec_per_char=sec_per_char, formula='non_whitespace_chars * sec_per_char')
    plan['narration'] = narration
    note = f'字幕/口播预计按每字{sec_per_char}秒×非空白字数重排（未对齐实测配音）'
    base = plan.get('copy_notes') or ''
    if '每字' not in base:
        plan['copy_notes'] = (base + '；' + note).strip('；') if base else note
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('narrate', 'retime', 'retime-chars'))
    parser.add_argument('storyboard', help='path to storyboard.json')
    parser.add_argument('--project', help='project root for narrate audio_dir (default: storyboard parent)')
    parser.add_argument('--audio-dir', default='narration', help='relative audio folder under project')
    parser.add_argument('--from-dir', help='directory of {script_id}.wav for retime')
    parser.add_argument('--durations', help='JSON object {script_id: seconds} for retime')
    parser.add_argument('--sec-per-char', type=float, default=DEFAULT_SEC_PER_CHAR,
                        help='seconds per on-screen character for retime-chars (default 0.22; override after measuring TTS)')
    parser.add_argument('--evidence', default='Measured cue audio; listen before build')
    parser.add_argument('--in-place', action='store_true', help='overwrite storyboard.json')
    parser.add_argument('--out', help='write retimed storyboard to this path')
    args = parser.parse_args()
    source = Path(args.storyboard).resolve()
    plan = read(source)
    project = Path(args.project).resolve() if args.project else source.parent
    try:
        if args.command == 'narrate':
            result = narrate_plan(plan, project, args.audio_dir)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result['ok'] else 1
        if args.command == 'retime-chars':
            updated = retime_by_chars(plan, sec_per_char=args.sec_per_char)
        else:
            durations = read(args.durations) if args.durations else None
            updated = retime(plan, durations=durations, from_dir=args.from_dir, evidence=args.evidence)
        report = validate(updated, source.parent)
        target = Path(args.out).resolve() if args.out else (source if args.in_place else None)
        if target is None:
            raise ValueError('retime needs --in-place or --out')
        write(target, updated)
        print(json.dumps(dict(ok=report['ok'], storyboard=str(target), duration=updated['duration'],
                              narration=updated.get('narration'), errors=report['errors'],
                              warnings=report.get('warnings', []),
                              sec_per_char=args.sec_per_char if args.command == 'retime-chars' else None),
                         ensure_ascii=False, indent=2))
        return 0 if report['ok'] else 1
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

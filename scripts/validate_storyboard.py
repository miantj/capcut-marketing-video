#!/usr/bin/env python3
"""Validate the skill's storyboard plan, not a capcut-cli compile spec.

Read-only. Checks declared data, not semantic correctness, visual or audio quality.
"""
import argparse
import json
import math
from pathlib import Path
import sys

RECIPES = {'keyword-reveal', 'editorial-stack', 'benefit-tag', 'number-focus', 'cta-lockup'}


def number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def cue_ids(row):
    return row.get('cue_ids', [row['cue_id']] if 'cue_id' in row else [])


def video_volume(asset, shot):
    action = asset.get('audio_action')
    return 0 if action == 'mute' else shot.get('volume', 1 if action == 'keep' else None)


def validate(plan, base):
    errors = []
    warnings = []
    def error(message):
        errors.append(message)
    if not isinstance(plan, dict):
        return {'ok': False, 'errors': ['Plan must be an object'], 'warnings': []}
    if plan.get('version') != 1:
        error('Unsupported storyboard version')
    duration = plan.get('duration')
    if not number(duration) or duration <= 0:
        error('duration must be positive and finite')
        duration = 0
    canvas = plan.get('canvas', {})
    if not isinstance(canvas, dict):
        canvas = {}
    for k in ('width', 'height', 'fps'):
        if not number(canvas.get(k)) or canvas[k] <= 0:
            error('canvas.' + k + ' must be positive')
    epsilon = 1 / canvas['fps'] + 1e-6 if number(canvas.get('fps')) and canvas['fps'] > 0 else 0.04
    collections = {}
    for k in ('assets', 'script', 'shots', 'captions', 'audio'):
        value = plan.get(k)
        if not isinstance(value, list) or any(not isinstance(v, dict) for v in value):
            error(k + ' must be an array of objects')
            value = []
        collections[k] = value
    for k in ('assets', 'script', 'shots', 'captions'):
        if not collections[k]:
            error(k + ' must not be empty')

    def index(rows, label):
        result = {}
        for row in rows:
            key = row.get('id')
            if not isinstance(key, str) or not key.strip() or key in result:
                error(label + ': missing or duplicate id')
                continue
            result[key] = row
        return result
    assets = index(collections['assets'], 'assets')
    script = index(collections['script'], 'script')
    for key, row in script.items():
        if not isinstance(row.get('text'), str) or not row['text'].strip():
            error('Empty script text: ' + key)
        emphasis = row.get('emphasis', [])
        if not isinstance(emphasis, list) or any(not isinstance(v, str) or not v for v in emphasis):
            error('emphasis must be a list of words: ' + key)
    for key, asset in assets.items():
        kind = asset.get('kind')
        if kind not in ('video', 'audio', 'image'):
            error('Unsupported asset kind: ' + key)
        rawpath = asset.get('path')
        if not isinstance(rawpath, str) or not rawpath:
            error('Missing asset path: ' + key)
        else:
            p = Path(rawpath).expanduser()
            if not p.is_absolute():
                p = base / p
            if not p.is_file():
                error('Asset not found: ' + str(p))
        if kind != 'image' and (not number(asset.get('duration')) or asset['duration'] <= 0):
            error('Invalid asset duration: ' + key)
        if not isinstance(asset.get('inspection'), str) or not asset['inspection'].strip():
            error('Missing inspection evidence: ' + key)
        if kind == 'video':
            if asset.get('original_audio') not in ('none', 'speech', 'music', 'ambient'):
                error('Unresolved original audio: ' + key)
            if asset.get('audio_action') not in ('mute', 'keep', 'duck'):
                error('Missing audio action: ' + key)
        if kind in ('video', 'image'):
            status, action = asset.get('burned_text'), asset.get('text_action')
            if status not in ('none', 'present'):
                error('Unresolved burned-in text: ' + key)
            if action not in ('none', 'avoid', 'crop', 'cover', 'keep-approved'):
                error('Invalid text action: ' + key)
            if status == 'present' and (action == 'none' or not asset.get('treatment_note')):
                error('Existing text needs explicit treatment/evidence: ' + key)

    def timing(row, label):
        a, b = row.get('start'), row.get('end')
        if not number(a) or not number(b) or a < 0 or b <= a or b > duration + epsilon:
            error('Invalid target interval: ' + label)
            return False
        return True

    def references(row, label, required=False):
        keys = cue_ids(row)
        if ('cue_id' in row and 'cue_ids' in row) or not isinstance(keys, list) or any(
                not isinstance(k, str) or k not in script for k in keys):
            error('Invalid cue references: ' + label)
            return []
        if (required and not keys) or len(keys) != len(set(keys)):
            error('Missing or duplicate cue references: ' + label)
        if keys != [k for k in script if k in keys]:
            error('Cue references out of script order: ' + label)
        return keys

    def no_overlap(rows, label):
        cursor = 0
        for row in sorted(rows, key=lambda r: r['start']):
            if row['start'] < cursor - epsilon:
                error('Overlapping ' + label + ' at ' + str(row['start']))
            cursor = max(cursor, row['end'])

    narration = plan.get('narration', {})
    if not isinstance(narration, dict):
        error('narration must be an object')
        narration = {}
    mode = narration.get('mode')
    if 'narration' in plan and mode not in ('none', 'provided', 'native_tts', 'source'):
        error('Unknown narration mode')
    if 'timing' in narration or mode in ('provided', 'native_tts', 'source'):
        if narration.get('timing') not in ('estimated', 'aligned'):
            error('Narration timing must be estimated or aligned')
        if narration.get('timing') == 'aligned' and (not isinstance(narration.get('evidence'), str) or not narration['evidence'].strip()):
            error('Aligned narration needs listening/alignment evidence')
    timed = any('start' in row or 'end' in row for row in script.values()) or bool(mode and mode != 'none')
    timed_cues = {}
    previous = None
    if timed:
        for key, row in script.items():
            valid = timing(row, 'script ' + key)
            pause = row.get('pause_after', 0)
            if not number(pause) or pause < 0:
                error('Invalid pause_after: ' + key)
                pause = 0
            if valid:
                timed_cues[key] = row
                if previous is not None and row['start'] < previous - epsilon:
                    error('Script speech order/overlap or insufficient pause: ' + key)
                previous = row['end'] + pause
                if previous > duration + epsilon:
                    error('Script tail/pause exceeds duration: ' + key)

    def segment(row, label, kinds):
        valid = timing(row, label)
        key = row.get('asset_id')
        asset = assets.get(key) if isinstance(key, str) else None
        if not asset or asset.get('kind') not in kinds:
            error('Missing/wrong asset: ' + label)
            return False
        if asset.get('kind') != 'image':
            a, b, speed = row.get('source_in'), row.get('source_out'), row.get('speed', 1)
            if not all(number(v) for v in (a, b, speed, asset.get('duration'))) or a < 0 or b <= a or speed <= 0 or b > asset['duration'] + epsilon:
                error('Invalid source interval/speed: ' + label)
                return False
            if valid and abs((b-a)/speed - (row['end']-row['start'])) > epsilon:
                error('Source/target duration mismatch: ' + label)
                return False
        return valid

    shots = [s for i, s in enumerate(collections['shots']) if segment(s, 'shot ' + str(i), ('video', 'image'))]
    cursor = 0
    for shot in sorted(shots, key=lambda s: s['start']):
        if abs(shot['start'] - cursor) > epsilon:
            error('Main video gap or overlap at ' + str(cursor))
        cursor = max(cursor, shot['end'])
    if abs(cursor - duration) > epsilon:
        error('Main video does not cover duration')
    for i, shot in enumerate(shots):
        references(shot, 'shot ' + str(i))
        asset = assets[shot['asset_id']]
        if asset.get('kind') == 'video':
            volume = video_volume(asset, shot)
            if not number(volume) or not 0 <= volume <= 1 or (asset.get('audio_action') == 'duck' and volume >= 1):
                error('Invalid shot volume; duck requires explicit volume in [0,1)')
            elif volume > 0 and asset.get('original_audio') == 'speech' and not asset.get('audio_note'):
                error('Retained speech needs consistency evidence: ' + shot['asset_id'])

    seen = []
    ordered_caps = []
    norm = lambda s: ''.join(s.split())
    for i, cap in enumerate(collections['captions']):
        valid = timing(cap, 'caption ' + str(i))
        keys = references(cap, 'caption ' + str(i), required=True)
        if valid:
            ordered_caps.append(cap)
        text = cap.get('text')
        originals = [script[k].get('text') for k in keys]
        if not isinstance(text, str) or any(not isinstance(t, str) for t in originals) or norm(text) != norm(''.join(originals)):
            error('Caption changes or omits script text: ' + str(keys))
        if cap.get('recipe') not in RECIPES:
            error('Unknown recipe: ' + str(keys))
        animation = cap.get('animation', {})
        if not isinstance(animation, dict):
            error('caption.animation must be an object')
            animation = {}
        intro, outro = animation.get('intro_seconds', 0.5), animation.get('outro_seconds', 0.5)
        if not all(number(v) and v >= 0 for v in (intro, outro)):
            error('Invalid caption animation duration')
        elif valid and cap['end'] - cap['start'] < intro + outro + 0.3 - epsilon:
            error('Insufficient stable caption reading time; merge short cues or retime')
        for key in keys:
            cue = timed_cues.get(key)
            if valid and cue and (cap['start'] > cue['start'] + epsilon or cap['end'] < cue['end'] - epsilon):
                error('Caption does not cover spoken cue: ' + key)
    no_overlap(ordered_caps, 'body captions')
    for cap in sorted(ordered_caps, key=lambda c: c['start']):
        seen.extend(references(cap, 'caption'))
    if seen != list(script):
        error('Captions must cover every script cue exactly once in script order')
    voices = []
    voice_keys = []
    for i, audio in enumerate(collections['audio']):
        if not segment(audio, 'audio ' + str(i), ('audio', 'video')):
            continue
        source_asset = assets[audio['asset_id']]
        if source_asset.get('kind') == 'video' and source_asset.get('original_audio') == 'none':
            error('Audio segment uses video declared to have no audio: ' + audio['asset_id'])
        if audio.get('role') not in ('narration', 'bgm', 'sfx'):
            error('Unknown audio role')
        if audio.get('role') == 'narration':
            voices.append(audio)
            volume = audio.get('volume', 1)
            if not number(volume) or not 0 < volume <= 1:
                error('Narration must have audible declared volume')
            keys = references(audio, 'narration ' + str(i), required=narration.get('timing') == 'aligned')
            voice_keys.extend(keys)
            for key in keys:
                cue = timed_cues.get(key)
                if cue and (audio['start'] > cue['start'] + epsilon or audio['end'] < cue['end'] - epsilon):
                    error('Narration audio truncates spoken cue: ' + key)
            for shot in shots:
                asset = assets[shot['asset_id']]
                volume = video_volume(asset, shot)
                if asset.get('kind') == 'video' and asset.get('original_audio') == 'speech' and number(volume) and volume > 0 and min(shot['end'], audio['end']) > max(shot['start'], audio['start']):
                    error('Overlapping narration and retained source speech: ' + shot['asset_id'])
        for field in ('fade_in', 'fade_out'):
            if field in audio and (not number(audio[field]) or audio[field] < 0 or audio[field] > audio['end'] - audio['start']):
                error('Invalid audio ' + field)
    no_overlap(voices, 'narration audio')
    if mode in ('none', 'source') and voices:
        error('Separate narration audio conflicts with narration mode')
    if narration.get('timing') == 'aligned' and mode in ('provided', 'native_tts'):
        if len(voice_keys) != len(set(voice_keys)) or set(voice_keys) != set(script):
            error('Aligned narration must bind every script cue exactly once')
    if narration.get('timing') == 'aligned' and mode == 'source':
        for key, cue in timed_cues.items():
            cursor = cue['start']
            for shot in sorted(shots, key=lambda s: s['start']):
                asset = assets[shot['asset_id']]
                if asset.get('kind') != 'video' or key not in references(shot, 'source shot') or asset.get('original_audio') != 'speech' or asset.get('audio_action') == 'mute':
                    continue
                volume = video_volume(asset, shot)
                if number(volume) and volume > 0 and shot['start'] <= cursor + epsilon and shot['end'] > cursor:
                    cursor = shot['end']
            if cursor < cue['end'] - epsilon:
                error('Retained source speech does not cover cue: ' + key)
    warnings.append('Declared data only: inspect visuals, sound, caption readability and native draft rendering separately.')
    return {'ok': not errors, 'errors': errors, 'warnings': warnings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan')
    args = parser.parse_args()
    try:
        path = Path(args.plan).expanduser().resolve()
        report = validate(json.loads(path.read_text(encoding='utf-8-sig')), path.parent)
    except (OSError, ValueError, TypeError) as exc:
        report = {'ok': False, 'errors': [str(exc)], 'warnings': []}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())

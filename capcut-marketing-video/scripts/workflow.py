#!/usr/bin/env python3
"""Portrait storyboard -> compile -> draft, with content-addressed restart points.

Uses scripted finishing, installation and delivery gates; never claims native UI verification from JSON alone.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from capcut_bin import capcut_cmd
from validate_storyboard import validate, number, cue_ids, video_volume


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def compile_plan(plan, base):
    report = validate(plan, base)
    if not report['ok']:
        raise ValueError('; '.join(report['errors']))
    if plan.get('delivery', 'draft+native') not in ('draft', 'draft+native', 'video-only'):
        raise ValueError('delivery must be draft, draft+native or explicit video-only')
    canvas = plan['canvas']
    if (canvas['width'], canvas['height'], canvas['fps']) not in ((1080, 1920, 30), (720, 1280, 30)):
        raise ValueError('P0 supports only 1080x1920 or 720x1280, 9:16, 30fps')
    assets = {a['id']: a for a in plan['assets']}
    def media(row, ref):
        asset = assets[row['asset_id']]
        path = Path(asset['path']).expanduser()
        item = dict(ref=ref, path=str((base / path).resolve()), start=row['start'], duration=row['end']-row['start'])
        if asset['kind'] == 'image':
            item['type'] = 'photo'
        else:
            item.update(sourceStart=row['source_in'], speed=row.get('speed', 1))
        return item
    tracks = []
    operations = []
    treatments = []
    shots = []
    for i, row in enumerate(plan['shots']):
        item = media(row, 'shot-' + str(i))
        asset = assets[row['asset_id']]
        if asset['kind'] == 'video':
            item['volume'] = video_volume(asset, row)
        shots.append(item)
        if asset.get('burned_text') == 'present':
            treatments.append(dict(ref=item['ref'], kind='shot', action=asset['text_action'],
                                   treatment_note=asset.get('treatment_note'), status='pending', evidence=[]))
    tracks.append(dict(type='video', name='主画面', items=shots))
    for role in ('narration', 'bgm', 'sfx'):
        items = []
        for i, row in enumerate(plan['audio']):
            if row['role'] != role:
                continue
            item = media(row, 'audio-' + str(i))
            volume = row.get('volume')
            if not number(volume) or not 0 <= volume <= 1:
                raise ValueError('Each audio item needs explicit volume in [0,1]')
            item['volume'] = volume
            items.append(item)
            fades = {target: row[source] for source, target in (('fade_in', 'fadeIn'), ('fade_out', 'fadeOut')) if source in row}
            if any(value > 0 for value in fades.values()):
                operations.append(dict(op='audio-fade', target=item['ref'], **fades))
        if items:
            tracks.append(dict(type='audio', name=role, items=items))
    captions = []
    native = []
    for i, row in enumerate(plan['captions']):
        visual = row.get('visual', {})
        if not isinstance(visual, dict):
            raise ValueError('caption.visual must be an object')
        for field in ('fontSize', 'x', 'y'):
            if not number(visual.get(field)):
                raise ValueError('Each caption needs calibrated visual.' + field)
        if visual['fontSize'] <= 0:
            raise ValueError('fontSize must be positive')
        import re
        if not isinstance(visual.get('color'), str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', visual['color']):
            raise ValueError('Each caption needs visual.color')
        ref = 'caption-' + str(i)
        captions.append(dict(ref=ref, text=row['text'], start=row['start'], duration=row['end']-row['start'],
                             **{k: visual[k] for k in ('fontSize', 'color', 'x', 'y')}))
        native.append(dict(ref=ref, kind='caption', cue_ids=cue_ids(row), recipe=row['recipe'],
                           font=visual.get('font'), animation=row.get('animation'), status='pending', evidence=[]))
    tracks.append(dict(type='text', name='正文', items=captions))
    # Unsupported styling must not silently disappear from a successful build.
    allowed_visual = {'fontSize', 'color', 'x', 'y', 'font'}
    if any(set(c.get('visual', {})) - allowed_visual for c in plan['captions']):
        raise ValueError('Unsupported visual fields: use documented native finishing stage')
    return dict(name=plan.get('name', '竖屏营销视频'), width=canvas['width'], height=canvas['height'],
                fps=30, ratio='9:16', tracks=tracks, operations=operations), native + treatments


def voice_script(plan):
    """Human-readable view only; storyboard remains the editable timing source."""
    lines = ['口播文稿（' + plan.get('narration', {}).get('timing', '未标记对齐状态') + '）']
    def stamp(seconds):
        milliseconds = round(seconds * 1000)
        minutes, remainder = divmod(milliseconds, 60000)
        return f'{minutes}:{remainder / 1000:06.3f}'
    for cue in plan['script']:
        interval = f"({stamp(cue['start'])}–{stamp(cue['end'])}) " if 'start' in cue else ''
        notes = []
        if cue.get('pause_after'):
            notes.append(f"句后停 {cue['pause_after']} 秒")
        if cue.get('emphasis'):
            notes.append('重读：' + '、'.join(cue['emphasis']))
        lines.append(interval + cue['text'] + ('〔' + '；'.join(notes) + '〕' if notes else ''))
    return '\n'.join(lines) + '\n'


def run(plan_path, output, build=False):
    source = Path(plan_path).resolve()
    raw = source.read_bytes()
    plan = json.loads(raw.decode('utf-8-sig'))
    spec, native = compile_plan(plan, source.parent)
    narration = plan.get('narration', {})
    if build and narration.get('mode') not in (None, 'none') and narration.get('timing') != 'aligned':
        raise ValueError('Narration is estimated: generate/listen/align audio before build; prepare remains available')
    if build:
        from delivery_steps import requirements
        if narration.get('mode') not in ('none', 'provided', 'native_tts', 'source'):
            raise ValueError('Build requires explicit narration.mode; missing is not silent-video authorization')
        task = read(source.parent / 'task.json')
        if task.get('mode') != 'create' or task.get('delivery') != plan.get('delivery', 'draft+native'):
            raise ValueError('Task mode/delivery differs from storyboard; review the request before build')
        requirements(plan, source.parent)
    # Absolute source paths and asset bytes participate in restart identity.
    media = {}
    for track in spec['tracks']:
        for item in track['items']:
            if 'path' in item and item['path'] not in media:
                with open(item['path'], 'rb') as stream:
                    media[item['path']] = hashlib.file_digest(stream, 'sha256').hexdigest()
    digest = hashlib.sha256(raw + json.dumps(spec, sort_keys=True).encode() + json.dumps(media, sort_keys=True).encode()).hexdigest()
    root = Path(output).resolve() / digest
    root.mkdir(parents=True, exist_ok=True)
    manifest = root / 'delivery.json'
    if manifest.exists():
        state = read(manifest)
        if state['input_sha256'] != digest or read(root / 'compile.json') != spec:
            raise ValueError('Existing run was modified; use a new output directory')
    else:
        write(root / 'storyboard.json', plan)
        write(root / 'compile.json', spec)
        write(root / 'native-finishing.json', native)
        (root / 'voice-script.txt').write_text(voice_script(plan), encoding='utf-8')
        (root / 'tts.txt').write_text('\n'.join(c['text'] for c in plan['script']) + '\n', encoding='utf-8')
        state = dict(input_sha256=digest, source=str(source), media_sha256=media,
                     mode=plan.get('delivery', 'draft+native'), stage='prepared',
                     draft=None, installed='pending', native_preview='pending', native_export='pending',
                     native_finishing='pending', audio_mix='pending', errors=[])
        if state['mode'] not in ('draft', 'draft+native', 'video-only'):
            raise ValueError('delivery must be draft, draft+native or explicit video-only')
        if state['mode'] == 'draft':
            state['native_export'] = 'not_requested'
        write(manifest, state)
    if build and state['stage'] != 'compiled':
        draft = root / 'draft'
        if draft.exists():
            raise ValueError('Partial or unrecorded draft exists; inspect it and use a new output directory; never overwrite')
        try:
            binary = capcut_cmd()
            version = subprocess.run([binary, '--version'], capture_output=True, timeout=30)
            if version.returncode:
                raise ValueError('capcut --version failed')
            state['capcut_version'] = (version.stdout or b'').decode('utf-8', errors='replace').strip()
            argv = [binary, 'compile', str(root / 'compile.json'), '--out', str(draft)]
            result = subprocess.run(argv, capture_output=True, timeout=300)
            stdout = (result.stdout or b'').decode('utf-8', errors='replace')
            stderr = (result.stderr or b'').decode('utf-8', errors='replace')
            write(root / 'compile-result.json', dict(argv=['capcut', 'compile', str(root / 'compile.json'), '--out', str(draft)], returncode=result.returncode, stdout=stdout, stderr=stderr))
            if result.returncode:
                raise ValueError('capcut compile failed; see compile-result.json')
            response = json.loads(stdout)
            if response.get('ok') is not True:
                raise ValueError('capcut did not confirm compilation')
            candidate = Path(response['file_path']).resolve()
            if not candidate.is_relative_to(draft) or not candidate.is_file():
                raise ValueError('Compiler returned an unexpected draft path')
            state.update(stage='compiled', draft=str(draft), draft_file=str(candidate),
                         draft_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(), refs=response.get('refs', {}), errors=[])
            # Cheap structural proxy; never substitutes for native preview.
            try:
                from delivery_steps import proxy_preview
                state['proxy_preview'] = proxy_preview(root, draft, tag='compiled')
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as preview_error:
                state['proxy_preview'] = dict(ok=False, error=str(preview_error), mode='approximate')
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            state.update(stage='failed', errors=[str(exc)])
            write(manifest, state)
            raise
        write(manifest, state)
    if state['stage'] == 'compiled':
        candidate = Path(state['draft_file'])
        if not candidate.is_file() or hashlib.sha256(candidate.read_bytes()).hexdigest() != state['draft_sha256']:
            raise ValueError('Built draft changed; preserve native edits and use existing-draft workflow')
    return dict(run_dir=str(root), **state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('start', 'prepare', 'build', 'finish', 'install', 'verify',
                                            'status', 'narrate', 'retime', 'bootstrap', 'preview'))
    parser.add_argument('path', nargs='?', help='start/narrate: project or storyboard; prepare/build: storyboard; '
                        'finish/install/verify/status/preview: run directory; bootstrap: ignored')
    parser.add_argument('--out', help='project-local build directory / retimed storyboard / resources json')
    parser.add_argument('--request', help='actual user request; required for start')
    parser.add_argument('--mode', choices=('create', 'edit', 'export', 'script'), default='create')
    parser.add_argument('--delivery', choices=('draft', 'draft+native', 'video-only'), default='draft+native')
    parser.add_argument('--resources', help='verified native animation resources JSON for finish')
    parser.add_argument('--store', help='confirmed live draft store for install')
    parser.add_argument('--evidence', help='current native visual/audio/export evidence JSON for verify')
    parser.add_argument('--from-dir', help='narration audio directory for retime')
    parser.add_argument('--durations', help='JSON {script_id: seconds} for retime')
    parser.add_argument('--audio-dir', default='narration', help='relative narration folder for narrate')
    parser.add_argument('--in-place', action='store_true', help='overwrite storyboard on retime')
    parser.add_argument('--names', nargs='*', help='animation names for bootstrap')
    parser.add_argument('--from-draft', help='seed bootstrap from a saved draft')
    parser.add_argument('--tag', default='manual', help='preview output tag')
    args = parser.parse_args()
    try:
        if args.command in ('start', 'finish', 'install', 'verify', 'preview'):
            from delivery_steps import start, finish, install, verify, proxy_preview
            if args.command == 'start':
                result = start(args.path, args.mode, args.delivery, args.request or '')
            elif args.command == 'finish':
                if not args.resources:
                    parser.error('--resources is required for finish')
                result = finish(args.path, args.resources)
            elif args.command == 'install':
                if not args.store:
                    parser.error('--store is required for install')
                result = install(args.path, args.store)
            elif args.command == 'preview':
                root = Path(args.path).resolve()
                state = read(root / 'delivery.json')
                draft = Path(state.get('finished_draft') or state.get('draft') or root / 'draft')
                result = proxy_preview(root, draft, tag=args.tag)
            else:
                result = verify(args.path, args.evidence)
        elif args.command == 'status':
            result = read(Path(args.path) / 'delivery.json')
        elif args.command == 'narrate':
            from timeline_ops import narrate_plan
            source = Path(args.path).resolve()
            plan = read(source if source.is_file() else source / 'storyboard.json')
            project = source.parent if source.is_file() else source
            result = narrate_plan(plan, project, args.audio_dir)
            write(project / 'narration-checklist.json', result)
            result = dict(result, checklist=str(project / 'narration-checklist.json'))
        elif args.command == 'retime':
            from timeline_ops import retime
            from validate_storyboard import validate as validate_plan
            source = Path(args.path).resolve()
            plan = read(source)
            durations = read(args.durations) if args.durations else None
            updated = retime(plan, durations=durations, from_dir=args.from_dir,
                             evidence=args.evidence or 'Measured cue audio; listen before build')
            target = Path(args.out).resolve() if args.out else (source if args.in_place else None)
            if target is None:
                raise ValueError('retime needs --in-place or --out')
            write(target, updated)
            report = validate_plan(updated, source.parent)
            result = dict(ok=report['ok'], storyboard=str(target), duration=updated['duration'],
                          narration=updated.get('narration'), errors=report['errors'],
                          warnings=report.get('warnings', []))
        elif args.command == 'bootstrap':
            from bootstrap_resources import bootstrap
            out = Path(args.out or (Path(args.path or '.') / 'native-resources.json')).resolve()
            bundled = bootstrap(names=args.names, from_draft=args.from_draft)
            write(out, bundled['resources'])
            write(out.with_suffix('.meta.json'), bundled['meta'])
            result = dict(ok=bundled['ok'], out=str(out), count=len(bundled['resources']),
                          unresolved=bundled['meta']['unresolved'], missing=bundled['meta']['missing'],
                          effect_roots=bundled['meta']['effect_roots'],
                          meta=str(out.with_suffix('.meta.json')))
        else:
            if not args.out:
                parser.error('--out is required for prepare/build')
            result = run(args.path, args.out, args.command == 'build')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get('ok') is False:
            return 1
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

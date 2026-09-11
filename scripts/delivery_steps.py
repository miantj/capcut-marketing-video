"""Deterministic finishing, installation and delivery gates. Native UI stays a human/agent check."""
import copy
import hashlib
import json
import shutil
import subprocess
import uuid
from pathlib import Path

from check_installed_draft import check as check_installed


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def write(p, data):
    p = Path(p)
    tmp = p.with_suffix(p.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(p)


def sha(p):
    with Path(p).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def command(args, log):
    r = subprocess.run(args, capture_output=True, text=True, timeout=300)
    write(log, dict(argv=args, returncode=r.returncode, stdout=r.stdout, stderr=r.stderr))
    if r.returncode:
        raise ValueError('Command failed; see ' + str(log))
    return json.loads(r.stdout)


def start(project, mode, delivery, request):
    if not request.strip():
        raise ValueError("Record the actual user request before planning")
    root = Path(project).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (root / 'task.json').exists():
        raise ValueError('task.json already exists; read it and resume, do not reset progress')
    steps = {
        'create': ['分析需求和交付物', '原文/口播文稿', '盘点并审阅素材', '生成配音并实测对齐', '分镜与样式设计', 'prepare', 'build', 'finish', 'install', '原生预览/试听', '按需导出', 'verify'],
        'edit': ['确认修改范围', 'inspect_inputs --draft', 'snapshot_draft', '在独立副本用capcut修改', '检查改动与原样式', '安装/注册修改副本', '原生预览/试听', '按需导出', '核对交付'],
        'export': ['确认最新来源', 'inspect_inputs --draft', 'snapshot_draft', '原生导出', '完整解码和来源比对'],
        'script': ['保存原文与疑点', '口播断句/停顿/重音', '预计时间标注', '交付文稿'],
    }[mode]
    result = dict(version=1, mode=mode, delivery=delivery, user_request=request, steps=steps,
                  instruction='Follow in order. Script errors block dependent steps, not independent work. No manual passed flags.')
    write(root / 'task.json', result)
    return result


def requirements(plan, base):
    """Fail before compile if required design is absent; exceptions need an explicit user reason."""
    if not isinstance(plan.get('source_text'), str) or not plan['source_text'].strip():
        raise ValueError('Preserve the original source_text before building')
    for cap in plan['captions']:
        v, a = cap.get('visual', {}), cap.get('animation', {})
        font = v.get('font', {})
        if not font.get('id') or not font.get('path') or not (base / font['path']).is_file():
            raise ValueError('Each caption requires an existing font.path and native font.id')
        if not all(a.get(k) for k in ('intro', 'outro', 'purpose')):
            raise ValueError('Each caption requires intro, outro and semantic purpose')
        for k in ('intro_seconds', 'outro_seconds'):
            if a.get(k) != .5 and not plan.get('style_exceptions', {}).get('animation_reason'):
                raise ValueError('Default animation is 0.5s; a user override needs animation_reason')
        if cap.get('keywords') and (not isinstance(cap['keywords'], list) or any(not isinstance(k, str) or not k or k not in cap['text'] for k in cap['keywords'])):
            raise ValueError('Keyword not present in caption text')
        bubble = cap.get('bubble')
        if bubble and (not isinstance(bubble, dict) or not bubble.get('text') or
                       any(not isinstance(bubble.get(k), (int, float)) for k in ('x', 'y', 'width', 'height')) or
                       bubble['width'] <= 0 or bubble['height'] <= 0):
            raise ValueError('Bubble needs text, x, y, positive width and height')
    for field in ('keywords', 'bubble'):
        if not any(c.get(field) for c in plan['captions']) and not plan.get('style_exceptions', {}).get(field + '_reason'):
            raise ValueError('Missing ' + field + ': plan it, or record the explicit user exception')


def compiled(root):
    root = Path(root).resolve()
    state = read(root / 'delivery.json')
    result = read(root / 'compile-result.json')
    response = json.loads(result['stdout'])
    if result.get('argv', [])[:2] != ['capcut', 'compile']:
        raise ValueError('Missing recorded capcut compile command; do not fabricate historical evidence')
    if result.get('returncode') != 0 or response.get('ok') is not True or not state.get('refs'):
        raise ValueError('No successful capcut compile evidence; doctor/register/MP4 cannot substitute')
    expected = (root / 'draft').resolve()
    draft = Path(state['draft_file']).resolve()
    if not draft.is_relative_to(expected) or not draft.is_file() or sha(draft) != state['draft_sha256']:
        raise ValueError('Compiled source changed or disappeared; preserve edits, do not overwrite')
    return root, state, read(root / 'storyboard.json'), draft


def finish(run_dir, resources_file):
    root, state, plan, source = compiled(run_dir)
    base = Path(state['source']).parent
    requirements(plan, base)
    resources = read(resources_file)
    for cap in plan['captions']:
        for k in ('intro', 'outro'):
            name = cap['animation'][k]
            resource = resources.get(name)
            resource_path = resource.get('path') if isinstance(resource, dict) else None
            if not isinstance(resource_path, str) or not resource_path.strip() or not Path(resource_path).is_dir():
                raise ValueError('Missing verified native text animation resource: ' + name)
    dest = root / 'finished'
    if dest.exists():
        raise ValueError('Finished draft already exists; verify/resume it instead of replacing edits')
    d = read(source)
    mats = {m['id']: m for m in d['materials']['texts']}
    segments = {s['id']: s for t in d['tracks'] for s in t['segments']}
    bubble_track = dict(id=str(uuid.uuid4()), type='text', name='气泡', segments=[], attribute=0, flag=0)
    for i, cap in enumerate(plan['captions']):
        seg = segments[state['refs']['caption-' + str(i)]]
        mat = mats[seg['material_id']]
        visual = cap['visual']
        font = dict(visual['font'], path=str((base / visual['font']['path']).resolve()))
        mat.update(font_path=font['path'], font_resource_id=font['id'], font_size=visual['fontSize'],
                   border_color='#202526', border_width=.035, border_alpha=1, has_shadow=True,
                   shadow_color='#000000', shadow_alpha=.65, text_alpha=1, global_alpha=1)
        content = json.loads(mat['content'])
        style = copy.deepcopy(content['styles'][0])
        style.update(font=font, size=visual['fontSize'])
        text = content['text']
        highlight = set()
        for key in cap.get('keywords', []):
            offset = 0
            while (at := text.find(key, offset)) >= 0:
                highlight.update(range(at, at + len(key)))
                offset = at + len(key)
        runs = []
        for index, char in enumerate(text):
            hot = index in highlight
            if runs and runs[-1][2] == hot:
                runs[-1][1] = index + 1
            else:
                runs.append([index, index + 1, hot])
        content['styles'] = []
        for lo, hi, hot in runs:
            s = copy.deepcopy(style)
            s['range'] = [len(text[:lo].encode('utf-16-le')) // 2, len(text[:hi].encode('utf-16-le')) // 2]
            if hot:
                s['fill'] = {'alpha': 1, 'content': {'solid': {'color': [1, .886, .388], 'alpha': 1}, 'render_type': 'solid'}}
                s['bold'] = True
            content['styles'].append(s)
        mat['content'] = json.dumps(content, ensure_ascii=False)
        animations = []
        for mode, key in (('in', 'intro'), ('out', 'outro')):
            a = copy.deepcopy(resources[cap['animation'][key]])
            length = round(cap['animation'][key + '_seconds'] * 1e6)
            a.update(type=mode, duration=length, start=0 if mode == 'in' else seg['target_timerange']['duration'] - length)
            animations.append(a)
        am = dict(id=str(uuid.uuid4()), type='sticker_animation', multi_language_current='none', animations=animations)
        d['materials'].setdefault('material_animations', []).append(am)
        old_anim = {x['id'] for x in d['materials']['material_animations']}
        seg['extra_material_refs'] = [r for r in seg.get('extra_material_refs', []) if r not in old_anim] + [am['id']]
        if cap.get('bubble'):
            b = cap['bubble']
            bm, bs = copy.deepcopy(mat), copy.deepcopy(seg)
            bm.update(id=str(uuid.uuid4()), font_size=visual['fontSize'] - 2, text_color='#202526',
                      background_color=b.get('color', '#FFE263'), background_alpha=1, background_style=1,
                      background_round_radius=.2, background_width=b['width'], background_height=b['height'])
            cs = copy.deepcopy(style)
            cs.update(size=visual['fontSize'] - 2, range=[0, len(b['text'].encode('utf-16-le')) // 2])
            cs['fill'] = {'alpha': 1, 'content': {'solid': {'color': [.125, .145, .149], 'alpha': 1}, 'render_type': 'solid'}}
            bm['content'] = json.dumps(dict(text=b['text'], styles=[cs]), ensure_ascii=False)
            bs.update(id=str(uuid.uuid4()), material_id=bm['id'], render_index=seg.get('render_index', 0) + 100)
            bs['clip']['transform'] = dict(x=b['x'], y=b['y'])
            d['materials']['texts'].append(bm)
            bubble_track['segments'].append(bs)
            state['refs']['bubble-' + str(i)] = bs['id']
    if bubble_track['segments']:
        d['tracks'].append(bubble_track)
    shutil.copytree(source.parent, dest)
    for name in ('draft_content.json', 'draft_info.json'):
        write(dest / name, d)
    state.update(finished_draft=str(dest), finished_sha256=sha(dest / 'draft_content.json'))
    write(root / 'delivery.json', state)
    result = check_styles(dest, plan, state['refs'], base)
    write(root / 'style-check.json', result)
    if not result['ok']:
        raise ValueError('Style verification failed; see style-check.json')
    return dict(**result, next_step='install', draft=str(dest), native_preview='pending')


def check_styles(draft, plan, refs, base):
    d = read(Path(draft) / 'draft_content.json')
    errors = []
    materials = {m['id']: m for a in d['materials'].values() if isinstance(a, list) for m in a if isinstance(m, dict) and 'id' in m}
    segments = {s['id']: s for t in d['tracks'] for s in t['segments']}
    video_ranges = []
    for track in d.get('tracks', []):
        if track.get('type') != 'video':
            continue
        for segment in track.get('segments', []):
            timerange = segment.get('target_timerange', {})
            clip = segment.get('clip') or {}
            if segment.get('visible') is False or float(clip.get('alpha', 1) or 0) <= 0:
                continue
            try:
                start = float(timerange['start'])
                end = start + float(timerange['duration'])
            except (KeyError, TypeError, ValueError):
                continue
            video_ranges.append((start, end))
    duration = round(float(plan.get('duration', 0)) * 1e6)
    video_ranges.sort()
    cursor = 0.0
    for start, end in video_ranges:
        if start > cursor + 1:
            break
        cursor = max(cursor, end)
    if not video_ranges or cursor < duration - 1:
        errors.append('Missing visible main video coverage')
    for i, cap in enumerate(plan['captions']):
        name = 'caption-' + str(i)
        s = segments.get(refs.get(name), {})
        m = materials.get(s.get('material_id'), {})
        clip = s.get('clip') or {}
        if s.get('visible') is False or float(clip.get('alpha', 1) or 0) <= 0:
            errors.append('Caption is hidden: ' + name)
        transform = clip.get('transform') or {}
        if any(isinstance(transform.get(k), (int, float)) and abs(transform[k]) > 1.25 for k in ('x', 'y')):
            errors.append('Caption is off-screen: ' + name)
        if not m:
            errors.append('Missing editable ' + name)
            continue
        c = json.loads(m.get('content', '{}'))
        font = cap['visual'].get('font', {})
        path = str((base / font.get('path', '')).resolve())
        wanted = dict(start=round(cap['start'] * 1e6), duration=round((cap['end']-cap['start']) * 1e6))
        if s.get('target_timerange') != wanted:
            errors.append('Caption timing mismatch: ' + name)
        if m.get('font_size') != cap['visual']['fontSize'] or any(x.get('size') != cap['visual']['fontSize'] for x in c.get('styles', [])):
            errors.append('Font size not applied: ' + name)
        if c.get('text') != cap['text']:
            errors.append('Text mismatch: ' + name)
        if not Path(path).is_file() or m.get('font_path') != path or m.get('font_resource_id') != font.get('id') or any(
                x.get('font', {}).get('path') != path or x.get('font', {}).get('id') != font.get('id') for x in c.get('styles', [])) or not c.get('styles'):
            errors.append('Font not applied to actual text: ' + name)
        for keyword in cap.get('keywords', []):
            at = cap['text'].find(keyword)
            lo = len(cap['text'][:at].encode('utf-16-le')) // 2
            hi = lo + len(keyword.encode('utf-16-le')) // 2
            hot = set()
            for st in c.get('styles', []):
                colour = st.get('fill', {}).get('content', {}).get('solid', {}).get('color')
                if st.get('bold') and colour == [1, .886, .388]:
                    hot.update(range(*st['range']))
            if not set(range(lo, hi)) <= hot:
                errors.append('Missing keyword styling: ' + name + ' ' + keyword)
        actual = [a for r in s.get('extra_material_refs', []) for a in materials.get(r, {}).get('animations', [])]
        for kind, key in (('in', 'intro'), ('out', 'outro')):
            expected = cap['animation'][key]
            length = round(cap['animation'][key + '_seconds'] * 1e6)
            start = 0 if kind == 'in' else s['target_timerange']['duration'] - length
            if not any(a.get('type') == kind and a.get('name') == expected and a.get('duration') == length and
                       a.get('start') == start and Path(a.get('path', '')).is_dir() for a in actual):
                errors.append('Missing/wrong native animation: ' + name + ' ' + kind)
        if cap.get('bubble'):
            bs = segments.get(refs.get('bubble-' + str(i)), {})
            bm = materials.get(bs.get('material_id'), {})
            bc = json.loads(bm.get('content', '{}'))
            if bc.get('text') != cap['bubble']['text'] or bm.get('font_size') != cap['visual']['fontSize'] - 2 or not bm.get('background_color') or bm.get('background_alpha', 0) <= 0 or not bc.get('styles') or any(st.get('size') != cap['visual']['fontSize'] - 2 or st.get('font', {}).get('path') != path for st in bc.get('styles', [])):
                errors.append('Missing editable bubble/background: ' + name)
    for i, audio in enumerate(plan.get('audio', [])):
        s = segments.get(refs.get('audio-' + str(i)), {})
        if not s or abs(s.get('volume', 0) - audio['volume']) > .001:
            errors.append('Missing or changed audio volume: audio-' + str(i))
        expected = dict(start=round(audio['start']*1e6), duration=round((audio['end']-audio['start'])*1e6))
        if s.get('target_timerange') != expected:
            errors.append('Audio timing mismatch: audio-' + str(i))
    return dict(ok=not errors, errors=errors, native_ui_verified=False)


def install(run_dir, store):
    root, state, plan, _ = compiled(run_dir)
    src, store = Path(state['finished_draft']).resolve(), Path(store).resolve()
    report = check_styles(src, plan, state['refs'], Path(state['source']).parent)
    if not report['ok'] or sha(src / 'draft_content.json') != state['finished_sha256']:
        raise ValueError('Finished draft changed or style gate failed; inspect before installing')
    index = store / 'root_meta_info.json'
    if not index.is_file():
        raise ValueError('Use the confirmed live store with root_meta_info.json; do not invent a store')
    before = index.read_bytes()
    # Use the actual project name, never register a generic directory named finished.
    name = read(src / 'draft_content.json')['name']
    if not name or Path(name).name != name or name in ('.', '..'):
        raise ValueError('Unsafe project name')
    dst = store / name
    ident = read(src / 'draft_content.json')['id']
    if any(e.get('draft_id') == ident for e in json.loads(before).get('all_draft_store', [])):
        raise ValueError('Project identity already exists in this store; preserve the installed project')
    source_sha = sha(src / 'draft_content.json')
    marker = dst / '.capcut-install-marker.json'
    if dst.exists():
        owned = False
        if marker.is_file():
            try:
                marker_data = read(marker)
                owned = marker_data.get('run_dir') == str(root) and marker_data.get('source_sha256') == source_sha
            except (OSError, ValueError, TypeError):
                owned = False
        if not owned:
            raise ValueError('Destination already exists; check installed draft, never overwrite user edits')
        shutil.rmtree(dst)
    staging = store / ('.' + name + '.installing-' + uuid.uuid4().hex)
    write(root / 'install-plan.json', dict(source=str(src), destination=str(dst), staging=str(staging), store=str(store), status='preparing'))
    (root / 'root-index-before-install.json').write_bytes(before)
    try:
        shutil.copytree(src, staging)
        write(staging / '.capcut-install-marker.json', dict(run_dir=str(root), source_sha256=source_sha, draft_id=ident))
        staging.rename(dst)
        # Relink only material paths, do not replace strings inside user text.
        for filename in ('draft_content.json', 'draft_info.json'):
            d = read(dst / filename)
            for group in ('videos', 'audios'):
                for m in d['materials'].get(group, []):
                    if not m.get('path'):
                        continue
                    original = Path(m['path']).expanduser()
                    if not original.is_absolute():
                        original = Path(state['source']).parent / original
                    if not original.is_file():
                        raise ValueError('Unresolved media path: ' + str(original))
                    target = dst / 'assets' / (sha(original)[:16] + original.suffix)
                    target.parent.mkdir(exist_ok=True)
                    if not target.exists():
                        shutil.copy2(original, target)
                    m['path'] = str(target)
            write(dst / filename, d)
        meta_path = dst / 'draft_meta_info.json'
        meta = read(meta_path) if meta_path.exists() else {}
        meta.update(draft_id=ident, draft_name=name, draft_fold_path=str(dst), draft_root_path=str(store),
                    draft_json_file=str(dst / 'draft_content.json'), tm_draft_removed=0, draft_is_invisible=False)
        write(meta_path, meta)
        cmd = ['capcut', 'register', str(dst), '--materials', '--drafts', str(store)]
        p = command(cmd, root / 'register-plan.json')
        if p.get('project_dir') != str(dst) or p.get('store_root') != str(store) or index.read_bytes() != before:
            raise ValueError('Unexpected registration target or concurrently changed index; no index write attempted')
        command(cmd + ['--apply'], root / 'register-result.json')
        result = check_installed(dst, store)
        write(root / 'installation-check.json', result)
        if not result['ok']:
            raise ValueError('Installation failed verification; see installation-check.json')
        state.update(installed_draft=str(dst), store=str(store), installed='passed', installed_sha256=sha(dst / 'draft_content.json'))
        write(root / 'delivery.json', state)
        (dst / '.capcut-install-marker.json').unlink(missing_ok=True)
        return dict(**result, next_step='native_preview_and_export')
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def verify(run_dir, evidence_file=None):
    root, state, plan, _ = compiled(run_dir)
    checks = []
    def add(step, ok, detail):
        checks.append(dict(step=step, ok=bool(ok), detail=detail))
    try:
        requirements(plan, Path(state['source']).parent)
        add('design_plan', True, 'Required font, animations and decorations are present')
    except ValueError as e:
        add('design_plan', False, str(e))
    draft = Path(state.get('installed_draft') or state.get('finished_draft') or root / 'missing')
    try:
        style = check_styles(draft, plan, state['refs'], Path(state['source']).parent)
        add('styles', style['ok'], style['errors'])
    except (OSError, ValueError, KeyError, TypeError) as e:
        add('styles', False, str(e))
    installed = state.get('installed_draft') and state.get('store')
    result = check_installed(draft, state['store']) if installed else None
    if state['mode'] != 'video-only':
        add('installation', result and result['ok'], result or 'No installed editable draft; an MP4 is insufficient')
    evidence = read(evidence_file) if evidence_file else {}
    digest = sha(draft / 'draft_content.json') if (draft / 'draft_content.json').is_file() else None
    current = digest and evidence.get('draft_sha256') == digest
    for kind in ('visual', 'audio'):
        if kind == 'audio' and not plan.get('audio') and plan.get('narration', {}).get('mode') == 'none':
            continue
        e = evidence.get(kind, {})
        files = e.get('files', [])
        # The reviewer supplies findings; the script checks attachment existence and source binding only.
        ok = current and e.get('reviewed') is True and bool(e.get('findings')) and bool(files) and all(Path(f).is_file() for f in files)
        if kind == 'visual':
            ok = ok and e.get('surface') == 'native' and set(e.get('moments', [])) >= {'intro', 'hold', 'outro', 'longest', 'cta'}
        add(kind + '_review', ok, 'Review needs current draft hash, actual evidence files and observations')
    if state['mode'] != 'draft':
        e = evidence.get('video', {})
        video = Path(e.get('path', ''))
        ok = current and video.is_file() and e.get('draft_sha256') == digest
        mode = e.get('mode')
        ok = ok and (mode == 'native' or (mode == 'approximate' and bool(e.get('authorization')) and bool(e.get('differences'))))
        if ok:
            probe = command(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(video)], root / 'video-probe.json')
            ok = abs(float(probe['format']['duration']) - plan['duration']) <= .25 and any(s['codec_type'] == 'video' for s in probe['streams'])
            if plan.get('audio') or plan.get('narration', {}).get('mode') == 'source':
                ok = ok and any(s['codec_type'] == 'audio' for s in probe['streams'])
            proc = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video), '-f', 'null', '-'], capture_output=True, text=True, timeout=300)
            write(root / 'video-decode.json', dict(returncode=proc.returncode, stderr=proc.stderr))
            ok = ok and proc.returncode == 0
        add('video', ok, 'Video must decode, match timing and be attributed to this draft; approximate remains labelled')
    missing = [c['step'] for c in checks if not c['ok']]
    result = dict(ok=not missing, checks=checks, next_step=missing[0] if missing else 'done',
                  note='Scripts verify structure and evidence binding, not whether visual/audio observations are truthful.')
    write(root / 'verification.json', result)
    return result

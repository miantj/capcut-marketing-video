"""Narrow Windows compatibility fixes for capcut-cli 0.23's probe/font gaps."""
import json
import re
import shutil
from pathlib import Path

from .media import ProductionError, probe, run


def align_render_frames(graph, document, fps):
    """Keep per-clip EOF rounding from accumulating across concatenated clips.

    Use cumulative timeline boundaries, so fractional source cuts do not each
    introduce their own rounded frame error. Pad at most two frames to cover
    frame-grid/EOF rounding; larger missing source ranges still fail validation.
    """
    tracks = [t for t in document['tracks'] if t['type'] == 'video']
    if len(tracks) != 1:
        raise ProductionError('当前预览仅支持一条主视频轨。')
    segments = sorted(tracks[0]['segments'], key=lambda s: s['target_timerange']['start'])
    parts, count = [], 0
    for part in graph.split(';'):
        match = re.fullmatch(r'(.*)\[v(\d+)\]', part)
        if match and part.startswith('[') and re.match(r'^\[\d+:v\]', part):
            index = int(match[2])
            if index >= len(segments):
                raise ProductionError('预览镜头与草稿不一致。')
            timing = segments[index]['target_timerange']
            start = round(timing['start'] * fps / 1_000_000)
            end = round((timing['start'] + timing['duration']) * fps / 1_000_000)
            if end <= start:
                raise ProductionError('镜头时长不足一帧，请调整素材。')
            part = (f'{match[1]},tpad=stop_mode=clone:stop_duration={2/fps:.9f},'
                    f'trim=end_frame={end-start},setpts=N/({fps}*TB)[v{index}]')
            count += 1
        parts.append(part)
    if count != len(segments):
        raise ProductionError('无法校准全部预览镜头，请检查剪辑工具版本。')
    return ';'.join(parts)


def repair_material_durations(draft, settings, log):
    path = draft / 'draft_content.json'
    document = json.loads(path.read_text('utf-8-sig'))
    cache = {}
    for category in ('videos', 'audios'):
        for material in document.get('materials', {}).get(category, []):
            source = material.get('path')
            if source:
                cache.setdefault(source, None)
                if cache[source] is None:
                    cache[source] = probe(settings.ffmpeg, source)
                material['duration'] = round(cache[source]['duration'] * 1_000_000)
    for material in document.get('materials', {}).get('texts', []):
        if material.get('font_path') or material.get('font_resource_id'):
            continue
        material['font_name'] = 'Microsoft YaHei'
        material['font_path'] = ''
    path.write_text(json.dumps(document, ensure_ascii=False), 'utf-8')
    run([*settings.capcut, 'sync-timelines', draft, '--apply', '--force-write'], log=log)
    # Verify source ranges against full source durations, not segment lengths.
    materials = {m['id']: m for category in ('videos', 'audios') for m in document.get('materials', {}).get(category, [])}
    for track in document['tracks']:
        if track['type'] not in ('video', 'audio'):
            continue
        for segment in track['segments']:
            source = segment['source_timerange']
            if source['start'] + source['duration'] > materials[segment['material_id']]['duration'] + 10000:
                raise ProductionError('草稿源区间超出实际素材时长。')
    return document


def render_chinese_preview(settings, draft, output, folder, log):
    # Reuse the CLI's actual draft -> FFmpeg plan. Only substitute the missing
    # Chinese font/text-file support; do not rebuild an unrelated video timeline.
    completed = run([*settings.capcut, 'render', draft, '--out', output, '--scale', '.5', '--dry-run'], log=log)
    report = json.loads(completed.stdout.splitlines()[0])
    args = report['args']
    graph_index = args.index('-filter_complex') + 1
    map_index = args.index('-map') + 1
    label = args[map_index]
    document = json.loads((draft / 'draft_content.json').read_text('utf-8-sig'))
    from .subtitles import write_ass
    ass_path = folder / 'preview-subtitles.ass'
    subtitle_report = write_ass(document, report['width'], report['height'], ass_path)
    if not subtitle_report['font_paths']:
        raise ProductionError('草稿缺少实际字体路径。')
    font_dir = folder / 'preview-fonts'
    font_dir.mkdir(exist_ok=True)
    shutil.copy2(subtitle_report['font_paths'][0], font_dir / 'HYYouRanTiJ.ttf')
    font_folder = font_dir.resolve().as_posix().replace(':', '\\:')
    graph = align_render_frames(report['filterComplex'], document, report['fps'])
    graph += f";{label}ass=filename='preview-subtitles.ass':fontsdir='{font_folder}'[styledtext]"
    label = '[styledtext]'
    args[graph_index], args[map_index] = graph, label
    # Web preview must be seekable without downloading the complete file first.
    args[-1:-1] = ['-movflags', '+faststart']
    run([settings.ffmpeg, '-hide_banner', '-nostdin', *args], cwd=folder, log=log)
    report.update(executed=True, filterComplex=graph, **subtitle_report)
    (folder/'render-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    return report

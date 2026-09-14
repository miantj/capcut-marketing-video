import json
import math
import re
import subprocess
from pathlib import Path


class ProductionError(Exception):
    pass


def validate_preview(info, expected):
    if not info['video']:
        raise ProductionError('预览没有检测到视频画面，制作未完成。')
    if not info['audio']:
        raise ProductionError('预览没有检测到背景音乐音轨，制作未完成。')
    if abs(info['duration'] - expected) > .3:
        raise ProductionError(f"预览时长不一致：计划 {expected:.2f} 秒，实际 {info['duration']:.2f} 秒，"
                              f"相差 {abs(info['duration'] - expected):.2f} 秒。请重试或联系管理员检查镜头拼接。")


def failed_tool_message(completed):
    blob = '\n'.join(part for part in (completed.stderr, completed.stdout) if part)
    text = ''
    for line in reversed(blob.splitlines()):
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            text = parsed.get('error') or parsed.get('message') or ''
            if text:
                break
    lowered = text.lower()
    if 'editor-open' in lowered or 'is running' in lowered:
        return '剪映正在运行，无法写入草稿。请保存并退出剪映后重试。'
    if text:
        return f'处理工具执行失败：{text[:240]}'
    for line in reversed(blob.splitlines()):
        line = line.strip()
        if 'No such filter' in line:
            return f'处理工具执行失败：{line[:240]}'
    for line in reversed(blob.splitlines()):
        line = line.strip()
        if line.startswith('Error '):
            return f'处理工具执行失败：{line[:240]}'
    return '处理工具执行失败，管理员可查看本机制作日志。'


def run(argv, *, cwd=None, timeout=900, log=None, check=True):
    completed = subprocess.run([str(x) for x in argv], cwd=cwd, capture_output=True,
                               encoding='utf-8', errors='replace', timeout=timeout,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if log:
        with Path(log).open('a', encoding='utf-8') as out:
            out.write(json.dumps({'argv': [str(x) for x in argv], 'returncode': completed.returncode,
                                  'stdout': completed.stdout, 'stderr': completed.stderr}, ensure_ascii=False) + '\n')
    if check and completed.returncode:
        raise ProductionError(failed_tool_message(completed))
    return completed


def probe(ffmpeg, path):
    # Reject disguised playlists before FFmpeg can follow external references.
    with Path(path).open('rb') as source:
        header = source.read(32)
    valid = (header[4:8] in (b'ftyp', b'moov', b'mdat', b'wide', b'free') or
             header.startswith((b'\x1aE\xdf\xa3', b'ID3', b'RIFF', b'fLaC', b'OggS')) or
             (len(header) >= 2 and header[0] == 255 and header[1] & 224 == 224))
    if not valid:
        raise ProductionError('文件内容不是支持的视频或音频格式，请勿只修改文件扩展名。')
    output = run([ffmpeg, '-hide_banner', '-nostdin', '-protocol_whitelist', 'file,pipe', '-i', path], timeout=30, check=False).stderr
    time = re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', output)
    video = next((x for x in output.splitlines() if 'Stream #' in x and 'Video:' in x), '')
    audio = any('Stream #' in x and 'Audio:' in x for x in output.splitlines())
    size = re.search(r'\b(\d{2,5})x(\d{2,5})\b', video)
    if not time or not (video or audio):
        raise ProductionError('素材无法读取，请上传完整的视频或音频文件。')
    duration = int(time[1]) * 3600 + int(time[2]) * 60 + float(time[3])
    if not math.isfinite(duration) or duration <= 0 or duration > 7200:
        raise ProductionError('单个素材时长需在 0～120 分钟之间。')
    width, height = (int(size[1]), int(size[2])) if size else (0, 0)
    rotation = re.search(r'rotation of (-?[\d.]+) degrees', output)
    if rotation and round(abs(float(rotation[1]))) % 180 == 90:
        width, height = height, width
    return {'duration': duration, 'width': width, 'height': height, 'video': bool(video), 'audio': audio}


def script_cues(text, *, limit_estimate=True, merge_short=True):
    from .skill_timing import estimate
    # Keep every non-whitespace character; split at punctuation before using a length cap.
    pieces = re.findall(r'[^，。！？；\n]+[，。！？；]?|[，。！？；]', text)
    lines = []
    for piece in pieces:
        piece = piece.strip()
        while len(piece) > 24:
            cut = piece.rfind(' ', 0, 24)
            cut = cut if cut >= 12 else 24
            lines.append(piece[:cut].strip())
            piece = piece[cut:].strip()
        if piece:
            lines.append(piece)
    if re.sub(r'\s', '', ''.join(lines)) != re.sub(r'\s', '', text):
        raise ProductionError('文案分句校验未通过，请检查特殊字符。')
    cues = estimate(lines)
    if not merge_short:
        if limit_estimate and sum(c['duration'] for c in cues) > 180:
            raise ProductionError('第一版支持 3 分钟以内的视频，请缩短文案后重试。')
        return cues
    # Merge short screens without adding time or changing the original words.
    # This avoids padding every short clause just to make an animation fit.
    merged, pending = [], ''
    elapsed = 0.
    for cue in cues:
        pending += cue['text']
        elapsed += cue['duration']
        if elapsed >= 1.3:
            merged.append(pending)
            pending, elapsed = '', 0.
    if pending:
        if merged:
            merged[-1] += pending
        else:
            merged.append(pending)
    cues = estimate(merged)
    if limit_estimate and sum(c['duration'] for c in cues) > 180:
        raise ProductionError('第一版支持 3 分钟以内的视频，请缩短文案后重试。')
    return cues


def ordered_shots(cues, videos):
    duration = sum(c['duration'] for c in cues)
    shots, start, index = [], 0., 0
    positions = [0.] * len(videos)
    while start < duration - .001:
        slot = index % len(videos)
        video = videos[slot]
        source = positions[slot]
        available = video['media']['duration'] - source - .06
        if available < .1:
            positions[slot] = 0
            index += 1
            continue
        take = min(4.5, available, duration - start)
        shots.append({'asset_id': video['id'], 'start': round(start, 6), 'duration': round(take, 6),
                      'source_in': round(source, 6), 'reason': '按上传顺序使用素材，未进行 AI 语义判断'})
        start += take
        positions[slot] = source + take
        index += 1
    return shots


def validate_shots(shots, videos, duration):
    assets = {v['id']: v for v in videos}
    cursor = 0.
    if not shots or len(shots) > 180:
        raise ProductionError('分镜数量无效。')
    for shot in shots:
        if shot.get('asset_id') not in assets:
            raise ProductionError('分镜引用了未上传的素材。')
        for key in ('start', 'duration', 'source_in'):
            value = shot.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                raise ProductionError('分镜时间无效。')
        if abs(shot['start'] - cursor) > .04 or shot['duration'] <= 0 or shot['source_in'] < 0:
            raise ProductionError('分镜时间不连续。')
        if shot['source_in'] + shot['duration'] > assets[shot['asset_id']]['media']['duration'] + .01:
            raise ProductionError('分镜超出素材时长。')
        cursor += shot['duration']
    if abs(cursor - duration) > .05:
        raise ProductionError('分镜没有完整覆盖文案。')

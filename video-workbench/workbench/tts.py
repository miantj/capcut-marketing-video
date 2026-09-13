"""Volcengine V3 SSE synthesis; credentials never enter job records or logs."""
import base64
import http.client
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
import wave

from .media import ProductionError, run
from .speech_cache import SpeechCache, DEFAULT_RESOURCE

ENDPOINT = 'https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse'


class SpeechServiceError(ProductionError):
    """A service failure that allows a complete video without narration."""


def optional_narration(settings, request, cues, folder, progress):
    if request.get('narration', 'none') == 'none':
        return cues, [], None
    try:
        aligned, items = narrate(settings, request, cues, folder, progress)
        return aligned, items, None
    except SpeechServiceError as exc:
        # Never attach partial speech or keep speech timing on fallback.
        (folder / 'narration.wav').unlink(missing_ok=True)
        for cue in cues:
            (folder / 'narration' / f'{cue["id"]}.wav').unlink(missing_ok=True)
        return cues, [], f'自动口播不可用，已回退为字幕 + 背景音乐，按文案估算时长。原因：{exc}'


def read_audio(response):
    chunks, total = [], 0
    started = time.monotonic()
    for raw in response:
        if time.monotonic() - started > 120:
            raise SpeechServiceError('火山口播响应超时，请重试。')
        line = raw.decode('utf-8').strip()
        if not line.startswith('data:'):
            continue
        try:
            event = json.loads(line[5:])
            code = event.get('code', 0)
            if code not in (0, 20000000):
                # Do not expose provider messages, which can echo submitted values.
                raise SpeechServiceError(f'火山口播生成失败（错误码 {int(code)}），请检查服务额度、资源和音色权限。')
            if event.get('data'):
                chunk = base64.b64decode(event['data'], validate=True)
                total += len(chunk)
                if total > 32 * 1024 * 1024:
                    raise SpeechServiceError('单段口播音频超过大小限制。')
                chunks.append(chunk)
            if code == 20000000:
                if chunks:
                    return b''.join(chunks)
                break
        except (ValueError, TypeError, AttributeError):
            raise SpeechServiceError('火山口播返回数据格式异常，请重试。') from None
    raise SpeechServiceError('火山口播未完整返回音频，请重试。')


def synthesize(settings, text, speaker, speed, destination):
    if not settings.tts_ready:
        raise SpeechServiceError('火山口播尚未配置 API Key。')
    payload = {'user': {'uid': 'video-workbench'}, 'req_params': {
        'text': text, 'speaker': speaker,
        'audio_params': {'format': 'mp3', 'sample_rate': 24000,
                         'speech_rate': round((speed - 1) * 100)}}}
    request = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode(), headers={
        'Content-Type': 'application/json', 'X-Api-Key': settings.tts_key,
        'X-Api-Resource-Id': settings.tts_resource, 'X-Api-Request-Id': str(uuid.uuid4())})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            audio = read_audio(response)
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.close()
        raise SpeechServiceError(f'火山口播请求失败（HTTP {status}），请检查密钥、语音服务和音色权限后重试。') from None
    except (OSError, http.client.HTTPException, UnicodeError):
        raise SpeechServiceError('无法连接火山语音服务或请求超时，请检查网络后重试。') from None
    encoded = destination.with_suffix('.mp3')
    encoded.write_bytes(audio)
    try:
        try:
            run([settings.ffmpeg, '-hide_banner', '-nostdin', '-v', 'error', '-xerror', '-y',
                 '-protocol_whitelist', 'file,pipe', '-f', 'mp3', '-i', encoded,
                 '-ar', '24000', '-ac', '1', '-c:a', 'pcm_s16le', destination], timeout=60)
            with wave.open(str(destination), 'rb') as wav:
                duration = wav.getnframes() / wav.getframerate()
        except (ProductionError, subprocess.TimeoutExpired, wave.Error, EOFError):
            destination.unlink(missing_ok=True)
            raise SpeechServiceError('火山口播返回的音频无法解码，请重试。') from None
        if duration <= 0 or duration > 180:
            raise ProductionError('单段口播时长无效或超过 3 分钟。')
        return duration
    finally:
        encoded.unlink(missing_ok=True)


def narrate(settings, request, cues, folder, progress):
    directory = folder / 'narration'
    directory.mkdir(exist_ok=True)
    cache = SpeechCache(folder, request, getattr(settings, 'tts_resource', DEFAULT_RESOURCE))
    items, aligned, cursor = [], [], 0.
    generated, reused, index = 0, 0, 0
    while index < len(cues):
        cue = dict(cues[index])
        progress(index, len(cues))
        # Legacy audio may combine several short clauses. Reuse an exact span
        # without splitting audio or matching by position.
        hit, end = None, index + 1
        text = ''
        for next_index in range(index, len(cues)):
            text += cues[next_index]['text']
            if len(text) > 150:
                break
            candidate = cache.get(text)
            if candidate:
                hit, end, cue['text'] = candidate, next_index + 1, text
        path = directory / f'{cue["id"]}.wav'
        if hit:
            shutil.copyfile(hit[0], path)
            duration = hit[1]
            reused += 1
        else:
            duration = synthesize(settings, cue['text'], request['tts_speaker'], request['tts_speed'], path)
            cache.put(cue['text'], path)
            generated += 1
        items.append({'ref': f'narration-{index}', 'path': str(path), 'start': cursor,
                      'duration': duration, 'sourceStart': 0, 'volume': 1.0})
        aligned.append({**cue, 'start': cursor, 'duration': duration})
        cursor += duration
        index = end
        if cursor > 180:
            raise ProductionError('实际口播超过 3 分钟，请缩短文案或提高语速后重试。')
    # Merge short caption screens without stretching speech or inserting silence.
    captions = []
    for cue in aligned:
        if captions and captions[-1]['duration'] < 1.3:
            captions[-1]['text'] += cue['text']
            captions[-1]['duration'] += cue['duration']
        else:
            captions.append(dict(cue))
    if len(captions) > 1 and captions[-1]['duration'] < 1.3:
        tail = captions.pop()
        captions[-1]['text'] += tail['text']
        captions[-1]['duration'] += tail['duration']
    # All generated segments share the exact PCM format; concatenate losslessly.
    with wave.open(str(folder / 'narration.wav'), 'wb') as output:
        output.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
        for item in items:
            with wave.open(item['path'], 'rb') as source:
                output.writeframes(source.readframes(source.getnframes()))
    (folder / 'narration-stats.json').write_text(json.dumps({'reused': reused, 'generated': generated,
        'segments': len(items), 'resource': cache.profile['resource']}), 'utf-8')
    return captions, items

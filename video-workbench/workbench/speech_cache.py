"""Revision-local, content-addressed speech cache. No credentials are stored."""
import hashlib
import json
import shutil
import uuid
import wave

from .media import script_cues

DEFAULT_RESOURCE = 'seed-tts-2.0'


def pcm_duration(path):
    with wave.open(str(path), 'rb') as audio:
        frames = audio.getnframes()
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, 24000, 'NONE'):
            raise ValueError('Unexpected speech format')
        if not 0 < frames <= 180 * 24000 or len(audio.readframes(frames)) != frames * 2:
            raise ValueError('Incomplete speech file')
        return frames / 24000


class SpeechCache:
    def __init__(self, folder, request, resource=DEFAULT_RESOURCE):
        self.root = folder / 'speech-cache'
        self.profile = {'version': 1, 'provider': 'volcengine-v3-sse', 'resource': resource,
                        'speaker': request['tts_speaker'],
                        'speech_rate': round((request['tts_speed'] - 1) * 100),
                        'format': 'mp3-to-pcm-s16le-mono-24000'}
        self.entries = {}
        for path in self.root.glob('*.json'):
            try:
                entry = json.loads(path.read_text('utf-8'))
                text = entry['text']
                if (isinstance(text, str) and entry['profile'] == self.profile
                        and path.stem == self.key(text)):
                    self.entries[text] = entry
            except (OSError, ValueError, KeyError, TypeError):
                continue

    def key(self, text):
        data = json.dumps([self.profile, text], ensure_ascii=False, sort_keys=True).encode()
        return hashlib.sha256(data).hexdigest()

    def get(self, text):
        entry = self.entries.get(text)
        if not entry:
            return None
        path = self.root / (self.key(text) + '.wav')
        try:
            if not path.resolve().is_relative_to(self.root.resolve()):
                return None
            if path.stat().st_size > 9 * 1024 * 1024:
                return None
            if hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
                return None
            return path, pcm_duration(path)
        except (OSError, ValueError, KeyError, wave.Error, EOFError):
            return None

    def put(self, text, source):
        pcm_duration(source)
        self.root.mkdir(exist_ok=True)
        key = self.key(text)
        entry = {'text': text, 'profile': self.profile,
                 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
        temporary = self.root / (uuid.uuid4().hex + '.tmp')
        try:
            shutil.copyfile(source, temporary)
            temporary.replace(self.root / (key + '.wav'))
            temporary.write_text(json.dumps(entry, ensure_ascii=False), 'utf-8')
            temporary.replace(self.root / (key + '.json'))
        finally:
            temporary.unlink(missing_ok=True)
        self.entries[text] = entry


def inherit_speech_cache(old, old_folder, new_folder, request, resource):
    """Snapshot needed audio before queuing, so deleting the parent is safe."""
    if request['narration'] != 'volcengine':
        return
    target = SpeechCache(new_folder, request, resource)
    source = SpeechCache(old_folder, request, resource)
    new_text = ''.join(c['text'] for c in script_cues(request['script'], limit_estimate=False, merge_short=False))
    for text in source.entries:
        if text in new_text:
            hit = source.get(text)
            if hit:
                target.put(text, hit[0])
    # Before caching was introduced, the deployed default was seed-tts-2.0.
    # Import successful legacy segment files using their ORIGINAL request, not
    # aligned/merged captions or the new request's segment numbers.
    result = (old.get('result') or {}).get('narration') or {}
    if source.root.exists() or result.get('provider') != 'volcengine':
        return
    original = old['request']
    legacy = SpeechCache(old_folder, original, result.get('resource', DEFAULT_RESOURCE))
    if legacy.profile != target.profile:
        return
    for cue in script_cues(original['script'], limit_estimate=False):
        path = old_folder / 'narration' / (cue['id'] + '.wav')
        if cue['text'] not in new_text or not path.resolve().is_relative_to(old_folder.resolve()):
            continue
        try:
            pcm_duration(path)
        except (OSError, ValueError, wave.Error, EOFError):
            continue
        target.put(cue['text'], path)

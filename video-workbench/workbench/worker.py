import json
import threading
import traceback

from .ai import select_shots
from .compat import repair_material_durations, render_chinese_preview
from .media import ProductionError, ordered_shots, probe, run, script_cues, validate_shots, validate_preview
from .packaging import package_draft
from .skill_timing import evidence as timing_evidence
from .skill_timing import skill_module
from .caption_style import native_resources, caption_plan, compile_and_finish


class Worker:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.thread = threading.Thread(target=self.loop, daemon=True, name='video-worker')

    def start(self):
        self.store.recover()
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.wake.set()
        self.thread.join(timeout=1)

    def loop(self):
        while not self.stop_event.is_set():
            job_id = self.store.claim()
            if job_id:
                try:
                    self.process(job_id)
                except Exception as exc:
                    folder = self.settings.data / 'jobs' / job_id
                    (folder / 'error.log').write_text(traceback.format_exc(), 'utf-8')
                    message = str(exc) if isinstance(exc, ProductionError) else '制作未完成，请管理员查看本机日志后重试。'
                    self.store.update(job_id, 'needs_attention', '需要处理', 0, error=message)
            else:
                self.wake.wait(2)
                self.wake.clear()

    def process(self, job_id):
        settings, store = self.settings, self.store
        job = store.get(job_id)
        request = job['request']
        folder = settings.data / 'jobs' / job_id
        build = folder / 'build'
        build.mkdir(exist_ok=False)
        log = folder / 'commands.jsonl'
        if not settings.ffmpeg or not settings.capcut:
            raise ProductionError('工作机缺少视频处理工具，请管理员完成环境配置。')
        videos, music = [], None
        for item in job['files']:
            item['path'] = str((folder / item['path']).resolve())
            item['media'] = probe(settings.ffmpeg, item['path'])
            if item['role'] == 'video':
                if not item['media']['video'] or item['media']['duration'] < .2:
                    raise ProductionError('上传的视频文件缺少可用画面或时长过短。')
                videos.append(item)
            else:
                if not item['media']['audio']:
                    raise ProductionError('背景音乐文件缺少音轨。')
                music = item
        if not videos or not music:
            raise ProductionError('需要至少一段视频和一首背景音乐。')
        (folder / 'asset-index.json').write_text(json.dumps(videos + [music], ensure_ascii=False, indent=2), 'utf-8')
        store.update(job_id, 'processing', '文案分句与镜头规划', 20)
        cues = script_cues(request['script'])
        duration = round(sum(c['duration'] for c in cues), 6)
        warnings = ['纯文字与背景音乐版本，未生成配音。', '近似预览不代表剪映原生效果，草稿需在目标电脑打开确认。']
        if request['selection'] == 'ai':
            store.update(job_id, 'processing', 'AI 查看关键帧并匹配文案', 28)
            inspection = folder / 'inspection'
            inspection.mkdir()
            selected = select_shots(settings, request, cues, videos, inspection)
            shots = selected['shots']
            warnings.extend(selected['warnings'])
        else:
            shots = ordered_shots(cues, videos)
            warnings.append('按素材顺序剪辑，未判断画面含义或处理原画面中的旧字幕；请在预览中检查。')
            if request['notes']:
                warnings.append('修改备注已保存。顺序剪辑不会理解自由文字指令；请通过文案、模板、音量等设置修改效果。')
        validate_shots(shots, videos, duration)
        if duration > sum(v['media']['duration'] for v in videos):
            warnings.append('文案时长超过视频素材总长，部分素材重复使用。')
        timing = timing_evidence(request['script'])
        plan = {'mode': request['selection'], 'source_text': request['script'], 'cues': cues,
                'shots': shots, 'duration': duration, 'timing_basis': timing, 'warnings': warnings}
        (folder / 'plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), 'utf-8')
        width, height = (1080, 1920) if request['ratio'] == '9:16' else (1920, 1080)
        lookup = {v['id']: v for v in videos}
        video_items = [{'ref': f'v{i}', 'path': lookup[s['asset_id']]['path'], 'start': s['start'], 'duration': s['duration'],
                        'sourceStart': s['source_in'], 'volume': 0, 'width': lookup[s['asset_id']]['media']['width'],
                        'height': lookup[s['asset_id']]['media']['height']} for i, s in enumerate(shots)]
        resources, font = native_resources(folder)
        captions = caption_plan(cues, font, width, height, request['template'])
        caption_items = []
        for i, cap in enumerate(captions):
            caption_items.append({'ref': f'caption-{i}', 'text': cap['text'], 'start': cap['start'], 'duration': cap['end']-cap['start'],
                                  **{key: cap['visual'][key] for key in ('fontSize','color','x','y')}})
        audio, cursor = [], 0.
        while cursor < duration - .001:
            take = min(music['media']['duration'], duration - cursor)
            audio.append({'ref': f'audio-{len(audio)}', 'path': music['path'], 'start': cursor,
                          'duration': take, 'sourceStart': 0, 'volume': request['bgm_volume']})
            cursor += take
        operations = [{'op': 'audio-fade', 'target': 'audio-0', 'fadeIn': min(.6, audio[0]['duration'] / 2)},
                      {'op': 'audio-fade', 'target': audio[-1]['ref'], 'fadeOut': min(1., audio[-1]['duration'] / 2)}]
        name = f'视频工作台-{job_id[:8]}-v{job["revision"]}'
        spec = {'name': name, 'width': width, 'height': height, 'fps': 30, 'ratio': request['ratio'],
                'tracks': [{'type': 'video', 'name': '主画面', 'items': video_items},
                           {'type': 'audio', 'name': '背景音乐', 'items': audio},
                           {'type': 'text', 'name': '文案字幕', 'items': caption_items}], 'operations': operations}
        store.update(job_id, 'processing', '生成可编辑剪映草稿', 45)
        style_plan = {'source_text':request['script'], 'duration':duration,
                      'canvas':{'width':width,'height':height,'fps':30}, 'captions':captions,
                      'narration':{'mode':'none','timing':'estimated'},
                      'audio':[{'start':a['start'],'end':a['start']+a['duration'],'volume':a['volume']} for a in audio]}
        draft, style_root = compile_and_finish(settings, folder, build, spec, style_plan, resources, log)
        repair_material_durations(draft, settings, log)
        run([*settings.capcut, 'register', draft, '--materials', '--drafts', draft.parent, '--apply', '--force-write'], log=log)
        style_module = skill_module('delivery_steps')
        style_state = style_module.read(style_root/'delivery.json')
        checked = style_module.check_styles(draft, style_plan, style_state['refs'], folder)
        style_module.write(folder/'caption-style-check.json', checked)
        if not checked['ok']:
            raise ProductionError('字幕样式未通过 skill 检查，请查看 caption-style-check.json。')
        store.update(job_id, 'processing', '渲染近似预览', 65)
        preview = folder / 'preview.mp4'
        render_chinese_preview(settings, draft, preview, folder, log)
        preview_info = probe(settings.ffmpeg, preview)
        validate_preview(preview_info, duration)
        run([settings.ffmpeg, '-hide_banner', '-nostdin', '-v', 'error', '-xerror', '-i', preview,
             '-f', 'null', '-'], timeout=900, log=log)
        run([settings.ffmpeg, '-hide_banner', '-nostdin', '-loglevel', 'error', '-y', '-ss', min(1, duration/2),
             '-i', preview, '-frames:v', '1', folder / 'cover.jpg'], log=log)
        store.update(job_id, 'processing', '收集素材并校验草稿包', 90)
        manifest = package_draft(draft, folder / 'draft.zip', request['title'], duration)
        result = {'duration': duration, 'draft_name': name, 'draft_id': manifest['draft_id'],
                  'timing_basis': timing,
                  'caption_style':{'font':font['family'],'intro_seconds':.5,'outro_seconds':.5,
                                   'keyword_screens':sum(bool(c.get('keywords')) for c in captions),
                                   'bubbles':sum(bool(c.get('bubble')) for c in captions), 'skill_style_check':checked['ok']},
                  'preview_mode': 'approximate', 'native_verified': False, 'selection': request['selection'],
                  'warnings': list(dict.fromkeys(warnings)), 'files': ['draft.zip', 'preview.mp4', 'cover.jpg', 'plan.json'],
                  'package_bytes': (folder / 'draft.zip').stat().st_size, 'shot_count': len(shots), 'caption_count': len(cues)}
        store.update(job_id, 'ready', '草稿与近似预览可下载', 100, result=result)

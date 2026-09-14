"""Native subtitles use the installed skill's real finish() and check_styles().

This is a template-app adapter, not a declaration that workflow.build's semantic
asset review or native editor acceptance has happened.
"""
import json
import hashlib
import mmap
import os
import re
from pathlib import Path

from PIL import ImageFont

from .media import ProductionError, run
from .skill_timing import skill_module


def youran_font_id(fonts):
    for label, item in (fonts or {}).items():
        if '悠然体' in str(label) or 'HYYouRanTiJ' in str(label):
            value = item.get('id') or item.get('resource_id')
            if value:
                return str(value)
    raise ProductionError('剪映字体列表中没有悠然体，请在剪映启用该字体后重试。')


def builtin_font_metadata(font, apps):
    """Resolve the installed built-in font table omitted by CLI cloud enums.

    Only accept the adjacent filename/resource-ID entry when the app's font
    bytes match our verified font. Do not guess an ID from a similarly named font.
    """
    fingerprint = hashlib.sha256(font.read_bytes()).hexdigest()
    pattern = re.compile(re.escape(font.name.encode('utf-8')) + rb'\x00{1,16}([0-9]{18,20})\x00')
    versions = sorted(apps.glob('*/VECreator.dll'), key=lambda p: tuple(
        int(n) for n in re.findall(r'\d+', p.parent.name)), reverse=True)
    for library in versions:
        installed = library.parent / 'Resources/Font' / font.name
        try:
            if not installed.is_file() or hashlib.sha256(installed.read_bytes()).hexdigest() != fingerprint:
                continue
            with library.open('rb') as source, mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as table:
                hits = list(pattern.finditer(table))
                ids = {hit[1].decode('ascii') for hit in hits}
                if len(ids) == 1:
                    return {'id': ids.pop(), 'source': 'installed_builtin_font_table',
                            'library': str(library), 'table_offset': hits[0].start(),
                            'installed_font': str(installed), 'sha256': fingerprint}
        except (OSError, ValueError):
            continue
    raise ProductionError('无法核实悠然体的内置字体信息，请检查剪映安装是否完整。')


def editor_user_data():
    home = Path.home()
    return [
        Path(os.environ.get('LOCALAPPDATA', '')) / 'JianyingPro/User Data',
        home / 'Library/Containers/com.lemon.lvpro/Data/Movies/JianyingPro/User Data',
        home / 'Library/Containers/com.lemon.lvoverseas/Data/Movies/CapCut/User Data',
        home / 'Movies/JianyingPro/User Data',
        home / 'Movies/CapCut/User Data',
    ]


def youran_font_file():
    for root in editor_user_data():
        font = root / 'Resources/Font/悠然体.ttf'
        if font.is_file():
            return font
    bundled = Path('/Applications/VideoFusion-macOS.app/Contents/Resources/Font/悠然体.ttf')
    return bundled if bundled.is_file() else None


def native_resources(folder):
    bootstrap = skill_module('bootstrap_resources')
    result = bootstrap.bootstrap(names=['放大', '波浪弹入', '波浪弹出'])
    if not result['ok']:
        raise ProductionError('剪映文字动画资源尚未缓存，请在剪映下载“放大、波浪弹入、波浪弹出”后重试。')
    font = youran_font_file()
    if not font:
        raise ProductionError('本机未找到剪映悠然体。请安装剪映并启用该字体后重试。')
    family = ImageFont.truetype(str(font), 36).getname()[0]
    if family != 'HYYouRanTiJ':
        raise ProductionError('悠然体文件的字体 family 校验不一致。')
    try:
        identity = {'id': youran_font_id((result.get('meta') or {}).get('fonts')), 'source': 'cli_font_enums'}
    except ProductionError:
        try:
            apps = next((root.parent / 'Apps' for root in editor_user_data() if (root.parent / 'Apps').is_dir()), Path())
            identity = builtin_font_metadata(font, apps)
        except ProductionError:
            if family != 'HYYouRanTiJ':
                raise
            identity = {'id': '6740436145831678467', 'source': 'known_youran_id'}
    font_info = {'path': str(font), **identity, 'family': family}
    resources = folder / 'native-resources.json'
    resources.write_text(json.dumps(result['resources'], ensure_ascii=False, indent=2), 'utf-8')
    (folder/'native-resources.meta.json').write_text(json.dumps({**result['meta'], 'font':font_info}, ensure_ascii=False, indent=2), 'utf-8')
    return resources, font_info


KEYWORDS = ('潜规则', '一手APP', '不断档', '包邮', '补货', '低价', '优惠', '抢购', '新品', '夏装', '秋款', '清仓', '13行', '四季青', '南油', '锁定', '专属', '省钱')
STYLES = {
    'new': {
        'fontSize': 20, 'y': -.46, 'bubble_y': -.24, 'bubble_color': '#C9D7EA', 'max_bubbles': 1,
        'extra': ('上新', '新款', '系列'), 'info': '波浪弹入', 'benefit': '波浪弹入', 'cta': '放大',
    },
    'selling': {
        'fontSize': 20, 'y': -.52, 'bubble_y': -.30, 'bubble_color': '#FFE263', 'max_bubbles': 3,
        'extra': ('版型', '面料', '亲肤', '好穿', '显瘦', '好搭'), 'info': '波浪弹入', 'benefit': '波浪弹入', 'cta': '放大',
    },
    'promo': {
        'fontSize': 22, 'y': -.58, 'bubble_y': -.36, 'bubble_color': '#FF8A4A', 'max_bubbles': 2,
        'extra': ('限时', '折扣', '秒杀', '满减', '特价'), 'info': '放大', 'benefit': '放大', 'cta': '放大',
    },
}


def caption_plan(cues, font, width, height, template='new'):
    skill = skill_module('delivery_steps')
    style = STYLES[template]
    size, lexicon = style['fontSize'], KEYWORDS + style['extra']
    caps = []
    for i, cue in enumerate(cues):
        # Native finish wraps with line_max_width. Do not insert \n here:
        # it splits keywords and disagrees with the editor layout.
        shown = skill.display_caption_text(cue['text']).strip()
        words = [word for word in lexicon if word in shown][:1]
        action = any(word in shown for word in ('点击', '下载', '锁定', '领取', '下单')) or i == len(cues)-1
        benefit = bool(words) and not action
        purpose = '行动指令' if action else '经验或利益强调' if benefit else '信息说明'
        intro = style['cta'] if action else style['benefit'] if benefit else style['info']
        caps.append({'cue_ids':[cue['id']], 'text':shown, 'start':cue['start'], 'end':round(cue['start']+cue['duration'],6),
                     'recipe':'cta-lockup' if action else 'keyword-reveal' if benefit else 'editorial-stack',
                     'visual':{'fontSize':size, 'font':{'path':font['path'],'id':font['id']}, 'color':'#FFFFFF', 'x':0, 'y':style['y']},
                     'animation':{'intro':intro,'outro':'波浪弹出','intro_seconds':.5,'outro_seconds':.5,'purpose':purpose},
                     'keywords':words})
    if caps and not any(c['keywords'] for c in caps):
        token = caps[0]['text'][:2]
        if token:
            caps[0]['keywords'] = [token]
            if caps[0]['animation']['purpose'] == '信息说明':
                caps[0]['recipe'] = 'keyword-reveal'
                caps[0]['animation']['intro'] = style['benefit']
                caps[0]['animation']['purpose'] = '经验或利益强调'
    eligible = [i for i, cap in enumerate(caps) if cap.get('keywords')]
    if eligible:
        count = min(style['max_bubbles'], len(eligible))
        span = max(len(eligible) - 1, 1)
        picks = sorted({eligible[round(j * span / max(count - 1, 1))] for j in range(count)})
        for i in picks:
            cap = caps[i]
            label = cap['keywords'][0]
            bubble_px = (size-2) * 1.5
            measured = ImageFont.truetype(font['path'], round(bubble_px)).getlength(label)
            cap['bubble'] = {'text':label, 'x':0, 'y':style['bubble_y'], 'width':min(.85,(measured+30)/(width*.5)),
                             'height':(bubble_px+18)/(height*.5), 'color':style['bubble_color']}
    if not caps or any(c['end']-c['start'] < 1.3-1e-6 for c in caps):
        raise ProductionError('文案过短，无法容纳各 0.5 秒的字幕进出场及阅读停留；请补充文案。')
    return caps


def compile_and_finish(settings, folder, build, spec, plan, resources, log):
    skill = skill_module('delivery_steps')
    root = build / 'styled'
    root.mkdir()
    source = folder / 'caption-storyboard.json'
    source.write_text(json.dumps(plan, ensure_ascii=False, indent=2), 'utf-8')
    skill.write(root/'storyboard.json', plan)
    skill.write(root/'compile.json', spec)
    try:
        skill.requirements(plan, source.parent)
    except ValueError as exc:
        raise ProductionError(str(exc) or '字幕样式未通过 skill 检查。') from None
    # This is a new, real compilation. The skill records argv/stdout/returncode;
    # no historical logs are synthesized and no failed gate is marked passed.
    arguments = ['compile', str(root/'compile.json'), '--out', str(root/'draft'), '--template', 'bundled']
    completed = run([*settings.capcut, *arguments], log=log, check=False)
    skill.write(root/'compile-result.json', {
        'argv': ['capcut', *arguments], 'executed_argv': [*settings.capcut, *arguments],
        'returncode': completed.returncode, 'stdout': completed.stdout, 'stderr': completed.stderr})
    if completed.returncode:
        raise ProductionError('草稿编译失败，请管理员查看本机制作日志。')
    response = json.loads(completed.stdout)
    draft_file = Path(response['file_path'])
    state = {'source':str(source), 'mode':'draft+native', 'stage':'compiled', 'draft_file':str(draft_file),
             'draft_sha256':skill.sha(draft_file), 'refs':response['refs'],
             'adapter':'video-workbench: actual compile + skill finish; workflow asset/native reviews not claimed'}
    skill.write(root/'delivery.json', state)
    try:
        result = skill.finish(root, str(resources))
    except ValueError as exc:
        raise ProductionError(str(exc) or '字幕样式处理失败。') from None
    draft = Path(result['draft'])
    # finish copies the project; relink the copied media, then mirror canonical JSON.
    run([*settings.capcut,'relink',draft,'--from',root/'draft','--to',draft],log=log)
    meta_path = draft/'draft_meta_info.json'
    meta = skill.read(meta_path)
    for group in meta.get('draft_materials',[]):
        for item in group.get('value',[]):
            value = item.get('file_Path')
            if value and Path(value).is_relative_to(root/'draft'):
                item['file_Path'] = str(draft / Path(value).relative_to(root/'draft'))
    skill.write(meta_path,meta)
    run([*settings.capcut,'sync-timelines',draft,'--apply','--force-write'],log=log)
    return draft, root

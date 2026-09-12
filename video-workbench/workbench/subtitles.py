"""Styled approximate preview derived from native text materials (libass)."""
import json
import re

from PIL import ImageFont


def stamp(seconds):
    centiseconds = round(seconds * 100)
    hours, remaining = divmod(centiseconds, 360000)
    minutes, remaining = divmod(remaining, 6000)
    secs, cents = divmod(remaining, 100)
    return f'{hours}:{minutes:02}:{secs:02}.{cents:02}'


def colour(rgb):
    return '&H' + ''.join(f'{max(0,min(255,round(c*255))):02X}' for c in reversed(rgb[:3])) + '&'


def rich_text(content, *, font_path=None, pixels=None, max_width=None):
    font = ImageFont.truetype(str(font_path), max(1, round(pixels))) if font_path and max_width else None
    parts, utf16, previous, line = [], 0, None, ''
    for char in content['text']:
        style = next((s for s in content['styles'] if s['range'][0] <= utf16 < s['range'][1]), content['styles'][0])
        fill = style.get('fill',{}).get('content',{}).get('solid',{}).get('color',[1,1,1])
        key = (tuple(fill), bool(style.get('bold')))
        if key != previous:
            parts.append('{\\c' + colour(fill) + ('\\b1}' if key[1] else '\\b0}'))
            previous = key
        if char == '\n' or (font and line and font.getlength(line + char) > max_width):
            parts.append('\\N')
            line = ''
            if char == '\n':
                utf16 += len(char.encode('utf-16-le'))//2
                continue
        parts.append(char.replace('\\','\\\\').replace('{','\\{').replace('}','\\}'))
        line += char
        utf16 += len(char.encode('utf-16-le'))//2
    return ''.join(parts)


def write_ass(document, width, height, target):
    materials = {m['id']:m for category in document['materials'].values() if isinstance(category,list)
                 for m in category if isinstance(m,dict) and 'id' in m}
    sizes = [m['font_size'] for m in materials.values() if isinstance(m.get('font_size'), (int, float))]
    # Style Fontsize drives libass line gap; keep it with override \\fs or wrapped
    # lines sit on a 36px stride while glyphs are twice as tall.
    style_px = max(sizes) * height / 320 if sizes else 36
    rows = [f'[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n',
        '[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
        f'Style: Body,HYYouRanTiJ,{style_px:g},&H00FFFFFF,&H00FFFFFF,&H00262520,&H90000000,0,0,0,0,100,100,0,0,1,1.5,1,5,20,20,20,1',
        '[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    count, bubble_count, font_paths = 0, 0, set()
    for track in document['tracks']:
        if track['type'] != 'text':
            continue
        for segment in track['segments']:
            material = materials[segment['material_id']]
            content = json.loads(material['content'])
            font_path = material.get('font_path')
            if font_path:
                font_paths.add(font_path)
            transform = segment.get('clip',{}).get('transform',{})
            x = round(width/2 * (1+transform.get('x',0)))
            y = round(height/2 * (1-transform.get('y',0)))
            start = segment['target_timerange']['start']/1_000_000
            end = start + segment['target_timerange']['duration']/1_000_000
            # Measured 2026-09-12 against native 悠然体 export (font_size 25 on
            # 1080x1920): ~7 glyphs/line, so ASS px ≈ font_size * canvas_h / 320.
            # height/640 was half that and kept long captions on one line.
            pixels = material['font_size'] * height / 320
            clip_scale = segment.get('clip', {}).get('scale', {})
            scale_x = 100 * clip_scale.get('x', 1)
            scale_y = 100 * clip_scale.get('y', 1)
            milliseconds = round((end-start)*1000)
            animations = [a for ref in segment.get('extra_material_refs',[]) for a in materials.get(ref,{}).get('animations',[])]
            intro = next((a['name'] for a in animations if a.get('type') == 'in'), '放大')
            # Font, text, positions, colors and timing come from the actual draft.
            # Native animation presets are approximated, never called native rendering.
            if intro == '波浪弹入':
                enter = '\\fscx88\\fscy88\\t(0,300,\\fscx106\\fscy106)\\t(300,500,\\fscx100\\fscy100)'
            else:
                enter = '\\fscx85\\fscy85\\t(0,500,\\fscx100\\fscy100)'
            # Apply native static scale throughout the approximate animation,
            # including its settled state and exit, instead of resetting to 100%.
            enter = re.sub(r'\\fsc([xy])(\d+)',
                           lambda m: '\\fsc' + m[1] + f'{int(m[2]) * (scale_x if m[1] == "x" else scale_y) / 100:g}', enter)
            line_max = material.get('line_max_width')
            max_width = width * line_max if isinstance(line_max, (int, float)) and line_max > 0 else width * 0.926
            styled = rich_text(content, font_path=font_path, pixels=pixels, max_width=max_width)
            tags = f'{{\\an5\\pos({x},{y})\\fs{pixels:g}\\fad(500,500){enter}\\t({milliseconds-500},{milliseconds},\\fscx{scale_x*.9:g}\\fscy{scale_y*.9:g})}}'
            if track.get('name') == '气泡':
                bubble_count += 1
                bw, bh = material.get('background_width'), material.get('background_height')
                if isinstance(bw, (int, float)) and isinstance(bh, (int, float)) and bw > 0 and bh > 0:
                    box_width = max(1, round(abs(bw) * width * 2 * scale_x / 100))
                    box_height = max(1, round(abs(bh) * height * 2 * scale_y / 100))
                else:
                    font = ImageFont.truetype(font_path, max(1, round(pixels)))
                    box_width = round((font.getlength(content['text']) + 28 * height / 960) * scale_x / 100)
                    box_height = round((pixels + 18 * height / 960) * scale_y / 100)
                # Rounded vector backing, like skill.finish's editable native bubble.
                left, top, radius = x-box_width//2, y-box_height//2, max(1, round(9 * height / 960))
                right, bottom = left+box_width, top+box_height
                drawing = (f'm {left+radius} {top} l {right-radius} {top} b {right} {top} {right} {top} {right} {top+radius} '
                           f'l {right} {bottom-radius} b {right} {bottom} {right} {bottom} {right-radius} {bottom} '
                           f'l {left+radius} {bottom} b {left} {bottom} {left} {bottom} {left} {bottom-radius} '
                           f'l {left} {top+radius} b {left} {top} {left} {top} {left+radius} {top}')
                hex_color = str(material.get('background_color') or '#FFE263').removeprefix('#')
                fill = f'&H{hex_color[4:6]}{hex_color[2:4]}{hex_color[0:2]}&' if len(hex_color) == 6 else '&H63E2FF&'
                rows.append(f'Dialogue: 1,{stamp(start)},{stamp(end)},Body,,0,0,0,,{{\\an7\\pos(0,0)\\p1\\bord0\\shad0\\c{fill}\\fad(500,500)}}{drawing}{{\\p0}}')
                tags = f'{{\\an5\\pos({x},{y})\\fs{pixels:g}\\fscx{scale_x:g}\\fscy{scale_y:g}\\bord0\\shad0\\fad(500,500)}}'
                styled = rich_text(content)
            rows.append(f'Dialogue: 2,{stamp(start)},{stamp(end)},Body,,0,0,0,,{tags}{styled}')
            count += 1
    target.write_text('\n'.join(rows)+'\n','utf-8-sig')
    return {'textOverlays':count,'bubbleOverlays':bubble_count,'font_paths':sorted(font_paths),
            'font_size_mode': 'calibrated: 悠然体 font_size * canvas_h / 320',
            'animation_mode':'approximate native presets; 0.5s intro/outro', 'captionFont':'HYYouRanTiJ'}

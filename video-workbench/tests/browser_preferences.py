"""UI preferences and unavailable-TTS submission; no paid speech calls."""
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    context = browser.new_context(viewport={'width':390, 'height':844})
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.route('**/api/health', lambda route: route.fulfill(json={'ready':True,'ai_ready':True,'tts_ready':False}))
    page.goto('http://127.0.0.1:8765')
    page.get_by_text('工作机已连接',exact=True).wait_for()
    assert page.locator('#narration').input_value() == 'volcengine'
    assert not page.locator('#tts-option').is_disabled()
    page.locator('#owner').fill('缓存测试')
    page.locator('#narration').select_option('none')
    page.locator('[name=template][value=promo]').check()
    page.locator('#volume').fill('0')
    page.locator('#volume').dispatch_event('input')
    page.reload()
    assert page.locator('#owner').input_value() == '缓存测试'
    assert page.locator('#narration').input_value() == 'none'
    assert page.locator('[name=template][value=promo]').is_checked()
    assert page.locator('#volume-value').inner_text() == '0%'
    assert page.locator('#tts-settings').is_hidden()
    page.locator('#narration').select_option('volcengine')
    assert page.locator('#volume').input_value() == '0'
    page.reload()
    assert page.locator('#narration').input_value() == 'volcengine'
    assert page.locator('#volume').input_value() == '0'
    # Confirm a missing API key does not prevent submission of automatic narration.
    page.locator('#title').fill('无 API 回退测试')
    page.locator('#script').fill('这是一段用于验证提交行为的文案。')
    page.locator('#videos').set_input_files({'name':'test.mp4','mimeType':'video/mp4','buffer':b'test'})
    page.locator('#music').set_input_files({'name':'test.wav','mimeType':'audio/wav','buffer':b'test'})
    submitted = []
    def capture(route):
        submitted.append(route.request.post_data_json)
        route.fulfill(status=409,json={'detail':'浏览器测试到此停止，不创建任务'})
    page.route('**/api/jobs', lambda route: capture(route) if route.request.method == 'POST' else route.continue_())
    page.locator('#submit').click()
    page.get_by_text('浏览器测试到此停止，不创建任务',exact=False).wait_for()
    assert submitted[0]['narration']=='volcengine'
    assert submitted[0]['bgm_volume']==0
    assert submitted[0]['template']=='promo'
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
    page.screenshot(path=str(root/'verification/preferences-mobile.png'),full_page=True)
    page.locator('#tts-voice').select_option('custom')
    page.locator('#tts-speaker').fill('custom_voice_id')
    page.locator('#tts-speed').select_option('1.5')
    page.locator('#ratio').select_option('16:9')
    page.locator('#selection').select_option('ai')
    page.locator('#allow-cloud').check()
    page.reload()
    assert page.locator('#tts-voice').input_value() == 'custom'
    assert page.locator('#tts-speaker').input_value() == 'custom_voice_id'
    assert page.locator('#tts-speed').input_value() == '1.5'
    assert page.locator('#ratio').input_value() == '16:9'
    assert page.locator('#selection').input_value() == 'ai'
    assert page.locator('#cloud-consent').is_visible()
    assert not page.locator('#allow-cloud').is_checked()
    preview = []
    def capture_preview(route):
        preview.append(route.request.post_data_json)
        route.fulfill(status=409,json={'detail':'测试试听长度，不调用接口'})
    page.route('**/api/tts/preview', capture_preview)
    text = '这是一段超过二十字的试听文本，用于确认仅发送前二十个字符进行试听。'
    page.locator('#script').fill(text)
    page.locator('#tts-preview').click()
    page.get_by_text('测试试听长度，不调用接口',exact=True).wait_for()
    assert preview[0]['text'] == text[:20]
    assert preview[0]['speaker'] == 'custom_voice_id'
    assert preview[0]['speed'] == 1.5
    assert page.locator('#tts-preview').inner_text() == '生成试听（前 20 字）'
    # Editing while a response is pending must discard the old result.
    pending = []
    page.unroute('**/api/tts/preview')
    page.route('**/api/tts/preview', lambda route: pending.append(route))
    with page.expect_request('**/api/tts/preview'):
        page.locator('#tts-preview').click()
    page.locator('#script').fill('这是修改后的试听文案。')
    pending[0].fulfill(status=200, content_type='audio/wav', body=b'old-audio')
    assert page.locator('#tts-preview-result').is_hidden()
    assert page.locator('#tts-preview').inner_text() == '生成试听（前 20 字）'
    # Disabled speech must not submit a stale invalid custom voice ID.
    page.locator('#tts-speaker').fill('无效 音色')
    page.locator('#narration').select_option('none')
    page.locator('#selection').select_option('ordered')
    page.locator('#title').fill('关闭口播测试')
    page.locator('#videos').set_input_files({'name':'test.mp4','mimeType':'video/mp4','buffer':b'test'})
    page.locator('#music').set_input_files({'name':'test.wav','mimeType':'audio/wav','buffer':b'test'})
    page.locator('#submit').click()
    page.get_by_text('浏览器测试到此停止，不创建任务',exact=False).wait_for()
    assert submitted[-1]['narration'] == 'none'
    assert submitted[-1]['tts_speaker'] == 'zh_female_vv_uranus_bigtts'
    page.evaluate("localStorage.setItem('video-workbench-preferences-v1', '{bad json')")
    page.reload()
    assert page.locator('#narration').input_value() == 'volcengine'
    assert page.locator('#volume').input_value() == '15'
    assert not errors, errors
    blocked = browser.new_context()
    blocked.add_init_script("Object.defineProperty(window, 'localStorage', {get() {throw new Error('blocked')}})")
    other = blocked.new_page()
    other.goto('http://127.0.0.1:8765')
    other.get_by_text('工作机已连接',exact=True).wait_for()
    other.locator('#narration').select_option('none')
    assert other.locator('#tts-settings').is_hidden()
    print('PASS: default on, preferences survive reload, zero volume, switch preserves volume, missing API allows submission, corrupt/blocked storage, mobile layout.')
    browser.close()

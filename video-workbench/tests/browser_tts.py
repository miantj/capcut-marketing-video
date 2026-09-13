import json
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[1]
with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1100}, accept_downloads=True)
    errors=[]
    page.on('pageerror',lambda e: errors.append(str(e)))
    page.goto('http://127.0.0.1:8765')
    page.wait_for_function("() => !document.getElementById('tts-option').disabled")
    page.locator('#script').fill('你好，这是视频工作台的自动口播测试。')
    page.locator('#narration').select_option('volcengine')
    assert page.locator('#volume').input_value()=='15'
    page.locator('#tts-speed').select_option('1.25')
    page.locator('#tts-preview').click()
    page.locator('#tts-preview-result').wait_for(state='visible',timeout=90000)
    page.wait_for_function("() => document.getElementById('tts-preview-audio').duration > 0")
    duration=page.locator('#tts-preview-audio').evaluate('(a)=>a.duration')
    with page.expect_download() as dl:
        page.locator('#tts-preview-download').click()
    dl.value.save_as(root/'verification/browser-tts.wav')
    page.screenshot(path=str(root/'verification/tts-desktop.png'),full_page=True)
    page.locator('#tts-voice').select_option('custom')
    assert page.locator('#tts-speaker').is_visible()
    page.locator('#tts-speaker').fill('zh_female_vv_uranus_bigtts')
    page.set_viewport_size({'width':390,'height':844})
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
    page.screenshot(path=str(root/'verification/tts-mobile.png'),full_page=True)
    page.locator('#narration').select_option('none')
    assert page.locator('#tts-settings').is_hidden()
    assert not errors, errors
    report={'ok':True,'preview_seconds':duration,'download_bytes':(root/'verification/browser-tts.wav').stat().st_size,'page_errors':errors}
    (root/'verification/tts-browser-report.json').write_text(json.dumps(report,indent=2),'utf-8')
    print(json.dumps(report))
    browser.close()

"""Browser submission, downloads, revision, mobile layout. Uses a running local app."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sample = json.loads((ROOT/'verification/latest-smoke.json').read_text('utf-8'))
folder = Path(sample['folder'])
with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    context = browser.new_context(viewport={'width':1440,'height':1100}, accept_downloads=True)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(os.environ.get('VIDEO_TEST_URL', 'http://127.0.0.1:8766'))
    page.get_by_text('工作机已连接', exact=True).wait_for()
    page.locator('#title').fill('流程验收 · 可编辑草稿')
    page.locator('#owner').fill('系统验收')
    page.locator('#videos').set_input_files(folder/'uploads/sample.mp4')
    page.locator('#music').set_input_files(folder/'uploads/music.wav')
    page.locator('#script').fill('上传素材，生成可编辑字幕。背景音乐独立成轨。')
    page.locator('#submit').click()
    page.get_by_text('任务已提交，制作完成后可在右侧领取。', exact=True).wait_for(timeout=30000)
    page.locator('.job-card').first.get_by_text('可下载',exact=True).wait_for(timeout=60000)
    page.locator('.job-card').first.get_by_role('button',name='查看预览').click()
    page.locator('video').wait_for()
    page.wait_for_function('() => document.querySelector("video")?.readyState >= 1')
    assert page.locator('video').evaluate('(v) => v.duration') > 0
    with page.expect_download() as info:
        page.get_by_role('link', name='下载剪映草稿包',exact=True).click()
    info.value.save_as(ROOT/'verification/browser-download.zip')
    page.screenshot(path=str(ROOT/'verification/preview-dialog.png'))
    page.get_by_role('button', name='关闭详情').click()
    page.locator('.job-card').first.get_by_role('button',name='修改一版').click()
    page.locator('#script').fill('新版本保留原素材。横屏字幕，测试价格99.9元。')
    page.locator('#ratio').select_option('16:9')
    page.locator('[name=template][value=promo]').check()
    with page.expect_response(lambda response: '/revisions' in response.url and response.request.method == 'POST') as revised:
        page.locator('#submit').click()
    revised_id = revised.value.json()['id']
    page.locator(f'[data-detail="{revised_id}"]').wait_for(timeout=30000)
    page.locator(f'[data-detail="{revised_id}"]').filter(has_text='查看预览').wait_for(timeout=60000)
    page.wait_for_function('() => document.querySelectorAll(".job-card").length >= 2')
    page.locator('#refresh').click()
    page.screenshot(path=str(ROOT/'verification/desktop-complete.png'),full_page=True)
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'), 'Desktop overflow'
    page.set_viewport_size({'width':390,'height':844})
    page.screenshot(path=str(ROOT/'verification/mobile.png'),full_page=True)
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'), 'Mobile overflow'
    page.set_viewport_size({'width':800,'height':900})
    page.evaluate('document.documentElement.style.fontSize = "200%"')
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'), 'Text enlargement overflow'
    assert not errors, errors
    (ROOT/'verification/browser-report.json').write_text(json.dumps({'ok':True,'page_errors':errors,'download_bytes':(ROOT/'verification/browser-download.zip').stat().st_size},indent=2),'utf-8')
    print('Browser submission, preview, ZIP download, revision and responsive checks passed.')
    browser.close()

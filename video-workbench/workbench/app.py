import asyncio
import hashlib
import hmac
import shutil
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from weakref import WeakValueDictionary

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import ROOT, Settings
from .models import FileRequest, JobRequest, LoginRequest, RevisionRequest, SpeechPreviewRequest
from .tts import synthesize
from .media import ProductionError
from .store import Store
from .worker import Worker

VIDEO_EXT = {'.mp4', '.mov', '.m4v', '.webm'}
AUDIO_EXT = {'.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac'}


def create_app(settings=None, start_worker=True):
    settings = settings or Settings.load()
    store = Store(settings.data)
    worker = Worker(settings, store)
    upload_locks = WeakValueDictionary()
    mutation_lock = threading.RLock()
    preview_lock = threading.Lock()
    session_secret = uuid.uuid4().hex

    @asynccontextmanager
    async def lifespan(app):
        if start_worker:
            worker.start()
        yield
        if start_worker:
            worker.stop()

    app = FastAPI(title='视频工作台', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.worker = store, worker

    def session_valid(value):
        try:
            expiry, signature = value.split('.')
            expected = hmac.new(session_secret.encode(), expiry.encode(), hashlib.sha256).hexdigest()
            return int(expiry) > time.time() and hmac.compare_digest(signature, expected)
        except (AttributeError, ValueError):
            return False

    @app.middleware('http')
    async def boundary(request, call_next):
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            if origin and urlparse(origin).netloc != request.headers.get('host'):
                return JSONResponse({'detail': '不允许跨站提交'}, status_code=403)
            if request.headers.get('sec-fetch-site') == 'cross-site':
                return JSONResponse({'detail': '不允许跨站提交'}, status_code=403)
        protected = request.url.path.startswith('/api/') and request.url.path not in ('/api/session', '/api/login')
        if settings.access_code and protected and not session_valid(request.cookies.get('video_session')):
            return JSONResponse({'detail': '请先输入团队访问码'}, status_code=401)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    def get_job(job_id):
        job = store.get(job_id)
        if not job:
            raise HTTPException(404, '任务不存在')
        return job

    def public(job):
        value = dict(job)
        value['files'] = [{k: v for k, v in f.items() if k != 'path'} for f in job['files']]
        return value

    def validate_request(body):
        if body.selection == 'ai' and not settings.ai_ready:
            raise HTTPException(409, 'AI 选片尚未配置，请选择按素材顺序剪辑')
        if body.selection == 'ai' and not body.allow_cloud_analysis:
            raise HTTPException(422, 'AI 选片需要明确同意发送关键帧和文案')

    @app.get('/api/session')
    def session(request: Request):
        return {'required': bool(settings.access_code), 'authenticated': not settings.access_code or session_valid(request.cookies.get('video_session'))}

    @app.post('/api/login')
    async def login(body: LoginRequest):
        if not settings.access_code or not hmac.compare_digest(
                hashlib.sha256(body.code.encode()).digest(),
                hashlib.sha256(settings.access_code.encode()).digest()):
            await asyncio.sleep(.5)
            raise HTTPException(401, '访问码不正确')
        expiry = str(int(time.time() + 12 * 3600))
        signature = hmac.new(session_secret.encode(), expiry.encode(), hashlib.sha256).hexdigest()
        response = JSONResponse({'ok': True})
        response.set_cookie('video_session', expiry + '.' + signature, httponly=True, samesite='strict', max_age=43200)
        return response

    @app.get('/api/health')
    def health():
        return {'ready': bool(settings.ffmpeg and settings.capcut), 'ai_ready': settings.ai_ready,
                'native_tts': False, 'tts_ready': settings.tts_ready, 'native_export': False, 'max_file_bytes': settings.max_file,
                'max_job_bytes': settings.max_job, 'free_bytes': shutil.disk_usage(settings.data).free,
                'scope': 'lan', 'templates': ['new', 'selling', 'promo']}

    @app.get('/api/jobs')
    def list_jobs():
        jobs = store.list()
        queued = sorted((j for j in jobs if j['status'] == 'queued'), key=lambda j: j['created'])
        positions = {j['id']: i + 1 for i, j in enumerate(queued)}
        return [dict(public(j), queue_position=positions.get(j['id'])) for j in jobs]

    @app.post('/api/tts/preview')
    def speech_preview(body: SpeechPreviewRequest):
        if not settings.tts_ready or not settings.ffmpeg:
            raise HTTPException(409, '口播服务尚未配置完成')
        if not body.text.strip():
            raise HTTPException(422, '请先输入口播文案')
        if not preview_lock.acquire(blocking=False):
            raise HTTPException(429, '正在生成试听，请稍后再试')
        directory = settings.data / 'tts-preview'
        path = directory / (uuid.uuid4().hex + '.wav')
        try:
            directory.mkdir(exist_ok=True)
            synthesize(settings, body.text, body.speaker, body.speed, path)
            return Response(path.read_bytes(), media_type='audio/wav')
        except ProductionError as exc:
            raise HTTPException(502, str(exc)) from None
        finally:
            preview_lock.release()
            path.unlink(missing_ok=True)

    @app.get('/api/jobs/{job_id}')
    def get(job_id: str):
        return public(get_job(job_id))

    @app.post('/api/jobs', status_code=201)
    def create(body: JobRequest):
        validate_request(body)
        with mutation_lock:
            with store.db() as db:
                active = db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('uploading','queued','processing')").fetchone()[0]
            if active >= 20:
                raise HTTPException(429, '当前任务较多，请稍后提交')
            if shutil.disk_usage(settings.data).free < settings.min_free:
                raise HTTPException(507, '工作机磁盘空间不足')
            return public(store.create(body.model_dump()))

    @app.post('/api/jobs/{job_id}/files', status_code=201)
    def create_file(job_id: str, body: FileRequest):
        with mutation_lock:
            job = get_job(job_id)
            if job['status'] != 'uploading':
                raise HTTPException(409, '任务已提交，不能再更改素材')
            ext = Path(body.name.replace('\\', '/')).suffix.lower()
            if ext not in (VIDEO_EXT if body.role == 'video' else AUDIO_EXT):
                raise HTTPException(422, '不支持该文件格式')
            if body.size > settings.max_file or sum(f['size'] for f in job['files']) + body.size > settings.max_job:
                raise HTTPException(413, '单文件最多 1GB，每个任务最多 4GB')
            if len(job['files']) >= 21 or (body.role == 'video' and sum(f['role'] == 'video' for f in job['files']) >= 20) or (body.role == 'bgm' and any(f['role'] == 'bgm' for f in job['files'])):
                raise HTTPException(422, '最多 20 段视频和 1 首背景音乐')
            file_id = uuid.uuid4().hex
            name = body.name.replace('\\', '/').split('/')[-1]
            path = f'uploads/{file_id}{ext}'
            with store.db() as db:
                db.execute('INSERT INTO files(id,job,name,role,size,path) VALUES(?,?,?,?,?,?)',
                           (file_id, job_id, name, body.role, body.size, path))
            return {'id': file_id, 'received': 0}

    @app.put('/api/jobs/{job_id}/files/{file_id}')
    async def upload(job_id: str, file_id: str, request: Request, offset: int = 0):
        lock = upload_locks.setdefault(file_id, asyncio.Lock())
        async with lock:
            job = get_job(job_id)
            if job['status'] != 'uploading':
                raise HTTPException(409, '任务已提交')
            item = next((f for f in job['files'] if f['id'] == file_id), None)
            if not item:
                raise HTTPException(404, '素材不存在')
            if offset != item['received']:
                raise HTTPException(409, f'上传偏移不一致，当前已收到 {item["received"]} 字节')
            if shutil.disk_usage(settings.data).free < settings.min_free:
                raise HTTPException(507, '工作机磁盘空间不足')
            chunks, total = [], 0
            async for chunk in request.stream():
                total += len(chunk)
                if total > 8 * 1024 * 1024 or offset + total > item['size']:
                    raise HTTPException(413, '上传块超过限制')
                chunks.append(chunk)
            if total == 0:
                raise HTTPException(422, '上传内容为空')
            payload = b''.join(chunks)
            relative = item['path']

            def persist():
                with mutation_lock:
                    if get_job(job_id)['status'] != 'uploading':
                        raise HTTPException(409, '任务已取消或提交')
                    path = settings.data / 'jobs' / job_id / relative
                    with path.open('r+b' if path.exists() else 'wb') as out:
                        out.seek(offset)
                        out.truncate(offset)
                        out.write(payload)
                    with store.db() as db:
                        db.execute('UPDATE files SET received=? WHERE id=?', (offset + total, file_id))

            await asyncio.to_thread(persist)
            return {'id': file_id, 'received': offset + total}

    @app.post('/api/jobs/{job_id}/submit')
    def submit(job_id: str):
        with mutation_lock:
            job = get_job(job_id)
            if job['status'] != 'uploading':
                raise HTTPException(409, '任务已经提交')
            roles = [f['role'] for f in job['files']]
            if 'video' not in roles or roles.count('bgm') != 1:
                raise HTTPException(422, '请上传视频素材和一首背景音乐')
            if any(f['received'] != f['size'] for f in job['files']):
                raise HTTPException(409, '素材尚未上传完成')
            store.update(job_id, 'queued', '排队中', 0)
        worker.wake.set()
        return public(get_job(job_id))

    @app.delete('/api/jobs/{job_id}')
    def delete_job(job_id: str):
        with mutation_lock:
            outcome = store.delete(job_id)
        if outcome == 'missing':
            raise HTTPException(404, '任务不存在或已删除')
        if outcome == 'busy':
            raise HTTPException(409, '上传中的任务请先取消，制作中的任务请等待完成后删除')
        if outcome == 'unsafe':
            raise HTTPException(409, '任务目录路径异常，未删除，请联系管理员')
        if outcome == 'failed':
            raise HTTPException(409, '文件清理未完成，请关闭预览或占用文件的程序后重试删除')
        return {'ok': True}

    @app.post('/api/jobs/{job_id}/cancel')
    def cancel(job_id: str):
        with mutation_lock, store.db() as db:
            changed = db.execute("UPDATE jobs SET status='cancelled',stage='已取消',updated=? WHERE id=? AND status IN ('uploading','queued')", (time.time(), job_id)).rowcount
        if not changed:
            raise HTTPException(409, '只能取消上传中或排队中的任务')
        return public(get_job(job_id))

    @app.post('/api/jobs/{job_id}/revisions', status_code=201)
    def revision(job_id: str, body: RevisionRequest):
        validate_request(body.request)
        with mutation_lock:
            old = get_job(job_id)
            if old['status'] not in ('ready', 'needs_attention', 'cancelled'):
                raise HTTPException(409, '请等待当前版本处理结束')
            roles = [f['role'] for f in old['files']]
            if ('video' not in roles or roles.count('bgm') != 1
                    or any(f['received'] != f['size'] for f in old['files'])):
                raise HTTPException(409, '原版本素材不完整，请重新上传')
            with store.db() as db:
                active = db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('uploading','queued','processing')").fetchone()[0]
            if active >= 20:
                raise HTTPException(429, '当前任务较多，请稍后提交')
            if shutil.disk_usage(settings.data).free < settings.min_free + sum(f['size'] for f in old['files']):
                raise HTTPException(507, '磁盘空间不足以创建新版本')
            new = store.create(body.request.model_dump(), old['id'], old['revision'] + 1)
            try:
                for item in old['files']:
                    file_id = uuid.uuid4().hex
                    relative = f'uploads/{file_id}{Path(item["path"]).suffix}'
                    shutil.copy2(settings.data / 'jobs' / job_id / item['path'], settings.data / 'jobs' / new['id'] / relative)
                    with store.db() as db:
                        db.execute('INSERT INTO files(id,job,name,role,size,received,path) VALUES(?,?,?,?,?,?,?)',
                                   (file_id, new['id'], item['name'], item['role'], item['size'], item['size'], relative))
                store.update(new['id'], 'queued', '新版本排队中', 0)
            except Exception:
                store.update(new['id'], 'needs_attention', '复制原素材失败', 0, error='请重新上传素材。')
                raise HTTPException(500, '复制原素材失败，原版本已保留') from None
        worker.wake.set()
        return public(get_job(new['id']))

    @app.get('/api/jobs/{job_id}/artifacts/{name}')
    def artifact(job_id: str, name: str):
        job = get_job(job_id)
        if job['status'] != 'ready' or name not in (job['result'] or {}).get('files', []):
            raise HTTPException(404, '文件尚未生成')
        path = settings.data / 'jobs' / job_id / name
        if not path.is_file():
            raise HTTPException(404, '产物文件已丢失，请重新制作一个版本')
        media = {'.zip': 'application/zip', '.mp4': 'video/mp4', '.wav': 'audio/wav', '.jpg': 'image/jpeg', '.json': 'application/json'}
        return FileResponse(path, media_type=media.get(path.suffix),
                            filename=f'{job["request"]["title"]}-v{job["revision"]}{path.suffix}' if name == 'draft.zip' else None,
                            headers={'Connection': 'close'})

    app.mount('/', StaticFiles(directory=ROOT / 'dist', html=True), name='web')
    return app


app = create_app()

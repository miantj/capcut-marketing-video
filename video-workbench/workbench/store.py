import json
import re
import shutil
import sqlite3
import time
import uuid
from contextlib import contextmanager


class Store:
    def __init__(self, data):
        self.data = data
        data.mkdir(parents=True, exist_ok=True)
        self.path = data / 'queue.sqlite3'
        with self.db() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, created REAL NOT NULL, updated REAL NOT NULL,
                    status TEXT NOT NULL, stage TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
                    request TEXT NOT NULL, parent TEXT, revision INTEGER NOT NULL DEFAULT 1,
                    error TEXT, result TEXT);
                CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status, created);
                CREATE TABLE IF NOT EXISTS files (
                    id TEXT PRIMARY KEY, job TEXT NOT NULL REFERENCES jobs(id), name TEXT NOT NULL,
                    role TEXT NOT NULL, size INTEGER NOT NULL, received INTEGER NOT NULL DEFAULT 0,
                    path TEXT NOT NULL, UNIQUE(job, path));
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, job TEXT NOT NULL REFERENCES jobs(id),
                    at REAL NOT NULL, message TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS events_job ON events(job, id);
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def create(self, request, parent=None, revision=1):
        job_id = uuid.uuid4().hex
        now = time.time()
        with self.db() as db:
            db.execute('INSERT INTO jobs(id,created,updated,status,stage,request,parent,revision) VALUES(?,?,?,?,?,?,?,?)',
                       (job_id, now, now, 'uploading', '等待上传素材', json.dumps(request, ensure_ascii=False), parent, revision))
        (self.data / 'jobs' / job_id / 'uploads').mkdir(parents=True)
        return self.get(job_id)

    def get(self, job_id):
        with self.db() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not row or row['status'] == 'deleted':
                return None
            result = dict(row)
            result['request'] = json.loads(result['request'])
            result['result'] = json.loads(result['result']) if result['result'] else None
            result['files'] = [dict(x) for x in db.execute('SELECT * FROM files WHERE job=? ORDER BY rowid', (job_id,))]
            result['events'] = [dict(x) for x in db.execute('SELECT at,message FROM events WHERE job=? ORDER BY id', (job_id,))]
            return result

    def list(self):
        with self.db() as db:
            ids = [x[0] for x in db.execute("SELECT id FROM jobs WHERE status != 'deleted' ORDER BY created DESC LIMIT 100")]
        return [job for x in ids if (job := self.get(x)) is not None]

    def delete(self, job_id):
        # Serialize with queue claims; only remove this generated task directory.
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT status FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not row:
                return 'missing'
            if row[0] in ('uploading', 'processing'):
                return 'busy'
            root = (self.data / 'jobs').resolve()
            folder = root / job_id
            if not re.fullmatch(r'[a-f0-9]{32}', job_id) or folder.resolve().parent != root:
                return 'unsafe'
            try:
                # Refuse links/junctions instead of following them outside the task.
                if folder.exists():
                    entries = [folder, *folder.rglob('*')]
                    if any(p.is_symlink() or p.is_junction() for p in entries):
                        return 'unsafe'
                    shutil.rmtree(folder)
            except OSError:
                db.execute("UPDATE jobs SET status='needs_attention',stage='删除文件失败，请重试删除',error='部分文件可能已清理，请关闭预览或占用文件的程序后重试删除。',updated=? WHERE id=?", (time.time(), job_id))
                return 'failed'
            db.execute('DELETE FROM files WHERE job=?', (job_id,))
            db.execute('DELETE FROM events WHERE job=?', (job_id,))
            db.execute('UPDATE jobs SET parent=NULL WHERE parent=?', (job_id,))
            db.execute('DELETE FROM jobs WHERE id=?', (job_id,))
            return 'deleted'

    def update(self, job_id, status, stage, progress, *, error=None, result=None):
        with self.db() as db:
            db.execute('UPDATE jobs SET status=?,stage=?,progress=?,updated=?,error=?,result=? WHERE id=?',
                       (status, stage, progress, time.time(), error, json.dumps(result, ensure_ascii=False) if result else None, job_id))
            db.execute('INSERT INTO events(job,at,message) VALUES(?,?,?)', (job_id, time.time(), stage))

    def claim(self):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE jobs SET status='processing',stage='检查素材',progress=5,updated=? WHERE id=?", (time.time(), row[0]))
            return row[0]

    def recover(self):
        with self.db() as db:
            ids = [x[0] for x in db.execute("SELECT id FROM jobs WHERE status='processing'")]
        for job_id in ids:
            self.update(job_id, 'needs_attention', '上次制作被中断，可重新制作一个版本', 0, error='工作机或服务曾停止；原文件保留。')

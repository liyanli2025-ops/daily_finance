"""Bounded local history of collected text, separate from the App database."""
from contextlib import closing
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

from ..models.news import News
from .event_observations import canonical
from .evidence import article_url
from .news_quality import excluded_reason
from .news_selection import within_window
from .time_context import china_now

ROOT=Path(__file__).resolve().parents[2]/'data/radar'


def identity(item):
    try:url=canonical(item.source_url)
    except ValueError:url=None
    return (url,item.source,hashlib.sha256(item.content.encode()).hexdigest())


class NewsArchive:
    def __init__(self,root=None):
        self.root=Path(root) if root is not None else ROOT

    def connect(self):
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        path=self.root/'news-history.db'
        connection=sqlite3.connect(path,timeout=15)
        connection.execute('PRAGMA secure_delete=ON')
        path.chmod(0o600)
        connection.row_factory=sqlite3.Row
        connection.executescript('''
            CREATE TABLE IF NOT EXISTS samples(id TEXT PRIMARY KEY, stamp TEXT, scope TEXT, coverage TEXT);
            CREATE TABLE IF NOT EXISTS documents(key TEXT PRIMARY KEY, url TEXT, source TEXT,
                body_hash TEXT, published TEXT, first_seen TEXT, last_seen TEXT, payload TEXT);
            CREATE INDEX IF NOT EXISTS document_publication ON documents(published);
        ''')
        return connection

    def save(self,news,coverage,scope,now=None):
        now=now or china_now()
        oldest=(now-timedelta(hours=24)).isoformat()
        with closing(self.connect()) as connection,connection:
            connection.execute('INSERT INTO samples VALUES (?,?,?,?)',
                (uuid.uuid4().hex,now.isoformat(),scope,json.dumps(coverage,ensure_ascii=False)))
            for item in news:
                if (not article_url(item.source_url) or not within_window(item,now,168)
                        or len(item.content.encode())>1024*1024):
                    continue
                url,source,body_hash=identity(item)
                key=hashlib.sha256((url+'\0'+source+'\0'+body_hash).encode()).hexdigest()
                data=json.loads(item.model_dump_json())
                # Archive IDs cannot collide with a provider's updated live ID.
                data['id']='history-'+key[:24]
                if item.published_at.tzinfo is not None:
                    from datetime import timezone
                    data['published_at']=item.published_at.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None).isoformat()
                connection.execute('''INSERT INTO documents VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(key) DO UPDATE SET last_seen=excluded.last_seen,payload=excluded.payload''',
                    (key,url,source,body_hash,data['published_at'],now.isoformat(),now.isoformat(),json.dumps(data,ensure_ascii=False)))
            connection.execute('DELETE FROM documents WHERE last_seen < ?',(oldest,))
            connection.execute('DELETE FROM samples WHERE stamp < ?',(oldest,))
            connection.execute('''DELETE FROM documents WHERE key IN
                (SELECT key FROM documents ORDER BY published DESC,key DESC LIMIT -1 OFFSET 15000)''')

    def load(self,hours,now=None,limit=3000):
        now=now or china_now()
        if not (self.root/'news-history.db').is_file():
            return [],dict(status='not_started',complete_window=False)
        with closing(self.connect()) as connection:
            rows=connection.execute('''SELECT * FROM documents WHERE published BETWEEN ? AND ? AND last_seen>=?
                ORDER BY last_seen DESC,published DESC,key DESC''',((now-timedelta(hours=hours)).isoformat(),now.isoformat(),
                    (now-timedelta(hours=24)).isoformat())).fetchall()
            samples=connection.execute('SELECT stamp FROM samples WHERE stamp>=? ORDER BY stamp',
                ((now-timedelta(hours=hours)).isoformat(),)).fetchall()
        news=[];seen=set();eligible=0
        for row in rows:
            key=(row['url'],row['source'])
            if key in seen:continue
            seen.add(key)  # Latest observed version only; older versions remain for audit.
            try:
                item=News.model_validate_json(row['payload'])
                if excluded_reason(item) or not within_window(item,now,hours):continue
            except (ValueError,TypeError):continue
            eligible+=1
            if len(news)<limit:news.append(item)
        stamps=[datetime.fromisoformat(row['stamp']) for row in samples]
        gaps=[round((b-a).total_seconds()/3600,2) for a,b in zip(stamps,stamps[1:])]
        return news,dict(status='sampled_history',complete_window=False,loaded=len(news),
            matching_versions=len(rows),eligible_latest_versions=eligible,truncated=eligible>limit,
            first_sample=stamps[0].isoformat() if stamps else None,
            last_sample=stamps[-1].isoformat() if stamps else None,sample_runs=len(stamps),
            largest_sample_gap_hours=max(gaps) if gaps else None,
            limitation='仅曾采集且保留的文本；小时采样也可能漏掉两次采样间被列表挤出的文章，不能称为完整历史。历史发布时间不变，首次采集时间不是发布或发生时间。')

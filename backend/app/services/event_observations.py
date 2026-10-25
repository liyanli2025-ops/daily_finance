"""Local observation history, not an omniscient measure of event dissemination."""
from contextlib import closing
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit, urlunsplit,parse_qsl,urlencode

from .time_context import china_now

ROOT=Path(__file__).resolve().parents[2]/'data/radar'


def canonical(url):
    parts=urlsplit(str(url or ''))
    if parts.scheme not in {'https','http'} or not parts.hostname:
        return None
    query=urlencode([(key,value) for key,value in parse_qsl(parts.query,keep_blank_values=True)
                     if not key.lower().startswith('utm_') and key.lower() not in {'spm','from','ref'}])
    return urlunsplit((parts.scheme,parts.netloc.lower(),parts.path,query,''))


def title_key(title):
    # Exact normalized titles only. Different titles are NOT assumed to be distinct events.
    return hashlib.sha256(re.sub(r'\W+','',title).encode()).hexdigest()


class EventObservations:
    def __init__(self,root=None):
        self.root=Path(root) if root is not None else ROOT

    def connect(self):
        self.root.mkdir(parents=True,exist_ok=True)
        connection=sqlite3.connect(self.root/'observations.db',timeout=15)
        connection.row_factory=sqlite3.Row
        connection.executescript('''
            CREATE TABLE IF NOT EXISTS runs(stamp TEXT, coverage TEXT);
            CREATE TABLE IF NOT EXISTS articles(url TEXT PRIMARY KEY, title_key TEXT,
                first_seen TEXT, last_seen TEXT, published TEXT, title TEXT, domain TEXT);
            CREATE TABLE IF NOT EXISTS versions(url TEXT, body_hash TEXT, first_seen TEXT,
                PRIMARY KEY(url,body_hash));
        ''')
        return connection

    def observe(self,news,coverage,now=None):
        now=now or china_now()
        stamp=now.isoformat()
        with closing(self.connect()) as connection, connection:
            connection.execute('INSERT INTO runs VALUES (?,?)',(stamp,json.dumps(coverage,ensure_ascii=False)))
            for item in news:
                url=canonical(item.source_url)
                if not url or not item.title or item.published_at>now:
                    continue
                connection.execute('''INSERT INTO articles VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(url) DO UPDATE SET last_seen=excluded.last_seen,
                    title=excluded.title, title_key=excluded.title_key''',
                    (url,title_key(item.title),stamp,stamp,item.published_at.isoformat(),item.title,urlsplit(url).hostname))
                body_hash=hashlib.sha256((item.content or '').strip().encode()).hexdigest()
                connection.execute('INSERT OR IGNORE INTO versions VALUES (?,?,?)',(url,body_hash,stamp))
            # Run metadata is bounded; article/version history is retained for provenance.
            connection.execute('DELETE FROM runs WHERE stamp < ?',((now-timedelta(days=30)).isoformat(),))

    def context(self,news,now=None):
        now=now or china_now()
        if not (self.root/'observations.db').exists():
            return '## 传播观察\n历史尚未建立；传播范围、独立佐证和是否已定价均未知。'
        with closing(self.connect()) as connection:
            runs=connection.execute('SELECT stamp,coverage FROM runs ORDER BY stamp DESC LIMIT 48').fetchall()
            latest=json.loads(runs[0]['coverage']) if runs else {}
            # The standalone check initially saved the media envelope directly;
            # normal collection and hourly samples wrap it under "media".
            # Read both historical layouts so failed providers stay visible.
            media=latest.get('media',latest if 'sources' in latest else {})
            sources={key:dict(status=value.get('status'),read=value.get('read'),errors=len(value.get('errors',[])))
                     for key,value in media.get('sources',{}).items()}
            coverage=dict(status=latest.get('status',media.get('status','see_sources')),
                rss_with_items=latest.get('rss_with_items'),rss_requested=latest.get('rss_requested'),
                empty_rss_status=latest.get('empty_rss_status','unknown'),sources=sources)
            lines=['## 本地传播观察（只覆盖接入来源，不是全网传播度）',
                '同标题和相同正文仅用于保守去重；异标题可能仍是同一事件。媒体域数不等于独立佐证数。',
                '首次观察时间不是事件发生时间；正文变化不是已核实新事实。低报道数不能证明未被广泛报道或尚未定价。',
                '历史观察批次：'+str(len(runs))+'；最近采样：'+(runs[0]['stamp'] if runs else '未知')+
                '；最近来源覆盖：'+json.dumps(coverage,ensure_ascii=False)+'；传播范围/独立佐证/已定价均未知。']
            for item in news[:12]:
                url=canonical(item.source_url)
                row=connection.execute('SELECT * FROM articles WHERE url=?',(url,)).fetchone()
                if not row:
                    continue
                peers=connection.execute('SELECT url,domain FROM articles WHERE title_key=? AND published>=?',
                    (row['title_key'],(now-timedelta(hours=72)).isoformat())).fetchall()
                versions=connection.execute('SELECT count(*) FROM versions WHERE url=?',(url,)).fetchone()[0]
                copies=connection.execute('''SELECT count(DISTINCT url) FROM versions WHERE body_hash IN
                    (SELECT body_hash FROM versions WHERE url=?)''',(url,)).fetchone()[0]
                from .evidence import publication_label
                lines.append(json.dumps(dict(news_id=item.id,first_seen=row['first_seen'],published=publication_label(item),
                    same_title_urls_72h=len(peers),observed_domains=sorted({peer['domain'] for peer in peers}),
                    content_versions=versions,same_body_urls=copies,independent_corroboration='unknown'),ensure_ascii=False))
            return '\n'.join(lines)

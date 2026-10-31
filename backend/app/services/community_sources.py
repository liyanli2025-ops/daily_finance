"""On-demand public participant statements. No logins, sentiment inference or LLM.

Posts, replies and quotations keep separate attribution. A user's claim never
becomes an independently verified fact merely because its page was readable.
"""
from collections import deque
from datetime import datetime,timedelta,timezone
from email.utils import parsedate_to_datetime
import hashlib,json,re,time
from pathlib import Path
from urllib.parse import urlsplit,urljoin

from bs4 import BeautifulSoup
import requests

from ..models.news import News
from .research_hub import ResearchHub
from .primary_sources import cached
from .source_health import PAUSED_PUBLIC_ARTICLES,RetiredSourceError
from .time_context import china_now

INDEXES={
    'jisilu':'https://www.jisilu.cn/',
    'taoguba':'https://www.tgb.cn/talk/talkSeq/21325',
    'tradingview':'https://www.tradingview.com/markets/stocks-usa/ideas/',
}
NAMES={'guba':'东方财富股吧','jisilu':'集思录','taoguba':'淘股吧','tradingview':'TradingView'}


def provider_for(url,index=False):
    p=urlsplit(url)
    if p.scheme!='https' or p.username or p.password or p.port not in (None,443) or p.query or p.fragment:
        raise ValueError('discussion_url_rejected')
    if index and url in INDEXES.values():return next(k for k,v in INDEXES.items() if v==url)
    if p.hostname=='guba.eastmoney.com' and re.fullmatch(r'/list,\d{6}\.html' if index else r'/news,\d{6},\d+\.html',p.path):return 'guba'
    if not index:
        if p.hostname=='www.jisilu.cn' and re.fullmatch(r'/question/\d+',p.path):return 'jisilu'
        if p.hostname=='www.tgb.cn' and re.fullmatch(r'/a/[A-Za-z0-9]+',p.path):return 'taoguba'
        if p.hostname=='www.tradingview.com' and re.fullmatch(r'/chart/[A-Za-z0-9._-]+/[A-Za-z0-9_-]+/',p.path):return 'tradingview'
    raise ValueError('discussion_url_rejected')


def plain(node):
    if node is None:return ''
    clone=BeautifulSoup(str(node),'html.parser')
    for x in clone.select('script,style,form,nav,aside'):x.decompose()
    return clone.get_text('\n',strip=True)


def stamp(value,require_timezone=False):
    value=str(value or '')
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})',value):
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
        return result.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None).isoformat()
    found=re.search(r'\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?',value)
    if found and not require_timezone:return datetime.fromisoformat(found[0]).isoformat()
    try:
        result=parsedate_to_datetime(value)
        if result.tzinfo is None:raise ValueError()
        return result.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None).isoformat()
    except (ValueError,TypeError,OverflowError):raise ValueError('discussion_publication_missing') from None


def literal_object(raw,name):
    # Decode a JSON literal only, never execute scripts/assignment expressions.
    match=re.search(r'\bvar\s+'+re.escape(name)+r'\s*=\s*',raw)
    if not match:raise ValueError('discussion_public_state_missing')
    try:value,_=json.JSONDecoder().raw_decode(raw[match.end():])
    except ValueError:raise ValueError('discussion_public_state_invalid') from None
    return value


def discover(provider,raw,url):
    if provider_for(url,True)!=provider:raise ValueError('discussion_identity_mismatch')
    soup=BeautifulSoup(raw,'html.parser');rows={}
    if provider=='guba':
        board=re.search(r'list,(\d{6})',url)[1]
        data=literal_object(raw,'article_list')
        if str(data.get('bar_code'))!=board:raise ValueError('discussion_board_mismatch')
        for row in data.get('re',[]):
            # A forum index also contains issuer/agency syndications and other
            # boards. Do not duplicate the main media feed or invent identity.
            if (str(row.get('stockbar_code'))!=board or row.get('post_type')!=0
                    or not str(row.get('post_id','')).isdigit()):continue
            target=f'https://guba.eastmoney.com/news,{board},{row["post_id"]}.html'
            rows[target]=dict(url=target,title=row.get('post_title',''),
                author=row.get('user_nickname'),updated_hint=row.get('post_last_time'),
                status='directory_not_body')
    else:
        links=soup.select('.question_list .title a[href]') if provider=='jisilu' else soup.select('a[href]')
        for a in links:
            target=urljoin(url,a['href']);title=a.get_text(' ',strip=True)
            if not title:continue
            try:
                if provider_for(target)!=provider:continue
            except ValueError:continue
            rows.setdefault(target,dict(url=target,title=title,status='directory_not_body'))
    return list(rows.values())


def statement(url,position,author,text,published,kind='personal_statement',quoted=(),require_timezone=False):
    if not text.strip():raise ValueError('discussion_body_missing')
    return dict(id=hashlib.sha256((url+'#'+position+'\0'+text).encode()).hexdigest()[:24],
        url=url,position=position,author=author or None,text=text,published_at=stamp(published,require_timezone),
        date_precision='second' if re.search(r'\d{2}:\d{2}:\d{2}',str(published)) else 'minute',
        kind=kind,verification='unverified_statement',quoted_context=list(quoted))


def parse_thread(raw,url):
    provider=provider_for(url);soup=BeautifulSoup(raw,'html.parser');records=[]
    if provider=='guba':
        row=literal_object(raw,'post_article')
        board,identifier=re.search(r'/news,(\d{6}),(\d+)\.html',url).groups()
        if (str(row.get('post_id'))!=identifier
                or str((row.get('post_guba') or {}).get('stockbar_code'))!=board):raise ValueError('discussion_identity_mismatch')
        # Keep actual body, not post title as a substitute for missing text.
        title=row.get('post_title','');author=(row.get('post_user') or {}).get('user_nickname')
        text=plain(BeautifulSoup(row.get('post_content') or '','html.parser'))
        records.append(statement(url,'post:'+identifier,author,text,row.get('post_publish_time')))
        replies_scope='回复区未解析；不把评论计数当成已读回复'
    elif provider=='jisilu':
        root=soup.select_one('.aw-question-detail-title')
        if root is None:raise ValueError('discussion_body_missing')
        title=plain(root.select_one('h1'));body=root.select_one('.aw-question-detail-txt')
        records.append(statement(url,'question',plain(root.select_one('.aw-user-name')),
            plain(body),plain(root.select_one('.aw-question-detail-meta'))))
        for node in soup.select('.aw-dynamic-topic-content'):
            content=node.select_one('.markitup-box');meta=node.select_one('.aw-dynamic-topic-meta')
            if content is None or meta is None:continue
            anchor=meta.select_one('[data-id]');identifier=anchor.get('data-id') if anchor else None
            if not identifier:continue
            clone=BeautifulSoup(str(content),'html.parser');quotes=[plain(n) for n in clone.select('blockquote')]
            for q in clone.select('blockquote'):q.decompose()
            # Mentions and quoted text are context, not assigned to the reply author.
            try:records.append(statement(url,'answer:'+identifier,
                plain(node.select_one('.publisher .aw-user-name')),plain(clone),plain(meta),quoted=quotes))
            except ValueError:continue  # Undated reply is not silently dated today.
        replies_scope='仅公开HTML当前页可见回复；引用块另列，未知被引作者不猜测'
    elif provider=='taoguba':
        title=plain(soup.select_one('#stockTitle'));author=plain(soup.select_one('.article-data .data-userid'))
        records.append(statement(url,'post',author,plain(soup.select_one('#first.article-text')),
            plain(soup.select_one('.article-data'))))
        for node in soup.select('.comment-data'):
            content=node.select_one('.comment-data-text');identifier=content.get('id') if content else None
            if not identifier:continue
            try:records.append(statement(url,identifier,plain(node.select_one('.comment-data-user .user-name')),
                plain(content),plain(node.select_one('.comment-data-user .pcyclspan'))))
            except ValueError:continue
        replies_scope='仅公开HTML当前页可见评论；评论中的转引按原文上下文保留，不推断回复树'
    else:
        root=soup.select_one('.js-publication-view')
        if root is None:raise ValueError('discussion_body_missing')
        title=plain(root.select_one('h1'));author=plain(root.select_one('a[href^="/u/"]'))
        body=root.select_one('div[class^="description-"]');clock=root.select_one('time[datetime]')
        records.append(statement(url,'idea',author,plain(body),clock.get('datetime') if clock else '',require_timezone=True))
        replies_scope='仅观点正文，未读取评论；图表图像未转为可核价格数据'
    if not title:raise ValueError('discussion_title_missing')
    return dict(provider=provider,url=url,title=title,statements=records,replies_scope=replies_scope,
        source_role='公开参与者的说法、观察或猜测；账号资历和内容均未独立核实',
        complete_thread=False)


class CommunityCollector:
    """Called explicitly for supplements; never expands legacy media scanning."""
    def __init__(self,root=None):self.hub=ResearchHub(root)

    def get(self,url,deadline,index=False):
        provider_for(url,index)
        if url in PAUSED_PUBLIC_ARTICLES:raise RetiredSourceError('source_paused_no_automatic_retest')
        def fetch():
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('discussion_time_budget_exhausted')
            r=requests.get(url,headers={'User-Agent':'Mozilla/5.0'},timeout=min(7,remaining),allow_redirects=False)
            r.raise_for_status()
            if r.status_code!=200 or len(r.content)>3*1024*1024:raise ValueError('discussion_response_invalid')
            r.encoding=r.apparent_encoding or 'utf-8'
            try:
                # Cache the raw page only if its expected structure is usable.
                discover(provider_for(url,True),r.text,url) if index else parse_thread(r.text,url)
            except ValueError as error:
                from .source_health import record_failure
                record_failure(self.hub.root,'community-page:'+url,
                    ValueError('web_research_failed_no_auto_retest'),detail_code=str(error))
                raise
            return r.text
        return cached(self.hub,'community-page:'+url,600,fetch)

    def collect(self,stocks=(),hours=72,budget=25,urls=None,existing=()):
        # The search-primary path bypasses the legacy collector's housekeeping.
        # Apply existing owned-cache expiry here; custom/test roots stay isolated.
        if self.hub.root.resolve()==Path(__file__).resolve().parents[2]/'data'/'research':
            from .material_lifecycle import prune_material_caches
            prune_material_caches()
        now=china_now();deadline=time.monotonic()+budget;cutoff=now-timedelta(hours=hours)
        queues={};errors=[];rows=[];items=[];reused=[];attempted=[];unread_directories=[]
        from .event_observations import canonical
        from .news_quality import reading_scope
        from .news_selection import within_window
        known={canonical(x.source_url):x for x in existing if hasattr(x,'content')
            and reading_scope(x) in {'public_statement','full_text','visible_body'} and within_window(x,now,hours)}
        if urls is not None:
            for url in urls:
                provider=provider_for(url);queues.setdefault(provider,deque()).append(dict(url=url,title='待读取'))
        else:
            indexes=list(INDEXES.values())
            for stock in stocks:
                if str(getattr(stock.market,'value',stock.market))=='A' and re.fullmatch(r'\d{6}',stock.code):
                    indexes.append(f'https://guba.eastmoney.com/list,{stock.code}.html')
            for index,url in enumerate(indexes):
                if time.monotonic()>=deadline:
                    unread_directories=indexes[index:];break
                try:
                    provider=provider_for(url,True)
                    found=discover(provider,self.get(url,deadline,True),url)
                    queues.setdefault(provider,deque()).extend(found)
                except Exception as error:errors.append(self.error(url,'directory',error))
        seen=set()
        # Round robin; elapsed-time budget, not a daily article quota.
        while any(queues.values()) and time.monotonic()<deadline:
            for provider,queue in queues.items():
                if not queue or time.monotonic()>=deadline:continue
                candidate=queue.popleft();url=candidate['url']
                if url in seen:continue
                seen.add(url)
                if url in known:
                    reused.append(dict(id=known[url].id,url=url,remote_version_checked=False));continue
                attempted.append(url)
                try:
                    thread=parse_thread(self.get(url,deadline),url)
                    fresh=[s for s in thread['statements'] if cutoff<=datetime.fromisoformat(s['published_at'])<=now]
                    rows.append(dict(**thread,current_statement_ids=[s['id'] for s in fresh]))
                    if not fresh:continue
                    # Old parent context may accompany new replies; keep dates
                    # per statement, never label the old claim as newly posted.
                    selected=[s for i,s in enumerate(thread['statements'])
                        if datetime.fromisoformat(s['published_at'])<=now and (i==0 or s in fresh)]
                    pieces=[]
                    for s in selected:
                        pieces.append(f'[{s["position"]} | {s["published_at"]} | 公开账号：{s["author"] or "未取得"} | 未核实说法]\n'+s['text'])
                        for quote in s['quoted_context']:pieces.append('[该回复引用的上下文；被引作者未核]\n'+quote)
                    content='\n\n'.join(pieces)
                    identifier='discussion-'+hashlib.sha256((url+'\0'+content).encode()).hexdigest()[:24]
                    related=[stock.code for stock in stocks if stock.name in thread['title'] or re.search(r'(?<!\d)'+re.escape(stock.code)+r'(?!\d)',url)]
                    items.append(News(id=identifier,title=thread['title'],content=content,
                        source='公开参与者讨论-'+NAMES[provider],source_url=url,
                        published_at=max(datetime.fromisoformat(s['published_at']) for s in fresh),
                        category='参与者说法与讨论',related_stocks=related,importance_score=.5,
                        market_impact=thread['source_role']+'；'+thread['replies_scope']+
                            '；News时间仅表示本页本次所见最新窗口内发言，每条原帖/回复时间分别保留，不是事件发生时间。'))
                except Exception as error:errors.append(self.error(url,'body',error))
        # No account profiles, emails, locations or inferred expertise are stored.
        return items,dict(status='partial' if errors or any(queues.values()) or unread_directories else 'sampled',
            read=len(items),threads=rows,reused=reused,attempted=attempted,errors=errors,
            unread_directories=unread_directories,
            unread_candidates=[row for queue in queues.values() for row in queue],
            scope='public_current_pages_not_all_forums',model_requests=0,
            limitation='按需公开参与者素材；非推荐、非事实确认或全网舆情，未获取隐藏回复。缓存复用不证明远端未更新。')

    @staticmethod
    def error(url,stage,error):
        status=getattr(getattr(error,'response',None),'status_code',None)
        message=str(error)
        reason=('http_'+str(status) if type(status) is int else message
            if re.fullmatch(r'discussion_[a-z_]+|source_paused_no_automatic_retest|cached_primary_failure:[a-z_]+',message)
            else type(error).__name__)
        return dict(url=url,stage=stage,error=type(error).__name__,reason=reason)

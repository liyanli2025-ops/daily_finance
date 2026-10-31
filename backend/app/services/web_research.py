"""Opt-in search directories and bounded public HTML reads; no snippet evidence.

Search requires an explicitly enabled account. Public reading does not transmit
that account key, cookies, or application credentials to publishers.
"""
from datetime import datetime,timedelta,timezone
import hashlib,ipaddress,json,re,socket,time
from urllib.parse import urlsplit,urljoin
import requests
import urllib3
from bs4 import BeautifulSoup
from .time_context import china_now
from .research_hub import ResearchHub
from .source_health import ensure_active,record_failure,PAUSED_PUBLIC_ARTICLES,RetiredSourceError


def failure_reason(error):
    """Preserve actionable codes, never provider responses, URLs or secrets."""
    from .source_health import permanent_reason
    status=getattr(getattr(error,'response',None),'status_code',None)
    if type(status) is int and 100<=status<=599:return 'http_'+str(status)
    code=permanent_reason(error)
    if code:return code
    code=str(error)
    if re.fullmatch(r'public_http_\d{3}',code):return code
    if code in {'public_url_rejected','public_read_budget_exhausted','web_source_body_unavailable',
        'web_source_access_restricted','web_source_time_outside_window','web_source_time_missing',
        'web_source_timezone_missing','web_source_redirect_without_location','web_source_redirect_limit',
        'web_source_not_admitted','search_response_not_ok','search_result_shape'}:return code
    return type(error).__name__


def capabilities():
    from ..config import settings
    return dict(search_provider='tavily',enabled=settings.research_web_search_enabled,
        configured=bool(settings.research_web_search_api_key and settings.research_web_search_api_key.get_secret_value().strip()),
        max_search_http_requests=settings.research_web_search_max_requests,
        fixed_media_search_scope=['wallstreetcn','stcn'],
        limitation='配置状态不是联网验收；搜索目录不是正文，聊天工具不能自动供服务器调用。')


def search(workspace,query,hours=72,deadline=None):
    from ..config import settings
    if not settings.research_web_search_enabled:return dict(status='disabled',scope='general_web',results=[])
    if not settings.research_web_search_api_key or not settings.research_web_search_api_key.get_secret_value().strip():return dict(status='unavailable',reason='search_account_not_configured',scope='general_web',results=[])
    cache=getattr(workspace,'web_search_cache',{})
    key=(query,hours)
    if key in cache:return dict(cache[key],reused_within_episode=True)
    attempts=getattr(workspace,'web_search_attempts',0)
    if attempts>=settings.research_web_search_max_requests:return dict(status='budget_exhausted',scope='general_web',results=[])
    root=ResearchHub().root;pause_key='research-web-search:tavily:v1:'+hashlib.sha256(settings.research_web_search_api_key.get_secret_value().encode()).hexdigest()[:12]
    try:ensure_active(root,pause_key)
    except RetiredSourceError:return dict(status='unavailable',reason='search_route_paused_no_auto_retest',scope='general_web',results=[])
    if deadline is not None and deadline<=time.monotonic():return dict(status='budget_exhausted',scope='general_web',results=[])
    workspace.web_search_attempts=attempts+1
    try:
        response=requests.post('https://api.tavily.com/search',
            headers={'Authorization':'Bearer '+settings.research_web_search_api_key.get_secret_value()},
            json=dict(query=query,topic='news',search_depth='basic',max_results=10,
                      time_range='day' if hours<=24 else 'week',include_published_date=True,
                      include_answer=False,include_raw_content=False,auto_parameters=False),
            timeout=min(10,max(.1,deadline-time.monotonic())) if deadline else 10,allow_redirects=False)
        response.raise_for_status()
        if response.status_code!=200:raise ValueError('search_response_not_ok')
        data=response.json()
        if not isinstance(data,dict) or not isinstance(data.get('results'),list):raise ValueError('search_result_shape')
        results=[]
        for row in data['results'][:10]:
            if not isinstance(row,dict):continue
            url=row.get('url')
            from .evidence import article_url
            if not article_url(url):continue
            results.append(dict(title=str(row.get('title') or '')[:300],url=url,
                snippet=str(row.get('content') or '')[:300],published_hint=row.get('published_date'),
                reading_status='search_snippet_not_body'))
        result=dict(status='ok',scope='general_web_search_results_not_exhaustive',query=query,
            requested_hours=hours,window='engine_day_or_week_hint_not_verified_article_window',
            results=results,http_attempts=workspace.web_search_attempts,
            limitation='搜索引擎可能漏收、排序失真或返回旧转载；须读取正文核对时间，未入证据池。')
    except Exception as error:
        record_failure(root,pause_key,ValueError('web_research_failed_no_auto_retest'),detail_code=failure_reason(error))
        result=dict(status='failed',scope='general_web',error=type(error).__name__,results=[],
                    reason=failure_reason(error),http_attempts=workspace.web_search_attempts,retries=0)
    cache[key]=result;workspace.web_search_cache=cache
    return result


def public_target(url):
    parts=urlsplit(url)
    if (parts.scheme not in {'http','https'} or not parts.hostname or parts.username or parts.password
            or parts.port not in {None,80,443} or len(url)>2048):raise ValueError('public_url_rejected')
    host=parts.hostname.rstrip('.')
    if host.lower()=='localhost' or host.lower().endswith(('.localhost','.local','.internal')):raise ValueError('public_url_rejected')
    addresses=socket.getaddrinfo(host,parts.port or (443 if parts.scheme=='https' else 80),type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):raise ValueError('public_url_rejected')
    return url.split('#',1)[0],addresses[0][4][0]


def fetch_html_once(url,deadline=None):
    """Pin the checked address; TLS still verifies the original hostname."""
    url,address=public_target(url);parts=urlsplit(url)
    remaining=deadline-time.monotonic() if deadline else 8
    if remaining<=0:raise TimeoutError('public_read_budget_exhausted')
    pool=(urllib3.HTTPSConnectionPool(address,port=parts.port or 443,
          assert_hostname=parts.hostname,server_hostname=parts.hostname,
          cert_reqs='CERT_REQUIRED',ca_certs=requests.certs.where())
          if parts.scheme=='https' else urllib3.HTTPConnectionPool(address,port=parts.port or 80))
    response=None
    try:
        path=(parts.path or '/')+('?' + parts.query if parts.query else '')
        response=pool.request('GET',path,headers={'Host':parts.netloc,'User-Agent':'Mozilla/5.0'},
            timeout=urllib3.Timeout(total=min(8,remaining)),redirect=False,retries=False,preload_content=False)
        if response.status in {301,302,303,307,308}:return response.status,dict(response.headers),b''
        if response.status!=200:raise ValueError('public_http_'+str(response.status))
        if 'html' not in response.headers.get('Content-Type','').lower():raise ValueError('web_source_body_unavailable')
        chunks=[];size=0
        for chunk in response.stream(65536,decode_content=True):
            if deadline is not None and time.monotonic()>=deadline:raise TimeoutError('public_read_budget_exhausted')
            size+=len(chunk)
            if size>2*1024*1024:raise ValueError('web_source_body_unavailable')
            chunks.append(chunk)
        return response.status,dict(response.headers),b''.join(chunks)
    finally:
        if response is not None:response.close()
        pool.close()


def parse_visible_article(html,url,now=None,hours=72):
    now=now or china_now();soup=BeautifulSoup(html,'html.parser')
    from .overseas_sources import ld_restricted
    if ld_restricted(soup) or re.search(r'订阅后阅读|登录后阅读|subscribe to continue|sign in to continue',soup.get_text(' ',strip=True),re.I):
        raise ValueError('web_source_access_restricted')
    # Reuse reviewed publisher adapters when the discovered URL matches one.
    # An adapter admission error is NOT bypassed by a weaker generic parser.
    from . import public_news_sources,overseas_sources
    for module in (public_news_sources,overseas_sources):
        for provider in module.SOURCES:
            if not module.permitted(provider,url):continue
            row=module.parse_article(provider,str(soup),url)
            stamp=datetime.fromisoformat(row.get('publication_start') or row['published'])
            end=datetime.fromisoformat(row.get('publication_end') or row['published'])
            if stamp>now or end<now-timedelta(hours=hours):raise ValueError('web_source_time_outside_window')
            precision=row.get('date_precision') or row.get('precision') or 'second'
            original=row.get('original_time') or (row['published'][:10] if precision=='day' else row['published'])
            from ..models.news import News
            return News(id='web-'+hashlib.sha256((url+'\n'+row['body']).encode()).hexdigest()[:24],
                title=row['title'],content=row['body'],source=row['source'],source_url=url,published_at=stamp,
                market_impact='原始来源时点：'+original+'；精度：'+precision+'；'+row.get('reading','公开页面正文，非独立核验')+
                '；转载来源：'+row.get('upstream','未单列'))
    host=urlsplit(url).hostname
    # Verified DOM variants from saved public pages, not a whole-page text fallback.
    template_date=None;heading=soup.find('h1');article=soup.select_one('article,[itemprop="articleBody"]')
    if host in {'cj.sina.com.cn','finance.sina.com.cn'} and soup.select_one('#artibody'):
        heading=soup.select_one('h1.main-title');article=soup.select_one('#artibody')
        node=soup.select_one('.date-source .date')
        match=re.search(r'(\d{4})年(\d{2})月(\d{2})日\s*(\d{2}:\d{2})',node.get_text(' ',strip=True) if node else '')
        if match:template_date='-'.join(match.groups()[:3])+'T'+match.group(4)+'+08:00'
    elif host=='www.bea.gov' and urlsplit(url).path.startswith('/news/'):
        headings=soup.select('h1');heading=headings[-1] if headings else None
        article=soup.select_one('.field--name-body')
        node=soup.select_one('.field--name-field-release-date')
        raw_release=node.get_text(' ',strip=True) if node else ''
        match=re.fullmatch(r'EMBARGOED UNTIL RELEASE AT (\d{1,2}:\d{2}) (a\.m\.|p\.m\.) (EDT|EST), \w+, (\w+ \d{1,2}, \d{4})',raw_release)
        if match:
            stamp=datetime.strptime(match.group(4)+' '+match.group(1)+' '+('AM' if match.group(2)=='a.m.' else 'PM'),'%B %d, %Y %I:%M %p')
            template_date=stamp.replace(tzinfo=timezone(timedelta(hours=-4 if match.group(3)=='EDT' else -5))).isoformat(timespec='minutes')
    if heading is None or article is None:raise ValueError('web_source_body_unavailable')
    title=heading.get_text(' ',strip=True)
    for node in article.select('script,style,nav,aside,footer,form'):node.decompose()
    content=article.get_text('\n',strip=True)
    if not 6<=len(title)<=300 or len(content)<160:raise ValueError('web_source_body_unavailable')
    dates=[template_date] if template_date else []
    for node in soup.select('meta[property="article:published_time"],meta[itemprop="datePublished"]')+article.select('time[itemprop="datePublished"][datetime]'):
        dates.append(node.get('content') or node.get('datetime'))
    # Only explicit article metadata, never URL dates or search snippets.
    for node in BeautifulSoup(html,'html.parser').select('script[type="application/ld+json"]'):
        try:data=json.loads(node.get_text())
        except (ValueError,TypeError):continue
        rows=data if isinstance(data,list) else [data]
        for row in rows:
            if not isinstance(row,dict):continue
            rows2=row.get('@graph') if isinstance(row.get('@graph'),list) else [row]
            for entry in rows2:
                if not isinstance(entry,dict):continue
                kind=entry.get('@type',[]);kind=kind if isinstance(kind,list) else [kind]
                if any(value in {'Article','NewsArticle','BlogPosting'} for value in kind) and entry.get('headline')==title:
                    dates.insert(0,entry.get('datePublished'))
    raw=next((str(value) for value in dates if value),None)
    if not raw:raise ValueError('web_source_time_missing')
    date_only=bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}',raw))
    if date_only:
        day=datetime.fromisoformat(raw)
        stamp=day.replace(tzinfo=timezone(timedelta(hours=14))).astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
        end=min(now,(day+timedelta(days=1)).replace(tzinfo=timezone(timedelta(hours=-12))).astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None))
    else:
        value=datetime.fromisoformat(raw.replace('Z','+00:00'))
        if value.tzinfo is None:raise ValueError('web_source_timezone_missing')
        stamp=value.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None);end=stamp
    if stamp>now or end<now-timedelta(hours=hours):raise ValueError('web_source_time_outside_window')
    from ..models.news import News
    return News(id='web-'+hashlib.sha256((url+'\n'+content).encode()).hexdigest()[:24],
        title=title,content=content,source='公开网页可见正文-'+urlsplit(url).hostname,
        source_url=url,published_at=stamp,category='公开网页，作者及原始来源仍需核对',
        market_impact='原始来源时点：'+raw+'；精度：'+('day' if date_only else 'minute' if re.search(r'T\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})$',raw) else 'second')+'；公开可见正文，不宣称完整稿或独立核验')


def read_public(workspace,url,hours=72,deadline=None,characters=6000):
    from .event_observations import canonical
    url=canonical(url) or url
    root=ResearchHub().root;key='research-public-url:'+str(url).split('#',1)[0]
    try:
        if url in PAUSED_PUBLIC_ARTICLES:raise RetiredSourceError('public_article_paused')
        ensure_active(root,key)
    except RetiredSourceError:return dict(status='unavailable',reason='article_paused_no_auto_retest',url=url)
    cached=getattr(workspace,'web_article_cache',{})
    if url in cached:
        return dict(cached[url],material=workspace.read(cached[url]['material']['id'],characters=characters),reused_within_episode=True)
    try:
        current=url
        for _ in range(3):
            if current in PAUSED_PUBLIC_ARTICLES:raise RetiredSourceError('public_article_paused')
            ensure_active(root,'research-public-url:'+current.split('#',1)[0])
            remaining=deadline-time.monotonic() if deadline else 8
            if remaining<=0:return dict(status='budget_exhausted',url=url)
            status,headers,raw=fetch_html_once(current,deadline)
            if status in {301,302,303,307,308}:
                location=headers.get('Location') or headers.get('location')
                if not location:raise ValueError('web_source_redirect_without_location')
                current=urljoin(current,location);continue
            item=parse_visible_article(raw,current,now=workspace.now,hours=hours)
            workspace.add([item])
            if item.id not in workspace.documents:raise ValueError('web_source_not_admitted')
            result=dict(status='ok',url=current,observed_at=china_now().isoformat(),reading_status='visible_article_body_not_certified_full_text',
                        material=workspace.read(item.id,characters=characters))
            cached[url]=result;workspace.web_article_cache=cached
            return result
        raise ValueError('web_source_redirect_limit')
    except Exception as error:
        # Also pause an alias that redirects to an already retired target.
        record_failure(root,key,ValueError('web_research_failed_no_auto_retest'),detail_code=failure_reason(error))
        return dict(status='failed',url=url,error=type(error).__name__,retries=0,
                    reason=failure_reason(error),
                    limitation='未入正文证据，不把HTTP错误、目录或摘要当全文；失败路径暂停自动重试。')

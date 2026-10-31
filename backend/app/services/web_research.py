"""Opt-in search directories and bounded public HTML reads; no snippet evidence.

Search requires an explicitly enabled account. Public reading does not transmit
that account key, cookies, or application credentials to publishers.
"""
from datetime import datetime,timedelta,timezone
import hashlib,ipaddress,json,re,socket,time
from urllib.parse import urlsplit,urljoin,parse_qs
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
    if code in {'web_source_non_html','web_source_response_too_large','web_source_article_structure_missing',
                'web_source_article_text_too_short','web_source_alias_identity_unverified','web_source_time_invalid',
                'web_source_day_window_boundary_requires_review','web_source_specialized_reader_required',
                'web_source_generic_extractor_unavailable'}:return code
    return type(error).__name__


def capabilities():
    from ..config import settings
    import importlib.util
    return dict(search_provider='tavily',enabled=settings.research_web_search_enabled,
        configured=bool(settings.research_web_search_api_key and settings.research_web_search_api_key.get_secret_value().strip()),
        max_search_http_requests=settings.research_web_search_max_requests,
        fixed_media_search_scope=['wallstreetcn','stcn'],
        public_discussion_tool='collect_discussions',discussion_providers=['guba','jisilu','taoguba','tradingview'],
        discussion_status='local_public_samples_verified_server_network_not_verified',
        generic_extractor_installed=importlib.util.find_spec('trafilatura') is not None,
        public_body_strategy='same_url_cache_then_reviewed_adapter_then_optional_generic_extractor',
        limitation='配置状态不是联网验收；搜索目录不是正文，聊天工具不能自动供服务器调用。')


def search(workspace,query,hours=72,deadline=None,topic='news',purpose='discovery'):
    from ..config import settings
    from .search_objectives import request_profile
    effective_query,profile=request_profile(query,purpose,workspace.now,hours)
    if topic not in {'news','general'}:raise ValueError('search_topic_invalid')
    if not settings.research_web_search_enabled:return dict(status='disabled',scope='general_web',results=[])
    if not settings.research_web_search_api_key or not settings.research_web_search_api_key.get_secret_value().strip():return dict(status='unavailable',reason='search_account_not_configured',scope='general_web',results=[])
    cache=getattr(workspace,'web_search_cache',{})
    key=(effective_query,hours,topic,purpose,tuple(sorted((k,str(v)) for k,v in profile.items())))
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
            json=dict(query=effective_query,topic=topic,search_depth='basic',max_results=10,
                      time_range='day' if hours<=24 else 'week',include_published_date=True,
                      include_answer=False,include_raw_content=False,auto_parameters=False,**profile),
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
        result=dict(status='ok',scope='general_web_search_results_not_exhaustive',query=effective_query,
            requested_query=query,topic=topic,purpose=purpose,retrieval_profile=profile,
            requested_max_results=10,provider_returned_results=len(data['results']),
            processed_results=min(10,len(data['results'])),metadata_results=len(results),
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
        if 'html' not in response.headers.get('Content-Type','').lower():raise ValueError('web_source_non_html')
        chunks=[];size=0
        for chunk in response.stream(65536,decode_content=True):
            if deadline is not None and time.monotonic()>=deadline:raise TimeoutError('public_read_budget_exhausted')
            size+=len(chunk)
            if size>2*1024*1024:raise ValueError('web_source_response_too_large')
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
    parts=urlsplit(url)
    if (parts.hostname in {'money.finance.sina.com.cn','vip.stock.finance.sina.com.cn'}
            and parts.path=='/corp/view/vCB_AllBulletinDetail.php'):
        params=parse_qs(parts.query);code=params.get('stockid',[''])[0]
        article=soup.select_one('#content');text=article.get_text('\n',strip=True) if article else ''
        date=re.search(r'公告日期\s*[:：]\s*(\d{4}-\d{2}-\d{2})',soup.get_text(' ',strip=True))
        if (not re.fullmatch(r'\d{6}',code) or not re.fullmatch(r'\d+',params.get('id',[''])[0])
            or not re.search(r'证券代码\s*[:：]?\s*'+code+r'(?!\d)',text)):
            raise ValueError('web_source_not_admitted')
        if not date:raise ValueError('web_source_time_missing')
        stamp=datetime.fromisoformat(date[1])
        if stamp>now or stamp<now-timedelta(hours=hours):raise ValueError('web_source_time_outside_window')
        if len(text)<80 or soup.title is None:raise ValueError('web_source_body_unavailable')
        from ..models.news import News
        return News(id='web-'+hashlib.sha256((url+'\n'+text).encode()).hexdigest()[:24],
            title=soup.title.get_text(' ',strip=True),content=text,
            source='公开网页可见正文-新浪公司公告镜像',source_url=url,published_at=stamp,
            market_impact='原始来源时点：'+date[1]+'；精度：day；HTML公告镜像正文及表格，公告日不等于签署日；未与交易所原文件逐项核对。')
    # Reuse reviewed publisher adapters when the discovered URL matches one.
    # An adapter admission error is NOT bypassed by a weaker generic parser.
    from . import public_news_sources,overseas_sources
    provider_url=url;alias_note=''
    # Reuse the reviewed NBD parser only when this alias page itself declares
    # the identical article path on nbd.com.cn. No request to the canonical URL.
    # The actual acquisition host remains visible; canonical is not proof of ownership.
    if parts.hostname=='www.mrjjxw.com' and re.fullmatch(r'/articles/\d{4}-\d{2}-\d{2}/\d+\.html',parts.path):
        links=soup.select('link[rel="canonical"]')
        values={node.get('href') for node in links}
        expected='https://www.nbd.com.cn'+parts.path
        if values!={expected}:raise ValueError('web_source_alias_identity_unverified')
        provider_url=expected
        alias_note='；实际取得于www.mrjjxw.com，页面声明canonical至每日经济新闻；域名归属未独立核实'
    for module in (public_news_sources,overseas_sources):
        for provider in module.SOURCES:
            if not module.permitted(provider,provider_url):continue
            row=module.parse_article(provider,str(soup),provider_url)
            stamp=datetime.fromisoformat(row.get('publication_start') or row['published'])
            end=datetime.fromisoformat(row.get('publication_end') or row['published'])
            if stamp>now or end<now-timedelta(hours=hours):raise ValueError('web_source_time_outside_window')
            precision=row.get('date_precision') or row.get('precision') or 'second'
            original=row.get('original_time') or (row['published'][:10] if precision=='day' else row['published'])
            from ..models.news import News
            return News(id='web-'+hashlib.sha256((url+'\n'+row['body']).encode()).hexdigest()[:24],
                title=row['title'],content=row['body'],source=row['source']+('（别名页声明，见来源说明）' if alias_note else ''),source_url=url,published_at=stamp,
                market_impact='原始来源时点：'+original+'；精度：'+precision+'；'+row.get('reading','公开页面正文，非独立核验')+
                '；转载来源：'+row.get('upstream','未单列')+alias_note)
    host=urlsplit(url).hostname
    from .generic_extraction import reader_kind
    if reader_kind(url)!='article_candidate':raise ValueError('web_source_specialized_reader_required')
    # Verified DOM variants from saved public pages, not a whole-page text fallback.
    template_date=None
    heading=next((node for node in soup.select('h1') if 6<=len(node.get_text(' ',strip=True))<=300),None)
    article=soup.select_one('article,[itemprop="articleBody"]')
    if host=='finance.eastmoney.com' and re.fullmatch(r'/a/\d+\.html',parts.path):
        heading=soup.select_one('h1,div.title');article=soup.select_one('#ContentBody')
        node=soup.select_one('.infos')
        match=re.search(r'(\d{4})年(\d{2})月(\d{2})日\s*(\d{2}:\d{2}(?::\d{2})?)',node.get_text(' ',strip=True) if node else '')
        if match:template_date='-'.join(match.groups()[:3])+'T'+match.group(4)+'+08:00'
    if article is not None and article.find('h1') is not None:heading=article.find('h1')
    if (host=='www.intc.com' and re.fullmatch(r'/news-events/press-releases/detail/\d+/[^/]+',urlsplit(url).path)
            and article is not None):
        node=article.select_one('time.date')
        clock=node.get_text(' ',strip=True) if node else ''
        match=re.fullmatch(r'([A-Z][a-z]{2} \d{1,2}, \d{4})\s*•\s*(\d{1,2}:\d{2} [AP]M) (EDT|EST)',clock)
        if match:
            value=datetime.strptime(match[1]+' '+match[2],'%b %d, %Y %I:%M %p')
            template_date=value.replace(tzinfo=timezone(timedelta(hours=-4 if match[3]=='EDT' else -5))).isoformat()
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
    title=heading.get_text(' ',strip=True) if heading is not None else ''
    if not title:
        node=soup.select_one('meta[property="og:title"],meta[name="ArticleTitle"]')
        title=node.get('content','').strip() if node else ''
    extraction_note=''
    if article is None:
        from .generic_extraction import extract_main_text
        candidate=extract_main_text(html,url)
        if candidate.get('status')=='unavailable':raise ValueError('web_source_generic_extractor_unavailable')
        if candidate.get('status')!='text_candidate':raise ValueError('web_source_article_structure_missing')
        content=candidate['text']
        extraction_note='；正文算法：'+candidate['method']+' '+candidate['version']+'；未确认完整稿；'+','.join(candidate['warnings'])
    else:
        for node in article.select('script,style,nav,aside,footer,form'):node.decompose()
        content=article.get_text('\n',strip=True)
    # A short, actually retrieved news item is not a missing article. Keep it
    # explicitly as short text instead of padding it with navigation/footer.
    content='\n'.join(line for line in content.splitlines() if not re.fullmatch(r'\s*(?:海量资讯.{0,60}新浪财经APP|责任编辑\s*[:：].{0,20})\s*',line)).strip()
    if not 6<=len(title)<=300 or len(content)<80:raise ValueError('web_source_article_text_too_short')
    short_text=len(content)<160
    dates=[template_date] if template_date else []
    for node in soup.select('meta[property="article:published_time"],meta[itemprop="datePublished"],meta[name="PubDate"],meta[name="pubdate"],meta[name="datePublished"]')+(article.select('time[itemprop="datePublished"][datetime]') if article else []):
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
    normalized=raw.replace('/','-')
    date_only=bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}Z?',normalized))
    try:value=datetime.fromisoformat(normalized.rstrip('Z') if date_only else normalized.replace('Z','+00:00'))
    except ValueError:raise ValueError('web_source_time_invalid') from None
    timezone_unknown=not date_only and value.tzinfo is None
    if date_only or timezone_unknown:
        # An explicitly labelled publication date is usable at day precision;
        # a missing timezone never becomes an invented local publication clock.
        day=datetime.combine(value.date(),datetime.min.time())
        stamp=day.replace(tzinfo=timezone(timedelta(hours=14))).astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
        end=min(now,(day+timedelta(days=1)).replace(tzinfo=timezone(timedelta(hours=-12))).astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None))
        if stamp<now-timedelta(hours=hours)<=end:raise ValueError('web_source_day_window_boundary_requires_review')
        date_only=True
    else:
        stamp=value.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None);end=stamp
    if stamp>now or end<now-timedelta(hours=hours):raise ValueError('web_source_time_outside_window')
    from ..models.news import News
    return News(id='web-'+hashlib.sha256((url+'\n'+content).encode()).hexdigest()[:24],
        title=title,content=content,source=('公开网页快讯正文-' if short_text else '公开网页可见正文-')+urlsplit(url).hostname,
        source_url=url,published_at=stamp,category='公开网页，作者及原始来源仍需核对',
        market_impact='原始来源时点：'+raw+('（来源未标时区，仅按日期，不用于盘前盘后或消息先后判断）' if timezone_unknown else '')+'；精度：'+('day' if date_only else 'minute' if re.search(r'T\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})$',raw) else 'second')+'；'+('短讯文字，未取得扩展报道；' if short_text else '')+'公开可见正文，不宣称完整稿或独立核验'+extraction_note)


def archived_public_body(url,now,hours=72,root=None):
    """Exact-URL, recent observed full bodies; read-only, no archive creation."""
    from pathlib import Path
    import sqlite3
    from .news_archive import ROOT
    from .event_observations import canonical
    from .news_quality import reading_scope,excluded_reason
    from .news_selection import within_window
    from ..models.news import News
    path=(Path(root) if root is not None else ROOT)/'news-history.db'
    if not path.is_file():return None
    try:
        connection=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
        try:
            rows=connection.execute('SELECT payload,last_seen FROM documents WHERE url=? AND last_seen BETWEEN ? AND ? ORDER BY last_seen DESC,published DESC',
                (canonical(url),(now-timedelta(hours=24)).isoformat(),now.isoformat())).fetchall()
        finally:connection.close()
    except sqlite3.Error:return None
    for payload,observed in rows:
        try:
            item=News.model_validate_json(payload)
            if (canonical(item.source_url)!=canonical(url) or len(item.content.strip())<100
                or not (reading_scope(item) in {'full_text','visible_body'} or item.source.startswith('公开网页快讯正文-')) or excluded_reason(item)
                or not within_window(item,now,hours)):continue
            return item,observed
        except (ValueError,TypeError):continue
    return None


def capture_public_response(workspace,url,status,headers,raw):
    """Private bytes for offline parser repair; never refetch a failed URL."""
    from .research_hub import save_json
    folder=workspace.path/'public-responses';folder.mkdir(exist_ok=True,mode=0o700)
    key=hashlib.sha256(url.encode()).hexdigest()[:24]
    target=folder/(key+'.body');target.write_bytes(raw);target.chmod(0o600)
    meta=dict(url=url,http_status=status,content_type=headers.get('Content-Type') or headers.get('content-type'),
        observed_at=china_now().isoformat(),snapshot_cutoff=workspace.now.isoformat(),bytes=len(raw),
        body_sha256=hashlib.sha256(raw).hexdigest(),file=target.name,
        limitation='原始响应，不代表正文、发布时间或事实已核实；仅随工作区保留，不保存请求头/凭据。')
    save_json(folder/(key+'.json'),meta)
    return 'public-responses/'+key+'.json'


def read_public(workspace,url,hours=72,deadline=None,characters=6000):
    from .event_observations import canonical
    url=canonical(url) or url
    # Reuse admitted body text across discovery channels, not just this tool's
    # own cache. A feed/search snippet at the same URL cannot satisfy this.
    from .news_quality import reading_scope
    from .news_selection import within_window
    reusable=[item for item in workspace.documents.values()
        if canonical(item.source_url)==url and hasattr(item,'content')
        and len(item.content.strip())>=100
        and (reading_scope(item) in {'full_text','visible_body'} or item.source.startswith('公开网页快讯正文-'))
        and within_window(item,workspace.now,hours)]
    if reusable:
        def latest(row):
            stamp=row.published_at
            if stamp.tzinfo is not None:stamp=stamp.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
            return stamp,len(row.content)
        item=max(reusable,key=latest)
        return dict(status='ok',url=url,material=workspace.read(item.id,characters=characters),
            reused_within_episode=True,reused_from='episode_body_pool',http_requests_performed=0,
            remote_version_checked=False,reading_status='stored_text_not_new_remote_verification',
            limitation='复用本期已存文字，不证明远端未更新或已读完整原文；新版本/修订须另核，不以同链接认定事件无增量。')
    stored=archived_public_body(url,workspace.now,hours)
    if stored:
        item,observed=stored;workspace.add([item])
        if item.id in workspace.documents:
            return dict(status='ok',url=url,material=workspace.read(item.id,characters=characters),
                reused_from='recent_same_url_archive',cache_observed_at=observed,http_requests_performed=0,
                remote_version_checked=False,reading_status='stored_text_not_new_remote_verification',
                limitation='复用过去24小时观察到、截止时点前同链接且发布窗口内的已存正文；不是新抓取，不证明远端未修订。')
    root=ResearchHub().root;key='research-public-url:'+str(url).split('#',1)[0]
    try:
        if url in PAUSED_PUBLIC_ARTICLES:raise RetiredSourceError('public_article_paused')
        ensure_active(root,key)
    except RetiredSourceError:return dict(status='unavailable',reason='article_paused_no_auto_retest',url=url)
    cached=getattr(workspace,'web_article_cache',{})
    if url in cached:
        return dict(cached[url],material=workspace.read(cached[url]['material']['id'],characters=characters),reused_within_episode=True)
    capture=None
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
            try:capture=capture_public_response(workspace,current,status,headers,raw)
            except OSError:capture=None  # Diagnostic disk failure is not publisher failure.
            item=parse_visible_article(raw,current,now=workspace.now,hours=hours)
            workspace.add([item])
            if item.id not in workspace.documents:raise ValueError('web_source_not_admitted')
            result=dict(status='ok',url=current,observed_at=china_now().isoformat(),response_capture=capture,reading_status='visible_article_body_not_certified_full_text',
                        material=workspace.read(item.id,characters=characters))
            cached[url]=result;workspace.web_article_cache=cached
            return result
        raise ValueError('web_source_redirect_limit')
    except Exception as error:
        # Also pause an alias that redirects to an already retired target.
        record_failure(root,key,ValueError('web_research_failed_no_auto_retest'),detail_code=failure_reason(error))
        return dict(status='failed',url=url,error=type(error).__name__,retries=0,
                    reason=failure_reason(error),response_capture=capture,
                    limitation='未入正文证据，不把HTTP错误、目录或摘要当全文；失败路径暂停自动重试。')

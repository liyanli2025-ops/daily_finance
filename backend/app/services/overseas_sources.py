"""Verified public overseas article readers. Discovery never counts as a body.

Bloomberg/WSJ/Reuters/AP/FT/Yahoo and metered CNBC are deliberately absent:
the tested routes did not establish accessible complete public articles.
"""
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timedelta,timezone
import hashlib,json,re,time
from urllib.parse import urljoin,urlsplit,parse_qs
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
import requests

from ..models.news import News
from .research_hub import ResearchHub
from .primary_sources import cached
from .time_context import china_now

CST=timezone(timedelta(hours=8))
SOURCES={
 'bbc':dict(index='https://www.bbc.com/business',host='www.bbc.com',name='BBC公开原文',path=r'/news/articles/[a-z0-9]+'),
 'guardian':dict(index='https://www.theguardian.com/uk/business',host='www.theguardian.com',name='Guardian公开原文',path=r'/business/\d{4}/[a-z]{3}/\d{2}/[^/]+'),
 'fed':dict(index='https://www.federalreserve.gov/json/ne-press.json',host='www.federalreserve.gov',name='美联储公开原文',path=r'/newsevents/pressreleases/[a-z]+\d{8}[a-z]\.htm'),
 'treasury':dict(index='https://home.treasury.gov/news/press-releases',host='home.treasury.gov',name='美国财政部公开原文',path=r'/news/press-releases/[a-z]{1,4}\d+/?'),
 'eia':dict(index='https://www.eia.gov/todayinenergy/',host='www.eia.gov',name='EIA公开原文',path=r'/todayinenergy/detail\.php'),
 'techcrunch':dict(index='https://techcrunch.com/news-sitemap.xml',host='techcrunch.com',name='TechCrunch公开原文',path=r'/\d{4}/\d{2}/\d{2}/[a-z0-9-]+/'),
 'fastbull':dict(index='https://www.fastbull.com/cn/news',host='www.fastbull.com',name='FastBull公开原文',path=r'/cn/news-detail/\d+_\d+')}
FINANCE=re.compile(r'\b(stock\w*|market\w*|econom\w*|inflation|bank\w*|interest|central|fed|trade|tariff\w*|china|chinese|hong kong|asia\w*|semiconductor\w*|chip\w*|ai|artificial intelligence|oil|gas|energy|electric\w*|power|copper|metal\w*|gold|bond\w*|treasury|dollar|yen|euro\w*|debt|sanction\w*|export\w*|supply|demand|earning\w*|invest\w*|capital|manufactur\w*)\b',re.I)
RESTRICTED=re.compile(r'subscribe to (?:continue|read|unlock)|sign in to (?:continue|read)|subscription required|already a subscriber|remaining content.{0,30}subscriber',re.I)


def permitted(provider,url,index=False):
    row=SOURCES[provider];parts=urlsplit(url)
    if parts.scheme!='https' or parts.username or parts.password or parts.fragment:return False
    if index:return url==row['index']
    if parts.hostname!=row['host'] or not re.fullmatch(row['path'],parts.path):return False
    if provider=='eia':
        query=parse_qs(parts.query,keep_blank_values=True)
        return set(query)=={'id'} and len(query['id'])==1 and query['id'][0].isdigit()
    return not parts.query


def plain(node):
    if node is None:return ''
    for n in node.select('script,style,form,aside,figure,nav'):n.decompose()
    return node.get_text('\n',strip=True)


def iso_time(raw):
    try:value=datetime.fromisoformat(str(raw).replace('Z','+00:00'))
    except (ValueError,TypeError):raise ValueError('overseas_source_time_missing')
    if value.tzinfo is None:raise ValueError('overseas_source_timezone_missing')
    return value.astimezone(CST).replace(tzinfo=None)


def publication(soup,provider):
    if provider=='fastbull':
        node=soup.select_one('.news-detail-main .detail-description .timedate[data-time]')
        try:stamp=datetime.fromtimestamp(int(node['data-time'])/1000,timezone.utc).astimezone(CST).replace(tzinfo=None)
        except (TypeError,ValueError,KeyError,OverflowError,OSError):raise ValueError('overseas_source_time_missing')
        return stamp,stamp,'millisecond',str(node['data-time'])+' (Unix milliseconds)'
    if provider=='fed':
        day=plain(soup.select_one('.article__time'))
        release=plain(soup.select_one('.releaseTime'))
        match=re.search(r'(\d{1,2}):(\d{2})\s*([ap])\.?m\.?\s+(EDT|EST)',release,re.I)
        if not match:raise ValueError('overseas_source_timezone_missing')
        date=datetime.strptime(day,'%B %d, %Y')
        hour=int(match[1])%12+(12 if match[3].lower()=='p' else 0)
        offset=-4 if match[4].upper()=='EDT' else -5
        original=date.replace(hour=hour,minute=int(match[2]),tzinfo=timezone(timedelta(hours=offset))).isoformat()
        stamp=iso_time(original)
        return stamp,stamp,'minute',day+' '+release
    if provider=='eia':
        raw=plain(soup.select_one('.tie-article .date'))
        day=datetime.strptime(raw,'%B %d, %Y')
        # The article provides neither a clock nor a timezone. Do not infer
        # Eastern Time merely from the agency's headquarters. Bound all civil
        # timezones conservatively; this interval is internal, not a timestamp.
        start=day.replace(tzinfo=timezone(timedelta(hours=14))).astimezone(CST).replace(tzinfo=None)
        end=(day+timedelta(days=1)).replace(tzinfo=timezone(timedelta(hours=-12))).astimezone(CST).replace(tzinfo=None)
        return start,end,'day',raw+' (calendar date only; source timezone and publication clock not supplied)'
    if provider=='treasury':
        node=soup.select_one('.field--name-field-news-publication-date time[datetime]')
        original=node.get('datetime') if node else None
    else:
        node=soup.select_one('meta[property="article:published_time"],meta[name="cXenseParse:publishtime"]')
        original=node.get('content') if node else None
    stamp=iso_time(original)
    return stamp,stamp,'second',original


def ld_restricted(soup):
    def denied(value):
        if isinstance(value,dict):
            if value.get('isAccessibleForFree') in (False,'False','false'):return True
            return any(denied(row) for row in value.values() if isinstance(row,(dict,list)))
        return isinstance(value,list) and any(denied(row) for row in value)
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            if denied(json.loads(node.get_text())):return True
        except (ValueError,TypeError):continue
    return False


def parse_article(provider,html,url):
    if not permitted(provider,url):raise ValueError('overseas_article_url_rejected')
    soup=BeautifulSoup(html,'html.parser')
    if ld_restricted(soup):raise ValueError('overseas_restricted_content')
    heading={'fed':'#article .title','treasury':'.uswds-page-title','eia':'.tie-article h1'}.get(provider,'h1')
    title=plain(soup.select_one(heading))
    if provider=='bbc':
        article=soup.select_one('article')
        blocks=article.select('[data-component="text-block"],[data-component="subheadline-block"]') if article else []
        body='\n'.join(plain(node) for node in blocks)
    elif provider=='guardian':body=plain(soup.select_one('.article-body-commercial-selector'))
    elif provider=='techcrunch':
        node=soup.select_one('div.entry-content')
        body='\n'.join(plain(part) for part in node.select(':scope > p,:scope > h2,:scope > ul > li')) if node else ''
    elif provider=='fastbull':body=plain(soup.select_one('.news-detail-main .news-detail-content'))
    elif provider=='treasury':body=plain(soup.select_one('.field--name-field-news-body'))
    elif provider=='eia':
        node=soup.select_one('.tie-article')
        if node:
            for part in node.select('.date,h1,.article-type'):part.decompose()
        body=plain(node)
    else:
        node=soup.select_one('#article .col-sm-8:not(.heading)')
        if node:
            for part in node.select('.article__time,.releaseTime,.title,.shareDL'):part.decompose()
        body=plain(node)
    if not title or len(body)<200:raise ValueError('overseas_full_body_unavailable')
    if RESTRICTED.search(body):raise ValueError('overseas_restricted_content')
    # Publication must be read from an independent copy: body cleaning mutates DOM.
    published,end,precision,original=publication(BeautifulSoup(html,'html.parser'),provider)
    return dict(title=title,body=body,published=published.isoformat(),publication_end=end.isoformat(),
        precision=precision,original_time=original,url=url,source=SOURCES[provider]['name'])


def discover(provider,content):
    if provider=='techcrunch':
        soup=BeautifulSoup(content,'xml');rows=[]
        for node in soup.find_all('url'):
            loc=node.find('loc');title=node.find('title')
            if loc and title:rows.append(dict(title=title.get_text(),url=loc.get_text()))
    elif provider=='fastbull':
        soup=BeautifulSoup(content,'html.parser');rows=[]
        for node in soup.select('.trending_type[href]'):
            title=node.select_one('.title')
            if title:rows.append(dict(title=title.get_text(' ',strip=True),url=urljoin(SOURCES[provider]['index'],node['href'])))
    elif provider=='fed':
        data=json.loads(content.lstrip('\ufeff'))
        rows=[dict(title=BeautifulSoup(row.get('t',''),'html.parser').get_text(),url=urljoin(SOURCES[provider]['index'],row.get('l','')),
            date_hint=row.get('d')) for row in data if row.get('pt') in {'Monetary Policy','Other Announcements'}]
    else:
        soup=BeautifulSoup(content,'html.parser');rows=[]
        for a in soup.select('a[href]'):
            title=a.get_text(' ',strip=True)
            if 15<=len(title)<=240:rows.append(dict(title=title,url=urljoin(SOURCES[provider]['index'],a['href'])))
    result={}
    for row in rows:
        chinese_finance=provider=='fastbull' and re.search(r'市场|经济|央行|利率|美联储|能源|原油|通胀|关税|股|汇率|债|资本|芯片|供应|贸易',row['title'])
        if permitted(provider,row['url']) and (provider in {'fed','eia','treasury'} or FINANCE.search(row['title']) or chinese_finance):
            result.setdefault(row['url'],row)
    return list(result.values())


class OverseasCollector:
    def __init__(self,root=None):self.hub=ResearchHub(root)

    def failure_detail(self,key,error):
        # Read existing negative evidence only; never re-request a failed URL
        # to retrieve an HTTP status. Provider response bodies are not logged.
        from .source_health import state_path
        path=state_path(self.hub.root,key)
        if path.exists():
            try:
                reason=json.loads(path.read_text(encoding='utf-8')).get('reason','')
                if re.fullmatch(r'http_\d{3}|tls_verification_failed|legacy_negative_result_requires_review|overseas_\w+|observed_(?:request_timeout|connection_failure)_no_auto_retest',reason):
                    return reason
            except (ValueError,OSError):pass
        reason=str(error)
        if re.fullmatch(r'(?:cached_primary_failure:\w+:)?overseas_\w+|source_paused_no_automatic_retest',reason):return reason
        return 'cause_not_retained_no_retest'

    def get(self,provider,url,deadline,index=False):
        if not permitted(provider,url,index):raise ValueError('overseas_article_url_rejected')
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('overseas_budget_exhausted')
        response=requests.get(url,headers={'User-Agent':'Mozilla/5.0'},timeout=min(8,remaining),allow_redirects=False)
        response.raise_for_status()
        if response.status_code!=200 or len(response.content)>4*1024*1024:raise ValueError('overseas_response_invalid')
        response.encoding=response.apparent_encoding or 'utf-8'
        return response.text

    def index(self,key,deadline):
        return cached(self.hub,'overseas:index:v1:'+key,900,lambda:self.get(key,SOURCES[key]['index'],deadline,True))

    def detail(self,key,url,deadline):
        return cached(self.hub,'overseas:article:v1:'+url,3600,lambda:parse_article(key,self.get(key,url,deadline),url))

    def collect(self,hours=72,budget=40,providers=None):
        from .source_health import RetiredSourceError
        names=list(providers if providers is not None else SOURCES);now=china_now();cutoff=now-timedelta(hours=hours)
        deadline=time.monotonic()+budget;queues={key:[] for key in names}
        states={key:dict(index=SOURCES[key]['index'],candidates=0,attempted=0,read=0,
            outside_window=0,date_boundary_uncertain=0,errors=[],paused_routes=[],complete_window=False) for key in names}
        with ThreadPoolExecutor(max_workers=4) as pool:
            pending={pool.submit(self.index,key,deadline):key for key in names}
            for future in as_completed(pending):
                key=pending[future]
                try:
                    rows=discover(key,future.result());states[key]['candidates']=len(rows)
                    for row in rows:
                        # Official Fed date hints can avoid downloading old releases.
                        if key=='fed' and row.get('date_hint'):
                            # The same official file contains old date-only rows.
                            # A discovery hint is an interval, never a fabricated
                            # publication clock; the article supplies the real time.
                            raw_day=str(row['date_hint']).split()[0]
                            day=datetime.strptime(raw_day,'%m/%d/%Y').replace(tzinfo=ZoneInfo('America/New_York'))
                            start=day.astimezone(CST).replace(tzinfo=None)
                            end=(day+timedelta(days=1)).astimezone(CST).replace(tzinfo=None)
                            if end<cutoff or start>now:states[key]['outside_window']+=1;continue
                        queues[key].append(row)
                except RetiredSourceError as error:
                    states[key]['paused_routes'].append(dict(stage='index',reason=self.failure_detail('overseas:index:v1:'+key,error)))
                except Exception as error:states[key]['errors'].append(dict(stage='index',error=type(error).__name__,
                    reason=self.failure_detail('overseas:index:v1:'+key,error)))
        from .news_assignment import discovery_order
        queues={key:discovery_order(rows) for key,rows in queues.items()}
        articles=[]
        with ThreadPoolExecutor(max_workers=4) as pool:
            pending={};busy=set();turn=0
            def fill():
                nonlocal turn
                while len(pending)<4 and time.monotonic()<deadline:
                    selected=None
                    for _ in names:
                        key=names[turn%len(names)];turn+=1
                        if key not in busy and queues[key]:selected=key;break
                    if selected is None:break
                    row=queues[selected].pop(0);busy.add(selected);states[selected]['attempted']+=1
                    pending[pool.submit(self.detail,selected,row['url'],deadline)]=(selected,row)
            fill()
            while pending:
                future=next(as_completed(pending));key,candidate=pending.pop(future);busy.remove(key)
                try:
                    row=future.result();stamp=datetime.fromisoformat(row['published']);end=datetime.fromisoformat(row['publication_end'])
                    if end<cutoff or stamp>now:states[key]['outside_window']+=1;continue
                    if stamp<cutoff or end>now:
                        states[key]['date_boundary_uncertain']+=1;continue
                    articles.append(News(id='overseas-'+hashlib.sha256(row['url'].encode()).hexdigest()[:24],title=row['title'],
                        content=row['body'],source=row['source'],source_url=row['url'],published_at=stamp,
                        category='海外市场原文',importance_score=.72,
                        market_impact='全市场事件入口：海外来源；须说明对A/H的具体传导，不自动对应任何自选股。'
                            +'原始来源时点：'+row['original_time']+'；精度：'+row['precision']+'；存储时间为北京时间。'
                            +'正文为原语言公开主体，未调用模型翻译；报道及官方声明均不等于独立证实。'))
                    states[key]['read']+=1
                except RetiredSourceError as error:
                    states[key]['paused_routes'].append(dict(stage='article',url=candidate['url'],
                        reason=self.failure_detail('overseas:article:v1:'+candidate['url'],error)))
                except Exception as error:
                    states[key]['errors'].append(dict(url=candidate['url'],error=type(error).__name__,
                        reason=self.failure_detail('overseas:article:v1:'+candidate['url'],error)))
                finally:fill()
        for key,state in states.items():
            state['not_attempted']=len(queues[key])
            state['status']='partial' if state['errors'] or queues[key] or state['paused_routes'] else 'ok' if state['read'] else 'no_recent_material'
            if not state['read'] and state['errors']:state['status']='failed'
            elif not state['read'] and not queues[key] and state['paused_routes']:state['status']='paused'
        return articles,dict(sources=states,read=len(articles),window_hours=hours,seconds=budget,complete_window=False,
            limitation='仅列明已验证公开正文的海外入口；不含彭博/WSJ/路透直连或CNBC付费预览。有限列表不代表全量；日精度跨窗口边界时不冒充72小时内发布，原文事件日与发布时间分开。')

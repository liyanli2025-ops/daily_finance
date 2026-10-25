"""Dated public media originals, searched from the current App watchlist.

No model requests, search snippets as evidence, inferred supply relationships,
login/captcha handling, or paid-article extraction.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import hashlib
import re
import time
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
import requests

from ..models.news import News, NewsType
from .time_context import china_now
from .research_hub import ResearchHub
from .primary_sources import cached

WSCN='https://api-one.wallstcn.com'
STCN='https://www.stcn.com'
MACRO=('美联储','出口管制','关税','央行','原油','制裁','海峡')
ROBOT=re.compile(r'融资买入|融资余额|融券余额|主力资金|资金净流入|龙虎榜数据|涨跌幅偏离值')
MARKET_RULES=('证监会','交易所','央行','降准','降息','加息','财政部','国务院','出口管制','关税','制裁')


def market_priority(title):
    """Reading priority only, never a return forecast or event verification."""
    return sum(term in title for term in MARKET_RULES)
# Product families, never stock-code rules. A topic requires an actual business match.
BUSINESS_TOPICS=[(('环氧塑封','塑封料','封装材料'),('封装材料','塑封料','封装')),
 (('水电','水力发电'),('来水','水电发电量','水电')),(('生猪','养猪'),('猪价','能繁母猪','生猪')),
 (('家禽','肉鸡'),('肉鸡','饲料')),(('煤电','火电','燃煤'),('煤电','电价')),
 (('光伏',),('光伏','硅料')),(('动力电池','锂电'),('锂电池','碳酸锂')),
 (('银行',),('净息差','信贷')),(('保险',),('保费','偿付能力')),
 (('游戏','互联网'),('游戏','平台监管')),(('创新药','制药'),('创新药','药品审批')),
 (('房地产',),('房地产','销售回款'))]


def clean(value):
    return BeautifulSoup(str(value or ''),'html.parser').get_text(' ',strip=True)


def topic_terms(profile):
    text=' '.join(str((profile or {}).get(key) or '') for key in ('industry','business'))
    selected=[]
    for anchors,topics in BUSINESS_TOPICS:
        if any(word in text for word in anchors):
            selected.extend(topics)
    if not selected:
        selected=[word for word in (profile or {}).get('topics',[]) if 2<=len(word)<=8][:2]
    return list(dict.fromkeys(selected))[:4]


def query_plan(stocks,profiles,limit=12):
    terms={stock.code:topic_terms(profiles.get(str(getattr(stock.market,'value',stock.market))+':'+stock.code,{})) for stock in stocks}
    queries=list(dict.fromkeys(stock.name.strip() for stock in stocks if stock.name.strip()))[:limit]
    # Round robin keeps a first stock's profile from consuming all search slots.
    for position in range(2):
        for stock in stocks:
            if position<len(terms[stock.code]) and terms[stock.code][position] not in queries and len(queries)<limit-2:
                queries.append(terms[stock.code][position])
    for term in ('美联储','出口管制'):
        if len(queries)<limit and term not in queries:
            queries.append(term)
    return queries,terms


def relation(title,body,stocks,terms):
    from .news_selection import industry_terms
    text=title+' '+body
    # Search hit != company mention, and industry hit != company beneficiary.
    direct=[stock.code for stock in stocks if stock.name and stock.name in text]
    industry={stock.code:industry_terms(text,terms.get(stock.code,[]))
              for stock in stocks}
    industry={key:value for key,value in industry.items() if value and key not in direct}
    macro=[term for term in MACRO if term in title]
    return direct,industry,macro


def public_article(row):
    flags=('is_paid','is_priced','is_need_pay','is_trial','is_trail')
    return not any(row.get(key) in (True,1,'1','true') for key in flags)


def epoch_time(value):
    try:
        return datetime.fromtimestamp(float(value),timezone(timedelta(hours=8))).replace(tzinfo=None)
    except (ValueError,TypeError,OverflowError,OSError):
        return None


def stcn_links(html):
    soup=BeautifulSoup(html,'html.parser')
    result={}
    for link in soup.select('a[href]'):
        url=urljoin(STCN,link['href'])
        parsed=urlsplit(url)
        title=link.get_text(' ',strip=True)
        if parsed.scheme!='https' or parsed.hostname!='www.stcn.com' or not re.fullmatch(r'/article/detail/\d+\.html',parsed.path):
            continue
        # Repeated image/summary anchors must not replace the actual headline.
        if 6<=len(title)<=100 and url not in result:
            result[url]=title
    return [(url,title) for url,title in result.items()]


def parse_stcn(html):
    soup=BeautifulSoup(html,'html.parser')
    title=soup.select_one('.detail-title,h1')
    info=soup.select_one('.detail-info')
    content=soup.select_one('.detail-content')
    if not all((title,info,content)):
        raise ValueError('media_article_structure_missing')
    stamp=re.search(r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?',info.get_text(' ',strip=True))
    if not stamp:
        raise ValueError('media_publication_missing')
    raw=stamp.group()
    published=datetime.strptime(raw,'%Y-%m-%d %H:%M:%S' if len(raw)==19 else '%Y-%m-%d %H:%M')
    for node in content.select('script,style,iframe'):
        node.decompose()
    body=content.get_text('\n',strip=True)
    if len(body)<100 or any(word in body for word in ('登录后阅读全文','购买后阅读','订阅后阅读')):
        raise ValueError('media_full_body_unavailable')
    return title.get_text(' ',strip=True),published,body


class MediaCollector:
    def __init__(self,root=None):
        self.hub=ResearchHub(root)

    def get(self,url,deadline,params=None,json_response=True):
        parsed=urlsplit(url)
        if parsed.scheme!='https' or parsed.hostname not in {'api-one.wallstcn.com','www.stcn.com'} or parsed.username or parsed.password:
            raise ValueError('media_host_not_allowed')
        remaining=deadline-time.monotonic()
        if remaining<=0:
            raise TimeoutError('media_budget_exhausted')
        response=requests.get(url,params=params,headers={'User-Agent':'Mozilla/5.0'},
                              timeout=min(8,remaining),allow_redirects=False)
        response.raise_for_status()
        if response.status_code!=200 or len(response.content)>3*1024*1024:
            raise ValueError('media_response_invalid')
        if not json_response:
            response.encoding='utf-8'
            return response.text
        data=response.json()
        if not isinstance(data,dict) or data.get('code')!=20000:
            raise ValueError('media_api_response_invalid')
        return data.get('data') or {}

    def search(self,query,deadline):
        return cached(self.hub,'media:wscn:search:'+query,900,
            lambda:self.get(WSCN+'/apiv1/search/article',deadline,dict(query=query,limit=20)))

    def latest(self,_key,deadline):
        # Follow only a provider-supplied next_cursor, with a strict page bound.
        # A page/time limit never means complete historical coverage.
        def fetch():
            items=[];seen=set();cursor=None;cursors=set();pages=0;errors=[]
            stop='page_limit'
            for _ in range(4):
                params=dict(channel='global-channel',accept='article',limit=30)
                if cursor is not None:params['cursor']=cursor
                try:
                    data=self.get(WSCN+'/apiv1/content/information-flow',deadline,params)
                    rows=data.get('items') or []
                    if not isinstance(rows,list):raise ValueError('invalid_flow_items')
                except Exception as error:
                    if not pages:raise
                    errors.append(type(error).__name__);stop='request_failed';break
                pages+=1
                new=0
                for row in rows:
                    resource=row.get('resource') if isinstance(row,dict) else None
                    key=(row.get('resource_type'),str(resource.get('id'))) if isinstance(resource,dict) else None
                    if key and key not in seen:
                        seen.add(key);items.append(row);new+=1
                if not rows:stop='empty_page';break
                if not new:stop='repeated_page';break
                cursor=data.get('next_cursor')
                if cursor is None or cursor=='':stop='no_next_cursor';break
                if not isinstance(cursor,(str,int)) or len(str(cursor))>256:
                    stop='invalid_cursor';break
                if str(cursor) in cursors:stop='repeated_cursor';break
                cursors.add(str(cursor))
            return dict(items=items,pagination=dict(pages=pages,stop=stop,errors=errors,complete_window=False))
        return cached(self.hub,'media:wscn:market-flow:v3',900,fetch)

    def detail(self,provider,identifier,deadline):
        def fetch():
            if provider=='wscn':
                data=self.get(WSCN+'/apiv1/content/articles/'+identifier,deadline,dict(extract=1))
                if str(data.get('id'))!=identifier or not public_article(data):
                    raise ValueError('media_identity_or_access_rejected')
                # Only full public article content, never content_short/search snippets.
                if not any(data.get(key) in (False,0,'0','false') for key in ('is_need_pay','is_priced')
                           if key in data):
                    raise ValueError('media_access_unknown')
                body=clean(str(data.get('content') or '')+'\n'+str(data.get('content_more') or ''))
                if len(body)<100:
                    raise ValueError('media_full_body_unavailable')
                body=body.split('风险提示及免责条款',1)[0].strip()
                return dict(title=clean(data.get('title')),published=(epoch_time(data.get('display_time')) or datetime.min).isoformat(),
                            body=body,url='https://wallstreetcn.com/articles/'+identifier,source='华尔街见闻原文')
            url=STCN+'/article/detail/'+identifier+'.html'
            title,published,body=parse_stcn(self.get(url,deadline,json_response=False))
            return dict(title=title,published=published.isoformat(),body=body,url=url,source='证券时报原文')
        return cached(self.hub,'media:article:v3:'+provider+':'+identifier,3600,fetch)

    def collect(self,stocks,profiles,hours=24,budget=50,search_queries=None):
        now=china_now()
        cutoff=now-timedelta(hours=hours)
        deadline=time.monotonic()+budget
        queries,terms=query_plan(stocks,profiles)
        targeted=search_queries is not None
        if targeted:queries=list(dict.fromkeys(search_queries))
        status={name:dict(read=0,errors=[],excluded=0,requested=0) for name in ('wscn','stcn')}
        candidates={}
        market_keys=set()
        def search_job(query):
            return self.search(query,deadline)
        # One shared latest-page scan supplements the targeted company/product queries.
        def index_job(path):
            return cached(self.hub,'media:stcn:index:'+path,900,
                lambda:self.get(STCN+path,deadline,json_response=False))
        jobs=[('wscn',query,search_job) for query in queries]+([] if targeted else
            [('wscn','market-flow',lambda key:self.latest(key,deadline))]+
            [('stcn',path,index_job) for path in ('/','/article/list/xw.html','/article/list/cj.html')])
        with ThreadPoolExecutor(max_workers=4) as pool:
            pending={pool.submit(fetch,key):(provider,key) for provider,key,fetch in jobs}
            for future in as_completed(pending):
                provider,key=pending[future]
                status[provider]['requested']+=1
                try:
                    data=future.result()
                    if provider=='wscn':
                        if key=='market-flow':
                            status[provider]['pagination']=data.get('pagination',{})
                            if data.get('pagination',{}).get('errors'):
                                status[provider]['errors'].append(dict(query=key,error='flow_pagination_partial'))
                        rows=data.get('items',[])
                        if rows is None:rows=[]  # Provider returns null for valid searches with no hits.
                        if not isinstance(rows,list):raise ValueError('media_items_structure_invalid')
                        if key=='market-flow':
                            rows=[entry['resource'] for entry in rows if entry.get('resource_type')=='article'
                                  and isinstance(entry.get('resource'),dict) and entry['resource'].get('type')!='live']
                        for row in rows:
                            identifier=str(row.get('id',''))
                            stamp=epoch_time(row.get('display_time'))
                            if (not identifier.isdigit() or not public_article(row) or not stamp
                                    or not cutoff<=stamp<=now or ROBOT.search(clean(row.get('title')))):
                                status[provider]['excluded']+=1
                                continue
                            title=clean(row.get('title'))
                            direct,industry,macro=relation(title,clean(row.get('content')),stocks,terms)
                            if key=='market-flow' or targeted:
                                market_keys.add((provider,identifier))
                            if direct or industry or macro or key=='market-flow' or targeted:
                                score=4*bool(direct)+2*bool(industry)+bool(macro)
                                previous=candidates.get((provider,identifier))
                                candidates[(provider,identifier)]=(title,max(score,previous[1] if previous else 0),stamp)
                    else:
                        for url,title in stcn_links(data):
                            direct,industry,macro=relation(title,'',stocks,terms)
                            policy=market_priority(title)
                            if (direct or industry or macro or policy) and not ROBOT.search(title):
                                identifier=re.search(r'/(\d+)\.html',url).group(1)
                                if policy:market_keys.add((provider,identifier))
                                candidates[(provider,identifier)]=(title,4*bool(direct)+2*bool(industry)+bool(macro)+policy,datetime.min)
                except Exception as error:
                    status[provider]['errors'].append(dict(query=key,error=type(error).__name__))
        selected=[];queues={}
        for provider in ('wscn','stcn'):
            ranked=sorted([key for key in candidates if key[0]==provider],
                key=lambda key:(candidates[key][1],candidates[key][2]),reverse=True)
            # Reserve three originals outside keyword searches, then fill by relevance.
            reserved=sorted([key for key in ranked if key in market_keys],
                key=lambda key:(market_priority(candidates[key][0]),candidates[key][2]),reverse=True)[:3]
            # Reserve a company and a product-variable candidate per current
            # stock, before one busy company can consume the remaining slots.
            for stock in stocks:
                for field in ('company','industry'):
                    for key in ranked:
                        direct,industry,_=relation(candidates[key][0],'',stocks,terms)
                        matched=stock.code in (direct if field=='company' else industry)
                        if matched and key not in reserved:
                            reserved.append(key);break
            selected.extend(reserved)
            queues[provider]=[key for key in ranked if key not in reserved]
        while any(queues.values()):
            for provider in queues:
                if queues[provider]:selected.append(queues[provider].pop(0))
        items=[];attempted=[]
        with ThreadPoolExecutor(max_workers=3) as pool:
            pending={};remaining=iter(selected)
            def fill():
                while len(pending)<3 and time.monotonic()<deadline:
                    key=next(remaining,None)
                    if key is None:break
                    attempted.append(key)
                    pending[pool.submit(self.detail,*key,deadline)]=key
            fill()
            while pending:
                future=next(as_completed(pending))
                provider,identifier=pending.pop(future)
                try:
                    row=future.result()
                    published=datetime.fromisoformat(row['published'])
                    if not cutoff<=published<=now or ROBOT.search(row['title']):
                        status[provider]['excluded']+=1
                        continue
                    direct,industry,macro=relation(row['title'],row['body'],stocks,terms)
                    market_wide=(provider,identifier) in market_keys
                    if not (direct or industry or macro or market_wide):
                        status[provider]['excluded']+=1
                        continue
                    labels=['媒体报道，保留原文归属；不代表独立核实或预期差']
                    labels.extend('行业关联 '+str(getattr(stock.market,'value',stock.market))+':'+stock.code+
                        '（匹配：'+','.join(industry[stock.code])+'；不证明该公司受益或供货）'
                        for stock in stocks if stock.code in industry)
                    if macro:labels.append('海外/宏观线索：'+','.join(macro)+'；需说明对A/H股的具体传导，不能等同个股利好')
                    if market_wide:labels.append('全市场事件入口：独立于自选股；尚须评估A/H影响范围，不自动视为短线催化')
                    items.append(News(id='media-'+hashlib.sha256((provider+identifier).encode()).hexdigest()[:24],
                        title=row['title'],content=row['body'],summary=row['body'][:220],source=row['source'],
                        source_url=row['url'],published_at=published,news_type=NewsType.FINANCE,
                        related_stocks=direct,category='公司报道' if direct else '行业报道' if industry else '宏观报道' if macro else '全市场事件',
                        market_impact='；'.join(labels),importance_score=.86 if direct else .74,
                        is_china_related=bool(direct or industry)))
                    status[provider]['read']+=1
                except Exception as error:
                    status[provider]['errors'].append(dict(article_id=identifier,error=type(error).__name__,
                        reason=str(error)[:100] if isinstance(error,(ValueError,TimeoutError)) else 'public_article_request_failed'))
                finally:fill()
        for provider in status:
            if any(key[0]==provider and key not in attempted for key in selected):
                status[provider]['errors'].append(dict(stage='body',error='time_budget_exhausted'))
        for value in status.values():
            value['status']='not_requested' if not value['requested'] else 'partial' if value['errors'] and value['read'] else 'failed' if value['errors'] else 'ok' if value['read'] else 'no_material'
        coverage=dict(sources=status,news_window_hours=hours,queries=queries,query_topics=terms,
            stock_queries_not_planned=[stock.code for stock in stocks if stock.name not in queries],
            article_candidates=len(candidates),article_read=len(items),
            detail_budget=dict(limit=None,seconds=budget,attempted=len(attempted),not_attempted=len(candidates)-len(attempted)),
            unread_candidates=[dict(provider=key[0],id=key[1],title=candidates[key][0],reason='time_budget')
                for key in candidates if key not in attempted][:50],
            market_wide_articles=sum(item.source_url.rsplit('/',1)[-1] in {identifier for provider,identifier in market_keys} for item in items),
            limitation=('定向补查目前仅使用见闻公开搜索，不执行无关栏目扫描。' if targeted else '')+
                '搜索摘要不入模；仅已读取公开正文且在窗口内的报道。栏目扫描有限，不声明完整覆盖；行业关联不证明公司受益，研判仍需原始披露佐证。')
        per_stock={}
        for stock in stocks:
            direct_count=sum(stock.code in item.related_stocks for item in items)
            industry_count=sum(stock.code in relation(item.title,item.content,stocks,terms)[1] for item in items)
            per_stock[str(getattr(stock.market,'value',stock.market))+':'+stock.code]=dict(
                company_mentions=direct_count,industry_leads=industry_count,
                status='company_mentions_found' if direct_count else 'industry_only' if industry_count else 'no_matching_article')
        coverage['per_stock']=per_stock
        return sorted(items,key=lambda item:(item.importance_score,item.published_at),reverse=True),coverage

"""Direct publisher pages: public article bodies and source dates, no RSS proxy.

No account, signed/private API, paid article, model or snippet-as-body fallback.
Latest-page coverage is explicitly partial, even when every candidate was read.
"""
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timedelta,timezone
import hashlib
import json
import re
import time
from urllib.parse import urljoin,urlsplit

from bs4 import BeautifulSoup
import requests

from ..models.news import News
from .media_sources import topic_terms,relation,epoch_time,ROBOT
from .primary_sources import cached
from .research_hub import ResearchHub
from .time_context import china_now

SOURCES={
 'cls':dict(index='https://www.cls.cn/index',name='财联社公开原文',host='www.cls.cn',path=r'/detail/\d+'),
 'cnstock':dict(index='https://www.cnstock.com/',name='中国证券网公开原文',host='www.cnstock.com',path=r'/commonDetail/\d+'),
 'yicai':dict(index='https://www.yicai.com/news/',name='第一财经公开原文',host='www.yicai.com',path=r'/news/\d+\.html'),
 '21jingji':dict(index='https://www.21jingji.com/',name='21世纪经济报道公开原文',host='m.21jingji.com',path=r'/article/\d{8}/herald/\w+\.html'),
 'cs':dict(index='https://www.cs.com.cn/',name='中证网公开原文',host='www.cs.com.cn',path=r'/(?:ssgs|xwzx|gppd|tzjj|qs|gj|sy|hy|cj)/[\w/]+\.html'),
 'nbd':dict(index='https://www.nbd.com.cn/',name='每日经济新闻公开原文',host='www.nbd.com.cn',path=r'/articles/\d{4}-\d{2}-\d{2}/\d+\.html'),
 'ndrc':dict(index='https://www.ndrc.gov.cn/xwdt/',name='发改委公开原文',host='www.ndrc.gov.cn',path=r'/xwdt/(?:xwfb|tzgg)/\d{6}/t\d+_\d+\.html'),
 'sse':dict(index='https://www.sse.com.cn/aboutus/mediacenter/hotandd/',name='上交所公开原文',host='www.sse.com.cn',path=r'/aboutus/mediacenter/hotandd/c/c_\d+_\d+\.shtml'),
 'eeo':dict(index='https://www.eeo.com.cn/',name='经济观察网公开原文',host='www.eeo.com.cn',path=r'/\d{4}/\d{4}/\d+\.shtml',role='财经记者报道或分析，具体作者与事实归属以正文为准'),
 'jiemian':dict(index='https://www.jiemian.com/',name='界面新闻公开原文',host='www.jiemian.com',path=r'/article/\d+\.html',role='商业报道或评论，记者分析不是独立核实的事实'),
 'smm':dict(index='https://news.smm.cn/',name='上海有色网公开原文',host='news.smm.cn',path=r'/news/\d+',role='产业机构公开报道/市场观察；非交易所行情，观点、样本及数据口径需另核验'),
 'trendforce':dict(index='https://www.trendforce.com/presscenter',name='TrendForce公开研究发布',host='www.trendforce.com',path=r'/presscenter/news/\d{8}-\d+\.html',role='机构公开研究发布文章；不是订阅报告全文，预测必须归属TrendForce')}
FINANCE=('A股','港股','股市','上市','公司','收购','三季报','半年报','财报','银行','金融','证券','基金','政策','电力','能源',
 '电价','芯片','半导体','存储','科技','AI','资本','人民币','出口','外贸','国务院','经济','猪价','生猪','养殖','水电','煤炭',
 '原油','铜','黄金','债券','ETF','美联储','关税','需求','供给','发改委','价格','投资','产能','消费','工业','就业','地产',
 '旺季','增长','盈利','亏损','利润','订单','库存','交期','排产','钢铁','汽车','啤酒','零售','医药','航运','机器人','光伏','算力',
 'Anthropic','Server','Optical','CapEx','Memory','DRAM','NAND','Panel','Shipments')
RESTRICTED=('登录后阅读全文','购买后阅读','订阅后阅读','付费阅读全文','开通会员阅读全文','付费内容','剩余内容仅限会员')


def permitted(provider,url,index=False):
    config=SOURCES[provider];parts=urlsplit(url)
    if parts.scheme!='https' or parts.username or parts.password or parts.query or parts.fragment:return False
    if index:return url==config['index']
    return parts.hostname==config['host'] and bool(re.fullmatch(config['path'],parts.path))


def text(node):
    if node is None:return ''
    for tag in node.select('script,style,iframe,form,.related_artlist,.article-recommend'):tag.decompose()
    return node.get_text('\n',strip=True)


def date_value(raw):
    match=re.search(r'\d{4}[-/]\d{2}[-/]\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?',str(raw))
    if not match:raise ValueError('publisher_source_date_missing')
    value=match.group().replace('/','-')
    return datetime.fromisoformat(value),'second' if len(value)==19 else 'minute' if len(value)==16 else 'day'


def discover(provider,html,stocks,terms):
    soup=BeautifulSoup(html,'html.parser');result={}
    for anchor in soup.select('a[href]'):
        url=urljoin(SOURCES[provider]['index'],anchor['href'])
        # The publisher's own homepage advertises HTTP article links; HTTPS
        # was separately verified on the same host, never follow arbitrary hosts.
        if provider=='eeo' and url.startswith('http://www.eeo.com.cn/'):
            url='https://'+url[len('http://'):]
        if not permitted(provider,url):continue
        heading=anchor.select_one('h2,h3,h4')
        title=(heading or anchor).get_text(' ',strip=True)
        if not 6<=len(title)<=180 or ROBOT.search(title):continue
        direct,industry,macro=relation(title,'',stocks,terms)
        if not (direct or industry or macro or any(word in title for word in FINANCE)):continue
        rank=10*bool(direct)+5*bool(industry)+2*bool(macro)
        hint=re.search(r'/(\d{4}-\d{2}-\d{2})/|/article/(\d{8})/',urlsplit(url).path)
        day_hint=(hint.group(1) or hint.group(2)) .replace('-','') if hint else ''
        result.setdefault(url,dict(url=url,title=title,rank=rank,url_day_hint=day_hint))
    # URL dates prioritize reads only; they never substitute for source publication.
    return sorted(result.values(),key=lambda row:(row['rank'],row['url_day_hint']),reverse=True)


def parse_article(provider,html,url):
    if not permitted(provider,url):raise ValueError('publisher_article_url_rejected')
    soup=BeautifulSoup(html,'html.parser');config=SOURCES[provider]
    title='';body='';raw_date='';upstream='';precision=None
    if provider in {'cls','cnstock'}:
        script=soup.select_one('#__NEXT_DATA__')
        if not script:raise ValueError('publisher_public_page_state_missing')
        data=json.loads(script.get_text())['props']['pageProps']
        if provider=='cls':
            row=data['articleDetail']
            if str(row.get('id'))!=url.rsplit('/',1)[-1] or row.get('isFree') is not True:
                raise ValueError('publisher_identity_or_free_access_rejected')
            title=row.get('title','');body=text(BeautifulSoup(row.get('content',''),'html.parser'))
            stamp=epoch_time(row.get('ctime'))
            if stamp is None:raise ValueError('publisher_source_date_missing')
            raw_date=stamp.isoformat(sep=' ')
        else:
            row=data['data']
            if str(row.get('contId'))!=url.rsplit('/',1)[-1]:raise ValueError('publisher_identity_rejected')
            # Only the public page's text field, never account APIs or summaries.
            if any(row.get(key) in (True,1,'1') for key in ('isPay','isPaid','needPay','isVip')):
                raise ValueError('publisher_paid_access_rejected')
            title=row.get('title','');raw_date=row.get('pubTime','');upstream=row.get('source','')
            body=text(BeautifulSoup((row.get('textInfo') or {}).get('content',''),'html.parser'))
    elif provider=='yicai':
        title=text(soup.select_one('h1'));raw_date=text(soup.select_one('.m-text .f-cb'))
        body=text(soup.select_one('#multi-text'))
    elif provider=='21jingji':
        title=text(soup.select_one('h1'));raw_date=text(soup.select_one('.newsDate,.titleHead .author-infos span'))
        body=text(soup.select_one('.main_content'))
    elif provider=='cs':
        title=text(soup.select_one('#title,h1'));raw_date=text(soup.select_one('.artc_info time'))
        node=soup.select_one('.cont_article')
        if node:
            for tag in node.select('header,aside,.artc_info,.artc_route,h1,h4'):tag.decompose()
        body=text(node)
    elif provider=='nbd':
        title=text(soup.select_one('.g-article h1'));raw_date=text(soup.select_one('.u-time .time'))
        body=text(soup.select_one('.g-articl-text'))
        # The footer is not reporting and must not become source evidence.
        for marker in ('如需转载请','未经《每日经济新闻》','读者热线：'):
            body=body.split(marker,1)[0].strip()
    elif provider=='ndrc':
        meta=soup.select_one('meta[name="ArticleTitle"]');date=soup.select_one('meta[name="PubDate"]')
        title=meta.get('content','') if meta else '';raw_date=date.get('content','') if date else ''
        body=text(soup.select_one('.article_con .TRS_Editor,.article_con .TRS_PreAppend,.article_con'))
    elif provider=='sse':
        title=text(soup.select_one('.article-infor h2'));raw_date=text(soup.select_one('.article_opt i'))
        body=text(soup.select_one('.article-infor .allZoom'))
    elif provider=='eeo':
        title=text(soup.select_one('h1'));raw_date=text(soup.select_one('#showFocus'))
        body=text(soup.select_one('.xx_boxsing'))
    elif provider=='jiemian':
        title=text(soup.select_one('h1'));raw_date=text(soup.select_one('.info-s'))
        body=text(soup.select_one('.article-content'))
    elif provider=='smm':
        script=soup.select_one('#__NEXT_DATA__')
        if not script:raise ValueError('publisher_public_page_state_missing')
        row=json.loads(script.get_text())['props']['pageProps']['newsDetail']
        if str(row.get('newsId'))!=url.rsplit('/',1)[-1]:raise ValueError('publisher_identity_rejected')
        if (row.get('isVip') is not False or row.get('isLoginVisible') is not False
                or row.get('hasPerm') is not True or row.get('remainWords') or row.get('disable')):
            raise ValueError('publisher_paid_access_rejected')
        title=row.get('title','');raw_date=text(soup.select_one('time'));upstream=row.get('source','')
        # Public page state only. Image-only research is not text extraction.
        body=text(BeautifulSoup(row.get('content',''),'html.parser'))
        if len(body)<300:raise ValueError('publisher_full_body_unavailable')
    elif provider=='trendforce':
        node=soup.select_one('article.presscenter')
        title=text(node.select_one('h1')) if node else ''
        raw_date=text(node.select_one('.tag-row span')) if node else ''
        body='\n'.join(text(p) for p in node.find_all('p',recursive=False)) if node else ''
        day=datetime.strptime(raw_date.strip(),'%d %B %Y')
        raw_date=day.strftime('%Y-%m-%d')
    if not title.strip() or len(body)<100:raise ValueError('publisher_full_body_unavailable')
    if any(marker in body for marker in RESTRICTED):raise ValueError('publisher_restricted_content')
    published,precision=date_value(raw_date)
    result=dict(title=title.strip(),body=body,published=published.isoformat(),date_precision=precision,
        url=url,source=config['name'],upstream=upstream,
        reading='公开文章页正文；页面状态正文不等于独立核验，文内事件日期可能早于页面发布时间')
    if provider=='trendforce':
        # No clock/timezone is supplied. Use conservative bounds for admission,
        # but display only the actual source day (never a fabricated clock).
        cst=timezone(timedelta(hours=8))
        result['publication_start']=published.replace(tzinfo=timezone(timedelta(hours=14))).astimezone(cst).replace(tzinfo=None).isoformat()
        result['publication_end']=(published+timedelta(days=1)).replace(tzinfo=timezone(timedelta(hours=-12))).astimezone(cst).replace(tzinfo=None).isoformat()
        result['reading']+='；原始来源时点：'+raw_date+'（时分及来源时区未提供）；精度：day；公开研究发布，不等于完整订阅报告'
    return result


class PublicNewsCollector:
    def __init__(self,root=None):self.hub=ResearchHub(root)

    def get(self,provider,url,deadline,index=False):
        if not permitted(provider,url,index):raise ValueError('publisher_host_or_path_rejected')
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('publisher_time_budget_exhausted')
        response=requests.get(url,headers={'User-Agent':'Mozilla/5.0'},timeout=min(7,remaining),allow_redirects=False)
        response.raise_for_status()
        if response.status_code!=200 or len(response.content)>3*1024*1024:
            raise ValueError('publisher_response_invalid')
        response.encoding=response.apparent_encoding or 'utf-8'
        return response.text

    def index(self,provider,deadline):
        return cached(self.hub,'publisher:index:v1:'+provider,600,
            lambda:self.get(provider,SOURCES[provider]['index'],deadline,True))

    def detail(self,provider,url,deadline):
        from .source_health import PAUSED_PUBLIC_ARTICLES,RetiredSourceError
        if url in PAUSED_PUBLIC_ARTICLES:
            raise RetiredSourceError('source_paused_no_automatic_retest')
        return cached(self.hub,'publisher:article:v1:'+url,3600,
            lambda:parse_article(provider,self.get(provider,url,deadline),url))

    def collect(self,stocks,profiles,hours=72,budget=50,providers=None):
        names=list(providers if providers is not None else SOURCES)
        now=china_now();cutoff=now-timedelta(hours=hours);deadline=time.monotonic()+budget
        terms={stock.code:topic_terms(profiles.get(str(getattr(stock.market,'value',stock.market))+':'+stock.code,{})) for stock in stocks}
        statuses={key:dict(index=SOURCES[key]['index'],candidates=0,attempted=0,read=0,
            excluded_old_or_future=0,errors=[],complete_window=False) for key in names}
        queues={key:[] for key in names};articles=[]
        with ThreadPoolExecutor(max_workers=4) as pool:
            pending={pool.submit(self.index,key,deadline):key for key in names}
            for future in as_completed(pending):
                key=pending[future]
                try:
                    queues[key]=discover(key,future.result(),stocks,terms)
                    statuses[key]['candidates']=len(queues[key])
                except Exception as error:statuses[key]['errors'].append(dict(stage='index',error=type(error).__name__))
        # One request in flight per provider, round robin across providers.
        with ThreadPoolExecutor(max_workers=4) as pool:
            pending={};busy=set();turn=0
            def fill():
                nonlocal turn
                while len(pending)<4 and time.monotonic()<deadline:
                    chosen=None
                    for _ in names:
                        key=names[turn%len(names)];turn+=1
                        if queues[key] and key not in busy:chosen=key;break
                    if chosen is None:break
                    candidate=queues[chosen].pop(0);busy.add(chosen);statuses[chosen]['attempted']+=1
                    pending[pool.submit(self.detail,chosen,candidate['url'],deadline)]=(chosen,candidate)
            fill()
            while pending:
                future=next(as_completed(pending));key,candidate=pending.pop(future);busy.remove(key)
                try:
                    row=future.result();published=datetime.fromisoformat(row['published'])
                    start=datetime.fromisoformat(row.get('publication_start',row['published']))
                    end=datetime.fromisoformat(row.get('publication_end',row['published']))
                    if not cutoff<=start<=end<=now:
                        statuses[key]['excluded_old_or_future']+=1;continue
                    direct,industry,macro=relation(row['title'],row['body'],stocks,terms)
                    labels=['独立直连采集入口；不表示原创或独立佐证；页面时间精度：'+row['date_precision'],row['reading']]
                    if SOURCES[key].get('role'):labels.append(SOURCES[key]['role'])
                    if row.get('upstream'):labels.append('页面标明转载来源：'+row['upstream'])
                    for stock in stocks:
                        if stock.code in industry:
                            labels.append('行业关联 '+str(getattr(stock.market,'value',stock.market))+':'+stock.code+
                                '（匹配：'+','.join(industry[stock.code])+'；不证明受益、客户或订单）')
                    if not direct and not industry:labels.append('全市场事件入口：须另证A/H传导，不因采到而自动重要')
                    articles.append(News(id='direct-'+hashlib.sha256(row['url'].encode()).hexdigest()[:24],
                        title=row['title'],content=row['body'],summary=row['body'][:220],source=row['source'],source_url=row['url'],
                        published_at=published,related_stocks=direct,importance_score=.85 if direct else .72,
                        market_impact='；'.join(labels),category='公司报道' if direct else '行业报道' if industry else '全市场事件',
                        is_china_related=True))
                    statuses[key]['read']+=1
                except Exception as error:
                    reason=str(error)
                    statuses[key]['errors'].append(dict(url=candidate['url'],error=type(error).__name__,
                        reason=reason if re.fullmatch(r'(?:cached_primary_failure:\w+:)?publisher_\w+|source_paused_no_automatic_retest',reason) else 'public_article_read_failed'))
                finally:fill()
        for key,state in statuses.items():
            state['not_attempted']=len(queues[key])
            state['status']='partial' if state['errors'] or queues[key] else 'ok' if state['read'] else 'no_recent_material'
            if not state['read'] and state['errors']:state['status']='failed'
        return articles,dict(sources=statuses,window_hours=hours,seconds=budget,read=len(articles),
            limit=None,complete_window=False,limitation='直连列明公开入口；仅扫描首页/当前列表，非72小时全量或全网。正文各有原日期与转载归属；多家报道不等于独立事件。无模型/付费搜索/会员请求。')

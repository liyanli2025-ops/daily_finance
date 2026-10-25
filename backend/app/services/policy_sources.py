"""Small, dated regulator originals feed. No inferred policy effects or net liquidity."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timedelta
import hashlib
import re
import time
from urllib.parse import urljoin,urlsplit

from bs4 import BeautifulSoup
import requests

from ..models.news import News,NewsType
from .research_hub import ResearchHub
from .primary_sources import cached
from .time_context import china_now

SOURCES={
    'csrc_news':dict(url='https://www.csrc.gov.cn/',name='证监会原文'),
    'pbc_operations':dict(url='https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/125475/index.html',name='央行公开市场操作原文'),
    'pbc_news':dict(url='https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html',name='央行新闻原文')}
POLICY=('征求意见','规定','规则','办法','降准','利率','政策','公开市场','金融支持','融资','交易','监管')
EXCLUDE=('会见','纪念币','招聘','招标','采购','讣告','行政许可事项','企业基本情况','受理及审核情况')


def permitted(url):
    parts=urlsplit(url)
    if parts.scheme!='https' or parts.username or parts.password or parts.query:
        return False
    if parts.hostname=='www.csrc.gov.cn':
        return bool(re.fullmatch(r'/csrc/c\d+/c\d+/content.shtml',parts.path))
    if parts.hostname=='www.pbc.gov.cn':
        return bool(re.fullmatch(r'/(?:goutongjiaoliu/113456/113469|zhengcehuobisi/125207/125213/125431/125475)/\d+/index.html',parts.path))
    return False


def index_links(html,source,now,hours):
    soup=BeautifulSoup(html,'html.parser')
    result={}
    for anchor in soup.select('a[href]'):
        url=urljoin(SOURCES[source]['url'],anchor['href'])
        title=anchor.get_text(' ',strip=True)
        if (not permitted(url) or urlsplit(url).hostname!=urlsplit(SOURCES[source]['url']).hostname
                or not any(word in title for word in POLICY) or any(word in title for word in EXCLUDE)):
            continue
        parent=anchor.find_parent('li') if source=='csrc_news' else anchor.find_parent('tr')
        context=parent.get_text(' ',strip=True) if parent else ''
        dates=re.findall(r'\d{4}-\d{2}-\d{2}',context)
        if dates:
            day=datetime.strptime(dates[-1],'%Y-%m-%d').date()
            if not (now-timedelta(hours=hours)).date()<=day<=now.date():continue
        elif source=='csrc_news':
            # Month/day only helps choose what to fetch. NEVER supplies publication year.
            stamp=parent.select_one('.time') if parent else None
            if stamp:
                recent={(now-timedelta(days=i)).strftime('%m-%d') for i in range(int(hours/24)+2)}
                if stamp.get_text(strip=True) not in recent:continue
        result.setdefault(url,(title,bool(dates or (parent and parent.select_one('.time')))))
    return [(url,value[0]) for url,value in sorted(result.items(),key=lambda row:row[1][1],reverse=True)]


def parse_article(html,url):
    if not permitted(url):raise ValueError('policy_article_host_or_path_rejected')
    soup=BeautifulSoup(html,'html.parser')
    title=soup.select_one('meta[name="ArticleTitle"]')
    publication=soup.select_one('meta[name="PubDate"]')
    if not title or not publication:raise ValueError('policy_metadata_missing')
    title=title.get('content','').strip()
    stamp=publication.get('content','').strip()
    # Date-only sources are retained as date-only precision. Midnight is not a publication time.
    precision='second' if len(stamp)==19 else 'day'
    published=datetime.strptime(stamp,'%Y-%m-%d %H:%M:%S' if precision=='second' else '%Y-%m-%d')
    body=soup.select_one('.detail-news' if 'csrc.gov.cn' in urlsplit(url).hostname else '#zoom')
    if not body or not title:raise ValueError('policy_body_missing')
    for node in body.select('script,style'):node.decompose()
    text=body.get_text(' ',strip=True)
    if len(text)<60:raise ValueError('policy_body_too_short')
    return dict(title=title,body=text,published=published.isoformat(),precision=precision,url=url)


class PolicyCollector:
    def __init__(self,root=None):self.hub=ResearchHub(root)

    def html(self,url,deadline):
        if url not in {value['url'] for value in SOURCES.values()} and not permitted(url):
            raise ValueError('policy_url_rejected')
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('policy_budget_exhausted')
        response=requests.get(url,headers={'User-Agent':'Mozilla/5.0'},timeout=min(7,remaining),allow_redirects=False)
        response.raise_for_status()
        if response.status_code!=200 or len(response.content)>3*1024*1024:raise ValueError('policy_response_invalid')
        response.encoding='utf-8'
        return response.text

    def collect(self,hours=24,budget=25):
        now=china_now();deadline=time.monotonic()+budget
        items=[]
        status={key:dict(read=0,errors=[],excluded=0,requested=0) for key in SOURCES}
        def source_job(key):
            index=cached(self.hub,'policy:index:v2:'+key,900,lambda:self.html(SOURCES[key]['url'],deadline))
            candidates=index_links(index,key,now,hours)
            result=[]
            for url,_ in candidates[:2]:
                status[key]['requested']+=1
                try:
                    row=cached(self.hub,'policy:body:v1:'+url,21600,lambda:parse_article(self.html(url,deadline),url))
                    published=datetime.fromisoformat(row['published'])
                    # With only a date, the entire publication day must be inside the window.
                    # Today may contain information later than an early-morning cutoff: don't infer midnight availability.
                    if row['precision']=='day' and published.date()==now.date():
                        status[key]['excluded']+=1;continue
                    if not now-timedelta(hours=hours)<=published<=now:
                        status[key]['excluded']+=1;continue
                    title=row['title']
                    if any(word in title for word in EXCLUDE):
                        status[key]['excluded']+=1;continue
                    stage='征求意见阶段，不能写成正式生效' if '征求意见' in title else '法律状态及生效日须按原文核验，不能由发布日期推定'
                    result.append(News(id='policy-'+hashlib.sha256(url.encode()).hexdigest()[:24],title=title,content=row['body'],
                        summary=row['body'][:200],source=SOURCES[key]['name'],source_url=url,published_at=published,
                        news_type=NewsType.FINANCE,category='监管原文',importance_score=.88,is_china_related=True,
                        market_impact='全市场事件入口；监管原文；'+stage+'；发布时间精度='+row['precision']+
                        '；操作量不等于净投放，缺少到期量不得计算净流动性；不自动推导个股受益'))
                    status[key]['read']+=1
                except Exception as error:
                    status[key]['errors'].append(dict(error=type(error).__name__))
            return result
        with ThreadPoolExecutor(max_workers=3) as pool:
            pending={pool.submit(source_job,key):key for key in SOURCES}
            for future in as_completed(pending):
                key=pending[future]
                try:items.extend(future.result())
                except Exception as error:status[key]['errors'].append(dict(error=type(error).__name__))
        for row in status.values():
            row['status']='partial' if row['errors'] and row['read'] else 'failed' if row['errors'] else 'ok' if row['read'] else 'no_material'
        return items,dict(sources=status,limitation='仅列明监管栏目、最多6篇公开原文；没有新增不凑数，非全部政策覆盖；日期精度不足时保守排除。')

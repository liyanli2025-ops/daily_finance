"""Optional public WeChat discovery/reading. No login, paid API or challenge bypass."""
from datetime import datetime,timedelta,timezone
import hashlib
import html as html_module
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit,urljoin

from bs4 import BeautifulSoup
import requests

from ..models.news import News
from .media_sources import query_plan,relation
from .research_hub import ResearchHub,save_json
from .time_context import china_now

CONFIG=Path(__file__).resolve().parents[2]/'wechat_sources.json'


def diagnostic(error):
    reason=str(error)
    return dict(error=type(error).__name__,reason=reason if re.fullmatch(r'wechat_[a-z_]+',reason) else 'public_request_failed')


def permitted(url):
    try:
        parsed=urlsplit(url)
        return (parsed.scheme=='https' and not parsed.username and not parsed.password
            and parsed.port in (None,443) and ((parsed.hostname=='mp.weixin.qq.com' and
            (parsed.path=='/s' or parsed.path.startswith('/s/'))) or
            (parsed.hostname=='weixin.sogou.com' and parsed.path in {'/weixin','/link'})))
    except ValueError:return False


def search_links(html):
    soup=BeautifulSoup(html,'html.parser')
    text=soup.get_text(' ',strip=True)
    if len(text)<2000 and any(word in text for word in ('验证码','访问过于频繁','安全验证','异常访问')):
        raise ValueError('wechat_public_search_blocked')
    rows=[]
    for link in soup.select('.news-list h3 a[href]'):
        url=urljoin('https://weixin.sogou.com',link['href'])
        if permitted(url) and url not in rows:rows.append(url)
    if not rows and not any(word in text for word in ('没有找到相关','未找到相关')):
        raise ValueError('wechat_search_layout_unrecognized')
    return rows[:6]


def parse_article(html):
    soup=BeautifulSoup(html,'html.parser')
    title=soup.select_one('#activity-name');account=soup.select_one('#js_name');body=soup.select_one('#js_content')
    if not all((title,account,body)):
        if '参数错误' in soup.get_text(' ',strip=True):raise ValueError('wechat_article_link_invalid')
        raise ValueError('wechat_public_body_unavailable')
    stamp=re.search(r'\bvar\s+ct\s*=\s*[\"\']?(\d{10})',html)
    if stamp:
        published=datetime.fromtimestamp(int(stamp[1]),timezone(timedelta(hours=8))).replace(tzinfo=None)
    else:
        date=soup.select_one('#publish_time')
        value=date.get_text(' ',strip=True) if date else ''
        # Require an actual year; never infer today/year from a relative label.
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?',value):
            raise ValueError('wechat_publication_unknown')
        published=datetime.fromisoformat(value)
    text=body.get_text('\n',strip=True)
    if len(text)<120:raise ValueError('wechat_public_body_too_short')
    return dict(title=title.get_text(' ',strip=True),account=account.get_text(' ',strip=True),
        body=text,published=published.isoformat())


def literal_redirect(html):
    """Read a literal public landing URL; never execute JavaScript or tracking."""
    block=re.search(r"var\s+url\s*=\s*''\s*;(?P<body>.*?)window\.location\.replace\(url\)",html,re.S)
    if not block:raise ValueError('wechat_search_redirect_not_resolved')
    parts=re.findall(r"url\s*\+=\s*'([^'\\]*)'\s*;",block['body'])
    target=html_module.unescape(''.join(parts))
    if (not parts or len(parts)>100 or len(target)>4096 or not permitted(target)
            or urlsplit(target).hostname!='mp.weixin.qq.com'):
        raise ValueError('wechat_literal_redirect_rejected')
    return target


class WeChatCollector:
    def __init__(self,root=None,config=None):
        self.hub=ResearchHub(root)
        self.config=config

    def get(self,url,deadline,params=None):
        if not permitted(url):raise ValueError('wechat_url_not_allowed')
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('wechat_budget')
        response=requests.get(url,params=params,timeout=min(6,remaining),allow_redirects=False,
            headers={'User-Agent':'Mozilla/5.0'})
        if response.status_code in (301,302,303,307,308):
            target=urljoin(url,response.headers.get('Location',''))
            if not permitted(target):raise ValueError('wechat_redirect_rejected')
            return None,target
        response.raise_for_status()
        if response.status_code!=200 or len(response.content)>3*1024*1024:
            raise ValueError('wechat_response_invalid')
        response.encoding='utf-8'
        return response.text,url

    def read(self,url,deadline):
        for _ in range(3):
            html,current=self.get(url,deadline)
            if html is None:url=current;continue
            if urlsplit(current).hostname!='mp.weixin.qq.com':
                url=literal_redirect(html)
                continue
            row=parse_article(html);row['url']=current
            return row
        raise ValueError('wechat_redirect_limit')

    def collect(self,stocks,profiles,hours=24,budget=15):
        if self.config is None:
            try:config=json.loads(CONFIG.read_text(encoding='utf-8'))
            except FileNotFoundError:config={}
        else:config=self.config
        search_enabled=config.get('public_search_enabled') is True
        urls=[url for url in config.get('article_urls',[]) if isinstance(url,str) and permitted(url)
              and urlsplit(url).hostname=='mp.weixin.qq.com'][:6]
        status=dict(status='disabled',search_enabled=search_enabled,discovered=0,read=0,errors=[],
            limitation='有限公开文章样本；不保证账号全量、阅读量或来源独立性。第三方付费接口未启用，无自动付费请求。')
        if not search_enabled and not urls:return [],status
        now=china_now();deadline=time.monotonic()+budget
        queries,terms=query_plan(stocks,profiles,limit=4)
        state=self.hub.root/'wechat-public-cooldown.json'
        try:cooldown=json.loads(state.read_text(encoding='utf-8'))
        except (OSError,ValueError):cooldown={}
        search_cooling=False
        try:search_cooling=now<datetime.fromisoformat(cooldown['until'])
        except (ValueError,KeyError,TypeError):pass
        if search_enabled and search_cooling:
            status['search_status']='cooldown';status['retry_after']=cooldown['until']
        elif search_enabled:
            for query in queries[:2]:
                try:
                    html,_=self.get('https://weixin.sogou.com/weixin',deadline,
                        dict(type=2,query=query,ie='utf8'))
                    if html is None:raise ValueError('wechat_search_redirect_rejected')
                    urls.extend(search_links(html))
                    status['search_status']='sampled'
                except Exception as error:
                    status['errors'].append(dict(stage='search',**diagnostic(error)))
                    status['search_status']='unavailable'
                    save_json(state,dict(until=(now+timedelta(hours=6)).isoformat(),error=type(error).__name__))
                    break
        items=[]
        urls=list(dict.fromkeys(urls))[:6];status['discovered']=len(urls)
        for url in urls:
            try:
                row=self.read(url,deadline);published=datetime.fromisoformat(row['published'])
                if not now-timedelta(hours=hours)<=published<=now:continue
                direct,industry,macro=relation(row['title'],row['body'],stocks,terms)
                if not (direct or industry or macro):continue
                labels=['公众号作者观点或报道，非自动认定为公司一手披露；不得把阅读量当可靠性或独立核实']
                labels.extend('行业关联 '+str(getattr(stock.market,'value',stock.market))+':'+stock.code+
                    '（匹配：'+','.join(industry[stock.code])+'；不证明受益）' for stock in stocks if stock.code in industry)
                items.append(News(id='wechat-'+hashlib.sha256(row['url'].encode()).hexdigest()[:24],
                    title=row['title'],content=row['body'],source='微信公众号原文-'+row['account'],
                    source_url=row['url'],published_at=published,related_stocks=direct,
                    market_impact='；'.join(labels),importance_score=.72,is_china_related=bool(direct or industry)))
            except Exception as error:
                status['errors'].append(dict(stage='body',**diagnostic(error)))
        status['read']=len(items)
        if search_enabled and not items and status['errors']:
            save_json(state,dict(until=(now+timedelta(hours=6)).isoformat(),error='public_source_unavailable'))
        status['status']='partial' if items and status['errors'] else 'ok' if items else 'unavailable' if status['errors'] or search_cooling else 'no_matching_material'
        return items,status

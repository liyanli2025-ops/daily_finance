"""Public domestic publisher lists and visible article bodies, no RSS proxy.

Endpoint discovery references RSSHub caijing/roll, tmtpost/new and
thepaper/channel. Our article readers require public visible bodies, retain
attribution, and never fall back from a missing body to a summary.
"""
from datetime import datetime,timedelta
import json
import re
from bs4 import BeautifulSoup


def entries(provider,content):
    data=json.loads(content)
    if provider=='thepaper':
        rows=data['data']['list']
        return [dict(title=x['name'],url='https://m.thepaper.cn/newsDetail_forward_'+str(x['contId']))
                for x in rows if not x.get('link') and x.get('paywalled') is False]
    if provider=='tmtpost':
        rows=data['data']
        return [dict(title=x['title'],url=x.get('share_link') or '') for x in rows
                if x.get('is_paid_special_column_post') is False and not x.get('is_popularize') in (1,'1',True)]
    if provider=='caijing':
        return [dict(title=x['title'],url=x['url']) for x in data]
    raise ValueError('publisher_response_invalid')


def article(provider,html,url):
    from .public_news_sources import text,date_value,RESTRICTED,SOURCES
    from .media_sources import epoch_time
    from .overseas_sources import ld_restricted
    soup=BeautifulSoup(html,'html.parser');upstream='';author='';precision=None
    if ld_restricted(soup):raise ValueError('publisher_paid_access_rejected')
    if provider=='thepaper':
        node=soup.select_one('#__NEXT_DATA__')
        if not node:raise ValueError('publisher_public_page_state_missing')
        detail=json.loads(node.get_text())['props']['pageProps']['detailData']['contentDetail']
        if str(detail.get('contId'))!=url.rsplit('_',1)[-1]:raise ValueError('publisher_identity_rejected')
        if detail.get('paywalled') in (True,1,'1') or detail.get('isPay') in (True,1,'1'):
            raise ValueError('publisher_paid_access_rejected')
        title=detail.get('name','');body=text(BeautifulSoup(detail.get('content') or '', 'html.parser'))
        # Public page JSON may include a hidden preview. Require both ends of
        # the body in rendered HTML text, not only inside script state.
        normalized=lambda value:re.sub(r'\s+','',value)
        visible=normalized(soup.get_text(' ',strip=True));flat=normalized(body)
        if not flat or flat[:80] not in visible or flat[-80:] not in visible:
            raise ValueError('publisher_full_body_unavailable')
        try:stamp=epoch_time(float(detail['publishTime'])/1000)
        except (TypeError,ValueError,KeyError):stamp=None
        if stamp is None:raise ValueError('publisher_source_date_missing')
        raw_date=stamp.isoformat(sep=' ');author=detail.get('author') or '';upstream=detail.get('source') or ''
    elif provider=='tmtpost':
        node=soup.select_one('._content_mode')
        title=text(node.select_one('h2.tit')) if node else ''
        raw_date=text(node.select_one('.post_author_infor .time')).replace('.','-') if node else ''
        body=text(node.select_one('._bottom')) if node else ''
        author=text(node.select_one('.post_author .name')) if node else ''
        if node and any(word in node.get_text() for word in ('付费阅读全文','订阅后阅读','购买后阅读','解锁全文')):
            raise ValueError('publisher_paid_access_rejected')
    elif provider=='caijing':
        title=text(soup.select_one('.article h2')) or text(soup.select_one('h1'))
        raw_date=text(soup.select_one('#pubtime_baidu')) or text(soup.select_one('.article .news_time'))
        body=text(soup.select_one('.article-content'))
        upstream=text(soup.select_one('.news_frome'));author=text(soup.select_one('#editor_baidu,.editor'))
    else:raise ValueError('publisher_article_url_rejected')
    if not title or len(body)<100:raise ValueError('publisher_full_body_unavailable')
    if any(word in body for word in RESTRICTED):raise ValueError('publisher_restricted_content')
    stamp,precision=date_value(raw_date)
    return dict(title=title,body=body,published=stamp.isoformat(),date_precision=precision,
                publication_start=stamp.isoformat(),
                publication_end=(stamp+timedelta(days=1)).isoformat() if precision=='day' else stamp.isoformat(),
                url=url,source=SOURCES[provider]['name'],upstream=upstream,author=author,
                reading='公开页面正文；作者：'+(author or '未单列')+'；转载来源：'+(upstream or '未单列')+
                    '；日期精度：'+precision+'；非独立事实核验')

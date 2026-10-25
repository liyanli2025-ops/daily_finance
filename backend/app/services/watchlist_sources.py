"""Bounded, timestamped watchlist feeds. No model calls or credentials."""
from datetime import datetime, timedelta
import hashlib
import math
import re
import time
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

from ..models.news import News, NewsType, SentimentType
from .time_context import china_now


def symbol_for(stock):
    market = str(getattr(stock.market, 'value', stock.market))
    if market == 'HK' and re.fullmatch(r'\d{1,5}', stock.code):
        return 'hk' + stock.code.zfill(5)
    if market == 'A' and re.fullmatch(r'\d{6}', stock.code):
        return ('sh' if stock.code.startswith(('6', '9')) else
                'bj' if stock.code.startswith(('4', '8', '92')) else 'sz') + stock.code
    return None


def parse_tencent_quotes(text, stocks, now=None):
    now = now or china_now()
    requested = {symbol_for(stock): stock for stock in stocks if symbol_for(stock)}
    quotes = {}
    for symbol, value in re.findall(r'v_(\w+)="([^"]*)"', text):
        stock = requested.get(symbol)
        fields = value.split('~')
        if stock is None or len(fields) < 34:
            continue
        try:
            # Validate identity as well as the response variable name.
            if fields[2].zfill(len(stock.code)) != stock.code.zfill(len(fields[2])):
                continue
            pattern = '%Y/%m/%d %H:%M:%S' if symbol.startswith('hk') else '%Y%m%d%H%M%S'
            stamp = datetime.strptime(fields[30], pattern)
            price, change_pct = float(fields[3]), float(fields[32])
            if stamp > now or price <= 0 or not all(map(math.isfinite, (price, change_pct))):
                continue
            quotes[stock.code] = dict(name=fields[1], price=price, change_pct=change_pct,
                                     as_of=stamp.isoformat(), source='腾讯财经', currency='HKD' if symbol.startswith('hk') else 'CNY')
        except (ValueError, TypeError, OverflowError):
            continue
    return quotes


def fetch_watchlist_quotes(stocks):
    symbols = [symbol_for(stock) for stock in stocks if symbol_for(stock)]
    if not symbols:
        return {}
    quotes = {}
    # Bounded batches also support long App watchlists without querying all stocks.
    for index in range(0, len(symbols), 60):
        try:
            response = requests.get('https://qt.gtimg.cn/q=' + ','.join(symbols[index:index+60]),
                                    headers={'User-Agent':'Mozilla/5.0'}, timeout=10)
            response.raise_for_status()
            response.encoding = 'gbk'
            quotes.update(parse_tencent_quotes(response.text, stocks))
        except (requests.RequestException, ValueError, AttributeError) as error:
            print(f'[自选股行情] 腾讯批量请求失败：{type(error).__name__}', flush=True)
    print(f'[自选股行情] 腾讯带来源时间报价 {len(quotes)}/{len(stocks)}', flush=True)
    return quotes


def publication_time(value):
    for pattern in ('%Y-%m-%d %H:%M:%S:%f', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(value or '', pattern)
        except (ValueError, TypeError):
            pass
    return None


def fetch_sina_stock_news(stock, hours=24, now=None):
    """Read a dated per-stock index and article bodies, rather than search snippets."""
    now = now or china_now()
    symbol = symbol_for(stock)
    if not symbol or str(getattr(stock.market, 'value', stock.market)) != 'A':
        return [], {'status':'unsupported', 'reason':'此新闻列表仅支持A股'}
    deadline = time.monotonic() + 35
    def get(url):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise requests.Timeout('逐股新闻采集预算已耗尽')
        response = requests.get(url, headers={'User-Agent':'Mozilla/5.0'},
                                timeout=min(10, remaining), allow_redirects=False)
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError('新闻请求不是完整页面')
        return response
    response = get(f'https://vip.stock.finance.sina.com.cn/corp/go.php/vCB_AllNewsStock/symbol/{symbol}.phtml')
    response.encoding = 'gb18030'
    soup = BeautifulSoup(response.text, 'html.parser')
    listing = soup.select_one('.datelist')
    if listing is None:
        raise ValueError('逐股新闻列表结构异常')
    selected, latest = [], None
    for link in listing.select('a[href]'):
        raw = re.sub(r'\s+', ' ', str(link.previous_sibling or '')).strip()
        try:
            published = datetime.strptime(raw, '%Y-%m-%d %H:%M')
        except ValueError:
            continue
        if published > now:
            continue
        latest = max(latest, published) if latest else published
        if published < now - timedelta(hours=hours):
            continue
        url = link['href']
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname != 'finance.sina.com.cn'
                or parsed.username or parsed.password or not parsed.path.endswith('.shtml')):
            continue
        selected.append((published, url, link.get_text(strip=True)))
    items, errors = [], []
    for published, url, title in sorted(selected, reverse=True)[:3]:
        try:
            response = get(url)
            response.encoding = 'utf-8'
            article = BeautifulSoup(response.text, 'html.parser')
            body = article.select_one('#artibody')
            date_element = article.select_one('.date')
            if body is None or date_element is None:
                raise ValueError('缺少正文或原文发布时间')
            date_match = re.search(r'(\d{4})年(\d{2})月(\d{2})日\s*(\d{2}):(\d{2})', date_element.get_text(' ', strip=True))
            if not date_match or datetime(*map(int, date_match.groups())) != published:
                raise ValueError('列表与原文发布时间不一致')
            for tag in body.select('script, style, iframe, .article-editor, .appendQr_wrap'):
                tag.decompose()
            paragraphs = [p.get_text(' ', strip=True) for p in body.select('p')]
            content = '\n'.join(p for p in paragraphs if p)
            if len(content) < 80 or (stock.name not in content and stock.code not in content):
                raise ValueError('正文不足或无法确认与该股票相关')
            automated = '/aiassist/' in url
            items.append(News(
                id=hashlib.sha256(url.encode()).hexdigest()[:24], title=title,
                content=('二手报道，未经独立核实；' + ('此条为自动生成快讯，不是独立人工调查。' if automated else '')
                         + '文中历史融资、交易数据只属于原文所述交易日，不能改写成今日盘中资金；'
                         '融资买入额不等于净买入，也不能单独推出股价方向或重大催化。\n' + content),
                source='新浪财经-' + ('自动生成快讯' if automated else '逐股新闻'), source_url=url,
                published_at=published, news_type=NewsType.FINANCE, sentiment=SentimentType.NEUTRAL,
                importance_score=0.65 if automated else 0.8, is_china_related=True,
                category='自选股-新闻', related_stocks=[stock.code]))
        except (requests.RequestException, ValueError, TypeError) as error:
            errors.append(type(error).__name__)
    return items, dict(status='partial' if errors or len(selected)>3 else 'ok',
                       retrieved=len(listing.select('a[href]')), eligible_in_window=len(selected),
                       full_text=len(items), latest_publication=latest.isoformat() if latest else None,
                       body_errors=errors)


def fetch_company_announcements(stock, hours=24, now=None):
    """Search each A-share issuer, then read full announcement text for fresh hits.

    display_time is public availability; notice_date is a separate document date.
    Never substitute a retrieval time or the next-day document date for release time.
    """
    now = now or china_now()
    if str(getattr(stock.market, 'value', stock.market)) != 'A':
        return [], {'status':'unsupported', 'reason':'此公告源仅支持A股'}
    deadline = time.monotonic() + 35
    def get(url, **kwargs):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise requests.Timeout('公告采集预算已耗尽')
        return requests.get(url, timeout=min(10, remaining), **kwargs)
    response = get('https://np-anotice-stock.eastmoney.com/api/security/ann',
                            params={'sr':-1, 'page_size':20, 'page_index':1, 'ann_type':'A',
                                    'client_source':'web', 'stock_list':stock.code})
    response.raise_for_status()
    data = response.json().get('data')
    if not isinstance(data, dict) or not isinstance(data.get('list'), list):
        raise ValueError('公告列表结构异常')
    rows = data['list']
    matches = []
    latest = None
    for row in rows:
        if not any(str(code.get('stock_code')) == stock.code for code in row.get('codes', [])):
            continue
        published = publication_time(row.get('display_time'))
        if published is None or published > now:
            continue
        latest = max(latest, published) if latest else published
        if now - timedelta(hours=hours) <= published:
            matches.append((published, row))
    result, errors = [], []
    for published, row in sorted(matches, key=lambda pair: pair[0], reverse=True)[:3]:
        art = str(row.get('art_code', ''))
        if not re.fullmatch(r'AN\d+', art):
            continue
        try:
            pages = []
            page_count = 1
            for page in range(1, 6):
                body = get('https://np-cnotice-stock.eastmoney.com/api/content/ann',
                           params={'art_code':art, 'client_source':'web', 'page_index':page})
                body.raise_for_status()
                detail = body.json().get('data') or {}
                if detail.get('art_code') != art:
                    raise ValueError('公告正文编号不匹配')
                page_count = int(detail.get('page_size', 0))
                content = detail.get('notice_content')
                if not 1 <= page_count <= 5 or not isinstance(content, str) or not content.strip():
                    raise ValueError('公告正文缺失或超出5页完整读取上限')
                pages.append(content.strip())
                if page >= page_count:
                    break
            # A repeated page is not a complete multipage document.
            if len(pages) != page_count or len(set(pages)) != len(pages):
                raise ValueError('公告正文分页不完整')
            result.append(News(
                id=hashlib.sha256(('announcement:'+stock.code+':'+art).encode()).hexdigest()[:24],
                title=str(row.get('title') or stock.name+'公告'),
                content=f"上市公司公告正文，东方财富披露镜像。公开时间：{published.isoformat()}；"
                        f"文件公告日期：{row.get('notice_date', '未提供')}。两者不可混同。\n" + '\n'.join(pages),
                source=f'上市公司公告-东方财富披露镜像-{stock.name}',
                source_url=f'https://data.eastmoney.com/notices/detail/{stock.code}/{art}.html',
                published_at=published, news_type=NewsType.FINANCE,
                sentiment=SentimentType.NEUTRAL, importance_score=0.9,
                is_china_related=True, category='自选股-公告', related_stocks=[stock.code]))
        except (requests.RequestException, ValueError, TypeError) as error:
            errors.append(type(error).__name__)
    return result, dict(status='partial' if errors or len(matches)>3 else 'ok',
                        retrieved=len(rows), in_window=len(matches), full_text=len(result),
                        latest_publication=latest.isoformat() if latest else None,
                        body_errors=errors)

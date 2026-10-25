"""Daily report market inputs: exact index identities and provider timestamps.

Other legacy tables stay out of this path until their actual observation dates
can be checked. A requested date is never proof of a returned table's date.
"""
from datetime import datetime, timedelta
import math
import re

import requests

from .time_context import china_now, china_today

INDICES = {
    'sh000001': ('000001','上证指数','A股'),
    'sz399001': ('399001','深证成指','A股'),
    'sz399006': ('399006','创业板指','A股'),
    'sh000300': ('000300','沪深300','A股'),
    'sh000688': ('000688','科创50','A股'),
    'hkHSI': ('HSI','恒生指数','港股'),
    'hkHSCEI': ('HSCEI','恒生国企指数','港股'),
    'hkHSTECH': ('HSTECH','恒生科技指数','港股'),
    'usDJI': ('.DJI','道琼斯指数','美股'),
    'usIXIC': ('.IXIC','纳斯达克综合指数','美股'),
    'usINX': ('.INX','标普500指数','美股'),
}
UNVERIFIED = ['板块排行','资金流向','涨跌停','市场涨跌家数','热门股票','概念板块',
              '连板股','技术信号','大宗商品','龙虎榜席位','大宗交易','融资融券']


def parse_quotes(text, now=None):
    now = now or china_now()
    rows = []
    for symbol, payload in re.findall(r'v_([A-Za-z0-9]+)="([^"\r\n]*)"',text):
        if symbol not in INDICES:
            continue
        code,name,region = INDICES[symbol]
        fields = payload.split('~')
        if len(fields)<35 or fields[2] != code:
            continue
        stamp = None
        for pattern in ('%Y%m%d%H%M%S','%Y/%m/%d %H:%M:%S','%Y-%m-%d %H:%M:%S'):
            try:
                stamp = datetime.strptime(fields[30],pattern)
                break
            except ValueError:
                pass
        # The source doesn't declare its timezone. Preserve its own clock and
        # validate only the date; never align US and Chinese clock times.
        if stamp is None or not timedelta() <= now.date()-stamp.date() <= timedelta(days=7):
            continue
        try:
            current, previous, change, pct = (float(fields[i]) for i in (3,4,31,32))
            if not all(math.isfinite(v) for v in (current,previous,change,pct)) or min(current,previous)<=0:
                continue
            if abs((current/previous-1)*100-pct)>0.04:
                continue
            if abs((current-previous)-change)>max(0.05,current*0.00001):
                continue
        except (ValueError,OverflowError):
            continue
        rows.append(dict(code=code,name=name,current=current,change=change,change_pct=pct,region=region,
                         as_of=stamp.isoformat(),source='腾讯财经HTTPS指数报价',
                         time_basis='来源原始时钟，接口未标明时区；不作跨市场时点对齐'))
    return rows


def fetch_quotes():
    response = requests.get('https://qt.gtimg.cn/q='+','.join(INDICES),timeout=10,allow_redirects=False)
    response.raise_for_status()
    if response.status_code != 200:
        raise ValueError('index_source_redirect')
    response.encoding='gbk'
    return parse_quotes(response.text)


async def collect_overview(target_date=None):
    import asyncio
    from .market_data_service import IndexData, GlobalIndexData, MarketOverview
    target_date = target_date or china_today()
    overview=MarketOverview(date=target_date.isoformat())
    overview.source_status={name:dict(status='disabled_unverified',
        reason='日期、来源或接口未通过核验，暂停采集；不能当作零值或没有交易') for name in UNVERIFIED}
    if target_date != china_today():
        overview.source_status['指数']=dict(status='unsupported',reason='实时端点不支持历史回放，不拿当前行情代替历史行情')
        return overview
    try:
        rows=await asyncio.wait_for(asyncio.to_thread(fetch_quotes),timeout=12)
    except Exception as error:
        overview.source_status['指数']=dict(status='failed',error=type(error).__name__)
        print('[行情来源] 腾讯HTTPS指数请求失败：'+type(error).__name__,flush=True)
        return overview
    seen=set()
    for row in rows:
        if (row['region'],row['code']) in seen:
            continue
        seen.add((row['region'],row['code']))
        if row['region']=='A股':
            overview.indices.append(IndexData(**{key:value for key,value in row.items() if key!='region'}))
        else:
            overview.global_indices.append(GlobalIndexData(**{key:value for key,value in row.items() if key not in {'code','change'}}))
    overview.source_status['指数']=dict(status='ok' if rows else 'no_verified_data',read=len(seen))
    print(f'[行情来源] 腾讯HTTPS：A股指数{len(overview.indices)}，港美指数{len(overview.global_indices)}；'
          '均保留来源时间。12类未核验行情暂停采集，不轮询旧失败端点。',flush=True)
    return overview

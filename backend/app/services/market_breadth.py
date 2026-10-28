"""Breadth for a disclosed provider catalogue, using individually dated quotes.

Sina's hs_a catalogue supplies membership only. Its undated price fields never
enter breadth calculations. Tencent supplies price, previous close and date.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timedelta
import hashlib,json,math,re,time
from statistics import median
import requests

from .primary_sources import cached
from .research_hub import ResearchHub
from .technical_radar import ROOT
from .time_context import china_now
from .intraday_context import clock_usable

BASE='https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/'
COUNT=BASE+'Market_Center.getHQNodeStockCount'
CATALOG=BASE+'Market_Center.getHQNodeData'
QUOTES='https://qt.gtimg.cn/q='
SYMBOL=re.compile(r'(?:sh6\d{5}|sz[03]\d{5}|bj[489]\d{5})')


def bounded_map(items,callback,workers=2):
    """Stop scheduling on first failure; never fan out a failed endpoint."""
    iterator=iter(items);results=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending={}
        def fill():
            while len(pending)<workers:
                item=next(iterator,None)
                if item is None:break
                pending[pool.submit(callback,item)]=item
        fill()
        while pending:
            future=next(as_completed(pending));pending.pop(future)
            results.append(future.result())
            fill()
    return results


def parse_catalog_page(rows):
    if not isinstance(rows,list) or not rows:raise ValueError('breadth_catalog_shape_invalid')
    result=[]
    for row in rows:
        symbol=row.get('symbol','')
        if not SYMBOL.fullmatch(symbol) or row.get('code')!=symbol[2:]:raise ValueError('breadth_catalog_identity_invalid')
        result.append(dict(symbol=symbol,name=row.get('name','')))
    return result


def parse_dated_quotes(text,expected,observed):
    result={};rejected=Counter();seen=set()
    for symbol,raw in re.findall(r'v_(\w+)="([^"\r\n]*)"',text):
        if symbol not in expected:continue
        if symbol in seen:rejected['duplicate_symbol']+=1;result.pop(symbol,None);continue
        seen.add(symbol);fields=raw.split('~')
        try:
            if len(fields)<33 or fields[2]!=symbol[2:]:raise ValueError()
            stamp=datetime.strptime(fields[30],'%Y%m%d%H%M%S')
            price,previous,pct,volume=map(float,(fields[3],fields[4],fields[32],fields[6]))
            if (stamp>observed or (observed.date()-stamp.date()).days>4
                    or not all(math.isfinite(v) for v in (price,previous,pct,volume))
                    or price<=0 or previous<=0 or volume<0
                    or abs((price/previous-1)*100-pct)>.06):raise ValueError()
            result[symbol]=dict(symbol=symbol,as_of=stamp.isoformat(),price=price,previous=previous,pct=pct,volume=volume)
        except (ValueError,TypeError,OverflowError):rejected['identity_date_or_price_invalid']+=1
    return result,dict(rejected)


def summarize_breadth(catalog,quotes,observed,rejections=None):
    total=catalog['expected'];counts=Counter(row['as_of'][:10] for row in quotes.values())
    common=counts.most_common(1);day=common[0][0] if common else None
    dated=[row for row in quotes.values() if row['as_of'][:10]==day]
    anchor=max((datetime.fromisoformat(row['as_of']) for row in dated),default=None)
    active=[row for row in dated if row['volume']>0 and anchor-datetime.fromisoformat(row['as_of'])<=timedelta(minutes=10)]
    span=(max(datetime.fromisoformat(row['as_of']) for row in active)-min(datetime.fromisoformat(row['as_of']) for row in active)).total_seconds() if active else None
    coverage=len(active)/total if total else 0
    clock_valid=anchor is not None and clock_usable(anchor,observed,'A')
    usable=coverage>=.95 and span is not None and span<=180 and clock_valid
    result=dict(status='ok_sampled' if usable else 'unavailable',scope='新浪hs_a目录中的沪深京股票覆盖样本；非交易所独立核验的全市场全集',
        catalogue_observed_at=catalog['observed_at'],expected=total,dated_quotes=len(quotes),active_comparable=len(active),
        comparable_coverage=round(coverage,6),quote_dates=dict(counts),as_of=anchor.isoformat() if anchor else None,
        timestamp_span_seconds=span,excluded_no_trade_old_date_or_clock=len(quotes)-len(active),
        source_clock_usable=clock_valid,
        rejections=rejections or {},observed_at=observed.isoformat(),
        limitation='目录来自新浪，涨跌只用腾讯逐股带日期报价；不使用新浪无日期价格。采集是时间区间样本，不是同一瞬间快照。'
            '不把无有效交易、旧日期或过旧时钟计为平盘；只在可比样本≥95%且报价跨度≤180秒时提供分布。'
            '不计算MA20上方比例、涨跌停家数、资金流或未定价概率；港股宽度仍缺失。')
    if usable:
        result['distribution']=dict(advancing=sum(row['price']>row['previous'] for row in active),
            declining=sum(row['price']<row['previous'] for row in active),unchanged=sum(row['price']==row['previous'] for row in active),
            median_return_pct=round(median(row['pct'] for row in active),6),
            above_2pct=sum(row['pct']>=2 for row in active),below_minus2pct=sum(row['pct']<=-2 for row in active))
    else:result['reason']='breadth_insufficient_comparable_coverage_or_time_alignment' if clock_valid else 'breadth_source_clock_stale_or_incomplete'
    return result


class BreadthRadar:
    def __init__(self,root=None):self.hub=ResearchHub(root if root is not None else ROOT)

    def get(self,url,params,deadline):
        remaining=deadline-time.monotonic()
        if remaining<=0:raise requests.Timeout('breadth_budget_exhausted')
        r=requests.get(url,params=params,headers={'User-Agent':'Mozilla/5.0'},timeout=min(7,remaining),allow_redirects=False)
        r.raise_for_status()
        if r.status_code!=200 or len(r.content)>3*1024*1024:raise ValueError('breadth_response_invalid')
        return r

    def catalog(self,deadline):
        def request():
            count=int(self.get(COUNT,{'node':'hs_a'},deadline).json())
            if not 1000<=count<=10000:raise ValueError('breadth_catalog_count_invalid')
            def page(number):
                params=dict(page=number,num=80,sort='symbol',asc=1,node='hs_a',symbol='',_s_r_a='page')
                return cached(self.hub,'breadth:catalog:page:v1:'+str(number),21600,
                    lambda:parse_catalog_page(self.get(CATALOG,params,deadline).json()))
            # Verify first page before scheduling any other pages.
            rows=page(1)
            for result in bounded_map(range(2,math.ceil(count/80)+1),page):rows.extend(result)
            by_symbol={row['symbol']:row for row in rows}
            after=int(self.get(COUNT,{'node':'hs_a'},deadline).json())
            if len(rows)!=len(by_symbol) or len(by_symbol)!=count or after!=count:raise ValueError('breadth_catalog_incomplete_or_changed')
            return dict(expected=count,observed_at=china_now().isoformat(),members=list(by_symbol.values()))
        return cached(self.hub,'breadth:catalog:v1',21600,request)

    def quote_batch(self,symbols,deadline):
        def request():
            r=self.get(QUOTES+','.join(symbols),None,deadline);r.encoding='gbk'
            return dict(text=r.text,symbols=symbols,observed_at=china_now().isoformat())
        return cached(self.hub,'breadth:quotes:v1:'+hashlib.sha256(','.join(symbols).encode()).hexdigest(),90,request)

    def collect(self,budget=90):
        start=china_now();deadline=time.monotonic()+budget
        try:
            catalog=self.catalog(deadline);symbols=sorted(row['symbol'] for row in catalog['members'])
            chunks=[symbols[i:i+200] for i in range(0,len(symbols),200)]
            quotes={};rejections=Counter()
            for saved in bounded_map(chunks,lambda chunk:self.quote_batch(chunk,deadline)):
                parsed,bad=parse_dated_quotes(saved['text'],set(saved['symbols']),datetime.fromisoformat(saved['observed_at']))
                quotes.update(parsed);rejections.update(bad)
            result=summarize_breadth(catalog,quotes,china_now(),dict(rejections))
            result['collection_started_at']=start.isoformat()
            return result
        except Exception as error:
            reason=str(error)
            return dict(status='unavailable',observed_at=china_now().isoformat(),error=type(error).__name__,
                reason=reason if re.fullmatch(r'(?:cached_primary_failure:\w+:)?breadth_\w+|source_paused_no_automatic_retest',reason) else 'breadth_collection_failed',
                limitation='未完成目录/带日期报价验收，禁止用部分页或指数/ETF数量补写市场宽度。')

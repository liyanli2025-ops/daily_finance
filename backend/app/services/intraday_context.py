"""Dated intraday observations, not one-minute OHLC candles or trading signals."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timedelta
import math
import time
import requests

from .primary_sources import cached
from .research_hub import ResearchHub
from .technical_radar import ROOT
from .time_context import china_now
from .watchlist_sources import symbol_for

API='https://web.ifzq.gtimg.cn/appstock/app/minute/query'
BENCHMARKS=[dict(symbol='sh000001',market='A',kind='index',name='上证指数'),
    dict(symbol='hkHSI',market='HK',kind='index',name='恒生指数')]


def clock_usable(stamp,observed,market):
    """Conservative regular-session freshness; half-day calendars not inferred."""
    if stamp>observed:return False
    end=(15,0) if market=='A' else (16,0);morning=(11,30) if market=='A' else (12,0)
    source=(stamp.hour,stamp.minute);now=(observed.hour,observed.minute)
    if stamp.date()<observed.date():return source>=end
    if now<(9,30):return False
    if (9,30)<=now<=morning or (13,0)<=now<=end:
        return observed-stamp<=timedelta(minutes=10)
    if morning<now<(13,0):
        return stamp>=datetime.combine(stamp.date(),datetime.min.time()).replace(hour=morning[0],minute=morning[1])-timedelta(minutes=10)
    return source>=end


def parse_minutes(payload,spec,observed):
    symbol=spec['symbol']
    if payload.get('code')!=0 or symbol not in payload.get('data',{}):raise ValueError('minute_identity_missing')
    node=payload['data'][symbol];raw=node.get('data',{});qt=node.get('qt',{}).get(symbol)
    if not isinstance(qt,list) or len(qt)<35 or qt[2]!=symbol[2:]:raise ValueError('minute_quote_identity_missing')
    stamp=None
    for pattern in ('%Y%m%d%H%M%S','%Y/%m/%d %H:%M:%S'):
        try:stamp=datetime.strptime(qt[30],pattern);break
        except (ValueError,TypeError):pass
    if stamp is None or stamp>observed or (observed.date()-stamp.date()).days>4:raise ValueError('minute_quote_date_invalid')
    if not clock_usable(stamp,observed,spec['market']):raise ValueError('minute_source_clock_stale_or_incomplete')
    day=datetime.strptime(raw.get('date',''),'%Y%m%d').date()
    if day!=stamp.date():raise ValueError('minute_date_mismatch')
    previous=float(qt[4]);high=float(qt[33]);low=float(qt[34])
    if not all(math.isfinite(v) and v>0 for v in (previous,high,low)) or high<low:raise ValueError('minute_quote_values_invalid')
    close=(15,0) if spec['market']=='A' else (16,0)
    after_close=(observed.date()>day or (observed.hour,observed.minute)>=(close[0],30)) and (stamp.hour,stamp.minute)>=close
    cutoff=stamp.replace(second=0,microsecond=0)
    points=[];last=None;excluded=0
    for line in raw.get('data',[]):
        parts=line.split()
        if len(parts) not in (3,4):raise ValueError('minute_shape_invalid')
        tick=datetime.combine(day,datetime.strptime(parts[0],'%H%M').time())
        if last is not None and tick<=last:raise ValueError('minute_sequence_invalid')
        last=tick
        hhmm=(tick.hour,tick.minute)
        morning_end=(11,30) if spec['market']=='A' else (12,0)
        session=(9,30)<=hhmm<=morning_end or (13,0)<=hhmm<=close
        if not session or tick>cutoff or (tick==cutoff and not after_close):excluded+=1;continue
        price,volume=map(float,parts[1:3]);amount=float(parts[3]) if len(parts)==4 else None
        if not math.isfinite(price) or price<=0 or not math.isfinite(volume) or volume<0:raise ValueError('minute_values_invalid')
        points.append(dict(time=tick.isoformat(),price=price,cumulative_volume=volume,
            cumulative_amount=amount if amount is not None and math.isfinite(amount) and amount>=0 else None))
    if len(points)<2:raise ValueError('minute_observations_insufficient')
    values=[p['price'] for p in points];rounded=lambda x:round(x,6)
    metrics=dict(price=values[-1],change_from_previous_close_pct=rounded((values[-1]/previous-1)*100),
        return_from_first_observation_pct=rounded((values[-1]/values[0]-1)*100),
        distance_from_sampled_peak_pct=rounded((values[-1]/max(values)-1)*100),
        sampled_range_vs_previous_close_pct=rounded((max(values)-min(values))/previous*100))
    volume=dict(status='unavailable',reason='index_volume_basis_not_verified')
    if spec['kind']!='index':
        monotone=all(b['cumulative_volume']>=a['cumulative_volume'] for a,b in zip(points,points[1:]))
        volume=dict(status='ok_relative_only' if monotone else 'unavailable',
            reason='cumulative_counter_not_monotone' if not monotone else 'same_instrument_relative_observation_intervals_only',
            recent5_vs_previous5_interval_rate=None,implied_cumulative_average_price=None,consistent_volume_scale=None)
        tail=points[-11:]
        if monotone and len(tail)==11 and all(datetime.fromisoformat(b['time'])-datetime.fromisoformat(a['time'])==timedelta(minutes=1) for a,b in zip(tail,tail[1:])):
            changes=[b['cumulative_volume']-a['cumulative_volume'] for a,b in zip(tail,tail[1:])]
            prior=sum(changes[:5]);volume['recent5_vs_previous5_interval_rate']=rounded(sum(changes[5:])/prior) if prior>0 else None
        samples=[p for p in points if p['cumulative_volume']>0 and p['cumulative_amount'] is not None]
        amounts_ok=all(b['cumulative_amount']>=a['cumulative_amount'] for a,b in zip(samples,samples[1:]))
        scales=[scale for scale in (1,100) if len(samples)>=10 and amounts_ok and all(
            low*.995<=p['cumulative_amount']/(p['cumulative_volume']*scale)<=high*1.005 for p in samples)]
        if monotone and len(scales)==1 and samples[-1]['time']==points[-1]['time']:
            volume.update(consistent_volume_scale=scales[0],
                implied_cumulative_average_price=rounded(samples[-1]['cumulative_amount']/(samples[-1]['cumulative_volume']*scales[0])))
    return dict(**spec,status='ok',source='腾讯公开分时观测',source_url=API+'?code='+symbol,
        provider_name=qt[1],source_quote_time=stamp.isoformat(),observed_at=observed.isoformat(),
        as_of=points[-1]['time'],session='prior_date_snapshot' if day<observed.date() else 'after_close_snapshot' if after_close else 'intraday_partial',
        observations=len(points),excluded_unconfirmed_points=excluded,metrics=metrics,volume=volume,
        limitations=['分时价格观测不是一分钟OHLC，采样峰值不是逐笔最高价；不计算蜡烛形态',
            '同日相邻观测间隔量速比较不是历史同分钟量比；不跨午休或缺口比较',
            '累计均价只作单位一致性推算参考，不称官方VWAP；缺金额或单位不明不计算',
            'A/H按市场本地时钟核对，提供方未独立声明时区；不与美股拼时点',
            '无盘中信号胜率、资金净流入、主力意图或自动买卖判断'])


class IntradayRadar:
    def __init__(self,root=None):self.hub=ResearchHub(root if root is not None else ROOT)

    def fetch(self,spec,deadline):
        def request():
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('minute_budget_exhausted')
            r=requests.get(API,params={'code':spec['symbol']},headers={'User-Agent':'Mozilla/5.0'},
                timeout=min(7,remaining),allow_redirects=False)
            r.raise_for_status()
            if r.status_code!=200 or len(r.content)>2*1024*1024:raise ValueError('minute_response_invalid')
            observed=china_now();payload=r.json()
            parsed=parse_minutes(payload,spec,observed)
            return dict(observed_at=observed.isoformat(),payload=payload,parsed=parsed)
        saved=cached(self.hub,'minute:v1:'+spec['symbol'],120,request)
        return saved['parsed'] if 'parsed' in saved else parse_minutes(saved['payload'],spec,datetime.fromisoformat(saved['observed_at']))

    def collect(self,stocks,budget=20):
        specs=list(BENCHMARKS);seen={row['symbol'] for row in specs}
        for stock in stocks:
            symbol=symbol_for(stock)
            if symbol and symbol not in seen:
                seen.add(symbol);specs.append(dict(symbol=symbol,name=stock.name,market=str(getattr(stock.market,'value',stock.market)),kind='watchlist'))
        deadline=time.monotonic()+budget;rows=[]
        with ThreadPoolExecutor(max_workers=3) as pool:
            pending={pool.submit(self.fetch,spec,deadline):spec for spec in specs}
            for future in as_completed(pending):
                try:rows.append(future.result())
                except Exception as error:rows.append(dict(**pending[future],status='failed',error=type(error).__name__,
                    reason=str(error) if isinstance(error,ValueError) else 'minute_request_failed'))
        return dict(instruments=rows,coverage=dict(requested=len(specs),verified=sum(r['status']=='ok' for r in rows)),
            limitation='两市场指数及当前动态自选股的有限分时观测；不是全市场扫描或完整分钟K线历史。')

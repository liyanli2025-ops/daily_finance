"""Deterministic completed-daily-bar context. No model, buy score or synthetic data."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
import time

import requests

from .research_hub import ResearchHub, save_json
from .time_context import china_now
from .watchlist_sources import symbol_for

ROOT=Path(__file__).resolve().parents[2]/'data/radar'
API='https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
BENCHMARKS=[('sh000001','上证指数','A'),('sh000300','沪深300','A'),('sz399006','创业板指','A'),
            ('sh000688','科创50','A'),('hkHSI','恒生指数','HK'),('hkHSTECH','恒生科技指数','HK')]
# These are explicit exchange-traded proxies, NOT a complete industry universe.
PROXIES=[('sh512480','半导体ETF代理'),('sh512800','银行ETF代理'),('sh512170','医疗ETF代理'),
         ('sz159928','消费ETF代理'),('sh512660','军工ETF代理'),('sh515700','新能源车ETF代理'),
         ('sh512000','证券ETF代理'),('sh512400','有色金属ETF代理')]


def instruments(stocks):
    result=[dict(symbol=symbol,name=name,market=market,kind='index') for symbol,name,market in BENCHMARKS]
    result.extend(dict(symbol=symbol,name=name,market='A',kind='sector_proxy') for symbol,name in PROXIES)
    existing={item['symbol'] for item in result}
    for stock in stocks:
        symbol=symbol_for(stock)
        if symbol and symbol not in existing:
            result.append(dict(symbol=symbol,name=stock.name,market=str(getattr(stock.market,'value',stock.market)),kind='watchlist'))
            existing.add(symbol)
    return result


def completed(day,observed,market):
    if day>observed.date() or day.weekday()>=5:
        return False
    if day<observed.date():
        return True
    # Conservative regular-session completion, including data/closing-auction delay.
    close=(15,30) if market=='A' else (16,30)
    return (observed.hour,observed.minute)>=close


def parse_bars(payload,instrument,observed,now=None):
    now=now or china_now()
    symbol=instrument['symbol']
    if payload.get('code')!=0 or symbol not in payload.get('data',{}):
        raise ValueError('kline_identity_missing')
    node=payload['data'][symbol]
    key='day' if instrument['kind']=='index' else 'qfqday'
    rows=node.get(key)
    if not isinstance(rows,list) or not rows:
        raise ValueError('completed_daily_or_adjusted_series_missing')
    qt=node.get('qt',{}).get(symbol)
    if not isinstance(qt,list) or len(qt)<3:
        raise ValueError('kline_quote_identity_missing')
    expected=symbol[2:]
    actual=str(qt[2])
    if actual!=expected and not (actual.isdigit() and expected.isdigit() and actual.zfill(len(expected))==expected):
        raise ValueError('kline_quote_identity_mismatch')
    bars=[]
    previous=None
    for row in rows:
        if not isinstance(row,list) or len(row)<6:
            raise ValueError('kline_row_incomplete')
        day=datetime.strptime(str(row[0]),'%Y-%m-%d').date()
        if day>now.date() or day.weekday()>=5 or (previous is not None and day<=previous):
            raise ValueError('kline_dates_invalid')
        previous=day
        opening,close,high,low,volume=map(float,row[1:6])
        if (not all(math.isfinite(value) for value in (opening,close,high,low,volume))
                or min(opening,close,high,low)<=0 or volume<0
                or low>min(opening,close)+0.0001 or high+0.0001<max(opening,close) or low>high):
            raise ValueError('kline_ohlcv_invalid')
        if completed(day,observed,instrument['market']):
            bars.append(dict(date=day.isoformat(),open=opening,close=close,high=high,low=low,volume=volume))
    if not bars:
        raise ValueError('no_completed_daily_bars')
    age=(now.date()-datetime.fromisoformat(bars[-1]['date']).date()).days
    if age>4:
        raise ValueError('daily_history_too_old_for_current_analysis')
    return bars,str(qt[1]),'index_unadjusted' if key=='day' else 'provider_qfq'


def indicators(bars,allow_volume=True):
    close=[bar['close'] for bar in bars]
    count=len(close)
    mean=lambda values:sum(values)/len(values)
    change=lambda days:round((close[-1]/close[-days-1]-1)*100,4) if count>days else None
    result=dict(as_of=bars[-1]['date'],observations=count,close=close[-1],
        return_1d_pct=change(1),return_5d_pct=change(5),return_20d_pct=change(20),
        ma20=round(mean(close[-20:]),6) if count>=20 else None,
        ma60=round(mean(close[-60:]),6) if count>=60 else None,
        drawdown_20d_pct=round((close[-1]/max(close[-20:])-1)*100,4) if count>=20 else None,
        volume_vs_prior20=None,rsi14=None,atr14=None,close_above_prior20_high=None)
    if count>=21:
        prior_high=max(bar['high'] for bar in bars[-21:-1])
        result.update(prior20_high=prior_high,prior20_low=min(bar['low'] for bar in bars[-21:-1]),
                      close_above_prior20_high=close[-1]>prior_high)
        prior_volume=mean([bar['volume'] for bar in bars[-21:-1]])
        if allow_volume and prior_volume>0:
            result['volume_vs_prior20']=round(bars[-1]['volume']/prior_volume,4)
    if count>=15:
        changes=[close[i]-close[i-1] for i in range(1,count)]
        gains=[max(value,0) for value in changes]
        losses=[max(-value,0) for value in changes]
        gain,loss=mean(gains[:14]),mean(losses[:14])
        ranges=[max(bars[i]['high']-bars[i]['low'],abs(bars[i]['high']-close[i-1]),abs(bars[i]['low']-close[i-1])) for i in range(1,count)]
        atr=mean(ranges[:14])
        for i in range(14,len(changes)):
            gain=(gain*13+gains[i])/14
            loss=(loss*13+losses[i])/14
            atr=(atr*13+ranges[i])/14
        # Flat prices carry no momentum; do not manufacture an RSI buy signal.
        result['rsi14']=round(100-100/(1+gain/loss),4) if loss else (100.0 if gain else None)
        result['atr14']=round(atr,6)
    return result


class TechnicalRadar:
    def __init__(self,root=None):
        self.root=Path(root) if root is not None else ROOT
        self.hub=ResearchHub(self.root)

    def fetch(self,instrument,deadline):
        symbol=instrument['symbol']
        from .source_health import PAUSED_DAILY,DAILY_STRUCTURE_FAILURES,record_failure,ensure_active
        if instrument['kind']=='sector_proxy' and symbol in PAUSED_DAILY:
            raise ValueError('daily_adapter_paused_after_verified_missing_series_no_retest')
        key='daily:v1:'+symbol
        # A parser failure happened outside the HTTP cache in older releases.
        # Migrate an already saved exact-instrument failure, without probing it.
        try:
            previous=json.loads((self.root/'technical.json').read_text(encoding='utf-8'))
            failed=next((row for row in previous.get('instruments',[]) if row.get('symbol')==symbol
                and row.get('market')==instrument.get('market') and row.get('kind')==instrument.get('kind')
                and row.get('status')=='failed' and row.get('reason') in DAILY_STRUCTURE_FAILURES),None)
            if failed:record_failure(self.hub.root,key,ValueError(failed['reason']))
        except (OSError,ValueError,TypeError):pass
        ensure_active(self.hub.root,key)
        def request():
            remaining=deadline-time.monotonic()
            if remaining<=0:
                raise TimeoutError('technical_budget_exhausted')
            response=requests.get(API,params=dict(param=symbol+',day,,,180,qfq'),
                                  timeout=min(7,remaining),allow_redirects=False)
            response.raise_for_status()
            if response.status_code!=200 or len(response.content)>2*1024*1024:
                raise ValueError('kline_response_invalid')
            return dict(observed_at=china_now().isoformat(),payload=response.json())
        from .primary_sources import cached
        saved=cached(self.hub,key,900,request)
        observed=datetime.fromisoformat(saved['observed_at'])
        if observed>china_now():
            raise ValueError('kline_observation_in_future')
        try:bars,name,adjustment=parse_bars(saved['payload'],instrument,observed)
        except ValueError as error:
            record_failure(self.hub.root,key,error)
            raise
        metrics=indicators(bars,allow_volume=instrument['kind']!='index')
        return dict(**instrument,status='ok',provider_name=name,source='腾讯公开日线',source_url=API+'?param='+symbol+',day,,,180,qfq',
                    observed_at=observed.isoformat(),adjustment=adjustment,metrics=metrics,
                    bars=bars,volume_basis='仅股票/ETF同一原始序列的量能比值；不跨标的加总，指数成交字段不用于量能判断')

    def collect(self,stocks,budget=40):
        deadline=time.monotonic()+budget
        universe=instruments(stocks)
        rows=[]
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures={pool.submit(self.fetch,item,deadline):item for item in universe}
            for future in as_completed(futures):
                item=futures[future]
                try:
                    rows.append(future.result())
                except Exception as error:
                    rows.append(dict(**item,status='failed',error=type(error).__name__,
                        reason=str(error) if isinstance(error,(ValueError,TimeoutError)) else '日线请求失败'))
        rows.sort(key=lambda item:(item['kind'],item['symbol']))
        benchmarks={row['market']:row for row in rows if row['symbol'] in {'sh000300','hkHSI'} and row['status']=='ok'}
        for row in rows:
            benchmark=benchmarks.get(row['market'])
            if row['status']!='ok' or not benchmark or row['metrics']['as_of']!=benchmark['metrics']['as_of']:
                continue
            row['benchmark']=benchmark['symbol']
            for days in (5,20):
                a=row['metrics'].get('return_'+str(days)+'d_pct')
                b=benchmark['metrics'].get('return_'+str(days)+'d_pct')
                aligned=([bar['date'] for bar in row['bars'][-days-1:]]==
                         [bar['date'] for bar in benchmark['bars'][-days-1:]])
                row['metrics']['excess_'+str(days)+'d_percentage_points']=round(a-b,4) if aligned and a is not None and b is not None else None
        snapshot=dict(collected_at=china_now().isoformat(),watchlist=[str(getattr(stock.market,'value',stock.market))+':'+stock.code for stock in stocks],
            instruments=rows,coverage=dict(requested=len(rows),verified=sum(row['status']=='ok' for row in rows)),
            breadth=dict(status='unavailable',reason='本日线集合不推算市场宽度；沪深京覆盖样本另见分时快照，港股宽度仍缺失'),
            limitation='仅已完成日线；交易日历未独立核验，超过4个自然日的历史不作当前分析。ETF只是列明的行业代理，非完整行业排名。指标不代表买卖建议或上涨概率。')
        from .technical_analysis import daily_analysis
        for row in rows:
            if row['status']=='ok':
                row['analysis']=daily_analysis(row['bars'],row['metrics'],row['kind']!='index')
                from .weekly_context import weekly_context
                try:
                    observed=datetime.fromisoformat(row.get('observed_at',snapshot['collected_at']))
                    row['weekly']=weekly_context(row['bars'],observed,row['market'],row['kind']!='index',row['metrics'])
                except (ValueError,KeyError,TypeError):
                    row['weekly']=dict(status='unavailable',reason='weekly_input_validation_failed')
        snapshot['weekly_coverage']=dict(available=sum(row.get('weekly',{}).get('status')=='ok' for row in rows),
            calendar_status='not_independently_verified',source='existing_verified_daily_bars_no_extra_requests')
        from .relative_strength import build as relative_strength
        snapshot['relative_strength']=relative_strength(rows)
        save_json(self.root/'technical.json',snapshot)
        return snapshot


def prompt(stocks,root=None,now=None):
    from .microstructure import prompt as microstructure_prompt
    now=now or china_now()
    folder=Path(root) if root is not None else ROOT
    try:
        data=json.loads((folder/'technical.json').read_text(encoding='utf-8'))
        stamp=datetime.fromisoformat(data['collected_at'])
        if not timedelta()<=now-stamp<timedelta(hours=2):
            raise ValueError('expired_technical_snapshot')
    except (OSError,ValueError,KeyError,TypeError):
        return '## 日线技术雷达\n当前无有效技术快照，禁止补写量价、突破或趋势指标。\n'+microstructure_prompt(stocks,folder,now)
    wanted={str(getattr(stock.market,'value',stock.market))+':'+stock.code for stock in stocks}
    wanted_symbols={symbol_for(stock) for stock in stocks}
    lines=['## 已核验日线技术雷达（计算结果，不是新闻或预测）',data['limitation'],str(data['coverage']),str(data['breadth'])]
    if not data.get('weekly_coverage'):
        lines.append('该旧快照尚无周级参考，禁止由日线指标臆造周线结果。')
    lines.append('指标口径：return_5d/20d为截至as_of收盘的5/20期已完成日线收益，包含当期涨跌，不能称为反弹前；'
        'drawdown_20d_pct是距最近20个收盘价最高值的回撤，不是距盘中最高价；prior20_high/low才使用前20期盘中高低，排除当期。'
        'RSI14低于30可按传统口径描述为技术性超卖；不等于估值便宜或反弹已获确认，允许结合其他证据提出反弹或趋势延续假设。'
        'RSI14、ATR14不提供已校准胜率；不同源报价与复权日线不得不注明口径直接拼接。')
    lines.append('新增技术口径：MACD为SMA预热EMA12-EMA26及DIF的EMA9，柱值不乘2；ADX为Wilder14，只有强度没有方向。'
        '布林带为20期均值±2倍总体标准差，日收益波动为20期对数收益总体标准差，不年化。'
        'VWMA是日收盘按成交量加权，不是盘中VWAP；方向成交量余额不是实际资金流。'
        '摆动点左右各2根已完成K线严格比较，只能从confirmed_at使用，不能回填point_date。'
        '趋势候选需ADX≥25且价/MA20/MA60同向，ADX<20仅为震荡候选，均为未校准启发式。'
        '各家族共享输入，不叠加投票；已有日线及周级参考，交易日历未独立核验；完整分钟OHLC、多流派与港股宽度仍缺。'
        '本日线集合的breadth=unavailable只表示不从指数/ETF推算宽度，沪深京覆盖样本状态以本期分时快照为准。')
    missing=wanted-set(data.get('watchlist',[]))
    if missing:
        lines.append('当前新增自选股尚无日线快照：'+','.join(sorted(missing)))
    for row in data['instruments']:
        if row['kind']=='watchlist' and row['symbol'] not in wanted_symbols:
            continue
        if row['status']!='ok':
            lines.append(row['name']+'：数据缺口 '+str(row.get('reason',row.get('error'))))
            continue
        metric_keys=['as_of','close','return_5d_pct','return_20d_pct','ma20','ma60','drawdown_20d_pct',
                     'volume_vs_prior20','rsi14','atr14','close_above_prior20_high']
        lines.append(json.dumps(dict(symbol=row['symbol'],name=row['provider_name'],kind=row['kind'],
            adjustment=row['adjustment'],observed_at=row['observed_at'],
            metrics={key:row['metrics'].get(key) for key in metric_keys}),ensure_ascii=False,separators=(',',':')))
        if row.get('analysis'):
            analysis=row['analysis']
            # Definitions are shared above; avoid paying for the same paragraphs per instrument.
            families={name:{key:value for key,value in values.items() if key not in {'definition','method','limitation'}}
                for name,values in analysis['families'].items()}
            lines.append('技术家族（非策略信号）：'+json.dumps(dict(regime=analysis['regime'],families=families),
                ensure_ascii=False,separators=(',',':')))
        if row.get('weekly'):
            weekly=row['weekly']
            lines.append('周级参考（不是独立交易所周K）：'+json.dumps(
                {key:weekly[key] for key in ('status','as_of','observations','latest_ohlcv','metrics','warming_up','calendar_status','comparison','reason') if key in weekly},
                ensure_ascii=False,separators=(',',':')))
    lines.append('周级口径：仅聚合已完成日线、保留同一复权口径；进行中的周不使用，首周可能截断时丢弃。'
        '无整周数据时不补零；4/13观察周收益是对应可用周记录间收益，不强称日历月/季度。均线不足返回空，周量仅股票/ETF同序列比较。'
        '周级与日线共享数据且截止日不同，不算两票独立证据；停牌、节假日与漏数未独立区分。')
    lines.append('日线来源URL模板：'+API+'?param={symbol},day,,,180,qfq；原始缓存与全部指标保存在data/radar。'
                 '量能只用同一股票/ETF序列相对前20日比值，指数成交字段不参与量能判断。')
    lines.append('跨来源/跨市场不得拼时点或比较原始成交量；超额收益仅为同截止日同市场对基准的算术收益差。\n'
                 '技术状态可以与事件交叉核对，但不能证明事件因果、主力意图、尚未定价或信号胜率。')
    from .relative_strength import build as relative_strength,compact as compact_relative
    current_rows=[row for row in data['instruments'] if row['kind']!='watchlist' or row['symbol'] in wanted_symbols]
    lines.append('同市场相对表现与有限ETF代理样本（从已有日线计算，无额外请求）：'+
        json.dumps(compact_relative(relative_strength(current_rows)),ensure_ascii=False,separators=(',',':')))
    return '\n'.join(lines)+'\n'+microstructure_prompt(stocks,folder,now)

"""Aligned return comparisons from existing daily bars. No fetches or scores."""
from datetime import date
import math

BENCHMARKS={'A':'sh000300','HK':'hkHSI'}


def validate(row):
    if row.get('status')!='ok':return row.get('reason') or 'daily_source_unavailable'
    if row.get('market') not in BENCHMARKS or row.get('kind') not in {'index','sector_proxy','watchlist'}:
        return 'instrument_market_or_kind_unknown'
    expected='index_unadjusted' if row.get('kind')=='index' else 'provider_qfq'
    if row.get('adjustment')!=expected:return 'price_adjustment_unverified'
    bars=row.get('bars')
    if not isinstance(bars,list) or not bars:return 'daily_bars_missing'
    previous=None
    for bar in bars:
        try:
            day=date.fromisoformat(bar['date']);price=bar['close']
            if (type(price) not in (int,float) or not math.isfinite(price) or price<=0
                    or previous is not None and day<=previous):return 'daily_comparison_values_invalid'
            previous=day
        except (KeyError,TypeError,ValueError,OverflowError):return 'daily_comparison_values_invalid'
    if not isinstance(row.get('metrics'),dict) or row['metrics'].get('as_of')!=bars[-1]['date']:
        return 'metrics_and_bars_date_mismatch'
    return None


def window(row,benchmark,periods,offset=0):
    a=row['bars'];b=benchmark['bars']
    if min(len(a),len(b))<periods+offset+1:
        return dict(status='unavailable',reason='insufficient_observations')
    end_a=len(a)-offset;end_b=len(b)-offset
    a=a[end_a-periods-1:end_a];b=b[end_b-periods-1:end_b]
    if [point['date'] for point in a]!=[point['date'] for point in b]:
        return dict(status='unavailable',reason='observation_dates_not_aligned')
    instrument=(a[-1]['close']/a[0]['close']-1)*100
    reference=(b[-1]['close']/b[0]['close']-1)*100
    if not all(math.isfinite(value) for value in (instrument,reference)):
        return dict(status='unavailable',reason='return_not_finite')
    return dict(status='ok',start=a[0]['date'],end=a[-1]['date'],periods=periods,
        instrument_return_pct=round(instrument,6),benchmark_return_pct=round(reference,6),
        excess_return_percentage_points=round(instrument-reference,6))


def build(rows):
    """Caller filters obsolete watchlist members; failed sources remain visible."""
    if any(not isinstance(row,dict) or not isinstance(row.get('symbol'),str) or not row['symbol'] for row in rows):
        return dict(status='unavailable',reason='instrument_identity_missing',comparisons=[],proxy_samples=[])
    symbols=[row.get('symbol') for row in rows]
    if len(symbols)!=len(set(symbols)):
        return dict(status='unavailable',reason='duplicate_instrument_identity',comparisons=[],proxy_samples=[])
    by_symbol={row['symbol']:row for row in rows};comparisons=[]
    for row in rows:
        market=row.get('market');symbol=BENCHMARKS.get(market)
        if row.get('symbol')==symbol:continue
        result={key:row.get(key) for key in ('symbol','name','market','kind','source_url','observed_at','adjustment')}
        result['benchmark']=symbol
        reason=validate(row)
        benchmark=by_symbol.get(symbol)
        if not reason and (not benchmark or benchmark.get('kind')!='index' or benchmark.get('market')!=market or validate(benchmark)):
            reason='same_market_benchmark_unavailable'
        if reason:
            comparisons.append(dict(result,status='unavailable',reason=reason));continue
        # Ending on different dates makes even the previous-window comparison stale.
        if row['bars'][-1]['date']!=benchmark['bars'][-1]['date']:
            comparisons.append(dict(result,status='unavailable',reason='latest_completed_dates_differ'));continue
        recent=window(row,benchmark,5);prior=window(row,benchmark,5,5);medium=window(row,benchmark,20)
        comparable=recent['status']==prior['status']=='ok'
        comparisons.append(dict(result,status='ok' if recent['status']=='ok' else 'unavailable',
            reason=None if recent['status']=='ok' else recent['reason'],
            recent5=recent,prior5=prior,latest20=medium,
            excess_change_5_vs_prior5_percentage_points=round(recent['excess_return_percentage_points']-
                prior['excess_return_percentage_points'],6) if comparable else None))
    samples=[]
    for market in BENCHMARKS:
        candidates=[row for row in comparisons if row['market']==market and row['kind']=='sector_proxy']
        eligible=[row for row in candidates if row['status']=='ok' and row['prior5']['status']=='ok']
        # Compare identical members AND identical windows, rather than changing
        # the denominator when a proxy is absent or a history has gaps.
        groups={}
        for row in eligible:
            key=tuple(row[period][edge] for period in ('recent5','prior5') for edge in ('start','end'))
            groups.setdefault(key,[]).append(row)
        for key,group in groups.items():
            ranked=[]
            for row in sorted(group,key=lambda r:(-r['recent5']['excess_return_percentage_points'],r['symbol'])):
                rank=lambda period:1+sum(other[period]['excess_return_percentage_points']>
                    row[period]['excess_return_percentage_points'] for other in group)
                ranked.append(dict(symbol=row['symbol'],name=row['name'],
                    recent5_excess_pp=row['recent5']['excess_return_percentage_points'],
                    prior5_excess_pp=row['prior5']['excess_return_percentage_points'],
                    recent_rank=rank('recent5') if len(group)>=2 else None,
                    prior_rank=rank('prior5') if len(group)>=2 else None))
            samples.append(dict(market=market,benchmark=BENCHMARKS[market],
                status='ok_limited_proxy_sample' if len(group)>=2 else 'insufficient_proxy_sample_for_ranking',
                requested_proxies=len(candidates),comparable_members=len(group),
                recent_start=key[0],recent_end=key[1],prior_start=key[2],prior_end=key[3],members=ranked))
    return dict(status='ok' if any(row['status']=='ok' for row in comparisons) else 'unavailable',
        comparisons=comparisons,proxy_samples=samples,
        definition='同市场且逐个观察日一致的已完成日线收益减基准收益，单位百分点；非风险调整alpha。相对强可由跌得少形成，不等于绝对上涨；相对改善也可能因基准更弱。五期与前五期相邻不重叠，但共享边界收盘。',
        limitation='仅现有ETF代理样本，相对表现变化不证明全行业轮动、资金迁移、独立事件因果或未定价；不自动将个股匹配某ETF。五期指可用日线观察期，交易日历未独立核验。日线不是盘中信号。')


def compact(context):
    """Share window definitions instead of repeating dates and benchmark returns."""
    windows={};rows=[]
    for row in context['comparisons']:
        item={key:row.get(key) for key in ('symbol','kind','benchmark','status')}
        if row['status']!='ok':
            item['reason']=row['reason'];rows.append(item);continue
        for period in ('recent5','prior5','latest20'):
            value=row[period]
            if value['status']!='ok':item[period]=dict(reason=value['reason']);continue
            key=(row['benchmark'],value['start'],value['end'],value['periods'],value['benchmark_return_pct'])
            if key not in windows:windows[key]='w'+str(len(windows)+1)
            item[period]=[windows[key],value['excess_return_percentage_points']]
        item['excess_change_5_vs_prior5_pp']=row['excess_change_5_vs_prior5_percentage_points']
        rows.append(item)
    return dict(status=context['status'],
        windows=[dict(id=identifier,benchmark=key[0],start=key[1],end=key[2],periods=key[3],benchmark_return_pct=key[4])
            for key,identifier in windows.items()],comparisons=rows,proxy_samples=context['proxy_samples'],
        definition=context.get('definition'),limitation=context.get('limitation'),
        value_columns='recent5/prior5/latest20的数组为[窗口ID,相对基准收益差百分点]；差值变化不是个股/ETF本身涨幅变化。')

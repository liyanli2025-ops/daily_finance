"""Reproducible completed-daily-bar features, not a fitted trading strategy."""
import math


def ema(values,period):
    result=[None]*len(values)
    if len(values)<period:return result
    result[period-1]=sum(values[:period])/period
    alpha=2/(period+1)
    for i in range(period,len(values)):
        result[i]=alpha*values[i]+(1-alpha)*result[i-1]
    return result


def rounded(value):return round(value,6) if value is not None else None


def macd(close):
    fast,slow=ema(close,12),ema(close,26)
    dif=[fast[i]-slow[i] for i in range(25,len(close))]
    signal=ema(dif,9)
    if not dif or not signal or signal[-1] is None:
        return dict(status='warming_up',required_bars=34,cross_required_bars=35)
    previous=dif[-2]-signal[-2] if len(signal)>1 and signal[-2] is not None else None
    current=dif[-1]-signal[-1]
    return dict(status='ok',dif=rounded(dif[-1]),signal=rounded(signal[-1]),
        histogram=rounded(current),cross_up=previous<=0<current if previous is not None else None,
        cross_down=previous>=0>current if previous is not None else None,
        definition='EMA12-EMA26；信号线为DIF的EMA9；EMA以首个周期SMA预热，柱值为DIF-信号线，不乘2')


def dmi(bars,period=14):
    tr=[];positive=[];negative=[]
    for previous,current in zip(bars,bars[1:]):
        up=current['high']-previous['high'];down=previous['low']-current['low']
        positive.append(up if up>down and up>0 else 0)
        negative.append(down if down>up and down>0 else 0)
        tr.append(max(current['high']-current['low'],abs(current['high']-previous['close']),abs(current['low']-previous['close'])))
    if len(tr)<period:return dict(status='warming_up',required_bars=period*2)
    total=sum(tr[:period]);plus=sum(positive[:period]);minus=sum(negative[:period]);dx=[]
    def values():
        a=100*plus/total if total else 0;b=100*minus/total if total else 0
        return a,b,100*abs(a-b)/(a+b) if a+b else 0
    a,b,value=values();dx.append(value)
    for i in range(period,len(tr)):
        total=total-total/period+tr[i];plus=plus-plus/period+positive[i];minus=minus-minus/period+negative[i]
        a,b,value=values();dx.append(value)
    adx=None
    if len(dx)>=period:
        adx=sum(dx[:period])/period
        for value in dx[period:]:adx=(adx*(period-1)+value)/period
    return dict(status='ok' if adx is not None else 'warming_up',plus_di=rounded(a),minus_di=rounded(b),adx14=rounded(adx),
        definition='Wilder14平滑TR及方向移动，再对14个DX预热和平滑；ADX只描述趋势强度，不给方向或胜率')


def confirmed_pivots(bars,left=2,right=2):
    highs=[];lows=[]
    for i in range(left,len(bars)-right):
        neighbors=bars[i-left:i]+bars[i+1:i+right+1]
        point=dict(point_date=bars[i]['date'],confirmed_at=bars[i+right]['date'])
        if all(bars[i]['high']>row['high'] for row in neighbors):highs.append(dict(point,price=bars[i]['high']))
        if all(bars[i]['low']<row['low'] for row in neighbors):lows.append(dict(point,price=bars[i]['low']))
    structure='insufficient_confirmed_swings'
    if len(highs)>=2 and len(lows)>=2:
        if highs[-1]['price']>highs[-2]['price'] and lows[-1]['price']>lows[-2]['price']:structure='higher_highs_and_lows'
        elif highs[-1]['price']<highs[-2]['price'] and lows[-1]['price']<lows[-2]['price']:structure='lower_highs_and_lows'
        else:structure='mixed'
    return dict(method='左右各2根已完成日K严格比较；平顶/平底不判，非缠论笔/中枢识别',
        structure=structure,last_highs=highs[-2:],last_lows=lows[-2:],
        limitation='信号最早在confirmed_at可用，不能回填point_date；末端2根尚不能确认，参考摆动点不保证支撑/阻力有效')


def daily_analysis(bars,metrics,allow_volume=True):
    close=[row['close'] for row in bars];count=len(close)
    trend=dmi(bars);momentum=macd(close)
    volatility=dict(status='warming_up',bollinger20=None,atr14_pct=None,daily_log_return_std20_pct=None)
    if count>=20:
        mean=sum(close[-20:])/20;std=math.sqrt(sum((value-mean)**2 for value in close[-20:])/20)
        lower,upper=mean-2*std,mean+2*std
        volatility.update(status='ok',bollinger20=dict(middle=rounded(mean),upper=rounded(upper),lower=rounded(lower),
            bandwidth_pct=rounded((upper-lower)/mean*100),percent_b=rounded((close[-1]-lower)/(upper-lower)) if upper>lower else None,
            definition='20期收盘均值±2倍总体标准差；触及上下轨不等于反转'))
    if metrics.get('atr14') is not None:volatility['atr14_pct']=rounded(metrics['atr14']/close[-1]*100)
    if count>=21:
        returns=[math.log(close[i]/close[i-1]) for i in range(count-20,count)]
        mean=sum(returns)/20
        volatility['daily_log_return_std20_pct']=rounded(math.sqrt(sum((value-mean)**2 for value in returns)/20)*100)
    volume=dict(status='unavailable',reason='指数成交字段未核验为同口径成交量，不计算量价指标')
    if allow_volume and count>=20:
        total=sum(row['volume'] for row in bars[-20:])
        signed=sum((1 if close[i]>close[i-1] else -1 if close[i]<close[i-1] else 0)*bars[i]['volume'] for i in range(max(1,count-20),count))
        volume=dict(status='ok' if total else 'zero_volume',
            volume_vs_prior20=metrics.get('volume_vs_prior20'),
            vwma20_close=rounded(sum(row['close']*row['volume'] for row in bars[-20:])/total) if total else None,
            signed_volume_balance20=rounded(signed/total) if count>=21 and total else None,
            definition='VWMA是日收盘价按日成交量加权，不是盘中VWAP；量价方向加权不是实际买卖资金净流入')
    ma20,ma60=metrics.get('ma20'),metrics.get('ma60');adx=trend.get('adx14')
    regime='undetermined'
    if adx is not None and ma20 is not None and ma60 is not None:
        if adx>=25 and close[-1]>ma20>ma60:regime='uptrend_candidate'
        elif adx>=25 and close[-1]<ma20<ma60:regime='downtrend_candidate'
        elif adx<20:regime='range_candidate'
        else:regime='mixed_or_transition'
    return dict(as_of=bars[-1]['date'],timeframe='completed_daily',regime=regime,
        regime_definition='ADX≥25且价/MA20/MA60同向为趋势候选；ADX<20为震荡候选；仅启发式，不是校准策略',
        families=dict(trend_strength=trend,momentum=momentum,volatility=volatility,volume_price=volume,
            price_structure=confirmed_pivots(bars)),
        limitations=['均线、MACD、RSI等共享价格输入，不累加成独立确认票数',
            '当前仅日线；分钟线、周线、市场宽度、缠论/威科夫/波浪结构未据此实现',
            '先比较趋势延续与均值回归假设，再用事件及相对强弱核对；无自动买卖、目标价或胜率'])

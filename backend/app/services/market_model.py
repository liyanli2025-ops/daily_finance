"""Single-factor market-model diagnostics, not a calibrated trading strategy.

OLS r_stock = alpha + beta * r_market + residual, daily returns in percent.
120 estimation returns -> 20 chronological holdout returns -> 5 recent returns.
No refitting on the holdout/recent windows, no search for a winning window.
"""
import math
from .relative_strength import BENCHMARKS,validate

ESTIMATION=120
HOLDOUT=20
RECENT=5


def mean(values):return math.fsum(values)/len(values)


def fit(x,y):
    mx,my=mean(x),mean(y)
    sxx=math.fsum((value-mx)**2 for value in x)
    if sxx<=1e-12:raise ValueError('benchmark_variation_insufficient')
    beta=math.fsum((a-mx)*(b-my) for a,b in zip(x,y))/sxx
    alpha=my-beta*mx
    errors=[actual-alpha-beta*market for market,actual in zip(x,y)]
    sse=math.fsum(value*value for value in errors)
    sst=math.fsum((value-my)**2 for value in y)
    result=dict(alpha_daily_pp=alpha,beta=beta,estimation_r_squared=1-sse/sst if sst>1e-12 else None,
        residual_std_pp=math.sqrt(sse/(len(x)-2)))
    if not all(value is None or math.isfinite(value) for value in result.values()):
        raise ValueError('non_finite_fit')
    return result


def calculate(stock,benchmark):
    periods=ESTIMATION+HOLDOUT+RECENT
    for row in (stock,benchmark):
        reason=validate(row)
        if reason:raise ValueError(reason)
    if stock['market']!=benchmark['market'] or benchmark['symbol']!=BENCHMARKS.get(stock['market']):
        raise ValueError('same_market_benchmark_required')
    if benchmark['kind']!='index':raise ValueError('benchmark_must_be_index')
    if min(len(stock['bars']),len(benchmark['bars']))<periods+1:
        raise ValueError('need_146_aligned_closes_for_fixed_windows')
    a=stock['bars'][-periods-1:];b=benchmark['bars'][-periods-1:]
    if [row['date'] for row in a]!=[row['date'] for row in b]:
        raise ValueError('model_observation_dates_not_aligned')
    for row in a[1:]:
        value=row.get('volume')
        if type(value) not in (int,float) or not math.isfinite(value) or value<=0:
            raise ValueError('stock_trading_volume_missing_or_zero')
    returns=lambda bars:[(current['close']/previous['close']-1)*100 for previous,current in zip(bars,bars[1:])]
    y,x=returns(a),returns(b)
    if not all(math.isfinite(value) for value in x+y):raise ValueError('non_finite_model_return')
    model=fit(x[:ESTIMATION],y[:ESTIMATION])
    expected=[model['alpha_daily_pp']+model['beta']*value for value in x]
    boundary=ESTIMATION+HOLDOUT
    rmse=lambda values:math.sqrt(mean([value*value for value in values]))
    holdout_model=rmse([y[i]-expected[i] for i in range(ESTIMATION,boundary)])
    holdout_naive=rmse([y[i]-x[i] for i in range(ESTIMATION,boundary)])
    improves=holdout_model+1e-12<holdout_naive
    recent=[dict(date=a[i+1]['date'],stock_return_pct=y[i],market_return_pct=x[i],
        conditional_baseline_return_pct=expected[i],abnormal_return_pp=y[i]-expected[i])
        for i in range(boundary,periods)]
    for row in recent:
        if not all(math.isfinite(value) for key,value in row.items() if key!='date'):
            raise ValueError('non_finite_model_result')
    def window(start,end):
        return dict(first_return_date=a[start+1]['date'],last_return_date=a[end]['date'],observations=end-start)
    return dict(status='holdout_better_than_naive' if improves else 'diagnostic_only',
        estimation=dict(**window(0,ESTIMATION),**model),
        holdout=dict(**window(ESTIMATION,boundary),model_rmse_pp=holdout_model,
            market_adjusted_rmse_pp=holdout_naive,model_improves_naive=improves),
        recent=dict(**window(boundary,periods),daily=recent,
            sum_abnormal_returns_pp=math.fsum(row['abnormal_return_pp'] for row in recent)),
        event_association='not_established',future_return_prediction_supported=False)


def build(rows):
    if any(not isinstance(row,dict) or not isinstance(row.get('symbol'),str) or not row['symbol'] for row in rows):
        return dict(model='market_model_ols_v1',instruments=[],reason='instrument_identity_missing')
    symbols=[row.get('symbol') for row in rows]
    if len(symbols)!=len(set(symbols)):
        return dict(model='market_model_ols_v1',instruments=[],reason='duplicate_instrument_identity')
    by_symbol={row['symbol']:row for row in rows};results=[]
    for stock in rows:
        if stock.get('kind')!='watchlist':continue
        identifier=BENCHMARKS.get(stock.get('market'))
        item=dict(symbol=stock['symbol'],benchmark=identifier,
            source_url=stock.get('source_url'),observed_at=stock.get('observed_at'),adjustment=stock.get('adjustment'))
        benchmark=by_symbol.get(identifier)
        try:
            if not benchmark:raise ValueError('same_market_benchmark_unavailable')
            item.update(calculate(stock,benchmark))
        except (ValueError,KeyError,TypeError,OverflowError,ZeroDivisionError) as error:
            item.update(status='unavailable',reason=str(error) if isinstance(error,ValueError) else 'model_input_or_numeric_invalid')
        results.append(item)
    return dict(model='market_model_ols_v1',instruments=results,
        definition='个股日收益=截距+beta×同市场指数日收益+残差。日收益为百分数，残差为百分点。120期估计、随后20期留出检验、再后5期观察，固定窗口，不重叠使用收益。',
        limitation='市场模型不是完整CAPM或交易策略；未使用无风险利率及行业/风格因子。留出检验仅20期，不证明长期可靠、因果、胜率或未来收益。提供方前复权与价格指数不是独立核验的含分红总收益。与技术指标共享价格数据，不算独立佐证。')


def compact(context):
    items=[]
    for row in context['instruments']:
        item={key:row.get(key) for key in ('symbol','benchmark','status')}
        if row['status']=='unavailable':item['reason']=row['reason']
        else:
            # Dates and fit quality stay visible. Daily fitted paths remain in
            # the snapshot, rather than paying to repeat them in every prompt.
            item['holdout']={key:round(value,6) if type(value) is float else value for key,value in row['holdout'].items()}
            if row['status']=='holdout_better_than_naive':
                item['estimation']={key:round(value,6) if type(value) is float else value for key,value in row['estimation'].items()}
                item['recent']={key:round(value,6) if type(value) is float else value for key,value in row['recent'].items() if key!='daily'}
            else:item['restriction']='留出期未优于简单随大盘基线，不使用最近残差作独立强势依据'
        items.append(item)
    return dict(model=context['model'],instruments=items,definition=context.get('definition'),
        reason=context.get('reason'),
        limitation=context.get('limitation'),
        interpretation='仅已观察行情的条件基线及偏离，不是下一日预测；正残差不证明利好、独立行情或消息未定价。未绑定已核实事件，不能称某公告的异常收益或统计显著。')

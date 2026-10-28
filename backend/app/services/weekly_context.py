"""Week-level references from verified completed daily bars, no extra API."""
from collections import defaultdict
from datetime import date,timedelta


def weekly_context(bars,observed,market,allow_volume=True,daily_metrics=None):
    """Confirm time boundaries, while disclosing the unverified trade calendar.

    Source omissions versus exchange holidays cannot be distinguished here.
    Thus these are aggregations of observed daily sessions, not independently
    verified exchange weekly candles. Never include the unfinished current week.
    """
    if market not in {'A','HK'}:return dict(status='unavailable',reason='weekly_market_calendar_unknown')
    groups=defaultdict(list);previous=None
    for row in bars:
        day=date.fromisoformat(row['date'])
        if previous is not None and day<=previous:raise ValueError('weekly_daily_dates_not_ordered')
        previous=day
        close=(15,30) if market=='A' else (16,30)
        if day.weekday()>=5 or day>observed.date() or (day==observed.date() and (observed.hour,observed.minute)<close):
            raise ValueError('weekly_contains_uncompleted_daily_bar')
        groups[day-timedelta(days=day.weekday())].append(row)
    weeks=[];skipped=[];first=date.fromisoformat(bars[0]['date']) if bars else None
    current_monday=observed.date()-timedelta(days=observed.weekday())
    for monday,rows in sorted(groups.items()):
        friday=monday+timedelta(days=4)
        last=date.fromisoformat(rows[-1]['date'])
        if monday>=current_monday and not (last==friday and last<=observed.date()):
            skipped.append(dict(week_start=monday.isoformat(),reason='unfinished_or_unconfirmed_week'))
            continue
        if first>monday and monday==first-timedelta(days=first.weekday()):
            skipped.append(dict(week_start=monday.isoformat(),reason='left_edge_may_be_truncated'))
            continue
        weeks.append(dict(date=rows[-1]['date'],week_start=monday.isoformat(),sessions=len(rows),
            open=rows[0]['open'],close=rows[-1]['close'],high=max(row['high'] for row in rows),
            low=min(row['low'] for row in rows),volume=sum(row['volume'] for row in rows) if allow_volume else None))
    result=dict(status='ok' if weeks else 'unavailable',timeframe='observed_sessions_weekly',
        calendar_status='not_independently_verified',observations=len(weeks),skipped=skipped,
        limitation='同一已验证日线序列按周聚合；缺交易日不能区分停牌/节假日/漏数，不补零。仅已确认周边界；不是独立核验的交易所周K。')
    if not weeks:
        result['reason']='no_confirmed_week_boundaries'
        return result
    closes=[row['close'] for row in weeks];count=len(weeks)
    avg=lambda n:sum(closes[-n:])/n if count>=n else None
    pct=lambda n:(closes[-1]/closes[-n-1]-1)*100 if count>n else None
    rounded=lambda x:round(x,6) if x is not None else None
    ma10,ma20=avg(10),avg(20)
    prior10=sum(closes[-14:-4])/10 if count>=14 else None
    prior_volume=sum(row['volume'] for row in weeks[-11:-1])/10 if allow_volume and count>=11 else None
    result.update(as_of=weeks[-1]['date'],latest_ohlcv={key:weeks[-1][key] for key in ('open','high','low','close','volume')},
        metrics=dict(close=closes[-1],ma10=rounded(ma10),ma20=rounded(ma20),
        return_1_observed_week_pct=rounded(pct(1)),return_4_observed_weeks_pct=rounded(pct(4)),
        return_13_observed_weeks_pct=rounded(pct(13)),
        ma10_slope_4_observed_weeks_pct=rounded((ma10/prior10-1)*100) if prior10 else None,
        volume_vs_prior10_observed_weeks=rounded(weeks[-1]['volume']/prior_volume) if prior_volume else None,
        last_week_sessions=weeks[-1]['sessions']),
        absent_week_starts=[(left+timedelta(days=7*i)).isoformat()
            for a,b in zip(weeks,weeks[1:])
            for left,right in [(date.fromisoformat(a['week_start']),date.fromisoformat(b['week_start']))]
            for i in range(1,(right-left).days//7)],
        warming_up=[name for name,value in [('ma10',ma10),('ma20',ma20)] if value is None])
    daily_metrics=daily_metrics or {}
    position=lambda close,ma:'unavailable' if ma is None else 'above' if close>ma else 'below' if close<ma else 'equal'
    daily=position(daily_metrics.get('close',closes[-1]),daily_metrics.get('ma20'))
    weekly=position(closes[-1],ma20)
    result['comparison']=dict(daily_as_of=daily_metrics.get('as_of'),weekly_as_of=weeks[-1]['date'],
        daily_price_vs_daily_ma20=daily,weekly_price_vs_weekly_ma20=weekly,
        relationship='unavailable' if 'unavailable' in {daily,weekly} else 'same_side' if daily==weekly else 'different_sides',
        interpretation='两个截止时点分别列示；相同方向不是独立双重确认，不同方向也不自动意味着反转')
    return result

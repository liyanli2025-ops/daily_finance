"""Shared intraday/breadth context; public deterministic data, no models."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta
import json
from pathlib import Path

from .intraday_context import IntradayRadar
from .market_breadth import BreadthRadar
from .technical_radar import ROOT
from .research_hub import save_json
from .time_context import china_now
from .watchlist_sources import symbol_for


class MicrostructureRadar:
    def __init__(self,root=None):self.root=Path(root) if root is not None else ROOT

    def collect(self,stocks,budget=40):
        with ThreadPoolExecutor(max_workers=2) as pool:
            minute=pool.submit(IntradayRadar(self.root).collect,stocks,min(20,budget))
            breadth=pool.submit(BreadthRadar(self.root).collect,budget)
            intraday=minute.result();distribution=breadth.result()
        alignment='unavailable'
        benchmark=next((row for row in intraday['instruments'] if row['symbol']=='sh000001' and row['status']=='ok'),None)
        if benchmark and distribution.get('status')=='ok_sampled':
            a=datetime.fromisoformat(benchmark['as_of']);b=datetime.fromisoformat(distribution['as_of'])
            alignment='nearby_same_date' if a.date()==b.date() and abs((a-b).total_seconds())<=300 else 'not_aligned'
        result=dict(collected_at=china_now().isoformat(),watchlist=[symbol_for(stock) for stock in stocks if symbol_for(stock)],
            unsupported=[str(getattr(stock.market,'value',stock.market))+':'+stock.code for stock in stocks if not symbol_for(stock)],
            intraday=intraday,breadth=distribution,a_index_breadth_time_alignment=alignment,
            limitation='同日期附近时点才可交叉比较指数与股票分布，不认作严格同步或因果；港股市场宽度尚未接通。')
        save_json(self.root/'microstructure.json',result)
        return result


def prompt(stocks,root=None,now=None):
    now=now or china_now();root=Path(root) if root is not None else ROOT
    try:
        data=json.loads((root/'microstructure.json').read_text(encoding='utf-8'))
        if not timedelta()<=now-datetime.fromisoformat(data['collected_at'])<timedelta(minutes=10):raise ValueError('stale')
    except (OSError,ValueError,KeyError,TypeError):
        return '## 分时与覆盖样本宽度\n没有有效近期快照，不得猜测盘中放量、涨跌家数或多数股票走势。'
    wanted={symbol_for(stock) for stock in stocks if symbol_for(stock)};lines=['## 分时观测与覆盖样本宽度',data['limitation'],
        '分时是价格点和累计计数，非一分钟K线；只用as_of之前确认的时点。区间量速不是历史量比，累计均价只作单位一致性参考。',
        '未取得历史同分钟对照，不许称较昨日同刻放量；不由价格点拼出蜡烛形态、主力流入或信号胜率。',
        '指数成交量单位未核实，不算指数VWAP/量能。A/H报价按各自截止时点，不跨市场拼接。']
    lines.append('分时报价未复权；日线可能前复权，跨除权日或跨源不可直接拼接为突破和收益。')
    lines.append('报价时间是提供方快照时钟，不等于逐笔成交时刻；午休期间刷新时钟不证明仍在交易。')
    if data.get('unsupported'):lines.append('当前不支持的自选股市场：'+','.join(data['unsupported']))
    for row in data.get('intraday',{}).get('instruments',[]):
        if row.get('kind')=='watchlist' and row.get('symbol') not in wanted:continue
        lines.append(json.dumps({key:row[key] for key in ('symbol','name','kind','status','as_of','source_quote_time','session','metrics','volume','source_url','reason') if key in row},ensure_ascii=False,separators=(',',':')))
    missing=wanted-set(data.get('watchlist',[]))
    if missing:lines.append('新增自选股分时缺口：'+','.join(sorted(missing)))
    breadth=data.get('breadth',{})
    lines.append('股票分布：'+json.dumps(breadth,ensure_ascii=False,separators=(',',':')))
    lines.append('A股指数与宽度时点关系：'+data.get('a_index_breadth_time_alignment','unavailable')+
        '；不是nearby_same_date时不可据此断言指数与大多数股票背离。目录全集未独立核对，不称全A股官方统计；港股宽度、MA20上方占比、涨跌停仍未知。')
    return '\n'.join(lines)

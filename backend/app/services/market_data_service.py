"""
市场数据采集服务
使用 AKShare 获取 A股市场全面数据，为 AI 报告生成提供真实数据支撑
"""
import asyncio
import time
from datetime import datetime, date
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
import traceback


# ── 全局令牌桶限流器：控制对东方财富 API 的请求频率 ──
class _AKShareRateLimiter:
    """
    令牌桶限流器（进程全局单例）
    
    所有通过 _call_akshare_with_retry 发起的 AKShare 调用
    都要先从这个桶里取令牌，取不到就等。
    确保全局请求频率不超过 1 次/1.5秒，避免被东方财富反爬封IP。
    """
    def __init__(self, rate: float = 0.67, burst: int = 2):
        """
        Args:
            rate: 每秒补充的令牌数（0.67 = 每 1.5 秒 1 个请求）
            burst: 令牌桶最大容量（允许短暂突发）
        """
        self._rate = rate
        self._burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()
    
    async def acquire(self):
        """获取一个令牌，如果桶空则等待"""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            self._last_refill = now
            
            if self._tokens < 1:
                wait_time = (1 - self._tokens) / self._rate
                await asyncio.sleep(wait_time)
                self._tokens = 0
            else:
                self._tokens -= 1


# 全局限流器实例（所有 MarketDataService / NewsCollector 共用）
_akshare_rate_limiter = _AKShareRateLimiter(rate=0.67, burst=2)


# ── 当日数据缓存：同一交易日同一接口只调一次 ──
class _MarketDataCache:
    """
    市场数据缓存（内存 + 可选磁盘持久化）
    
    同一交易日内，相同的 AKShare 接口只调用一次，
    后续复用缓存结果，大幅减少对东方财富的请求次数。
    """
    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._cache_date: Optional[str] = None
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存数据，如果日期不匹配则清空"""
        today = date.today().isoformat()
        if self._cache_date != today:
            self._cache.clear()
            self._cache_date = today
            return None
        return self._cache.get(key)
    
    def set(self, key: str, value: Any):
        """设置缓存数据"""
        today = date.today().isoformat()
        if self._cache_date != today:
            self._cache.clear()
            self._cache_date = today
        self._cache[key] = value
    
    def has(self, key: str) -> bool:
        """检查是否有缓存"""
        today = date.today().isoformat()
        if self._cache_date != today:
            return False
        return key in self._cache


# 全局缓存实例
_market_data_cache = _MarketDataCache()

# ── 给 requests 全局加超时，防止 AKShare 底层 HTTP 请求永久挂起 ──
try:
    import requests
    from requests.adapters import HTTPAdapter
    
    class _TimeoutHTTPAdapter(HTTPAdapter):
        """强制所有 requests 请求带超时"""
        def __init__(self, timeout=30, *args, **kwargs):
            self.timeout = timeout
            super().__init__(*args, **kwargs)
        
        def send(self, request, **kwargs):
            kwargs.setdefault('timeout', self.timeout)
            return super().send(request, **kwargs)
    
    # Monkey-patch requests.Session 的默认适配器
    _timeout_adapter = _TimeoutHTTPAdapter(timeout=30)
    _session = requests.Session()
    _session.mount('http://', _timeout_adapter)
    _session.mount('https://', _timeout_adapter)
    # 替换 requests 模块的默认 session（AKShare 内部用 requests.get 时生效）
    requests.adapters.DEFAULT_RETRIES = 2
    
    # 同时 patch requests.get/post 等快捷方法的默认超时
    _original_request = requests.Session.request
    def _patched_request(self, method, url, **kwargs):
        kwargs.setdefault('timeout', 30)
        return _original_request(self, method, url, **kwargs)
    requests.Session.request = _patched_request
    
    print("[MarketData] ✅ 已为 requests 全局设置 30 秒超时", flush=True)
except Exception as e:
    print(f"[MarketData] ⚠️ 设置 requests 超时失败: {e}", flush=True)


@dataclass
class IndexData:
    """指数数据"""
    code: str
    name: str
    current: float
    change: float
    change_pct: float
    volume: float = 0
    amount: float = 0
    high: float = 0
    low: float = 0
    open: float = 0


@dataclass
class SectorData:
    """板块数据"""
    name: str
    change_pct: float
    leader_stock: str = ""
    leader_change: float = 0
    fund_flow: float = 0  # 资金流入（亿元）


@dataclass
class FundFlowData:
    """资金流向数据"""
    main_net_inflow: float  # 主力净流入（亿元）
    retail_net_inflow: float  # 散户净流入（亿元）
    super_large_inflow: float = 0  # 超大单
    large_inflow: float = 0  # 大单
    medium_inflow: float = 0  # 中单
    small_inflow: float = 0  # 小单


@dataclass
class LimitData:
    """涨跌停数据"""
    up_limit_count: int  # 涨停数量
    down_limit_count: int  # 跌停数量
    up_limit_stocks: List[Dict] = field(default_factory=list)  # 涨停股票
    down_limit_stocks: List[Dict] = field(default_factory=list)  # 跌停股票


@dataclass
class HotStockData:
    """热门股票数据"""
    code: str
    name: str
    price: float
    change_pct: float
    turnover_rate: float = 0
    pe_ratio: float = 0
    reason: str = ""  # 上榜原因


@dataclass
class ConceptSectorData:
    """概念板块数据"""
    name: str
    change_pct: float
    leader_stock: str = ""
    leader_change: float = 0
    stock_count: int = 0  # 板块内股票数


@dataclass
class ConsecutiveLimitStock:
    """连板强势股"""
    code: str
    name: str
    price: float
    change_pct: float
    limit_days: int = 0  # 连板天数
    limit_reason: str = ""  # 涨停原因/概念
    sector: str = ""  # 所属行业


@dataclass
class TechSignalStock:
    """技术信号机会股"""
    code: str
    name: str
    price: float
    change_pct: float
    volume_ratio: float = 0       # 量比
    turnover_rate: float = 0      # 换手率
    signals: List[str] = field(default_factory=list)  # 触发的信号列表
    signal_score: float = 0       # 综合信号得分 (0-100)
    consecutive_up_days: int = 0  # 连续上涨天数
    sector: str = ""              # 所属行业
    source: str = ""              # 数据来源


@dataclass
class LHBSeatData:
    """龙虎榜席位明细"""
    stock_code: str          # 股票代码
    stock_name: str          # 股票名称
    seat_name: str           # 席位名称
    buy_amount: float = 0    # 买入金额（万元）
    sell_amount: float = 0   # 卖出金额（万元）
    net_amount: float = 0    # 净买入金额（万元）
    is_institution: bool = False  # 是否机构席位
    seat_type: str = ""      # 席位类型：机构/知名游资/普通营业部
    reason: str = ""         # 上榜原因


@dataclass
class BlockTradeData:
    """大宗交易数据"""
    code: str                # 股票代码
    name: str                # 股票名称
    price: float = 0         # 成交价
    close_price: float = 0   # 收盘价
    discount_rate: float = 0 # 折价率(%)，负值=折价，正值=溢价
    volume: float = 0        # 成交量（万股）
    amount: float = 0        # 成交金额（万元）
    buyer_seat: str = ""     # 买方营业部
    seller_seat: str = ""    # 卖方营业部


@dataclass
class MarginTradingData:
    """融资融券数据"""
    total_margin_balance: float = 0      # 融资余额（亿元）
    margin_buy_amount: float = 0         # 融资买入额（亿元）
    total_short_balance: float = 0       # 融券余额（亿元）
    margin_balance_change: float = 0     # 融资余额较前一日变化（亿元）
    short_balance_change: float = 0      # 融券余额较前一日变化（亿元）
    top_margin_stocks: List[Dict] = field(default_factory=list)  # 融资余额Top股票


@dataclass
class CommodityData:
    """大宗商品数据"""
    name: str           # 如"WTI原油"、"现货黄金"
    price: float        # 当前价格
    change_pct: float   # 涨跌幅(%)
    unit: str = ""      # 单位（美元/桶、美元/盎司等）


@dataclass
class GlobalIndexData:
    """全球指数数据（外盘）"""
    name: str           # 如"道琼斯"、"纳斯达克"、"恒生指数"
    current: float      # 当前点位
    change_pct: float   # 涨跌幅(%)
    region: str = ""    # 区域（美股/港股/欧洲/亚太）


@dataclass
class MarketOverview:
    """市场概览数据"""
    date: str
    indices: List[IndexData] = field(default_factory=list)
    top_sectors: List[SectorData] = field(default_factory=list)  # 涨幅前5
    bottom_sectors: List[SectorData] = field(default_factory=list)  # 跌幅前5
    fund_flow: Optional[FundFlowData] = None
    limit_data: Optional[LimitData] = None
    hot_stocks: List[HotStockData] = field(default_factory=list)
    market_sentiment: str = ""  # 市场情绪描述
    total_volume: float = 0  # 两市总成交额（亿元）
    up_count: int = 0  # 上涨家数
    down_count: int = 0  # 下跌家数
    flat_count: int = 0  # 平盘家数
    # 🆕 新增模块
    concept_sectors: List[ConceptSectorData] = field(default_factory=list)  # 概念板块排行
    consecutive_limit_stocks: List[ConsecutiveLimitStock] = field(default_factory=list)  # 连板强势股
    tech_signal_stocks: List[TechSignalStock] = field(default_factory=list)  # 技术信号机会股
    # 🆕 大宗商品与外盘数据
    commodities: List[CommodityData] = field(default_factory=list)          # 大宗商品（原油/黄金/白银等）
    global_indices: List[GlobalIndexData] = field(default_factory=list)     # 外盘指数（美股/港股/欧洲等）
    # 🆕 聪明钱数据（龙虎榜席位 + 大宗交易 + 融资融券）
    lhb_seats: List[LHBSeatData] = field(default_factory=list)             # 龙虎榜席位明细
    block_trades: List[BlockTradeData] = field(default_factory=list)       # 大宗交易
    margin_data: Optional[MarginTradingData] = None                        # 融资融券
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return asdict(self)
    
    def to_prompt_text(self) -> str:
        """转换为 AI Prompt 使用的文本格式"""
        lines = []
        lines.append(f"## 📊 市场数据（{self.date}）\n")
        
        # 数据缺失警告（让 AI 知道哪些数据不可用，避免编造）
        missing = []
        if not self.indices:
            missing.append("大盘指数")
        if not self.top_sectors:
            missing.append("行业板块排行")
        if not self.concept_sectors:
            missing.append("概念板块")
        if not self.global_indices:
            missing.append("外盘指数")
        if not self.commodities:
            missing.append("大宗商品")
        if not self.fund_flow:
            missing.append("资金流向")
        if not self.margin_data:
            missing.append("融资融券")
        
        if missing:
            lines.append(f"⚠️ **以下数据因接口异常暂不可用：{', '.join(missing)}**")
            lines.append(f"**对于缺失的数据项，请直接说\"数据暂缺\"，严禁编造任何数字或趋势。**\n")
        
        # 1. 大盘指数
        if self.indices:
            lines.append("### 主要指数")
            for idx in self.indices:
                trend = "📈" if idx.change_pct > 0 else ("📉" if idx.change_pct < 0 else "➡️")
                lines.append(f"- {idx.name}：{idx.current:.2f} {trend} {idx.change_pct:+.2f}%（成交额 {idx.amount/100000000:.0f}亿）")
            lines.append("")
        
        # 1.5 外盘指数（全球市场）
        if self.global_indices:
            lines.append("### 🌍 外盘指数（全球市场）")
            # 按区域分组
            regions = {}
            for gi in self.global_indices:
                region = gi.region or "其他"
                if region not in regions:
                    regions[region] = []
                regions[region].append(gi)
            for region, indices in regions.items():
                lines.append(f"**{region}：**")
                for gi in indices:
                    trend = "📈" if gi.change_pct > 0 else ("📉" if gi.change_pct < 0 else "➡️")
                    lines.append(f"- {gi.name}：{gi.current:.2f} {trend} {gi.change_pct:+.2f}%")
            lines.append("")
        
        # 1.8 大宗商品
        if self.commodities:
            lines.append("### 🛢️ 大宗商品行情")
            for comm in self.commodities:
                trend = "📈" if comm.change_pct > 0 else ("📉" if comm.change_pct < 0 else "➡️")
                unit_str = f"（{comm.unit}）" if comm.unit else ""
                lines.append(f"- {comm.name}：{comm.price:.2f}{unit_str} {trend} {comm.change_pct:+.2f}%")
            lines.append("")
        
        # 2. 涨跌家数
        if self.up_count or self.down_count:
            total = self.up_count + self.down_count + self.flat_count
            up_ratio = self.up_count / total * 100 if total > 0 else 0
            lines.append(f"### 涨跌统计")
            lines.append(f"- 上涨 {self.up_count} 家 / 下跌 {self.down_count} 家 / 平盘 {self.flat_count} 家")
            lines.append(f"- 上涨比例：{up_ratio:.1f}%")
            if self.total_volume > 0:
                lines.append(f"- 两市总成交额：{self.total_volume:.0f} 亿元")
            lines.append("")
        
        # 3. 板块涨跌
        if self.top_sectors:
            lines.append("### 领涨板块（前5）")
            for i, sector in enumerate(self.top_sectors[:5], 1):
                lines.append(f"{i}. {sector.name}：+{sector.change_pct:.2f}%（龙头：{sector.leader_stock}）")
            lines.append("")
        
        if self.bottom_sectors:
            lines.append("### 领跌板块（前5）")
            for i, sector in enumerate(self.bottom_sectors[:5], 1):
                lines.append(f"{i}. {sector.name}：{sector.change_pct:.2f}%")
            lines.append("")
        
        # 4. 资金流向
        if self.fund_flow:
            lines.append("### 资金流向")
            flow = self.fund_flow
            main_trend = "净流入" if flow.main_net_inflow > 0 else "净流出"
            lines.append(f"- 主力资金：{main_trend} {abs(flow.main_net_inflow):.2f} 亿元")
            if flow.super_large_inflow != 0:
                lines.append(f"- 超大单：{flow.super_large_inflow:+.2f} 亿元")
            if flow.large_inflow != 0:
                lines.append(f"- 大单：{flow.large_inflow:+.2f} 亿元")
            lines.append("")
        
        # 5. 涨跌停
        if self.limit_data:
            lines.append("### 涨跌停统计")
            lines.append(f"- 涨停：{self.limit_data.up_limit_count} 家")
            lines.append(f"- 跌停：{self.limit_data.down_limit_count} 家")
            
            if self.limit_data.up_limit_stocks:
                lines.append("- 部分涨停股：" + "、".join([
                    f"{s['name']}({s['code']})" 
                    for s in self.limit_data.up_limit_stocks[:5]
                ]))
            lines.append("")
        
        # 6. 热门股票
        if self.hot_stocks:
            lines.append("### 热门股票（龙虎榜/异动）")
            for stock in self.hot_stocks[:5]:
                lines.append(f"- {stock.name}({stock.code})：{stock.change_pct:+.2f}%，{stock.reason}")
            lines.append("")
        
        # 7. 市场情绪
        if self.market_sentiment:
            lines.append(f"### 市场情绪\n{self.market_sentiment}\n")
        
        # 8. 概念板块排行
        if self.concept_sectors:
            lines.append("### 🔥 概念板块排行（前10）")
            for i, sector in enumerate(self.concept_sectors[:10], 1):
                lines.append(
                    f"{i}. {sector.name}：{sector.change_pct:+.2f}%"
                    f"（龙头：{sector.leader_stock}，"
                    f"板块{sector.stock_count}只）"
                )
            lines.append("")
        
        # 9. 连板强势股
        if self.consecutive_limit_stocks:
            lines.append("### 🚀 连板强势股")
            for i, stock in enumerate(self.consecutive_limit_stocks[:10], 1):
                lines.append(
                    f"{i}. **{stock.name}**（{stock.code}）"
                    f"｜{stock.price:.2f}元 {stock.change_pct:+.2f}%"
                    f"｜{stock.limit_days}连板"
                    f"｜概念：{stock.limit_reason}"
                )
            lines.append("")
        
        # 10. 技术信号机会股
        if self.tech_signal_stocks:
            lines.append("### 🎯 技术信号机会股（多因子筛选）")
            lines.append("以下股票触发了多个看涨技术信号，值得关注：\n")
            for i, stock in enumerate(self.tech_signal_stocks[:10], 1):
                signals_str = "、".join(stock.signals)
                lines.append(
                    f"{i}. **{stock.name}**（{stock.code}）"
                    f"｜{stock.price:.2f}元 {stock.change_pct:+.2f}%"
                    f"｜量比{stock.volume_ratio:.1f} 换手率{stock.turnover_rate:.1f}%"
                    f"\n   信号：{signals_str}"
                    f"（综合得分：{stock.signal_score:.0f}）"
                )
            lines.append("")
        
        # 11. 龙虎榜席位明细（聪明钱追踪）
        if self.lhb_seats:
            lines.append("### 🏛️ 龙虎榜席位明细（聪明钱追踪）")
            lines.append("以下是龙虎榜上机构和知名游资的操作明细：\n")
            
            # 按股票分组
            stocks_seats = {}
            for seat in self.lhb_seats:
                key = f"{seat.stock_code}_{seat.stock_name}"
                if key not in stocks_seats:
                    stocks_seats[key] = {"name": seat.stock_name, "code": seat.stock_code, "seats": [], "reason": seat.reason}
                stocks_seats[key]["seats"].append(seat)
            
            for i, (key, info) in enumerate(list(stocks_seats.items())[:8], 1):
                lines.append(f"{i}. **{info['name']}**（{info['code']}）— {info['reason']}")
                # 分开显示机构和游资
                inst_seats = [s for s in info["seats"] if s.is_institution]
                famous_seats = [s for s in info["seats"] if s.seat_type == "知名游资"]
                normal_seats = [s for s in info["seats"] if not s.is_institution and s.seat_type != "知名游资"]
                
                if inst_seats:
                    total_buy = sum(s.buy_amount for s in inst_seats)
                    total_sell = sum(s.sell_amount for s in inst_seats)
                    lines.append(f"   🏦 机构席位：买入{total_buy:.0f}万 / 卖出{total_sell:.0f}万 / 净买入{total_buy-total_sell:.0f}万")
                if famous_seats:
                    for s in famous_seats[:3]:
                        lines.append(f"   🔥 {s.seat_name}：买入{s.buy_amount:.0f}万 / 卖出{s.sell_amount:.0f}万")
                if normal_seats:
                    top_buyers = sorted(normal_seats, key=lambda x: x.buy_amount, reverse=True)[:2]
                    for s in top_buyers:
                        lines.append(f"   📍 {s.seat_name}：买入{s.buy_amount:.0f}万")
            lines.append("")
        
        # 12. 大宗交易
        if self.block_trades:
            lines.append("### 📦 大宗交易（机构暗盘动向）")
            # 分为折价交易和溢价交易
            discount_trades = [t for t in self.block_trades if t.discount_rate < -2]
            premium_trades = [t for t in self.block_trades if t.discount_rate > 0]
            
            if discount_trades:
                lines.append("\n**⚠️ 大幅折价交易（可能有减持压力）：**")
                for t in sorted(discount_trades, key=lambda x: x.discount_rate)[:5]:
                    lines.append(
                        f"- {t.name}（{t.code}）：成交价{t.price:.2f}元，折价{t.discount_rate:.1f}%，"
                        f"成交{t.amount:.0f}万元"
                    )
            
            if premium_trades:
                lines.append("\n**✅ 溢价交易（机构看好信号）：**")
                for t in sorted(premium_trades, key=lambda x: x.discount_rate, reverse=True)[:5]:
                    lines.append(
                        f"- {t.name}（{t.code}）：成交价{t.price:.2f}元，溢价+{t.discount_rate:.1f}%，"
                        f"成交{t.amount:.0f}万元"
                    )
            
            # 按成交金额排序的TOP5
            top_amount = sorted(self.block_trades, key=lambda x: x.amount, reverse=True)[:5]
            lines.append("\n**💰 成交金额TOP5：**")
            for t in top_amount:
                discount_str = f"折价{t.discount_rate:.1f}%" if t.discount_rate < 0 else f"溢价+{t.discount_rate:.1f}%"
                lines.append(f"- {t.name}（{t.code}）：{t.amount:.0f}万元，{discount_str}")
            lines.append("")
        
        # 13. 融资融券
        if self.margin_data:
            lines.append("### 💳 融资融券（杠杆资金动向）")
            md = self.margin_data
            
            margin_trend = "📈 加杠杆" if md.margin_balance_change > 0 else "📉 降杠杆"
            lines.append(f"- 融资余额：{md.total_margin_balance:.0f}亿元（较前日{md.margin_balance_change:+.2f}亿 {margin_trend}）")
            lines.append(f"- 融资买入额：{md.margin_buy_amount:.0f}亿元")
            if md.total_short_balance > 0:
                short_trend = "📈" if md.short_balance_change > 0 else "📉"
                lines.append(f"- 融券余额：{md.total_short_balance:.2f}亿元（较前日{md.short_balance_change:+.2f}亿 {short_trend}）")
            
            if md.top_margin_stocks:
                lines.append("\n**融资余额Top股票（杠杆资金最看好）：**")
                for s in md.top_margin_stocks[:5]:
                    lines.append(f"- {s.get('name', '')}（{s.get('code', '')}）：融资余额{s.get('balance', 0):.2f}亿元，变化{s.get('change', 0):+.2f}亿")
            lines.append("")
        
        return "\n".join(lines)


class MarketDataService:
    """市场数据服务"""
    
    def __init__(self):
        self.akshare_available = False
        self._check_akshare()
    
    def _check_akshare(self):
        """检查 AKShare 是否可用"""
        try:
            import akshare
            self.akshare_available = True
            print("✅ MarketDataService: AKShare 可用")
        except ImportError:
            print("⚠️ MarketDataService: AKShare 不可用")
    
    async def _call_akshare_with_retry(self, func, *args, max_retries: int = 2, use_cache: bool = True, cache_key: str = None, **kwargs):
        """
        带重试 + 全局限流 + 缓存的 AKShare 调用包装
        
        四重保护：
        1. 全局令牌桶限流（每 1.5 秒最多 1 个请求）
        2. requests 全局 30 秒超时（模块级 monkey-patch）
        3. asyncio.wait_for 45 秒超时（本函数）
        4. scheduler 层 10 分钟总超时（外层兜底）
        
        缓存机制：
        - 同一交易日内，相同接口调用直接返回缓存结果
        - 大幅减少对东方财富的重复请求
        """
        global _akshare_rate_limiter, _market_data_cache
        
        # 生成缓存 key
        if cache_key is None:
            cache_key = f"{func.__name__}_{str(args)}_{str(sorted(kwargs.items()))}"
        
        # 检查缓存
        if use_cache:
            cached = _market_data_cache.get(cache_key)
            if cached is not None:
                print(f"  [AKShare] {func.__name__} 命中缓存，跳过网络请求", flush=True)
                return cached
        
        SINGLE_CALL_TIMEOUT = 45
        last_error = None
        
        for attempt in range(max_retries):
            try:
                # 全局限流：等待令牌
                await _akshare_rate_limiter.acquire()
                
                # AKShare 是同步库，在线程池中执行避免阻塞事件循环
                loop = asyncio.get_event_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: func(*args, **kwargs)),
                    timeout=SINGLE_CALL_TIMEOUT
                )
                
                # 成功后写入缓存
                if use_cache and result is not None:
                    _market_data_cache.set(cache_key, result)
                
                return result
            except asyncio.TimeoutError:
                last_error = TimeoutError(f"{func.__name__} 超时 ({SINGLE_CALL_TIMEOUT}s)")
                print(f"  [AKShare] {func.__name__} 第{attempt+1}次超时({SINGLE_CALL_TIMEOUT}s)", flush=True)
                if attempt < max_retries - 1:
                    wait = (attempt + 1) * 3
                    print(f"  [AKShare] {wait}秒后重试...", flush=True)
                    await asyncio.sleep(wait)
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait = (attempt + 1) * 4  # 4秒、8秒递增（更长的间隔降低被封风险）
                    print(f"  [AKShare] {func.__name__} 第{attempt+1}次失败: {type(e).__name__}, {wait}秒后重试...", flush=True)
                    await asyncio.sleep(wait)
        
        raise last_error
    
    async def get_market_overview(self, target_date: Optional[date] = None) -> MarketOverview:
        """
        获取市场全面数据
        
        Args:
            target_date: 目标日期，默认为今天
            
        Returns:
            MarketOverview 包含所有市场数据
        """
        if target_date is None:
            target_date = date.today()
        
        date_str = target_date.strftime("%Y-%m-%d")
        overview = MarketOverview(date=date_str)
        
        if not self.akshare_available:
            print("⚠️ AKShare 不可用，将仅使用 HTTP 直连方案获取数据")
        
        # 串行获取各类数据，每次间隔 1 秒，避免触发数据源限流/反爬
        task_configs = [
            ("指数", self._get_indices),
            ("板块排行", self._get_sector_ranking),
            ("资金流向", self._get_fund_flow),
            ("涨跌停", lambda: self._get_limit_stocks(target_date)),
            ("市场统计", self._get_market_stats),
            ("热门股票", lambda: self._get_hot_stocks(target_date)),
            ("概念板块", self._get_concept_sectors),
            ("连板强势股", lambda: self._get_consecutive_limit_stocks(target_date)),
            ("技术信号机会股", lambda: self._get_tech_signal_stocks(target_date)),
            ("大宗商品", self._get_commodities),
            ("外盘指数", self._get_global_indices),
            ("龙虎榜席位", lambda: self._get_lhb_seats(target_date)),
            ("大宗交易", lambda: self._get_block_trades(target_date)),
            ("融资融券", lambda: self._get_margin_trading(target_date)),
        ]
        
        results = []
        for name, task_func in task_configs:
            try:
                result = await task_func()
                results.append(result)
                # 检查返回值是否为空数据（空列表/空元组/None/空字典）
                is_empty = (
                    result is None or 
                    result == [] or 
                    result == ([], []) or 
                    (isinstance(result, dict) and all(v == 0 for v in result.values()))
                )
                if is_empty:
                    print(f"  [WARN] {name} 返回空数据（接口可能异常）")
                else:
                    print(f"  [OK] {name} 获取成功")
            except Exception as e:
                results.append(e)
                print(f"  [FAIL] {name} 获取失败: {e}")
            await asyncio.sleep(2)  # 间隔 2 秒，配合全局令牌桶避免限流
        
        # 处理结果（原有6个）
        if not isinstance(results[0], Exception):
            overview.indices = results[0]
        else:
            print(f"获取指数失败: {results[0]}")
            
        if not isinstance(results[1], Exception):
            top, bottom = results[1]
            overview.top_sectors = top
            overview.bottom_sectors = bottom
        else:
            print(f"获取板块排行失败: {results[1]}")
            
        if not isinstance(results[2], Exception):
            overview.fund_flow = results[2]
        else:
            print(f"获取资金流向失败: {results[2]}")
            
        if not isinstance(results[3], Exception):
            overview.limit_data = results[3]
        else:
            print(f"获取涨跌停失败: {results[3]}")
            
        if not isinstance(results[4], Exception):
            stats = results[4]
            overview.up_count = stats.get("up", 0)
            overview.down_count = stats.get("down", 0)
            overview.flat_count = stats.get("flat", 0)
            overview.total_volume = stats.get("total_volume", 0)
        else:
            print(f"获取市场统计失败: {results[4]}")
            
        if not isinstance(results[5], Exception):
            overview.hot_stocks = results[5]
        else:
            print(f"获取热门股票失败: {results[5]}")
        
        # 处理结果（新增3个）
        if not isinstance(results[6], Exception):
            overview.concept_sectors = results[6]
        else:
            print(f"获取概念板块失败: {results[6]}")
        
        if not isinstance(results[7], Exception):
            overview.consecutive_limit_stocks = results[7]
        else:
            print(f"获取连板强势股失败: {results[7]}")
        
        if not isinstance(results[8], Exception):
            overview.tech_signal_stocks = results[8]
        else:
            print(f"获取技术信号机会股失败: {results[8]}")
        
        # 处理结果（大宗商品+外盘）
        if not isinstance(results[9], Exception):
            overview.commodities = results[9]
        else:
            print(f"获取大宗商品失败: {results[9]}")
        
        if not isinstance(results[10], Exception):
            overview.global_indices = results[10]
        else:
            print(f"获取外盘指数失败: {results[10]}")
        
        # 处理结果（聪明钱数据）
        if len(results) > 11 and not isinstance(results[11], Exception):
            overview.lhb_seats = results[11]
        elif len(results) > 11:
            print(f"获取龙虎榜席位失败: {results[11]}")
        
        if len(results) > 12 and not isinstance(results[12], Exception):
            overview.block_trades = results[12]
        elif len(results) > 12:
            print(f"获取大宗交易失败: {results[12]}")
        
        if len(results) > 13 and not isinstance(results[13], Exception):
            overview.margin_data = results[13]
        elif len(results) > 13:
            print(f"获取融资融券失败: {results[13]}")
        
        # 计算市场情绪
        overview.market_sentiment = self._calculate_sentiment(overview)
        
        # 汇总日志：哪些数据成功，哪些失败（空数据也算失败）
        def _is_empty_result(r):
            """检查结果是否为空数据"""
            if isinstance(r, Exception):
                return True
            if r is None or r == [] or r == ([], []):
                return True
            if isinstance(r, dict) and all(v == 0 for v in r.values()):
                return True
            return False
        
        real_success_count = sum(1 for r in results if not _is_empty_result(r))
        empty_count = sum(1 for r in results if not isinstance(r, Exception) and _is_empty_result(r))
        fail_count = sum(1 for r in results if isinstance(r, Exception))
        fail_names = [task_configs[i][0] for i, r in enumerate(results) if isinstance(r, Exception)]
        empty_names = [task_configs[i][0] for i, r in enumerate(results) if not isinstance(r, Exception) and _is_empty_result(r)]
        
        problem_names = fail_names + empty_names
        print(f"\n  [市场数据汇总] {real_success_count}/{len(results)} 项有效数据"
              f"（{fail_count} 项异常, {empty_count} 项空数据）"
              f"{f'，问题项: {chr(44).join(problem_names)}' if problem_names else ''}")
        
        # ── 熔断机制：核心数据全部失败则中止报告生成 ──
        # 核心数据 = 指数 + 板块排行 + 市场统计，这三项全失败说明所有数据源都不可用
        core_data_ok = (
            bool(overview.indices) or
            bool(overview.top_sectors) or
            (overview.up_count > 0 or overview.down_count > 0)
        )
        if not core_data_ok:
            error_msg = (
                f"[熔断] ⚠️ 核心市场数据全部采集失败！"
                f"（指数: {'失败' if not overview.indices else 'OK'}, "
                f"板块: {'失败' if not overview.top_sectors else 'OK'}, "
                f"涨跌统计: {'失败' if overview.up_count == 0 and overview.down_count == 0 else 'OK'}）\n"
                f"失败项: {', '.join(fail_names)}\n"
                f"所有数据源（AKShare/东方财富/腾讯/新浪）均不可用，中止报告生成以避免输出无数据的空报告。"
            )
            print(error_msg, flush=True)
            raise RuntimeError(error_msg)
        
        return overview
    
    async def _get_indices(self) -> List[IndexData]:
        """
        获取主要指数数据（4层备用链路）
        
        方案1: AKShare → 东方财富 (stock_zh_index_spot_em)
        方案2: 东方财富 HTTP 直连 (push2.eastmoney.com，绕过AKShare)
        方案3: 腾讯财经 HTTP 直连 (qt.gtimg.cn，最稳定)
        方案4: 新浪实时行情 HTTP 直连 (hq.sinajs.cn)
        """
        indices = []
        
        # ── 方案1：AKShare → 东方财富 ──
        try:
            import akshare as ak
            df = await self._call_akshare_with_retry(ak.stock_zh_index_spot_em)
            
            main_indices = {
                "000001": "上证指数",
                "399001": "深证成指",
                "399006": "创业板指",
                "000688": "科创50",
                "000300": "沪深300",
            }
            
            for code, name in main_indices.items():
                row = df[df['代码'] == code]
                if not row.empty:
                    r = row.iloc[0]
                    indices.append(IndexData(
                        code=code,
                        name=name,
                        current=float(r['最新价']),
                        change=float(r['涨跌额']),
                        change_pct=float(r['涨跌幅']),
                        volume=float(r.get('成交量', 0)),
                        amount=float(r.get('成交额', 0)),
                        high=float(r.get('最高', 0)),
                        low=float(r.get('最低', 0)),
                        open=float(r.get('今开', 0)),
                    ))
            if indices:
                print(f"  [指数] 方案1（AKShare东方财富）获取成功: {len(indices)} 个指数")
                return indices
        except Exception as e:
            print(f"  [指数] 方案1（AKShare东方财富）失败: {e}")
        
        # ── 方案2：东方财富 HTTP 直连（绕过AKShare） ──
        try:
            indices = await self._fetch_indices_eastmoney_http()
            if indices:
                print(f"  [指数] 方案2（东方财富HTTP直连）获取成功: {len(indices)} 个指数")
                return indices
        except Exception as e:
            print(f"  [指数] 方案2（东方财富HTTP直连）失败: {e}")
        
        # ── 方案3：腾讯财经 HTTP 直连（最稳定） ──
        try:
            indices = await self._fetch_indices_tencent_http()
            if indices:
                print(f"  [指数] 方案3（腾讯财经HTTP直连）获取成功: {len(indices)} 个指数")
                return indices
        except Exception as e:
            print(f"  [指数] 方案3（腾讯财经HTTP直连）失败: {e}")
        
        # ── 方案4：新浪实时行情 HTTP 直连 ──
        try:
            indices = await self._fetch_indices_sina_http()
            if indices:
                print(f"  [指数] 方案4（新浪HTTP直连）获取成功: {len(indices)} 个指数")
                return indices
        except Exception as e:
            print(f"  [指数] 方案4（新浪HTTP直连）失败: {e}")
        
        print("  [指数] ⚠️ 所有4个方案均失败！")
        return indices
    
    async def _fetch_indices_eastmoney_http(self) -> List[IndexData]:
        """
        方案2：东方财富 push2.eastmoney.com 直连
        不依赖 AKShare，直接 HTTP 请求
        """
        import urllib.request
        import ssl
        import json
        
        # 东方财富 secid 格式: 1.000001=上证, 0.399001=深证
        em_indices = {
            "1.000001": ("000001", "上证指数"),
            "0.399001": ("399001", "深证成指"),
            "0.399006": ("399006", "创业板指"),
            "1.000688": ("000688", "科创50"),
            "1.000300": ("000300", "沪深300"),
        }
        
        secids = ",".join(em_indices.keys())
        url = (
            f"https://push2.eastmoney.com/api/qt/ulist.np/get?"
            f"fltt=2&secids={secids}"
            f"&fields=f2,f3,f4,f6,f12,f13,f14,f15,f16,f17,f18"
        )
        
        def _do_request():
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            req.add_header('Referer', 'https://quote.eastmoney.com/')
            
            with urllib.request.urlopen(req, timeout=15, context=ctx) as response:
                return json.loads(response.read().decode('utf-8'))
        
        loop = asyncio.get_event_loop()
        data = await asyncio.wait_for(
            loop.run_in_executor(None, _do_request),
            timeout=20
        )
        
        indices = []
        diff_list = data.get("data", {}).get("diff", []) if data.get("data") else []
        
        for item in diff_list:
            secid = f"{item.get('f13', '')}.{item.get('f12', '')}"
            if secid in em_indices:
                code, name = em_indices[secid]
                current = item.get('f2', 0)
                if current and current != '-':
                    indices.append(IndexData(
                        code=code,
                        name=name,
                        current=float(current),
                        change=float(item.get('f4', 0) or 0),
                        change_pct=float(item.get('f3', 0) or 0),
                        amount=float(item.get('f6', 0) or 0),
                        high=float(item.get('f15', 0) or 0),
                        low=float(item.get('f16', 0) or 0),
                        open=float(item.get('f17', 0) or 0),
                    ))
        
        return indices
    
    async def _fetch_indices_tencent_http(self) -> List[IndexData]:
        """
        方案3：腾讯财经 qt.gtimg.cn 直连
        不依赖 AKShare，国内最稳定的行情接口
        """
        import urllib.request
        import ssl
        
        qq_indices = {
            "sh000001": ("000001", "上证指数"),
            "sz399001": ("399001", "深证成指"),
            "sz399006": ("399006", "创业板指"),
            "sh000688": ("000688", "科创50"),
            "sh000300": ("000300", "沪深300"),
        }
        
        symbols = ",".join(qq_indices.keys())
        url = f"http://qt.gtimg.cn/q={symbols}"
        
        def _do_request():
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'Mozilla/5.0')
            
            with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
                return response.read().decode('gbk')
        
        loop = asyncio.get_event_loop()
        content = await asyncio.wait_for(
            loop.run_in_executor(None, _do_request),
            timeout=15
        )
        
        indices = []
        for line in content.strip().split(';'):
            if '=' not in line or '~' not in line:
                continue
            
            var_name = line.split('=')[0].replace('v_', '').strip()
            data_str = line.split('"')[1] if '"' in line else ""
            
            if var_name in qq_indices and data_str:
                code, name = qq_indices[var_name]
                parts = data_str.split('~')
                
                if len(parts) >= 6:
                    try:
                        current_price = float(parts[3]) if parts[3] else 0
                        change = float(parts[4]) if parts[4] else 0
                        
                        # 涨跌幅：优先 parts[32]，其次 parts[5]
                        change_pct = 0
                        if len(parts) > 32 and parts[32]:
                            try:
                                change_pct = float(parts[32])
                            except ValueError:
                                pass
                        if change_pct == 0 and parts[5]:
                            try:
                                pct_val = float(parts[5])
                                if abs(pct_val) <= 100:
                                    change_pct = pct_val
                                elif current_price > 0 and change != 0:
                                    prev_close = current_price - change
                                    if prev_close > 0:
                                        change_pct = (change / prev_close) * 100
                            except ValueError:
                                pass
                        
                        if current_price > 0:
                            indices.append(IndexData(
                                code=code,
                                name=name,
                                current=current_price,
                                change=change,
                                change_pct=round(change_pct, 2),
                                volume=float(parts[6]) * 100 if len(parts) > 6 and parts[6] else 0,
                                amount=float(parts[7]) * 10000 if len(parts) > 7 and parts[7] else 0,
                                high=float(parts[33]) if len(parts) > 33 and parts[33] else 0,
                                low=float(parts[34]) if len(parts) > 34 and parts[34] else 0,
                                open=0,
                            ))
                    except (ValueError, IndexError) as e:
                        print(f"  [腾讯] 解析 {var_name} 失败: {e}")
        
        return indices
    
    async def _fetch_indices_sina_http(self) -> List[IndexData]:
        """
        方案4：新浪实时行情 hq.sinajs.cn 直连
        注意：需要 Referer 头，返回 GBK 编码
        """
        import urllib.request
        import ssl
        
        sina_indices = {
            "sh000001": ("000001", "上证指数"),
            "sz399001": ("399001", "深证成指"),
            "sz399006": ("399006", "创业板指"),
            "sh000300": ("000300", "沪深300"),
            "sh000688": ("000688", "科创50"),
        }
        
        symbols = ",".join(sina_indices.keys())
        url = f"https://hq.sinajs.cn/list={symbols}"
        
        def _do_request():
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            req.add_header('Referer', 'https://finance.sina.com.cn')
            
            with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
                return response.read().decode('gbk')
        
        loop = asyncio.get_event_loop()
        content = await asyncio.wait_for(
            loop.run_in_executor(None, _do_request),
            timeout=15
        )
        
        indices = []
        for line in content.strip().split('\n'):
            if '=' not in line or '"' not in line:
                continue
            
            # 格式: var hq_str_sh000001="上证指数,3299.7057,...";
            var_part = line.split('=')[0].strip()
            symbol = var_part.split('_')[-1] if '_' in var_part else ""
            
            data_str = line.split('"')[1] if '"' in line else ""
            if not data_str or symbol not in sina_indices:
                continue
            
            code, name = sina_indices[symbol]
            parts = data_str.split(',')
            
            # 新浪指数格式: 名称,今开,昨收,当前价,最高,最低,成交量,成交额,...
            if len(parts) >= 7:
                try:
                    current = float(parts[3]) if parts[3] else 0
                    open_price = float(parts[1]) if parts[1] else 0
                    prev_close = float(parts[2]) if parts[2] else 0
                    high = float(parts[4]) if parts[4] else 0
                    low = float(parts[5]) if parts[5] else 0
                    volume = float(parts[6]) if parts[6] else 0
                    amount = float(parts[7]) if len(parts) > 7 and parts[7] else 0
                    
                    if current > 0 and prev_close > 0:
                        change = current - prev_close
                        change_pct = (change / prev_close) * 100
                        
                        indices.append(IndexData(
                            code=code,
                            name=name,
                            current=current,
                            change=round(change, 2),
                            change_pct=round(change_pct, 2),
                            volume=volume,
                            amount=amount,
                            high=high,
                            low=low,
                            open=open_price,
                        ))
                except (ValueError, IndexError) as e:
                    print(f"  [新浪] 解析 {symbol} 失败: {e}")
        
        return indices
    
    async def _get_sector_ranking(self) -> tuple:
        """
        获取板块涨跌排行（4层备用）
        
        方案1: AKShare → 东方财富行业板块
        方案2: AKShare → 同花顺行业板块
        方案3: 东方财富 HTTP 直连（绕过AKShare，不走push2域名）
        方案4: 腾讯财经 HTTP 直连（最稳定）
        """
        import akshare as ak
        
        top_sectors = []
        bottom_sectors = []
        
        # 方案1：东方财富行业板块（AKShare）
        try:
            df = await self._call_akshare_with_retry(ak.stock_board_industry_name_em)
            
            if df is not None and not df.empty:
                df_sorted = df.sort_values('涨跌幅', ascending=False)
                
                for _, row in df_sorted.head(5).iterrows():
                    top_sectors.append(SectorData(
                        name=row['板块名称'],
                        change_pct=float(row['涨跌幅']),
                        leader_stock=str(row.get('领涨股票', '')),
                        leader_change=float(row.get('领涨股票-涨跌幅', 0)),
                    ))
                
                for _, row in df_sorted.tail(5).iterrows():
                    bottom_sectors.append(SectorData(
                        name=row['板块名称'],
                        change_pct=float(row['涨跌幅']),
                    ))
                    
                if top_sectors:
                    return top_sectors, bottom_sectors
        except Exception as e:
            print(f"  [板块排行] 方案1（AKShare东方财富）失败: {e}")
        
        # 方案2：同花顺行业板块（AKShare）
        try:
            if hasattr(ak, 'stock_board_industry_name_ths'):
                df = await self._call_akshare_with_retry(
                    ak.stock_board_industry_name_ths, max_retries=1
                )
                if df is not None and not df.empty:
                    change_col = None
                    for col in df.columns:
                        if '涨跌' in str(col) or 'change' in str(col).lower():
                            change_col = col
                            break
                    name_col = None
                    for col in df.columns:
                        if '名称' in str(col) or '板块' in str(col):
                            name_col = col
                            break
                    
                    if change_col and name_col:
                        df_sorted = df.sort_values(change_col, ascending=False)
                        for _, row in df_sorted.head(5).iterrows():
                            top_sectors.append(SectorData(
                                name=str(row[name_col]),
                                change_pct=float(row[change_col]),
                            ))
                        for _, row in df_sorted.tail(5).iterrows():
                            bottom_sectors.append(SectorData(
                                name=str(row[name_col]),
                                change_pct=float(row[change_col]),
                            ))
                        if top_sectors:
                            print(f"  [板块排行] 方案2（同花顺AKShare）获取成功")
                            return top_sectors, bottom_sectors
        except Exception as e:
            print(f"  [板块排行] 方案2（同花顺AKShare）失败: {e}")
        
        # 方案3：东方财富 HTTP 直连（用 datacenter 域名，不走 push2）
        try:
            result = await self._fetch_sector_ranking_eastmoney_http()
            if result and result[0]:
                print(f"  [板块排行] 方案3（东方财富HTTP直连）获取成功")
                return result
        except Exception as e:
            print(f"  [板块排行] 方案3（东方财富HTTP直连）失败: {e}")
        
        # 方案4：腾讯财经 HTTP 直连
        try:
            result = await self._fetch_sector_ranking_tencent_http()
            if result and result[0]:
                print(f"  [板块排行] 方案4（腾讯财经HTTP）获取成功")
                return result
        except Exception as e:
            print(f"  [板块排行] 方案4（腾讯财经HTTP）失败: {e}")
        
        print("  [板块排行] ⚠️ 所有4个方案均失败！")
        return top_sectors, bottom_sectors
    
    async def _fetch_sector_ranking_eastmoney_http(self) -> tuple:
        """
        东方财富 datacenter-web 接口直连获取行业板块
        使用 datacenter-web.eastmoney.com（不同于被封的 push2 域名）
        """
        import urllib.request
        import ssl
        import json
        
        url = (
            "https://datacenter-web.eastmoney.com/api/data/v1/get?"
            "sortColumns=f3&sortTypes=-1&pageSize=100&pageNumber=1&"
            "reportName=RPT_BOARD_INDUSTRY_ALLDATA&"
            "columns=ALL&"
            "filter=(TRADE_DATE%3E%27{date}%27)"
        ).format(date=datetime.now().strftime("%Y-%m-%d"))
        
        # 备用：用 push2his（历史数据域名，不同于实时 push2）
        url_alt = (
            "https://push2.eastmoney.com/api/qt/clist/get?"
            "pn=1&pz=50&po=1&np=1&"
            "ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&"
            "fid=f3&fs=m:90+t:2+f:!50&"
            "fields=f2,f3,f4,f8,f12,f14,f15,f16,f17,f18,f20,f21,f24,f25,f128,f140,f141,f136"
        )
        
        def _do_request():
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            
            req = urllib.request.Request(url_alt)
            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            req.add_header('Referer', 'https://data.eastmoney.com/')
            
            with urllib.request.urlopen(req, timeout=15, context=ctx) as response:
                return json.loads(response.read().decode('utf-8'))
        
        loop = asyncio.get_event_loop()
        data = await asyncio.wait_for(
            loop.run_in_executor(None, _do_request),
            timeout=20
        )
        
        top_sectors = []
        bottom_sectors = []
        
        diff_list = data.get("data", {}).get("diff", []) if data.get("data") else []
        if not diff_list:
            return top_sectors, bottom_sectors
        
        # f14=板块名, f3=涨跌幅, f140=领涨股名, f136=领涨股涨跌幅
        items = sorted(diff_list, key=lambda x: float(x.get('f3', 0) or 0), reverse=True)
        
        for item in items[:5]:
            top_sectors.append(SectorData(
                name=str(item.get('f14', '')),
                change_pct=float(item.get('f3', 0) or 0),
                leader_stock=str(item.get('f140', '') or ''),
                leader_change=float(item.get('f136', 0) or 0),
            ))
        
        for item in items[-5:]:
            bottom_sectors.append(SectorData(
                name=str(item.get('f14', '')),
                change_pct=float(item.get('f3', 0) or 0),
            ))
        
        return top_sectors, bottom_sectors
    
    async def _fetch_sector_ranking_tencent_http(self) -> tuple:
        """
        腾讯财经获取行业板块排行
        使用腾讯板块接口 http://qt.gtimg.cn/q=qsBKhy 获取行业板块列表
        """
        import urllib.request
        import ssl
        import json
        
        # 腾讯行业板块列表接口
        url = "http://qt.gtimg.cn/q=bkhy"
        
        def _do_request():
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'Mozilla/5.0')
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.read().decode('gbk')
        
        loop = asyncio.get_event_loop()
        content = await asyncio.wait_for(
            loop.run_in_executor(None, _do_request),
            timeout=15
        )
        
        # 解析板块代码列表
        sector_codes = []
        if '=' in content and '"' in content:
            data_str = content.split('"')[1] if '"' in content else ""
            if data_str:
                sector_codes = [c.strip() for c in data_str.split(',') if c.strip()]
        
        if not sector_codes:
            return [], []
        
        # 批量获取板块行情（每次最多50个）
        batch = sector_codes[:50]
        symbols = ",".join(batch)
        detail_url = f"http://qt.gtimg.cn/q={symbols}"
        
        def _do_detail_request():
            req = urllib.request.Request(detail_url)
            req.add_header('User-Agent', 'Mozilla/5.0')
            with urllib.request.urlopen(req, timeout=15) as response:
                return response.read().decode('gbk')
        
        detail_content = await asyncio.wait_for(
            loop.run_in_executor(None, _do_detail_request),
            timeout=20
        )
        
        sectors_data = []
        for line in detail_content.strip().split(';'):
            if '=' not in line or '~' not in line:
                continue
            data_str = line.split('"')[1] if '"' in line else ""
            if not data_str:
                continue
            parts = data_str.split('~')
            if len(parts) >= 5:
                try:
                    name = parts[1] if len(parts) > 1 else ""
                    change_pct = float(parts[3]) if parts[3] else 0
                    if name:
                        sectors_data.append({"name": name, "change_pct": change_pct})
                except (ValueError, IndexError):
                    continue
        
        if not sectors_data:
            return [], []
        
        sectors_data.sort(key=lambda x: x["change_pct"], reverse=True)
        
        top_sectors = [SectorData(name=s["name"], change_pct=s["change_pct"]) for s in sectors_data[:5]]
        bottom_sectors = [SectorData(name=s["name"], change_pct=s["change_pct"]) for s in sectors_data[-5:]]
        
        return top_sectors, bottom_sectors
    
    async def _get_fund_flow(self) -> Optional[FundFlowData]:
        """获取大盘资金流向"""
        import akshare as ak
        
        try:
            # 获取大盘资金流向（带重试）
            df = await self._call_akshare_with_retry(ak.stock_market_fund_flow)
            
            if df is not None and not df.empty:
                # 取最新一行
                row = df.iloc[-1]
                
                return FundFlowData(
                    main_net_inflow=float(row.get('主力净流入-净额', 0)) / 100000000,  # 转为亿元
                    retail_net_inflow=float(row.get('小单净流入-净额', 0)) / 100000000,
                    super_large_inflow=float(row.get('超大单净流入-净额', 0)) / 100000000,
                    large_inflow=float(row.get('大单净流入-净额', 0)) / 100000000,
                    medium_inflow=float(row.get('中单净流入-净额', 0)) / 100000000,
                    small_inflow=float(row.get('小单净流入-净额', 0)) / 100000000,
                )
        except Exception as e:
            print(f"获取资金流向异常: {e}")
            traceback.print_exc()
        
        return None
    
    async def _get_limit_stocks(self, target_date: date) -> Optional[LimitData]:
        """获取涨跌停统计"""
        import akshare as ak
        
        limit_data = LimitData(up_limit_count=0, down_limit_count=0)
        date_str = target_date.strftime("%Y%m%d")
        
        try:
            # 获取涨停股票池
            try:
                df_up = await self._call_akshare_with_retry(ak.stock_zt_pool_em, date=date_str)
                if df_up is not None and not df_up.empty:
                    limit_data.up_limit_count = len(df_up)
                    limit_data.up_limit_stocks = [
                        {"code": row['代码'], "name": row['名称'], "reason": str(row.get('涨停原因', ''))}
                        for _, row in df_up.head(10).iterrows()
                    ]
            except Exception as e:
                print(f"获取涨停池异常（可能非交易日）: {e}")
            
            # 获取跌停股票池
            try:
                df_down = await self._call_akshare_with_retry(ak.stock_zt_pool_dtgc_em, date=date_str)
                if df_down is not None and not df_down.empty:
                    limit_data.down_limit_count = len(df_down)
                    limit_data.down_limit_stocks = [
                        {"code": row['代码'], "name": row['名称']}
                        for _, row in df_down.head(10).iterrows()
                    ]
            except:
                pass
                
        except Exception as e:
            print(f"获取涨跌停异常: {e}")
        
        return limit_data
    
    async def _get_market_stats(self) -> Dict:
        """
        获取市场涨跌统计（2层备用）
        
        方案1: AKShare → stock_zh_a_spot_em（全A股实时行情）
        方案2: 腾讯财经 HTTP 直连（沪深市场统计）
        """
        import akshare as ak
        
        stats = {"up": 0, "down": 0, "flat": 0, "total_volume": 0}
        
        # 方案1：AKShare 全A股实时行情
        try:
            df = await self._call_akshare_with_retry(ak.stock_zh_a_spot_em)
            
            if df is not None and not df.empty:
                stats["up"] = len(df[df['涨跌幅'] > 0])
                stats["down"] = len(df[df['涨跌幅'] < 0])
                stats["flat"] = len(df[df['涨跌幅'] == 0])
                
                total_amount = df['成交额'].sum()
                stats["total_volume"] = total_amount / 100000000
                
                if stats["up"] > 0 or stats["down"] > 0:
                    return stats
        except Exception as e:
            print(f"  [市场统计] 方案1（AKShare）失败: {e}")
        
        # 方案2：腾讯财经 HTTP 直连
        try:
            stats = await self._fetch_market_stats_tencent_http()
            if stats["up"] > 0 or stats["down"] > 0:
                print(f"  [市场统计] 方案2（腾讯财经HTTP）获取成功")
                return stats
        except Exception as e:
            print(f"  [市场统计] 方案2（腾讯财经HTTP）失败: {e}")
        
        print("  [市场统计] ⚠️ 所有方案均失败！")
        return stats
    
    async def _fetch_market_stats_tencent_http(self) -> Dict:
        """
        腾讯财经 HTTP 直连获取市场统计
        
        使用上证指数和深证成指的详细行情数据中包含的涨跌家数信息。
        腾讯接口 qt.gtimg.cn 返回的数据中，parts[4]/[5] 包含涨跌数。
        
        备选方案：通过查询沪深两市大盘指数的成交额来估算。
        """
        import urllib.request
        import ssl
        
        stats = {"up": 0, "down": 0, "flat": 0, "total_volume": 0}
        
        # 通过腾讯获取上证和深证两个指数的成交额
        url = "http://qt.gtimg.cn/q=sh000001,sz399001"
        
        def _do_request():
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'Mozilla/5.0')
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.read().decode('gbk')
        
        loop = asyncio.get_event_loop()
        content = await asyncio.wait_for(
            loop.run_in_executor(None, _do_request),
            timeout=15
        )
        
        total_amount = 0
        for line in content.strip().split(';'):
            if '=' not in line or '~' not in line:
                continue
            data_str = line.split('"')[1] if '"' in line else ""
            if not data_str:
                continue
            parts = data_str.split('~')
            
            # parts[7] = 成交额（万元）, parts[4] = 涨跌额
            if len(parts) > 7 and parts[7]:
                try:
                    # 腾讯返回的成交额单位是万元
                    amount = float(parts[7]) * 10000  # 转为元
                    total_amount += amount
                except ValueError:
                    pass
        
        if total_amount > 0:
            stats["total_volume"] = total_amount / 100000000  # 转为亿元
        
        # 尝试通过东方财富涨跌统计专用接口
        try:
            import json
            stat_url = (
                "https://push2.eastmoney.com/api/qt/clist/get?"
                "pn=1&pz=1&po=1&np=1&"
                "ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&"
                "fid=f12&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048&"
                "fields=f3"
            )
            
            def _do_stat_request():
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                req = urllib.request.Request(stat_url)
                req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
                req.add_header('Referer', 'https://quote.eastmoney.com/')
                with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
                    return json.loads(response.read().decode('utf-8'))
            
            data = await asyncio.wait_for(
                loop.run_in_executor(None, _do_stat_request),
                timeout=15
            )
            
            total_count = data.get("data", {}).get("total", 0) if data.get("data") else 0
            if total_count > 0:
                # 东方财富API返回的 total 是全部A股数量
                # 由于只请求了1条数据，无法精确统计涨跌
                # 但可以用大盘指数的涨跌幅估算大致比例
                pass
        except Exception:
            pass
        
        return stats
    
    async def _get_hot_stocks(self, target_date: date) -> List[HotStockData]:
        """
        获取热门股票（3层备用）
        
        方案1: AKShare 龙虎榜（兼容多个版本参数格式）
        方案2: 东方财富 HTTP 直连龙虎榜
        方案3: AKShare 换手率排行（兜底）
        """
        import akshare as ak
        
        hot_stocks = []
        date_str = target_date.strftime("%Y%m%d")
        date_str_dash = target_date.strftime("%Y-%m-%d")
        
        # 方案1：AKShare 龙虎榜（兼容多个版本参数格式）
        try:
            lhb_df = None
            
            # 兼容6种参数格式，覆盖各版本AKShare
            param_variants = [
                {"start_date": date_str, "end_date": date_str},
                {"start_date": date_str_dash, "end_date": date_str_dash},
                {"date": date_str},
                {"date": date_str_dash},
            ]
            
            for params in param_variants:
                try:
                    lhb_df = await self._call_akshare_with_retry(
                        ak.stock_lhb_detail_em, max_retries=1, **params
                    )
                    if lhb_df is not None and not lhb_df.empty:
                        break
                    lhb_df = None
                except (TypeError, ValueError):
                    lhb_df = None
                    continue
                except Exception:
                    lhb_df = None
                    continue
            
            # 备选接口：stock_lhb_jgmmtj_em（机构买卖统计）
            if lhb_df is None:
                for params in param_variants[:2]:
                    try:
                        if hasattr(ak, 'stock_lhb_jgmmtj_em'):
                            lhb_df = await self._call_akshare_with_retry(
                                ak.stock_lhb_jgmmtj_em, max_retries=1, **params
                            )
                            if lhb_df is not None and not lhb_df.empty:
                                break
                            lhb_df = None
                    except (TypeError, ValueError, Exception):
                        lhb_df = None
                        continue
            
            if lhb_df is not None and not lhb_df.empty:
                code_col = '代码' if '代码' in lhb_df.columns else lhb_df.columns[0]
                name_col = '名称' if '名称' in lhb_df.columns else lhb_df.columns[1]
                lhb_df_unique = lhb_df.drop_duplicates(subset=[code_col], keep='first')
                
                for _, row in lhb_df_unique.head(10).iterrows():
                    hot_stocks.append(HotStockData(
                        code=str(row[code_col]),
                        name=str(row[name_col]),
                        price=float(row.get('收盘价', row.get('最新价', 0))),
                        change_pct=float(row.get('涨跌幅', 0)),
                        reason=f"龙虎榜：{row.get('上榜原因', '异动')}"
                    ))
                if hot_stocks:
                    print(f"  [龙虎榜] 方案1（AKShare）获取 {len(hot_stocks)} 只热门股票")
                    return hot_stocks
        except Exception as e:
            print(f"  [龙虎榜] 方案1（AKShare）失败: {e}")
        
        # 方案2：东方财富 HTTP 直连龙虎榜
        try:
            hot_stocks = await self._fetch_hot_stocks_eastmoney_http(date_str)
            if hot_stocks:
                print(f"  [龙虎榜] 方案2（东方财富HTTP）获取 {len(hot_stocks)} 只热门股票")
                return hot_stocks
        except Exception as e:
            print(f"  [龙虎榜] 方案2（东方财富HTTP）失败: {e}")
        
        # 方案3：换手率排行（兜底）
        try:
            df = await self._call_akshare_with_retry(ak.stock_zh_a_spot_em)
            if df is not None and not df.empty:
                df_sorted = df.sort_values('换手率', ascending=False)
                for _, row in df_sorted.head(5).iterrows():
                    hot_stocks.append(HotStockData(
                        code=row['代码'],
                        name=row['名称'],
                        price=float(row['最新价']),
                        change_pct=float(row['涨跌幅']),
                        turnover_rate=float(row.get('换手率', 0)),
                        reason=f"换手率 {row.get('换手率', 0):.1f}%"
                    ))
                if hot_stocks:
                    print(f"  [龙虎榜] 方案3（换手率排行）获取 {len(hot_stocks)} 只")
        except Exception as e:
            print(f"  [龙虎榜] 方案3（换手率排行）也失败: {e}")
        
        return hot_stocks
    
    async def _fetch_hot_stocks_eastmoney_http(self, date_str: str) -> List[HotStockData]:
        """
        东方财富 HTTP 直连获取龙虎榜数据
        使用 datacenter-web.eastmoney.com 的龙虎榜接口
        """
        import urllib.request
        import ssl
        import json
        
        # 东方财富龙虎榜 Web API（datacenter 域名，不是 push2）
        url = (
            f"https://datacenter-web.eastmoney.com/api/data/v1/get?"
            f"sortColumns=SECURITY_CODE&sortTypes=1&pageSize=50&pageNumber=1&"
            f"reportName=RPT_DAILYBILLBOARD_DETAILSNEW&"
            f"columns=SECURITY_CODE,SECURITY_NAME_ABBR,CHANGE_RATE,CLOSE_PRICE,EXPLANATION&"
            f"filter=(TRADE_DATE%3D%27{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}%27)"
        )
        
        def _do_request():
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            req.add_header('Referer', 'https://data.eastmoney.com/')
            
            with urllib.request.urlopen(req, timeout=15, context=ctx) as response:
                return json.loads(response.read().decode('utf-8'))
        
        loop = asyncio.get_event_loop()
        data = await asyncio.wait_for(
            loop.run_in_executor(None, _do_request),
            timeout=20
        )
        
        hot_stocks = []
        result_data = data.get("result", {})
        if not result_data:
            return hot_stocks
        
        items = result_data.get("data", []) or []
        
        # 去重
        seen_codes = set()
        for item in items:
            code = str(item.get('SECURITY_CODE', ''))
            if code in seen_codes:
                continue
            seen_codes.add(code)
            
            hot_stocks.append(HotStockData(
                code=code,
                name=str(item.get('SECURITY_NAME_ABBR', '')),
                price=float(item.get('CLOSE_PRICE', 0) or 0),
                change_pct=float(item.get('CHANGE_RATE', 0) or 0),
                reason=f"龙虎榜：{item.get('EXPLANATION', '异动')}"
            ))
            
            if len(hot_stocks) >= 10:
                break
        
        return hot_stocks
    
    async def _get_concept_sectors(self) -> List[ConceptSectorData]:
        """
        获取概念板块排行（2层备用）
        
        方案1: AKShare → 东方财富概念板块
        方案2: 东方财富 HTTP 直连（push2 接口，概念板块专用）
        """
        import akshare as ak
        
        concept_sectors = []
        
        # 方案1：AKShare 东方财富概念板块
        try:
            df = await self._call_akshare_with_retry(ak.stock_board_concept_name_em)
            
            if df is not None and not df.empty:
                df_sorted = df.sort_values('涨跌幅', ascending=False)
                
                for _, row in df_sorted.head(10).iterrows():
                    concept_sectors.append(ConceptSectorData(
                        name=str(row.get('板块名称', '')),
                        change_pct=float(row.get('涨跌幅', 0)),
                        leader_stock=str(row.get('领涨股票', '')),
                        leader_change=float(row.get('领涨股票-涨跌幅', 0)),
                        stock_count=int(row.get('总市值', 0)) if '上涨家数' not in df.columns else int(row.get('上涨家数', 0)),
                    ))
                if concept_sectors:
                    return concept_sectors
        except Exception as e:
            print(f"  [概念板块] 方案1（AKShare东方财富）失败: {e}")
        
        # 方案2：东方财富 HTTP 直连
        try:
            concept_sectors = await self._fetch_concept_sectors_eastmoney_http()
            if concept_sectors:
                print(f"  [概念板块] 方案2（东方财富HTTP直连）获取成功: {len(concept_sectors)} 个")
                return concept_sectors
        except Exception as e:
            print(f"  [概念板块] 方案2（东方财富HTTP直连）失败: {e}")
        
        print("  [概念板块] ⚠️ 所有方案均失败！")
        return concept_sectors
    
    async def _fetch_concept_sectors_eastmoney_http(self) -> List[ConceptSectorData]:
        """
        东方财富 HTTP 直连获取概念板块
        使用 push2.eastmoney.com 的 clist 接口（fs=m:90+t:3 = 概念板块）
        """
        import urllib.request
        import ssl
        import json
        
        url = (
            "https://push2.eastmoney.com/api/qt/clist/get?"
            "pn=1&pz=50&po=1&np=1&"
            "ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&"
            "fid=f3&fs=m:90+t:3+f:!50&"
            "fields=f2,f3,f4,f8,f12,f14,f15,f16,f17,f18,f20,f21,f24,f25,f104,f105,f128,f140,f141,f136"
        )
        
        def _do_request():
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            req.add_header('Referer', 'https://data.eastmoney.com/')
            
            with urllib.request.urlopen(req, timeout=15, context=ctx) as response:
                return json.loads(response.read().decode('utf-8'))
        
        loop = asyncio.get_event_loop()
        data = await asyncio.wait_for(
            loop.run_in_executor(None, _do_request),
            timeout=20
        )
        
        concept_sectors = []
        diff_list = data.get("data", {}).get("diff", []) if data.get("data") else []
        if not diff_list:
            return concept_sectors
        
        # 已按 f3(涨跌幅) 降序排列
        for item in diff_list[:10]:
            concept_sectors.append(ConceptSectorData(
                name=str(item.get('f14', '')),
                change_pct=float(item.get('f3', 0) or 0),
                leader_stock=str(item.get('f140', '') or ''),
                leader_change=float(item.get('f136', 0) or 0),
                stock_count=int(item.get('f104', 0) or 0),  # f104=上涨家数
            ))
        
        return concept_sectors
    
    async def _get_consecutive_limit_stocks(self, target_date: date) -> List[ConsecutiveLimitStock]:
        """
        获取连板强势股
        
        使用 AKShare 的涨停股票池接口，筛选连续涨停天数 >= 2 的股票。
        
        注意：东方财富的涨停股票池数据在收盘后（15:00）约 30-60 分钟才完成更新。
        若在数据更新完成前调用，接口会静默返回前一个交易日的数据。
        因此此处加入数据新鲜度验证：通过检查返回数据量是否与历史均值差距过大，
        以及调用时间来判断是否需要重试。
        """
        import akshare as ak
        import re
        from datetime import datetime as dt
        
        consecutive_stocks = []
        date_str = target_date.strftime("%Y%m%d")
        
        # 在收盘后窗口期（15:00-17:00）内最多重试 3 次，每次等待 5 分钟
        now = dt.now()
        is_post_close_window = (now.hour == 15 or now.hour == 16)
        max_attempts = 3 if is_post_close_window else 1
        
        def parse_df(df):
            """解析 DataFrame，返回连板股列表和涨停总数"""
            import re
            
            def parse_limit_days_field(text):
                text = str(text)
                # 优先取"板"前面的数字（代表涨停次数），如 "5天3板" → 3
                match_ban = re.search(r'(\d+)板', text)
                if match_ban:
                    return int(match_ban.group(1))
                # fallback 取"天"前面的数字
                match_tian = re.search(r'(\d+)天', text)
                return int(match_tian.group(1)) if match_tian else 1
            
            total_count = len(df)
            
            if '连板数' in df.columns:
                df_multi = df[df['连板数'] >= 2].sort_values('连板数', ascending=False)
                get_limit_days = lambda row: int(row.get('连板数', 0))
            elif '几天几板' in df.columns:
                df['_limit_days'] = df['几天几板'].apply(parse_limit_days_field)
                df_multi = df[df['_limit_days'] >= 2].sort_values('_limit_days', ascending=False)
                get_limit_days = lambda row: int(row.get('_limit_days', 0))
            else:
                return [], total_count
            
            stocks = []
            for _, row in df_multi.head(10).iterrows():
                limit_days = get_limit_days(row)
                stocks.append(ConsecutiveLimitStock(
                    code=str(row.get('代码', '')),
                    name=str(row.get('名称', '')),
                    price=float(row.get('最新价', 0)),
                    change_pct=float(row.get('涨跌幅', 0)),
                    limit_days=limit_days,
                    limit_reason=str(row.get('涨停原因', row.get('所属行业', ''))),
                    sector=str(row.get('所属行业', '')),
                ))
            return stocks, total_count
        
        for attempt in range(max_attempts):
            try:
                df = await self._call_akshare_with_retry(ak.stock_zt_pool_em, date=date_str)
                
                if df is None or df.empty:
                    print(f"[连板股] 获取数据为空（日期={date_str}，尝试 {attempt+1}/{max_attempts}）")
                else:
                    stocks, total_count = parse_df(df)
                    
                    # 数据新鲜度验证：
                    # 正常交易日涨停股通常在 30-200 只之间。
                    # 若返回数据量异常少（< 5 只），且当前处于盘后窗口期，
                    # 可能是东财数据还未更新，需要重试。
                    if total_count < 5 and is_post_close_window and attempt < max_attempts - 1:
                        print(f"[连板股] 疑似数据未更新（仅 {total_count} 只涨停股，日期={date_str}），"
                              f"5分钟后重试 (第{attempt+2}次)...")
                        await asyncio.sleep(300)
                        continue
                    
                    print(f"[连板股] 获取成功：{date_str} 共 {total_count} 只涨停股，"
                          f"其中连板 {len(stocks)} 只")
                    consecutive_stocks = stocks
                    break
                    
            except Exception as e:
                print(f"获取连板强势股异常（可能非交易日）: {e}")
                break
            
            # 第一次尝试结束，不满足条件时不再循环（非盘后窗口已设 max_attempts=1）
            break
        
        return consecutive_stocks
    
    async def _get_ths_tech_stocks(self) -> List[TechSignalStock]:
        """
        从同花顺技术选股接口获取机会股
        
        调用4个现成接口：量价齐升、连续上涨、创新高、持续放量
        同一只股票出现在多个榜单 → 信号叠加，分数累加
        """
        import akshare as ak
        
        all_stocks = {}  # code -> TechSignalStock
        
        ths_apis = [
            ("stock_rank_ljqs_ths", "量价齐升", 25),
            ("stock_rank_lxsz_ths", "连续上涨", 20),
            ("stock_rank_cxg_ths",  "创新高",   20),
            ("stock_rank_cxfl_ths", "持续放量", 15),
        ]
        
        for api_name, signal_name, base_score in ths_apis:
            try:
                api_func = getattr(ak, api_name, None)
                if api_func is None:
                    print(f"  [THS技术选股] 接口 {api_name} 不存在，跳过")
                    continue
                
                df = await self._call_akshare_with_retry(api_func)
                if df is not None and not df.empty:
                    for _, row in df.head(10).iterrows():
                        code = str(row.get('股票代码', row.get('代码', '')))
                        if not code:
                            continue
                        if code in all_stocks:
                            # 同一只股票出现在多个榜单 → 信号叠加
                            all_stocks[code].signals.append(signal_name)
                            all_stocks[code].signal_score += base_score
                        else:
                            all_stocks[code] = TechSignalStock(
                                code=code,
                                name=str(row.get('股票简称', row.get('名称', ''))),
                                price=float(row.get('最新价', row.get('收盘价', 0))),
                                change_pct=float(row.get('涨跌幅', row.get('最新涨跌幅', 0))),
                                signals=[signal_name],
                                signal_score=base_score,
                                sector=str(row.get('所属行业', '')),
                                source=signal_name,
                            )
                await asyncio.sleep(2)  # 避免限流（同花顺接口间隔2秒）
            except Exception as e:
                print(f"  [THS技术选股] {signal_name} 获取失败: {e}")
        
        return list(all_stocks.values())
    
    async def _scan_tech_signals(self, target_date: date) -> List[TechSignalStock]:
        """
        自研多因子技术信号扫描
        
        Step 1: 从全A股中初筛（涨幅2-7%、量比>1.5、换手率>3%）
        Step 2: 对Top20候选股拉120日K线
        Step 3: 用 TechnicalIndicators 计算技术指标
        Step 4: 多信号打分排序
        """
        import akshare as ak
        from ..utils.indicators import TechnicalIndicators, OHLCV
        
        candidates = []
        
        # Step 1: 初筛
        try:
            df = await self._call_akshare_with_retry(ak.stock_zh_a_spot_em)
        except Exception as e:
            print(f"  [技术扫描] 获取全A股行情失败: {e}")
            return []
        
        if df is None or df.empty:
            return []
        
        try:
            # 过滤条件
            filtered = df[
                (df['涨跌幅'] >= 2) & (df['涨跌幅'] <= 7) &
                (df['量比'] > 1.5) &
                (df['换手率'] > 3) &
                (~df['名称'].str.contains('ST|退', na=False))
            ].copy()
            
            if filtered.empty:
                print("  [技术扫描] 初筛无符合条件股票")
                return []
            
            # 按 量比*涨幅 综合分排序，取Top8（减少K线请求量，避免触发反爬）
            filtered['_score'] = filtered['量比'] * filtered['涨跌幅']
            filtered = filtered.sort_values('_score', ascending=False).head(8)
            
            print(f"  [技术扫描] 初筛出 {len(filtered)} 只候选股，开始深度分析...")
        except Exception as e:
            print(f"  [技术扫描] 初筛异常: {e}")
            return []
        
        # Step 2 & 3: 逐个拉K线并计算技术指标
        for _, row in filtered.iterrows():
            code = str(row['代码'])
            name = str(row['名称'])
            try:
                # 拉120日K线
                kline_df = await self._call_akshare_with_retry(
                    ak.stock_zh_a_hist,
                    symbol=code, period="daily", adjust="qfq"
                )
                if kline_df is None or len(kline_df) < 60:
                    continue
                
                kline_df = kline_df.tail(120)
                
                # 提取价格和成交量
                closes = [float(r['收盘']) for _, r in kline_df.iterrows()]
                volumes = [float(r['成交量']) for _, r in kline_df.iterrows()]
                highs = [float(r['最高']) for _, r in kline_df.iterrows()]
                lows = [float(r['最低']) for _, r in kline_df.iterrows()]
                
                # 计算全套指标
                ma5 = TechnicalIndicators.sma(closes, 5)
                ma10 = TechnicalIndicators.sma(closes, 10)
                ma20 = TechnicalIndicators.sma(closes, 20)
                ma60 = TechnicalIndicators.sma(closes, 60)
                macd = TechnicalIndicators.macd(closes)
                kdj = TechnicalIndicators.kdj(highs, lows, closes)
                rsi = TechnicalIndicators.rsi(closes, 14)
                boll = TechnicalIndicators.bollinger_bands(closes)
                
                # Step 4: 多信号打分
                signals = []
                score = 0
                
                # 信号1: MACD金叉
                dif_list = macd['dif']
                dea_list = macd['dea']
                if (len(dif_list) >= 2 and dif_list[-1] is not None and dif_list[-2] is not None
                    and dea_list[-1] is not None and dea_list[-2] is not None):
                    if dif_list[-2] <= dea_list[-2] and dif_list[-1] > dea_list[-1]:
                        signals.append("MACD金叉")
                        score += 20
                    elif dif_list[-1] > dea_list[-1] and dif_list[-1] > 0:
                        signals.append("MACD多头")
                        score += 10
                
                # 信号2: 均线多头排列
                if all(v is not None for v in [ma5[-1], ma10[-1], ma20[-1], ma60[-1]]):
                    if ma5[-1] > ma10[-1] > ma20[-1] > ma60[-1]:
                        signals.append("均线多头排列")
                        score += 15
                    elif ma5[-1] > ma10[-1] > ma20[-1]:
                        signals.append("短中期均线多头")
                        score += 8
                
                # 信号3: 站上MA20
                if ma20[-1] is not None and ma20[-2] is not None:
                    if closes[-2] < ma20[-2] and closes[-1] > ma20[-1]:
                        signals.append("突破20日均线")
                        score += 12
                
                # 信号4: KDJ金叉
                k_vals = kdj['k']
                d_vals = kdj['d']
                j_vals = kdj['j']
                if (len(k_vals) >= 2 and k_vals[-1] is not None and k_vals[-2] is not None
                    and d_vals[-1] is not None and d_vals[-2] is not None):
                    if k_vals[-2] <= d_vals[-2] and k_vals[-1] > d_vals[-1]:
                        if j_vals[-1] is not None and j_vals[-1] < 80:
                            signals.append("KDJ金叉(非超买)")
                            score += 15
                        else:
                            signals.append("KDJ金叉")
                            score += 8
                
                # 信号5: RSI从超卖区回升
                if len(rsi) >= 2 and rsi[-1] is not None and rsi[-2] is not None:
                    if rsi[-2] < 30 and rsi[-1] >= 30:
                        signals.append("RSI超卖反弹")
                        score += 18
                    elif 40 < rsi[-1] < 70:
                        signals.append("RSI健康区间")
                        score += 5
                
                # 信号6: 布林带突破中轨
                if (boll['middle'][-1] is not None and boll['middle'][-2] is not None
                    and len(closes) >= 2):
                    if closes[-2] < boll['middle'][-2] and closes[-1] > boll['middle'][-1]:
                        signals.append("突破布林中轨")
                        score += 10
                
                # 信号7: 放量
                if len(volumes) >= 6:
                    avg_vol_5 = sum(volumes[-6:-1]) / 5
                    if avg_vol_5 > 0 and volumes[-1] > avg_vol_5 * 1.5:
                        signals.append(f"放量{volumes[-1]/avg_vol_5:.1f}倍")
                        score += 10
                
                # 信号8: 连续上涨天数
                up_days = 0
                for i in range(len(closes)-1, 0, -1):
                    if closes[i] > closes[i-1]:
                        up_days += 1
                    else:
                        break
                if up_days >= 3:
                    signals.append(f"连续{up_days}日上涨")
                    score += min(up_days * 3, 15)
                
                # 至少触发2个信号才入选
                if len(signals) >= 2:
                    candidates.append(TechSignalStock(
                        code=code,
                        name=name,
                        price=float(row['最新价']),
                        change_pct=float(row['涨跌幅']),
                        volume_ratio=float(row.get('量比', 0)),
                        turnover_rate=float(row.get('换手率', 0)),
                        signals=signals,
                        signal_score=score,
                        consecutive_up_days=up_days,
                        sector=str(row.get('所属行业', '')),
                        source="多因子扫描",
                    ))
                
                await asyncio.sleep(2)  # K线接口限流控制（每只股票间隔2秒）
                
            except Exception as e:
                print(f"  [技术扫描] {code} {name} 分析失败: {e}")
                continue
        
        # 按综合得分排序
        candidates.sort(key=lambda x: x.signal_score, reverse=True)
        print(f"  [技术扫描] 深度分析完成，{len(candidates)} 只股票入选")
        return candidates[:10]
    
    async def _get_tech_signal_stocks(self, target_date: date) -> List[TechSignalStock]:
        """
        获取技术信号机会股（合并两条路径）
        
        路径A: 同花顺现成选股接口（快速，零计算成本）
        路径B: 自研多因子扫描（深度，高质量）
        """
        # 路径A: 同花顺现成选股
        ths_stocks = await self._get_ths_tech_stocks()
        print(f"  [技术信号] 路径A（THS选股）完成，{len(ths_stocks)} 只")
        
        await asyncio.sleep(2)  # 路径切换间隔
        
        # 路径B: 自研多因子扫描
        scan_stocks = await self._scan_tech_signals(target_date)
        print(f"  [技术信号] 路径B（多因子扫描）完成，{len(scan_stocks)} 只")
        
        # 合并去重
        merged = {}
        for stock in ths_stocks + scan_stocks:
            if stock.code in merged:
                existing = merged[stock.code]
                # 合并信号
                for sig in stock.signals:
                    if sig not in existing.signals:
                        existing.signals.append(sig)
                existing.signal_score += stock.signal_score
                # 多路径共振加分
                if existing.source != stock.source:
                    existing.signal_score += 10  # 两条路径都选中 → 额外加10分
                    existing.source = f"{existing.source}+{stock.source}"
            else:
                merged[stock.code] = stock
        
        # 最终排序
        result = sorted(merged.values(), key=lambda x: x.signal_score, reverse=True)
        return result[:10]
    
    async def _get_commodities(self) -> List[CommodityData]:
        """
        获取大宗商品数据（原油、黄金、白银等）
        
        多方案兜底，兼容 AKShare 新旧版本：
        - 方案1: futures_foreign_commodity_realtime（外盘商品）
        - 方案2: futures_main_sina（新浪主力合约）
        - 方案3: index_global_em 中提取商品相关指数
        - 方案4: 硬编码"暂无数据"占位，不影响报告生成
        """
        import akshare as ak
        
        commodities = []
        
        # 方案1：获取国际大宗商品现货报价
        try:
            df = await self._call_akshare_with_retry(
                ak.futures_foreign_commodity_realtime, symbol="全部",
                use_cache=True, cache_key="commodities_foreign"
            )
            if df is not None and not df.empty:
                target_commodities = {
                    "WTI原油": {"keywords": ["WTI", "原油", "Crude"], "unit": "美元/桶"},
                    "布伦特原油": {"keywords": ["布伦特", "Brent"], "unit": "美元/桶"},
                    "现货黄金": {"keywords": ["黄金", "Gold", "XAUUSD"], "unit": "美元/盎司"},
                    "现货白银": {"keywords": ["白银", "Silver", "XAGUSD"], "unit": "美元/盎司"},
                    "COMEX铜": {"keywords": ["铜", "Copper"], "unit": "美元/磅"},
                }
                
                for comm_name, config in target_commodities.items():
                    for _, row in df.iterrows():
                        name_col = str(row.iloc[0]) if len(row) > 0 else ""
                        if any(kw in name_col for kw in config["keywords"]):
                            try:
                                # 自适应列名（兼容不同版本）
                                price = 0
                                change_pct = 0
                                for col in df.columns:
                                    col_str = str(col)
                                    if '最新' in col_str or 'price' in col_str.lower() or 'current' in col_str.lower():
                                        price = float(row[col]) if row[col] else 0
                                    if '涨跌幅' in col_str or 'change' in col_str.lower() or 'percent' in col_str.lower():
                                        change_pct = float(row[col]) if row[col] else 0
                                
                                if price > 0:
                                    commodities.append(CommodityData(
                                        name=comm_name, price=price,
                                        change_pct=change_pct, unit=config["unit"]
                                    ))
                                    break
                            except (ValueError, TypeError):
                                continue
                
                if commodities:
                    print(f"  [大宗商品] 方案1获取成功: {len(commodities)} 个品种")
                    return commodities
        except Exception as e:
            print(f"  [大宗商品] 方案1失败: {e}")
        
        # 方案2：通过新浪期货主力合约获取国内商品
        try:
            # 使用 futures_main_sina 获取国内期货主力合约
            sina_contracts = {
                "AU0": {"name": "沪金（黄金期货）", "unit": "元/克"},
                "AG0": {"name": "沪银（白银期货）", "unit": "元/千克"},
                "SC0": {"name": "原油期货（INE）", "unit": "元/桶"},
                "CU0": {"name": "沪铜期货", "unit": "元/吨"},
                "I0": {"name": "铁矿石期货", "unit": "元/吨"},
            }
            
            for symbol, config in sina_contracts.items():
                try:
                    df = await self._call_akshare_with_retry(
                        ak.futures_main_sina, symbol=symbol, start_date="20260401",
                        max_retries=1, use_cache=True, cache_key=f"commodity_sina_{symbol}"
                    )
                    if df is not None and not df.empty:
                        row = df.iloc[-1]
                        close = float(row.get('收盘价', row.get('close', 0)))
                        # 计算涨跌幅
                        if len(df) >= 2:
                            prev_close = float(df.iloc[-2].get('收盘价', df.iloc[-2].get('close', 0)))
                            change_pct = ((close - prev_close) / prev_close * 100) if prev_close > 0 else 0
                        else:
                            change_pct = 0
                        
                        if close > 0:
                            commodities.append(CommodityData(
                                name=config["name"], price=close,
                                change_pct=round(change_pct, 2), unit=config["unit"]
                            ))
                except Exception:
                    continue
            
            if commodities:
                print(f"  [大宗商品] 方案2获取成功: {len(commodities)} 个品种")
                return commodities
        except Exception as e:
            print(f"  [大宗商品] 方案2失败: {e}")
        
        # 方案3：尝试从全球指数接口中提取商品相关数据
        try:
            df = await self._call_akshare_with_retry(
                ak.index_global_em,
                max_retries=1, use_cache=True, cache_key="index_global_for_commodities"
            )
            if df is not None and not df.empty:
                commodity_indices = {
                    "COMEX黄金": {"keywords": ["黄金", "Gold"], "unit": "美元/盎司"},
                    "WTI原油": {"keywords": ["原油", "WTI", "Oil"], "unit": "美元/桶"},
                }
                for comm_name, config in commodity_indices.items():
                    for _, row in df.iterrows():
                        name_col = str(row.get('名称', ''))
                        if any(kw in name_col for kw in config["keywords"]):
                            try:
                                price = float(row.get('最新价', 0))
                                change_pct = float(row.get('涨跌幅', 0))
                                if price > 0:
                                    commodities.append(CommodityData(
                                        name=comm_name, price=price,
                                        change_pct=change_pct, unit=config["unit"]
                                    ))
                                    break
                            except (ValueError, TypeError):
                                continue
                
                if commodities:
                    print(f"  [大宗商品] 方案3获取成功: {len(commodities)} 个品种")
        except Exception as e:
            print(f"  [大宗商品] 方案3失败: {e}")
        
        if not commodities:
            print("  [大宗商品] 所有方案均失败，本次无大宗商品数据")
        
        return commodities
    
    async def _get_global_indices(self) -> List[GlobalIndexData]:
        """
        获取全球主要指数（外盘）（3层备用）
        
        方案1: AKShare → index_global_em（全球指数）
        方案2: AKShare → 分别获取美股(新浪) + 港股(东方财富)
        方案3: 新浪 HTTP 直连 hq.sinajs.cn（最稳定，支持全球指数）
        """
        import akshare as ak
        
        global_indices = []
        
        # 方案1：获取全球指数实时行情（AKShare）
        try:
            df = await self._call_akshare_with_retry(ak.index_global_em)
            if df is not None and not df.empty:
                target_indices = {
                    "道琼斯": {"keywords": ["道琼斯", "Dow Jones", "DJI"], "region": "美股"},
                    "纳斯达克": {"keywords": ["纳斯达克", "NASDAQ", "纳指"], "region": "美股"},
                    "标普500": {"keywords": ["标普500", "S&P 500", "标普"], "region": "美股"},
                    "恒生指数": {"keywords": ["恒生指数", "HSI", "恒指"], "region": "港股"},
                    "国企指数": {"keywords": ["国企指数", "H股指数"], "region": "港股"},
                    "日经225": {"keywords": ["日经225", "日经", "Nikkei"], "region": "亚太"},
                    "韩国综合": {"keywords": ["韩国综合", "KOSPI"], "region": "亚太"},
                    "英国富时100": {"keywords": ["富时100", "FTSE", "英国"], "region": "欧洲"},
                    "德国DAX": {"keywords": ["DAX", "德国"], "region": "欧洲"},
                    "法国CAC40": {"keywords": ["CAC", "法国"], "region": "欧洲"},
                }
                
                for idx_name, config in target_indices.items():
                    for _, row in df.iterrows():
                        name_col = str(row.get('名称', ''))
                        if any(kw in name_col for kw in config["keywords"]):
                            try:
                                current = float(row.get('最新价', 0))
                                change_pct = float(row.get('涨跌幅', 0))
                                if current > 0:
                                    global_indices.append(GlobalIndexData(
                                        name=idx_name,
                                        current=current,
                                        change_pct=change_pct,
                                        region=config["region"]
                                    ))
                                    break
                            except (ValueError, TypeError):
                                continue
                
                if global_indices:
                    print(f"  [外盘指数] 方案1获取成功: {len(global_indices)} 个指数")
                    return global_indices
        except Exception as e:
            print(f"  [外盘指数] 方案1失败: {e}")
        
        # 方案2：AKShare 分别获取美股和港股
        try:
            try:
                df_us = await self._call_akshare_with_retry(ak.index_us_stock_sina)
                if df_us is not None and not df_us.empty:
                    us_targets = {
                        ".DJI": ("道琼斯", "美股"),
                        ".IXIC": ("纳斯达克", "美股"),
                        ".INX": ("标普500", "美股"),
                    }
                    for _, row in df_us.iterrows():
                        code = str(row.get('代码', row.get('code', '')))
                        if code in us_targets:
                            name, region = us_targets[code]
                            try:
                                current = float(row.get('最新价', row.get('current', 0)))
                                change_pct = float(row.get('涨跌幅', row.get('change_percent', 0)))
                                if current > 0:
                                    global_indices.append(GlobalIndexData(
                                        name=name, current=current,
                                        change_pct=change_pct, region=region
                                    ))
                            except (ValueError, TypeError):
                                continue
            except Exception as e:
                print(f"  [外盘] 美股指数获取失败: {e}")
            
            await asyncio.sleep(1)
            
            try:
                df_hk = await self._call_akshare_with_retry(ak.stock_hk_index_spot_em)
                if df_hk is not None and not df_hk.empty:
                    hk_targets = {
                        "恒生指数": "港股",
                        "国企指数": "港股",
                        "恒生科技指数": "港股",
                    }
                    for _, row in df_hk.iterrows():
                        name_col = str(row.get('名称', ''))
                        for target_name, region in hk_targets.items():
                            if target_name in name_col:
                                try:
                                    current = float(row.get('最新价', 0))
                                    change_pct = float(row.get('涨跌幅', 0))
                                    if current > 0:
                                        global_indices.append(GlobalIndexData(
                                            name=target_name, current=current,
                                            change_pct=change_pct, region=region
                                        ))
                                except (ValueError, TypeError):
                                    continue
            except Exception as e:
                print(f"  [外盘] 港股指数获取失败: {e}")
            
            if global_indices:
                print(f"  [外盘指数] 方案2获取成功: {len(global_indices)} 个指数")
                return global_indices
        except Exception as e:
            print(f"  [外盘指数] 方案2失败: {e}")
        
        # 方案3：新浪 HTTP 直连（最稳定的全球指数源）
        try:
            global_indices = await self._fetch_global_indices_sina_http()
            if global_indices:
                print(f"  [外盘指数] 方案3（新浪HTTP直连）获取成功: {len(global_indices)} 个指数")
                return global_indices
        except Exception as e:
            print(f"  [外盘指数] 方案3（新浪HTTP直连）失败: {e}")
        
        print("  [外盘指数] ⚠️ 所有3个方案均失败！")
        return global_indices
    
    async def _fetch_global_indices_sina_http(self) -> List[GlobalIndexData]:
        """
        新浪 HTTP 直连获取全球主要指数
        
        使用 hq.sinajs.cn 接口，格式和A股类似，支持全球指数代码：
        - int_dji=道琼斯, int_nasdaq=纳斯达克, int_sp500=标普500
        - int_hangseng=恒生指数, int_hscei=国企指数
        - int_nikkei=日经225
        - b_FSSTI=富时100, b_DAX=德国DAX, b_FCHI=法国CAC40
        """
        import urllib.request
        import ssl
        
        # 新浪全球指数代码映射
        sina_global = {
            "int_dji": ("道琼斯", "美股"),
            "int_nasdaq": ("纳斯达克", "美股"),
            "int_sp500": ("标普500", "美股"),
            "int_hangseng": ("恒生指数", "港股"),
            "int_hscei": ("国企指数", "港股"),
            "int_nikkei": ("日经225", "亚太"),
            "b_FSSTI": ("英国富时100", "欧洲"),
            "b_DAX": ("德国DAX", "欧洲"),
            "b_FCHI": ("法国CAC40", "欧洲"),
        }
        
        symbols = ",".join(sina_global.keys())
        url = f"https://hq.sinajs.cn/list={symbols}"
        
        def _do_request():
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            req.add_header('Referer', 'https://finance.sina.com.cn')
            
            with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
                return response.read().decode('gbk')
        
        loop = asyncio.get_event_loop()
        content = await asyncio.wait_for(
            loop.run_in_executor(None, _do_request),
            timeout=15
        )
        
        global_indices = []
        for line in content.strip().split('\n'):
            if '=' not in line or '"' not in line:
                continue
            
            # 格式: var hq_str_int_dji="道琼斯,43241.11,...";
            var_part = line.split('=')[0].strip()
            # 提取符号名
            symbol = ""
            for key in sina_global.keys():
                if key in var_part:
                    symbol = key
                    break
            
            if not symbol:
                continue
            
            data_str = line.split('"')[1] if '"' in line else ""
            if not data_str:
                continue
            
            name, region = sina_global[symbol]
            parts = data_str.split(',')
            
            try:
                # 新浪国际指数格式因指数不同略有差异
                # 通用格式: 名称,当前价,涨跌点数,涨跌幅,...
                current = 0
                change_pct = 0
                
                if symbol.startswith("int_"):
                    # int_ 系列：名称,当前价,涨跌点,涨跌幅,...
                    if len(parts) >= 2:
                        current = float(parts[1]) if parts[1] else 0
                    if len(parts) >= 4:
                        try:
                            pct_str = parts[3].replace('%', '').strip()
                            change_pct = float(pct_str) if pct_str else 0
                        except ValueError:
                            pass
                    # 如果涨跌幅没拿到，手动算
                    if change_pct == 0 and current > 0 and len(parts) >= 3:
                        try:
                            change_val = float(parts[2]) if parts[2] else 0
                            prev = current - change_val
                            if prev > 0:
                                change_pct = (change_val / prev) * 100
                        except ValueError:
                            pass
                elif symbol.startswith("b_"):
                    # b_ 系列（欧洲等）：名称,当前价,...
                    if len(parts) >= 2:
                        current = float(parts[1]) if parts[1] else 0
                    if len(parts) >= 3:
                        try:
                            change_pct = float(parts[2]) if parts[2] else 0
                        except ValueError:
                            pass
                
                if current > 0:
                    global_indices.append(GlobalIndexData(
                        name=name,
                        current=current,
                        change_pct=round(change_pct, 2),
                        region=region
                    ))
            except (ValueError, IndexError) as e:
                print(f"  [新浪外盘] 解析 {symbol} 失败: {e}")
        
        return global_indices
    
    async def _get_lhb_seats(self, target_date: date) -> List[LHBSeatData]:
        """
        获取龙虎榜席位明细（聪明钱追踪）（2层备用）
        
        方案1: AKShare（兼容多版本参数格式）
        方案2: 东方财富 datacenter HTTP 直连
        """
        import akshare as ak
        
        seats = []
        date_str = target_date.strftime("%Y%m%d")
        date_str_dash = target_date.strftime("%Y-%m-%d")
        
        # 知名游资席位关键词
        famous_traders = [
            "赵老哥", "炒股养家", "章盟主", "小鳄鱼",
            "佛山无影脚", "作手新一", "深股通", "沪股通",
            "华鑫证券上海宛平南路",
            "国泰君安上海江苏路",
            "华泰证券深圳益田路",
            "中信证券上海溧阳路",
            "东方财富拉萨",
            "西藏东方财富",
        ]
        
        def _classify_seat(seat_name: str) -> tuple:
            """分类席位：返回 (is_institution, seat_type)"""
            is_institution = "机构" in seat_name or "专用" in seat_name
            seat_type = "机构" if is_institution else "普通营业部"
            for trader_kw in famous_traders:
                if trader_kw in seat_name:
                    seat_type = "知名游资"
                    break
            return is_institution, seat_type
        
        # 方案1：AKShare（兼容多版本参数格式）
        try:
            df = None
            param_variants = [
                {"start_date": date_str, "end_date": date_str},
                {"start_date": date_str_dash, "end_date": date_str_dash},
                {"date": date_str},
                {"date": date_str_dash},
            ]
            
            for params in param_variants:
                try:
                    df = await self._call_akshare_with_retry(
                        ak.stock_lhb_detail_em, max_retries=1, **params
                    )
                    if df is not None and not df.empty:
                        break
                    df = None
                except (TypeError, ValueError):
                    df = None
                    continue
                except Exception:
                    df = None
                    continue
            
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    seat_name = str(row.get('营业部名称', row.get('买方营业部', '')))
                    buy_amount = float(row.get('买入金额', row.get('买入额', 0))) / 10000
                    sell_amount = float(row.get('卖出金额', row.get('卖出额', 0))) / 10000
                    
                    is_institution, seat_type = _classify_seat(seat_name)
                    
                    seats.append(LHBSeatData(
                        stock_code=str(row.get('代码', '')),
                        stock_name=str(row.get('名称', '')),
                        seat_name=seat_name,
                        buy_amount=buy_amount,
                        sell_amount=sell_amount,
                        net_amount=buy_amount - sell_amount,
                        is_institution=is_institution,
                        seat_type=seat_type,
                        reason=str(row.get('上榜原因', '异动'))
                    ))
                
                if seats:
                    print(f"  [龙虎榜席位] 方案1（AKShare）共解析 {len(seats)} 条，"
                          f"机构 {sum(1 for s in seats if s.is_institution)} 条，"
                          f"知名游资 {sum(1 for s in seats if s.seat_type == '知名游资')} 条")
                    return seats
        except Exception as e:
            print(f"  [龙虎榜席位] 方案1（AKShare）失败: {e}")
        
        # 方案2：东方财富 datacenter HTTP 直连
        try:
            seats = await self._fetch_lhb_seats_eastmoney_http(date_str_dash, _classify_seat)
            if seats:
                print(f"  [龙虎榜席位] 方案2（东方财富HTTP）共解析 {len(seats)} 条")
                return seats
        except Exception as e:
            print(f"  [龙虎榜席位] 方案2（东方财富HTTP）失败: {e}")
        
        print(f"  [龙虎榜席位] {date_str} 所有方案均失败（可能非交易日）")
        return seats
    
    async def _fetch_lhb_seats_eastmoney_http(self, date_str_dash: str, classify_fn) -> List[LHBSeatData]:
        """
        东方财富 datacenter HTTP 直连获取龙虎榜席位明细
        """
        import urllib.request
        import ssl
        import json
        
        url = (
            f"https://datacenter-web.eastmoney.com/api/data/v1/get?"
            f"sortColumns=SECURITY_CODE&sortTypes=1&pageSize=200&pageNumber=1&"
            f"reportName=RPT_BILLBOARD_DAILYDETAILSBUY&"
            f"columns=ALL&"
            f"filter=(TRADE_DATE%3D%27{date_str_dash}%27)"
        )
        
        def _do_request():
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            req.add_header('Referer', 'https://data.eastmoney.com/')
            
            with urllib.request.urlopen(req, timeout=15, context=ctx) as response:
                return json.loads(response.read().decode('utf-8'))
        
        loop = asyncio.get_event_loop()
        data = await asyncio.wait_for(
            loop.run_in_executor(None, _do_request),
            timeout=20
        )
        
        seats = []
        result_data = data.get("result", {})
        if not result_data:
            return seats
        
        items = result_data.get("data", []) or []
        
        for item in items:
            seat_name = str(item.get('OPERATEDEPT_NAME', '') or '')
            buy_amount = float(item.get('BUY', 0) or 0) / 10000  # 转万元
            sell_amount = float(item.get('SELL', 0) or 0) / 10000
            
            is_institution, seat_type = classify_fn(seat_name)
            
            seats.append(LHBSeatData(
                stock_code=str(item.get('SECURITY_CODE', '')),
                stock_name=str(item.get('SECURITY_NAME_ABBR', '')),
                seat_name=seat_name,
                buy_amount=buy_amount,
                sell_amount=sell_amount,
                net_amount=buy_amount - sell_amount,
                is_institution=is_institution,
                seat_type=seat_type,
                reason=str(item.get('EXPLANATION', '异动'))
            ))
        
        return seats
    
    async def _get_block_trades(self, target_date: date) -> List[BlockTradeData]:
        """
        获取大宗交易数据
        
        关注：
        - 大幅折价交易（可能有减持压力）
        - 溢价交易（机构看好信号）
        - 连续大宗买入的股票
        """
        import akshare as ak
        
        trades = []
        date_str = target_date.strftime("%Y%m%d")
        date_str_dash = target_date.strftime("%Y-%m-%d")
        
        try:
            # 方案1：获取大宗交易每日统计（兼容多种参数格式）
            try:
                df = None
                for params in [
                    {"start_date": date_str, "end_date": date_str},
                    {"start_date": date_str_dash, "end_date": date_str_dash},
                ]:
                    try:
                        df = await self._call_akshare_with_retry(
                            ak.stock_dzjy_sctj, max_retries=1, **params
                        )
                        if df is not None and not df.empty:
                            break
                        df = None
                    except TypeError:
                        df = None
                        continue
                
                # 如果带参数都失败，尝试无参数调用（部分版本不需要日期）
                if df is None:
                    try:
                        df = await self._call_akshare_with_retry(
                            ak.stock_dzjy_sctj, max_retries=1
                        )
                    except Exception:
                        df = None
                if df is not None and not df.empty:
                    for _, row in df.iterrows():
                        try:
                            close_price = float(row.get('收盘价', 0))
                            trade_price = float(row.get('成交价', row.get('加权平均价', 0)))
                            
                            # 计算折价率
                            discount_rate = 0
                            if close_price > 0 and trade_price > 0:
                                discount_rate = (trade_price - close_price) / close_price * 100
                            
                            trades.append(BlockTradeData(
                                code=str(row.get('证券代码', row.get('代码', ''))),
                                name=str(row.get('证券简称', row.get('名称', ''))),
                                price=trade_price,
                                close_price=close_price,
                                discount_rate=round(discount_rate, 2),
                                volume=float(row.get('成交量', 0)) / 10000,  # 转万股
                                amount=float(row.get('成交金额', row.get('成交总额', 0))) / 10000,  # 转万元
                            ))
                        except (ValueError, TypeError):
                            continue
                    
                    if trades:
                        print(f"  [大宗交易] 方案1获取成功: {len(trades)} 笔交易")
                        return trades
            except Exception as e:
                print(f"  [大宗交易] 方案1失败: {e}")
            
            # 方案2：获取大宗交易明细
            try:
                df = await self._call_akshare_with_retry(
                    ak.stock_dzjy_mrmx, symbol="A股", start_date=date_str, end_date=date_str
                )
                if df is not None and not df.empty:
                    for _, row in df.iterrows():
                        try:
                            close_price = float(row.get('收盘价', 0))
                            trade_price = float(row.get('成交价', 0))
                            
                            discount_rate = 0
                            if close_price > 0 and trade_price > 0:
                                discount_rate = (trade_price - close_price) / close_price * 100
                            
                            trades.append(BlockTradeData(
                                code=str(row.get('证券代码', row.get('代码', ''))),
                                name=str(row.get('证券简称', row.get('名称', ''))),
                                price=trade_price,
                                close_price=close_price,
                                discount_rate=round(discount_rate, 2),
                                volume=float(row.get('成交量', 0)) / 10000,
                                amount=float(row.get('成交额', row.get('成交金额', 0))) / 10000,
                                buyer_seat=str(row.get('买方营业部', '')),
                                seller_seat=str(row.get('卖方营业部', '')),
                            ))
                        except (ValueError, TypeError):
                            continue
                    
                    if trades:
                        print(f"  [大宗交易] 方案2获取成功: {len(trades)} 笔交易")
            except Exception as e:
                print(f"  [大宗交易] 方案2也失败: {e}")
        except Exception as e:
            print(f"获取大宗交易异常: {e}")
        
        return trades
    
    async def _get_margin_trading(self, target_date: date) -> Optional[MarginTradingData]:
        """
        获取融资融券数据（兼容 AKShare 新旧版本参数格式）
        """
        import akshare as ak
        
        date_str = target_date.strftime("%Y%m%d")
        date_str_dash = target_date.strftime("%Y-%m-%d")
        
        try:
            # 方案1：获取融资融券汇总数据（兼容多种参数格式）
            df = None
            for params in [
                {"start_date": date_str, "end_date": date_str},
                {"start_date": date_str_dash, "end_date": date_str_dash},
                {"date": date_str},
            ]:
                try:
                    df = await self._call_akshare_with_retry(
                        ak.stock_margin_sse, max_retries=1, **params
                    )
                    if df is not None and not df.empty:
                        break
                    df = None
                except (TypeError, ValueError):
                    df = None
                    continue
                except Exception:
                    df = None
                    continue
            
            if df is not None and not df.empty:
                row = df.iloc[-1]
                
                # 自适应列名
                margin_balance = 0
                margin_buy = 0
                short_balance = 0
                for col in df.columns:
                    col_str = str(col)
                    if '融资余额' in col_str and '买' not in col_str:
                        margin_balance = float(row[col]) / 100000000
                    elif '融资买入' in col_str:
                        margin_buy = float(row[col]) / 100000000
                    elif '融券余额' in col_str:
                        short_balance = float(row[col]) / 100000000
                
                margin_change = 0
                short_change = 0
                if len(df) >= 2:
                    prev_row = df.iloc[-2]
                    for col in df.columns:
                        col_str = str(col)
                        if '融资余额' in col_str and '买' not in col_str:
                            prev_margin = float(prev_row[col]) / 100000000
                            margin_change = margin_balance - prev_margin
                        elif '融券余额' in col_str:
                            prev_short = float(prev_row[col]) / 100000000
                            short_change = short_balance - prev_short
                
                if margin_balance > 0:
                    result = MarginTradingData(
                        total_margin_balance=margin_balance,
                        margin_buy_amount=margin_buy,
                        total_short_balance=short_balance,
                        margin_balance_change=margin_change,
                        short_balance_change=short_change,
                    )
                    print(f"  [融资融券] 方案1获取成功: 融资余额{margin_balance:.0f}亿")
                    return result
            
            print(f"  [融资融券] 方案1无有效数据")
            
            # 方案2：获取深交所融资融券数据（兼容参数格式）
            df2 = None
            for params in [
                {"date": date_str},
                {"date": date_str_dash},
            ]:
                try:
                    df2 = await self._call_akshare_with_retry(
                        ak.stock_margin_underlying_info_szse, max_retries=1, **params
                    )
                    if df2 is not None and not df2.empty:
                        break
                    df2 = None
                except (TypeError, ValueError):
                    df2 = None
                    continue
                except Exception:
                    df2 = None
                    continue
            
            if df2 is not None and not df2.empty:
                total_margin = 0
                total_margin_buy = 0
                total_short = 0
                for col in df2.columns:
                    col_str = str(col)
                    if '融资余额' in col_str and '买' not in col_str:
                        total_margin = df2[col].sum() / 100000000
                    elif '融资买入' in col_str:
                        total_margin_buy = df2[col].sum() / 100000000
                    elif '融券余额' in col_str:
                        total_short = df2[col].sum() / 100000000
                
                top_stocks = []
                margin_col = next((c for c in df2.columns if '融资余额' in str(c) and '买' not in str(c)), None)
                if margin_col:
                    top_df = df2.nlargest(10, margin_col)
                    code_col = next((c for c in df2.columns if '代码' in str(c)), None)
                    name_col = next((c for c in df2.columns if '简称' in str(c) or '名称' in str(c)), None)
                    if code_col and name_col:
                        for _, r in top_df.iterrows():
                            top_stocks.append({
                                "code": str(r[code_col]),
                                "name": str(r[name_col]),
                                "balance": float(r[margin_col]) / 100000000,
                                "change": 0,
                            })
                
                if total_margin > 0:
                    result = MarginTradingData(
                        total_margin_balance=total_margin,
                        margin_buy_amount=total_margin_buy,
                        total_short_balance=total_short,
                        top_margin_stocks=top_stocks,
                    )
                    print(f"  [融资融券] 方案2获取成功: 融资余额{total_margin:.0f}亿，Top股票{len(top_stocks)}只")
                    return result
            
            print(f"  [融资融券] 方案2也无有效数据")
                
        except Exception as e:
            print(f"获取融资融券异常: {e}")
        
        return None
    
    def _calculate_sentiment(self, overview: MarketOverview) -> str:
        """根据数据计算市场情绪"""
        sentiments = []
        
        # 根据指数涨跌
        if overview.indices:
            sh_index = next((i for i in overview.indices if i.code == "000001"), None)
            if sh_index:
                if sh_index.change_pct > 1:
                    sentiments.append("大盘强势上涨")
                elif sh_index.change_pct > 0:
                    sentiments.append("大盘小幅收涨")
                elif sh_index.change_pct > -1:
                    sentiments.append("大盘小幅收跌")
                else:
                    sentiments.append("大盘明显下跌")
        
        # 根据涨跌家数
        if overview.up_count and overview.down_count:
            total = overview.up_count + overview.down_count
            up_ratio = overview.up_count / total
            if up_ratio > 0.7:
                sentiments.append("普涨格局，赚钱效应强")
            elif up_ratio > 0.5:
                sentiments.append("多数个股上涨")
            elif up_ratio > 0.3:
                sentiments.append("多数个股下跌")
            else:
                sentiments.append("普跌格局，亏钱效应明显")
        
        # 根据资金流向
        if overview.fund_flow:
            if overview.fund_flow.main_net_inflow > 50:
                sentiments.append("主力资金大幅流入")
            elif overview.fund_flow.main_net_inflow > 0:
                sentiments.append("主力资金小幅流入")
            elif overview.fund_flow.main_net_inflow > -50:
                sentiments.append("主力资金小幅流出")
            else:
                sentiments.append("主力资金大幅流出")
        
        # 根据涨跌停
        if overview.limit_data:
            if overview.limit_data.up_limit_count > 100:
                sentiments.append("涨停潮，市场情绪高涨")
            elif overview.limit_data.up_limit_count > 50:
                sentiments.append("涨停家数较多")
            
            if overview.limit_data.down_limit_count > 50:
                sentiments.append("跌停家数偏多，注意风险")
        
        return "；".join(sentiments) if sentiments else "市场表现平稳"


# 单例实例
_market_data_service: Optional[MarketDataService] = None


def get_market_data_service() -> MarketDataService:
    """获取市场数据服务实例"""
    global _market_data_service
    if _market_data_service is None:
        _market_data_service = MarketDataService()
    return _market_data_service

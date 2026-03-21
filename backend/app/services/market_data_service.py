"""
市场数据采集服务
使用 AKShare 获取 A股市场全面数据，为 AI 报告生成提供真实数据支撑
"""
import asyncio
from datetime import datetime, date
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
import traceback


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
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return asdict(self)
    
    def to_prompt_text(self) -> str:
        """转换为 AI Prompt 使用的文本格式"""
        lines = []
        lines.append(f"## 📊 市场数据（{self.date}）\n")
        
        # 1. 大盘指数
        if self.indices:
            lines.append("### 主要指数")
            for idx in self.indices:
                trend = "📈" if idx.change_pct > 0 else ("📉" if idx.change_pct < 0 else "➡️")
                lines.append(f"- {idx.name}：{idx.current:.2f} {trend} {idx.change_pct:+.2f}%（成交额 {idx.amount/100000000:.0f}亿）")
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
            print("⚠️ AKShare 不可用，返回空数据")
            return overview
        
        # 串行获取各类数据，每次间隔 1 秒，避免触发数据源限流/反爬
        task_configs = [
            ("指数", self._get_indices),
            ("板块排行", self._get_sector_ranking),
            ("资金流向", self._get_fund_flow),
            ("涨跌停", lambda: self._get_limit_stocks(target_date)),
            ("市场统计", self._get_market_stats),
            ("热门股票", lambda: self._get_hot_stocks(target_date)),
        ]
        
        results = []
        for name, task_func in task_configs:
            try:
                result = await task_func()
                results.append(result)
                print(f"  [OK] {name} 获取成功")
            except Exception as e:
                results.append(e)
                print(f"  [FAIL] {name} 获取失败: {e}")
            await asyncio.sleep(1)  # 间隔 1 秒，避免限流
        
        # 处理结果
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
        
        # 计算市场情绪
        overview.market_sentiment = self._calculate_sentiment(overview)
        
        return overview
    
    async def _get_indices(self) -> List[IndexData]:
        """获取主要指数数据"""
        import akshare as ak
        
        indices = []
        
        try:
            # 获取 A股主要指数实时行情
            df = ak.stock_zh_index_spot_em()
            
            # 筛选主要指数
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
        except Exception as e:
            print(f"获取指数数据异常: {e}")
            traceback.print_exc()
        
        return indices
    
    async def _get_sector_ranking(self) -> tuple:
        """获取板块涨跌排行"""
        import akshare as ak
        
        top_sectors = []
        bottom_sectors = []
        
        try:
            # 获取行业板块行情
            df = ak.stock_board_industry_name_em()
            
            if df is not None and not df.empty:
                # 按涨跌幅排序
                df_sorted = df.sort_values('涨跌幅', ascending=False)
                
                # 涨幅前5
                for _, row in df_sorted.head(5).iterrows():
                    top_sectors.append(SectorData(
                        name=row['板块名称'],
                        change_pct=float(row['涨跌幅']),
                        leader_stock=str(row.get('领涨股票', '')),
                        leader_change=float(row.get('领涨股票-涨跌幅', 0)),
                    ))
                
                # 跌幅前5
                for _, row in df_sorted.tail(5).iterrows():
                    bottom_sectors.append(SectorData(
                        name=row['板块名称'],
                        change_pct=float(row['涨跌幅']),
                    ))
                    
        except Exception as e:
            print(f"获取板块排行异常: {e}")
            traceback.print_exc()
        
        return top_sectors, bottom_sectors
    
    async def _get_fund_flow(self) -> Optional[FundFlowData]:
        """获取大盘资金流向"""
        import akshare as ak
        
        try:
            # 获取大盘资金流向
            df = ak.stock_market_fund_flow()
            
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
                df_up = ak.stock_zt_pool_em(date=date_str)
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
                df_down = ak.stock_zt_pool_dtgc_em(date=date_str)
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
        """获取市场涨跌统计"""
        import akshare as ak
        
        stats = {"up": 0, "down": 0, "flat": 0, "total_volume": 0}
        
        try:
            # 获取所有 A股实时行情
            df = ak.stock_zh_a_spot_em()
            
            if df is not None and not df.empty:
                # 统计涨跌
                stats["up"] = len(df[df['涨跌幅'] > 0])
                stats["down"] = len(df[df['涨跌幅'] < 0])
                stats["flat"] = len(df[df['涨跌幅'] == 0])
                
                # 计算总成交额（亿元）
                total_amount = df['成交额'].sum()
                stats["total_volume"] = total_amount / 100000000
                
        except Exception as e:
            print(f"获取市场统计异常: {e}")
        
        return stats
    
    async def _get_hot_stocks(self, target_date: date) -> List[HotStockData]:
        """获取热门股票（龙虎榜等）"""
        import akshare as ak
        
        hot_stocks = []
        date_str = target_date.strftime("%Y%m%d")
        
        try:
            # 尝试获取龙虎榜数据
            try:
                df = ak.stock_lhb_detail_em(start_date=date_str, end_date=date_str)
                if df is not None and not df.empty:
                    # 去重，保留每只股票第一条
                    df_unique = df.drop_duplicates(subset=['代码'], keep='first')
                    
                    for _, row in df_unique.head(10).iterrows():
                        hot_stocks.append(HotStockData(
                            code=row['代码'],
                            name=row['名称'],
                            price=float(row.get('收盘价', 0)),
                            change_pct=float(row.get('涨跌幅', 0)),
                            reason=f"龙虎榜：{row.get('上榜原因', '异动')}"
                        ))
            except Exception as e:
                print(f"获取龙虎榜异常（可能无数据）: {e}")
            
            # 如果龙虎榜没数据，获取换手率最高的股票
            if not hot_stocks:
                try:
                    df = ak.stock_zh_a_spot_em()
                    if df is not None and not df.empty:
                        # 按换手率排序
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
                except:
                    pass
                    
        except Exception as e:
            print(f"获取热门股票异常: {e}")
        
        return hot_stocks
    
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

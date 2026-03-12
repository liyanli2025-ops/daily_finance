"""
股票数据服务
获取 A股、港股行情数据和计算技术指标
"""
import asyncio
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from ..config import settings
from ..models.stock import (
    Stock, StockQuote, KlineData, 
    FundamentalData, TechnicalData, MarketType
)
from ..utils.indicators import TechnicalIndicators, OHLCV


class StockDataService:
    """股票数据服务"""
    
    def __init__(self):
        self.tushare_api = None
        self.akshare_available = False
        self._init_data_sources()
    
    def _init_data_sources(self):
        """初始化数据源"""
        # 尝试初始化 Tushare（需要 token）
        if settings.tushare_token:
            try:
                import tushare as ts
                ts.set_token(settings.tushare_token)
                self.tushare_api = ts.pro_api()
                print("✅ Tushare 初始化成功")
            except Exception as e:
                print(f"⚠️ Tushare 初始化失败: {e}")
        
        # 检查 AKShare 是否可用（免费，无需 token）
        try:
            import akshare
            self.akshare_available = True
            print("✅ AKShare 可用")
        except ImportError:
            print("⚠️ AKShare 不可用")
    
    async def get_stock_quote(self, code: str, market: MarketType) -> Optional[StockQuote]:
        """
        获取股票实时行情
        
        Args:
            code: 股票代码
            market: 市场类型
            
        Returns:
            实时行情数据
        """
        if market == MarketType.A_SHARE:
            return await self._get_a_share_quote(code)
        else:
            return await self._get_hk_stock_quote(code)
    
    async def _get_a_share_quote(self, code: str) -> Optional[StockQuote]:
        """获取 A股实时行情"""
        if self.akshare_available:
            try:
                import akshare as ak
                
                # 使用腾讯接口获取实时行情
                df = ak.stock_zh_a_spot_em()
                
                # 查找指定股票
                stock_data = df[df['代码'] == code]
                
                if stock_data.empty:
                    return None
                
                row = stock_data.iloc[0]
                
                return StockQuote(
                    code=code,
                    name=row['名称'],
                    current_price=float(row['最新价']),
                    open_price=float(row['今开']),
                    high_price=float(row['最高']),
                    low_price=float(row['最低']),
                    prev_close=float(row['昨收']),
                    change=float(row['涨跌额']),
                    change_percent=float(row['涨跌幅']),
                    volume=float(row['成交量']),
                    amount=float(row['成交额']),
                    update_time=datetime.now()
                )
            except Exception as e:
                print(f"获取 A股行情失败: {e}")
        
        # 返回模拟数据
        return self._mock_quote(code, "模拟A股")
    
    async def _get_hk_stock_quote(self, code: str) -> Optional[StockQuote]:
        """获取港股实时行情"""
        if self.akshare_available:
            try:
                import akshare as ak
                
                # 港股实时行情
                df = ak.stock_hk_spot_em()
                
                # 查找指定股票（港股代码可能需要补0）
                code_padded = code.zfill(5)
                stock_data = df[df['代码'] == code_padded]
                
                if stock_data.empty:
                    return None
                
                row = stock_data.iloc[0]
                
                return StockQuote(
                    code=code,
                    name=row['名称'],
                    current_price=float(row['最新价']),
                    open_price=float(row['今开']),
                    high_price=float(row['最高']),
                    low_price=float(row['最低']),
                    prev_close=float(row['昨收']),
                    change=float(row['涨跌额']),
                    change_percent=float(row['涨跌幅']),
                    volume=float(row['成交量']),
                    amount=float(row['成交额']),
                    update_time=datetime.now()
                )
            except Exception as e:
                print(f"获取港股行情失败: {e}")
        
        return self._mock_quote(code, "模拟港股")
    
    async def get_kline_data(self, code: str, market: MarketType, 
                            period: str = "daily", limit: int = 120) -> List[KlineData]:
        """
        获取K线数据
        
        Args:
            code: 股票代码
            market: 市场类型
            period: 周期 (daily/weekly/monthly)
            limit: 数据条数
            
        Returns:
            K线数据列表
        """
        if market == MarketType.A_SHARE and self.akshare_available:
            return await self._get_a_share_kline(code, period, limit)
        elif market == MarketType.HK_STOCK and self.akshare_available:
            return await self._get_hk_kline(code, period, limit)
        
        # 返回模拟数据
        return self._mock_kline(limit)
    
    async def _get_a_share_kline(self, code: str, period: str, limit: int) -> List[KlineData]:
        """获取 A股K线数据"""
        try:
            import akshare as ak
            
            # 获取日K线
            df = ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                adjust="qfq"  # 前复权
            )
            
            # 取最近 limit 条数据
            df = df.tail(limit)
            
            klines = []
            for _, row in df.iterrows():
                klines.append(KlineData(
                    date=row['日期'].date() if hasattr(row['日期'], 'date') else row['日期'],
                    open=float(row['开盘']),
                    high=float(row['最高']),
                    low=float(row['最低']),
                    close=float(row['收盘']),
                    volume=float(row['成交量']),
                    amount=float(row['成交额']) if '成交额' in row else None
                ))
            
            return klines
            
        except Exception as e:
            print(f"获取 A股K线失败: {e}")
            return self._mock_kline(limit)
    
    async def _get_hk_kline(self, code: str, period: str, limit: int) -> List[KlineData]:
        """获取港股K线数据"""
        try:
            import akshare as ak
            
            code_padded = code.zfill(5)
            df = ak.stock_hk_hist(
                symbol=code_padded,
                period="daily",
                adjust="qfq"
            )
            
            df = df.tail(limit)
            
            klines = []
            for _, row in df.iterrows():
                klines.append(KlineData(
                    date=row['日期'].date() if hasattr(row['日期'], 'date') else row['日期'],
                    open=float(row['开盘']),
                    high=float(row['最高']),
                    low=float(row['最低']),
                    close=float(row['收盘']),
                    volume=float(row['成交量'])
                ))
            
            return klines
            
        except Exception as e:
            print(f"获取港股K线失败: {e}")
            return self._mock_kline(limit)
    
    async def get_fundamentals(self, code: str, market: MarketType) -> FundamentalData:
        """
        获取基本面数据
        """
        if market == MarketType.A_SHARE and self.tushare_api:
            return await self._get_a_share_fundamentals(code)
        
        # 返回模拟数据
        return FundamentalData(
            pe_ratio=15.5,
            pb_ratio=2.3,
            roe=12.5,
            revenue_growth=8.5,
            profit_growth=10.2,
            market_cap=1000.0,
            dividend_yield=2.5
        )
    
    async def _get_a_share_fundamentals(self, code: str) -> FundamentalData:
        """获取 A股基本面数据"""
        try:
            # 股票代码格式转换（Tushare 格式）
            ts_code = f"{code}.SH" if code.startswith('6') else f"{code}.SZ"
            
            # 获取基本面数据
            df = self.tushare_api.daily_basic(
                ts_code=ts_code,
                fields='ts_code,pe,pb,total_mv,turnover_rate'
            )
            
            if df.empty:
                return FundamentalData()
            
            row = df.iloc[0]
            
            return FundamentalData(
                pe_ratio=float(row['pe']) if row['pe'] else None,
                pb_ratio=float(row['pb']) if row['pb'] else None,
                market_cap=float(row['total_mv']) / 10000 if row['total_mv'] else None,  # 转换为亿元
            )
            
        except Exception as e:
            print(f"获取基本面数据失败: {e}")
            return FundamentalData()
    
    async def calculate_technicals(self, code: str, market: MarketType) -> TechnicalData:
        """
        计算技术指标
        """
        # 获取K线数据
        klines = await self.get_kline_data(code, market, limit=120)
        
        if not klines:
            return TechnicalData()
        
        # 转换为 OHLCV 格式
        ohlcv_list = [
            OHLCV(
                open=k.open,
                high=k.high,
                low=k.low,
                close=k.close,
                volume=k.volume
            )
            for k in klines
        ]
        
        # 计算所有指标
        indicators = TechnicalIndicators.calculate_all(ohlcv_list)
        
        return TechnicalData(
            ma5=indicators.get("ma5"),
            ma10=indicators.get("ma10"),
            ma20=indicators.get("ma20"),
            ma60=indicators.get("ma60"),
            macd_dif=indicators.get("macd_dif"),
            macd_dea=indicators.get("macd_dea"),
            macd_histogram=indicators.get("macd_histogram"),
            rsi_6=indicators.get("rsi_6"),
            rsi_12=indicators.get("rsi_12"),
            rsi_24=indicators.get("rsi_24"),
            boll_upper=indicators.get("boll_upper"),
            boll_middle=indicators.get("boll_middle"),
            boll_lower=indicators.get("boll_lower"),
            kdj_k=indicators.get("kdj_k"),
            kdj_d=indicators.get("kdj_d"),
            kdj_j=indicators.get("kdj_j"),
            volume=klines[-1].volume if klines else None
        )
    
    async def search_stocks(self, keyword: str, market: Optional[MarketType] = None) -> List[Dict]:
        """
        搜索股票
        """
        results = []
        
        if self.akshare_available:
            try:
                import akshare as ak
                
                # 搜索 A股
                if market is None or market == MarketType.A_SHARE:
                    df = ak.stock_zh_a_spot_em()
                    matched = df[
                        df['代码'].str.contains(keyword, na=False) |
                        df['名称'].str.contains(keyword, na=False)
                    ].head(10)
                    
                    for _, row in matched.iterrows():
                        results.append({
                            "code": row['代码'],
                            "name": row['名称'],
                            "market": "A"
                        })
                
                # 搜索港股
                if market is None or market == MarketType.HK_STOCK:
                    df = ak.stock_hk_spot_em()
                    matched = df[
                        df['代码'].str.contains(keyword, na=False) |
                        df['名称'].str.contains(keyword, na=False)
                    ].head(10)
                    
                    for _, row in matched.iterrows():
                        results.append({
                            "code": row['代码'],
                            "name": row['名称'],
                            "market": "HK"
                        })
                        
            except Exception as e:
                print(f"搜索股票失败: {e}")
        
        return results
    
    def _mock_quote(self, code: str, name: str) -> StockQuote:
        """生成模拟行情数据"""
        import random
        
        base_price = 100.0
        change_percent = random.uniform(-5, 5)
        change = base_price * change_percent / 100
        
        return StockQuote(
            code=code,
            name=name,
            current_price=round(base_price + change, 2),
            open_price=round(base_price - random.uniform(0, 2), 2),
            high_price=round(base_price + random.uniform(0, 3), 2),
            low_price=round(base_price - random.uniform(0, 3), 2),
            prev_close=round(base_price, 2),
            change=round(change, 2),
            change_percent=round(change_percent, 2),
            volume=random.uniform(100000, 1000000),
            amount=random.uniform(10000000, 100000000),
            update_time=datetime.now()
        )
    
    def _mock_kline(self, limit: int) -> List[KlineData]:
        """生成模拟K线数据"""
        import random
        
        klines = []
        base_date = date.today()
        base_price = 100.0
        
        for i in range(limit):
            d = base_date - timedelta(days=limit - i - 1)
            
            # 随机波动
            open_p = base_price + random.uniform(-2, 2)
            close_p = open_p + random.uniform(-3, 3)
            high_p = max(open_p, close_p) + random.uniform(0, 2)
            low_p = min(open_p, close_p) - random.uniform(0, 2)
            
            klines.append(KlineData(
                date=d,
                open=round(open_p, 2),
                high=round(high_p, 2),
                low=round(low_p, 2),
                close=round(close_p, 2),
                volume=random.uniform(100000, 500000)
            ))
            
            # 更新基准价格
            base_price = close_p
        
        return klines


# 单例实例
_stock_service: Optional[StockDataService] = None


def get_stock_service() -> StockDataService:
    """获取股票数据服务实例"""
    global _stock_service
    if _stock_service is None:
        _stock_service = StockDataService()
    return _stock_service

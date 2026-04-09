"""
股票数据模型
"""
from datetime import datetime as dt, date as dt_date
from typing import Optional, List
from pydantic import BaseModel, Field
from enum import Enum


class MarketType(str, Enum):
    """市场类型"""
    A_SHARE = "A"       # A股
    HK_STOCK = "HK"     # 港股


class PredictionType(str, Enum):
    """预测类型"""
    BULLISH = "bullish"     # 看多
    BEARISH = "bearish"     # 看空
    NEUTRAL = "neutral"     # 中性


class StockBase(BaseModel):
    """股票基础模型"""
    code: str = Field(..., description="股票代码")
    name: str = Field(..., description="股票名称")
    market: MarketType = Field(..., description="市场类型")


class StockCreate(StockBase):
    """创建自选股时的模型"""
    pass


class FundamentalData(BaseModel):
    """基本面数据"""
    pe_ratio: Optional[float] = Field(default=None, description="市盈率")
    pb_ratio: Optional[float] = Field(default=None, description="市净率")
    roe: Optional[float] = Field(default=None, description="净资产收益率（%）")
    revenue_growth: Optional[float] = Field(default=None, description="营收增长率（%）")
    profit_growth: Optional[float] = Field(default=None, description="净利润增长率（%）")
    market_cap: Optional[float] = Field(default=None, description="总市值（亿元）")
    total_shares: Optional[float] = Field(default=None, description="总股本（亿股）")
    dividend_yield: Optional[float] = Field(default=None, description="股息率（%）")


class TechnicalData(BaseModel):
    """技术指标数据"""
    # 均线
    ma5: Optional[float] = Field(default=None, description="5日均线")
    ma10: Optional[float] = Field(default=None, description="10日均线")
    ma20: Optional[float] = Field(default=None, description="20日均线")
    ma60: Optional[float] = Field(default=None, description="60日均线")
    
    # MACD
    macd_dif: Optional[float] = Field(default=None, description="MACD DIF线")
    macd_dea: Optional[float] = Field(default=None, description="MACD DEA线")
    macd_histogram: Optional[float] = Field(default=None, description="MACD柱状图")
    
    # RSI
    rsi_6: Optional[float] = Field(default=None, description="6日RSI")
    rsi_12: Optional[float] = Field(default=None, description="12日RSI")
    rsi_24: Optional[float] = Field(default=None, description="24日RSI")
    
    # 布林带
    boll_upper: Optional[float] = Field(default=None, description="布林带上轨")
    boll_middle: Optional[float] = Field(default=None, description="布林带中轨")
    boll_lower: Optional[float] = Field(default=None, description="布林带下轨")
    
    # KDJ
    kdj_k: Optional[float] = Field(default=None, description="KDJ K值")
    kdj_d: Optional[float] = Field(default=None, description="KDJ D值")
    kdj_j: Optional[float] = Field(default=None, description="KDJ J值")
    
    # 成交量
    volume: Optional[float] = Field(default=None, description="成交量")
    volume_ratio: Optional[float] = Field(default=None, description="量比")
    turnover_rate: Optional[float] = Field(default=None, description="换手率（%）")


class SentimentData(BaseModel):
    """情绪分析数据"""
    news_sentiment: float = Field(default=0, ge=-1, le=1, description="新闻情绪得分 (-1到1)")
    news_count: int = Field(default=0, description="相关新闻数量")
    positive_news: int = Field(default=0, description="正面新闻数量")
    negative_news: int = Field(default=0, description="负面新闻数量")
    hot_keywords: List[str] = Field(default_factory=list, description="热门关键词")
    recent_events: List[str] = Field(default_factory=list, description="近期重大事件")


class StockQuote(BaseModel):
    """股票实时行情"""
    code: str = Field(..., description="股票代码")
    name: str = Field(..., description="股票名称")
    current_price: float = Field(..., description="当前价格")
    open_price: float = Field(..., description="开盘价")
    high_price: float = Field(..., description="最高价")
    low_price: float = Field(..., description="最低价")
    prev_close: float = Field(..., description="昨收价")
    change: float = Field(..., description="涨跌额")
    change_percent: float = Field(..., description="涨跌幅（%）")
    volume: float = Field(..., description="成交量（手）")
    amount: float = Field(..., description="成交额（万元）")
    update_time: dt = Field(..., description="更新时间")
    pe_ratio: Optional[float] = Field(default=None, description="市盈率(动态)")
    pb_ratio: Optional[float] = Field(default=None, description="市净率")
    market_cap: Optional[float] = Field(default=None, description="总市值(亿)")


class StockPrediction(BaseModel):
    """股票投资预判"""
    code: str = Field(..., description="股票代码")
    name: str = Field(..., description="股票名称")
    market: MarketType = Field(..., description="市场类型")
    current_price: float = Field(..., description="当前价格")
    
    # 分析数据
    fundamentals: FundamentalData = Field(default_factory=FundamentalData, description="基本面数据")
    technicals: TechnicalData = Field(default_factory=TechnicalData, description="技术指标")
    sentiment: SentimentData = Field(default_factory=SentimentData, description="情绪分析")
    
    # 预测结果
    prediction: PredictionType = Field(..., description="预测结果")
    confidence: float = Field(default=0.5, ge=0, le=1, description="置信度 (0-1)")
    target_price: Optional[float] = Field(default=None, description="目标价格")
    stop_loss: Optional[float] = Field(default=None, description="止损价格")
    reasoning: str = Field(..., description="分析理由")
    
    # 综合评分
    fundamental_score: float = Field(default=0.5, ge=0, le=1, description="基本面评分")
    technical_score: float = Field(default=0.5, ge=0, le=1, description="技术面评分")
    sentiment_score: float = Field(default=0.5, ge=0, le=1, description="情绪评分")
    overall_score: float = Field(default=0.5, ge=0, le=1, description="综合评分")
    
    generated_at: dt = Field(default_factory=dt.now, description="生成时间")


class Stock(StockBase):
    """完整股票模型（自选股）"""
    id: str = Field(..., description="记录ID")
    
    # 最新行情
    current_price: Optional[float] = Field(default=None, description="当前价格")
    change_percent: Optional[float] = Field(default=None, description="涨跌幅（%）")
    
    # 最新预测
    latest_prediction: Optional[PredictionType] = Field(default=None, description="最新预测")
    latest_confidence: Optional[float] = Field(default=None, description="最新置信度")
    
    # 元数据
    added_at: dt = Field(default_factory=dt.now, description="添加时间")
    last_updated: Optional[dt] = Field(default=None, description="最后更新时间")
    
    class Config:
        from_attributes = True


class KlineData(BaseModel):
    """K线数据"""
    trade_date: dt_date = Field(..., description="日期")
    open_price: float = Field(..., description="开盘价")
    high_price: float = Field(..., description="最高价")
    low_price: float = Field(..., description="最低价")
    close_price: float = Field(..., description="收盘价")
    volume: float = Field(..., description="成交量")
    amount: Optional[float] = Field(default=None, description="成交额")

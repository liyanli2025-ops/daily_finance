"""
每日报告数据模型
"""
from datetime import datetime as dt, date as dt_date
from typing import Optional, List
from pydantic import BaseModel, Field
from enum import Enum


class SentimentType(str, Enum):
    """情绪类型"""
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class MarketTrend(str, Enum):
    """市场趋势"""
    BULLISH = "bullish"      # 看多
    BEARISH = "bearish"      # 看空
    NEUTRAL = "neutral"      # 中性


class NewsHighlight(BaseModel):
    """重点新闻摘要"""
    title: str = Field(..., description="新闻标题")
    source: str = Field(..., description="来源")
    summary: str = Field(..., description="摘要")
    sentiment: SentimentType = Field(..., description="情绪倾向")
    related_stocks: List[str] = Field(default_factory=list, description="关联股票代码")
    historical_context: Optional[str] = Field(default=None, description="历史背景/前因")
    source_url: Optional[str] = Field(default=None, description="原文链接")


class IndexSnapshot(BaseModel):
    """指数快照"""
    name: str = Field(..., description="指数名称")
    code: str = Field(..., description="指数代码")
    current: float = Field(..., description="当前点位")
    change: float = Field(..., description="涨跌点数")
    change_percent: float = Field(..., description="涨跌幅（%）")


class MarketAnalysis(BaseModel):
    """市场分析"""
    overall_sentiment: SentimentType = Field(..., description="整体市场情绪")
    trend: MarketTrend = Field(..., description="市场趋势判断")
    key_factors: List[str] = Field(default_factory=list, description="关键影响因素")
    opportunities: List[str] = Field(default_factory=list, description="投资机会")
    risks: List[str] = Field(default_factory=list, description="风险提示")
    indices: List[IndexSnapshot] = Field(default_factory=list, description="主要指数快照")


class ReportBase(BaseModel):
    """报告基础模型"""
    title: str = Field(..., description="报告标题")
    summary: str = Field(..., max_length=500, description="报告摘要（200-300字）")
    content: str = Field(..., description="完整内容（Markdown格式）")
    report_date: dt_date = Field(..., description="报告日期")


class ReportCreate(ReportBase):
    """创建报告时的模型"""
    highlights: List[NewsHighlight] = Field(default_factory=list, description="重点新闻")
    analysis: Optional[MarketAnalysis] = Field(default=None, description="市场分析")


class Report(ReportBase):
    """完整报告模型"""
    id: str = Field(..., description="报告ID")
    highlights: List[NewsHighlight] = Field(default_factory=list, description="重点新闻")
    analysis: Optional[MarketAnalysis] = Field(default=None, description="市场分析")
    
    # 播客相关
    podcast_url: Optional[str] = Field(default=None, description="播客音频URL")
    podcast_duration: Optional[int] = Field(default=None, description="播客时长（秒）")
    podcast_status: str = Field(default="pending", description="播客状态: pending/generating/ready/failed")
    
    # 元数据
    word_count: int = Field(default=0, description="报告字数")
    reading_time: int = Field(default=0, description="预计阅读时间（分钟）")
    news_count: int = Field(default=0, description="涉及新闻数量")
    
    created_at: dt = Field(default_factory=dt.now, description="创建时间")
    updated_at: Optional[dt] = Field(default=None, description="更新时间")
    
    class Config:
        from_attributes = True


class ReportListItem(BaseModel):
    """报告列表项（精简版）"""
    id: str
    title: str
    summary: str
    report_date: dt_date
    podcast_status: str
    podcast_duration: Optional[int]
    created_at: dt
    
    class Config:
        from_attributes = True

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


class ReportSectionType(str, Enum):
    """报告模块类型（5大模块 —— 投资决策导向）"""
    OPERATION_GUIDE = "operation_guide"       # 模块1：今日操作建议
    MARKET_PANORAMA = "market_panorama"      # 模块2：市场全景（大盘+板块+资金）
    WATCHLIST_BATTLE = "watchlist_battle"     # 模块3：自选股作战图
    EVENT_CATALYST = "event_catalyst"        # 模块4：事件催化与埋伏策略
    RISK_DASHBOARD = "risk_dashboard"        # 模块5：风控仪表盘


class CrossBorderCategory(str, Enum):
    """跨界事件类别"""
    GEOPOLITICAL = "geopolitical"   # 国际政治/地缘冲突
    TECH = "tech"                   # 科技突破/AI/新能源
    SOCIAL = "social"               # 社会舆论/明星事件/品牌危机
    DISASTER = "disaster"           # 自然灾害/气候事件


class AnalysisHighlight(BaseModel):
    """分析亮点（五要素结构）"""
    event: str = Field(..., description="事件/机会描述")
    historical_case: str = Field(..., description="历史案例对比")
    data_evidence: str = Field(..., description="数据佐证")
    logic_chain: str = Field(..., description="投资逻辑链条（因为A→所以B→因此C）")
    action_advice: str = Field(..., description="操作建议（买入/卖出/持有）")
    risk_warning: str = Field(..., description="风险提示")
    related_stocks: List[str] = Field(default_factory=list, description="关联股票代码")
    target_price: Optional[float] = Field(default=None, description="目标价")
    stop_loss: Optional[float] = Field(default=None, description="止损位")


class CrossBorderEvent(BaseModel):
    """跨界热点事件"""
    title: str = Field(..., description="事件标题")
    category: CrossBorderCategory = Field(..., description="事件类别")
    summary: str = Field(..., description="事件简述")
    market_impact_direct: str = Field(..., description="直接影响")
    market_impact_indirect: str = Field(..., description="间接影响")
    historical_reference: str = Field(..., description="历史参照")
    beneficiaries: List[str] = Field(default_factory=list, description="受益标的/板块")
    losers: List[str] = Field(default_factory=list, description="受损标的/板块")
    follow_up_advice: str = Field(..., description="持续跟踪建议")


class ReportSection(BaseModel):
    """报告模块"""
    id: str = Field(..., description="模块ID")
    title: str = Field(..., description="模块标题")
    section_type: ReportSectionType = Field(..., description="模块类型")
    content: str = Field(..., description="Markdown内容")
    highlights: List[AnalysisHighlight] = Field(default_factory=list, description="分析亮点（五要素）")
    cross_border_events: List[CrossBorderEvent] = Field(default_factory=list, description="跨界事件（仅跨界模块）")


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
    
    # 核心观点（3句话版）
    core_opinions: List[str] = Field(default_factory=list, description="今日核心观点（3条）")
    
    # 7大模块结构化内容
    sections: List[ReportSection] = Field(default_factory=list, description="7大模块结构化内容")
    
    # 重点新闻和跨界事件
    highlights: List[NewsHighlight] = Field(default_factory=list, description="重点新闻")
    cross_border_events: List[CrossBorderEvent] = Field(default_factory=list, description="跨界热点事件")
    
    # 市场分析
    analysis: Optional[MarketAnalysis] = Field(default=None, description="市场分析")
    
    # 播客相关
    podcast_url: Optional[str] = Field(default=None, description="播客音频URL")
    podcast_duration: Optional[int] = Field(default=None, description="播客时长（秒）")
    podcast_status: str = Field(default="pending", description="播客状态: pending/generating/ready/failed")
    
    # 元数据
    word_count: int = Field(default=0, description="报告字数")
    reading_time: int = Field(default=0, description="预计阅读时间（分钟）")
    news_count: int = Field(default=0, description="涉及新闻数量")
    cross_border_count: int = Field(default=0, description="跨界新闻数量")
    
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

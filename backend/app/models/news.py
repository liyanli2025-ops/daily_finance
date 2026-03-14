"""
新闻数据模型
"""
from datetime import datetime as dt
from typing import Optional, List
from pydantic import BaseModel, Field
from enum import Enum


class SentimentType(str, Enum):
    """新闻情绪类型"""
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class NewsType(str, Enum):
    """新闻类型（区分财经和跨界）"""
    FINANCE = "finance"           # 财经类
    GEOPOLITICAL = "geopolitical" # 国际政治/地缘冲突
    TECH = "tech"                 # 科技突破/AI/新能源
    SOCIAL = "social"             # 社会舆论/明星事件/品牌危机
    DISASTER = "disaster"         # 自然灾害/气候事件


class NewsBase(BaseModel):
    """新闻基础模型"""
    title: str = Field(..., description="新闻标题")
    content: str = Field(..., description="新闻内容")
    summary: Optional[str] = Field(default=None, description="新闻摘要")
    source: str = Field(..., description="新闻来源")
    source_url: Optional[str] = Field(default=None, description="原文链接")
    published_at: dt = Field(..., description="发布时间")
    

class NewsCreate(NewsBase):
    """创建新闻时的模型"""
    pass


class SentimentStrength(str, Enum):
    """情感强度"""
    WEAK = "weak"        # 弱：轻微影响
    MODERATE = "moderate"  # 中：明显影响
    STRONG = "strong"    # 强：重大影响


class News(NewsBase):
    """完整新闻模型（含数据库字段）"""
    id: str = Field(..., description="新闻ID")
    sentiment: SentimentType = Field(default=SentimentType.NEUTRAL, description="情绪倾向")
    importance_score: float = Field(default=0.5, ge=0, le=1, description="重要性评分")
    keywords: List[str] = Field(default_factory=list, description="关键词列表")
    related_stocks: List[str] = Field(default_factory=list, description="关联股票代码")
    created_at: dt = Field(default_factory=dt.now, description="入库时间")
    
    # 新闻类型（财经/跨界）
    news_type: NewsType = Field(default=NewsType.FINANCE, description="新闻类型")
    category: Optional[str] = Field(default=None, description="新闻分类（如：国际政治、科技突破等）")
    
    # 跨界新闻的市场影响分析
    market_impact: Optional[str] = Field(default=None, description="对市场的潜在影响分析")
    beneficiary_sectors: List[str] = Field(default_factory=list, description="受益板块")
    affected_sectors: List[str] = Field(default_factory=list, description="受损板块")
    
    # 事件追踪相关
    event_id: Optional[str] = Field(default=None, description="关联事件ID（用于新闻聚类）")
    is_follow_up: bool = Field(default=False, description="是否为后续报道")
    
    # ============ 深度情感分析字段（FinBERT）============
    sentiment_confidence: float = Field(default=0.5, ge=0, le=1, description="情感置信度")
    sentiment_strength: SentimentStrength = Field(default=SentimentStrength.MODERATE, description="情感强度")
    sentiment_scores: Optional[dict] = Field(default=None, description="各情感类别得分 {positive, negative, neutral}")
    sentiment_keywords_positive: List[str] = Field(default_factory=list, description="触发正面情感的关键词")
    sentiment_keywords_negative: List[str] = Field(default_factory=list, description="触发负面情感的关键词")
    sentiment_analysis_method: str = Field(default="pending", description="分析方法：finbert/rule/pending")
    is_china_related: bool = Field(default=False, description="是否中国相关")
    
    class Config:
        from_attributes = True


class NewsCluster(BaseModel):
    """新闻聚类（同一事件的相关新闻）"""
    event_id: str = Field(..., description="事件ID")
    event_title: str = Field(..., description="事件标题")
    news_list: List[News] = Field(default_factory=list, description="相关新闻列表")
    first_reported_at: dt = Field(..., description="首次报道时间")
    last_updated_at: dt = Field(..., description="最后更新时间")
    historical_context: Optional[str] = Field(default=None, description="历史背景")
    similar_cases: List[str] = Field(default_factory=list, description="历史类似案例")

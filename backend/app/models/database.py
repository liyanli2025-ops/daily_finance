"""
SQLAlchemy 数据库模型
"""
from datetime import datetime, date
from sqlalchemy import (
    Column, String, Text, Float, Integer, Boolean, 
    DateTime, Date, JSON, Enum, create_engine
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
import enum

Base = declarative_base()


class SentimentEnum(enum.Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class MarketEnum(enum.Enum):
    A = "A"
    HK = "HK"


class PredictionEnum(enum.Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class ReportTypeEnum(enum.Enum):
    """报告类型枚举"""
    MORNING = "morning"    # 早报
    EVENING = "evening"    # 晚报


class NewsModel(Base):
    """新闻表"""
    __tablename__ = "news"
    
    id = Column(String(36), primary_key=True)
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)
    summary = Column(Text)
    source = Column(String(100), nullable=False)
    source_url = Column(String(1000))
    published_at = Column(DateTime, nullable=False)
    
    sentiment = Column(String(20), default="neutral")
    importance_score = Column(Float, default=0.5)
    keywords = Column(JSON, default=list)
    related_stocks = Column(JSON, default=list)
    
    # 新闻类型（财经/跨界）
    news_type = Column(String(20), default="finance")
    category = Column(String(50))
    
    # 跨界新闻的市场影响
    market_impact = Column(Text)
    beneficiary_sectors = Column(JSON, default=list)
    affected_sectors = Column(JSON, default=list)
    
    # 事件追踪
    event_id = Column(String(36))
    is_follow_up = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.now)


class ReportModel(Base):
    """报告表"""
    __tablename__ = "reports"
    
    id = Column(String(36), primary_key=True)
    title = Column(String(500), nullable=False)
    summary = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    report_date = Column(Date, nullable=False)  # 允许同一天生成多条报告
    
    # 报告类型（早报/晚报）
    report_type = Column(String(20), default="morning")  # morning 或 evening
    
    # 核心观点（3条）
    core_opinions = Column(JSON, default=list)
    
    # 重点新闻和跨界事件
    highlights = Column(JSON, default=list)
    cross_border_events = Column(JSON, default=list)
    
    # 市场分析
    analysis = Column(JSON)
    
    # 播客相关
    podcast_url = Column(String(1000))
    podcast_duration = Column(Integer)
    podcast_status = Column(String(20), default="pending")
    
    # 统计信息
    word_count = Column(Integer, default=0)
    reading_time = Column(Integer, default=0)
    news_count = Column(Integer, default=0)
    cross_border_count = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime)


class StockModel(Base):
    """自选股表"""
    __tablename__ = "stocks"
    
    id = Column(String(36), primary_key=True)
    code = Column(String(20), nullable=False)
    name = Column(String(100), nullable=False)
    market = Column(String(10), nullable=False)
    
    current_price = Column(Float)
    change_percent = Column(Float)
    
    latest_prediction = Column(String(20))
    latest_confidence = Column(Float)
    
    added_at = Column(DateTime, default=datetime.now)
    last_updated = Column(DateTime)


class StockPredictionModel(Base):
    """股票预测记录表"""
    __tablename__ = "stock_predictions"
    
    id = Column(String(36), primary_key=True)
    stock_code = Column(String(20), nullable=False)
    stock_name = Column(String(100), nullable=False)
    market = Column(String(10), nullable=False)
    
    current_price = Column(Float, nullable=False)
    prediction = Column(String(20), nullable=False)
    confidence = Column(Float, nullable=False)
    target_price = Column(Float)
    stop_loss = Column(Float)
    reasoning = Column(Text, nullable=False)
    
    fundamental_score = Column(Float)
    technical_score = Column(Float)
    sentiment_score = Column(Float)
    overall_score = Column(Float)
    
    fundamentals = Column(JSON)
    technicals = Column(JSON)
    sentiment = Column(JSON)
    
    generated_at = Column(DateTime, default=datetime.now)


class EventModel(Base):
    """事件聚类表"""
    __tablename__ = "events"
    
    id = Column(String(36), primary_key=True)
    title = Column(String(500), nullable=False)
    summary = Column(Text)
    first_reported_at = Column(DateTime, nullable=False)
    last_updated_at = Column(DateTime)
    
    historical_context = Column(Text)
    similar_cases = Column(JSON, default=list)
    
    news_ids = Column(JSON, default=list)
    news_count = Column(Integer, default=0)


class TechSignalHistoryModel(Base):
    """技术信号历史记录表 — 用于追踪信号的历史胜率"""
    __tablename__ = "tech_signal_history"
    
    id = Column(String(36), primary_key=True)
    
    # 信号发出日期和股票信息
    signal_date = Column(Date, nullable=False)         # 信号触发日期
    stock_code = Column(String(20), nullable=False)    # 股票代码
    stock_name = Column(String(100), nullable=False)   # 股票名称
    
    # 信号详情
    signal_type = Column(String(50), nullable=False)   # 信号类型（如 MACD金叉、均线多头排列）
    signal_score = Column(Float, default=0)            # 信号综合得分
    all_signals = Column(JSON, default=list)            # 当日触发的所有信号列表
    
    # 信号触发时的价格
    entry_price = Column(Float, nullable=False)        # 信号触发日收盘价
    
    # 7日后评估结果（延迟填充）
    eval_date = Column(Date)                           # 评估日期（信号日+7天）
    exit_price = Column(Float)                         # 评估日收盘价
    return_pct = Column(Float)                         # 7日收益率(%)
    is_win = Column(Boolean)                           # 是否盈利（收益率>0）
    is_evaluated = Column(Boolean, default=False)      # 是否已评估
    
    # 元数据
    sector = Column(String(100))                       # 所属行业
    volume_ratio = Column(Float)                       # 信号日量比
    turnover_rate = Column(Float)                      # 信号日换手率
    
    created_at = Column(DateTime, default=datetime.now)
    evaluated_at = Column(DateTime)                    # 评估完成时间


class PredictionAccuracyModel(Base):
    """预测准确度记录表 — 自动回测早报预测 vs 实际收盘"""
    __tablename__ = "prediction_accuracy"
    
    id = Column(String(36), primary_key=True)
    report_id = Column(String(36), nullable=False)     # 关联早报ID
    report_date = Column(Date, nullable=False)         # 报告日期
    
    # 各维度评分
    market_direction_hit = Column(Boolean)             # 大盘方向是否命中
    sector_accuracy = Column(Float)                    # 板块推荐准确率 (0-1)
    stock_accuracy = Column(Float)                     # 个股建议准确率 (0-1)
    overall_accuracy = Column(Float)                   # 综合准确率 (0-1)
    
    # 详细数据（JSON）
    predictions = Column(JSON)                         # 原始预测数据
    actuals = Column(JSON)                             # 实际收盘数据
    evaluation = Column(JSON)                          # 逐项评估结果
    
    # 经验教训（AI生成）
    lessons_learned = Column(Text)
    
    created_at = Column(DateTime, default=datetime.now)


# 数据库初始化函数
def get_database_url(url: str) -> str:
    """转换数据库URL为异步版本"""
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///")
    return url


async def init_database(database_url: str):
    """初始化数据库"""
    async_url = get_database_url(database_url)
    engine = create_async_engine(async_url, echo=False)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    return engine


def get_session_maker(engine):
    """获取会话工厂"""
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

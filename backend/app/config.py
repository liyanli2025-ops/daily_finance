"""
应用配置管理模块
使用 pydantic-settings 进行配置验证和类型安全
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional, List, Literal
from pathlib import Path


class Settings(BaseSettings):
    """应用配置类"""
    
    # 基础配置
    app_name: str = Field(default="FinanceDaily", description="应用名称")
    debug: bool = Field(default=True, description="调试模式")
    host: str = Field(default="0.0.0.0", description="服务监听地址")
    port: int = Field(default=8000, description="服务端口")
    
    # 推送时间配置
    daily_report_hour: int = Field(default=6, ge=0, le=23, description="每日早报推送小时")
    daily_report_minute: int = Field(default=0, ge=0, le=59, description="每日早报推送分钟")
    
    # 【新增】晚报推送时间配置（交易日下午5点前完成）
    evening_report_hour: int = Field(default=17, ge=0, le=23, description="每日晚报推送小时")
    evening_report_minute: int = Field(default=0, ge=0, le=59, description="每日晚报推送分钟")
    
    # 新闻采集提前时间（提前多少分钟开始采集）
    collection_lead_time: int = Field(default=60, description="采集提前时间（分钟）")
    
    # 【新增】晚报采集开始时间（下午4点30分开始收集内容，避免东财涨停池数据延迟问题）
    evening_collection_hour: int = Field(default=16, ge=0, le=23, description="晚报采集开始小时")
    evening_collection_minute: int = Field(default=30, ge=0, le=59, description="晚报采集开始分钟（默认30分，等待东财涨停池数据更新完成）")
    
    # 【新增】盘中预采集时间（交易日午间，缓存上午新闻避免被下午新闻冲掉）
    midday_collection_hour: int = Field(default=11, ge=0, le=23, description="盘中预采集小时")
    midday_collection_minute: int = Field(default=35, ge=0, le=59, description="盘中预采集分钟")
    
    # Explicit task routes; existing credentials remain supported.
    ai_provider: Literal["auto", "compatible", "anthropic", "backup"] = "auto"
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    ai_model: Optional[str] = Field(default=None, description="兼容旧配置的明确模型名；不再默认过期模型")
    ai_timeout_seconds: int = Field(default=300, ge=10, le=900)
    model_max_calls_per_report: int = Field(default=8, ge=1, le=12, description='整期模型HTTP请求上限，含网络重试与审查修复；不是金额上限')
    model_http_retries: int = Field(default=0, ge=0, le=1, description='默认不自动重复付费HTTP请求；显式设置1才允许一次重试')
    report_auto_repair_enabled: bool = Field(default=False, description='默认保留审查失败稿待编辑，不自动整篇付费重写')

    # 备用 AI 服务（主服务挂了自动切换，强烈推荐配置！）
    # 例如：主用 DeepSeek，备用硅基流动
    backup_ai_api_key: Optional[str] = Field(default=None, description="备用 AI API Key")
    backup_ai_base_url: Optional[str] = Field(default=None, description="备用 AI Base URL")
    backup_ai_model: Optional[str] = Field(default=None, description="备用 AI 模型名称")
    
    analysis_provider: Optional[Literal["compatible", "anthropic", "backup"]] = None
    analysis_model: Optional[str] = None
    analysis_reasoning_effort: Literal["none", "low", "high", "max"] = "none"
    review_provider: Optional[Literal["compatible", "anthropic", "backup"]] = None
    review_model: Optional[str] = None
    review_reasoning_effort: Literal["none", "low", "high", "max"] = "none"
    extraction_provider: Optional[Literal["compatible", "anthropic", "backup"]] = None
    extraction_model: Optional[str] = None
    extraction_reasoning_effort: Literal["none", "low", "high", "max"] = "none"
    podcast_provider: Optional[Literal["compatible", "anthropic", "backup"]] = None
    podcast_model: Optional[str] = None
    podcast_reasoning_effort: Literal["none", "low", "high", "max"] = "none"

    # 语音合成配置
    tts_voice: str = Field(default="zh-CN-YunxiNeural", description="TTS语音角色")
    tts_rate: str = Field(default="+0%", description="TTS语速")
    tts_volume: str = Field(default="+0%", description="TTS音量")
    
    # 股票数据配置
    tushare_token: Optional[str] = Field(default=None, description="Tushare Token")
    
    # 【新增】用户个性化配置
    user_nickname: str = Field(default="卢卡", description="用户昵称，播客中会使用")
    
    # 【新增】自选股配置 - 你关注的股票，会在报告中特别追踪分析
    # 格式: "代码:名称:市场" 多个用逗号分隔
    # 市场: A=A股, HK=港股
    # 示例: "600519:贵州茅台:A,00700:腾讯控股:HK,300750:宁德时代:A"
    watchlist_stocks: str = Field(
        default="",
        description="自选股列表，格式: 代码:名称:市场,代码:名称:市场"
    )
    
    # 【新增】投资风格偏好（影响分析角度）
    # conservative=保守型, balanced=平衡型, aggressive=激进型
    investment_style: str = Field(
        default="balanced",
        description="投资风格：conservative/balanced/aggressive"
    )
    
    # 数据库配置
    database_url: str = Field(
        default="sqlite:///./data/database.db",
        description="数据库连接字符串"
    )
    
    # 数据存储路径 - 使用相对路径，会在初始化时转为绝对路径
    data_dir: Path = Field(default=Path("./data"), description="数据目录")
    reports_dir: Path = Field(default=Path("./data/reports"), description="报告存储目录")
    podcasts_dir: Path = Field(default=Path("./data/podcasts"), description="播客存储目录")
    
    # 新闻源配置
    rss_feeds: List[str] = Field(
        default=[
            "https://feedx.net/rss/wallstreetcn.xml",  # 华尔街见闻
            "https://rsshub.app/cls/telegraph",        # 财联社电报
            "https://rsshub.app/eastmoney/report",     # 东方财富研报
            "https://rsshub.app/caixin/latest",        # 财新网
        ],
        description="RSS新闻源列表"
    )
    
    class Config:
        # 使用绝对路径定位 .env，避免 CWD 不同（如 systemd、nohup 等）导致找不到文件
        env_file = Path(__file__).resolve().parent.parent / ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
    
    def model_post_init(self, __context):
        """初始化后处理，将相对路径转换为绝对路径"""
        # 获取 backend 目录的绝对路径（config.py 所在目录的上两级）
        config_file = Path(__file__).resolve()
        backend_dir = config_file.parent.parent
        
        # 转换为绝对路径
        if not self.data_dir.is_absolute():
            self.data_dir = backend_dir / self.data_dir
        if not self.reports_dir.is_absolute():
            self.reports_dir = backend_dir / self.reports_dir
        if not self.podcasts_dir.is_absolute():
            self.podcasts_dir = backend_dir / self.podcasts_dir
        
        # 修复数据库路径：将相对路径转换为绝对路径
        if self.database_url.startswith("sqlite:///./"):
            db_relative = self.database_url.replace("sqlite:///./", "")
            db_absolute = backend_dir / db_relative
            self.database_url = f"sqlite:///{db_absolute}"
    
    def ensure_directories(self):
        """确保所有数据目录存在"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.podcasts_dir.mkdir(parents=True, exist_ok=True)


# 全局配置实例
settings = Settings()

# 启动时打印关键配置，便于排查问题
_env_path = Path(__file__).resolve().parent.parent / ".env"
print(f"[CONFIG] .env 路径: {_env_path} (存在: {_env_path.is_file()})")
print(f"[CONFIG] daily_report_hour={settings.daily_report_hour}, ai_model={settings.ai_model}, port={settings.port}")


# 确保目录存在
settings.ensure_directories()

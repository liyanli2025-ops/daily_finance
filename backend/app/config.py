"""
应用配置管理模块
使用 pydantic-settings 进行配置验证和类型安全
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional, List
from pathlib import Path


class Settings(BaseSettings):
    """应用配置类"""
    
    # 基础配置
    app_name: str = Field(default="FinanceDaily", description="应用名称")
    debug: bool = Field(default=True, description="调试模式")
    host: str = Field(default="0.0.0.0", description="服务监听地址")
    port: int = Field(default=8000, description="服务端口")
    
    # 推送时间配置
    daily_report_hour: int = Field(default=6, ge=0, le=23, description="每日报告推送小时")
    daily_report_minute: int = Field(default=0, ge=0, le=59, description="每日报告推送分钟")
    
    # 新闻采集提前时间（提前多少分钟开始采集）
    collection_lead_time: int = Field(default=60, description="采集提前时间（分钟）")
    
    # AI 服务配置
    # 优先级：Anthropic > OpenAI > 免费服务 (Pollinations.AI)
    # 
    # 推荐配置方式：
    # 1. 使用 Claude（最佳效果）: 设置 ANTHROPIC_API_KEY
    # 2. 使用 GPT-4: 设置 OPENAI_API_KEY
    # 3. 使用 DeepSeek（高性价比）: 设置 OPENAI_API_KEY 和 OPENAI_BASE_URL=https://api.deepseek.com
    # 4. 不配置任何 key：自动使用免费的 Pollinations.AI（不稳定，仅用于测试）
    anthropic_api_key: Optional[str] = Field(default=None, description="Anthropic API Key（推荐使用 Claude）")
    openai_api_key: Optional[str] = Field(default=None, description="OpenAI API Key 或兼容服务的 Key")
    openai_base_url: Optional[str] = Field(default=None, description="OpenAI 兼容服务 Base URL（如 DeepSeek）")
    ai_model: str = Field(
        default="claude-3-opus-20240229", 
        description="AI 模型名称。Claude: claude-3-opus-20240229 / claude-3-5-sonnet-20241022; OpenAI: gpt-4-turbo / gpt-4o; DeepSeek: deepseek-chat"
    )
    
    # 语音合成配置
    tts_voice: str = Field(default="zh-CN-YunxiNeural", description="TTS语音角色")
    tts_rate: str = Field(default="+0%", description="TTS语速")
    tts_volume: str = Field(default="+0%", description="TTS音量")
    
    # 股票数据配置
    tushare_token: Optional[str] = Field(default=None, description="Tushare Token")
    
    # 数据库配置
    database_url: str = Field(
        default="sqlite:///./data/database.db",
        description="数据库连接字符串"
    )
    
    # 数据存储路径
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
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
    
    def ensure_directories(self):
        """确保所有数据目录存在"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.podcasts_dir.mkdir(parents=True, exist_ok=True)


# 全局配置实例
settings = Settings()


# 确保目录存在
settings.ensure_directories()

"""
微信公众号订阅 Pydantic 模型
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class WechatAccountBase(BaseModel):
    """公众号基础字段"""
    name: str = Field(..., description="公众号名称")
    biz: str = Field(..., description="公众号 __biz 参数（唯一标识）")
    description: Optional[str] = Field(None, description="公众号描述")
    category: str = Field(default="财经", description="分类：财经/宏观/行业/券商/科技")


class WechatAccountCreate(BaseModel):
    """添加公众号 - 请求体"""
    name: str = Field(..., description="公众号名称")
    biz: str = Field(..., description="公众号 __biz 参数")
    description: Optional[str] = Field(None, description="公众号描述")
    category: str = Field(default="财经", description="分类")


class WechatAccountUpdate(BaseModel):
    """更新公众号 - 请求体"""
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    enabled: Optional[bool] = None


class WechatAccountResponse(BaseModel):
    """公众号 - 响应体"""
    id: str
    name: str
    biz: str
    description: Optional[str] = None
    category: str = "财经"
    is_preset: bool = False
    enabled: bool = True
    last_fetched_at: Optional[datetime] = None
    total_articles: int = 0
    fetch_fail_count: int = 0
    added_at: Optional[datetime] = None
    
    # RSSHub URL（计算字段）
    rsshub_url: Optional[str] = None
    
    class Config:
        from_attributes = True


class WechatArticle(BaseModel):
    """公众号文章（采集到的）"""
    title: str
    content: str
    summary: str
    source_name: str  # 公众号名称
    source_url: str
    published_at: datetime
    biz: str

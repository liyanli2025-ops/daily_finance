"""
微信公众号订阅管理服务

功能：
- 公众号 CRUD（增删改查）
- 通过 WeWe-RSS（优先）或 RSSHub（备用）采集公众号文章
- 预置常见财经公众号
- 从文章链接自动提取 __biz 参数

数据源优先级：
1. WeWe-RSS（本地部署，基于微信读书，稳定可靠）
2. RSSHub（公共实例，微信路由经常被封，仅作备用）
"""
import re
import uuid
import asyncio
from datetime import datetime
from typing import List, Optional, Dict
from urllib.parse import unquote, parse_qs, urlparse

import httpx
import feedparser

from ..models.news import News, NewsType, SentimentType


# ==========================================
# 预置的财经公众号（用户开箱即用）
# biz 用于 RSSHub 备用通道
# feed_id 用于 WeWe-RSS（在 WeWe-RSS 管理面板订阅后会自动获取）
# ==========================================
PRESET_ACCOUNTS = [
    {
        "name": "泽平宏观",
        "biz": "MzA4NTI0MDY3OQ==",
        "description": "任泽平团队，宏观经济与政策解读",
        "category": "宏观"
    },
    {
        "name": "华尔街见闻",
        "biz": "MjM5MzE5MzI4MA==",
        "description": "全球财经资讯，快速、深度",
        "category": "财经"
    },
    {
        "name": "中国基金报",
        "biz": "MzI0NDg2ODA0MQ==",
        "description": "基金行业权威媒体",
        "category": "基金"
    },
    {
        "name": "券商中国",
        "biz": "MzI2MDAxODA4MQ==",
        "description": "券商行业深度报道",
        "category": "券商"
    },
    {
        "name": "Wind万得",
        "biz": "MzI2MjE3NzA0MA==",
        "description": "万得资讯，金融数据服务",
        "category": "数据"
    },
    {
        "name": "21世纪经济报道",
        "biz": "MjM5MjAyMzA0MA==",
        "description": "深度财经新闻报道",
        "category": "财经"
    },
    {
        "name": "第一财经",
        "biz": "MjM5MTYzMDc2OA==",
        "description": "专业财经媒体",
        "category": "财经"
    },
    {
        "name": "国泰君安证券研究",
        "biz": "MzA4MDUxMjIxOA==",
        "description": "国泰君安研究所，卖方研报",
        "category": "券商"
    },
    {
        "name": "中信建投证券研究",
        "biz": "MzI0NTIyNjc4OA==",
        "description": "中信建投研究所",
        "category": "券商"
    },
    {
        "name": "格隆汇",
        "biz": "MzI1MjA1MDA3OQ==",
        "description": "港股及全球资产研究",
        "category": "港股"
    },
]


# WeWe-RSS 本地服务地址（部署在同一台服务器上）
WEWE_RSS_BASE = "http://localhost:4000"

# RSSHub 实例列表（备用，按优先级排序）
RSSHUB_INSTANCES = [
    "https://rsshub.rssforever.com",
    "https://rsshub.app",
    "https://rss.shab.fun",
]


class WechatSubscriptionService:
    """微信公众号订阅管理服务"""
    
    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            }
        )
        self._rsshub_base = RSSHUB_INSTANCES[0]
        self._wewe_rss_available = None  # None=未检测, True/False=检测结果
    
    # ==========================================
    # 公众号 CRUD
    # ==========================================
    
    async def get_all_accounts(self, db_session) -> List[Dict]:
        """获取所有公众号"""
        from ..models.database import WechatAccountModel
        from sqlalchemy import select
        
        result = await db_session.execute(
            select(WechatAccountModel).order_by(WechatAccountModel.added_at.desc())
        )
        accounts = result.scalars().all()
        return accounts
    
    async def get_enabled_accounts(self, db_session) -> List[Dict]:
        """获取所有启用的公众号"""
        from ..models.database import WechatAccountModel
        from sqlalchemy import select
        
        result = await db_session.execute(
            select(WechatAccountModel).where(
                WechatAccountModel.enabled == True
            ).order_by(WechatAccountModel.added_at.desc())
        )
        return result.scalars().all()
    
    async def add_account(self, db_session, name: str, biz: str, 
                          description: str = None, category: str = "财经",
                          is_preset: bool = False) -> Dict:
        """添加公众号"""
        from ..models.database import WechatAccountModel
        from sqlalchemy import select
        
        # 检查 biz 是否已存在
        existing = await db_session.execute(
            select(WechatAccountModel).where(WechatAccountModel.biz == biz)
        )
        if existing.scalar_one_or_none():
            raise ValueError(f"公众号 biz={biz} 已存在")
        
        # 清理 biz（去除可能的 URL 编码、空格等）
        biz = biz.strip().replace(" ", "+")
        
        account = WechatAccountModel(
            id=str(uuid.uuid4()),
            name=name,
            biz=biz,
            description=description,
            category=category,
            is_preset=is_preset,
            enabled=True,
            added_at=datetime.now()
        )
        
        db_session.add(account)
        await db_session.commit()
        await db_session.refresh(account)
        
        return account
    
    async def update_account(self, db_session, account_id: str, **kwargs) -> Optional[Dict]:
        """更新公众号"""
        from ..models.database import WechatAccountModel
        from sqlalchemy import select
        
        result = await db_session.execute(
            select(WechatAccountModel).where(WechatAccountModel.id == account_id)
        )
        account = result.scalar_one_or_none()
        if not account:
            return None
        
        for key, value in kwargs.items():
            if value is not None and hasattr(account, key):
                setattr(account, key, value)
        
        account.updated_at = datetime.now()
        await db_session.commit()
        await db_session.refresh(account)
        
        return account
    
    async def delete_account(self, db_session, account_id: str) -> bool:
        """删除公众号"""
        from ..models.database import WechatAccountModel
        from sqlalchemy import select
        
        result = await db_session.execute(
            select(WechatAccountModel).where(WechatAccountModel.id == account_id)
        )
        account = result.scalar_one_or_none()
        if not account:
            return False
        
        await db_session.delete(account)
        await db_session.commit()
        return True
    
    async def toggle_account(self, db_session, account_id: str) -> Optional[Dict]:
        """切换公众号启用/禁用状态"""
        from ..models.database import WechatAccountModel
        from sqlalchemy import select
        
        result = await db_session.execute(
            select(WechatAccountModel).where(WechatAccountModel.id == account_id)
        )
        account = result.scalar_one_or_none()
        if not account:
            return None
        
        account.enabled = not account.enabled
        account.updated_at = datetime.now()
        await db_session.commit()
        await db_session.refresh(account)
        
        return account
    
    async def init_preset_accounts(self, db_session):
        """
        初始化预置公众号（首次运行时调用）
        只添加还不存在的预置号
        """
        from ..models.database import WechatAccountModel
        from sqlalchemy import select
        
        added_count = 0
        for preset in PRESET_ACCOUNTS:
            # 检查是否已存在
            existing = await db_session.execute(
                select(WechatAccountModel).where(WechatAccountModel.biz == preset["biz"])
            )
            if existing.scalar_one_or_none():
                continue
            
            try:
                await self.add_account(
                    db_session,
                    name=preset["name"],
                    biz=preset["biz"],
                    description=preset["description"],
                    category=preset["category"],
                    is_preset=True
                )
                added_count += 1
            except Exception as e:
                print(f"  [公众号] 预置 {preset['name']} 失败: {e}")
        
        if added_count > 0:
            print(f"  [公众号] 初始化了 {added_count} 个预置公众号")
    
    # ==========================================
    # 从链接提取 biz
    # ==========================================
    
    @staticmethod
    def extract_biz_from_url(url: str) -> Optional[str]:
        """
        从微信文章链接中提取 __biz 参数
        
        示例链接：
        https://mp.weixin.qq.com/s?__biz=MzA4NTI0MDY3OQ==&mid=123&idx=1&sn=xxx
        """
        try:
            # URL decode
            url = unquote(url)
            
            # 方法1：从 query string 提取
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            
            if "__biz" in params:
                return params["__biz"][0]
            
            # 方法2：正则匹配
            match = re.search(r'__biz=([A-Za-z0-9+/=]+)', url)
            if match:
                return match.group(1)
            
            return None
        except Exception:
            return None
    
    # ==========================================
    # WeWe-RSS 采集（优先方案）
    # ==========================================
    
    async def _check_wewe_rss(self) -> bool:
        """检测 WeWe-RSS 本地服务是否可用"""
        if self._wewe_rss_available is not None:
            return self._wewe_rss_available
        
        try:
            response = await self.client.get(f"{WEWE_RSS_BASE}/feeds/all.json", timeout=5.0)
            self._wewe_rss_available = response.status_code == 200
        except Exception:
            self._wewe_rss_available = False
        
        status = "✅ 可用" if self._wewe_rss_available else "❌ 不可用"
        print(f"  [公众号] WeWe-RSS ({WEWE_RSS_BASE}) {status}")
        return self._wewe_rss_available
    
    async def _fetch_from_wewe_rss(self, account_name: str = "未知") -> List[News]:
        """
        从 WeWe-RSS 获取所有订阅的文章
        
        WeWe-RSS 的文章按订阅源管理，使用 /feeds/all.json 获取全部文章，
        然后按 account_name 筛选。
        如果 account_name 为 "__ALL__" 则获取全部文章。
        """
        articles = []
        
        try:
            url = f"{WEWE_RSS_BASE}/feeds/all.json?limit=50"
            response = await self.client.get(url)
            
            if response.status_code != 200:
                return articles
            
            data = response.json()
            items = data.get("items", [])
            
            for item in items:
                title = item.get("title", "").strip()
                if not title:
                    continue
                
                content_html = item.get("content_html", "")
                summary = item.get("summary", "")
                link = item.get("url", "")
                source_name = item.get("_feed_title", "") or item.get("authors", [{}])[0].get("name", "未知公众号") if item.get("authors") else "未知公众号"
                
                # 如果指定了具体公众号名称，只保留匹配的
                if account_name != "__ALL__" and source_name and account_name not in source_name and source_name not in account_name:
                    continue
                
                # 解析时间
                published = datetime.now()
                date_str = item.get("date_published", "")
                if date_str:
                    try:
                        published = datetime.fromisoformat(date_str.replace("Z", "+00:00")).replace(tzinfo=None)
                    except Exception:
                        pass
                
                content = self._clean_html(content_html or summary)
                
                articles.append(News(
                    id=str(uuid.uuid4()),
                    title=title,
                    content=content[:2000] if content else title,
                    summary=content[:300] if content else title,
                    source=f"公众号·{source_name}",
                    source_url=link,
                    published_at=published,
                    news_type=NewsType.FINANCE,
                    sentiment=SentimentType.NEUTRAL,
                    importance_score=0.75,
                    is_china_related=True,
                    category="公众号"
                ))
            
        except Exception as e:
            print(f"  [公众号] WeWe-RSS 采集失败: {e}")
        
        return articles
    
    async def _fetch_all_from_wewe_rss(self) -> List[News]:
        """从 WeWe-RSS 获取所有订阅的文章（不区分公众号）"""
        return await self._fetch_from_wewe_rss("__ALL__")
    
    # ==========================================
    # RSSHub 采集（备用方案）
    # ==========================================
    
    def _get_rsshub_url(self, biz: str) -> str:
        """生成 RSSHub 微信公众号 URL"""
        return f"{self._rsshub_base}/wechat/mp/articles/{biz}"
    
    async def _fetch_from_rsshub(self, biz: str, account_name: str = "未知") -> List[News]:
        """
        通过 RSSHub 采集公众号文章（备用方案）
        
        会尝试多个 RSSHub 实例，某个不通就切换下一个
        """
        articles = []
        
        for instance in RSSHUB_INSTANCES:
            url = f"{instance}/wechat/mp/articles/{biz}"
            try:
                response = await self.client.get(url)
                if response.status_code == 200:
                    feed = feedparser.parse(response.text)
                    
                    if not feed.entries:
                        continue
                    
                    for entry in feed.entries[:10]:
                        title = entry.get("title", "").strip()
                        summary = entry.get("summary", "").strip()
                        link = entry.get("link", "")
                        
                        published = datetime.now()
                        if hasattr(entry, "published_parsed") and entry.published_parsed:
                            try:
                                from time import mktime
                                published = datetime.fromtimestamp(mktime(entry.published_parsed))
                            except Exception:
                                pass
                        
                        if not title:
                            continue
                        
                        content = self._clean_html(summary)
                        
                        articles.append(News(
                            id=str(uuid.uuid4()),
                            title=title,
                            content=content[:2000] if content else title,
                            summary=content[:300] if content else title,
                            source=f"公众号·{account_name}",
                            source_url=link,
                            published_at=published,
                            news_type=NewsType.FINANCE,
                            sentiment=SentimentType.NEUTRAL,
                            importance_score=0.75,
                            is_china_related=True,
                            category="公众号"
                        ))
                    
                    self._rsshub_base = instance
                    return articles
                    
            except Exception as e:
                print(f"  [公众号] RSSHub实例 {instance} 失败: {e}")
                continue
        
        return articles
    
    # ==========================================
    # 统一采集入口
    # ==========================================
    
    async def fetch_articles(self, biz: str, account_name: str = "未知") -> List[News]:
        """
        采集某个公众号的文章
        
        优先使用 WeWe-RSS，不可用时降级到 RSSHub
        """
        # 方案1：WeWe-RSS
        if await self._check_wewe_rss():
            articles = await self._fetch_from_wewe_rss(account_name)
            if articles:
                return articles
            print(f"  [公众号] WeWe-RSS 未获取到 {account_name} 的文章，尝试 RSSHub...")
        
        # 方案2：RSSHub 备用
        return await self._fetch_from_rsshub(biz, account_name)
    
    async def fetch_all_enabled(self, db_session) -> List[News]:
        """
        采集所有启用的公众号的文章
        
        如果 WeWe-RSS 可用，直接批量获取全部文章（更高效）；
        否则逐个通过 RSSHub 采集。
        """
        from ..models.database import WechatAccountModel
        
        accounts = await self.get_enabled_accounts(db_session)
        
        if not accounts:
            return []
        
        print(f"[公众号] 开始采集 {len(accounts)} 个公众号...")
        
        all_articles = []
        
        # 优先尝试 WeWe-RSS 批量采集
        if await self._check_wewe_rss():
            print(f"  [公众号] 使用 WeWe-RSS 批量采集...")
            all_articles = await self._fetch_all_from_wewe_rss()
            
            if all_articles:
                # 更新所有账号的采集状态
                for account in accounts:
                    account.last_fetched_at = datetime.now()
                    account.fetch_fail_count = 0
                    account.updated_at = datetime.now()
                
                try:
                    await db_session.commit()
                except Exception:
                    pass
                
                print(f"[公众号] WeWe-RSS 采集完成：共 {len(all_articles)} 篇文章")
                return all_articles
            else:
                print(f"  [公众号] WeWe-RSS 未获取到文章，降级到 RSSHub...")
        
        # 降级：逐个通过 RSSHub 采集
        print(f"  [公众号] 使用 RSSHub 逐个采集...")
        
        semaphore = asyncio.Semaphore(3)
        
        async def _fetch_one(account):
            async with semaphore:
                try:
                    articles = await self._fetch_from_rsshub(account.biz, account.name)
                    
                    if articles:
                        account.last_fetched_at = datetime.now()
                        account.total_articles += len(articles)
                        account.fetch_fail_count = 0
                    else:
                        account.fetch_fail_count += 1
                    
                    account.updated_at = datetime.now()
                    return articles
                except Exception as e:
                    print(f"  [公众号] {account.name} 采集失败: {e}")
                    account.fetch_fail_count += 1
                    account.updated_at = datetime.now()
                    return []
        
        tasks = [_fetch_one(acc) for acc in accounts]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success_count = 0
        for result in results:
            if isinstance(result, Exception):
                continue
            if result:
                all_articles.extend(result)
                success_count += 1
        
        try:
            await db_session.commit()
        except Exception:
            pass
        
        print(f"[公众号] RSSHub 采集完成: {success_count}/{len(accounts)} 个成功，共 {len(all_articles)} 篇文章")
        
        return all_articles
    
    # ==========================================
    # 工具方法
    # ==========================================
    
    @staticmethod
    def _clean_html(text: str) -> str:
        """清理 HTML 标签"""
        if not text:
            return ""
        # 简单清理 HTML
        import re
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'&[a-zA-Z]+;', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text


# 全局单例
_wechat_service: Optional[WechatSubscriptionService] = None


def get_wechat_service() -> WechatSubscriptionService:
    """获取公众号服务单例"""
    global _wechat_service
    if _wechat_service is None:
        _wechat_service = WechatSubscriptionService()
    return _wechat_service

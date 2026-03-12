"""
新闻采集服务
支持多源 RSS 抓取、网页爬取、去重和聚类
"""
import asyncio
import hashlib
import re
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
import uuid

import feedparser
import httpx
from bs4 import BeautifulSoup

from ..config import settings
from ..models.news import News, NewsCreate, SentimentType


@dataclass
class RawNewsItem:
    """原始新闻条目"""
    title: str
    content: str
    source: str
    source_url: str
    published_at: datetime


class NewsCollectorService:
    """新闻采集服务"""
    
    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )
        
        # RSS 源配置（使用多个备用源，提高可用性）
        self.rss_feeds = [
            # === 直接可用的 RSS 源（无需代理） ===
            {
                "url": "http://rss.xinhuanet.com/rss/fortune.xml",
                "name": "新华网财经",
                "category": "综合财经"
            },
            # === 备用 RSSHub 实例（尝试多个公共实例） ===
            {
                "url": "https://rsshub.rssforever.com/cls/telegraph",
                "name": "财联社电报",
                "category": "快讯"
            },
            {
                "url": "https://rsshub.rssforever.com/jin10/flash",
                "name": "金十数据",
                "category": "快讯"
            },
            {
                "url": "https://rsshub.rssforever.com/eastmoney/report/strategyreport",
                "name": "东方财富研报",
                "category": "研报"
            },
            # === 百度新闻 RSS（较稳定） ===
            {
                "url": "http://news.baidu.com/n?cmd=1&class=finannews&tn=rss&sub=0",
                "name": "百度财经焦点",
                "category": "综合财经"
            },
            {
                "url": "http://news.baidu.com/n?cmd=1&class=stock&tn=rss&sub=0",
                "name": "百度股票焦点",
                "category": "股票"
            }
        ]
        
        # 新闻去重缓存（基于标题哈希）
        self._seen_hashes: set = set()
        
        # 中国相关关键词
        self.china_keywords = [
            "中国", "人民币", "央行", "A股", "沪深", "港股",
            "中美", "贸易", "发改委", "工信部", "财政部",
            "北京", "上海", "深圳", "香港", "内地",
            "国企", "民企", "科创板", "创业板", "北交所"
        ]
    
    async def collect_all(self, hours: int = 24) -> List[News]:
        """
        采集所有来源的新闻
        
        Args:
            hours: 采集最近多少小时的新闻
            
        Returns:
            去重后的新闻列表
        """
        all_news = []
        
        # 并行采集所有 RSS 源
        tasks = [
            self._collect_rss(feed) 
            for feed in self.rss_feeds
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, Exception):
                print(f"采集出错: {result}")
                continue
            all_news.extend(result)
        
        # 去重
        unique_news = self._deduplicate(all_news)
        
        # 过滤时间范围
        cutoff_time = datetime.now() - timedelta(hours=hours)
        filtered_news = [
            n for n in unique_news 
            if n.published_at >= cutoff_time
        ]
        
        # 按重要性和时间排序
        filtered_news.sort(key=lambda x: (x.importance_score, x.published_at), reverse=True)
        
        print(f"[NEWS] 共采集到 {len(filtered_news)} 条新闻（原始 {len(all_news)} 条，去重后 {len(unique_news)} 条）")
        
        return filtered_news
    
    async def _collect_rss(self, feed_config: Dict[str, str]) -> List[News]:
        """采集单个 RSS 源"""
        news_list = []
        
        try:
            response = await self.client.get(feed_config["url"])
            response.raise_for_status()
            
            # 解析 RSS
            feed = feedparser.parse(response.text)
            
            for entry in feed.entries:
                try:
                    news = self._parse_rss_entry(entry, feed_config)
                    if news:
                        news_list.append(news)
                except Exception as e:
                    print(f"解析条目失败: {e}")
                    continue
            
            print(f"[OK] {feed_config['name']}: 获取 {len(news_list)} 条")
            
        except Exception as e:
            print(f"[FAIL] {feed_config['name']} 采集失败: {e}")
        
        return news_list
    
    def _parse_rss_entry(self, entry: Any, feed_config: Dict[str, str]) -> Optional[News]:
        """解析 RSS 条目为 News 对象"""
        # 提取标题
        title = entry.get("title", "").strip()
        if not title:
            return None
        
        # 提取内容
        content = ""
        if hasattr(entry, "content"):
            content = entry.content[0].value if entry.content else ""
        elif hasattr(entry, "summary"):
            content = entry.summary or ""
        elif hasattr(entry, "description"):
            content = entry.description or ""
        
        # 清理 HTML 标签
        content = self._clean_html(content)
        
        # 如果内容太短，用标题作为内容
        if len(content) < 50:
            content = title
        
        # 解析发布时间
        published_at = datetime.now()
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                published_at = datetime(*entry.published_parsed[:6])
            except:
                pass
        elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
            try:
                published_at = datetime(*entry.updated_parsed[:6])
            except:
                pass
        
        # 提取链接
        source_url = entry.get("link", "")
        
        # 创建新闻对象
        news_id = str(uuid.uuid4())
        
        # 计算重要性评分
        importance_score = self._calculate_importance(title, content)
        
        # 提取关键词
        keywords = self._extract_keywords(title + " " + content)
        
        # 提取关联股票
        related_stocks = self._extract_stock_codes(title + " " + content)
        
        return News(
            id=news_id,
            title=title,
            content=content,
            summary=content[:200] if len(content) > 200 else content,
            source=feed_config["name"],
            source_url=source_url,
            published_at=published_at,
            sentiment=SentimentType.NEUTRAL,  # 后续由 AI 分析
            importance_score=importance_score,
            keywords=keywords,
            related_stocks=related_stocks,
            created_at=datetime.now()
        )
    
    def _clean_html(self, text: str) -> str:
        """清理 HTML 标签"""
        if not text:
            return ""
        
        # 使用 BeautifulSoup 提取纯文本
        soup = BeautifulSoup(text, "lxml")
        text = soup.get_text(separator=" ")
        
        # 清理多余空白
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        return text
    
    def _calculate_importance(self, title: str, content: str) -> float:
        """计算新闻重要性评分"""
        score = 0.5  # 基础分
        
        combined_text = title + " " + content
        
        # 中国相关加分
        for keyword in self.china_keywords:
            if keyword in combined_text:
                score += 0.1
        
        # 重要信号词加分
        important_words = ["重磅", "突发", "暴跌", "暴涨", "央行", "降息", "加息", "政策", "监管"]
        for word in important_words:
            if word in combined_text:
                score += 0.15
        
        # 限制在 0-1 范围
        return min(1.0, max(0.0, score))
    
    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词"""
        # 简单实现：提取常见财经关键词
        finance_keywords = [
            "股市", "基金", "债券", "利率", "汇率", "通胀", "GDP",
            "科技", "新能源", "消费", "医药", "金融", "地产",
            "并购", "IPO", "减持", "增持", "回购", "分红"
        ]
        
        found = []
        for kw in finance_keywords:
            if kw in text:
                found.append(kw)
        
        return found[:10]  # 最多返回10个
    
    def _extract_stock_codes(self, text: str) -> List[str]:
        """提取股票代码"""
        codes = []
        
        # A股代码模式：6位数字
        a_share_pattern = r'\b(00[0-3]\d{3}|30[0-2]\d{3}|60[0-3]\d{3}|68[89]\d{3})\b'
        codes.extend(re.findall(a_share_pattern, text))
        
        # 港股代码模式：4-5位数字
        hk_pattern = r'\b(0[0-9]{4})\b'
        codes.extend(re.findall(hk_pattern, text))
        
        return list(set(codes))[:10]  # 去重，最多10个
    
    def _deduplicate(self, news_list: List[News]) -> List[News]:
        """新闻去重"""
        unique = []
        
        for news in news_list:
            # 基于标题生成哈希
            title_hash = hashlib.md5(news.title.encode()).hexdigest()
            
            if title_hash not in self._seen_hashes:
                self._seen_hashes.add(title_hash)
                unique.append(news)
        
        return unique
    
    def filter_china_related(self, news_list: List[News], min_score: float = 0.5) -> List[News]:
        """
        筛选中国相关新闻
        """
        china_news = []
        
        for news in news_list:
            text = news.title + " " + news.content
            
            # 检查是否包含中国相关关键词
            is_china_related = any(kw in text for kw in self.china_keywords)
            
            if is_china_related and news.importance_score >= min_score:
                china_news.append(news)
        
        return china_news
    
    async def close(self):
        """关闭 HTTP 客户端"""
        await self.client.aclose()


# 单例实例
_collector_instance: Optional[NewsCollectorService] = None


def get_news_collector() -> NewsCollectorService:
    """获取新闻采集服务实例"""
    global _collector_instance
    if _collector_instance is None:
        _collector_instance = NewsCollectorService()
    return _collector_instance

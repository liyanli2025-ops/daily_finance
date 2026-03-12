"""
RSS 解析工具
"""
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

import feedparser
from bs4 import BeautifulSoup


@dataclass
class RSSItem:
    """RSS 条目数据类"""
    title: str
    link: str
    description: str
    content: str
    author: Optional[str]
    published: datetime
    categories: List[str]
    

class RSSParser:
    """RSS 解析器"""
    
    @staticmethod
    def parse(xml_content: str) -> List[RSSItem]:
        """
        解析 RSS/Atom 内容
        
        Args:
            xml_content: RSS/Atom XML 字符串
            
        Returns:
            RSSItem 列表
        """
        items = []
        feed = feedparser.parse(xml_content)
        
        for entry in feed.entries:
            item = RSSParser._parse_entry(entry)
            if item:
                items.append(item)
        
        return items
    
    @staticmethod
    def _parse_entry(entry: Any) -> Optional[RSSItem]:
        """解析单个 RSS 条目"""
        try:
            # 标题
            title = entry.get("title", "").strip()
            if not title:
                return None
            
            # 链接
            link = entry.get("link", "")
            
            # 描述/摘要
            description = entry.get("summary", "") or entry.get("description", "")
            description = RSSParser._clean_html(description)
            
            # 完整内容
            content = ""
            if hasattr(entry, "content") and entry.content:
                content = entry.content[0].get("value", "")
            content = RSSParser._clean_html(content) or description
            
            # 作者
            author = entry.get("author")
            
            # 发布时间
            published = datetime.now()
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    published = datetime(*entry.published_parsed[:6])
                except:
                    pass
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                try:
                    published = datetime(*entry.updated_parsed[:6])
                except:
                    pass
            
            # 分类
            categories = []
            if hasattr(entry, "tags"):
                categories = [tag.get("term", "") for tag in entry.tags if tag.get("term")]
            
            return RSSItem(
                title=title,
                link=link,
                description=description[:500] if len(description) > 500 else description,
                content=content,
                author=author,
                published=published,
                categories=categories
            )
            
        except Exception as e:
            print(f"解析 RSS 条目失败: {e}")
            return None
    
    @staticmethod
    def _clean_html(html: str) -> str:
        """清理 HTML，提取纯文本"""
        if not html:
            return ""
        
        # 使用 BeautifulSoup 提取文本
        soup = BeautifulSoup(html, "html.parser")
        
        # 移除 script 和 style 标签
        for tag in soup(["script", "style"]):
            tag.decompose()
        
        # 获取文本
        text = soup.get_text(separator=" ")
        
        # 清理多余空白
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        return text
    
    @staticmethod
    def get_feed_info(xml_content: str) -> Dict[str, Any]:
        """
        获取 Feed 基本信息
        """
        feed = feedparser.parse(xml_content)
        
        return {
            "title": feed.feed.get("title", "Unknown"),
            "link": feed.feed.get("link", ""),
            "description": feed.feed.get("description", ""),
            "language": feed.feed.get("language", ""),
            "updated": feed.feed.get("updated", ""),
            "entry_count": len(feed.entries)
        }

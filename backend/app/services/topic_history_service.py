"""
话题历史追踪服务

从已有报告中提取近期讲过的话题/概念/行业，
生成去重提示注入到 AI prompt 中，避免多天出现重复内容。

设计原则：
- 不新建数据库表，直接查询现有 reports 表
- 解析报告 JSON 中的 new_concepts、concept_tutorials 等字段
- 同时从报告正文中提取"今日投资课堂"等模块的关键词
- 返回格式化的去重提示文本，直接嵌入 prompt
"""
import json
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import List, Dict, Optional

from ..config import settings


class TopicHistoryService:
    """话题历史追踪服务，用于报告/播客的话题去重"""
    
    def __init__(self):
        self._db_path = self._get_db_path()
    
    def _get_db_path(self) -> str:
        """获取数据库文件路径"""
        db_url = settings.database_url
        # sqlite:///path/to/db -> path/to/db
        if db_url.startswith("sqlite:///"):
            return db_url.replace("sqlite:///", "")
        return ""
    
    def get_recent_topics(self, days: int = 7) -> Dict[str, List[str]]:
        """
        获取最近 N 天报告中讲过的话题
        
        Returns:
            {
                "2026-03-30": ["低空经济", "量化交易策略"],
                "2026-03-29": ["DPU芯片", "注册制改革"],
                ...
            }
        """
        if not self._db_path or not Path(self._db_path).exists():
            print("[话题去重] 数据库文件不存在，跳过去重")
            return {}
        
        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            
            # 查询最近 N 天的报告
            cutoff_date = (date.today() - timedelta(days=days)).isoformat()
            cursor.execute("""
                SELECT report_date, report_type, content, core_opinions, 
                       highlights, cross_border_events, analysis
                FROM reports 
                WHERE report_date >= ? 
                ORDER BY report_date DESC
            """, (cutoff_date,))
            
            rows = cursor.fetchall()
            conn.close()
            
            if not rows:
                return {}
            
            # 按日期汇总话题
            topics_by_date: Dict[str, List[str]] = {}
            
            for row in rows:
                report_date_str = row[0]
                report_type = row[1] or "morning"
                content = row[2] or ""
                core_opinions_json = row[3]
                highlights_json = row[4]
                cross_border_json = row[5]
                analysis_json = row[6]
                
                date_key = f"{report_date_str}({report_type})"
                topics = set()
                
                # 1. 从 content 正文中提取课堂/概念相关内容
                topics.update(self._extract_topics_from_content(content))
                
                # 2. 从 JSON 字段中提取
                topics.update(self._extract_from_json_field(core_opinions_json))
                topics.update(self._extract_concepts_from_highlights(highlights_json))
                topics.update(self._extract_from_analysis(analysis_json))
                
                if topics:
                    topics_by_date[date_key] = list(topics)
            
            return topics_by_date
            
        except Exception as e:
            print(f"[话题去重] 查询历史话题失败: {e}")
            return {}
    
    def _extract_topics_from_content(self, content: str) -> set:
        """从报告正文中提取话题关键词"""
        topics = set()
        
        if not content:
            return topics
        
        # 匹配"投资课堂""概念科普""热点科普"等模块的标题和关键词
        patterns = [
            # 匹配模块标题后的概念名称
            r'(?:投资课堂|概念科普|热点科普|新概念)[^：:]*[：:]\s*(.+?)(?:\n|$)',
            # 匹配"今天讲讲""给你聊聊""科普一下"后面的主题
            r'(?:今天讲讲|给你聊聊|科普一下|深度解析|重点解读)\s*[「"《]?([^」"》\n]{2,20})[」"》]?',
            # 匹配 ### 开头的子标题中的概念（如 ### 低空经济：未来的万亿赛道）
            r'###\s*(?:概念|热点|行业)?[^：:]*?[：:]?\s*(.{2,15})(?:[：:—]|$)',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, content, re.MULTILINE)
            for match in matches:
                # 清洗：去掉数字序号、emoji、多余空白
                cleaned = re.sub(r'^[\d.\s#*]+', '', match.strip())
                cleaned = re.sub(r'[\U0001F000-\U0001FFFF]', '', cleaned).strip()
                if 2 <= len(cleaned) <= 20:
                    topics.add(cleaned)
        
        # 提取报告中 new_concepts JSON 字段（可能嵌在正文里）
        json_match = re.search(r'"new_concepts"\s*:\s*\[(.*?)\]', content)
        if json_match:
            try:
                concepts_str = '[' + json_match.group(1) + ']'
                concepts = json.loads(concepts_str)
                for c in concepts:
                    if isinstance(c, str) and 2 <= len(c) <= 20:
                        topics.add(c)
            except:
                pass
        
        # 提取 today_lesson 字段
        lesson_match = re.search(r'"today_lesson"\s*:\s*"([^"]+)"', content)
        if lesson_match:
            topics.add(lesson_match.group(1)[:20])
        
        # 提取 concept_tutorials
        tutorials_match = re.search(r'"concept_tutorials"\s*:\s*\[(.*?)\]', content, re.DOTALL)
        if tutorials_match:
            try:
                tutorials_str = '[' + tutorials_match.group(1) + ']'
                tutorials = json.loads(tutorials_str)
                for t in tutorials:
                    if isinstance(t, dict) and 'name' in t:
                        topics.add(t['name'])
            except:
                pass
        
        return topics
    
    def _extract_from_json_field(self, json_str) -> set:
        """从 JSON 字段中提取话题"""
        topics = set()
        if not json_str:
            return topics
        
        try:
            data = json.loads(json_str) if isinstance(json_str, str) else json_str
            
            if isinstance(data, list):
                # core_opinions 是列表
                for item in data:
                    if isinstance(item, str):
                        # 提取建议中提到的板块/概念（简单启发式）
                        # 如 "今日加仓半导体板块" -> "半导体"
                        sector_match = re.findall(r'([\u4e00-\u9fa5]{2,6})(?:板块|概念|行业|赛道)', item)
                        topics.update(sector_match)
        except:
            pass
        
        return topics
    
    def _extract_concepts_from_highlights(self, json_str) -> set:
        """从 highlights JSON 中提取概念"""
        topics = set()
        if not json_str:
            return topics
        
        try:
            data = json.loads(json_str) if isinstance(json_str, str) else json_str
            if isinstance(data, list):
                for h in data:
                    if isinstance(h, dict):
                        # 从标题中提取概念
                        title = h.get('title', '')
                        if title:
                            sector_match = re.findall(r'([\u4e00-\u9fa5]{2,6})(?:板块|概念|行业|赛道)', title)
                            topics.update(sector_match)
        except:
            pass
        
        return topics
    
    def _extract_from_analysis(self, json_str) -> set:
        """从 analysis JSON 中提取话题"""
        topics = set()
        if not json_str:
            return topics
        
        try:
            data = json.loads(json_str) if isinstance(json_str, str) else json_str
            if isinstance(data, dict):
                # hot_themes, hot_sectors 等
                for key in ['hot_themes', 'hot_sectors', 'opportunities']:
                    items = data.get(key, [])
                    if isinstance(items, list):
                        for item in items:
                            if isinstance(item, str) and 2 <= len(item) <= 20:
                                topics.add(item)
        except:
            pass
        
        return topics
    
    def format_dedup_prompt(self, days: int = 7) -> str:
        """
        生成话题去重提示文本，可直接嵌入 AI prompt
        
        Returns:
            格式化的去重提示，如果没有历史话题则返回空字符串
        """
        topics_by_date = self.get_recent_topics(days)
        
        if not topics_by_date:
            return ""
        
        lines = [
            "\n## ⚠️ 话题去重要求（重要！）\n",
            "以下话题/概念在最近报告中已经讲过，**请务必选择全新的、不同的话题**：\n"
        ]
        
        for date_key, topics in topics_by_date.items():
            if topics:
                topics_str = "、".join(topics[:8])  # 每天最多显示8个
                lines.append(f"- {date_key}：{topics_str}")
        
        lines.append("")
        lines.append("**要求**：")
        lines.append("1. 今日投资课堂/概念科普的主题必须与上述列表完全不同")
        lines.append("2. 可以选择：当下最新的热点事件、冷门但有价值的投资知识、新兴行业趋势、经典投资理论的新应用等")
        lines.append("3. 如果实在没有全新话题，可以从全新角度解读已有话题（但角度必须完全不同）")
        lines.append("")
        
        return "\n".join(lines)


# 单例
_topic_history_instance: Optional[TopicHistoryService] = None


def get_topic_history_service() -> TopicHistoryService:
    """获取话题历史服务实例"""
    global _topic_history_instance
    if _topic_history_instance is None:
        _topic_history_instance = TopicHistoryService()
    return _topic_history_instance

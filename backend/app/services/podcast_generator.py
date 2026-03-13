"""
播客生成服务
使用 Edge TTS 将报告文本转换为音频
"""
import asyncio
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List
import uuid

import edge_tts

from ..config import settings
from ..models.report import Report


class PodcastGeneratorService:
    """播客生成服务"""
    
    def __init__(self):
        # TTS 配置
        self.voice = settings.tts_voice  # 默认：zh-CN-YunxiNeural（男声，清晰专业）
        self.rate = settings.tts_rate     # 语速
        self.volume = settings.tts_volume # 音量
        
        # 可用的中文语音角色
        self.available_voices = {
            "zh-CN-YunxiNeural": "云希（男声，年轻，适合新闻播报）",
            "zh-CN-YunjianNeural": "云健（男声，成熟，适合财经分析）",
            "zh-CN-XiaoxiaoNeural": "晓晓（女声，温和，适合日常播报）",
            "zh-CN-XiaoyiNeural": "晓依（女声，专业，适合正式内容）",
        }
        
        # 输出目录
        self.output_dir = Path(settings.podcasts_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    async def generate_podcast(self, report: Report) -> tuple[str, int]:
        """
        为报告生成播客音频
        
        Args:
            report: 报告对象
            
        Returns:
            (音频文件路径, 时长秒数)
        """
        # 准备播客文本
        podcast_text = self._prepare_podcast_text(report)
        
        # 生成音频文件名
        filename = f"{report.id}.mp3"
        output_path = self.output_dir / filename
        
        # 生成音频
        communicate = edge_tts.Communicate(
            text=podcast_text,
            voice=self.voice,
            rate=self.rate,
            volume=self.volume
        )
        
        await communicate.save(str(output_path))
        
        # 估算时长（大约每分钟 250 字）
        word_count = len(podcast_text)
        duration_seconds = int((word_count / 250) * 60)
        
        # 确保在 20-30 分钟范围内
        duration_seconds = max(1200, min(1800, duration_seconds))
        
        print(f"✅ 播客生成完成: {filename}, 时长约 {duration_seconds // 60} 分钟")
        
        return str(output_path), duration_seconds
    
    def _prepare_podcast_text(self, report: Report) -> str:
        """
        准备播客文本 - 差异化风格（观点输出 + 财经脱口秀）
        不是念报告，而是提炼核心观点，加入主播个人判断
        """
        # 开场白（轻松活泼风格）
        opening = f"""
各位听众朋友，大家好！欢迎收听今天的财经脱口秀。
今天是{report.report_date.strftime('%Y年%m月%d日')}，我是老李。
废话不多说，直接上干货！

今天的报告标题是：{report.title}

"""
        
        # 核心观点（如果有）- 开门见山
        core_opinions_text = ""
        if hasattr(report, 'core_opinions') and report.core_opinions:
            core_opinions_text = """
先说今天我的三个核心判断，听好了：

"""
            for i, opinion in enumerate(report.core_opinions, 1):
                core_opinions_text += f"第{i}个判断：{opinion}\n\n"
            core_opinions_text += """
这三条判断，你可以不信，但我建议你记下来，一周后回来对照看看我说得准不准。

"""
        else:
            # 使用摘要作为核心内容
            core_opinions_text = f"""
今天的核心内容是：{report.summary}

接下来我展开聊聊。

"""
        
        # 跨界热点分析（如果有）- 这是差异化的重点
        cross_border_text = ""
        if hasattr(report, 'cross_border_events') and report.cross_border_events:
            cross_border_text = """

说完财经新闻，我们聊聊今天的跨界热点。
很多人只盯着财经频道，其实很多影响股市的大事，都发生在财经圈外面。

"""
            for event in report.cross_border_events:
                category_name = {
                    "geopolitical": "地缘政治",
                    "tech": "科技圈",
                    "social": "社会热点",
                    "disaster": "自然灾害"
                }.get(event.category.value, "其他")
                
                cross_border_text += f"""
来看一个{category_name}的事件：{event.title}

简单说就是：{event.summary}

这对股市有什么影响？我跟你说：
直接影响是：{event.market_impact_direct}
间接影响是：{event.market_impact_indirect}

历史上类似情况：{event.historical_reference}

所以受益的可能是：{', '.join(event.beneficiaries) if event.beneficiaries else '暂无明确受益方'}
受损的可能是：{', '.join(event.losers) if event.losers else '暂无明确受损方'}

我的建议是：{event.follow_up_advice}

"""
        
        # 重点新闻 + 我的看法
        highlights_text = ""
        if report.highlights:
            highlights_text = """

好，接下来聊聊今天的几条重要新闻，以及我的个人看法。

"""
            for i, h in enumerate(report.highlights[:3], 1):  # 只取前3条重点说
                sentiment_opinion = {
                    "positive": "我觉得这是个好消息",
                    "negative": "这条消息需要警惕",
                    "neutral": "这条消息影响不大"
                }.get(h.sentiment.value, "")
                
                highlights_text += f"""
第{i}条：{h.title}

{h.summary}

{sentiment_opinion}。
"""
                if h.historical_context:
                    highlights_text += f"从历史经验看：{h.historical_context}\n"
                
                highlights_text += "\n"
        
        # 市场分析 + 操作建议
        analysis_text = ""
        if report.analysis:
            trend_opinion = {
                "bullish": "我个人倾向于看多",
                "bearish": "我觉得需要谨慎一些",
                "neutral": "目前我保持观望"
            }.get(report.analysis.trend.value, "")
            
            analysis_text = f"""

说说我对整体市场的看法。

{trend_opinion}。原因很简单：

关键因素就这几个：{', '.join(report.analysis.key_factors)}

如果你问我现在该买什么？我觉得机会在：{', '.join(report.analysis.opportunities)}

但也要注意这些风险：{', '.join(report.analysis.risks)}

记住，投资没有绝对的对错，关键是你要有自己的判断逻辑。

"""
        
        # 处理报告正文的关键段落
        key_content = self._extract_key_paragraphs(report.content)
        
        # 结束语（有态度的风格）
        closing = """

好了，今天的财经脱口秀就到这里。

总结一下今天的核心观点：
第一，关注政策面的变化；
第二，重点板块可以逢低布局；
第三，风险管理永远是第一位的。

最后送给大家一句话：投资不是赌博，是认知的变现。
知道自己为什么买、为什么卖，比知道买什么更重要。

感谢收听，我们明天再见！
"""
        
        # 组合完整文本
        full_text = opening + core_opinions_text + key_content + cross_border_text + highlights_text + analysis_text + closing
        
        # 控制字数在合理范围（5000-7500字，对应20-30分钟）
        if len(full_text) > 7500:
            # 截断并添加总结
            full_text = full_text[:7000] + """

由于时间关系，今天就先聊到这里。
更详细的分析可以在App里看完整报告。

""" + closing
        elif len(full_text) < 4000:
            # 内容不足时，添加更多观点
            padding = f"""

让我再补充几点个人看法。

关于当前市场，我认为最重要的是把握节奏。
不要急于追涨，也不要盲目恐惧。
记住：别人恐惧时贪婪，别人贪婪时恐惧。

今天的市场情况：{report.summary}

"""
            full_text = full_text.replace(closing, padding + closing)
        
        return full_text
    
    def _extract_key_paragraphs(self, content: str) -> str:
        """从报告内容中提取关键段落用于播客"""
        # 清理Markdown格式
        text = self._clean_for_tts(content)
        
        # 只保留前2000字的核心内容
        if len(text) > 2000:
            # 尝试找到自然断点
            cutoff = text.find('。', 1800)
            if cutoff > 0:
                text = text[:cutoff + 1]
            else:
                text = text[:2000] + "..."
        
        return text
    
    def _clean_for_tts(self, markdown_text: str) -> str:
        """
        清理 Markdown 文本，使其适合 TTS 朗读
        """
        text = markdown_text
        
        # 移除代码块
        text = re.sub(r'```[\s\S]*?```', '', text)
        
        # 移除行内代码
        text = re.sub(r'`[^`]+`', '', text)
        
        # 转换标题为朗读格式
        text = re.sub(r'^#{1,6}\s+(.+)$', r'\n\n\1\n', text, flags=re.MULTILINE)
        
        # 移除链接，保留文字
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        
        # 移除图片
        text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
        
        # 转换列表项
        text = re.sub(r'^[-*]\s+', '• ', text, flags=re.MULTILINE)
        text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)
        
        # 移除粗体/斜体标记
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
        text = re.sub(r'\*([^*]+)\*', r'\1', text)
        text = re.sub(r'__([^_]+)__', r'\1', text)
        text = re.sub(r'_([^_]+)_', r'\1', text)
        
        # 处理表格（简单移除）
        text = re.sub(r'\|[^\n]+\|', '', text)
        text = re.sub(r'^[-|:]+$', '', text, flags=re.MULTILINE)
        
        # 替换一些符号为可朗读的文字
        text = text.replace('&', '和')
        text = text.replace('%', '百分之')
        text = text.replace('①', '第一')
        text = text.replace('②', '第二')
        text = text.replace('③', '第三')
        
        # 清理多余空行
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # 添加适当的停顿标记
        text = text.replace('。', '。\n')
        text = text.replace('；', '；')
        text = text.replace('？', '？\n')
        text = text.replace('！', '！\n')
        
        return text.strip()
    
    async def list_voices(self) -> List[dict]:
        """列出所有可用的中文语音"""
        voices = await edge_tts.list_voices()
        chinese_voices = [
            v for v in voices 
            if v['Locale'].startswith('zh-CN')
        ]
        return chinese_voices
    
    def set_voice(self, voice: str):
        """设置语音角色"""
        if voice in self.available_voices:
            self.voice = voice
            print(f"✅ 语音已切换为: {self.available_voices[voice]}")
        else:
            print(f"⚠️ 未知的语音角色: {voice}")


# 单例实例
_podcast_generator: Optional[PodcastGeneratorService] = None


def get_podcast_generator() -> PodcastGeneratorService:
    """获取播客生成服务实例"""
    global _podcast_generator
    if _podcast_generator is None:
        _podcast_generator = PodcastGeneratorService()
    return _podcast_generator

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
        准备播客文本
        将 Markdown 报告转换为适合朗读的文本
        """
        # 开场白
        opening = f"""
各位听众朋友，大家好！欢迎收听今天的财经深度日报。
今天是{report.report_date.strftime('%Y年%m月%d日')}，我是您的AI财经主播。
接下来我将为您播报今日的财经要闻和深度分析。

今日报告的标题是：{report.title}

首先，让我为您简要概述一下今天的核心内容：
{report.summary}

好的，接下来让我们进入详细内容。
"""
        
        # 处理报告正文
        content = self._clean_for_tts(report.content)
        
        # 重点新闻
        highlights_text = ""
        if report.highlights:
            highlights_text = "\n\n接下来是今日重点新闻：\n\n"
            for i, h in enumerate(report.highlights, 1):
                sentiment_text = {
                    "positive": "这是一条利好消息",
                    "negative": "这是一条需要关注的风险信息",
                    "neutral": "这是一条中性消息"
                }.get(h.sentiment.value, "")
                
                highlights_text += f"""
第{i}条：{h.title}
来源：{h.source}
{h.summary}
{sentiment_text}。
"""
                if h.historical_context:
                    highlights_text += f"背景信息：{h.historical_context}\n"
        
        # 市场分析
        analysis_text = ""
        if report.analysis:
            trend_text = {
                "bullish": "整体偏向看多",
                "bearish": "整体偏向谨慎",
                "neutral": "保持中性观望"
            }.get(report.analysis.trend.value, "")
            
            analysis_text = f"""

接下来是今日市场分析：

当前市场整体情绪为{report.analysis.overall_sentiment.value}，{trend_text}。

关键影响因素包括：{', '.join(report.analysis.key_factors)}

值得关注的投资机会：{', '.join(report.analysis.opportunities)}

需要注意的风险点：{', '.join(report.analysis.risks)}
"""
        
        # 结束语
        closing = """

好的，以上就是今天财经深度日报的全部内容。

感谢您的收听！如果您觉得今天的内容对您有帮助，欢迎分享给您的朋友。

我们明天同一时间再见！祝您投资顺利，财源广进！
"""
        
        # 组合完整文本
        full_text = opening + content + highlights_text + analysis_text + closing
        
        # 控制字数在合理范围（5000-7500字，对应20-30分钟）
        if len(full_text) > 7500:
            full_text = full_text[:7500] + "\n\n由于时间关系，今天的详细内容就播报到这里。完整报告请在App内查看。\n" + closing
        elif len(full_text) < 5000:
            # 内容不足时，可以添加一些填充语
            padding = "\n\n让我们稍微总结一下今天的要点...\n" + report.summary + "\n"
            full_text = full_text.replace(closing, padding + closing)
        
        return full_text
    
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

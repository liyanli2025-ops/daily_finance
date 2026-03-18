"""
播客生成服务
使用 Edge TTS 将报告文本转换为音频
"""
import asyncio
import os
import re
import random
from datetime import datetime, date
from pathlib import Path
from typing import Optional, List
import uuid

import edge_tts
import httpx

from ..config import settings
from ..models.report import Report
from .audio_mixer import get_audio_mixer


class PodcastGeneratorService:
    """播客生成服务"""
    
    def __init__(self):
        # TTS 配置
        self.voice = settings.tts_voice  # 默认：zh-CN-YunxiNeural（男声，清晰专业）
        self.rate = settings.tts_rate     # 语速
        self.volume = settings.tts_volume # 音量
        
        # 【优化】从配置读取用户昵称
        self.user_nickname = settings.user_nickname or "朋友"
        
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
        
        # 初始化开场白模板（使用用户昵称）
        self._init_openings()
        
        # HTTP客户端用于获取天气
        self.http_client = None
    
    def _init_openings(self):
        """初始化开场白模板，使用配置的用户昵称"""
        name = self.user_nickname
        
        # 工作日多样化开场白模板
        self.weekday_openings = [
            f"{name}，早上好！新的一天开始了，让我们一起看看今天的财经大事。",
            f"{name}你好呀！又是元气满满的一天，今天的市场有什么新动向呢？",
            f"嗨，{name}！准备好了吗？今天的财经快报马上开始。",
            f"{name}，早安！咖啡准备好了吗？边喝边听今天的市场分析吧。",
            f"{name}，今天又是充满机会的一天！让我们看看市场在说什么。",
            f"Hello{name}！通勤路上就让我来陪你，一起聊聊今天的财经热点。",
            f"{name}早！新的一周，新的机会，今天的报告干货满满哦。",
            f"{name}，起床啦！今天的市场消息已经为你整理好了。",
        ]
        
        # 周末特别开场白
        self.weekend_openings = [
            f"{name}，周末愉快！虽然A股和港股今天休市，但我们可以趁机复盘本周，展望下周。",
            f"{name}你好！难得的周末时光，让我们轻松聊聊这周的市场和下周的机会。",
            f"嗨{name}，周末好！今天咱们不着急，慢慢聊聊这周发生的大事。",
            f"{name}，休息日快乐！市场虽然休息了，但我们的思考不能停。",
        ]
    
    async def _get_http_client(self):
        """获取或创建HTTP客户端"""
        if self.http_client is None:
            self.http_client = httpx.AsyncClient(timeout=10.0)
        return self.http_client
    
    async def get_beijing_weather(self) -> str:
        """
        获取北京当天的天气情况
        使用免费的天气API
        """
        try:
            client = await self._get_http_client()
            
            # 使用 wttr.in 免费天气服务
            url = "https://wttr.in/Beijing?format=%C+%t+%h+%w&lang=zh-cn"
            response = await client.get(url, headers={"User-Agent": "curl/7.68.0"})
            
            if response.status_code == 200:
                weather_raw = response.text.strip()
                # 格式化天气信息
                return f"北京今天的天气：{weather_raw}。"
            
            # 备用方案：使用另一个API
            backup_url = "https://api.seniverse.com/v3/weather/now.json?key=demo&location=beijing&language=zh-Hans"
            response = await client.get(backup_url)
            if response.status_code == 200:
                data = response.json()
                result = data.get("results", [{}])[0]
                now = result.get("now", {})
                weather_text = now.get("text", "晴")
                temperature = now.get("temperature", "20")
                return f"北京今天{weather_text}，气温{temperature}度。"
                
        except Exception as e:
            print(f"[天气] 获取天气失败: {e}")
        
        # 获取失败时返回通用语句
        return "今天北京天气不错。"
    
    def _is_weekend(self, check_date: date = None) -> bool:
        """判断是否是周末"""
        if check_date is None:
            check_date = date.today()
        # 如果是字符串，转换为 date 对象
        if isinstance(check_date, str):
            try:
                check_date = datetime.strptime(check_date, "%Y-%m-%d").date()
            except ValueError:
                check_date = date.today()
        return check_date.weekday() >= 5  # 5是周六，6是周日
    
    def _get_random_opening(self, is_weekend: bool = False) -> str:
        """获取随机开场白"""
        if is_weekend:
            return random.choice(self.weekend_openings)
        return random.choice(self.weekday_openings)
    
    async def generate_podcast(self, report: Report) -> tuple[str, int]:
        """
        为报告生成播客音频
        
        Args:
            report: 报告对象
            
        Returns:
            (音频文件路径, 时长秒数)
        """
        # 获取北京天气
        weather_info = await self.get_beijing_weather()
        
        # 准备播客文本（传入天气信息）
        podcast_text = self._prepare_podcast_text(report, weather_info)
        
        # 生成音频文件名
        filename = f"{report.id}.mp3"
        output_path = self.output_dir / filename
        
        # 临时文件（用于TTS输出，之后会与背景音乐混合）
        temp_path = self.output_dir / f"{report.id}_voice.mp3"
        
        # 分段生成语音（在 [SECTION_BREAK] 处分段，并加入停顿）
        await self._generate_segmented_tts(podcast_text, str(temp_path))
        
        # 与背景音乐混合
        audio_mixer = get_audio_mixer()
        if audio_mixer.has_bgm():
            print(f"[BGM] 检测到背景音乐，开始混音...")
            audio_mixer.mix_podcast_with_bgm(str(temp_path), str(output_path))
            # 删除临时文件
            try:
                os.remove(str(temp_path))
            except:
                pass
        else:
            # 没有背景音乐，直接重命名
            print(f"[INFO] 未配置背景音乐，使用纯语音")
            if temp_path != output_path:
                os.rename(str(temp_path), str(output_path))
        
        # 获取实际音频时长
        try:
            # 使用 audio_mixer 模块中已配置好 ffmpeg 路径的 AudioSegment
            from .audio_mixer import AudioSegment
            audio = AudioSegment.from_mp3(str(output_path))
            duration_seconds = len(audio) // 1000
        except Exception as e:
            print(f"[WARN] 无法获取音频时长: {e}")
            # 估算时长（大约每分钟 250 字）
            word_count = len(podcast_text)
            duration_seconds = int((word_count / 250) * 60)
            # 如果有背景音乐，加上开头和结尾的额外时间
            if audio_mixer.has_bgm():
                duration_seconds += 8  # 4秒开头 + 4秒结尾
        
        print(f"[OK] 播客生成完成: {filename}, 时长约 {duration_seconds // 60} 分 {duration_seconds % 60} 秒")
        
        return str(output_path), duration_seconds

    async def _generate_segmented_tts(self, full_text: str, output_path: str):
        """
        分段生成 TTS，在模块之间加入停顿
        
        通过 [SECTION_BREAK] 标记分段，每段之间加入 1.5 秒停顿
        """
        # 使用 audio_mixer 模块中已配置好 ffmpeg 路径的 AudioSegment
        from .audio_mixer import AudioSegment
        import tempfile
        
        # 分段
        segments = full_text.split('[SECTION_BREAK]')
        segments = [s.strip() for s in segments if s.strip()]
        
        print(f"[TTS] 检测到 {len(segments)} 个内容模块")
        
        if len(segments) <= 1:
            # 没有分段标记，直接生成
            communicate = edge_tts.Communicate(
                text=full_text.replace('[SECTION_BREAK]', ''),
                voice=self.voice,
                rate=self.rate,
                volume=self.volume
            )
            await communicate.save(output_path)
            return
        
        # 创建临时目录存放分段音频
        temp_dir = Path(tempfile.gettempdir()) / f"podcast_segments_{uuid.uuid4().hex[:8]}"
        temp_dir.mkdir(exist_ok=True)
        
        try:
            # 生成每个段落的音频
            segment_files = []
            for i, segment in enumerate(segments):
                if not segment:
                    continue
                    
                segment_path = temp_dir / f"segment_{i:02d}.mp3"
                print(f"[TTS] 正在生成第 {i+1}/{len(segments)} 段...")
                
                communicate = edge_tts.Communicate(
                    text=segment,
                    voice=self.voice,
                    rate=self.rate,
                    volume=self.volume
                )
                await communicate.save(str(segment_path))
                segment_files.append(segment_path)
            
            # 合并所有段落，中间加入停顿
            print(f"[TTS] 正在合并音频段落...")
            
            # 1.5 秒的静音停顿
            pause_duration = 1500  # 毫秒
            pause = AudioSegment.silent(duration=pause_duration)
            
            # 合并
            final_audio = AudioSegment.empty()
            for i, segment_path in enumerate(segment_files):
                segment_audio = AudioSegment.from_mp3(str(segment_path))
                final_audio += segment_audio
                
                # 在段落之间加入停顿（最后一段不加）
                if i < len(segment_files) - 1:
                    final_audio += pause
            
            # 导出最终音频
            final_audio.export(output_path, format="mp3", bitrate="192k")
            print(f"[TTS] 分段合成完成，共 {len(segment_files)} 段")
            
        finally:
            # 清理临时文件
            import shutil
            try:
                shutil.rmtree(temp_dir)
            except:
                pass
    
    def _prepare_podcast_text(self, report: Report, weather_info: str = "") -> str:
        """
        准备播客文本 - 精简版（观点输出 + 财经脱口秀）
        
        结构（每个信息只说一遍）：
        1. 开场白（天气 + 日期）
        2. 核心判断（3句话，最重要的结论）
        3. 报告正文精华（去重后的深度内容）
        4. 跨界热点（差异化内容，与正文不重复）
        5. 结束语（基于当天核心观点动态总结）
        
        去掉了：
        - highlights_text（重点新闻已在报告正文 key_content 里覆盖）
        - analysis_text（市场分析已在核心观点和报告正文里覆盖）
        - 固定模板的结尾总结（改为动态生成）
        - 内容不足时的鸡汤填充
        """
        report_date = report.report_date
        # 确保 report_date 是 date 对象
        if isinstance(report_date, str):
            try:
                report_date = datetime.strptime(report_date, "%Y-%m-%d").date()
            except ValueError:
                report_date = date.today()
        
        is_weekend = self._is_weekend(report_date)
        weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        weekday_name = weekday_names[report_date.weekday()]
        
        # 用户昵称
        name = self.user_nickname
        
        # 随机选择开场白
        random_greeting = self._get_random_opening(is_weekend)
        
        # 开场白（包含天气和日期）
        opening = f"""
{random_greeting}

{weather_info}

今天是{report_date.strftime('%Y年%m月%d日')}，{weekday_name}。
"""
        
        # 周末特别提示
        if is_weekend:
            opening += """
温馨提示：今天是周末，A股和港股都休市哦。
所以今天的内容主要是本周回顾和下周展望，帮你做好投资规划。

[SECTION_BREAK]
"""
        else:
            opening += """
废话不多说，直接上干货！

[SECTION_BREAK]
"""
        
        # 核心观点（如果有）- 开门见山
        core_opinions_text = ""
        if hasattr(report, 'core_opinions') and report.core_opinions:
            if is_weekend:
                core_opinions_text = """
先说说本周我的几个核心判断：

"""
            else:
                core_opinions_text = f"""
{name}，先说说我今天的核心判断，听好了：

"""
            for i, opinion in enumerate(report.core_opinions, 1):
                core_opinions_text += f"第{i}个判断：{opinion}\n\n"
            
            if is_weekend:
                core_opinions_text += """
这些判断，你可以下周开盘后观察验证一下。

[SECTION_BREAK]
"""
            else:
                core_opinions_text += """
这几条判断，记下来，过几天回来对照看看准不准。

[SECTION_BREAK]
"""
        else:
            # 使用摘要作为核心内容
            core_opinions_text = f"""
{name}，今天的核心内容是：{report.summary}

接下来我展开聊聊。

[SECTION_BREAK]
"""
        
        # 跨界热点分析（如果有）- 这是差异化的重点，和报告正文不重复
        cross_border_text = ""
        if hasattr(report, 'cross_border_events') and report.cross_border_events:
            cross_border_text = f"""

[SECTION_BREAK]

{name}，聊聊跨界热点。很多影响股市的大事，其实发生在财经圈外面。

"""
            for event in report.cross_border_events:
                category_name = {
                    "geopolitical": "地缘政治",
                    "tech": "科技圈",
                    "social": "社会热点",
                    "disaster": "自然灾害"
                }.get(event.category.value, "其他")
                
                cross_border_text += f"""
{category_name}方面：{event.title}

简单说就是：{event.summary}

对股市的影响：{event.market_impact_direct}
{event.market_impact_indirect}

受益方：{', '.join(event.beneficiaries) if event.beneficiaries else '暂无明确受益方'}
受损方：{', '.join(event.losers) if event.losers else '暂无明确受损方'}

我的建议：{event.follow_up_advice}

"""
        
        # 处理报告正文的关键段落（已通过 _extract_key_paragraphs 去重和精炼）
        key_content = self._extract_key_paragraphs(report.content)
        
        # 结束语 - 基于当天实际核心观点动态生成
        closing = self._generate_dynamic_closing(report, name, is_weekend)
        
        # 组合完整文本（去掉了 highlights_text 和 analysis_text，避免重复）
        full_text = opening + core_opinions_text + key_content + cross_border_text + closing
        
        # 控制字数在合理范围（3000-6000字，对应12-24分钟）
        if len(full_text) > 6000:
            # 截断并添加总结
            full_text = full_text[:5500] + f"""

{name}，时间关系，今天就先聊到这里。更详细的内容可以在App里看完整报告。

""" + closing
        
        return full_text
    
    def _generate_dynamic_closing(self, report: Report, name: str, is_weekend: bool) -> str:
        """
        基于当天报告内容动态生成结尾总结，不使用固定模板
        """
        closing = f"""

[SECTION_BREAK]

好了{name}，"""
        
        if is_weekend:
            closing += "今天的周末财经复盘就到这里。\n\n"
        else:
            closing += "今天的财经快报就到这里。\n\n"
        
        # 用实际核心观点做总结
        if hasattr(report, 'core_opinions') and report.core_opinions:
            closing += "帮你划个重点：\n"
            for i, opinion in enumerate(report.core_opinions, 1):
                # 提取观点的前30个字作为精炼总结
                short_opinion = opinion[:30].rstrip('，。、；') if len(opinion) > 30 else opinion.rstrip('，。、；')
                closing += f"第{i}，{short_opinion}。\n"
            closing += "\n"
        
        # 如果有市场趋势判断，加一句简短的态度
        if report.analysis:
            trend_one_liner = {
                "bullish": "整体我偏乐观，但仓位控制好。",
                "bearish": "短期注意风险，别急着抄底。",
                "neutral": "震荡市别追涨杀跌，耐心等机会。"
            }.get(report.analysis.trend.value, "")
            if trend_one_liner:
                closing += f"{trend_one_liner}\n\n"
        
        if is_weekend:
            closing += f"{name}，周末愉快！我们下周再见！\n"
        else:
            closing += f"{name}，今天就聊到这，我们明天见！\n"
        
        return closing
    
    def _extract_key_paragraphs(self, content: str) -> str:
        """
        从报告内容中提取关键段落用于播客
        
        优化：跳过报告开头的标题、引言、开场白部分，直接从"模块"开始
        避免与播客自己的开场白重复
        """
        # 先尝试找到"模块"开始的位置，跳过报告开头的引言部分
        # 常见的模块标记：## 模块1、## 模块一、**模块1**、模块1：等
        import re
        
        # 定位模块开始位置的正则模式
        module_patterns = [
            r'##\s*模块\s*[1一]',           # ## 模块1 或 ## 模块一
            r'\*\*模块\s*[1一]',             # **模块1**
            r'模块\s*[1一][：:、]',           # 模块1：或 模块1、
            r'##\s*[🔍📊💡🎯📌⚡🔥]\s*模块', # 带emoji的模块标题
            r'#\s+.*核心.*复盘',              # # 本周核心复盘 等周末模式
        ]
        
        module_start = -1
        for pattern in module_patterns:
            match = re.search(pattern, content)
            if match:
                module_start = match.start()
                break
        
        # 如果找到模块位置，从该位置开始提取
        if module_start > 0:
            content = content[module_start:]
            print(f"[播客] 跳过报告开头，从模块位置开始（跳过了 {module_start} 字符）")
        
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
        
        优化项：
        1. 粗体标记(**)转为停顿（气口）
        2. 过滤emoji表情符号
        3. 过滤新闻来源标注（如"新闻1"、"据新闻2"、"[1]"等）
        """
        text = markdown_text
        
        # ========== 1. 处理粗体为气口停顿 ==========
        # 粗体内容后加逗号作为气口停顿
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1，', text)
        text = re.sub(r'__([^_]+)__', r'\1，', text)
        
        # ========== 2. 移除emoji表情符号 ==========
        # 使用更精确的emoji范围，避免误删中文
        emoji_ranges = [
            ('\U0001F600', '\U0001F64F'),  # 表情符号
            ('\U0001F300', '\U0001F5FF'),  # 符号和象形文字
            ('\U0001F680', '\U0001F6FF'),  # 交通和地图符号
            ('\U0001F900', '\U0001F9FF'),  # 补充符号
            ('\U0001FA00', '\U0001FAFF'),  # 扩展符号
            ('\U00002600', '\U000026FF'),  # 杂项符号
            ('\U00002700', '\U000027BF'),  # 装饰符号
            ('\U0001F1E0', '\U0001F1FF'),  # 国旗
        ]
        for start, end in emoji_ranges:
            text = re.sub(f'[{start}-{end}]', '', text)
        
        # 移除特定常用emoji（可能不在上述范围内的）
        specific_emojis = '📊📈📉💹💰🔥⚠️✅❌⭐🌟💡🎯📌📍🔴🟢🟡🎉🎊👍👎💪🙏❤️💙💚💛🧡💜🖤🤍🤎'
        for emoji in specific_emojis:
            text = text.replace(emoji, '')
        
        # ========== 3. 移除新闻来源标注 ==========
        # 注意：顺序很重要！先匹配长的模式，再匹配短的模式
        
        # 移除 [1] [2] 等纯数字方括号引用
        text = re.sub(r'\[\d+\]', '', text)
        # 移除 [新闻1] [来源2] 等方括号引用
        text = re.sub(r'\[(新闻|来源|参考)\d*\]', '', text)
        
        # 先处理包含前缀的模式（"据新闻X"、"根据新闻X"）
        # 移除 "据新闻1，" "根据新闻2，" 等表述（完整移除包括前缀）
        text = re.sub(r'根据新闻\d+[，,]?\s*', '', text)  # 先处理"根据新闻"（更长）
        text = re.sub(r'据新闻\d+[，,]?\s*', '', text)    # 再处理"据新闻"
        
        # 再处理独立的 "新闻X" 标注
        # 移除 "新闻1：" "新闻2、" 等独立标注（后面有标点的）
        text = re.sub(r'新闻\d+[：:、，,]', '', text)
        # 移除句首的 "新闻X" 后跟动词（新闻1显示... -> ...）
        text = re.sub(r'新闻\d+(?:显示|报道|称|指出|表示)[，,]?', '', text)
        
        # 处理来源相关
        # 移除 "（来源：xxx）" "(Source: xxx)" 等括号内容（先处理括号包裹的）
        text = re.sub(r'（来源[：:][^）]*）', '', text)
        text = re.sub(r'\(来源[：:][^\)]*\)', '', text)
        text = re.sub(r'[（(][Ss]ource[：:][^）)]*[）)]', '', text)
        # 移除 "来源：xxx。" "来源：xxx，" 等（到句末或逗号）
        text = re.sub(r'来源[：:][^。！？，\n]*[。！？，]?', '', text)
        # 移除可能残留的空括号
        text = re.sub(r'（\s*）', '', text)
        text = re.sub(r'\(\s*\)', '', text)
        
        # 移除 "——新闻X" "—来源" 等破折号引用
        text = re.sub(r'[—–-]{1,2}\s*(新闻|来源)\d*', '', text)
        # 移除 "注1：xxx" "注：xxx" 等注释
        text = re.sub(r'注\d*[：:][^\n。]*[。]?', '', text)
        # 移除上标数字引用 ¹²³ 等
        text = re.sub(r'[¹²³⁴⁵⁶⁷⁸⁹⁰]+', '', text)
        
        # ========== 移除代码块和行内代码 ==========
        text = re.sub(r'```[\s\S]*?```', '', text)
        text = re.sub(r'`[^`]+`', '', text)
        
        # ========== 转换标题为朗读格式 ==========
        text = re.sub(r'^#{1,6}\s+(.+)$', r'\n\n\1\n', text, flags=re.MULTILINE)
        
        # ========== 移除链接和图片 ==========
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
        
        # ========== 转换列表项 ==========
        text = re.sub(r'^[-*]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)
        
        # ========== 移除剩余的斜体标记 ==========
        text = re.sub(r'\*([^*]+)\*', r'\1', text)
        text = re.sub(r'_([^_]+)_', r'\1', text)
        
        # ========== 处理表格 ==========
        text = re.sub(r'\|[^\n]+\|', '', text)
        text = re.sub(r'^[-|:]+$', '', text, flags=re.MULTILINE)
        
        # ========== 替换符号为可朗读文字 ==========
        text = text.replace('&', '和')
        text = re.sub(r'(\d+(?:\.\d+)?)\s*%', r'百分之\1', text)
        text = text.replace('①', '第一')
        text = text.replace('②', '第二')
        text = text.replace('③', '第三')
        
        # ========== 数字朗读优化 ==========
        # 移除带括号的情绪值，如（+0.72）、(+0.35)等，不朗读
        text = re.sub(r'[（(][+\-]?\d+\.?\d*[）)]', '', text)
        
        # 处理小数点后的数字朗读（+0.12 读作"零点一二"而不是"零点十二"）
        # 自定义函数处理小数朗读
        def convert_decimal_reading(match):
            """将小数转换为逐位朗读格式"""
            full_match = match.group(0)
            sign = match.group(1) or ''  # 正负号
            integer_part = match.group(2)  # 整数部分
            decimal_part = match.group(3)  # 小数部分
            
            # 处理符号：加号不读，减号读"负"
            sign_text = ''
            if sign == '-':
                sign_text = '负'
            # 加号不读，所以 sign == '+' 时 sign_text 保持为空
            
            # 处理整数部分
            digit_map = {'0': '零', '1': '一', '2': '二', '3': '三', '4': '四',
                        '5': '五', '6': '六', '7': '七', '8': '八', '9': '九'}
            
            # 整数部分直接读数字
            int_text = digit_map.get(integer_part, integer_part)
            
            # 小数部分逐位读
            decimal_text = ''.join([digit_map.get(d, d) for d in decimal_part])
            
            return f'{sign_text}{int_text}点{decimal_text}'
        
        # 匹配带符号的小数：+0.12, -0.35, 0.72 等
        # 注意：只处理小数部分不超过4位的情况
        text = re.sub(r'([+\-])?(\d)\.(\d{1,4})(?!\d)', convert_decimal_reading, text)
        
        # ========== 清理多余的标点和空白 ==========
        # 连续的逗号合并
        text = re.sub(r'[，,]{2,}', '，', text)
        # 句号前的逗号去掉
        text = re.sub(r'，([。！？])', r'\1', text)
        # 清理多余空行
        text = re.sub(r'\n{3,}', '\n\n', text)
        # 清理行首行尾空白
        text = re.sub(r'^\s+', '', text, flags=re.MULTILINE)
        
        # ========== 添加适当的停顿标记 ==========
        text = text.replace('。', '。\n')
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
            print(f"[OK] 语音已切换为: {self.available_voices[voice]}")
        else:
            print(f"[WARN] 未知的语音角色: {voice}")


# 单例实例
_podcast_generator: Optional[PodcastGeneratorService] = None


def get_podcast_generator() -> PodcastGeneratorService:
    """获取播客生成服务实例"""
    global _podcast_generator
    if _podcast_generator is None:
        _podcast_generator = PodcastGeneratorService()
    return _podcast_generator

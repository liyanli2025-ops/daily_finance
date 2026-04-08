"""
播客生成服务
使用 Edge TTS 将报告文本转换为音频

重构版 v2：AI 自动生成播客脚本
- 不再依赖固定模板，每期开场白都独一无二
- AI 根据报告内容、天气、日期等上下文生成自然口语化的播客脚本
- 早报：简洁直接，快节奏，聚焦当日操作
- 晚报：深入复盘，稍慢节奏，回顾+展望
- 非交易日：深度科普，慢节奏，知识性强
"""
import asyncio
import os
import re
import random
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, List, Tuple
import uuid

import edge_tts
import httpx

from ..config import settings
from ..models.report import Report, ReportType
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
        
        # 初始化开场白模板（备用方案）
        self._init_openings()
        
        # HTTP客户端用于获取天气
        self.http_client = None
        
        # 初始化 AI 客户端（用于生成播客脚本）
        self.ai_client = None
        self.using_free_service = False
        self._init_ai_client()
    
    def _init_openings(self):
        """初始化开场白模板，使用配置的用户昵称"""
        name = self.user_nickname
        
        # ==================== 交易日早报开场白 ====================
        self.morning_openings = [
            f"{name}，早上好！新的交易日开始了，让我们看看今天的市场机会。",
            f"{name}你好呀！又是充满机会的一天，最新的市场分析来了。",
            f"嗨，{name}！财经早报马上开始，抓住今日投资先机。",
            f"{name}，早安！边喝咖啡边听今天的操作建议吧。",
            f"{name}，新的一天，新的机会！今天的市场有什么看点？",
            f"Hello{name}！通勤路上，先听听今天的市场预判。",
            f"{name}早！开盘前先听这期早报，做好今日作战准备。",
            f"{name}，起床啦！今天的操作建议已经为你整理好了。",
        ]
        
        # ==================== 交易日晚报开场白 ====================
        self.evening_openings = [
            f"{name}，晚上好！今天市场收盘了，让我们一起复盘今日的得失。",
            f"{name}你好！辛苦了一天，来听听今日市场的战报吧。",
            f"嗨{name}，下班后的第一件事，回顾今天的投资表现。",
            f"{name}，收盘了！今天的预测准不准？让我来给你详细分析。",
            f"{name}晚上好！边吃饭边听今日复盘，为明天做好准备。",
            f"Hello{name}！今天的市场让你满意吗？来听听详细分析。",
            f"{name}，今日战报来了！先看看早上的预测兑现了多少。",
            f"{name}晚安！睡前听听今日复盘，明天继续加油。",
        ]
        
        # ==================== 非交易日深度版开场白 ====================
        self.weekend_openings = [
            f"{name}，周末愉快！今天不开市，咱们来做个深度复盘。",
            f"{name}你好！难得的休息日，一起聊聊本周市场和下周展望。",
            f"嗨{name}，周末好！这期是深度版，内容丰富，泡杯茶慢慢听。",
            f"{name}，休息日快乐！市场虽然休息，但我们的思考不能停。",
            f"{name}周末好！今天不着急，我们深入聊聊市场的来龙去脉。",
            f"Hello{name}！周末时光，适合深度思考，这期内容更丰富。",
            f"{name}，假期愉快！趁着市场休息，做一期深度科普。",
            f"{name}周末好！今天有充足时间，给你讲讲本周的热点概念。",
        ]
        
        # 兼容旧版属性名
        self.weekday_openings = self.morning_openings
    
    def _init_ai_client(self):
        """初始化 AI 客户端（用于生成播客脚本，含备用服务）"""
        # 构建 AI 客户端列表（按优先级排序）
        self.ai_clients = []  # [(名称, 类型, 客户端, 模型)]
        
        # 1. Anthropic
        if settings.anthropic_api_key:
            try:
                from anthropic import Anthropic
                client = Anthropic(api_key=settings.anthropic_api_key)
                self.ai_clients.append(("Anthropic", "anthropic", client, settings.ai_model or "claude-sonnet-4-20250514"))
                print("[播客] AI 客户端初始化成功 (Anthropic)")
            except Exception as e:
                print(f"[播客] Anthropic 初始化失败: {e}")
        
        # 2. OpenAI/DeepSeek（主服务）
        if settings.openai_api_key:
            try:
                from openai import OpenAI
                base_url = settings.openai_base_url or "https://api.openai.com/v1"
                client = OpenAI(api_key=settings.openai_api_key, base_url=base_url)
                model = self._select_podcast_model(settings.openai_base_url, settings.ai_model)
                self.ai_clients.append((f"主服务({base_url})", "openai", client, model))
                # 兼容旧属性
                self.ai_client = ("openai", client)
                print(f"[播客] AI 客户端初始化成功 (OpenAI/兼容服务: {base_url})")
            except Exception as e:
                print(f"[播客] OpenAI 初始化失败: {e}")
        
        # 3. 备用 AI 服务
        if settings.backup_ai_api_key:
            try:
                from openai import OpenAI
                base_url = settings.backup_ai_base_url or "https://api.openai.com/v1"
                client = OpenAI(api_key=settings.backup_ai_api_key, base_url=base_url)
                model = settings.backup_ai_model or "deepseek-chat"
                self.ai_clients.append((f"备用({base_url})", "openai", client, model))
                print(f"[播客] 备用 AI 初始化成功 ({base_url})")
            except Exception as e:
                print(f"[播客] 备用 AI 初始化失败: {e}")
        
        # 4. Pollinations 免费服务（最后防线）
        if not self.ai_clients:
            try:
                from openai import OpenAI
                client = OpenAI(api_key="dummy", base_url="https://text.pollinations.ai/openai")
                self.ai_clients.append(("Pollinations免费", "openai", client, "openai"))
                self.using_free_service = True
                self.ai_client = ("openai", client)
                print("[播客] AI 客户端初始化成功 (免费服务 Pollinations)")
            except Exception as e:
                print(f"[播客] 免费服务初始化失败: {e}，将使用备用模板")
        
        # 兼容旧属性
        if not hasattr(self, 'ai_client') or self.ai_client is None:
            if self.ai_clients:
                name, ctype, client, model = self.ai_clients[0]
                self.ai_client = (ctype, client)
            else:
                self.ai_client = None
        
        providers = [item[0] for item in self.ai_clients]
        print(f"[播客] 降级链路: {' → '.join(providers) if providers else '⚠️ 无可用AI! 将使用备用模板'}")
    
    def _select_podcast_model(self, base_url: Optional[str], ai_model: Optional[str]) -> str:
        """为播客选择模型"""
        if ai_model and "claude" not in ai_model.lower():
            return ai_model
        if base_url:
            if "deepseek" in base_url.lower():
                return "deepseek-chat"
            elif "siliconflow" in base_url.lower():
                return "deepseek-ai/DeepSeek-V3"
        return "gpt-4-turbo"
    
    async def _call_ai_for_podcast(self, system_prompt: str, user_prompt: str, max_tokens: int = 4000) -> Optional[str]:
        """
        调用 AI 生成播客脚本（多提供商自动降级）
        
        降级链路：按 ai_clients 列表依次尝试
        全部失败 → 返回 None，使用备用模板
        """
        if not self.ai_clients:
            print("[播客] 无可用 AI 客户端，将使用备用模板")
            return None
        
        AI_TIMEOUT = 180  # 3 分钟
        
        for provider_name, client_type, client, model in self.ai_clients:
            retries = 3 if "pollinations" in provider_name.lower() else 2
            
            for attempt in range(retries):
                try:
                    print(f"[播客] 🔵 尝试 {provider_name} / {model} (尝试 {attempt + 1}/{retries})")
                    
                    if client_type == "anthropic":
                        message = await asyncio.wait_for(
                            asyncio.get_event_loop().run_in_executor(
                                None,
                                lambda c=client, m=model: c.messages.create(
                                    model=m,
                                    max_tokens=max_tokens,
                                    system=system_prompt,
                                    messages=[{"role": "user", "content": user_prompt}]
                                )
                            ),
                            timeout=AI_TIMEOUT
                        )
                        print(f"[播客] ✅ {provider_name} 调用成功")
                        return message.content[0].text
                    else:
                        # DeepSeek max_tokens 适配
                        actual_max_tokens = max_tokens
                        if "deepseek" in model.lower():
                            actual_max_tokens = min(max_tokens, 8192)
                        
                        response = await asyncio.wait_for(
                            asyncio.get_event_loop().run_in_executor(
                                None,
                                lambda c=client, m=model, mt=actual_max_tokens: c.chat.completions.create(
                                    model=m,
                                    max_tokens=mt,
                                    messages=[
                                        {"role": "system", "content": system_prompt},
                                        {"role": "user", "content": user_prompt}
                                    ],
                                    timeout=AI_TIMEOUT
                                )
                            ),
                            timeout=AI_TIMEOUT + 10
                        )
                        print(f"[播客] ✅ {provider_name} 调用成功")
                        return response.choices[0].message.content
                        
                except asyncio.TimeoutError:
                    print(f"[播客] ⚠️ {provider_name} 超时 (尝试 {attempt + 1})")
                except Exception as e:
                    print(f"[播客] ❌ {provider_name} 失败 (尝试 {attempt + 1}): {e}")
                
                if attempt < retries - 1:
                    wait_time = (attempt + 1) * 3
                    print(f"   等待 {wait_time} 秒后重试...")
                    await asyncio.sleep(wait_time)
            
            print(f"[播客] ⚠️ {provider_name} 全部失败，尝试下一个提供商...")
        
        print("[播客] 🚨 所有 AI 提供商都失败了，将使用备用模板")
        return None
    
    async def _get_http_client(self):
        """获取或创建HTTP客户端"""
        if self.http_client is None:
            self.http_client = httpx.AsyncClient(timeout=10.0)
        return self.http_client
    
    # 英文天气描述 -> 中文映射字典
    WEATHER_EN_TO_ZH = {
        "sunny": "晴",
        "clear": "晴",
        "partly cloudy": "多云",
        "partly Cloudy": "多云",
        "cloudy": "多云",
        "overcast": "阴",
        "mist": "薄雾",
        "fog": "雾",
        "freezing fog": "冻雾",
        "patchy rain possible": "可能有零星小雨",
        "patchy rain nearby": "附近有零星小雨",
        "patchy snow possible": "可能有零星小雪",
        "patchy sleet possible": "可能有零星雨夹雪",
        "patchy freezing drizzle possible": "可能有零星冻毛毛雨",
        "thundery outbreaks possible": "可能有雷阵雨",
        "blowing snow": "吹雪",
        "blizzard": "暴风雪",
        "haze": "霾",
        "light drizzle": "小毛毛雨",
        "light rain": "小雨",
        "light rain shower": "小阵雨",
        "moderate rain": "中雨",
        "moderate rain at times": "时有中雨",
        "heavy rain": "大雨",
        "heavy rain at times": "时有大雨",
        "light snow": "小雪",
        "moderate snow": "中雪",
        "heavy snow": "大雪",
        "light sleet": "小雨夹雪",
        "moderate or heavy sleet": "中到大雨夹雪",
        "light freezing rain": "小冻雨",
        "moderate or heavy freezing rain": "中到大冻雨",
        "light showers of ice pellets": "小冰粒",
        "moderate or heavy showers of ice pellets": "中到大冰粒",
        "thunderstorm": "雷暴",
        "rain": "雨",
        "snow": "雪",
        "sleet": "雨夹雪",
        "drizzle": "毛毛雨",
        "shower": "阵雨",
        "ice pellets": "冰粒",
        "patchy light rain": "零星小雨",
        "patchy light snow": "零星小雪",
        "patchy moderate snow": "零星中雪",
        "patchy heavy snow": "零星大雪",
        "patchy light drizzle": "零星毛毛雨",
        "light snow showers": "小阵雪",
        "moderate or heavy snow showers": "中到大阵雪",
        "patchy light rain with thunder": "零星小雨伴雷",
        "moderate or heavy rain with thunder": "中到大雨伴雷",
        "patchy light snow with thunder": "零星小雪伴雷",
        "moderate or heavy snow with thunder": "中到大雪伴雷",
    }

    def _translate_weather(self, desc_en: str) -> str:
        """将英文天气描述翻译为中文，找不到则返回原文"""
        if not desc_en:
            return "晴"
        lower = desc_en.strip().lower()
        return self.WEATHER_EN_TO_ZH.get(lower, desc_en)

    async def _get_aqi(self) -> Optional[int]:
        """获取北京空气质量指数（AQI）"""
        try:
            client = await self._get_http_client()
            url = "https://api.waqi.info/feed/beijing/?token=demo"
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "ok":
                    aqi = data.get("data", {}).get("aqi")
                    if aqi is not None:
                        return int(aqi)
        except Exception as e:
            print(f"[天气] 获取AQI失败: {e}")
        return None

    async def get_beijing_weather(self) -> str:
        """
        获取北京当天的天气情况
        输出格式：北京今天天气x，气温x摄氏度到x摄氏度，空气质量指数x
        """
        weather_desc = ""
        max_temp = ""
        min_temp = ""

        try:
            client = await self._get_http_client()

            # 使用 wttr.in JSON API
            url = "https://wttr.in/Beijing?format=j1"
            response = await client.get(url, headers={"User-Agent": "curl/7.68.0"})

            if response.status_code == 200:
                data = response.json()
                weather_list = data.get("weather", [])
                if weather_list:
                    today = weather_list[0]
                    max_temp = today.get("maxtempC", "")
                    min_temp = today.get("mintempC", "")

                current = data.get("current_condition", [{}])[0]
                # 优先使用中文描述
                lang_zh_list = current.get("lang_zh", [])
                if lang_zh_list and lang_zh_list[0].get("value"):
                    weather_desc = lang_zh_list[0]["value"]
                else:
                    # 英文描述 -> 用映射字典翻译为中文
                    en_desc = current.get("weatherDesc", [{}])[0].get("value", "")
                    weather_desc = self._translate_weather(en_desc)

        except Exception as e:
            print(f"[天气] 获取天气失败: {e}")

        # 获取空气质量指数
        aqi = await self._get_aqi()

        # 组装输出
        if weather_desc and max_temp and min_temp:
            base = f"北京今天天气{weather_desc}，气温{min_temp}摄氏度到{max_temp}摄氏度"
            if aqi is not None:
                return f"{base}，空气质量指数{aqi}。"
            return f"{base}。"
        elif weather_desc:
            base = f"北京今天天气{weather_desc}"
            if aqi is not None:
                return f"{base}，空气质量指数{aqi}。"
            return f"{base}。"

        return "北京今天天气不错。"
    
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
    
    def _get_last_trading_day(self, current_date: date = None) -> date:
        """
        获取上一个交易日的日期
        简单逻辑：往前推，跳过周末（不含法定节假日）
        """
        if current_date is None:
            current_date = date.today()
        last_day = current_date - timedelta(days=1)
        # 跳过周末
        while last_day.weekday() >= 5:
            last_day -= timedelta(days=1)
        return last_day
    
    def _get_market_data_date_info(self, report_date: date) -> Tuple[str, str, bool]:
        """
        根据报告日期，判断市场数据实际对应哪一天，返回准确的日期表述
        
        Returns:
            (data_date_str, date_description, is_today_data)
            - data_date_str: 数据对应的日期字符串，如 "3月20日周五"
            - date_description: 用于播客的表述，如 "上一个交易日" 或 "今天"
            - is_today_data: 数据是否就是今天的（即今天是交易日且已开盘）
        """
        weekday = report_date.weekday()  # 0=周一 ... 6=周日
        
        # 判断报告生成时，市场数据来自哪一天
        # 系统默认凌晨5-6点生成，此时A股还没开盘（9:30），所以数据一定是上一个交易日的
        if weekday >= 5:
            # 周末：数据是上周五的
            last_trading = self._get_last_trading_day(report_date)
            weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
            data_date_str = f"{last_trading.month}月{last_trading.day}日{weekday_names[last_trading.weekday()]}"
            return (data_date_str, "上一个交易日", False)
        else:
            # 工作日（凌晨生成，A股还没开盘，数据是上一个交易日的）
            last_trading = self._get_last_trading_day(report_date)
            weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
            data_date_str = f"{last_trading.month}月{last_trading.day}日{weekday_names[last_trading.weekday()]}"
            return (data_date_str, "上一个交易日", False)
    
    def _get_random_opening(self, report_type: ReportType = None, is_weekend: bool = False) -> str:
        """
        获取随机开场白
        
        Args:
            report_type: 报告类型（morning/evening）
            is_weekend: 是否是非交易日
        """
        if is_weekend:
            return random.choice(self.weekend_openings)
        
        if report_type == ReportType.EVENING:
            return random.choice(self.evening_openings)
        
        return random.choice(self.morning_openings)
    
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
        
        # 准备播客文本（使用 AI 生成脚本）
        podcast_text = await self._prepare_podcast_text(report, weather_info)
        
        # 生成音频文件名
        filename = f"{report.id}.mp3"
        output_path = self.output_dir / filename
        
        # 临时文件（用于TTS输出，之后会与背景音乐混合）
        temp_path = self.output_dir / f"{report.id}_voice.mp3"
        
        # 分段生成语音（在 [SECTION_BREAK] 处分段，并加入停顿）
        await self._generate_segmented_tts(podcast_text, str(temp_path))
        
        # 判断是否是晚报
        report_type = getattr(report, 'report_type', ReportType.MORNING)
        if isinstance(report_type, str):
            report_type = ReportType(report_type)
        is_evening = (report_type == ReportType.EVENING)
        
        # 与背景音乐混合
        audio_mixer = get_audio_mixer()
        if audio_mixer.has_bgm(is_evening):
            bgm_type = "晚报" if is_evening else "日报"
            print(f"[BGM] 检测到{bgm_type}背景音乐，开始混音...")
            audio_mixer.mix_podcast_with_bgm(str(temp_path), str(output_path), is_evening=is_evening)
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
            if audio_mixer.has_bgm(is_evening):
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
        
        # 二次清理：确保每段中不残留舞台指示
        cleaned_segments = []
        for s in segments:
            # 移除可能残留的 SECTION_BREAK 变体
            s = re.sub(r'(?i)\[?\s*section[\s_]*break\s*\]?', '', s).strip()
            # 移除任何残留的舞台指示（中文括号）
            s = re.sub(r'（[^）]*(?:音乐|音效|渐弱|渐强|淡入|淡出|过渡|停顿)[^）]*）', '', s, flags=re.IGNORECASE)
            # 移除任何残留的舞台指示（英文括号）
            s = re.sub(r'\([^)]*(?:music|fade|pause|transition|sound)[^)]*\)', '', s, flags=re.IGNORECASE)
            # 移除任何残留的舞台指示（方括号，排除SECTION_BREAK）
            s = re.sub(r'\[[^\]]*(?:音乐|音效|渐弱|渐强|淡入|淡出|过渡|停顿|music|fade|pause|transition|break|intro|outro)[^\]]*\]', '', s, flags=re.IGNORECASE)
            s = s.strip()
            if s:
                cleaned_segments.append(s)
        segments = cleaned_segments
        
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
        
        # 超长段落自动切割（Edge TTS 对单次超过 ~2000 字的文本不稳定）
        MAX_SEGMENT_CHARS = 1500
        final_segments = []
        for seg in segments:
            if len(seg) <= MAX_SEGMENT_CHARS:
                final_segments.append(seg)
            else:
                # 按句号/问号/感叹号切割
                sub_parts = re.split(r'(?<=[。！？])', seg)
                current_chunk = ""
                for part in sub_parts:
                    if len(current_chunk) + len(part) > MAX_SEGMENT_CHARS and current_chunk:
                        final_segments.append(current_chunk.strip())
                        current_chunk = part
                    else:
                        current_chunk += part
                if current_chunk.strip():
                    final_segments.append(current_chunk.strip())
                print(f"[TTS] 超长段落已切割为 {len(final_segments)} 个子段")
        segments = final_segments
        
        print(f"[TTS] 最终 {len(segments)} 个音频段落，最长 {max(len(s) for s in segments)} 字")
        
        # 创建临时目录存放分段音频
        temp_dir = Path(tempfile.gettempdir()) / f"podcast_segments_{uuid.uuid4().hex[:8]}"
        temp_dir.mkdir(exist_ok=True)
        
        try:
            # 生成每个段落的音频（带重试和容错）
            segment_files = []
            failed_count = 0
            for i, segment in enumerate(segments):
                if not segment:
                    continue
                    
                segment_path = temp_dir / f"segment_{i:02d}.mp3"
                print(f"[TTS] 正在生成第 {i+1}/{len(segments)} 段（{len(segment)}字）...")
                
                # 重试机制：Edge TTS 偶尔会返回空音频
                success = False
                for retry in range(3):
                    try:
                        communicate = edge_tts.Communicate(
                            text=segment,
                            voice=self.voice,
                            rate=self.rate,
                            volume=self.volume
                        )
                        await communicate.save(str(segment_path))
                        
                        # 验证文件是否有效（大于 1KB）
                        if segment_path.exists() and segment_path.stat().st_size > 1024:
                            segment_files.append(segment_path)
                            success = True
                            break
                        else:
                            print(f"[TTS] 第 {i+1} 段生成了空文件，重试 ({retry+1}/3)...")
                            await asyncio.sleep(2)
                    except Exception as e:
                        print(f"[TTS] 第 {i+1} 段失败: {e}，重试 ({retry+1}/3)...")
                        await asyncio.sleep(3)
                
                if not success:
                    failed_count += 1
                    print(f"[TTS] ⚠️ 第 {i+1} 段最终失败，跳过")
            
            if not segment_files:
                raise Exception("所有 TTS 段落都失败了，无法生成播客音频")
            
            if failed_count > 0:
                print(f"[TTS] ⚠️ {failed_count} 个段落失败，使用 {len(segment_files)} 个成功段落继续合成")
            
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
    
    async def _prepare_podcast_text(self, report: Report, weather_info: str = "") -> str:
        """
        准备播客文本 - 使用 AI 生成完整脚本
        
        v2: 全面升级，AI 自动生成播客脚本
        - 不再依赖固定模板
        - 根据报告内容、天气、日期等上下文生成
        - 每期开场白、过渡语、结束语都独一无二
        
        如果 AI 生成失败，则回退到模板方案
        """
        report_date = report.report_date
        # 确保 report_date 是 date 对象
        if isinstance(report_date, str):
            try:
                report_date = datetime.strptime(report_date, "%Y-%m-%d").date()
            except ValueError:
                report_date = date.today()
        
        # 获取报告类型
        report_type = getattr(report, 'report_type', ReportType.MORNING)
        if isinstance(report_type, str):
            report_type = ReportType(report_type)
        
        is_weekend = self._is_weekend(report_date)
        
        # 尝试使用 AI 生成播客脚本
        ai_script = await self._generate_ai_podcast_script(
            report=report,
            weather_info=weather_info,
            report_date=report_date,
            report_type=report_type,
            is_weekend=is_weekend
        )
        
        if ai_script:
            print("[播客] ✅ AI 脚本生成成功")
            return ai_script
        
        # AI 生成失败，回退到模板方案
        print("[播客] ⚠️ AI 脚本生成失败，使用备用模板")
        if is_weekend:
            return self._prepare_weekend_podcast_text_fallback(report, weather_info, report_date)
        elif report_type == ReportType.EVENING:
            return self._prepare_evening_podcast_text_fallback(report, weather_info, report_date)
        else:
            return self._prepare_morning_podcast_text_fallback(report, weather_info, report_date)
    
    async def _generate_ai_podcast_script(
        self,
        report: Report,
        weather_info: str,
        report_date: date,
        report_type: ReportType,
        is_weekend: bool
    ) -> Optional[str]:
        """
        使用 AI 生成完整的播客脚本
        
        Args:
            report: 报告对象
            weather_info: 天气信息
            report_date: 报告日期
            report_type: 报告类型
            is_weekend: 是否是非交易日
            
        Returns:
            AI 生成的播客脚本，失败返回 None
        """
        if not self.ai_client:
            return None
        
        weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        weekday_name = weekday_names[report_date.weekday()]
        data_date_str, date_description, _ = self._get_market_data_date_info(report_date)
        name = self.user_nickname
        
        # 确定播客类型和风格要求
        if is_weekend:
            podcast_type = "周末深度版"
            style_requirement = """
风格要求：
- 这是周末/非交易日版本，你和用户坐在咖啡馆里深度聊天
- 节奏放慢，像和老朋友娓娓道来
- 内容更深入，做整周复盘和概念科普，但科普要从本周实际案例中引出，不要硬插
- 字数要求：4000-5000字（约16-20分钟）
- 开头要提醒今天是非交易日，市场休市
- **关键：全程是一个连贯的故事线，从"本周发生了什么"→"为什么"→"我学到什么可以教你"→"下周怎么做"**
- 模块之间用自然的过渡，不要说"接下来我们看模块X"
"""
            time_context = "周末愉快" if report_date.weekday() == 5 else "假期愉快"
        elif report_type == ReportType.EVENING:
            podcast_type = "交易日晚报"
            style_requirement = """
风格要求：
- 这是晚间复盘版本，你像收盘后和用户在阳台上喝茶聊天
- 重点复盘今天市场表现，自然穿插评价早报预测的准确度（对了就自信，错了就坦诚）
- 投资课堂部分要从今天的实际市场案例中引出，不要突兀地插入一个不相关的话题
- 为明天做展望和建议
- 字数要求：3000-4000字（约12-16分钟）
- **关键：全程是一个连贯的分析叙事，从"今天发生了什么"→"为什么"→"从中我们能学到什么"→"明天怎么操作"**
- 口吻轻松自信，像和朋友复盘今天的得失
"""
            time_context = "晚上好"
        else:
            podcast_type = "交易日早报"
            style_requirement = """
风格要求：
- 这是早间版本，快节奏、信息密集
- 聚焦当日操作建议，实用性强
- 适合通勤路上收听
- 字数要求：2500-3000字（约10-12分钟）
- 开头可以结合天气聊几句，然后快速进入正题
- **关键：全程围绕"今天该怎么操作"这条主线，所有分析都指向操作建议**
- 不要有模块割裂感，从宏观→板块→个股→操作建议，层层递进
"""
            time_context = "早上好"
        
        # 准备报告素材
        core_opinions_str = ""
        if hasattr(report, 'core_opinions') and report.core_opinions:
            core_opinions_str = "\n".join([f"{i}. {op}" for i, op in enumerate(report.core_opinions, 1)])
        
        cross_border_str = ""
        if hasattr(report, 'cross_border_events') and report.cross_border_events:
            for event in report.cross_border_events:
                category_name = {
                    "geopolitical": "地缘政治",
                    "tech": "科技圈",
                    "social": "社会热点",
                    "disaster": "自然灾害"
                }.get(event.category.value, "其他")
                cross_border_str += f"\n- [{category_name}] {event.title}: {event.summary}\n  市场影响: {event.market_impact_direct}"
        
        # 提取报告精华内容（限制长度避免 token 过多）
        report_essence = self._extract_key_paragraphs(report.content)
        if len(report_essence) > 2000:
            report_essence = report_essence[:2000] + "..."
        
        # 构造 System Prompt
        system_prompt = f"""你正在用**聊天的方式**和{name}分享你对市场的分析和见解。这是一期{podcast_type}播客。

## 你的人设
- 你有20年实战投资经验，说话有分量
- 你和{name}很熟悉，说话自然亲切，像老朋友聊天
- 你有自己的投资哲学和判断框架，敢于表达明确观点
- 适当使用口语化表达（"说实话"、"坦白讲"、"我个人觉得"、"其实呢"、"你别看..."等）
- 不要念稿式的播报，要像在面对面交谈
- **绝对不要自我介绍**——不要说"我是XX主播""我是你的投资顾问""我是XX"等任何形式的身份说明，直接开聊

## 核心原则——一气呵成的整体性（极其重要！）
1. 每期播客要有一条清晰的**主线**串联全篇——所有分析和建议都围绕这条主线展开
2. **不要有模块感**——不要说"接下来是模块X"或"接下来看XX部分"，用自然过渡连接
3. 好的过渡示例：
   - "说到半导体，其实今天有个更有意思的事儿..."
   - "为什么我对明天这么有信心？因为刚才分析的那些资金数据已经说明了一切"
   - "这就引出了一个很多人不懂的概念..."
4. 分析要有深度但表达要通俗
5. 开场白必须每次都不一样，有创意，可以结合天气、日期、时事、节气等——**直接打招呼就行，不要介绍自己是谁**
6. 结束语要有温度，让{name}感觉被真诚关心

## 技术要求
- 用 [SECTION_BREAK] 标记分段（系统会在这些位置加入停顿）
- 建议每 300-500 字加一个 [SECTION_BREAK]
- 不要使用 Markdown 格式（粗体、列表等），要纯文本
- 不要使用 emoji
- 用户昵称"{name}"在播客中至少出现 3-4 次
- 数字要适合朗读（"百分之三点五"而不是"3.5%"）

## ⛔ 严格禁止（非常重要！）
- **绝对不要自我介绍！** 禁止出现以下任何形式：
  - ❌ "我是XX主播"、"我是你的投资顾问"、"我是XX"
  - ❌ "这里是XX节目"、"欢迎来到XX频道"、"欢迎收听XX播客"
  - ❌ 任何身份说明、节目名称、频道介绍
  - 直接和{name}打招呼就好，比如"{name}，早上好！"
- **绝对不要**输出任何舞台指示、音效描述、导演备注类文本！
- 禁止出现类似以下内容（这些会被TTS原样朗读出来，严重影响体验）：
  - ❌ （音乐渐弱）、（音乐渐强）、（背景音乐淡入）、（音乐淡出）
  - ❌ [音乐过渡]、[音效]、[转场]、[片头曲]、[片尾曲]
  - ❌ （停顿）、（深呼吸）、（语速加快）、（语气变化）
  - ❌ [BGM]、[sound effect]、[music fades]、[transition]
  - ❌ Section Break（除了[SECTION_BREAK]标记以外）
  - ❌ 任何用括号或方括号包裹的非正文指示
- 只输出**可以直接朗读的纯文本**，不要有任何"导演注释"
- [SECTION_BREAK] 是唯一允许的特殊标记
- **不要有模块编号**（如"模块一""第一部分"），直接自然地展开内容

{style_requirement}
"""

        # 构造 User Prompt
        user_prompt = f"""请根据以下素材，生成一期完整的{podcast_type}播客脚本。

## 基本信息
- 日期：{report_date.strftime('%Y年%m月%d日')}，{weekday_name}
- 天气：{weather_info if weather_info else "北京今天天气不错"}
- 用户昵称：{name}
- 市场数据来自：{date_description}（{data_date_str}的收盘数据）

## 报告摘要
{report.summary}

## 核心操作建议
{core_opinions_str if core_opinions_str else "暂无具体操作建议"}

## 跨界热点
{cross_border_str if cross_border_str else "今天没有特别重大的跨界事件"}

## 报告正文精华
{report_essence}

---

## 重要提醒
1. 先确定这期播客的**一条主线**是什么（比如"今天半导体大涨，我们来聊聊芯片国产替代的投资逻辑"），然后围绕这条主线展开
2. 所有内容（复盘、科普、建议）都要和主线有关联，不要硬插无关话题
3. 不要有模块编号，不要说"第一部分""模块一"——直接自然地聊
4. 请直接输出播客脚本，不要输出任何解释或说明
5. 脚本应该是可以直接朗读的纯文本
"""

        # 调用 AI 生成
        print(f"[播客] 正在调用 AI 生成{podcast_type}脚本...")
        script = await self._call_ai_for_podcast(system_prompt, user_prompt, max_tokens=4000)
        
        if script:
            # 清理可能的 Markdown 残留
            script = self._clean_for_tts(script)
            # 确保有分段标记
            if "[SECTION_BREAK]" not in script:
                # AI 可能没有加分段标记，手动添加一些
                paragraphs = script.split("\n\n")
                if len(paragraphs) > 3:
                    # 每 2-3 个段落加一个分段
                    new_paragraphs = []
                    for i, p in enumerate(paragraphs):
                        new_paragraphs.append(p)
                        if (i + 1) % 3 == 0 and i < len(paragraphs) - 1:
                            new_paragraphs.append("[SECTION_BREAK]")
                    script = "\n\n".join(new_paragraphs)
            return script
        
        return None
    
    # ==================== 备用模板方法（AI 生成失败时使用）====================
    
    def _prepare_morning_podcast_text_fallback(self, report: Report, weather_info: str, report_date: date) -> str:
        """
        【备用方案】准备交易日早报播客文本
        
        当 AI 生成失败时使用此模板方法
        """
        weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        weekday_name = weekday_names[report_date.weekday()]
        
        # 获取市场数据日期信息
        data_date_str, date_description, _ = self._get_market_data_date_info(report_date)
        
        name = self.user_nickname
        random_greeting = self._get_random_opening(report_type=ReportType.MORNING, is_weekend=False)
        
        # 开场白
        opening = f"""
{random_greeting}

{weather_info}

今天是{report_date.strftime('%Y年%m月%d日')}，{weekday_name}。
本期播客的市场数据来自{date_description}，也就是{data_date_str}的收盘数据。

[SECTION_BREAK]
"""
        
        # 核心观点（最重要的部分）
        core_opinions_text = ""
        if hasattr(report, 'core_opinions') and report.core_opinions:
            core_opinions_text = f"""
{name}，先听我今天的三条操作建议：

"""
            for i, opinion in enumerate(report.core_opinions, 1):
                core_opinions_text += f"第{i}条：{opinion}\n\n"
            
            core_opinions_text += """
以上三条，建议你记下来，今天开盘后对照操作。

[SECTION_BREAK]
"""
        else:
            core_opinions_text = f"""
{name}，今天的核心内容是：{report.summary}

接下来我展开聊聊。

[SECTION_BREAK]
"""
        
        # 跨界热点
        cross_border_text = self._prepare_cross_border_for_podcast(report, name)
        
        # 报告正文精华
        key_content = self._extract_key_paragraphs(report.content)
        
        # 结束语
        closing = self._generate_morning_closing(report, name)
        
        full_text = opening + core_opinions_text + key_content + cross_border_text + closing
        
        # 控制字数（早报偏短）
        if len(full_text) > 3000:
            full_text = full_text[:2700] + f"""

{name}，时间关系，这期就先聊到这里。更详细的内容可以在App里看完整报告。

""" + closing
        
        return full_text
    
    def _prepare_evening_podcast_text_fallback(self, report: Report, weather_info: str, report_date: date) -> str:
        """
        【备用方案】准备交易日晚报播客文本
        
        当 AI 生成失败时使用此模板方法
        """
        weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        weekday_name = weekday_names[report_date.weekday()]
        
        name = self.user_nickname
        random_greeting = self._get_random_opening(report_type=ReportType.EVENING, is_weekend=False)
        
        # 开场白
        opening = f"""
{random_greeting}

今天是{report_date.strftime('%Y年%m月%d日')}，{weekday_name}，收盘了。
让我们一起回顾今天的市场表现，看看早上的预测准不准。

[SECTION_BREAK]
"""
        
        # 今日复盘摘要
        summary_text = f"""
{name}，先简单总结一下今天的市场：

{report.summary}

[SECTION_BREAK]
"""
        
        # 早报预测回顾（如果有的话，从报告内容中提取）
        review_text = ""
        if "早报" in report.content or "预测" in report.content:
            review_text = f"""
{name}，关于今天早上的预测准确度，我要向你汇报：

"""
            # 从报告中提取早报回顾相关内容
            review_content = self._extract_section_content(report.content, ["早报预测回顾", "早报回顾", "预测准确"])
            if review_content:
                review_text += review_content + "\n\n"
            review_text += "[SECTION_BREAK]\n"
        
        # 核心观点（明日建议）
        core_opinions_text = ""
        if hasattr(report, 'core_opinions') and report.core_opinions:
            core_opinions_text = f"""
{name}，基于今天的复盘，我给你明天的操作建议是：

"""
            for i, opinion in enumerate(report.core_opinions, 1):
                core_opinions_text += f"第{i}条：{opinion}\n\n"
            
            core_opinions_text += """
这几条建议，可以在明天开盘前再复习一下。

[SECTION_BREAK]
"""
        
        # 新概念科普（如果有）
        concept_text = ""
        if "概念" in report.content or "科普" in report.content:
            concept_content = self._extract_section_content(report.content, ["新概念", "概念科普", "热点科普"])
            if concept_content:
                concept_text = f"""
{name}，今天市场上有一些新概念值得了解：

{concept_content}

[SECTION_BREAK]
"""
        
        # 跨界热点
        cross_border_text = self._prepare_cross_border_for_podcast(report, name)
        
        # 报告正文精华
        key_content = self._extract_key_paragraphs(report.content)
        
        # 结束语
        closing = self._generate_evening_closing(report, name)
        
        full_text = opening + summary_text + review_text + core_opinions_text + concept_text + key_content + cross_border_text + closing
        
        # 控制字数（晚报可以更长）
        if len(full_text) > 4000:
            full_text = full_text[:3600] + f"""

{name}，内容很多，今天就先聊到这里。详细分析请看App里的完整报告。

""" + closing
        
        return full_text
    
    def _prepare_weekend_podcast_text_fallback(self, report: Report, weather_info: str, report_date: date) -> str:
        """
        【备用方案】准备非交易日深度版播客文本
        
        当 AI 生成失败时使用此模板方法
        """
        weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        weekday_name = weekday_names[report_date.weekday()]
        
        # 获取市场数据日期信息
        data_date_str, date_description, _ = self._get_market_data_date_info(report_date)
        
        name = self.user_nickname
        random_greeting = self._get_random_opening(report_type=ReportType.MORNING, is_weekend=True)
        
        # 开场白
        opening = f"""
{random_greeting}

{weather_info}

今天是{report_date.strftime('%Y年%m月%d日')}，{weekday_name}。

温馨提示：今天是非交易日，A股和港股都休市。
本期是深度版，内容比平时更丰富，适合泡杯茶慢慢听。
市场数据来自{date_description}，也就是{data_date_str}的收盘数据。

[SECTION_BREAK]
"""
        
        # 本周复盘摘要
        summary_text = f"""
{name}，先来看看本周市场的整体表现：

{report.summary}

[SECTION_BREAK]
"""
        
        # 核心观点（下周建议）
        core_opinions_text = ""
        if hasattr(report, 'core_opinions') and report.core_opinions:
            core_opinions_text = f"""
{name}，我对下周的操作建议是：

"""
            for i, opinion in enumerate(report.core_opinions, 1):
                core_opinions_text += f"第{i}条：{opinion}\n\n"
            
            core_opinions_text += """
这几条建议，下周一开盘可以参考执行。

[SECTION_BREAK]
"""
        
        # 概念科普模块（非交易日的核心特色）
        concept_text = ""
        concept_content = self._extract_section_content(report.content, ["概念科普", "热点概念", "本周热点", "新概念"])
        if concept_content:
            concept_text = f"""
{name}，接下来给你讲讲本周市场上的热点概念：

{concept_content}

这些概念可能在下周继续发酵，值得关注。

[SECTION_BREAK]
"""
        
        # 行业深度分析
        industry_text = ""
        industry_content = self._extract_section_content(report.content, ["行业深度", "本周行业", "行业分析"])
        if industry_content:
            industry_text = f"""
{name}，再来聊聊本周表现突出的行业：

{industry_content}

[SECTION_BREAK]
"""
        
        # 跨界热点
        cross_border_text = self._prepare_cross_border_for_podcast(report, name)
        
        # 报告正文精华
        key_content = self._extract_key_paragraphs(report.content)
        
        # 结束语
        closing = self._generate_weekend_closing(report, name)
        
        full_text = opening + summary_text + core_opinions_text + concept_text + industry_text + key_content + cross_border_text + closing
        
        # 控制字数（深度版可以更长）
        if len(full_text) > 5000:
            full_text = full_text[:4500] + f"""

{name}，今天内容确实很多，更详细的分析请在App里查看完整报告。

""" + closing
        
        return full_text
    
    def _prepare_cross_border_for_podcast(self, report: Report, name: str) -> str:
        """准备跨界热点播客文本"""
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
        return cross_border_text
    
    def _extract_section_content(self, content: str, section_keywords: List[str]) -> str:
        """从报告内容中提取指定章节的内容"""
        for keyword in section_keywords:
            # 尝试找到包含关键词的章节
            pattern = rf'#{1,3}\s*[^#]*{keyword}[^#]*\n([\s\S]*?)(?=#{1,3}|\Z)'
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                extracted = match.group(1).strip()
                # 清理并限制长度
                cleaned = self._clean_for_tts(extracted)
                if len(cleaned) > 800:
                    # 找到自然断点截断
                    cutoff = cleaned.find('。', 600)
                    if cutoff > 0:
                        cleaned = cleaned[:cutoff + 1]
                    else:
                        cleaned = cleaned[:800] + "..."
                return cleaned
        return ""
    
    def _generate_morning_closing(self, report: Report, name: str) -> str:
        """生成早报结束语"""
        closing = f"""

[SECTION_BREAK]

好了{name}，这期早报就到这里。

"""
        # 用实际核心观点做简短总结
        if hasattr(report, 'core_opinions') and report.core_opinions:
            closing += "最后帮你总结今天的操作要点：\n"
            for i, opinion in enumerate(report.core_opinions[:2], 1):  # 早报只总结前2条
                short_opinion = opinion[:35].rstrip('，。、；') if len(opinion) > 35 else opinion.rstrip('，。、；')
                closing += f"第{i}，{short_opinion}。\n"
            closing += "\n"
        
        closing += f"{name}，祝你今天交易顺利！我们晚上再见！\n"
        return closing
    
    def _generate_evening_closing(self, report: Report, name: str) -> str:
        """生成晚报结束语"""
        closing = f"""

[SECTION_BREAK]

好了{name}，这期晚报复盘就到这里。

"""
        # 总结明日要点
        if hasattr(report, 'core_opinions') and report.core_opinions:
            closing += "帮你总结明天的操作要点：\n"
            for i, opinion in enumerate(report.core_opinions[:2], 1):
                short_opinion = opinion[:35].rstrip('，。、；') if len(opinion) > 35 else opinion.rstrip('，。、；')
                closing += f"第{i}，{short_opinion}。\n"
            closing += "\n"
        
        # 如果有市场趋势判断
        if report.analysis:
            trend_one_liner = {
                "bullish": "整体我对明天偏乐观。",
                "bearish": "明天注意风险，别急着抄底。",
                "neutral": "震荡市保持耐心，等待机会。"
            }.get(report.analysis.trend.value, "")
            if trend_one_liner:
                closing += f"{trend_one_liner}\n\n"
        
        closing += f"{name}，早点休息，我们明天早上见！\n"
        return closing
    
    def _generate_weekend_closing(self, report: Report, name: str) -> str:
        """生成非交易日深度版结束语"""
        closing = f"""

[SECTION_BREAK]

好了{name}，这期深度版播客就到这里。

"""
        # 总结下周要点
        if hasattr(report, 'core_opinions') and report.core_opinions:
            closing += "帮你总结下周的操作要点：\n"
            for i, opinion in enumerate(report.core_opinions, 1):
                short_opinion = opinion[:40].rstrip('，。、；') if len(opinion) > 40 else opinion.rstrip('，。、；')
                closing += f"第{i}，{short_opinion}。\n"
            closing += "\n"
        
        # 如果有市场趋势判断
        if report.analysis:
            trend_one_liner = {
                "bullish": "整体我对下周偏乐观，可以适当积极一些。",
                "bearish": "下周可能还有波动，控制好仓位。",
                "neutral": "保持震荡思维，高抛低吸。"
            }.get(report.analysis.trend.value, "")
            if trend_one_liner:
                closing += f"{trend_one_liner}\n\n"
        
        closing += f"{name}，周末愉快！好好休息，我们下周再见！\n"
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
        
        # 只保留前1500字的核心内容
        if len(text) > 1500:
            # 尝试找到自然断点
            cutoff = text.find('。', 1300)
            if cutoff > 0:
                text = text[:cutoff + 1]
            else:
                text = text[:1500] + "..."
        
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
        
        # ========== 0. 移除舞台指示/音效描述/导演备注 ==========
        # 这些描述性内容不应被TTS朗读
        
        # 移除自我介绍类文本（如"我是XX主播""这里是XX节目""欢迎收听XX"等）
        text = re.sub(r'我是[^，。！？\n]{1,20}(?:主播|主持人|顾问|分析师|播音员)[，。！？]?\s*', '', text)
        text = re.sub(r'(?:这里是|欢迎来到|欢迎收听|欢迎收看)[^，。！？\n]{1,20}(?:节目|频道|播客|栏目|电台)[，。！？]?\s*', '', text)
        
        # 移除中文括号包裹的舞台指示：（音乐渐弱）（停顿）（深呼吸）等
        text = re.sub(r'（[^）]*(?:音乐|音效|背景|BGM|渐弱|渐强|淡入|淡出|过渡|转场|停顿|深呼吸|语速|语气|片头|片尾|叮咚|铃声|sound|music|fade|transition)[^）]*）', '', text, flags=re.IGNORECASE)
        
        # 移除英文括号包裹的舞台指示：(music fades) (pause) (BGM) 等
        text = re.sub(r'\([^)]*(?:音乐|音效|背景|BGM|渐弱|渐强|淡入|淡出|过渡|转场|停顿|深呼吸|语速|语气|片头|片尾|sound|music|fade|transition|pause|breath)[^)]*\)', '', text, flags=re.IGNORECASE)
        
        # 移除方括号包裹的舞台指示：[音乐过渡] [BGM] [sound effect] 等
        # 注意：保留 [SECTION_BREAK] 标记
        text = re.sub(r'\[(?!SECTION_BREAK\])[^\]]*(?:音乐|音效|背景|BGM|渐弱|渐强|淡入|淡出|过渡|转场|停顿|片头|片尾|叮咚|铃声|sound|music|fade|transition|pause|break|intro|outro|jingle)[^\]]*\]', '', text, flags=re.IGNORECASE)
        
        # 移除独立的 "Section Break"、"section break" 等文本（不在方括号内的）
        text = re.sub(r'(?i)\bsection\s*break\b', '', text)
        
        # 移除星号包裹的舞台指示：*音乐渐弱* *停顿* 等
        text = re.sub(r'\*[^*]*(?:音乐|音效|渐弱|渐强|淡入|淡出|过渡|停顿|fade|music)[^*]*\*', '', text, flags=re.IGNORECASE)
        
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
        # 移除 （新闻1）(新闻2) 等括号包裹的新闻引用
        text = re.sub(r'[（(]\s*新闻\d+\s*[）)]', '', text)
        
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

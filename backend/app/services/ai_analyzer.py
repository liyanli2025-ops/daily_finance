"""
AI 分析服务
使用 Claude API 进行新闻分析、报告生成和投资建议

增强版：
- 集成 AKShare 真实市场数据，让 AI 基于真实数据进行分析
- 集成 FinBERT 深度情感分析，提供更精准的市场情绪判断
- 统一自选股管理（配置文件 + 数据库）
"""
import json
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any
import uuid

from ..config import settings
from ..models.news import News, SentimentType, NewsType, SentimentStrength
from ..models.report import (
    Report, ReportCreate, NewsHighlight, MarketAnalysis,
    IndexSnapshot, MarketTrend, SentimentType as ReportSentiment,
    ReportSection, ReportSectionType, AnalysisHighlight,
    CrossBorderEvent, CrossBorderCategory, ReportType
)
from ..models.stock import StockPrediction, PredictionType
from .market_data_service import get_market_data_service, MarketOverview
from .watchlist_service import get_watchlist_service
from .topic_history_service import get_topic_history_service


class AIAnalyzerService:
    """AI 分析服务"""
    
    def __init__(self):
        self.anthropic_client = None
        self.openai_client = None
        self.using_free_service = False  # 是否使用免费服务
        self._init_clients()
    
    def _init_clients(self):
        """初始化 AI 客户端"""
        # 尝试初始化 Anthropic
        if settings.anthropic_api_key:
            try:
                from anthropic import Anthropic
                self.anthropic_client = Anthropic(api_key=settings.anthropic_api_key)
                print("[OK] Anthropic 客户端初始化成功")
            except Exception as e:
                print(f"[WARN] Anthropic 初始化失败: {e}")
        
        # 尝试初始化 OpenAI（备选）
        if settings.openai_api_key:
            try:
                from openai import OpenAI
                kwargs = {"api_key": settings.openai_api_key}
                if settings.openai_base_url:
                    kwargs["base_url"] = settings.openai_base_url
                self.openai_client = OpenAI(**kwargs)
                print(f"[OK] OpenAI 客户端初始化成功 (base_url: {settings.openai_base_url or 'default'})")
            except Exception as e:
                print(f"[WARN] OpenAI 初始化失败: {e}")
        
        # 如果没有配置任何 API，自动使用免费的 Pollinations.AI
        if not self.anthropic_client and not self.openai_client:
            try:
                from openai import OpenAI
                # Pollinations.AI 免费服务，无需 API Key
                self.openai_client = OpenAI(
                    api_key="free",
                    base_url="https://text.pollinations.ai/openai"
                )
                self.using_free_service = True
                print("[OK] 使用免费 Pollinations.AI 服务（无需配置）")
            except Exception as e:
                print(f"[WARN] Pollinations.AI 初始化失败: {e}")
    
    async def analyze_news_sentiment(self, news: News) -> SentimentType:
        """
        分析单条新闻的情绪倾向
        """
        prompt = f"""分析以下财经新闻的情绪倾向，只返回一个词：positive（正面/利好）、negative（负面/利空）、neutral（中性）。

标题：{news.title}
内容：{news.content[:500]}

请直接返回情绪词，不要有任何其他内容："""
        
        response = await self._call_ai(prompt, max_tokens=10)
        
        if "positive" in response.lower():
            return SentimentType.POSITIVE
        elif "negative" in response.lower():
            return SentimentType.NEGATIVE
        else:
            return SentimentType.NEUTRAL
    
    async def generate_daily_report(
        self, 
        news_list: List[News], 
        cross_border_news: List[News] = None,
        report_type: ReportType = ReportType.MORNING,
        is_trading_day: bool = True,
        morning_report: Optional[Report] = None
    ) -> Report:
        """
        生成每日财经报告（支持早报/晚报/非交易日深度版）
        
        Args:
            news_list: 财经新闻列表
            cross_border_news: 跨界新闻列表
            report_type: 报告类型（morning早报/evening晚报）
            is_trading_day: 是否是交易日
            morning_report: 今日早报（晚报时用于回顾对比）
            
        Returns:
            生成的报告对象
        """
        today = date.today()
        weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        weekday_name = weekday_names[today.weekday()]
        
        # 计算上一个交易日（市场数据实际对应的日期）
        last_trading = today - timedelta(days=1)
        while last_trading.weekday() >= 5:
            last_trading -= timedelta(days=1)
        last_trading_str = f"{last_trading.month}月{last_trading.day}日{weekday_names[last_trading.weekday()]}"
        
        # 【新增】获取自选股配置
        watchlist_text = self._prepare_watchlist_analysis()
        investment_style_desc = self._get_investment_style_description()
        
        # 【新增】获取真实市场数据（带容错）
        print("[AI] 正在获取真实市场数据...")
        try:
            market_service = get_market_data_service()
            market_data: MarketOverview = await market_service.get_market_overview(today)
            market_data_text = market_data.to_prompt_text()
            print(f"[AI] 市场数据获取完成：{len(market_data.indices)} 个指数，{len(market_data.top_sectors)} 个热门板块，"
                  f"{len(market_data.concept_sectors)} 个概念板块，"
                  f"{len(market_data.consecutive_limit_stocks)} 只连板股，"
                  f"{len(market_data.tech_signal_stocks)} 只技术信号股")
        except Exception as e:
            print(f"[WARN] 市场数据获取失败，将使用空数据继续生成报告: {e}")
            market_data = MarketOverview(date=today.strftime("%Y-%m-%d"))
            market_data_text = "（市场数据暂不可用，请基于新闻信息进行分析）"
        
        # 【新增】计算市场情绪指数
        sentiment_index_text = self._prepare_sentiment_index(news_list, cross_border_news or [])
        
        # 准备新闻摘要
        finance_summary = self._prepare_news_summary_with_sentiment(news_list)
        cross_border_summary = self._prepare_cross_border_summary(cross_border_news or [])
        
        # 根据报告类型选择不同的 prompt
        if report_type == ReportType.EVENING:
            # 晚报 prompt
            report_prompt = self._build_evening_report_prompt(
                today, weekday_name, last_trading_str,
                watchlist_text, investment_style_desc,
                market_data_text, sentiment_index_text,
                finance_summary, cross_border_summary,
                morning_report
            )
        elif not is_trading_day:
            # 非交易日深度版早报 prompt
            report_prompt = self._build_weekend_report_prompt(
                today, weekday_name, last_trading_str,
                watchlist_text, investment_style_desc,
                market_data_text, sentiment_index_text,
                finance_summary, cross_border_summary
            )
        else:
            # 交易日早报 prompt
            report_prompt = self._build_morning_report_prompt(
                today, weekday_name, last_trading_str,
                watchlist_text, investment_style_desc,
                market_data_text, sentiment_index_text,
                finance_summary, cross_border_summary
            )
        
        response = await self._call_ai(report_prompt, max_tokens=8000)
        
        # 解析响应
        report = self._parse_enhanced_report_response(
            response, today, news_list, cross_border_news or [], report_type
        )
        
        return report
    
    def _build_morning_report_prompt(
        self, today, weekday_name, last_trading_str,
        watchlist_text, investment_style_desc,
        market_data_text, sentiment_index_text,
        finance_summary, cross_border_summary
    ) -> str:
        """
        构建交易日早报 prompt
        
        特点：
        - 整体性写作，一气呵成
        - 结合前一个交易日的市场情况
        - 侧重当天操作建议
        - 话题去重（避免重复科普）
        """
        # 获取整体性写作哲学和话题去重提示
        writing_philosophy = self._get_writing_philosophy()
        topic_dedup = self._get_topic_dedup_prompt()
        
        return f"""你是{settings.user_nickname}的私人投资顾问，拥有20年A股和港股实战经验。
你的核心使命：**每一段分析都必须回答"所以我该怎么做"**。

{writing_philosophy}

## 🌅 早报定位

这是**交易日早报**，在开盘前生成。核心目标是：
1. 帮{settings.user_nickname}快速了解昨夜今晨的重要信息
2. 给出**今日操作的具体建议**
3. 预判今日市场走势，提前布局

你的风格：
- 直接给结论，再讲逻辑——先告诉我"买还是卖"，再解释为什么
- 敢于提出反共识观点——市场都看多时，你要指出盲点；市场恐慌时，你要找到机会
- 不说废话——禁止"值得关注""需要注意""密切跟踪"等模糊表述，必须说"建议买入/卖出/观望/加仓/减仓"
- 每个观点后必须有一句【操作建议】
- **板块和行业要细致，最好带上具体股票名称**

## 🎯 今日任务

今天是{today.strftime('%Y年%m月%d日')} {weekday_name}。
⚠️ 本报告在开盘前生成，市场数据来自上一个交易日（{last_trading_str}）的收盘数据。

### 用户画像
- 昵称：{settings.user_nickname}
- 投资风格：{investment_style_desc}

{watchlist_text}

---

## 📊 真实市场数据（上一交易日收盘）

{market_data_text}

---

{sentiment_index_text}

---

## 📰 昨夜今晨财经新闻（含情感标签）

{finance_summary}

## 🌍 跨界热点

{cross_border_summary if cross_border_summary else "暂无重大跨界热点"}

{topic_dedup}

---

## 📝 早报结构（5大模块）——必须一气呵成

⚠️ 重要：以下模块仅是内容框架，你写出来的文章必须是**一个整体**，模块之间要有自然的逻辑过渡，不能有割裂感。

### 模块1：🎯 今日三条操作建议

**这是全文最重要的部分，开门见山。**

给出3条**可执行的操作建议**：
- 格式：**建议X（置信度：高/中/低）**：做什么 + 为什么 + 风险是什么
- 每条建议必须包含：具体的操作动作（买入/卖出/加仓/减仓/观望）+ **具体标的或板块+代表个股** + 理由 + 止损条件
- 参考市场情绪指数判断当前阶段

示例：
> **建议一（置信度：高）**：今日逢低加仓半导体板块，重点关注北方华创（002371）、中微公司（688012），目标仓位从2成提到3成。理由：昨夜费城半导体指数大涨3.2%，情绪指数+0.45偏多。止损位：如果3日内板块跌超3%则减回2成。

### 模块2：📈 市场全景：大盘+板块+资金

1. **大盘研判**：昨日收盘+隔夜外盘+今日预判→ **结论：今日大盘偏多还是偏空？给出具体点位区间**
2. **隔夜外盘**：美股、港股夜盘、商品期货的表现→ **对A股的影响判断**
3. **资金暗语**：北向资金+主力资金流向→ **结论：聪明钱在往哪个方向押注？**
4. **板块机会**：
   - 今日看好的板块（带具体个股）：为什么看好？建议什么价位介入？
   - 今日需要回避的板块：为什么回避？
   - ⚠️ **概念板块**：市场数据中提供了概念板块排行（如有），结合行业板块一起分析，找出资金共识方向
5. **连板龙头**：
   - 市场数据中提供了连板强势股（如有），分析连板股背后代表的市场主线和情绪
   - 判断哪些连板股是真龙头（有概念+资金共识），哪些是纯情绪投机

### 模块2.5：🎯 技术信号机会股点评

市场数据中提供了技术信号机会股（如有），这些是经过MACD金叉、均线多头排列、KDJ金叉、放量等多因子扫描筛选出的股票。请对信号得分最高的3-5只做简要点评：
- 这些信号意味着什么？（用通俗语言解释）
- 结合基本面判断：技术信号强 ≠ 值得买，还要看行业景气度和估值
- 给出具体建议：哪些值得关注跟踪，哪些信号可能是假突破
- **注意**：不要逐条罗列数据，而是挑最有故事性的2-3只深入分析

### 模块3：⭐ 自选股作战图

{self._get_watchlist_analysis_prompt()}

对每只自选股，必须给出：
- **信号**：明确的买入/持有/减仓/清仓/观望
- **目标价**：短期（1-2周）目标价位
- **止损位**：跌破多少必须走
- **仓位建议**：建议占总仓位的百分比
- **一句话理由**

### 模块4：⚡ 今日事件催化

今天盘中可能影响市场的事件（经济数据发布、政策会议、公司公告等）：
- 事件内容和发布时间
- 乐观情景下怎么操作
- 悲观情景下怎么操作

### 模块5：🛡️ 风控仪表盘

1. **总仓位建议**：今日应该几成仓？
2. **仓位分配**：大盘蓝筹 vs 中小成长 vs 现金
3. **雷区预警**：今日需要特别注意的风险点

---

## ✍️ 写作风格

1. **结论先行**：每段先给操作建议，再讲逻辑
2. **数据说话**：每个观点引用具体数字
3. **具体到个股**：板块建议要带上代表性个股名称和代码
4. **通俗直白**：像给朋友打电话聊投资一样说话
5. **一气呵成**：全文是一个有机整体，不是5个独立段落

## ⛔ 禁止

- 不要有模板化开头
- 不要只描述现象不给建议
- 不要泛泛而谈，要具体到个股
- 不要有割裂感——模块之间必须有逻辑串联

## 📤 结构化输出

在报告末尾，用 ```json 包裹输出以下数据：

```json
{{
  "title": "结合当前市场特征的标题（要有观点和具体板块，如'半导体利好，今日加仓芯片龙头'）",
  "summary": "200字精华摘要（核心操作建议+关键数据）",
  "core_opinions": [
    "操作建议1（含具体动作+标的+理由+止损）",
    "操作建议2",
    "操作建议3"
  ],
  "market_score": 65,
  "position_advice": "6成",
  "highlights": [...],
  "watchlist_analysis": [...],
  "market_analysis": {{
    "overall_sentiment": "positive/negative/neutral",
    "trend": "bullish/bearish/neutral",
    "key_factors": [...],
    "opportunities": [...],
    "risks": [...]
  }},
  "hot_sectors": ["热门板块1（代表个股）", "板块2（代表个股）"],
  "risk_sectors": ["风险板块1", "风险板块2"]
}}
```

请开始撰写早报："""

    def _build_evening_report_prompt(
        self, today, weekday_name, last_trading_str,
        watchlist_text, investment_style_desc,
        market_data_text, sentiment_index_text,
        finance_summary, cross_border_summary,
        morning_report: Optional[Report] = None
    ) -> str:
        """
        构建交易日晚报 prompt
        
        v2 重构：
        - 注入整体性写作哲学
        - 早报回顾精简为附属内容（不再占整个模块）
        - 模块三扩展为"今日投资课堂"（含热门新闻/行业/概念 + 去重）
        - 新增明日作战地图（三情景推演）
        - 全文一气呵成，不割裂
        """
        # 获取整体性写作哲学和话题去重提示
        writing_philosophy = self._get_writing_philosophy()
        topic_dedup = self._get_topic_dedup_prompt()
        
        # 准备早报回顾内容（精简版）
        morning_review = ""
        if morning_report:
            morning_review = f"""
## 📋 今日早报回顾（精简版）

今天早上给{settings.user_nickname}的核心建议是：
- **标题**：{morning_report.title}
"""
            for i, opinion in enumerate(morning_report.core_opinions or [], 1):
                # 每条建议只取前60字
                short_opinion = opinion[:60] + "..." if len(opinion) > 60 else opinion
                morning_review += f"- 建议{i}：{short_opinion}\n"
            
            morning_review += f"""
请在晚报分析中自然地穿插评价这些预判的准确性（对了就说对了，错了就坦诚认错并分析原因），不需要单独开一个大模块来回顾。

---
"""
        
        return f"""你是{settings.user_nickname}的私人投资顾问，拥有20年A股和港股实战经验。

{writing_philosophy}

## 🌆 晚报定位

这是**交易日晚报**，在收盘后生成。核心目标是：
1. 深度复盘今日市场，找到涨跌背后的真正原因
2. 穿插回顾早报预测的准确性（自然地融入复盘中，不单独开模块）
3. 今日投资课堂：讲一个有价值的话题（热门概念/行业/投资知识，但不能和近期重复）
4. 给出明日可执行的操作策略

你的风格：
- 复盘要客观，有数据支撑
- 敢于承认早报预判失误，坦诚分析原因
- 分析有深度，不停留在表面
- 明日预测要具体可执行
- **全文一气呵成，不要有模块割裂感**

## 🎯 今日任务

今天是{today.strftime('%Y年%m月%d日')} {weekday_name}。
本报告在收盘后生成，反映今日实际交易情况。

### 用户画像
- 昵称：{settings.user_nickname}
- 投资风格：{investment_style_desc}

{watchlist_text}

{morning_review}

---

## 📊 今日市场数据

{market_data_text}

---

{sentiment_index_text}

---

## 📰 今日财经要闻

{finance_summary}

## 🌍 今日跨界热点

{cross_border_summary if cross_border_summary else "暂无重大跨界热点"}

{topic_dedup}

---

## 📝 晚报结构（6大模块）——必须一气呵成

⚠️ 重要：以下模块仅是内容框架，你写出来的文章必须是**一个完整的叙事**。想象你在{settings.user_nickname}对面坐下来，从今天发生了什么 → 为什么会这样 → 所以我们学到了什么 → 明天该怎么做，自然地聊下来。

### 模块1：📊 今日市场一句话

**30秒快速概括**，先告诉{settings.user_nickname}今天大盘怎么样：
- 用一两句话精准概括今天市场的核心特征（如："今天科技股大涨半导体领涨，但消费板块集体调整"）
- 今天市场的"关键词"是什么

### 模块2：🔍 深度复盘——涨跌背后的真相

**这是晚报的核心，要有深度的因果链分析：**

不要只罗列"涨了什么跌了什么"，要深入分析：
1. **表面现象**：今天大盘涨跌了多少？哪些板块领涨领跌？
2. **深层原因**：为什么涨？为什么跌？是政策驱动？资金驱动？消息驱动？
3. **投资逻辑**：这背后反映了什么样的市场逻辑？对你未来的操作有什么启示？
4. **资金面**：北向资金、主力资金今天怎么操作的？透露了什么信号？
5. **概念板块暗线**：结合概念板块排行数据（如有），挖掘今天的隐藏主线——哪些概念在悄悄发酵？
6. **连板股信号**：今天的连板股（如有）反映了市场什么样的投机情绪？连板股背后的题材是否有持续性？
7. **技术信号机会股**：市场数据中提供了技术信号机会股（如有），点评信号得分最高的2-3只——技术信号验证了还是被打脸了？

如果今天早报有预判，在分析过程中自然穿插评价：
- "今天早上我说会涨，确实涨了，但涨的原因和我预判的不太一样..."
- "坦白说，今天的走势出乎我的预料，错在..."

### 模块3：💡 今日投资课堂

**从今天的市场实战中，引出一个有价值的知识点或热门话题：**

可以讲的内容范围（选择其一即可）：
- **时下热门概念/行业**：今天市场上最火的概念是什么？用大白话科普
- **投资知识/技巧**：从今天的实际案例引出一个投资方法或理念
- **新兴技术/趋势**：今天出现的新技术、新政策、新赛道解读
- **经典投资理论的新应用**：结合今天的案例讲一个经典理论

每个话题要包含：
- 是什么（通俗解释）
- 为什么今天/最近火了
- 投资机会在哪里
- 有什么风险/坑

⚠️ 这个模块要和前面的复盘有**逻辑关联**。比如今天半导体板块大涨，你可以借机科普"半导体周期理论"或者讲讲"国产替代的投资逻辑"。不要硬插一个完全无关的话题。

### 模块4：⭐ 自选股作战室

{self._get_watchlist_analysis_prompt()}

对每只自选股总结今日表现：
- 今日涨跌幅
- 成交量变化
- 是否符合早报预期
- **明日操作建议**（继续持有/加仓/减仓/止损）+ 目标价/止损价
- **一句话策略**

### 模块5：🗺️ 明日作战地图

基于今日复盘，用**三情景推演法**预判明天：

| 情景 | 概率 | 大盘走势 | 板块机会 | 操作建议 |
|------|------|---------|---------|---------|
| 乐观情景 | X% | ... | ... | ... |
| 中性情景 | X% | ... | ... | ... |
| 悲观情景 | X% | ... | ... | ... |

给出**3条明日操作建议**（格式同早报）。

⚠️ 制定明日策略时，参考今日的连板股走势（判断市场情绪是否可持续）和技术信号机会股（哪些技术突破的股票明天可能延续）。

### 模块6：🛡️ 风险提示 + 早报准确度回顾

1. 总仓位调整建议
2. 需要注意的风险事件（明天的经济数据、财报、解禁等）
3. 需要设置止损的持仓
4. **今日早报预判综合评分**：X/10（一句话总结经验教训）

---

## ✍️ 写作风格

1. **复盘客观**：用数据说话，不美化也不丑化
2. **敢于认错**：早报预判失误要坦诚分析原因
3. **概念科普**：新概念解释要通俗易懂，从实际案例引出
4. **预判具体**：明日建议要可执行
5. **一气呵成**：全文是一个完整的投资分析叙事

## ⛔ 禁止

- 不要把"早报回顾"做成一个死板的逐条对照表
- 不要让"投资课堂"和前后文完全割裂
- 不要只描述现象不分析原因

## 📤 结构化输出

在报告末尾，用 ```json 包裹输出以下数据：

```json
{{
  "title": "晚报标题（如'半导体如期大涨，明日关注回调机会'）",
  "summary": "200字精华摘要",
  "core_opinions": [
    "明日操作建议1",
    "明日操作建议2", 
    "明日操作建议3"
  ],
  "morning_accuracy": 75,
  "morning_review": "早报预测回顾总结（一句话）",
  "new_concepts": ["今日课堂话题"],
  "today_lesson": "今日投资课堂的主题名称",
  "market_analysis": {{
    "overall_sentiment": "positive/negative/neutral",
    "trend": "bullish/bearish/neutral",
    "key_factors": [...],
    "opportunities": [...],
    "risks": [...]
  }},
  "tomorrow_outlook": {{
    "direction": "bullish/bearish/neutral",
    "key_levels": "支撑位xxx，压力位xxx",
    "hot_sectors": ["板块1", "板块2"],
    "risk_sectors": ["风险板块1"]
  }}
}}
```

请开始撰写晚报："""

    def _build_weekend_report_prompt(
        self, today, weekday_name, last_trading_str,
        watchlist_text, investment_style_desc,
        market_data_text, sentiment_index_text,
        finance_summary, cross_border_summary
    ) -> str:
        """
        构建非交易日深度早报 prompt
        
        v2 重构：
        - 注入整体性写作哲学
        - 话题去重
        - 全文一气呵成的叙事结构
        """
        # 获取整体性写作哲学和话题去重提示
        writing_philosophy = self._get_writing_philosophy()
        topic_dedup = self._get_topic_dedup_prompt()
        
        return f"""你是{settings.user_nickname}的私人投资顾问，拥有20年A股和港股实战经验。

{writing_philosophy}

## 🏖️ 非交易日深度早报定位

今天是**非交易日**（周末或节假日），A股休市。本期是**深度早报**，不追求时效性，而是做深度分析和科普。

核心目标：
1. **本周复盘**：系统梳理本周市场表现
2. **深度科普**：解释本周热点概念、新技术、政策（注意去重，不要讲近期讲过的）
3. **行业聚焦**：深入分析市场讨论最多的行业和企业
4. **下周展望**：给出下周操作策略

你的风格：
- 深度分析，不求快但求深
- 科普内容要通俗易懂，小白也能听懂
- 数据详实，有理有据
- 给出可执行的下周操作建议
- **全文像一次深度对话，不像一份枯燥的报告**

## 🎯 今日任务

今天是{today.strftime('%Y年%m月%d日')} {weekday_name}，非交易日。
市场数据来自上一个交易日（{last_trading_str}）的收盘数据。

### 用户画像
- 昵称：{settings.user_nickname}
- 投资风格：{investment_style_desc}

{watchlist_text}

---

## 📊 本周市场数据

{market_data_text}

---

{sentiment_index_text}

---

## 📰 本周重要财经新闻

{finance_summary}

## 🌍 本周跨界热点

{cross_border_summary if cross_border_summary else "暂无重大跨界热点"}

{topic_dedup}

---

## 📝 深度早报结构（7大模块，时长更长）——必须一气呵成

⚠️ 重要：想象你周末约{settings.user_nickname}喝咖啡，从头到尾聊一个小时投资。从本周发生了什么 → 为什么 → 这些热点概念到底是什么 → 哪些行业值得深入研究 → 下周怎么操作。这是一次**完整的深度对话**，不是7个独立的段落。

### 模块1：📊 本周市场复盘

**系统梳理本周市场表现：**
- 主要指数本周涨跌幅及走势分析
- 本周领涨板块TOP5和领跌板块TOP5
- **概念板块暗线**：概念板块排行数据（如有）揭示了哪些隐性投资主线？哪些概念在连续发酵？
- 北向资金本周流入流出情况
- 本周市场情绪变化曲线
- **连板股回顾**：本周有哪些连板妖股？它们背后代表什么市场主线？哪些是真龙头、哪些是击鼓传花？
- **技术信号精选**：本周末技术信号机会股（如有）中，哪些下周值得重点跟踪？结合基本面做深度筛选
- 本周市场的核心主线是什么

### 模块2：🎓 本周热点概念科普（重点模块）

**这是非交易日深度版的核心特色，做好科普：**

选取本周市场讨论最热的2-3个概念/技术/政策，做深度科普：

每个概念包含：
1. **是什么**：用大白话解释这个概念
2. **为什么火**：政策背景、事件催化
3. **产业链拆解**：上游、中游、下游分别是什么
4. **受益标的**：哪些公司最受益，为什么
5. **投资节奏**：现在是什么阶段？是初期炒预期还是业绩兑现期？
6. **风险提示**：有什么坑要避免

⚠️ 概念科普要和前面的市场复盘有**因果关联**——从本周的市场表现中自然引出。

### 模块3：🏭 本周行业深度

**选取本周讨论度最高的1-2个行业，做深度分析：**

包含：
- 行业本周表现及原因
- 行业政策面变化
- 行业基本面变化（订单、产能、价格等）
- 行业龙头公司近况
- 行业估值分析（贵了还是便宜）
- 下周行业展望

### 模块4：🏢 本周明星企业

**选取本周市场关注度最高的2-3家企业：**
- 为什么被关注（财报、公告、新闻）
- 公司基本面分析
- 技术面分析
- 投资价值评估

### 模块5：⭐ 自选股本周总结

{self._get_watchlist_analysis_prompt()}

对每只自选股做本周总结：
- 本周涨跌幅
- 本周重要事件
- 技术面位置
- **下周操作建议**

### 模块6：🔮 下周展望与策略

1. **宏观日历**：下周有哪些重要事件（经济数据、政策会议、财报等）
2. **大盘预判**：下周大概率是涨是跌？关键点位在哪
3. **板块轮动**：哪些板块下周可能轮动到（结合概念板块趋势判断）
4. **连板股启示**：本周的连板题材下周还有持续性吗？有无新的接力题材？
5. **技术信号跟踪**：技术信号机会股中，哪些值得下周一开盘关注？
6. **三条操作建议**：下周一开盘具体怎么做

### 模块7：📚 投资知识小课堂

结合本周的实际案例，讲一个投资知识点：
- 可以是技术分析方法
- 可以是基本面分析框架
- 可以是风险控制技巧
- 用案例说明，生动易懂

⚠️ 这个知识点要和前面的分析有**自然关联**，不要硬插。

---

## ✍️ 写作风格

1. **深入浅出**：专业内容用大白话讲
2. **数据详实**：多用数据支撑观点
3. **案例丰富**：用实际案例解释概念
4. **可听性强**：适合播客收听，节奏适中
5. **一气呵成**：全文是一次完整的深度对话

## ⛔ 禁止

- 不要让科普模块和其他模块割裂
- 不要讲近期已经讲过的话题（参考去重列表）

## 📤 结构化输出

在报告末尾，用 ```json 包裹输出以下数据：

```json
{{
  "title": "非交易日深度版标题（如'本周复盘：AI主线不变，下周关注低位补涨'）",
  "summary": "300字精华摘要（本周要点+下周建议）",
  "core_opinions": [
    "下周操作建议1",
    "下周操作建议2",
    "下周操作建议3"
  ],
  "weekly_review": {{
    "market_performance": "本周市场整体表现总结",
    "hot_themes": ["本周热点主题1", "主题2"],
    "top_sectors": ["领涨板块1", "板块2"],
    "bottom_sectors": ["领跌板块1", "板块2"]
  }},
  "concept_tutorials": [
    {{
      "name": "概念名称",
      "explanation": "通俗解释",
      "beneficiaries": ["受益标的1", "标的2"]
    }}
  ],
  "today_lesson": "本期投资课堂的核心话题",
  "next_week_outlook": {{
    "direction": "bullish/bearish/neutral",
    "key_events": ["重要事件1", "事件2"],
    "opportunities": ["机会板块1", "板块2"],
    "risks": ["风险点1", "风险2"]
  }},
  "market_analysis": {{
    "overall_sentiment": "positive/negative/neutral",
    "trend": "bullish/bearish/neutral",
    "key_factors": [...],
    "opportunities": [...],
    "risks": [...]
  }}
}}
```

请开始撰写非交易日深度早报："""
    
    def _prepare_watchlist_analysis(self) -> str:
        """
        准备自选股分析文本
        
        统一从配置文件和数据库加载自选股
        """
        watchlist_service = get_watchlist_service()
        
        # 从配置加载
        watchlist_service.load_from_config(settings.watchlist_stocks)
        
        # 尝试从数据库加载（同步方式读取）
        try:
            import sqlite3
            from pathlib import Path
            
            db_path = Path(settings.database_url.replace("sqlite:///", ""))
            if db_path.exists():
                conn = sqlite3.connect(str(db_path))
                cursor = conn.cursor()
                cursor.execute("SELECT code, name, market FROM stocks")
                rows = cursor.fetchall()
                conn.close()
                
                if rows:
                    db_stocks = [{"code": row[0], "name": row[1], "market": row[2]} for row in rows]
                    watchlist_service.load_from_database(db_stocks)
                    print(f"[AI] 从数据库加载了 {len(db_stocks)} 只自选股")
        except Exception as e:
            print(f"[AI] 数据库自选股加载失败: {e}")
        
        return watchlist_service.format_for_prompt()
    
    def _get_watchlist_analysis_prompt(self) -> str:
        """
        生成自选股分析提示
        
        使用统一的自选股服务
        """
        watchlist_service = get_watchlist_service()
        
        # 确保已加载（_prepare_watchlist_analysis 应该先被调用）
        all_stocks = watchlist_service.get_all_stocks()
        
        if not all_stocks:
            # 尝试重新加载
            watchlist_service.load_from_config(settings.watchlist_stocks)
            all_stocks = watchlist_service.get_all_stocks()
        
        return watchlist_service.format_analysis_prompt()
    
    def _get_investment_style_description(self) -> str:
        """获取投资风格描述"""
        style = settings.investment_style.lower()
        descriptions = {
            "conservative": "保守型（偏好低风险、稳健收益、高股息股票）",
            "balanced": "平衡型（风险收益均衡，接受适度波动）",
            "aggressive": "激进型（追求高收益，能承受较大波动）"
        }
        return descriptions.get(style, descriptions["balanced"])
    
    def _get_writing_philosophy(self) -> str:
        """
        所有报告共享的整体性写作哲学
        
        确保早报、晚报、周末报告都像一位资深投资顾问写的
        一篇浑然一体的文章，而不是拼凑的模块。
        """
        return f"""
## 写作核心原则：一气呵成的整体性（极其重要！）

你不是在"填模板"或"分模块拼凑"，你是在写一篇有灵魂、有逻辑、有温度的投资分析文章。
你是{settings.user_nickname}的私人投资顾问，有20年实战经验，有自己的判断框架和投资哲学。

### 1. 逻辑链贯穿全文
- 各模块之间必须有**因果链条**串联，像讲故事一样层层推进
- 复盘不是孤立的复盘，而是为后续分析铺垫
- 投资课堂不是硬插入的科普，而是从今天的实际市场案例中**自然引出**
- 明日预判不是拍脑袋猜，而是从今天的因果链条中**推导出来**
- 错误示范：先讲大盘涨了，然后硬插一个无关概念，再讲明天预测
- 正确示范：今天大盘大涨3%，主要因为XX政策 → 这让我想给你讲讲XX的投资逻辑 → 基于这个逻辑，明天XX板块大概率...

### 2. 人格统一
- 你有自己的分析风格和口头禅，不要每段换一种说话方式
- 敢于在不确定时说"我也不确定，但我倾向于..."
- 有自己的判断，不做墙头草
- 对{settings.user_nickname}有真诚的关心，把他的钱当自己的钱看待

### 3. 因果呼应
- 前面提到的数据、事件，后面的分析和建议必须回应
- 不要"提了不管"——每个信息点都要有后续
- 结尾的操作建议必须是全文分析的自然结论，而不是突然蹦出来的

### 4. 过渡自然
- 模块之间要有自然的过渡句，不要生硬地说"接下来看模块X"
- 好的过渡："说完了大盘，我们自然要问一个问题：这波行情里，你的自选股表现怎么样？"
- 差的过渡："接下来是自选股分析部分。"
"""
    
    def _get_topic_dedup_prompt(self) -> str:
        """
        获取话题去重提示文本
        
        从数据库查询最近7天的报告，提取已讲过的话题，
        生成提示文本注入到 prompt 中。
        """
        try:
            topic_service = get_topic_history_service()
            dedup_text = topic_service.format_dedup_prompt(days=7)
            if dedup_text:
                print(f"[AI] 话题去重：已加载近7天历史话题")
            return dedup_text
        except Exception as e:
            print(f"[AI] 话题去重服务异常，跳过: {e}")
            return ""
    
    async def analyze_stock(self, code: str, name: str, market: str,
                           fundamentals: Dict, technicals: Dict, 
                           related_news: List[News]) -> StockPrediction:
        """
        生成股票投资预判
        """
        from ..models.stock import FundamentalData, TechnicalData, SentimentData, MarketType
        
        # 准备新闻摘要
        news_text = "\n".join([
            f"- {n.title} ({n.sentiment.value})" 
            for n in related_news[:10]
        ])
        
        prompt = f"""你是一位专业的股票分析师，请对以下股票进行综合分析并给出投资建议。

## 股票信息
- 代码：{code}
- 名称：{name}
- 市场：{'A股' if market == 'A' else '港股'}

## 基本面数据
{json.dumps(fundamentals, ensure_ascii=False, indent=2)}

## 技术指标
{json.dumps(technicals, ensure_ascii=False, indent=2)}

## 相关新闻
{news_text if news_text else "暂无相关新闻"}

## 分析要求

请给出：
1. 综合评估（看多/中性/看空）
2. 置信度（0-100分）
3. 目标价位（如果看多）
4. 止损价位建议
5. 详细分析理由（200-300字）

请以 JSON 格式输出：
```json
{{
  "prediction": "bullish/neutral/bearish",
  "confidence": 75,
  "target_price": 100.00,
  "stop_loss": 90.00,
  "fundamental_score": 0.7,
  "technical_score": 0.6,
  "sentiment_score": 0.65,
  "reasoning": "详细分析理由..."
}}
```"""

        response = await self._call_ai(prompt, max_tokens=1000)
        
        # 解析响应
        prediction_data = self._extract_json(response)
        
        return StockPrediction(
            code=code,
            name=name,
            market=MarketType(market),
            current_price=technicals.get("current_price", 0),
            fundamentals=FundamentalData(**fundamentals) if fundamentals else FundamentalData(),
            technicals=TechnicalData(**technicals) if technicals else TechnicalData(),
            sentiment=SentimentData(
                news_count=len(related_news),
                positive_news=sum(1 for n in related_news if n.sentiment == SentimentType.POSITIVE),
                negative_news=sum(1 for n in related_news if n.sentiment == SentimentType.NEGATIVE)
            ),
            prediction=PredictionType(prediction_data.get("prediction", "neutral")),
            confidence=prediction_data.get("confidence", 50) / 100,
            target_price=prediction_data.get("target_price"),
            stop_loss=prediction_data.get("stop_loss"),
            reasoning=prediction_data.get("reasoning", "分析生成失败"),
            fundamental_score=prediction_data.get("fundamental_score", 0.5),
            technical_score=prediction_data.get("technical_score", 0.5),
            sentiment_score=prediction_data.get("sentiment_score", 0.5),
            overall_score=(
                prediction_data.get("fundamental_score", 0.5) * 0.4 +
                prediction_data.get("technical_score", 0.5) * 0.35 +
                prediction_data.get("sentiment_score", 0.5) * 0.25
            ),
            generated_at=datetime.now()
        )
    
    async def analyze_stock_simple(self, code: str, name: str, market: str,
                                   current_price: float = 0, change_percent: float = 0) -> StockPrediction:
        """
        简化版股票预测 - 快速生成 AI 预测
        
        不需要完整的基本面和技术面数据，适合批量预测
        """
        from ..models.stock import FundamentalData, TechnicalData, SentimentData, MarketType
        
        prompt = f"""你是一位专业的股票分析师。请对以下股票给出简短的投资评级。

## 股票信息
- 代码：{code}
- 名称：{name}
- 市场：{'A股' if market == 'A' else '港股'}
- 当前价格：{current_price:.2f}
- 今日涨跌：{change_percent:+.2f}%

## 要求

基于你对这只股票的了解（公司基本面、行业地位、近期消息等），给出：
1. 投资评级：看多(bullish) / 中性(neutral) / 看空(bearish)
2. 置信度：0-100 分
3. 简短理由：50字以内

请以 JSON 格式输出：
```json
{{
  "prediction": "bullish/neutral/bearish",
  "confidence": 70,
  "reasoning": "理由..."
}}
```"""
        
        try:
            response = await self._call_ai(prompt, max_tokens=300)
            prediction_data = self._extract_json(response)
        except Exception as e:
            print(f"[AI] analyze_stock_simple 失败: {e}")
            prediction_data = {
                "prediction": "neutral",
                "confidence": 50,
                "reasoning": "AI 分析暂时不可用"
            }
        
        prediction_str = prediction_data.get("prediction", "neutral").lower()
        if prediction_str not in ["bullish", "bearish", "neutral"]:
            prediction_str = "neutral"
        
        confidence = prediction_data.get("confidence", 50)
        if isinstance(confidence, (int, float)):
            confidence = min(100, max(0, confidence)) / 100
        else:
            confidence = 0.5
        
        return StockPrediction(
            code=code,
            name=name,
            market=MarketType(market),
            current_price=current_price,
            fundamentals=FundamentalData(),
            technicals=TechnicalData(),
            sentiment=SentimentData(),
            prediction=PredictionType(prediction_str),
            confidence=confidence,
            target_price=None,
            stop_loss=None,
            reasoning=prediction_data.get("reasoning", "暂无分析"),
            fundamental_score=0.5,
            technical_score=0.5,
            sentiment_score=0.5,
            overall_score=0.5,
            generated_at=datetime.now()
        )
    
    async def _call_ai(self, prompt: str, max_tokens: int = 4000) -> str:
        """
        调用 AI 模型
        优先使用 Anthropic，失败则尝试 OpenAI/兼容服务
        """
        import asyncio
        
        print(f"[AI DEBUG] 准备调用 AI，客户端状态:")
        print(f"   - Anthropic: {'已初始化' if self.anthropic_client else '未初始化'}")
        print(f"   - OpenAI: {'已初始化' if self.openai_client else '未初始化'}")
        print(f"   - 使用免费服务: {self.using_free_service}")
        print(f"   - 配置的模型: {settings.ai_model}")
        print(f"   - 配置的 Base URL: {settings.openai_base_url}")
        
        # 尝试 Anthropic
        if self.anthropic_client:
            try:
                message = self.anthropic_client.messages.create(
                    model=settings.ai_model,  # 使用配置文件中的模型
                    max_tokens=max_tokens,
                    messages=[
                        {"role": "user", "content": prompt}
                    ]
                )
                return message.content[0].text
            except Exception as e:
                print(f"Anthropic 调用失败: {e}")
        
        # 尝试 OpenAI/兼容服务
        if self.openai_client:
            # 免费服务可能不稳定，添加重试机制
            max_retries = 3 if self.using_free_service else 2
            
            for attempt in range(max_retries):
                try:
                    # 智能选择模型
                    if self.using_free_service:
                        model = "openai"  # Pollinations 默认使用 openai
                    elif settings.openai_base_url:
                        # 使用兼容服务时，优先使用配置的模型
                        if settings.ai_model and "claude" not in settings.ai_model.lower():
                            model = settings.ai_model
                        else:
                            # 根据 base_url 智能推断模型
                            if "deepseek" in settings.openai_base_url.lower():
                                model = "deepseek-chat"
                            elif "siliconflow" in settings.openai_base_url.lower():
                                model = "deepseek-ai/DeepSeek-V3"
                            else:
                                model = "gpt-4-turbo"
                    else:
                        # OpenAI 官方服务
                        model = settings.ai_model if "gpt" in settings.ai_model.lower() else "gpt-4-turbo"
                    
                    print(f"[AI] 调用模型: {model} (尝试 {attempt + 1}/{max_retries})")
                    
                    response = self.openai_client.chat.completions.create(
                        model=model,
                        max_tokens=max_tokens,
                        messages=[
                            {"role": "user", "content": prompt}
                        ]
                    )
                    return response.choices[0].message.content
                except Exception as e:
                    print(f"OpenAI/兼容服务调用失败 (尝试 {attempt + 1}): {e}")
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 5  # 递增等待时间
                        print(f"   等待 {wait_time} 秒后重试...")
                        await asyncio.sleep(wait_time)
        
        # 都失败了，返回模拟数据
        print("[AI] 所有 AI 服务调用失败，使用模拟报告")
        return self._generate_mock_report()
    
    def _prepare_news_summary(self, news_list: List[News]) -> str:
        """准备新闻摘要文本（旧版兼容）"""
        return self._prepare_news_summary_with_sentiment(news_list)
    
    def _prepare_news_summary_with_sentiment(self, news_list: List[News]) -> str:
        """准备新闻摘要文本（增强版：包含情感分析标签）"""
        summary_parts = []
        
        # 按重要性排序，取前20条
        sorted_news = sorted(news_list, key=lambda x: x.importance_score, reverse=True)[:20]
        
        for i, news in enumerate(sorted_news, 1):
            # 增加内容截取长度到500字，提供更多上下文
            content_preview = news.content[:500] if len(news.content) > 500 else news.content
            
            # 情感标签
            sentiment_emoji = {
                SentimentType.POSITIVE: "🟢",
                SentimentType.NEGATIVE: "🔴",
                SentimentType.NEUTRAL: "⚪"
            }.get(news.sentiment, "⚪")
            
            sentiment_text = {
                SentimentType.POSITIVE: "利好",
                SentimentType.NEGATIVE: "利空",
                SentimentType.NEUTRAL: "中性"
            }.get(news.sentiment, "中性")
            
            # 情感置信度和强度
            confidence_text = f"置信度{news.sentiment_confidence:.0%}" if hasattr(news, 'sentiment_confidence') and news.sentiment_confidence else ""
            strength_text = ""
            if hasattr(news, 'sentiment_strength') and news.sentiment_strength:
                strength_map = {
                    SentimentStrength.STRONG: "情感强烈",
                    SentimentStrength.MODERATE: "情感适中",
                    SentimentStrength.WEAK: "情感较弱"
                }
                strength_text = strength_map.get(news.sentiment_strength, "")
            
            # 情感关键词
            keywords_text = ""
            if hasattr(news, 'sentiment_keywords_positive') and news.sentiment_keywords_positive:
                keywords_text += f"正面词: {', '.join(news.sentiment_keywords_positive[:3])} "
            if hasattr(news, 'sentiment_keywords_negative') and news.sentiment_keywords_negative:
                keywords_text += f"负面词: {', '.join(news.sentiment_keywords_negative[:3])}"
            
            summary_parts.append(f"""
### {i}. {sentiment_emoji} {news.title}
- 来源：{news.source}
- 时间：{news.published_at.strftime('%H:%M')}
- **情感判断**：{sentiment_text} | {confidence_text} | {strength_text}
- **情感触发词**：{keywords_text if keywords_text else "无明显情感词"}
- 摘要：{content_preview}
""")
        
        return "\n".join(summary_parts)
    
    def _prepare_sentiment_index(self, news_list: List[News], cross_border_news: List[News]) -> str:
        """
        准备市场情绪指数文本
        
        基于 FinBERT 情感分析结果，计算整体市场情绪
        """
        all_news = news_list + cross_border_news
        
        if not all_news:
            return ""
        
        # 统计情感分布
        positive_count = 0
        negative_count = 0
        neutral_count = 0
        total_score = 0.0
        
        # 板块情绪统计
        sector_sentiment: Dict[str, List[float]] = {}
        sector_keywords = {
            "科技": ["科技", "芯片", "半导体", "AI", "人工智能", "软件", "互联网"],
            "金融": ["银行", "保险", "券商", "金融"],
            "新能源": ["新能源", "光伏", "锂电", "储能", "风电"],
            "消费": ["消费", "白酒", "食品", "零售", "餐饮", "旅游"],
            "医药": ["医药", "医疗", "生物", "制药"],
            "地产": ["地产", "房地产", "房企", "楼市"],
            "军工": ["军工", "国防", "航空", "航天"],
        }
        
        # 热词统计
        positive_keywords: Dict[str, int] = {}
        negative_keywords: Dict[str, int] = {}
        
        for news in all_news:
            weight = news.importance_score
            
            if news.sentiment == SentimentType.POSITIVE:
                positive_count += 1
                confidence = getattr(news, 'sentiment_confidence', 0.7)
                total_score += confidence * weight
            elif news.sentiment == SentimentType.NEGATIVE:
                negative_count += 1
                confidence = getattr(news, 'sentiment_confidence', 0.7)
                total_score -= confidence * weight
            else:
                neutral_count += 1
            
            # 统计板块情绪
            text = news.title + " " + news.content[:200]
            for sector, keywords in sector_keywords.items():
                if any(kw in text for kw in keywords):
                    if sector not in sector_sentiment:
                        sector_sentiment[sector] = []
                    
                    if news.sentiment == SentimentType.POSITIVE:
                        sector_sentiment[sector].append(getattr(news, 'sentiment_confidence', 0.7))
                    elif news.sentiment == SentimentType.NEGATIVE:
                        sector_sentiment[sector].append(-getattr(news, 'sentiment_confidence', 0.7))
                    else:
                        sector_sentiment[sector].append(0)
            
            # 统计热词
            if hasattr(news, 'sentiment_keywords_positive'):
                for kw in news.sentiment_keywords_positive:
                    positive_keywords[kw] = positive_keywords.get(kw, 0) + 1
            if hasattr(news, 'sentiment_keywords_negative'):
                for kw in news.sentiment_keywords_negative:
                    negative_keywords[kw] = negative_keywords.get(kw, 0) + 1
        
        total_count = len(all_news)
        if total_count == 0:
            return ""
        
        # 计算指标
        bullish_ratio = positive_count / total_count
        bearish_ratio = negative_count / total_count
        neutral_ratio = neutral_count / total_count
        
        # 归一化整体得分到 -1 ~ 1
        overall_score = total_score / total_count
        overall_score = max(-1.0, min(1.0, overall_score))
        
        # 计算板块平均情绪
        sector_avg = {
            sector: sum(scores) / len(scores) if scores else 0
            for sector, scores in sector_sentiment.items()
        }
        
        # 判断整体情感强度
        if abs(overall_score) > 0.5 or bullish_ratio > 0.6 or bearish_ratio > 0.6:
            strength = "强烈"
        elif abs(overall_score) > 0.2 or bullish_ratio > 0.4 or bearish_ratio > 0.4:
            strength = "适中"
        else:
            strength = "较弱"
        
        # 排序热词
        hot_positive = sorted(positive_keywords.items(), key=lambda x: x[1], reverse=True)[:5]
        hot_negative = sorted(negative_keywords.items(), key=lambda x: x[1], reverse=True)[:5]
        
        # 构建文本
        sentiment_desc = "偏多" if overall_score > 0.1 else "偏空" if overall_score < -0.1 else "中性"
        
        text = f"""
## 🎭 市场情绪指数（基于 {total_count} 条新闻的 FinBERT 深度情感分析）

> 这是独家优势！通过 AI 情感分析引擎对每条新闻进行情感判断，量化市场情绪。

| 指标 | 数值 | 解读 |
|------|------|------|
| **整体情绪得分** | **{overall_score:+.2f}** | **{sentiment_desc}** |
| 看多新闻占比 | {bullish_ratio*100:.1f}% | 利好消息比例 |
| 看空新闻占比 | {bearish_ratio*100:.1f}% | 利空消息比例 |
| 中性新闻占比 | {neutral_ratio*100:.1f}% | 无明显倾向 |
| 情感强度 | {strength} | 市场情绪波动程度 |
"""
        
        # 板块情绪热力图
        if sector_avg:
            text += "\n### 📊 板块情绪热力图\n\n"
            sorted_sectors = sorted(sector_avg.items(), key=lambda x: x[1], reverse=True)
            for sector, score in sorted_sectors:
                if score > 0.3:
                    emoji = "🔥"
                elif score > 0:
                    emoji = "📈"
                elif score > -0.3:
                    emoji = "📉"
                else:
                    emoji = "❄️"
                text += f"- {emoji} **{sector}**: {score:+.2f}\n"
        
        # 热词
        if hot_positive:
            text += f"\n### 🟢 正面情绪热词：{', '.join([kw for kw, _ in hot_positive])}\n"
        if hot_negative:
            text += f"\n### 🔴 负面情绪热词：{', '.join([kw for kw, _ in hot_negative])}\n"
        
        return text
    
    def _prepare_cross_border_summary(self, cross_border_news: List[News]) -> str:
        """准备跨界新闻摘要文本"""
        if not cross_border_news:
            return ""
        
        # 按类型分组
        by_type = {}
        for news in cross_border_news:
            type_name = {
                NewsType.GEOPOLITICAL: "🌍 国际政治/地缘冲突",
                NewsType.TECH: "🔬 科技突破",
                NewsType.SOCIAL: "📢 社会舆论",
                NewsType.DISASTER: "🌪️ 自然灾害"
            }.get(news.news_type, "其他")
            
            if type_name not in by_type:
                by_type[type_name] = []
            by_type[type_name].append(news)
        
        summary_parts = []
        for type_name, news_items in by_type.items():
            summary_parts.append(f"\n### {type_name}")
            for i, news in enumerate(news_items[:3], 1):  # 每类最多3条
                impact_info = ""
                if news.beneficiary_sectors or news.affected_sectors:
                    impact_info = f"\n- 潜在影响：受益板块[{', '.join(news.beneficiary_sectors)}]，受损板块[{', '.join(news.affected_sectors)}]"
                summary_parts.append(f"""
{i}. **{news.title}**
- 来源：{news.source}
- 时间：{news.published_at.strftime('%H:%M')}
- 内容：{news.content[:150]}...{impact_info}
""")
        
        return "\n".join(summary_parts)
    
    def _parse_report_response(self, response: str, report_date: date, 
                               news_list: List[News]) -> Report:
        """解析 AI 响应，构建报告对象（旧版兼容）"""
        return self._parse_enhanced_report_response(response, report_date, news_list, [], ReportType.MORNING)
    
    def _parse_enhanced_report_response(
        self, response: str, report_date: date,
        news_list: List[News], cross_border_news: List[News],
        report_type: ReportType = ReportType.MORNING
    ) -> Report:
        """解析 AI 响应，构建5模块投资决策导向报告对象"""
        # 尝试提取 JSON 数据
        json_data = self._extract_json(response)
        
        # 提取报告正文（JSON 之前的部分）
        content = response
        if "```json" in response:
            content = response.split("```json")[0].strip()
        
        # 根据报告类型确定默认标题
        type_name = "早报" if report_type == ReportType.MORNING else "晚报"
        default_title = f"{report_date.strftime('%Y年%m月%d日')} 财经{type_name}"
        
        # 构建报告基础信息
        title = json_data.get("title", default_title)
        summary = json_data.get("summary", content[:200])
        core_opinions = json_data.get("core_opinions", [])
        
        # 构建 highlights
        highlights = []
        for h in json_data.get("highlights", [])[:5]:
            highlights.append(NewsHighlight(
                title=h.get("title", ""),
                source=h.get("source", ""),
                summary=h.get("summary", ""),
                sentiment=ReportSentiment(h.get("sentiment", "neutral")),
                related_stocks=h.get("related_stocks", []),
                historical_context=h.get("historical_context")
            ))
        
        # 如果没有解析出 highlights，从新闻列表生成
        if not highlights and news_list:
            for news in sorted(news_list, key=lambda x: x.importance_score, reverse=True)[:5]:
                highlights.append(NewsHighlight(
                    title=news.title,
                    source=news.source,
                    summary=news.content[:100],
                    sentiment=ReportSentiment(news.sentiment.value),
                    related_stocks=news.related_stocks
                ))
        
        # 构建跨界事件
        cross_border_events = []
        for cb in json_data.get("cross_border_events", []):
            category_str = cb.get("category", "tech")
            try:
                category = CrossBorderCategory(category_str)
            except:
                category = CrossBorderCategory.TECH
            
            cross_border_events.append(CrossBorderEvent(
                title=cb.get("title", ""),
                category=category,
                summary=cb.get("summary", ""),
                market_impact_direct=cb.get("market_impact_direct", ""),
                market_impact_indirect=cb.get("market_impact_indirect", ""),
                historical_reference=cb.get("historical_reference", ""),
                beneficiaries=cb.get("beneficiaries", []),
                losers=cb.get("losers", []),
                follow_up_advice=cb.get("follow_up_advice", "")
            ))
        
        # 构建市场分析
        analysis_data = json_data.get("market_analysis", {})
        analysis = MarketAnalysis(
            overall_sentiment=ReportSentiment(analysis_data.get("overall_sentiment", "neutral")),
            trend=MarketTrend(analysis_data.get("trend", "neutral")),
            key_factors=analysis_data.get("key_factors", []),
            opportunities=analysis_data.get("opportunities", []),
            risks=analysis_data.get("risks", []),
            indices=[]
        )
        
        # 计算统计信息
        word_count = len(content)
        reading_time = max(1, word_count // 400)
        
        return Report(
            id=str(uuid.uuid4()),
            title=title,
            summary=summary,
            report_type=report_type,
            core_opinions=core_opinions,
            content=content,
            report_date=report_date,
            sections=[],  # 可以后续从 content 中解析出各模块
            highlights=highlights,
            cross_border_events=cross_border_events,
            analysis=analysis,
            podcast_status="pending",
            word_count=word_count,
            reading_time=reading_time,
            news_count=len(news_list),
            cross_border_count=len(cross_border_news),
            created_at=datetime.now()
        )
    
    def _extract_json(self, text: str) -> Dict:
        """从文本中提取 JSON"""
        try:
            # 尝试找到 JSON 块
            if "```json" in text:
                start = text.index("```json") + 7
                end = text.index("```", start)
                json_str = text[start:end].strip()
                return json.loads(json_str)
            
            # 尝试直接解析
            return json.loads(text)
        except:
            return {}
    
    def _generate_mock_report(self) -> str:
        """生成模拟报告（用于测试或 API 不可用时）- 7模块结构"""
        from datetime import datetime
        import random
        
        today = date.today().strftime('%Y年%m月%d日')
        weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        weekday = weekday_names[date.today().weekday()]
        
        # 随机生成一些市场数据
        shanghai_change = round(random.uniform(-2, 2), 2)
        shenzhen_change = round(random.uniform(-2.5, 2.5), 2)
        chuangye_change = round(random.uniform(-3, 3), 2)
        hangseng_change = round(random.uniform(-2, 2), 2)
        
        shanghai_trend = "上涨" if shanghai_change > 0 else "下跌"
        market_sentiment = "积极" if shanghai_change > 0.5 else "谨慎" if shanghai_change > -0.5 else "观望"
        action = "买入" if shanghai_change > 0.5 else "持有" if shanghai_change > -0.5 else "减仓"
        
        # 随机选择热点板块
        hot_sectors = random.sample([
            "新能源汽车", "人工智能", "半导体", "医药生物", "消费电子",
            "光伏储能", "军工", "白酒", "银行", "地产", "基建"
        ], 3)
        
        # 随机选择风险点
        risk_points = random.sample([
            "外围市场波动加剧",
            "地缘政治不确定性上升",
            "部分板块估值偏高需警惕",
            "资金面边际收紧",
            "机构持仓调整频繁"
        ], 3)
        
        return f"""# {today} ({weekday}) 财经深度日报

## 🎯 核心观点

1. **央行维持流动性宽松，建议{action}金融板块**：央行近日开展逆回购操作，银行间利率维持低位，流动性充裕利好估值修复。

2. **{hot_sectors[0]}板块持续走强，龙头个股目标价上调15%**：政策催化+业绩兑现，板块估值仍有空间，建议逢低布局龙头。

3. **警惕{risk_points[0]}，控制仓位在6成以下**：当前市场情绪偏{market_sentiment}，建议保持灵活，等待更明确的方向信号。

---

## 📈 宏观政策解读

### 央行逆回购操作释放积极信号

**事件概述**：央行近日开展2000亿元7天期逆回购操作，利率维持1.8%不变。

**历史案例对比**：
- 2024年9月，央行同样在市场低迷时加大逆回购力度，随后一个月上证指数上涨12.3%
- 2023年6月类似操作后，银行板块一周内反弹8.7%

**数据佐证**：
- 当前DR007报1.75%，处于近6个月低位
- 北向资金本周净流入87亿元
- 银行板块PE仅5.2倍，处于历史10%分位

**投资逻辑链条**：
流动性宽松 → 无风险利率下行 → 高股息资产吸引力上升 → 银行、保险等金融板块受益

**操作建议**：建议{action}银行ETF（512800），目标涨幅10-15%

**风险提示**：若通胀数据超预期或美联储鹰派表态，可能导致政策转向

---

## 🔄 行业轮动分析

### {hot_sectors[0]}板块：强势领涨，仍有空间

**板块表现**：
- 上一交易日涨幅：+{round(random.uniform(2, 5), 2)}%
- 本周涨幅：+{round(random.uniform(5, 12), 2)}%
- 资金流向：主力净流入{random.randint(20, 80)}亿元

**驱动因素**：
1. 政策端：国家发改委发布产业支持政策
2. 业绩端：龙头公司Q3业绩预增30-50%
3. 资金端：北向资金连续5日加仓

**龙头标的**：
- 标的A（600xxx）：行业绝对龙头，市占率35%
- 标的B（300xxx）：技术领先，毛利率最高

**技术面分析**：
- 板块指数突破年线，MACD金叉
- 短期支撑位：xxxx点，阻力位：xxxx点

**操作建议**：建议买入，仓位控制在15%以内

---

## 💎 个股机会挖掘

### 推荐股票：XXX科技（688xxx）

**近期催化**：
- 下周发布Q3业绩预告，预计同比增长40-60%
- 新产品下月量产，打开第二增长曲线

**基本面数据**：
| 指标 | 数值 | 行业排名 |
|------|------|----------|
| PE(TTM) | 28倍 | 中位数 |
| PEG | 0.8 | 偏低 |
| ROE | 18% | 前20% |
| 毛利率 | 42% | 前10% |

**技术面判断**：
- 周线站上MA20，量能放大
- MACD底背离后金叉

**AI预判**：看多（置信度78%）

**目标价**：150元（当前价120元，空间25%）

**止损位**：108元（跌破即止损，幅度-10%）

---

## ⚡ 事件驱动机会

### 下周关注：美联储议息会议（3/18-19）

**时间节点**：北京时间3月20日凌晨2:00公布结果

**市场预期**：
- CME利率期货显示：维持利率不变概率88%
- 市场关注点：点阵图是否暗示年内降息次数

**不同情景应对**：

| 情景 | 概率 | 市场反应 | 操作建议 |
|------|------|----------|----------|
| 符合预期（维持） | 88% | 小幅反弹 | 持有，等待突破 |
| 鸽派表态 | 8% | 强势上涨 | 加仓科技股 |
| 鹰派意外 | 4% | 短期承压 | 减仓，等待企稳 |

**历史参考**：
- 去年6月议息后一周，纳指+3.2%，A股科技板块+5.1%
- 去年12月鸽派表态后，全球风险资产普涨

---

## 🌍 跨界热点扫描

### 热点一：中东局势紧张升级

**事件简述**：中东某地区冲突持续，国际油价应声上涨3%。

**市场关联分析**：
- **直接影响**：原油、天然气等能源股直接受益；航空、物流成本承压
- **间接影响**：避险情绪升温，黄金、国债受追捧；出口企业汇率风险上升

**历史参照**：
2022年俄乌冲突初期，中石油一个月涨幅25%，航空股普跌15%

**受益标的**：中石油（601857）、中海油（600938）、黄金ETF（518880）

**受损标的**：南方航空（600029）、中国国航（601111）

**持续跟踪建议**：关注每日原油价格和地区局势变化，若冲突持续超过2周，能源股可能有第二波行情

### 热点二：某知名品牌代言人翻车

**事件简述**：某流量明星因负面事件导致多个品牌连夜解约。

**市场关联分析**：
- **直接影响**：相关代言品牌股价承压，短期情绪冲击
- **间接影响**：消费者信心波动，品牌商可能增加营销费用

**历史参照**：
2021年类似事件后，相关消费品公司股价平均下跌8%，但一个月后基本收复失地

**受损标的**：暂不点名，建议回避近期有明星代言争议的消费股

**持续跟踪建议**：这类事件通常是短期情绪冲击，若基本面未受实质影响，反而可能是逢低买入机会

---

## ⚠️ 风险雷达

### 风险一：{risk_points[0]}
- **风险等级**：🟡 中等
- **影响范围**：全市场
- **应对建议**：控制整体仓位，分散配置

### 风险二：{risk_points[1]}
- **风险等级**：🟠 偏高
- **影响范围**：部分板块
- **应对建议**：回避相关板块，等待风险释放

### 风险三：{risk_points[2]}
- **风险等级**：🟡 中等
- **影响范围**：高估值成长股
- **应对建议**：关注业绩能否兑现，设好止损位

### 本周财报爆雷预警
- XX公司（300xxx）：业绩预告下修，警惕
- YY公司（600xxx）：商誉减值风险，规避

---

*免责声明：以上分析仅供参考，不构成投资建议。投资有风险，入市需谨慎。*

```json
{{
  "title": "{today} ({weekday}) 财经深度日报",
  "summary": "上一交易日A股市场{shanghai_trend}，上证指数{'+' if shanghai_change > 0 else ''}{shanghai_change}%。{hot_sectors[0]}板块表现活跃，央行维持流动性宽松。建议投资者保持{market_sentiment}态度，重点关注金融和{hot_sectors[0]}板块机会。",
  "core_opinions": [
    "央行维持流动性宽松，建议{action}金融板块",
    "{hot_sectors[0]}板块持续走强，龙头个股目标价上调15%",
    "警惕{risk_points[0]}，控制仓位在6成以下"
  ],
  "highlights": [
    {{
      "title": "央行公开市场操作维护流动性",
      "source": "央行官网",
      "summary": "央行近日开展2000亿元逆回购操作，利率维持1.8%不变，维护银行体系流动性合理充裕。",
      "sentiment": "positive",
      "related_stocks": ["601398", "601288", "512800"],
      "historical_context": "2024年9月类似操作后，上证一个月涨12.3%"
    }},
    {{
      "title": "{hot_sectors[0]}板块集体走强",
      "source": "市场观察",
      "summary": "{hot_sectors[0]}板块上一交易日领涨两市，多只个股涨停，主力资金持续流入。",
      "sentiment": "positive",
      "related_stocks": [],
      "historical_context": "政策催化+业绩兑现双重驱动"
    }}
  ],
  "cross_border_events": [
    {{
      "title": "中东局势紧张升级",
      "category": "geopolitical",
      "summary": "中东地区冲突持续，国际油价应声上涨3%",
      "market_impact_direct": "能源股直接受益，航空物流成本承压",
      "market_impact_indirect": "避险情绪升温，黄金国债受追捧",
      "historical_reference": "2022年俄乌冲突初期，中石油一月涨25%",
      "beneficiaries": ["中石油", "中海油", "黄金ETF"],
      "losers": ["航空股", "物流股"],
      "follow_up_advice": "关注油价和局势变化，冲突持续则能源股有第二波"
    }},
    {{
      "title": "知名品牌代言人翻车",
      "category": "social",
      "summary": "某流量明星负面事件导致多品牌连夜解约",
      "market_impact_direct": "相关代言品牌股价短期承压",
      "market_impact_indirect": "消费者信心波动，品牌营销费用可能增加",
      "historical_reference": "2021年类似事件后相关股票平均跌8%，一月后收复",
      "beneficiaries": [],
      "losers": ["相关代言品牌"],
      "follow_up_advice": "短期情绪冲击，基本面未变则是逢低买入机会"
    }}
  ],
  "stock_picks": [
    {{
      "code": "688xxx",
      "name": "XXX科技",
      "action": "买入",
      "target_price": 150.00,
      "stop_loss": 108.00,
      "confidence": 78,
      "reasoning": "Q3业绩预增40-60%，新产品下月量产，PE28倍PEG0.8偏低"
    }}
  ],
  "market_analysis": {{
    "overall_sentiment": "{'positive' if shanghai_change > 0.3 else 'negative' if shanghai_change < -0.3 else 'neutral'}",
    "trend": "{'bullish' if shanghai_change > 0.5 else 'bearish' if shanghai_change < -0.5 else 'neutral'}",
    "key_factors": ["央行流动性", "板块轮动", "地缘政治", "美联储议息"],
    "opportunities": ["{hot_sectors[0]}", "金融板块", "黄金避险"],
    "risks": ["{risk_points[0]}", "{risk_points[1]}", "{risk_points[2]}"]
  }}
}}
```"""


# 单例实例
_analyzer_instance: Optional[AIAnalyzerService] = None


def get_ai_analyzer(force_reinit: bool = False) -> AIAnalyzerService:
    """
    获取 AI 分析服务实例
    
    Args:
        force_reinit: 是否强制重新初始化（用于配置变更后）
    """
    global _analyzer_instance
    if _analyzer_instance is None or force_reinit:
        _analyzer_instance = AIAnalyzerService()
    return _analyzer_instance


def reset_ai_analyzer():
    """重置 AI 分析器实例（配置变更后调用）"""
    global _analyzer_instance
    _analyzer_instance = None

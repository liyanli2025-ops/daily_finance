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
    CrossBorderEvent, CrossBorderCategory
)
from ..models.stock import StockPrediction, PredictionType
from .market_data_service import get_market_data_service, MarketOverview
from .watchlist_service import get_watchlist_service


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
    
    async def generate_daily_report(self, news_list: List[News], cross_border_news: List[News] = None) -> Report:
        """
        生成每日财经深度报告（5模块 + 投资决策导向 + 自选股追踪 + 情感分析）
        
        优化版：
        - 5模块精简结构（操作建议/市场全景/自选股作战图/事件催化/风控仪表盘）
        - 投资决策导向：每段分析必须回答"所以我该怎么做"
        - 集成 AKShare 真实市场数据 + FinBERT 情感分析
        - 自选股给出明确信号+目标价+止损位
        
        Args:
            news_list: 财经新闻列表
            cross_border_news: 跨界新闻列表
            
        Returns:
            生成的报告对象
        """
        today = date.today()
        is_weekend = today.weekday() >= 5  # 判断是否是周末（周六=5，周日=6）
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
        
        # 【新增】获取真实市场数据（带容错：即使失败也能继续生成报告）
        print("[AI] 正在获取真实市场数据...")
        try:
            market_service = get_market_data_service()
            market_data: MarketOverview = await market_service.get_market_overview(today)
            market_data_text = market_data.to_prompt_text()
            print(f"[AI] 市场数据获取完成：{len(market_data.indices)} 个指数，{len(market_data.top_sectors)} 个热门板块")
        except Exception as e:
            print(f"[WARN] 市场数据获取失败，将使用空数据继续生成报告: {e}")
            market_data = MarketOverview(date=today.strftime("%Y-%m-%d"))
            market_data_text = "（市场数据暂不可用，请基于新闻信息进行分析）"
        
        # 【新增】计算市场情绪指数（基于 FinBERT 情感分析）
        sentiment_index_text = self._prepare_sentiment_index(news_list, cross_border_news or [])
        
        # 准备新闻摘要（增强版：包含情感标签）
        finance_summary = self._prepare_news_summary_with_sentiment(news_list)
        cross_border_summary = self._prepare_cross_border_summary(cross_border_news or [])
        
        # 周末特别说明
        weekend_notice = ""
        if is_weekend:
            weekend_notice = """
## ⚠️ 重要提示：今天是周末
- A股和港股今日休市，没有实时交易数据
- 本报告以【周回顾】和【下周展望】为主
- 市场数据为上一个交易日（周五）的数据
- 请注意区分"本周"和"下周"的表述

"""
        
        # 【大幅优化】5模块深度分析 prompt —— 投资决策导向 + 深度分析兼顾
        report_prompt = f"""你是{settings.user_nickname}的私人投资顾问，拥有20年A股和港股实战经验。
你的核心使命：**每一段分析都必须回答"所以我该怎么做"**。

你的风格：
- 直接给结论，再讲逻辑——先告诉我"买还是卖"，再解释为什么
- 敢于提出反共识观点——市场都看多时，你要指出盲点；市场恐慌时，你要找到机会
- 不说废话——禁止"值得关注""需要注意""密切跟踪"等模糊表述，必须说"建议买入/卖出/观望/加仓/减仓"
- 每个观点后必须有一句【操作建议】

## 🎯 今日任务

今天是{today.strftime('%Y年%m月%d日')} {weekday_name}。
⚠️ 本报告在开盘前生成，市场数据来自上一个交易日（{last_trading_str}）的收盘数据，请用"上一个交易日"描述。
{weekend_notice}

### 用户画像
- 昵称：{settings.user_nickname}
- 投资风格：{investment_style_desc}

{watchlist_text}

---

## 📊 真实市场数据（基于 AKShare，请基于这些数据分析，不要编造）

{market_data_text}

---

{sentiment_index_text}

---

## 📰 {'本周' if is_weekend else '最新'}财经新闻（含情感标签）

{finance_summary}

## 🌍 {'本周' if is_weekend else '最新'}跨界热点

{cross_border_summary if cross_border_summary else "暂无重大跨界热点"}

---

## 📝 报告结构（5大模块，每个模块必须以【操作建议】结尾）

### 模块1：🎯 {'本周复盘与下周操作指南' if is_weekend else '今日三条操作建议'}

**这是全文最重要的部分，开门见山。**

给出3条**可执行的操作建议**（不是判断、不是观察）：
- 格式：**建议X（置信度：高/中/低）**：做什么 + 为什么 + 风险是什么
- 每条建议必须包含：具体的操作动作（买入/卖出/加仓/减仓/观望）+ 具体标的或板块 + 理由 + 止损条件
- 参考市场情绪指数判断当前阶段

示例（注意是建议做什么，不是描述发生了什么）：
> **建议一（置信度：高）**：{'下周一' if is_weekend else '今天'}逢低加仓半导体ETF（如512480），目标仓位从2成提到3成。理由：上一个交易日费城半导体指数大涨3.2%，情绪指数+0.45偏多，A股半导体板块有望跟涨。止损位：如果3日内板块跌超3%则减回2成。

### 模块2：📈 {'本周市场全景复盘' if is_weekend else '市场全景：大盘+板块+资金'}

**合并大盘和行业分析，重点是"这些信息对操作意味着什么"**

1. **大盘研判**：指数涨跌+成交量+情绪指数→ **结论：{'下周' if is_weekend else '明天'}大盘偏多还是偏空？给出具体点位区间**
2. **资金暗语**：北向资金+主力资金流向→ **结论：聪明钱在往哪个方向押注？**
3. **板块轮动**：
   - 领涨板块为什么涨？是真逻辑还是短期炒作？→ **建议：哪些板块现在可以上车，哪些已经迟了**
   - 领跌板块是机会还是陷阱？→ **建议：哪些板块可以抄底，哪些继续回避**
4. **反共识观点**：市场一致预期是什么？你看到了什么被忽略的信号？

每段分析后都要跟一句 **【操作含义】：所以你应该...**

### 模块3：⭐ {'自选股本周表现与下周策略' if is_weekend else '自选股作战图'}

**这是用户最关心的部分，给出最明确的信号。**

{self._get_watchlist_analysis_prompt()}

对每只自选股，必须给出：
- **信号**：明确的买入/持有/减仓/清仓/观望（不要含糊）
- **目标价**：短期（1-2周）目标价位
- **止损位**：跌破多少必须走
- **仓位建议**：建议占总仓位的百分比
- **一句话理由**：为什么给这个信号

格式参考：
> **贵州茅台（600519）—— 持有** | 目标价：1850 | 止损位：1720 | 建议仓位：15%
> 理由：上一个交易日缩量企稳，北向资金净买入2.3亿，短期调整充分，持股待涨。

### 模块4：⚡ {'下周事件日历与埋伏策略' if is_weekend else '事件催化：未来一周怎么埋伏'}

**不只是列事件，更要给出"提前布局"的策略**

按时间顺序列出未来一周的重要事件（经济数据、政策会议、财报发布等），每个事件给出：
1. 事件内容和时间
2. **乐观情景**：如果结果好于预期 → 哪些标的受益 → 建议提前买入多少仓位
3. **悲观情景**：如果结果差于预期 → 哪些标的受损 → 建议提前做什么防护
4. **操作策略**：具体怎么埋伏

### 模块5：🛡️ 风控仪表盘：仓位与雷区

**帮用户守住利润、控制回撤**

1. **总仓位建议**：当前应该几成仓？结合情绪指数和市场阶段给出明确数字
2. **仓位分配**：大盘蓝筹 vs 中小成长 vs 现金 的建议比例
3. **雷区预警**：
   - 近期要回避的板块和个股（减持、解禁、财报爆雷预警）
   - 需要设置止损的持仓
4. **系统性风险评估**：当前最大的潜在风险是什么？发生概率多大？如何对冲？

---

## ✍️ 写作风格

1. **结论先行**：每段先给操作建议，再讲逻辑
2. **数据说话**：每个观点引用具体数字，不要空谈
3. **情绪为锚**：充分利用市场情绪指数
4. **通俗直白**：像给朋友打电话聊投资一样说话
5. **禁止模糊**：不说"值得关注""需要注意""后续观察"，必须给明确动作

## ⛔ 禁止

- 不要有模板化开头（报告日期/分析师/致用户xxx等）
- 不要重复描述人尽皆知的信息（如"美联储加息影响全球市场"这种废话）
- 不要只描述现象不给建议

## 📤 结构化输出

在报告末尾，用 ```json 包裹输出以下数据：

```json
{{
  "title": "{'周末复盘版' if is_weekend else '结合当前市场特征'}的标题（要有观点，如'反弹确认，加仓科技'而非'市场分析报告'）",
  "summary": "200字精华摘要（核心操作建议+关键数据）",
  "core_opinions": [
    "操作建议1（含具体动作+理由+止损）",
    "操作建议2",
    "操作建议3"
  ],
  "market_score": 65,
  "position_advice": "6成",
  "highlights": [
    {{
      "title": "重要新闻标题",
      "source": "来源",
      "summary": "100字摘要",
      "sentiment": "positive/negative/neutral",
      "sentiment_confidence": 0.85,
      "related_stocks": ["相关股票代码"],
      "historical_context": "历史参考"
    }}
  ],
  "watchlist_analysis": [
    {{
      "code": "股票代码",
      "name": "股票名称",
      "signal": "买入/持有/减仓/观望",
      "reason": "具体理由",
      "key_price": "关键价位"
    }}
  ],
  "market_analysis": {{
    "overall_sentiment": "positive/negative/neutral",
    "sentiment_score": 0.35,
    "trend": "bullish/bearish/neutral",
    "key_factors": ["影响因素1", "影响因素2"],
    "opportunities": ["机会板块1", "机会板块2"],
    "risks": ["风险点1", "风险点2"],
    "support_level": "支撑位",
    "resistance_level": "阻力位"
  }},
  "hot_sectors": ["热门板块1", "板块2", "板块3"],
  "risk_sectors": ["风险板块1", "风险板块2"],
  "next_week_focus": ["下周关注点1", "关注点2"]
}}
```

请开始撰写报告："""

        response = await self._call_ai(report_prompt, max_tokens=8000)
        
        # 解析响应
        report = self._parse_enhanced_report_response(response, today, news_list, cross_border_news or [])
        
        return report
    
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
        return self._parse_enhanced_report_response(response, report_date, news_list, [])
    
    def _parse_enhanced_report_response(self, response: str, report_date: date,
                                        news_list: List[News], cross_border_news: List[News]) -> Report:
        """解析 AI 响应，构建5模块投资决策导向报告对象"""
        # 尝试提取 JSON 数据
        json_data = self._extract_json(response)
        
        # 提取报告正文（JSON 之前的部分）
        content = response
        if "```json" in response:
            content = response.split("```json")[0].strip()
        
        # 构建报告基础信息
        title = json_data.get("title", f"{report_date.strftime('%Y年%m月%d日')} 财经深度日报")
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

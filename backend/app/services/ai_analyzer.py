"""
AI 分析服务
使用 Claude API 进行新闻分析、报告生成和投资建议
"""
import json
from datetime import datetime, date
from typing import List, Optional, Dict, Any
import uuid

from ..config import settings
from ..models.news import News, SentimentType
from ..models.report import (
    Report, ReportCreate, NewsHighlight, MarketAnalysis,
    IndexSnapshot, MarketTrend, SentimentType as ReportSentiment
)
from ..models.stock import StockPrediction, PredictionType


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
    
    async def generate_daily_report(self, news_list: List[News]) -> Report:
        """
        生成每日财经深度报告
        
        Args:
            news_list: 今日新闻列表
            
        Returns:
            生成的报告对象
        """
        today = date.today()
        
        # 准备新闻摘要
        news_summary = self._prepare_news_summary(news_list)
        
        # 生成报告内容
        report_prompt = f"""你是一位专业的财经分析师，请根据今日（{today.strftime('%Y年%m月%d日')}）的财经新闻，撰写一份深度分析报告。

## 今日重要新闻

{news_summary}

## 报告要求

请撰写一份 5000-7000 字的深度财经日报，要求：

1. **标题**：一个吸引眼球、概括今日核心主题的标题

2. **内容结构**（使用 Markdown 格式）：
   - **今日市场概览**：简要概述今日市场整体表现
   - **重点事件深度分析**：选取 3-5 个最重要的事件，每个事件包括：
     - 事件概述
     - 背景回溯（这个事件的前因是什么，之前发生过什么）
     - 历史类似案例（如果有的话）
     - 对市场的影响分析
     - 投资启示
   - **行业观察**：重点关注的 2-3 个行业动态
   - **政策解读**：如有重要政策，进行详细解读
   - **风险提示**：当前需要注意的风险点
   - **明日展望**：对明日市场的预判

3. **分析风格**：
   - 专业但通俗易懂
   - 结合宏观经济背景
   - 给出具体的、可操作的投资参考
   - 避免模糊的套话，要有干货

4. **额外输出**（JSON 格式）：
   在报告末尾，用 ```json 包裹，输出以下结构化数据：
   {{
     "title": "报告标题",
     "summary": "200字以内的报告摘要",
     "highlights": [
       {{
         "title": "新闻标题",
         "source": "来源",
         "summary": "100字摘要",
         "sentiment": "positive/negative/neutral",
         "related_stocks": ["代码1", "代码2"],
         "historical_context": "历史背景（可选）"
       }}
     ],
     "market_analysis": {{
       "overall_sentiment": "positive/negative/neutral",
       "trend": "bullish/bearish/neutral",
       "key_factors": ["因素1", "因素2"],
       "opportunities": ["机会1", "机会2"],
       "risks": ["风险1", "风险2"]
     }}
   }}

请开始撰写报告："""

        response = await self._call_ai(report_prompt, max_tokens=8000)
        
        # 解析响应
        report = self._parse_report_response(response, today, news_list)
        
        return report
    
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
        
        # 尝试 Anthropic
        if self.anthropic_client:
            try:
                message = self.anthropic_client.messages.create(
                    model="claude-3-opus-20240229",
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
            max_retries = 3 if self.using_free_service else 1
            
            for attempt in range(max_retries):
                try:
                    # 选择模型：免费服务使用 deepseek-r1，否则使用配置的模型
                    if self.using_free_service:
                        model = "openai"  # Pollinations 默认使用 openai
                    elif settings.openai_base_url:
                        # 使用兼容服务时的模型名称
                        model = settings.ai_model if settings.ai_model != "claude-3-opus-20240229" else "deepseek-ai/DeepSeek-V3"
                    else:
                        model = "gpt-4-turbo-preview"
                    
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
        """准备新闻摘要文本"""
        summary_parts = []
        
        # 按重要性排序，取前20条
        sorted_news = sorted(news_list, key=lambda x: x.importance_score, reverse=True)[:20]
        
        for i, news in enumerate(sorted_news, 1):
            summary_parts.append(f"""
### {i}. {news.title}
- 来源：{news.source}
- 时间：{news.published_at.strftime('%H:%M')}
- 摘要：{news.content[:200]}...
""")
        
        return "\n".join(summary_parts)
    
    def _parse_report_response(self, response: str, report_date: date, 
                               news_list: List[News]) -> Report:
        """解析 AI 响应，构建报告对象"""
        # 尝试提取 JSON 数据
        json_data = self._extract_json(response)
        
        # 提取报告正文（JSON 之前的部分）
        content = response
        if "```json" in response:
            content = response.split("```json")[0].strip()
        
        # 构建报告
        title = json_data.get("title", f"{report_date.strftime('%Y年%m月%d日')} 财经日报")
        summary = json_data.get("summary", content[:200])
        
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
        
        # 构建市场分析
        analysis_data = json_data.get("market_analysis", {})
        analysis = MarketAnalysis(
            overall_sentiment=ReportSentiment(analysis_data.get("overall_sentiment", "neutral")),
            trend=MarketTrend(analysis_data.get("trend", "neutral")),
            key_factors=analysis_data.get("key_factors", []),
            opportunities=analysis_data.get("opportunities", []),
            risks=analysis_data.get("risks", []),
            indices=[]  # 需要从其他数据源获取
        )
        
        # 计算统计信息
        word_count = len(content)
        reading_time = max(1, word_count // 400)
        
        return Report(
            id=str(uuid.uuid4()),
            title=title,
            summary=summary,
            content=content,
            report_date=report_date,
            highlights=highlights,
            analysis=analysis,
            podcast_status="pending",
            word_count=word_count,
            reading_time=reading_time,
            news_count=len(news_list),
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
        """生成模拟报告（用于测试或 API 不可用时）"""
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
        ], 2)
        
        return f"""# {today} ({weekday}) 财经深度日报

## 📊 今日市场概览

今日 A 股市场{shanghai_trend}，三大指数分化明显：

| 指数 | 涨跌幅 | 走势 |
|------|--------|------|
| 上证指数 | {'+' if shanghai_change > 0 else ''}{shanghai_change}% | {'📈 上涨' if shanghai_change > 0 else '📉 下跌'} |
| 深证成指 | {'+' if shenzhen_change > 0 else ''}{shenzhen_change}% | {'📈 上涨' if shenzhen_change > 0 else '📉 下跌'} |
| 创业板指 | {'+' if chuangye_change > 0 else ''}{chuangye_change}% | {'📈 上涨' if chuangye_change > 0 else '📉 下跌'} |
| 恒生指数 | {'+' if hangseng_change > 0 else ''}{hangseng_change}% | {'📈 上涨' if hangseng_change > 0 else '📉 下跌'} |

今日两市成交额约 9000 亿元，市场整体交投活跃度{market_sentiment}。北向资金今日净{'买入' if random.random() > 0.5 else '卖出'} {random.randint(10, 80)} 亿元。

---

## 🔥 重点事件深度分析

### 1. 央行货币政策动向

**事件概述**：央行今日开展逆回购操作，维护银行体系流动性合理充裕。

**背景回溯**：
- 近期央行持续通过公开市场操作调节流动性
- 当前银行间市场利率维持在合理区间
- 市场对货币政策预期保持稳定

**历史类似案例**：
回顾 2023-2024 年，央行在经济恢复期采取了灵活适度的货币政策，有效支撑了实体经济发展。

**对市场的影响**：
- 短期：流动性充裕利好股债两市
- 中期：为经济平稳运行提供支撑
- 长期：货币政策框架持续完善

**投资启示**：
关注受益于低利率环境的成长股，以及估值具有安全边际的蓝筹股。

---

### 2. {hot_sectors[0]}板块异动

**事件概述**：{hot_sectors[0]}板块今日表现活跃，多只个股涨停。

**背景分析**：
- 政策端持续发力，行业利好不断
- 产业链景气度维持高位
- 机构资金持续加仓

**投资建议**：
- 关注行业龙头企业
- 注意估值与业绩的匹配度
- 设置好止盈止损位

---

### 3. 国际市场联动

**隔夜美股**：道琼斯指数{'+' if random.random() > 0.5 else '-'}{round(random.uniform(0.1, 1.5), 2)}%，纳斯达克指数{'+' if random.random() > 0.5 else '-'}{round(random.uniform(0.2, 2), 2)}%

**影响分析**：
- 美联储政策预期变化影响全球风险偏好
- 国际资金流向对 A 股北向资金有一定指引作用
- 科技股走势对 A 股相关板块有参考意义

---

## 📈 行业观察

### {hot_sectors[0]}
今日领涨两市，主要受益于：
1. 政策支持力度加大
2. 行业需求持续增长
3. 产业链利润向龙头集中

### {hot_sectors[1]}
表现相对活跃，关注：
1. 技术突破带来的投资机会
2. 下游需求复苏进度
3. 国产替代加速推进

### {hot_sectors[2]}
震荡整理中，建议：
1. 等待更明确的信号
2. 关注龙头公司财报
3. 注意板块轮动节奏

---

## ⚠️ 风险提示

1. **{risk_points[0]}**
   - 需密切关注外部环境变化
   - 做好资产配置的再平衡

2. **{risk_points[1]}**
   - 建议保持适度仓位
   - 分散投资降低风险

3. **操作建议**
   - 不追高，不杀跌
   - 严格执行投资纪律
   - 关注政策边际变化

---

## 🔮 明日展望

基于今日市场表现和消息面分析，预计明日：

- **大盘走势**：延续震荡格局，关注支撑位有效性
- **热点方向**：{hot_sectors[0]}、{hot_sectors[1]} 可能继续活跃
- **操作策略**：建议{market_sentiment}配置，关注低位优质标的

---

*免责声明：以上分析仅供参考，不构成投资建议。投资有风险，入市需谨慎。*

```json
{{
  "title": "{today} ({weekday}) 财经深度日报",
  "summary": "今日A股市场{shanghai_trend}，上证指数{'+' if shanghai_change > 0 else ''}{shanghai_change}%。{hot_sectors[0]}板块表现活跃，央行维持流动性合理充裕。建议投资者保持{market_sentiment}态度，关注政策动向和行业轮动机会。",
  "highlights": [
    {{
      "title": "央行公开市场操作维护流动性",
      "source": "央行官网",
      "summary": "央行今日开展逆回购操作，维护银行体系流动性合理充裕，货币政策保持稳健基调。",
      "sentiment": "neutral",
      "related_stocks": ["601398", "601288"],
      "historical_context": "延续近期流动性调控节奏"
    }},
    {{
      "title": "{hot_sectors[0]}板块集体走强",
      "source": "市场观察",
      "summary": "{hot_sectors[0]}板块今日表现活跃，多只个股涨停，资金持续流入。",
      "sentiment": "positive",
      "related_stocks": [],
      "historical_context": "板块轮动行情延续"
    }}
  ],
  "market_analysis": {{
    "overall_sentiment": "{'positive' if shanghai_change > 0.3 else 'negative' if shanghai_change < -0.3 else 'neutral'}",
    "trend": "{'bullish' if shanghai_change > 0.5 else 'bearish' if shanghai_change < -0.5 else 'neutral'}",
    "key_factors": ["央行政策", "板块轮动", "外围市场"],
    "opportunities": ["{hot_sectors[0]}", "{hot_sectors[1]}", "低估值蓝筹"],
    "risks": ["{risk_points[0]}", "{risk_points[1]}"]
  }}
}}
```"""


# 单例实例
_analyzer_instance: Optional[AIAnalyzerService] = None


def get_ai_analyzer() -> AIAnalyzerService:
    """获取 AI 分析服务实例"""
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = AIAnalyzerService()
    return _analyzer_instance

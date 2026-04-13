"""
FinBERT 深度情感分析服务

使用预训练的金融领域 BERT 模型进行新闻情感分析
- ProsusAI/finbert: 英文金融情感分析
- 中文金融情感分析: 使用规则 + 简单模型

功能：
1. 单条新闻情感分析（正面/负面/中性）
2. 情感置信度评分（0-1）
3. 情感强度评分（弱/中/强）
4. 批量新闻分析
5. 每日市场情绪指数计算
"""
import asyncio
import re
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import hashlib

from ..models.news import News, SentimentType, NewsType


class SentimentStrength(str, Enum):
    """情感强度"""
    WEAK = "weak"        # 弱：轻微影响
    MODERATE = "moderate"  # 中：明显影响
    STRONG = "strong"    # 强：重大影响


@dataclass
class SentimentResult:
    """情感分析结果"""
    sentiment: SentimentType  # 情感类型：正面/负面/中性
    confidence: float         # 置信度：0-1
    strength: SentimentStrength  # 情感强度
    scores: Dict[str, float] = field(default_factory=dict)  # 各类别得分
    keywords_positive: List[str] = field(default_factory=list)  # 触发正面情感的关键词
    keywords_negative: List[str] = field(default_factory=list)  # 触发负面情感的关键词
    analysis_method: str = "rule"  # 分析方法：rule/finbert/chinese_bert
    
    def to_dict(self) -> Dict:
        return {
            "sentiment": self.sentiment.value,
            "confidence": self.confidence,
            "strength": self.strength.value,
            "scores": self.scores,
            "keywords_positive": self.keywords_positive,
            "keywords_negative": self.keywords_negative,
            "analysis_method": self.analysis_method
        }


@dataclass
class MarketSentimentIndex:
    """市场情绪指数"""
    date: datetime
    overall_score: float      # 整体情绪分数 -1 到 1
    bullish_ratio: float      # 看多比例
    bearish_ratio: float      # 看空比例
    neutral_ratio: float      # 中性比例
    sentiment_strength: SentimentStrength  # 整体情感强度
    news_count: int           # 分析的新闻数量
    sector_sentiment: Dict[str, float] = field(default_factory=dict)  # 板块情绪
    hot_positive_topics: List[str] = field(default_factory=list)  # 热门正面话题
    hot_negative_topics: List[str] = field(default_factory=list)  # 热门负面话题
    
    def to_prompt_text(self) -> str:
        """转换为 AI 分析的提示文本"""
        sentiment_desc = "偏多" if self.overall_score > 0.1 else "偏空" if self.overall_score < -0.1 else "中性"
        strength_desc = {
            SentimentStrength.WEAK: "情绪较弱",
            SentimentStrength.MODERATE: "情绪适中",
            SentimentStrength.STRONG: "情绪强烈"
        }[self.sentiment_strength]
        
        text = f"""
### 📊 市场情绪指数（基于 {self.news_count} 条新闻的深度情感分析）

| 指标 | 数值 | 解读 |
|------|------|------|
| 整体情绪 | {self.overall_score:+.2f} | {sentiment_desc} |
| 看多新闻占比 | {self.bullish_ratio*100:.1f}% | - |
| 看空新闻占比 | {self.bearish_ratio*100:.1f}% | - |
| 中性新闻占比 | {self.neutral_ratio*100:.1f}% | - |
| 情感强度 | {self.sentiment_strength.value} | {strength_desc} |
"""
        
        if self.sector_sentiment:
            text += "\n**板块情绪热力图**：\n"
            sorted_sectors = sorted(self.sector_sentiment.items(), key=lambda x: x[1], reverse=True)
            for sector, score in sorted_sectors[:5]:
                emoji = "🔥" if score > 0.3 else "📈" if score > 0 else "📉" if score > -0.3 else "❄️"
                text += f"- {emoji} {sector}: {score:+.2f}\n"
        
        if self.hot_positive_topics:
            text += f"\n**正面热词**：{', '.join(self.hot_positive_topics[:5])}\n"
        
        if self.hot_negative_topics:
            text += f"\n**负面热词**：{', '.join(self.hot_negative_topics[:5])}\n"
        
        return text


class SentimentAnalyzerService:
    """
    情感分析服务
    
    分析流程：
    1. 首先尝试使用 FinBERT（如果已安装 transformers）
    2. 如果 FinBERT 不可用，使用增强版规则引擎
    3. 中文新闻使用专门的中文情感词典
    """
    
    def __init__(self):
        self.finbert_model = None
        self.finbert_tokenizer = None
        self.chinese_model = None
        self.use_finbert = False
        self.use_chinese_bert = False
        
        # 情感分析缓存（避免重复分析）
        self._cache: Dict[str, SentimentResult] = {}
        self._cache_max_size = 10000
        
        # 初始化模型
        self._init_models()
        
        # 加载情感词典
        self._load_sentiment_lexicons()
    
    def _init_models(self):
        """初始化情感分析模型"""
        # FinBERT 是英文模型，对中文财经新闻无实际价值
        # 且服务器无法访问 HuggingFace，每次启动会因重试超时浪费 20-60 秒
        # 直接使用中文规则引擎，效果更好且无网络依赖
        print("[SentimentAnalyzer] 使用中文金融规则引擎进行情感分析（已禁用 FinBERT）")
    
    def _load_sentiment_lexicons(self):
        """加载情感词典"""
        
        # ============ 正面词汇（金融领域）============
        self.positive_words = {
            # 强正面（权重 2.0）
            "strong": [
                "暴涨", "涨停", "大涨", "飙升", "井喷", "狂飙", "爆发",
                "突破", "新高", "创历史新高", "强势", "大幅上涨",
                "重大利好", "超预期", "业绩暴增", "翻倍", "历史最好",
                "里程碑", "重大突破", "颠覆性", "划时代"
            ],
            # 中等正面（权重 1.0）
            "moderate": [
                "上涨", "走高", "反弹", "回升", "企稳", "站稳",
                "利好", "增长", "盈利", "增持", "加仓", "买入",
                "看多", "乐观", "积极", "改善", "提升", "扩大",
                "受益", "机会", "突破", "创新", "领先", "龙头",
                "景气", "复苏", "回暖", "向好", "超额收益"
            ],
            # 弱正面（权重 0.5）
            "weak": [
                "稳健", "平稳", "持平", "维持", "守住", "企稳",
                "小幅上涨", "微涨", "略涨", "温和增长"
            ]
        }
        
        # ============ 负面词汇（金融领域）============
        self.negative_words = {
            # 强负面（权重 2.0）
            "strong": [
                "暴跌", "跌停", "大跌", "崩盘", "闪崩", "腰斩",
                "血崩", "踩踏", "暴雷", "爆仓", "重大利空",
                "业绩暴雷", "财务造假", "退市", "ST", "*ST",
                "强制平仓", "清盘", "破产", "倒闭", "违约"
            ],
            # 中等负面（权重 1.0）
            "moderate": [
                "下跌", "走低", "回调", "回落", "承压", "疲软",
                "利空", "下滑", "亏损", "减持", "抛售", "卖出",
                "看空", "悲观", "担忧", "警惕", "风险", "压力",
                "收缩", "萎缩", "恶化", "下修", "不及预期",
                "减仓", "清仓", "撤退", "离场", "见顶"
            ],
            # 弱负面（权重 0.5）
            "weak": [
                "震荡", "波动", "分化", "观望", "谨慎",
                "小幅下跌", "微跌", "略跌", "温和下滑"
            ]
        }
        
        # ============ 板块关键词映射 ============
        self.sector_keywords = {
            "科技": ["科技", "芯片", "半导体", "AI", "人工智能", "软件", "互联网", "云计算", "大数据"],
            "金融": ["银行", "保险", "券商", "金融", "信托", "基金"],
            "新能源": ["新能源", "光伏", "锂电", "储能", "风电", "氢能", "电动车"],
            "消费": ["消费", "白酒", "食品", "零售", "餐饮", "旅游", "酒店"],
            "医药": ["医药", "医疗", "生物", "制药", "疫苗", "创新药"],
            "地产": ["地产", "房地产", "房企", "楼市", "物业"],
            "军工": ["军工", "国防", "航空", "航天", "导弹"],
            "基建": ["基建", "建筑", "铁路", "公路", "水利"],
        }
        
        # ============ 否定词 ============
        self.negation_words = [
            "不", "没", "无", "未", "非", "否", "难以", "不再",
            "并非", "而非", "不是", "没有", "不会", "不能"
        ]
        
        # ============ 程度副词 ============
        self.intensifiers = {
            "强": ["极", "非常", "特别", "十分", "极其", "异常", "格外", "高度"],
            "中": ["很", "较", "比较", "相当", "颇"],
            "弱": ["略", "稍", "有点", "有些", "轻微"]
        }
    
    async def analyze_news(self, news: News) -> SentimentResult:
        """
        分析单条新闻的情感
        
        Args:
            news: 新闻对象
            
        Returns:
            情感分析结果
        """
        # 检查缓存
        cache_key = self._get_cache_key(news)
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # 合并标题和内容进行分析（标题权重更高）
        text = f"{news.title} {news.title} {news.content[:500]}"  # 标题出现两次增加权重
        
        # 判断语言（简单判断是否为中文）
        is_chinese = self._is_chinese_text(text)
        
        if self.use_finbert and not is_chinese:
            # 使用 FinBERT 分析英文
            result = await self._analyze_with_finbert(text)
        else:
            # 使用规则引擎分析（中文或 FinBERT 不可用时）
            result = self._analyze_with_rules(text, is_chinese)
        
        # 根据新闻类型调整权重
        result = self._adjust_by_news_type(result, news.news_type)
        
        # 缓存结果
        self._add_to_cache(cache_key, result)
        
        return result
    
    async def analyze_batch(self, news_list: List[News]) -> List[Tuple[News, SentimentResult]]:
        """
        批量分析新闻情感
        
        Args:
            news_list: 新闻列表
            
        Returns:
            [(新闻, 情感结果), ...]
        """
        results = []
        
        # 并行分析（但控制并发数）
        semaphore = asyncio.Semaphore(10)  # 最多10个并发
        
        async def analyze_one(news: News):
            async with semaphore:
                result = await self.analyze_news(news)
                return (news, result)
        
        tasks = [analyze_one(news) for news in news_list]
        results = await asyncio.gather(*tasks)
        
        return results
    
    def calculate_market_sentiment_index(
        self, 
        analyzed_news: List[Tuple[News, SentimentResult]]
    ) -> MarketSentimentIndex:
        """
        计算市场情绪指数
        
        Args:
            analyzed_news: [(新闻, 情感结果), ...]
            
        Returns:
            市场情绪指数
        """
        if not analyzed_news:
            return MarketSentimentIndex(
                date=datetime.now(),
                overall_score=0.0,
                bullish_ratio=0.0,
                bearish_ratio=0.0,
                neutral_ratio=1.0,
                sentiment_strength=SentimentStrength.WEAK,
                news_count=0
            )
        
        # 统计各类情绪
        positive_count = 0
        negative_count = 0
        neutral_count = 0
        total_score = 0.0
        
        # 板块情绪统计
        sector_scores: Dict[str, List[float]] = {}
        
        # 热词统计
        positive_topics: Dict[str, int] = {}
        negative_topics: Dict[str, int] = {}
        
        for news, result in analyzed_news:
            # 计算加权得分
            weight = news.importance_score  # 使用重要性作为权重
            
            if result.sentiment == SentimentType.POSITIVE:
                positive_count += 1
                score = result.confidence * weight
                total_score += score
            elif result.sentiment == SentimentType.NEGATIVE:
                negative_count += 1
                score = -result.confidence * weight
                total_score += score
            else:
                neutral_count += 1
            
            # 统计板块情绪
            for sector, keywords in self.sector_keywords.items():
                if any(kw in news.title or kw in news.content for kw in keywords):
                    if sector not in sector_scores:
                        sector_scores[sector] = []
                    
                    if result.sentiment == SentimentType.POSITIVE:
                        sector_scores[sector].append(result.confidence)
                    elif result.sentiment == SentimentType.NEGATIVE:
                        sector_scores[sector].append(-result.confidence)
                    else:
                        sector_scores[sector].append(0)
            
            # 统计热词
            for kw in result.keywords_positive:
                positive_topics[kw] = positive_topics.get(kw, 0) + 1
            for kw in result.keywords_negative:
                negative_topics[kw] = negative_topics.get(kw, 0) + 1
        
        total_count = len(analyzed_news)
        
        # 计算各项指标
        bullish_ratio = positive_count / total_count
        bearish_ratio = negative_count / total_count
        neutral_ratio = neutral_count / total_count
        
        # 归一化整体得分到 -1 ~ 1
        overall_score = total_score / total_count if total_count > 0 else 0
        overall_score = max(-1.0, min(1.0, overall_score))
        
        # 计算板块平均情绪
        sector_sentiment = {
            sector: sum(scores) / len(scores) if scores else 0
            for sector, scores in sector_scores.items()
        }
        
        # 判断整体情感强度
        if abs(overall_score) > 0.5 or bullish_ratio > 0.6 or bearish_ratio > 0.6:
            strength = SentimentStrength.STRONG
        elif abs(overall_score) > 0.2 or bullish_ratio > 0.4 or bearish_ratio > 0.4:
            strength = SentimentStrength.MODERATE
        else:
            strength = SentimentStrength.WEAK
        
        # 排序热词
        hot_positive = sorted(positive_topics.items(), key=lambda x: x[1], reverse=True)
        hot_negative = sorted(negative_topics.items(), key=lambda x: x[1], reverse=True)
        
        return MarketSentimentIndex(
            date=datetime.now(),
            overall_score=overall_score,
            bullish_ratio=bullish_ratio,
            bearish_ratio=bearish_ratio,
            neutral_ratio=neutral_ratio,
            sentiment_strength=strength,
            news_count=total_count,
            sector_sentiment=sector_sentiment,
            hot_positive_topics=[kw for kw, _ in hot_positive[:10]],
            hot_negative_topics=[kw for kw, _ in hot_negative[:10]]
        )
    
    async def _analyze_with_finbert(self, text: str) -> SentimentResult:
        """使用 FinBERT 分析"""
        import torch
        
        # 截断文本（BERT 最大 512 tokens）
        text = text[:500]
        
        # Tokenize
        inputs = self.finbert_tokenizer(
            text, 
            return_tensors="pt", 
            truncation=True, 
            max_length=512,
            padding=True
        )
        
        # 推理
        with torch.no_grad():
            outputs = self.finbert_model(**inputs)
            probs = torch.softmax(outputs.logits, dim=1).squeeze()
        
        # FinBERT 输出顺序: positive, negative, neutral
        scores = {
            "positive": probs[0].item(),
            "negative": probs[1].item(),
            "neutral": probs[2].item()
        }
        
        # 确定情感类型
        max_label = max(scores, key=scores.get)
        sentiment = {
            "positive": SentimentType.POSITIVE,
            "negative": SentimentType.NEGATIVE,
            "neutral": SentimentType.NEUTRAL
        }[max_label]
        
        confidence = scores[max_label]
        
        # 判断强度
        if confidence > 0.8:
            strength = SentimentStrength.STRONG
        elif confidence > 0.6:
            strength = SentimentStrength.MODERATE
        else:
            strength = SentimentStrength.WEAK
        
        return SentimentResult(
            sentiment=sentiment,
            confidence=confidence,
            strength=strength,
            scores=scores,
            analysis_method="finbert"
        )
    
    def _analyze_with_rules(self, text: str, is_chinese: bool = True) -> SentimentResult:
        """使用规则引擎分析（增强版）"""
        
        positive_score = 0.0
        negative_score = 0.0
        keywords_pos = []
        keywords_neg = []
        
        # 分词（简单按标点和空格分割）
        pattern = r'[，。！？、；：""''（）' + r'\s]+'
        words = re.split(pattern, text)
        
        # 检测否定词位置
        negation_positions = set()
        for i, word in enumerate(words):
            if any(neg in word for neg in self.negation_words):
                negation_positions.add(i)
                negation_positions.add(i + 1)  # 否定词后一个词
                negation_positions.add(i + 2)  # 否定词后两个词
        
        # 遍历文本匹配情感词
        for level, word_list in self.positive_words.items():
            weight = {"strong": 2.0, "moderate": 1.0, "weak": 0.5}[level]
            for word in word_list:
                if word in text:
                    # 检查是否被否定
                    word_idx = None
                    for i, w in enumerate(words):
                        if word in w:
                            word_idx = i
                            break
                    
                    if word_idx in negation_positions:
                        # 被否定，转为负面
                        negative_score += weight * 0.8
                        keywords_neg.append(f"不{word}")
                    else:
                        positive_score += weight
                        keywords_pos.append(word)
        
        for level, word_list in self.negative_words.items():
            weight = {"strong": 2.0, "moderate": 1.0, "weak": 0.5}[level]
            for word in word_list:
                if word in text:
                    # 检查是否被否定
                    word_idx = None
                    for i, w in enumerate(words):
                        if word in w:
                            word_idx = i
                            break
                    
                    if word_idx in negation_positions:
                        # 被否定，转为正面（如"不担忧"）
                        positive_score += weight * 0.5
                        keywords_pos.append(f"不{word}")
                    else:
                        negative_score += weight
                        keywords_neg.append(word)
        
        # 计算最终得分
        total = positive_score + negative_score
        if total == 0:
            # 没有匹配到任何情感词
            return SentimentResult(
                sentiment=SentimentType.NEUTRAL,
                confidence=0.5,
                strength=SentimentStrength.WEAK,
                scores={"positive": 0.33, "negative": 0.33, "neutral": 0.34},
                keywords_positive=keywords_pos[:5],
                keywords_negative=keywords_neg[:5],
                analysis_method="rule"
            )
        
        # 归一化得分
        pos_ratio = positive_score / total
        neg_ratio = negative_score / total
        
        # 计算净情感得分 (-1 到 1)
        net_score = pos_ratio - neg_ratio
        
        # 确定情感类型
        if net_score > 0.2:
            sentiment = SentimentType.POSITIVE
            confidence = min(0.95, 0.5 + pos_ratio * 0.5)
        elif net_score < -0.2:
            sentiment = SentimentType.NEGATIVE
            confidence = min(0.95, 0.5 + neg_ratio * 0.5)
        else:
            sentiment = SentimentType.NEUTRAL
            confidence = 0.5 + abs(net_score) * 0.3
        
        # 判断强度
        if total > 5:
            strength = SentimentStrength.STRONG
        elif total > 2:
            strength = SentimentStrength.MODERATE
        else:
            strength = SentimentStrength.WEAK
        
        return SentimentResult(
            sentiment=sentiment,
            confidence=confidence,
            strength=strength,
            scores={
                "positive": pos_ratio,
                "negative": neg_ratio,
                "neutral": 1 - max(pos_ratio, neg_ratio)
            },
            keywords_positive=keywords_pos[:5],
            keywords_negative=keywords_neg[:5],
            analysis_method="rule"
        )
    
    def _adjust_by_news_type(self, result: SentimentResult, news_type: NewsType) -> SentimentResult:
        """根据新闻类型调整情感分析结果"""
        
        # 跨界新闻的情感判断需要更谨慎
        if news_type != NewsType.FINANCE:
            # 降低置信度，因为非财经新闻对市场的影响更间接
            result.confidence *= 0.8
        
        # 灾害类新闻通常是负面的
        if news_type == NewsType.DISASTER and result.sentiment == SentimentType.NEUTRAL:
            result.sentiment = SentimentType.NEGATIVE
            result.confidence = max(0.6, result.confidence)
        
        return result
    
    def _is_chinese_text(self, text: str) -> bool:
        """判断文本是否主要为中文"""
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        total_chars = len(text)
        return chinese_chars / total_chars > 0.3 if total_chars > 0 else False
    
    def _get_cache_key(self, news: News) -> str:
        """生成缓存键"""
        content = f"{news.title}:{news.content[:200]}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def _add_to_cache(self, key: str, result: SentimentResult):
        """添加到缓存"""
        if len(self._cache) >= self._cache_max_size:
            # 简单清理：删除一半
            keys_to_remove = list(self._cache.keys())[:self._cache_max_size // 2]
            for k in keys_to_remove:
                del self._cache[k]
        
        self._cache[key] = result


# 单例实例
_sentiment_analyzer: Optional[SentimentAnalyzerService] = None


def get_sentiment_analyzer() -> SentimentAnalyzerService:
    """获取情感分析服务实例"""
    global _sentiment_analyzer
    if _sentiment_analyzer is None:
        _sentiment_analyzer = SentimentAnalyzerService()
    return _sentiment_analyzer

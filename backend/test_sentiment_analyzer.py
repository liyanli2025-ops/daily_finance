"""
测试 FinBERT 深度情感分析服务
"""
import asyncio
import sys
import io

# 修复 Windows 控制台编码问题
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 添加项目路径
sys.path.insert(0, '.')

from datetime import datetime

from app.models.news import News, SentimentType, NewsType
from app.services.sentiment_analyzer import (
    get_sentiment_analyzer, 
    SentimentResult,
    MarketSentimentIndex
)


def create_test_news(title: str, content: str, news_type: NewsType = NewsType.FINANCE) -> News:
    """创建测试新闻"""
    import uuid
    return News(
        id=str(uuid.uuid4()),
        title=title,
        content=content,
        source="测试来源",
        source_url="https://example.com",
        published_at=datetime.now(),
        news_type=news_type,
        importance_score=0.7
    )


async def test_single_news_analysis():
    """测试单条新闻分析"""
    print("\n" + "="*60)
    print("📊 测试单条新闻情感分析")
    print("="*60)
    
    analyzer = get_sentiment_analyzer()
    
    # 测试用例
    test_cases = [
        # 明显正面
        ("央行宣布降准0.5%，释放流动性超万亿", 
         "中国人民银行决定于2024年3月1日下调存款准备金率0.5个百分点，释放长期资金约1万亿元，支持实体经济发展。市场普遍预期此举将利好股市。",
         "预期: 正面 (POSITIVE)"),
        
        # 明显负面
        ("某上市公司业绩暴雷，净利润大幅下滑80%",
         "XX科技发布业绩预告，预计2023年净利润同比下降80%，主要原因是市场竞争加剧、订单减少。公司股价盘后大跌。",
         "预期: 负面 (NEGATIVE)"),
        
        # 中性
        ("沪深两市今日成交额破万亿",
         "今日A股三大指数小幅震荡，沪指微涨0.1%，深成指跌0.05%，创业板指涨0.2%。两市成交额达1.05万亿元，北向资金小幅净流出5亿元。",
         "预期: 中性 (NEUTRAL)"),
        
        # 强正面
        ("重磅！国产芯片实现重大突破，打破国外垄断",
         "中芯国际宣布成功量产7nm芯片，良品率达到国际领先水平，这标志着我国在高端芯片领域取得重大突破，相关产业链将迎来爆发式增长机遇。",
         "预期: 强正面"),
        
        # 强负面
        ("突发！某百亿私募暴雷，投资者血本无归",
         "知名私募XX资本疑似爆雷，旗下多只产品清盘，投资者本金损失殆尽。据悉该私募管理规模超百亿，此次事件或将引发连锁反应。监管部门已介入调查。",
         "预期: 强负面"),
        
        # 否定词测试
        ("专家称短期不必担忧股市大幅波动",
         "著名经济学家表示，当前宏观经济基本面稳健，短期内不必担忧股市大幅下跌。建议投资者保持理性，不要恐慌性抛售。",
         "预期: 正面 (否定词翻转)"),
    ]
    
    for title, content, expected in test_cases:
        news = create_test_news(title, content)
        result = await analyzer.analyze_news(news)
        
        print(f"\n📰 标题: {title[:40]}...")
        print(f"   情感: {result.sentiment.value} | 置信度: {result.confidence:.2%} | 强度: {result.strength.value}")
        print(f"   正面词: {result.keywords_positive[:3]}")
        print(f"   负面词: {result.keywords_negative[:3]}")
        print(f"   分析方法: {result.analysis_method}")
        print(f"   {expected}")


async def test_batch_analysis():
    """测试批量分析"""
    print("\n" + "="*60)
    print("📊 测试批量新闻情感分析")
    print("="*60)
    
    analyzer = get_sentiment_analyzer()
    
    # 创建一批模拟新闻
    news_list = [
        create_test_news("央行降准利好银行股", "央行宣布降准，银行板块有望受益。"),
        create_test_news("科技股集体暴跌", "今日科技股大幅下挫，多只股票跌停。"),
        create_test_news("新能源车销量创新高", "比亚迪月销量突破30万辆，创历史新高。"),
        create_test_news("房地产调控政策放松", "多地出台房地产刺激政策，市场情绪回暖。"),
        create_test_news("医药板块承压明显", "集采政策冲击，医药股普遍下跌。"),
        create_test_news("沪指震荡收平", "今日大盘窄幅震荡，成交量有所萎缩。"),
        create_test_news("军工板块异动拉升", "地缘局势紧张，军工股集体走强。"),
        create_test_news("白酒股遭遇抛售", "消费降级担忧，白酒龙头股跌幅居前。"),
    ]
    
    # 批量分析
    results = await analyzer.analyze_batch(news_list)
    
    print(f"\n共分析 {len(results)} 条新闻：\n")
    
    for news, result in results:
        emoji = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}[result.sentiment.value]
        print(f"{emoji} {news.title} → {result.sentiment.value} ({result.confidence:.0%})")


async def test_market_sentiment_index():
    """测试市场情绪指数计算"""
    print("\n" + "="*60)
    print("📊 测试市场情绪指数计算")
    print("="*60)
    
    analyzer = get_sentiment_analyzer()
    
    # 模拟一天的新闻（偏多行情）
    bullish_news = [
        create_test_news("沪指大涨3%创年内新高", "A股全线上涨，沪指突破3500点。"),
        create_test_news("北向资金狂买200亿", "外资持续流入，看好中国资产。"),
        create_test_news("科技股领涨两市", "AI概念股集体涨停。"),
        create_test_news("央行释放流动性", "降准利好市场信心。"),
        create_test_news("新能源订单超预期", "产业链景气度持续向好。"),
    ]
    
    bearish_news = [
        create_test_news("部分高位股回调", "获利盘抛压明显。"),
        create_test_news("地产股继续走弱", "销售数据不及预期。"),
    ]
    
    neutral_news = [
        create_test_news("两市成交额1.2万亿", "市场交投活跃。"),
        create_test_news("期指小幅升水", "套利空间有限。"),
    ]
    
    all_news = bullish_news + bearish_news + neutral_news
    
    # 批量分析
    analyzed = await analyzer.analyze_batch(all_news)
    
    # 计算情绪指数
    index = analyzer.calculate_market_sentiment_index(analyzed)
    
    print(f"\n📈 市场情绪指数报告")
    print(f"=" * 40)
    print(f"整体情绪得分: {index.overall_score:+.2f}")
    print(f"看多比例: {index.bullish_ratio:.1%}")
    print(f"看空比例: {index.bearish_ratio:.1%}")
    print(f"中性比例: {index.neutral_ratio:.1%}")
    print(f"情感强度: {index.sentiment_strength.value}")
    print(f"分析新闻数: {index.news_count}")
    
    if index.sector_sentiment:
        print(f"\n📊 板块情绪:")
        for sector, score in sorted(index.sector_sentiment.items(), key=lambda x: x[1], reverse=True):
            emoji = "🔥" if score > 0.3 else "📈" if score > 0 else "📉" if score > -0.3 else "❄️"
            print(f"   {emoji} {sector}: {score:+.2f}")
    
    if index.hot_positive_topics:
        print(f"\n🟢 正面热词: {', '.join(index.hot_positive_topics)}")
    if index.hot_negative_topics:
        print(f"🔴 负面热词: {', '.join(index.hot_negative_topics)}")
    
    print(f"\n📝 AI 提示文本预览:")
    print("-" * 40)
    print(index.to_prompt_text())


async def main():
    """主测试函数"""
    print("\n🚀 FinBERT 深度情感分析服务测试")
    print("=" * 60)
    
    # 检查分析器初始化
    analyzer = get_sentiment_analyzer()
    print(f"✅ 情感分析服务已初始化")
    print(f"   - FinBERT 模型: {'已加载' if analyzer.use_finbert else '未加载（使用规则引擎）'}")
    
    # 运行测试
    await test_single_news_analysis()
    await test_batch_analysis()
    await test_market_sentiment_index()
    
    print("\n" + "="*60)
    print("✅ 所有测试完成！")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())

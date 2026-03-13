"""完整测试报告生成流程"""
import asyncio
import sys
sys.stdout.reconfigure(encoding='utf-8')

async def main():
    print("=" * 60)
    print("完整测试报告生成流程")
    print("=" * 60)
    
    from datetime import datetime
    print(f"当前时间: {datetime.now()}")
    
    # 1. 测试配置
    print("\n[1] 检查配置...")
    from app.config import settings
    print(f"   API Key: {settings.openai_api_key[:20]}..." if settings.openai_api_key else "   API Key: 未设置")
    print(f"   Base URL: {settings.openai_base_url}")
    print(f"   Model: {settings.ai_model}")
    
    # 2. 测试 AI 分析器
    print("\n[2] 测试 AI 分析器...")
    from app.services.ai_analyzer import get_ai_analyzer
    analyzer = get_ai_analyzer()
    print(f"   Anthropic 客户端: {'已初始化' if analyzer.anthropic_client else '未初始化'}")
    print(f"   OpenAI 客户端: {'已初始化' if analyzer.openai_client else '未初始化'}")
    print(f"   使用免费服务: {analyzer.using_free_service}")
    
    # 3. 测试简单 AI 调用
    print("\n[3] 测试简单 AI 调用...")
    try:
        result = await analyzer._call_ai("用一句话描述今天的A股市场。", max_tokens=100)
        print(f"   ✅ AI 响应: {result[:100]}...")
    except Exception as e:
        print(f"   ❌ AI 调用失败: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # 4. 测试完整报告生成
    print("\n[4] 测试完整报告生成...")
    print("   （这可能需要 1-2 分钟）")
    
    # 创建模拟新闻
    from app.models.news import News, SentimentType, NewsType
    import uuid
    
    mock_news = [
        News(
            id=str(uuid.uuid4()),
            title="A股市场今日震荡上涨，科技板块领涨",
            content="A股今日三大指数集体上涨。科技板块表现强势，半导体、消费电子等个股涨幅居前。",
            summary="A股上涨，科技领涨",
            source="测试新闻",
            source_url="",
            published_at=datetime.now(),
            sentiment=SentimentType.POSITIVE,
            importance_score=0.8,
            keywords=["A股", "科技"],
            related_stocks=[],
            news_type=NewsType.FINANCE,
            created_at=datetime.now()
        )
    ]
    
    try:
        report = await analyzer.generate_daily_report(mock_news, [])
        print(f"   ✅ 报告生成成功!")
        print(f"   标题: {report.title}")
        print(f"   字数: {report.word_count}")
        print(f"   内容预览: {report.content[:300]}...")
    except Exception as e:
        print(f"   ❌ 报告生成失败: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("测试完成!")

if __name__ == "__main__":
    asyncio.run(main())

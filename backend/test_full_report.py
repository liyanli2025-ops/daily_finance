"""测试完整报告生成流程"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import asyncio
from datetime import datetime

async def test_report_generation():
    print("=" * 60)
    print("测试完整报告生成流程")
    print("=" * 60)
    
    # Step 1: 测试配置
    print("\n[Step 1] 检查配置...")
    from app.config import settings
    print(f"   API Key: {settings.openai_api_key[:20]}..." if settings.openai_api_key else "   API Key: None")
    print(f"   Base URL: {settings.openai_base_url}")
    print(f"   Model: {settings.ai_model}")
    
    # Step 2: 测试 AI 客户端
    print("\n[Step 2] 初始化 AI 客户端...")
    from app.services.ai_analyzer import AIAnalyzerService
    analyzer = AIAnalyzerService()
    print(f"   OpenAI 客户端: {'已初始化' if analyzer.openai_client else '未初始化'}")
    print(f"   使用免费服务: {analyzer.using_free_service}")
    
    # Step 3: 直接测试 AI 调用
    print("\n[Step 3] 测试 AI 调用...")
    try:
        test_prompt = "请用一句话概括今天A股的走势（随便编一个，这是测试）"
        result = await analyzer._call_ai(test_prompt, max_tokens=100)
        print(f"   ✅ AI 调用成功！")
        print(f"   返回内容: {result[:100]}...")
        
        # 检查是否是模拟报告
        if "央行维持流动性宽松" in result or "mock" in result.lower():
            print(f"   ⚠️ 注意：返回的是模拟数据，AI 调用可能失败了")
        
    except Exception as e:
        print(f"   ❌ AI 调用失败: {e}")
        import traceback
        traceback.print_exc()
    
    # Step 4: 测试完整报告生成
    print("\n[Step 4] 测试完整报告生成...")
    from app.models.news import News, SentimentType, NewsType
    import uuid
    
    # 创建测试新闻
    test_news = [
        News(
            id=str(uuid.uuid4()),
            title="测试新闻：A股今日大涨，创业板领涨两市",
            content="今日A股市场表现强劲，上证指数上涨2.5%，创业板指数涨幅超过4%。新能源、半导体等热门板块获得资金追捧。",
            summary="A股大涨",
            source="测试来源",
            source_url="",
            published_at=datetime.now(),
            sentiment=SentimentType.POSITIVE,
            importance_score=0.9,
            keywords=["A股", "创业板", "新能源"],
            related_stocks=["000001"],
            news_type=NewsType.FINANCE,
            created_at=datetime.now()
        )
    ]
    
    try:
        report = await analyzer.generate_daily_report(test_news, [])
        print(f"   报告标题: {report.title}")
        print(f"   报告字数: {report.word_count}")
        print(f"   内容预览: {report.content[:200]}...")
        
        # 检查是否是模拟报告
        if "央行维持流动性宽松，建议" in report.content and "金融板块" in report.content:
            print(f"\n   ⚠️ 检测到模拟报告！AI 调用可能在某处失败了")
        else:
            print(f"\n   ✅ 报告内容看起来是 AI 生成的！")
            
    except Exception as e:
        print(f"   ❌ 报告生成失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_report_generation())

"""快速测试 AI 分析器"""
import asyncio
import sys
sys.stdout.reconfigure(encoding='utf-8')

async def main():
    print("=" * 60)
    print("快速测试 AI 分析器")
    print("=" * 60)
    
    # 强制重新初始化
    from app.services.ai_analyzer import get_ai_analyzer
    analyzer = get_ai_analyzer(force_reinit=True)
    
    print(f"Anthropic: {'✅' if analyzer.anthropic_client else '❌'}")
    print(f"OpenAI: {'✅' if analyzer.openai_client else '❌'}")
    print(f"免费服务: {'是' if analyzer.using_free_service else '否'}")
    
    # 测试简单调用
    print("\n测试 AI 调用...")
    try:
        result = await analyzer._call_ai("用一句话描述今天的天气。", max_tokens=50)
        print(f"响应: {result}")
        print("✅ AI 调用成功！")
    except Exception as e:
        print(f"❌ AI 调用失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())

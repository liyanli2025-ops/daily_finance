"""测试配置是否正确加载"""
from app.config import settings

print("=" * 50)
print("当前 AI 配置：")
print("=" * 50)
print(f"Anthropic Key: {settings.anthropic_api_key[:20] + '...' if settings.anthropic_api_key else 'None'}")
print(f"OpenAI Key: {settings.openai_api_key[:20] + '...' if settings.openai_api_key else 'None'}")
print(f"OpenAI Base URL: {settings.openai_base_url}")
print(f"AI Model: {settings.ai_model}")
print("=" * 50)

# 测试 AI 客户端初始化
print("\n测试 AI 客户端初始化...")
from app.services.ai_analyzer import AIAnalyzerService
service = AIAnalyzerService()
print(f"Anthropic 客户端: {'已初始化' if service.anthropic_client else '未初始化'}")
print(f"OpenAI 客户端: {'已初始化' if service.openai_client else '未初始化'}")
print(f"使用免费服务: {service.using_free_service}")

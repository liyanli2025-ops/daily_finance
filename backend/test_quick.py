"""快速测试"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

print("测试 DeepSeek API...")

from openai import OpenAI
from app.config import settings

print(f"API Key: {settings.openai_api_key[:20]}...")
print(f"Base URL: {settings.openai_base_url}")
print(f"Model: {settings.ai_model}")

client = OpenAI(
    api_key=settings.openai_api_key,
    base_url=settings.openai_base_url
)

print("\n调用 API...")
response = client.chat.completions.create(
    model=settings.ai_model,
    messages=[{"role": "user", "content": "你好"}],
    max_tokens=50
)

print(f"响应: {response.choices[0].message.content}")
print("✅ 测试成功!")

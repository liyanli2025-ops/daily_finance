"""直接测试 DeepSeek API"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from openai import OpenAI

# DeepSeek 配置
client = OpenAI(
    api_key="sk-57df261b73574f46b1610eb7dfd087c6",
    base_url="https://api.deepseek.com"
)

print("正在测试 DeepSeek API...")
print("=" * 50)

try:
    response = client.chat.completions.create(
        model="deepseek-chat",
        max_tokens=100,
        messages=[
            {"role": "user", "content": "你好，请用一句话介绍一下今天A股市场的情况（随便编一个就行，这是测试）"}
        ]
    )
    print("✅ DeepSeek API 调用成功！")
    print("=" * 50)
    print("API 返回内容：")
    print(response.choices[0].message.content)
except Exception as e:
    print(f"❌ DeepSeek API 调用失败：{e}")
    print("=" * 50)
    print("可能原因：")
    print("1. API Key 无效或已过期")
    print("2. 网络连接问题")
    print("3. 账户余额不足")

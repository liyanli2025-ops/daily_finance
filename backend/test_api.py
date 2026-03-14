"""测试 API 是否工作"""
import requests
import sys
sys.stdout.reconfigure(encoding='utf-8')

print("=" * 50)
print("测试 API")
print("=" * 50)

# 1. 测试健康检查
print("\n1. 测试健康检查 /health...")
try:
    res = requests.get("http://localhost:9090/health", timeout=5)
    print(f"   状态: {res.status_code}")
    print(f"   响应: {res.json()}")
except Exception as e:
    print(f"   ❌ 失败: {e}")

# 2. 测试触发报告
print("\n2. 测试触发报告 /api/trigger-report...")
try:
    res = requests.post("http://localhost:9090/api/trigger-report", timeout=5)
    print(f"   状态: {res.status_code}")
    print(f"   响应: {res.json()}")
except Exception as e:
    print(f"   ❌ 失败: {e}")

# 3. 测试获取今日报告
print("\n3. 测试获取今日报告 /api/reports/today...")
try:
    res = requests.get("http://localhost:9090/api/reports/today", timeout=5)
    print(f"   状态: {res.status_code}")
    data = res.json()
    if 'title' in data:
        print(f"   标题: {data.get('title', '无')}")
        print(f"   内容长度: {len(data.get('content', ''))}")
    else:
        print(f"   响应: {data}")
except Exception as e:
    print(f"   ❌ 失败: {e}")

print("\n" + "=" * 50)

"""等待报告生成并检查"""
import time
import sqlite3
import sys
sys.stdout.reconfigure(encoding='utf-8')

print("等待 90 秒让报告生成...")
print("（DeepSeek 生成完整报告需要一些时间）")

for i in range(18):  # 90秒，每5秒更新一次
    time.sleep(5)
    print(f"   已等待 {(i+1)*5} 秒...")

print("\n检查最新报告...")

conn = sqlite3.connect('data/database.db')
cursor = conn.cursor()

cursor.execute('''
    SELECT id, title, content, created_at 
    FROM reports 
    ORDER BY created_at DESC 
    LIMIT 1
''')

row = cursor.fetchone()
if row:
    print("=" * 60)
    print(f"最新报告：")
    print(f"ID: {row[0][:20]}...")
    print(f"创建时间: {row[3]}")
    print("-" * 60)
    content = row[2] or ""
    # 检查是否是模拟报告
    if "XXX科技" in content or "688xxx" in content or "600xxx" in content:
        print("⚠️  这是模拟报告！AI 可能调用失败")
    else:
        print("✅ 这是真实 AI 生成的报告！")
    print("-" * 60)
    print("内容预览（前 800 字）：")
    print(content[:800])
else:
    print("没有找到报告")

conn.close()

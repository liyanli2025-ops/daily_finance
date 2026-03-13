"""检查最新报告内容"""
import sqlite3
import sys
sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('data/database.db')
cursor = conn.cursor()

# 获取最新报告
cursor.execute('''
    SELECT id, title, content, created_at 
    FROM reports 
    ORDER BY created_at DESC 
    LIMIT 1
''')

row = cursor.fetchone()
if row:
    print("=" * 60)
    print("最新报告信息：")
    print("=" * 60)
    print(f"ID: {row[0]}")
    print(f"标题: {row[1]}")
    print(f"创建时间: {row[3]}")
    print("-" * 60)
    print("内容（前 1500 字符）：")
    print("-" * 60)
    content = row[2] or ""
    print(content[:1500])
    print("\n...")
else:
    print("没有找到报告")

conn.close()

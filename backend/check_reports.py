"""查看数据库中的报告"""
import sqlite3
from datetime import datetime
import sys
sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('data/database.db')
cursor = conn.cursor()

print("=" * 60)
print("数据库中的报告列表（最新3条）：")
print("=" * 60)

cursor.execute('''
    SELECT id, title, report_date, created_at, substr(content, 1, 150) as preview
    FROM reports 
    ORDER BY created_at DESC 
    LIMIT 3
''')

rows = cursor.fetchall()
for i, row in enumerate(rows, 1):
    print(f"\n【报告 {i}】")
    print(f"  ID: {row[0][:8]}...")
    print(f"  标题: {row[1]}")
    print(f"  日期: {row[2]}")
    print(f"  创建时间: {row[3]}")
    print(f"  内容预览: {row[4][:100]}...")

conn.close()

"""查看数据库中所有报告"""
import sqlite3
from datetime import datetime
import sys
sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('data/database.db')
cursor = conn.cursor()

# 获取所有报告
cursor.execute('''
    SELECT id, title, created_at 
    FROM reports 
    ORDER BY created_at DESC
    LIMIT 10
''')

rows = cursor.fetchall()

print("=" * 60)
print(f"数据库中的所有报告（共 {len(rows)} 条最新）：")
print("=" * 60)

for i, row in enumerate(rows, 1):
    report_id = row[0][:8] + "..."
    title = row[1][:40] if row[1] else "无标题"
    created = row[2]
    print(f"{i}. [{created}] {title}")

conn.close()

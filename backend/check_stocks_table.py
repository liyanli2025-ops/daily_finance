import sqlite3

conn = sqlite3.connect('data/database.db')
cursor = conn.cursor()

# 检查表结构
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
print("所有表:", cursor.fetchall())

# 检查 stocks 表
try:
    cursor.execute('SELECT * FROM stocks')
    rows = cursor.fetchall()
    print(f'\n自选股数量: {len(rows)}')
    for row in rows:
        print(row)
except Exception as e:
    print(f"错误: {e}")

conn.close()

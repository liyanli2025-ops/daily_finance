import sqlite3

conn = sqlite3.connect('backend/data/database.db')
c = conn.cursor()

# 查询报告数量
c.execute('SELECT COUNT(*) FROM reports')
print('Total reports:', c.fetchone()[0])

# 查询最近的报告
c.execute('SELECT id, title, report_date, podcast_status FROM reports ORDER BY created_at DESC LIMIT 5')
print('\nRecent reports:')
for r in c.fetchall():
    print(r)

conn.close()

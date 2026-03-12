import sqlite3

conn = sqlite3.connect('data/database.db')
cursor = conn.execute('SELECT id, title, summary, content, report_date, podcast_status, podcast_url FROM reports')
for row in cursor.fetchall():
    print("ID:", row[0])
    print("Title:", row[1])
    print("Summary:", row[2][:100] if row[2] else "None")
    print("Content length:", len(row[3]) if row[3] else 0)
    print("Date:", row[4])
    print("Podcast Status:", row[5])
    print("Podcast URL:", row[6])
    print("-" * 50)
conn.close()

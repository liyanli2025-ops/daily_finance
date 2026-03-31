"""
数据迁移脚本：从旧数据库恢复数据到新数据库
使用方法：在服务器上执行
    cd /var/www/finance-daily/backend
    python migrate_data.py
"""
import sqlite3
import os
from datetime import datetime

# 数据库路径
OLD_DB = "data/database.db.bak"
NEW_DB = "data/database.db"


def migrate_data():
    """迁移数据"""
    
    # 检查文件存在
    if not os.path.exists(OLD_DB):
        print(f"❌ 旧数据库不存在: {OLD_DB}")
        return
    
    if not os.path.exists(NEW_DB):
        print(f"❌ 新数据库不存在: {NEW_DB}")
        return
    
    print(f"📂 旧数据库: {OLD_DB}")
    print(f"📂 新数据库: {NEW_DB}")
    
    # 连接数据库
    old_conn = sqlite3.connect(OLD_DB)
    new_conn = sqlite3.connect(NEW_DB)
    
    old_conn.row_factory = sqlite3.Row
    new_conn.row_factory = sqlite3.Row
    
    old_cursor = old_conn.cursor()
    new_cursor = new_conn.cursor()
    
    try:
        # 1. 迁移报告数据 (reports)
        print("\n📋 正在迁移报告数据...")
        migrate_reports(old_cursor, new_cursor)
        
        # 2. 迁移自选股数据 (stocks)
        print("\n📈 正在迁移自选股数据...")
        migrate_stocks(old_cursor, new_cursor)
        
        # 3. 迁移新闻数据 (news)
        print("\n📰 正在迁移新闻数据...")
        migrate_news(old_cursor, new_cursor)
        
        # 4. 迁移股票预测数据 (stock_predictions)
        print("\n🔮 正在迁移股票预测数据...")
        migrate_predictions(old_cursor, new_cursor)
        
        # 5. 迁移事件数据 (events)
        print("\n📅 正在迁移事件数据...")
        migrate_events(old_cursor, new_cursor)
        
        new_conn.commit()
        print("\n✅ 数据迁移完成！")
        
    except Exception as e:
        print(f"\n❌ 迁移失败: {e}")
        new_conn.rollback()
        raise
    finally:
        old_conn.close()
        new_conn.close()


def migrate_reports(old_cursor, new_cursor):
    """迁移报告数据"""
    # 获取旧数据库的列名
    old_cursor.execute("PRAGMA table_info(reports)")
    old_columns = [col[1] for col in old_cursor.fetchall()]
    print(f"  旧表列: {old_columns}")
    
    # 获取新数据库的列名
    new_cursor.execute("PRAGMA table_info(reports)")
    new_columns = [col[1] for col in new_cursor.fetchall()]
    print(f"  新表列: {new_columns}")
    
    # 查询旧数据
    old_cursor.execute("SELECT * FROM reports ORDER BY created_at")
    old_rows = old_cursor.fetchall()
    print(f"  找到 {len(old_rows)} 条旧报告")
    
    # 检查新数据库已有数据
    new_cursor.execute("SELECT COUNT(*) FROM reports")
    existing_count = new_cursor.fetchone()[0]
    print(f"  新数据库已有 {existing_count} 条报告")
    
    migrated = 0
    skipped = 0
    
    for row in old_rows:
        row_dict = dict(row)
        report_id = row_dict['id']
        
        # 检查是否已存在
        new_cursor.execute("SELECT id FROM reports WHERE id = ?", (report_id,))
        if new_cursor.fetchone():
            skipped += 1
            continue
        
        # 构建插入数据，添加 report_type 默认值
        if 'report_type' not in row_dict or not row_dict.get('report_type'):
            row_dict['report_type'] = 'morning'  # 旧数据默认为早报
        
        # 获取共同列（排除新数据库特有的列）
        common_columns = [col for col in old_columns if col in new_columns]
        
        # 如果 report_type 不在旧列中，手动添加
        if 'report_type' not in common_columns:
            common_columns.append('report_type')
        
        # 构建 INSERT 语句
        placeholders = ', '.join(['?' for _ in common_columns])
        columns_str = ', '.join(common_columns)
        
        values = []
        for col in common_columns:
            if col == 'report_type' and col not in old_columns:
                values.append('morning')
            else:
                values.append(row_dict.get(col))
        
        try:
            new_cursor.execute(
                f"INSERT INTO reports ({columns_str}) VALUES ({placeholders})",
                values
            )
            migrated += 1
        except Exception as e:
            print(f"  ⚠️ 跳过报告 {report_id}: {e}")
    
    print(f"  ✅ 迁移 {migrated} 条，跳过 {skipped} 条（已存在）")


def migrate_stocks(old_cursor, new_cursor):
    """迁移自选股数据"""
    try:
        old_cursor.execute("SELECT * FROM stocks")
        old_rows = old_cursor.fetchall()
        print(f"  找到 {len(old_rows)} 只自选股")
    except:
        print("  ⚠️ 旧数据库没有 stocks 表")
        return
    
    migrated = 0
    skipped = 0
    
    for row in old_rows:
        row_dict = dict(row)
        stock_id = row_dict['id']
        stock_code = row_dict.get('code', '')
        
        # 检查是否已存在（通过 ID 或 code）
        new_cursor.execute(
            "SELECT id FROM stocks WHERE id = ? OR code = ?", 
            (stock_id, stock_code)
        )
        if new_cursor.fetchone():
            skipped += 1
            continue
        
        # 获取列
        columns = list(row_dict.keys())
        placeholders = ', '.join(['?' for _ in columns])
        columns_str = ', '.join(columns)
        values = list(row_dict.values())
        
        try:
            new_cursor.execute(
                f"INSERT INTO stocks ({columns_str}) VALUES ({placeholders})",
                values
            )
            migrated += 1
        except Exception as e:
            print(f"  ⚠️ 跳过股票 {stock_code}: {e}")
    
    print(f"  ✅ 迁移 {migrated} 只，跳过 {skipped} 只（已存在）")


def migrate_news(old_cursor, new_cursor):
    """迁移新闻数据"""
    try:
        old_cursor.execute("SELECT COUNT(*) FROM news")
        total = old_cursor.fetchone()[0]
        print(f"  找到 {total} 条新闻")
        
        if total == 0:
            return
        
        # 分批迁移（每批 100 条）
        batch_size = 100
        offset = 0
        migrated = 0
        skipped = 0
        
        while offset < total:
            old_cursor.execute(f"SELECT * FROM news LIMIT {batch_size} OFFSET {offset}")
            rows = old_cursor.fetchall()
            
            for row in rows:
                row_dict = dict(row)
                news_id = row_dict['id']
                
                # 检查是否已存在
                new_cursor.execute("SELECT id FROM news WHERE id = ?", (news_id,))
                if new_cursor.fetchone():
                    skipped += 1
                    continue
                
                columns = list(row_dict.keys())
                placeholders = ', '.join(['?' for _ in columns])
                columns_str = ', '.join(columns)
                values = list(row_dict.values())
                
                try:
                    new_cursor.execute(
                        f"INSERT INTO news ({columns_str}) VALUES ({placeholders})",
                        values
                    )
                    migrated += 1
                except:
                    skipped += 1
            
            offset += batch_size
            print(f"    进度: {min(offset, total)}/{total}")
        
        print(f"  ✅ 迁移 {migrated} 条，跳过 {skipped} 条")
    except Exception as e:
        print(f"  ⚠️ 新闻迁移失败: {e}")


def migrate_predictions(old_cursor, new_cursor):
    """迁移股票预测数据"""
    try:
        old_cursor.execute("SELECT * FROM stock_predictions")
        old_rows = old_cursor.fetchall()
        print(f"  找到 {len(old_rows)} 条预测记录")
    except:
        print("  ⚠️ 旧数据库没有 stock_predictions 表")
        return
    
    migrated = 0
    skipped = 0
    
    for row in old_rows:
        row_dict = dict(row)
        pred_id = row_dict['id']
        
        new_cursor.execute("SELECT id FROM stock_predictions WHERE id = ?", (pred_id,))
        if new_cursor.fetchone():
            skipped += 1
            continue
        
        columns = list(row_dict.keys())
        placeholders = ', '.join(['?' for _ in columns])
        columns_str = ', '.join(columns)
        values = list(row_dict.values())
        
        try:
            new_cursor.execute(
                f"INSERT INTO stock_predictions ({columns_str}) VALUES ({placeholders})",
                values
            )
            migrated += 1
        except Exception as e:
            print(f"  ⚠️ 跳过预测 {pred_id}: {e}")
    
    print(f"  ✅ 迁移 {migrated} 条，跳过 {skipped} 条")


def migrate_events(old_cursor, new_cursor):
    """迁移事件数据"""
    try:
        old_cursor.execute("SELECT * FROM events")
        old_rows = old_cursor.fetchall()
        print(f"  找到 {len(old_rows)} 个事件")
    except:
        print("  ⚠️ 旧数据库没有 events 表")
        return
    
    migrated = 0
    skipped = 0
    
    for row in old_rows:
        row_dict = dict(row)
        event_id = row_dict['id']
        
        new_cursor.execute("SELECT id FROM events WHERE id = ?", (event_id,))
        if new_cursor.fetchone():
            skipped += 1
            continue
        
        columns = list(row_dict.keys())
        placeholders = ', '.join(['?' for _ in columns])
        columns_str = ', '.join(columns)
        values = list(row_dict.values())
        
        try:
            new_cursor.execute(
                f"INSERT INTO events ({columns_str}) VALUES ({placeholders})",
                values
            )
            migrated += 1
        except Exception as e:
            print(f"  ⚠️ 跳过事件 {event_id}: {e}")
    
    print(f"  ✅ 迁移 {migrated} 个，跳过 {skipped} 个")


if __name__ == "__main__":
    print("=" * 50)
    print("📦 Finance-Daily 数据迁移工具")
    print("=" * 50)
    migrate_data()

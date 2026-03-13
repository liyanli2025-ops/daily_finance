"""同步测试完整报告生成流程"""
import asyncio
import sys
sys.stdout.reconfigure(encoding='utf-8')

async def main():
    print("=" * 60)
    print("同步测试完整报告生成流程")
    print("=" * 60)
    
    from datetime import datetime
    print(f"开始时间: {datetime.now()}")
    
    # 初始化数据库
    print("\n[1] 初始化数据库...")
    from app.config import settings
    from app.models.database import init_database, get_session_maker
    
    db_engine = await init_database(settings.database_url)
    session_maker = get_session_maker(db_engine)
    print("   ✅ 数据库初始化成功")
    
    # 初始化调度器
    print("\n[2] 初始化调度器...")
    from app.services.scheduler import SchedulerService
    
    scheduler = SchedulerService()
    scheduler.set_db(db_engine, session_maker)
    print("   ✅ 调度器初始化成功")
    
    # 生成报告
    print("\n[3] 开始生成报告...")
    print("   （这可能需要 1-2 分钟，请耐心等待）")
    
    try:
        await scheduler.generate_daily_report()
        print("\n   ✅ 报告生成流程完成！")
    except Exception as e:
        print(f"\n   ❌ 报告生成失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 检查结果
    print("\n[4] 检查生成结果...")
    import sqlite3
    conn = sqlite3.connect('data/database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, title, created_at, substr(content, 1, 300) FROM reports ORDER BY created_at DESC LIMIT 1')
    row = cursor.fetchone()
    if row:
        print(f"   最新报告ID: {row[0][:20]}...")
        print(f"   创建时间: {row[2]}")
        print(f"   内容预览: {row[3][:200]}...")
    conn.close()
    
    # 清理
    await db_engine.dispose()
    print(f"\n结束时间: {datetime.now()}")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())

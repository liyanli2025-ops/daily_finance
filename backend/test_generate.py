"""直接测试报告生成流程"""
import asyncio
import sys
sys.stdout.reconfigure(encoding='utf-8')

async def test_generate():
    print("=" * 60)
    print("直接测试报告生成流程")
    print("=" * 60)
    
    # 1. 初始化数据库
    print("\n1. 初始化数据库...")
    from app.config import settings
    from app.models.database import init_database, get_session_maker
    
    db_engine = await init_database(settings.database_url)
    session_maker = get_session_maker(db_engine)
    print("   ✅ 数据库初始化成功")
    
    # 2. 初始化调度器
    print("\n2. 初始化调度器...")
    from app.services.scheduler import SchedulerService
    
    scheduler = SchedulerService()
    scheduler.set_db(db_engine, session_maker)
    print("   ✅ 调度器初始化成功")
    
    # 3. 生成报告
    print("\n3. 开始生成报告...")
    print("   （这会调用 DeepSeek API，可能需要 1-2 分钟）")
    
    try:
        await scheduler.generate_daily_report()
        print("\n   ✅ 报告生成完成！")
    except Exception as e:
        print(f"\n   ❌ 报告生成失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 4. 检查数据库
    print("\n4. 检查数据库中的报告...")
    import sqlite3
    conn = sqlite3.connect('data/database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, created_at, title FROM reports ORDER BY created_at DESC LIMIT 3')
    rows = cursor.fetchall()
    for row in rows:
        print(f"   - [{row[1]}] {row[2][:40]}...")
    conn.close()
    
    # 清理
    await db_engine.dispose()
    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_generate())

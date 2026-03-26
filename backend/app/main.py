"""
Finance Daily 后端服务主入口
财经智能助手 API 服务
"""
import asyncio
import sys
import io
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

# 修复 Windows 控制台编码问题
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from .config import settings
from .models.database import init_database, get_session_maker
from .routers import reports, podcasts, stocks
from .services.scheduler import SchedulerService


# 全局变量
db_engine = None
scheduler_service = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global db_engine, scheduler_service
    
    # 启动时初始化
    print(f"[启动] 正在启动 {settings.app_name}...")
    
    # 初始化数据库
    db_engine = await init_database(settings.database_url)
    app.state.db_engine = db_engine
    app.state.session_maker = get_session_maker(db_engine)
    print("[OK] 数据库初始化完成")
    
    # 初始化定时调度器
    scheduler_service = SchedulerService()
    # 关键：传入数据库连接，否则报告无法保存
    scheduler_service.set_db(db_engine, app.state.session_maker)
    await scheduler_service.start()
    app.state.scheduler = scheduler_service
    print("[OK] 定时调度器启动完成")
    
    # 确保静态文件目录存在
    settings.podcasts_dir.mkdir(parents=True, exist_ok=True)
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"[OK] {settings.app_name} 启动成功！")
    print(f"[INFO] 每日报告推送时间: {settings.daily_report_hour:02d}:{settings.daily_report_minute:02d}")
    
    yield
    
    # 关闭时清理
    print("[关闭] 正在关闭服务...")
    if scheduler_service:
        await scheduler_service.stop()
    if db_engine:
        await db_engine.dispose()
    print("[BYE] 服务已关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title=settings.app_name,
    description="财经智能助手 - 每日财经报告与播客生成系统 API",
    version="0.1.0",
    lifespan=lifespan
)


# CORS 配置（允许移动端访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 静态文件服务（用于音频文件访问）
podcasts_path = Path(settings.podcasts_dir)
if podcasts_path.exists():
    app.mount("/podcasts", StaticFiles(directory=str(podcasts_path)), name="podcasts")

# 前端静态文件服务
web_path = Path(__file__).parent.parent.parent / "web"
if web_path.exists():
    app.mount("/static", StaticFiles(directory=str(web_path)), name="static")


# 注册路由
app.include_router(reports.router, prefix="/api/reports", tags=["Reports"])
app.include_router(podcasts.router, prefix="/api/podcasts", tags=["Podcasts"])
app.include_router(stocks.router, prefix="/api/stocks", tags=["Stocks"])


@app.get("/")
async def root():
    """根路径 - 返回前端页面"""
    web_path = Path(__file__).parent.parent.parent / "web"
    index_file = web_path / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {
        "name": settings.app_name,
        "version": "0.1.0",
        "status": "running",
        "message": "财经智能助手服务运行中",
        "daily_report_time": f"{settings.daily_report_hour:02d}:{settings.daily_report_minute:02d}"
    }


@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {
        "status": "healthy",
        "database": "connected" if db_engine else "disconnected",
        "scheduler": "running" if scheduler_service and scheduler_service.is_running else "stopped"
    }


@app.post("/api/trigger-report")
async def trigger_report_generation():
    """
    手动触发报告生成（用于测试）
    """
    print(f"\n[API] /api/trigger-report 被调用！时间: {datetime.now()}")
    if scheduler_service:
        print("[API] 创建报告生成任务...")
        
        # 使用包装函数来捕获异常
        async def generate_with_error_handling():
            try:
                await scheduler_service.generate_daily_report()
                print("[API] 报告生成任务完成！")
            except Exception as e:
                print(f"[API] ❌ 报告生成任务失败: {e}")
                import traceback
                traceback.print_exc()
        
        asyncio.create_task(generate_with_error_handling())
        print("[API] 任务已创建，立即返回")
        return {"status": "started", "message": "报告生成任务已启动"}
    print("[API] 调度器未运行！")
    return {"status": "error", "message": "调度器未运行"}


@app.post("/api/generate-report-sync")
async def generate_report_sync():
    """
    同步生成报告（等待完成后返回）
    """
    print(f"\n[API] /api/generate-report-sync 被调用！时间: {datetime.now()}")
    if scheduler_service:
        try:
            await scheduler_service.generate_daily_report()
            return {"status": "success", "message": "报告生成完成"}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}
    return {"status": "error", "message": "调度器未运行"}


@app.get("/api/settings")
async def get_settings():
    """获取当前设置"""
    return {
        "daily_report_hour": settings.daily_report_hour,
        "daily_report_minute": settings.daily_report_minute,
        "tts_voice": settings.tts_voice,
        "ai_model": settings.ai_model,
        "rss_feeds": settings.rss_feeds
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )

"""
定时调度服务
管理每日报告生成、播客合成等定时任务
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional
import uuid

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..config import settings
from .news_collector import get_news_collector
from .ai_analyzer import get_ai_analyzer
from .podcast_generator import get_podcast_generator
from ..models.database import ReportModel, get_session_maker


class SchedulerService:
    """定时调度服务"""
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.is_running = False
        self._db_engine = None
        self._session_maker = None
    
    def set_db(self, engine, session_maker):
        """设置数据库连接"""
        self._db_engine = engine
        self._session_maker = session_maker
    
    async def start(self):
        """启动调度器"""
        if self.is_running:
            return
        
        # 计算新闻采集时间（比报告推送时间早 collection_lead_time 分钟）
        report_hour = settings.daily_report_hour
        report_minute = settings.daily_report_minute
        lead_time = settings.collection_lead_time
        
        # 计算采集开始时间
        collection_time = datetime.now().replace(
            hour=report_hour, 
            minute=report_minute,
            second=0,
            microsecond=0
        ) - timedelta(minutes=lead_time)
        
        collection_hour = collection_time.hour
        collection_minute = collection_time.minute
        
        # 添加每日报告生成任务
        self.scheduler.add_job(
            self.generate_daily_report,
            CronTrigger(
                hour=collection_hour,
                minute=collection_minute
            ),
            id="daily_report",
            name="每日财经报告生成",
            replace_existing=True
        )
        
        # 添加自选股数据更新任务（每小时一次，交易时间）
        self.scheduler.add_job(
            self.update_watchlist_data,
            CronTrigger(
                hour="9-15",
                minute="30"
            ),
            id="watchlist_update",
            name="自选股数据更新",
            replace_existing=True
        )
        
        self.scheduler.start()
        self.is_running = True
        
        print(f"[SCHEDULER] 调度器已启动")
        print(f"   - 每日报告生成时间: {collection_hour:02d}:{collection_minute:02d}")
        print(f"   - 报告推送时间: {report_hour:02d}:{report_minute:02d}")
    
    async def stop(self):
        """停止调度器"""
        if self.is_running:
            self.scheduler.shutdown(wait=False)
            self.is_running = False
            print("[SCHEDULER] 调度器已停止")
    
    async def generate_daily_report(self):
        """
        生成每日报告的完整流程：
        1. 采集新闻
        2. AI 分析生成报告
        3. 生成播客音频
        4. 保存到数据库
        """
        print("\n" + "="*50)
        print(f"[START] 开始生成每日报告 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*50)
        
        try:
            # Step 1: 采集新闻
            print("\n[Step 1] 采集新闻...")
            collector = get_news_collector()
            all_news = await collector.collect_all(hours=24)
            
            # 筛选中国相关新闻
            china_news = collector.filter_china_related(all_news)
            print(f"   筛选出 {len(china_news)} 条中国相关新闻")
            
            if not all_news:
                print("[WARN] 未能从 RSS 源采集到新闻，将使用模拟数据生成报告")
                # 生成模拟新闻数据，确保报告能够生成
                from ..models.news import News, SentimentType
                import uuid
                
                mock_news = [
                    News(
                        id=str(uuid.uuid4()),
                        title="A股市场震荡整理，科技板块表现活跃",
                        content="今日A股市场整体呈现震荡整理态势，上证指数小幅收涨。科技板块领涨两市，新能源、半导体等热门赛道获得资金青睐。",
                        summary="A股震荡整理，科技板块领涨",
                        source="财经快讯",
                        source_url="",
                        published_at=datetime.now(),
                        sentiment=SentimentType.POSITIVE,
                        importance_score=0.8,
                        keywords=["A股", "科技", "新能源"],
                        related_stocks=["000001"],
                        created_at=datetime.now()
                    ),
                    News(
                        id=str(uuid.uuid4()),
                        title="央行维持流动性合理充裕，货币政策稳健",
                        content="央行今日开展逆回购操作，维护银行体系流动性合理充裕。市场人士认为，当前货币政策将继续保持稳健基调。",
                        summary="央行维持流动性，货币政策稳健",
                        source="金融要闻",
                        source_url="",
                        published_at=datetime.now(),
                        sentiment=SentimentType.NEUTRAL,
                        importance_score=0.9,
                        keywords=["央行", "货币政策", "流动性"],
                        related_stocks=[],
                        created_at=datetime.now()
                    ),
                    News(
                        id=str(uuid.uuid4()),
                        title="新能源汽车销量持续增长，行业前景向好",
                        content="最新数据显示，新能源汽车销量同比大幅增长，市场渗透率再创新高。分析人士看好新能源产业链长期发展。",
                        summary="新能源车销量增长，行业向好",
                        source="行业动态",
                        source_url="",
                        published_at=datetime.now(),
                        sentiment=SentimentType.POSITIVE,
                        importance_score=0.75,
                        keywords=["新能源", "汽车", "销量"],
                        related_stocks=["002594", "300750"],
                        created_at=datetime.now()
                    )
                ]
                all_news = mock_news
                china_news = mock_news
            
            # Step 2: AI 分析生成报告
            print("\n[Step 2] AI 分析生成报告...")
            analyzer = get_ai_analyzer()
            
            # 对重要新闻进行情绪分析
            for news in china_news[:10]:
                news.sentiment = await analyzer.analyze_news_sentiment(news)
            
            # 生成报告
            report = await analyzer.generate_daily_report(china_news if china_news else all_news)
            print(f"   报告生成完成: {report.title}")
            print(f"   字数: {report.word_count}, 预计阅读时间: {report.reading_time} 分钟")
            
            # Step 3: 生成播客
            print("\n[Step 3] 生成播客音频...")
            podcast_gen = get_podcast_generator()
            
            try:
                audio_path, duration = await podcast_gen.generate_podcast(report)
                report.podcast_url = f"/podcasts/{report.id}.mp3"
                report.podcast_duration = duration
                report.podcast_status = "ready"
                print(f"   播客生成完成: 时长 {duration // 60} 分钟")
            except Exception as e:
                print(f"   [WARN] 播客生成失败: {e}")
                report.podcast_status = "failed"
            
            # Step 4: 保存到数据库
            print("\n[Step 4] 保存到数据库...")
            await self._save_report(report)
            print(f"   报告已保存，ID: {report.id}")
            
            print("\n" + "="*50)
            print(f"[DONE] 每日报告生成完成！")
            print("="*50 + "\n")
            
        except Exception as e:
            print(f"\n[ERROR] 报告生成失败: {e}")
            import traceback
            traceback.print_exc()
    
    async def generate_podcast_for_report(self, report_id: str):
        """
        为指定报告重新生成播客
        """
        print(f"[PODCAST] 重新生成播客: {report_id}")
        
        try:
            # 从数据库获取报告
            report = await self._get_report(report_id)
            if not report:
                print(f"[WARN] 报告不存在: {report_id}")
                return
            
            # 生成播客
            podcast_gen = get_podcast_generator()
            audio_path, duration = await podcast_gen.generate_podcast(report)
            
            # 更新数据库
            await self._update_report_podcast(
                report_id,
                f"/podcasts/{report_id}.mp3",
                duration,
                "ready"
            )
            
            print(f"[OK] 播客重新生成完成: {report_id}")
            
        except Exception as e:
            print(f"[ERROR] 播客生成失败: {e}")
            await self._update_report_podcast(report_id, None, None, "failed")
    
    async def update_watchlist_data(self):
        """
        更新自选股数据
        """
        print(f"[STOCK] 更新自选股数据 - {datetime.now().strftime('%H:%M:%S')}")
        
        # TODO: 实现自选股数据更新逻辑
        # 1. 获取所有自选股
        # 2. 批量获取实时行情
        # 3. 更新数据库
    
    async def _save_report(self, report):
        """保存报告到数据库"""
        from ..models.database import ReportModel
        
        if not self._session_maker:
            print("[WARN] 数据库未初始化")
            return
        
        async with self._session_maker() as session:
            db_report = ReportModel(
                id=report.id,
                title=report.title,
                summary=report.summary,
                content=report.content,
                report_date=report.report_date,
                highlights=[h.model_dump() for h in report.highlights],
                analysis=report.analysis.model_dump() if report.analysis else None,
                podcast_url=report.podcast_url,
                podcast_duration=report.podcast_duration,
                podcast_status=report.podcast_status,
                word_count=report.word_count,
                reading_time=report.reading_time,
                news_count=report.news_count,
                created_at=report.created_at
            )
            
            session.add(db_report)
            await session.commit()
    
    async def _get_report(self, report_id: str):
        """从数据库获取报告"""
        from sqlalchemy import select
        from ..models.database import ReportModel
        from ..models.report import Report, NewsHighlight, MarketAnalysis
        
        if not self._session_maker:
            return None
        
        async with self._session_maker() as session:
            query = select(ReportModel).where(ReportModel.id == report_id)
            result = await session.execute(query)
            db_report = result.scalar_one_or_none()
            
            if not db_report:
                return None
            
            return Report(
                id=db_report.id,
                title=db_report.title,
                summary=db_report.summary,
                content=db_report.content,
                report_date=db_report.report_date,
                highlights=[NewsHighlight(**h) for h in (db_report.highlights or [])],
                analysis=MarketAnalysis(**db_report.analysis) if db_report.analysis else None,
                podcast_url=db_report.podcast_url,
                podcast_duration=db_report.podcast_duration,
                podcast_status=db_report.podcast_status,
                word_count=db_report.word_count,
                reading_time=db_report.reading_time,
                news_count=db_report.news_count,
                created_at=db_report.created_at
            )
    
    async def _update_report_podcast(self, report_id: str, url: Optional[str], 
                                     duration: Optional[int], status: str):
        """更新报告的播客信息"""
        from sqlalchemy import select
        from ..models.database import ReportModel
        
        if not self._session_maker:
            return
        
        async with self._session_maker() as session:
            query = select(ReportModel).where(ReportModel.id == report_id)
            result = await session.execute(query)
            report = result.scalar_one_or_none()
            
            if report:
                report.podcast_url = url
                report.podcast_duration = duration
                report.podcast_status = status
                report.updated_at = datetime.now()
                await session.commit()


# 单例实例
_scheduler_instance: Optional[SchedulerService] = None


def get_scheduler() -> SchedulerService:
    """获取调度服务实例"""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = SchedulerService()
    return _scheduler_instance

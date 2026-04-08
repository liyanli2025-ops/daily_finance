"""
定时调度服务
管理每日报告生成、播客合成等定时任务

重构版：支持早报+晚报双播客模式
- 交易日：早报（凌晨） + 晚报（下午5点）
- 非交易日：仅早报（深度周报版）
"""
import sys
import asyncio
from datetime import datetime, timedelta, date
from typing import Optional
import uuid

# 强制行缓冲，让 print 立即写入日志文件（nohup 重定向时默认是全缓冲）
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass  # Python < 3.7 或特殊环境下可能不支持

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..config import settings
from .news_collector import get_news_collector
from .ai_analyzer import get_ai_analyzer
from .podcast_generator import get_podcast_generator
from .signal_tracker import get_signal_tracker
from .backtest_service import get_backtest_service
from ..models.database import ReportModel, get_session_maker
from ..models.report import ReportType, Report


class SchedulerService:
    """定时调度服务"""
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.is_running = False
        self._db_engine = None
        self._session_maker = None
        
        # 中国节假日列表（需要定期更新）
        # 格式：YYYY-MM-DD
        self._holidays_2024 = {
            "2024-01-01",  # 元旦
            "2024-02-10", "2024-02-11", "2024-02-12", "2024-02-13", "2024-02-14", "2024-02-15", "2024-02-16", "2024-02-17",  # 春节
            "2024-04-04", "2024-04-05", "2024-04-06",  # 清明
            "2024-05-01", "2024-05-02", "2024-05-03", "2024-05-04", "2024-05-05",  # 劳动节
            "2024-06-08", "2024-06-09", "2024-06-10",  # 端午
            "2024-09-15", "2024-09-16", "2024-09-17",  # 中秋
            "2024-10-01", "2024-10-02", "2024-10-03", "2024-10-04", "2024-10-05", "2024-10-06", "2024-10-07",  # 国庆
        }
        self._holidays_2025 = {
            "2025-01-01",  # 元旦
            "2025-01-28", "2025-01-29", "2025-01-30", "2025-01-31", "2025-02-01", "2025-02-02", "2025-02-03", "2025-02-04",  # 春节
            "2025-04-04", "2025-04-05", "2025-04-06",  # 清明
            "2025-05-01", "2025-05-02", "2025-05-03", "2025-05-04", "2025-05-05",  # 劳动节
            "2025-05-31", "2025-06-01", "2025-06-02",  # 端午
            "2025-10-01", "2025-10-02", "2025-10-03", "2025-10-04", "2025-10-05", "2025-10-06", "2025-10-07", "2025-10-08",  # 国庆+中秋
        }
        self._holidays_2026 = {
            "2026-01-01", "2026-01-02", "2026-01-03",  # 元旦（1/1周四-1/3周六，1/4周日上班）
            "2026-02-15", "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20", "2026-02-21", "2026-02-22", "2026-02-23",  # 春节（2/15周日-2/23周一，2/14周六、2/28周六上班）
            "2026-04-04", "2026-04-05", "2026-04-06",  # 清明（4/4周六-4/6周一，不调休）
            "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",  # 劳动节（5/1周五-5/5周二，5/9周六上班）
            "2026-06-19", "2026-06-20", "2026-06-21",  # 端午（6/19周五-6/21周日，不调休）
            "2026-09-25", "2026-09-26", "2026-09-27",  # 中秋（9/25周五-9/27周日，不调休）
            "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05", "2026-10-06", "2026-10-07",  # 国庆（10/1周四-10/7周三，9/20周日、10/10周六上班）
        }
    
    def set_db(self, engine, session_maker):
        """设置数据库连接"""
        self._db_engine = engine
        self._session_maker = session_maker
        
        # 同步数据库到信号追踪和回测服务
        get_signal_tracker().set_db(session_maker)
        get_backtest_service().set_db(session_maker)
    
    def is_trading_day(self, check_date: date = None) -> bool:
        """
        判断是否是交易日
        
        交易日条件：
        1. 不是周末（周六、周日）
        2. 不是法定节假日
        """
        if check_date is None:
            check_date = date.today()
        
        # 周末不是交易日
        if check_date.weekday() >= 5:  # 5=周六, 6=周日
            return False
        
        # 检查是否是节假日
        date_str = check_date.strftime("%Y-%m-%d")
        all_holidays = self._holidays_2024 | self._holidays_2025 | self._holidays_2026
        if date_str in all_holidays:
            return False
        
        return True
    
    def get_last_trading_day(self, from_date: date = None) -> date:
        """获取上一个交易日"""
        if from_date is None:
            from_date = date.today()
        
        last_day = from_date - timedelta(days=1)
        while not self.is_trading_day(last_day):
            last_day -= timedelta(days=1)
        
        return last_day
    
    async def start(self):
        """启动调度器"""
        if self.is_running:
            return
        
        # ==================== 早报任务配置 ====================
        report_hour = settings.daily_report_hour
        report_minute = settings.daily_report_minute
        lead_time = settings.collection_lead_time
        
        # 计算早报采集开始时间
        collection_time = datetime.now().replace(
            hour=report_hour, 
            minute=report_minute,
            second=0,
            microsecond=0
        ) - timedelta(minutes=lead_time)
        
        collection_hour = collection_time.hour
        collection_minute = collection_time.minute
        
        # 添加早报生成任务（每天执行，内部判断是否是交易日）
        self.scheduler.add_job(
            self.generate_morning_report,
            CronTrigger(
                hour=collection_hour,
                minute=collection_minute
            ),
            id="morning_report",
            name="每日早报生成",
            replace_existing=True
        )
        
        # ==================== 晚报任务配置 ====================
        evening_hour = settings.evening_report_hour
        evening_minute = settings.evening_report_minute
        evening_collection_hour = settings.evening_collection_hour
        
        # 添加晚报生成任务（仅交易日执行，在任务内部判断）
        self.scheduler.add_job(
            self.generate_evening_report,
            CronTrigger(
                hour=evening_collection_hour,
                minute=0,
                day_of_week="mon-fri"  # 周一到周五触发，内部再判断是否真正的交易日
            ),
            id="evening_report",
            name="每日晚报生成",
            replace_existing=True
        )
        
        # ==================== 盘中预采集任务配置 ====================
        midday_hour = settings.midday_collection_hour
        midday_minute = settings.midday_collection_minute
        
        # 添加盘中预采集任务（交易日午间执行，缓存上午新闻）
        self.scheduler.add_job(
            self.midday_news_precollect,
            CronTrigger(
                hour=midday_hour,
                minute=midday_minute,
                day_of_week="mon-fri"  # 周一到周五触发，内部再判断是否真正的交易日
            ),
            id="midday_precollect",
            name="盘中新闻预采集",
            replace_existing=True
        )
        
        # ==================== 自选股更新任务 ====================
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
        
        # ==================== 盘后回测任务 ====================
        # 在晚报采集前执行（15:30），回测今日早报的预测准确度
        self.scheduler.add_job(
            self.run_backtest,
            CronTrigger(
                hour=15,
                minute=30,
                day_of_week="mon-fri"
            ),
            id="backtest",
            name="盘后回测（早报预测准确度）",
            replace_existing=True
        )
        
        # ==================== 信号追踪任务 ====================
        # 15:35 记录今日技术信号 + 评估7天前的信号
        self.scheduler.add_job(
            self.run_signal_tracking,
            CronTrigger(
                hour=15,
                minute=35,
                day_of_week="mon-fri"
            ),
            id="signal_tracking",
            name="技术信号追踪与胜率统计",
            replace_existing=True
        )
        
        self.scheduler.start()
        self.is_running = True
        
        print(f"[SCHEDULER] 调度器已启动")
        print(f"   - 早报采集时间: {collection_hour:02d}:{collection_minute:02d}")
        print(f"   - 早报推送时间: {report_hour:02d}:{report_minute:02d}")
        print(f"   - 盘中预采集时间: {midday_hour:02d}:{midday_minute:02d} (仅交易日)")
        print(f"   - 盘后回测时间: 15:30 (仅交易日)")
        print(f"   - 信号追踪时间: 15:35 (仅交易日)")
        print(f"   - 晚报采集时间: {evening_collection_hour:02d}:00 (仅交易日)")
        print(f"   - 晚报推送时间: {evening_hour:02d}:{evening_minute:02d} (仅交易日)")
    
    async def stop(self):
        """停止调度器"""
        if self.is_running:
            self.scheduler.shutdown(wait=False)
            self.is_running = False
            print("[SCHEDULER] 调度器已停止")
    
    async def generate_morning_report(self):
        """
        生成早报的完整流程
        
        交易日早报：
        - 结合前一个交易日的市场情况
        - 昨天收盘后的新闻、重要信息
        - 国际市场情况（美股、港股夜盘等）
        - 侧重当天操作建议
        
        非交易日早报（深度版）：
        - 整周市场表现复盘
        - 重要新闻深度梳理
        - 重要概念科普
        - 下周操作预测
        """
        import sys
        today = date.today()
        is_trading = self.is_trading_day(today)
        report_type_str = "交易日早报" if is_trading else "非交易日深度早报"
        
        print("\n" + "="*50, flush=True)
        print(f"[START] 开始生成{report_type_str} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
        print("="*50, flush=True)
        sys.stdout.flush()
        
        try:
            # Step 1: 采集新闻（带超时保护，防止某个数据源卡住导致进程假死）
            NEWS_COLLECT_TIMEOUT = 300  # 5 分钟超时
            print(f"\n[Step 1] 采集新闻（超时 {NEWS_COLLECT_TIMEOUT}s）...", flush=True)
            collector = get_news_collector()
            
            # 非交易日采集更长时间的新闻（整周）
            hours = 168 if not is_trading else 24  # 非交易日采集7天，交易日采集24小时
            
            try:
                all_news = await asyncio.wait_for(
                    collector.collect_all(hours=hours),
                    timeout=NEWS_COLLECT_TIMEOUT
                )
            except asyncio.TimeoutError:
                print(f"[WARN] ⚠️ 新闻采集超时 ({NEWS_COLLECT_TIMEOUT}s)！将使用已采集到的数据或模拟数据", flush=True)
                all_news = []
            
            # 分离财经新闻和跨界新闻
            news_by_type = collector.get_news_by_type(all_news)
            finance_news = news_by_type.get('finance', [])
            
            # 筛选中国相关财经新闻
            china_news = collector.filter_china_related(finance_news)
            print(f"   筛选出 {len(china_news)} 条中国及全球市场相关财经新闻（含大宗商品/外盘）")
            
            # 如果筛选后新闻太少，放宽使用全部财经新闻
            if len(china_news) < 5 and len(finance_news) > 0:
                print(f"   [INFO] 筛选后新闻较少，补充使用全部 {len(finance_news)} 条财经新闻")
                china_news = finance_news
            
            # 筛选跨界新闻
            cross_border_news = collector.filter_cross_border_news(all_news)
            print(f"   筛选出 {len(cross_border_news)} 条跨界热点新闻")
            if cross_border_news:
                for news in cross_border_news[:5]:
                    print(f"      - [{news.news_type.value}] {news.title[:40]}...")
            
            if not all_news:
                print("[WARN] 未能从 RSS 源采集到新闻，将使用模拟数据生成报告")
                china_news, cross_border_news = self._generate_mock_news()
            
            # Step 2: AI 分析生成早报
            # Step 2: AI 分析生成早报（带超时保护）
            AI_REPORT_TIMEOUT = 600  # 10 分钟超时
            print(f"\n[Step 2] AI 分析生成{report_type_str}（超时 {AI_REPORT_TIMEOUT}s）...", flush=True)
            analyzer = get_ai_analyzer(force_reinit=True)
            
            # 对重要新闻进行情绪分析（单条超时30秒，失败跳过）
            for news in china_news[:10]:
                try:
                    news.sentiment = await asyncio.wait_for(
                        analyzer.analyze_news_sentiment(news),
                        timeout=30
                    )
                except (asyncio.TimeoutError, Exception) as e:
                    print(f"   [WARN] 情绪分析跳过: {str(e)[:50]}", flush=True)
            
            # 生成早报（传入报告类型和是否交易日）
            try:
                report = await asyncio.wait_for(
                    analyzer.generate_daily_report(
                        china_news if china_news else finance_news,
                        cross_border_news,
                        report_type=ReportType.MORNING,
                        is_trading_day=is_trading
                    ),
                    timeout=AI_REPORT_TIMEOUT
                )
            except asyncio.TimeoutError:
                print(f"\n[ERROR] ⚠️ AI 报告生成超时 ({AI_REPORT_TIMEOUT}s)！跳过本次生成", flush=True)
                return
            
            print(f"   报告生成完成: {report.title}")
            print(f"   字数: {report.word_count}, 预计阅读时间: {report.reading_time} 分钟")
            print(f"   核心观点: {len(report.core_opinions)} 条")
            print(f"   跨界事件: {len(report.cross_border_events)} 条")
            
            # Step 3: 生成播客
            print(f"\n[Step 3] 生成播客音频...")
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
            print(f"[DONE] {report_type_str}生成完成！")
            print("="*50 + "\n")
            
        except Exception as e:
            print(f"\n[ERROR] 早报生成失败: {e}")
            import traceback
            traceback.print_exc()
    
    async def midday_news_precollect(self):
        """
        盘中新闻预采集（交易日午间执行）
        
        在交易日午休时（如 11:35）采集上午的新闻和雪球讨论，
        缓存在内存中，供晚报生成时合并使用。
        
        这样做的目的：
        - 锁定上午的盘中新闻（盘中突发消息、异动解读等）
        - 捕获午间雪球最活跃的投资者观点
        - 避免下午4点采集时，上午的热点新闻被下午新闻冲掉
        """
        import sys
        today = date.today()
        
        # 非交易日不执行
        if not self.is_trading_day(today):
            print(f"[SKIP] 今天 {today} 不是交易日，跳过盘中预采集")
            return
        
        print("\n" + "-"*40, flush=True)
        print(f"[盘中预采集] 开始 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
        print("-"*40, flush=True)
        sys.stdout.flush()
        
        try:
            collector = get_news_collector()
            
            # 采集上午的新闻（开盘前2h + 盘中2h ≈ 4小时窗口）
            midday_news = await collector.collect_midday_cache(hours=4)
            
            print(f"[盘中预采集] 完成，缓存了 {len(midday_news)} 条盘中新闻")
            print("-"*40 + "\n", flush=True)
            
        except Exception as e:
            print(f"\n[ERROR] 盘中预采集失败（不影响晚报生成）: {e}")
            import traceback
            traceback.print_exc()
    
    async def generate_evening_report(self):
        """
        生成晚报的完整流程（仅交易日）
        
        晚报内容：
        - 当天交易情况梳理总结
        - 回顾早报内容，评价预测准确性
        - 结合市场技术面、新闻事件影响分析
        - 对明日市场情况、投资建议作出预测
        - 新颖/深刻的概念解释
        """
        import sys
        today = date.today()
        
        # 非交易日不生成晚报
        if not self.is_trading_day(today):
            print(f"[SKIP] 今天 {today} 不是交易日，跳过晚报生成")
            return
        
        print("\n" + "="*50, flush=True)
        print(f"[START] 开始生成交易日晚报 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
        print("="*50, flush=True)
        sys.stdout.flush()
        
        try:
            # Step 1: 获取今日早报（用于对比评价）
            print("\n[Step 1] 获取今日早报...")
            morning_report = await self._get_today_morning_report()
            if morning_report:
                print(f"   找到今日早报: {morning_report.title}")
            else:
                print("   [WARN] 未找到今日早报，将独立生成晚报")
            
            # Step 2: 采集盘后新闻和当日市场数据（带超时保护）
            NEWS_COLLECT_TIMEOUT = 300  # 5 分钟超时
            print(f"\n[Step 2] 采集盘后数据（超时 {NEWS_COLLECT_TIMEOUT}s）...", flush=True)
            collector = get_news_collector()
            
            # 采集今天下午到现在的新闻
            try:
                all_news = await asyncio.wait_for(
                    collector.collect_all(hours=8),
                    timeout=NEWS_COLLECT_TIMEOUT
                )
            except asyncio.TimeoutError:
                print(f"[WARN] ⚠️ 晚报新闻采集超时 ({NEWS_COLLECT_TIMEOUT}s)！", flush=True)
                all_news = []
            
            # 【核心改动】合并盘中预采集缓存，确保盘中新闻不丢失
            midday_cache = collector.get_midday_cache()
            midday_cache_count = len(midday_cache)
            all_news = collector.merge_with_midday_cache(all_news)
            
            # 分离新闻
            news_by_type = collector.get_news_by_type(all_news)
            finance_news = news_by_type.get('finance', [])
            china_news = collector.filter_china_related(finance_news)
            cross_border_news = collector.filter_cross_border_news(all_news)
            
            print(f"   筛选出 {len(china_news)} 条中国及全球市场相关财经新闻（含大宗商品/外盘）")
            print(f"   筛选出 {len(cross_border_news)} 条跨界热点新闻")
            
            # 如果筛选后新闻太少，放宽使用全部财经新闻
            if len(china_news) < 5 and len(finance_news) > 0:
                print(f"   [INFO] 筛选后新闻较少，补充使用全部 {len(finance_news)} 条财经新闻")
                china_news = finance_news
            
            if not all_news:
                print("[WARN] 未能采集到新闻，将使用模拟数据")
                china_news, cross_border_news = self._generate_mock_news()
            
            # Step 3: AI 分析生成晚报（带超时保护）
            AI_REPORT_TIMEOUT = 600  # 10 分钟超时
            print(f"\n[Step 3] AI 分析生成晚报（超时 {AI_REPORT_TIMEOUT}s）...", flush=True)
            analyzer = get_ai_analyzer(force_reinit=True)
            
            # 对重要新闻进行情绪分析（单条超时30秒，失败跳过）
            for news in china_news[:10]:
                try:
                    news.sentiment = await asyncio.wait_for(
                        analyzer.analyze_news_sentiment(news),
                        timeout=30
                    )
                except (asyncio.TimeoutError, Exception) as e:
                    print(f"   [WARN] 情绪分析跳过: {str(e)[:50]}", flush=True)
            
            # 生成晚报（传入今日早报用于回顾对比）
            try:
                report = await asyncio.wait_for(
                    analyzer.generate_daily_report(
                        china_news if china_news else finance_news,
                        cross_border_news,
                        report_type=ReportType.EVENING,
                        is_trading_day=True,
                        morning_report=morning_report
                    ),
                    timeout=AI_REPORT_TIMEOUT
                )
            except asyncio.TimeoutError:
                print(f"\n[ERROR] ⚠️ 晚报 AI 报告生成超时 ({AI_REPORT_TIMEOUT}s)！跳过本次生成", flush=True)
                return
            
            print(f"   报告生成完成: {report.title}")
            print(f"   字数: {report.word_count}, 预计阅读时间: {report.reading_time} 分钟")
            
            # Step 4: 生成播客（晚报版可以更长）
            print("\n[Step 4] 生成播客音频...")
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
            
            # Step 5: 保存到数据库
            print("\n[Step 5] 保存到数据库...")
            await self._save_report(report)
            print(f"   报告已保存，ID: {report.id}")
            
            print("\n" + "="*50)
            print(f"[DONE] 交易日晚报生成完成！")
            print("="*50 + "\n")
            
        except Exception as e:
            print(f"\n[ERROR] 晚报生成失败: {e}")
            import traceback
            traceback.print_exc()
    
    async def generate_daily_report(self):
        """
        兼容旧接口：生成每日报告（默认生成早报）
        """
        await self.generate_morning_report()
    
    async def generate_podcast_for_report(self, report_id: str):
        """
        为指定报告重新生成播客
        """
        import traceback
        print(f"[PODCAST] 重新生成播客: {report_id}", flush=True)
        
        try:
            # 从数据库获取报告
            report = await self._get_report(report_id)
            if not report:
                print(f"[WARN] 报告不存在: {report_id}", flush=True)
                return
            
            # 生成播客
            podcast_gen = get_podcast_generator()
            audio_path, duration = await podcast_gen.generate_podcast(report)
            
            print(f"[PODCAST] 生成完成，时长: {duration} 秒，路径: {audio_path}", flush=True)
            
            # 更新数据库
            await self._update_report_podcast(
                report_id,
                f"/podcasts/{report_id}.mp3",
                duration,
                "ready"
            )
            
            print(f"[OK] 播客重新生成完成: {report_id}, 时长: {duration}秒", flush=True)
            
        except Exception as e:
            print(f"[ERROR] 播客生成失败: {e}", flush=True)
            traceback.print_exc()
            try:
                await self._update_report_podcast(report_id, None, None, "failed")
            except Exception as e2:
                print(f"[ERROR] 更新失败状态也失败: {e2}", flush=True)
    
    def _generate_mock_news(self):
        """生成模拟新闻数据"""
        from ..models.news import News, SentimentType, NewsType
        
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
                news_type=NewsType.FINANCE,
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
                news_type=NewsType.FINANCE,
                created_at=datetime.now()
            ),
            News(
                id=str(uuid.uuid4()),
                title="国际局势紧张，地缘政治风险上升",
                content="近期国际局势出现新变化，地缘政治风险有所上升。分析人士认为这可能影响全球资本市场风险偏好。",
                summary="地缘政治风险上升",
                source="国际新闻",
                source_url="",
                published_at=datetime.now(),
                sentiment=SentimentType.NEGATIVE,
                importance_score=0.85,
                keywords=["地缘", "风险", "国际"],
                related_stocks=[],
                news_type=NewsType.GEOPOLITICAL,
                beneficiary_sectors=["黄金", "军工"],
                affected_sectors=["航空", "旅游"],
                created_at=datetime.now()
            )
        ]
        
        china_news = [n for n in mock_news if n.news_type == NewsType.FINANCE]
        cross_border_news = [n for n in mock_news if n.news_type != NewsType.FINANCE]
        return china_news, cross_border_news
    
    async def _get_today_morning_report(self) -> Optional[Report]:
        """获取今日早报（用于晚报对比）"""
        from sqlalchemy import select, and_
        from ..models.report import Report, NewsHighlight, MarketAnalysis, ReportType
        
        if not self._session_maker:
            return None
        
        today = date.today()
        
        async with self._session_maker() as session:
            query = select(ReportModel).where(
                and_(
                    ReportModel.report_date == today,
                    ReportModel.report_type == "morning"
                )
            ).order_by(ReportModel.created_at.desc()).limit(1)
            
            result = await session.execute(query)
            db_report = result.scalars().first()
            
            if not db_report:
                return None
            
            return Report(
                id=db_report.id,
                title=db_report.title,
                summary=db_report.summary,
                content=db_report.content,
                report_date=db_report.report_date,
                report_type=ReportType(db_report.report_type) if db_report.report_type else ReportType.MORNING,
                core_opinions=db_report.core_opinions or [],
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
    
    async def run_backtest(self):
        """
        盘后回测任务（交易日15:30执行）
        
        自动对比今日早报的预测 vs 实际收盘数据，
        计算预测准确率，保存结果。
        """
        import sys
        today = date.today()
        
        if not self.is_trading_day(today):
            print(f"[SKIP] 今天 {today} 不是交易日，跳过回测")
            return
        
        print(f"\n[BACKTEST] 开始盘后回测 - {datetime.now().strftime('%H:%M:%S')}", flush=True)
        sys.stdout.flush()
        
        try:
            # Step 1: 获取今日早报
            morning_report = await self._get_today_morning_report()
            if not morning_report:
                print("[BACKTEST] 未找到今日早报，跳过回测")
                return
            
            # Step 2: 执行回测
            backtest_service = get_backtest_service()
            evaluation = await backtest_service.evaluate_morning_predictions(morning_report)
            
            if evaluation:
                accuracy = evaluation.get("overall_accuracy", 0)
                direction = evaluation.get("market_direction", {})
                print(f"[BACKTEST] ✅ 回测完成！")
                print(f"   综合准确率: {accuracy*100:.0f}%")
                print(f"   大盘方向: {'✅ 命中' if direction.get('hit') else '❌ 失误'}")
                print(f"   经验教训: {evaluation.get('lessons', 'N/A')}")
            else:
                print("[BACKTEST] 回测未能完成（数据不足）")
                
        except Exception as e:
            print(f"[BACKTEST ERROR] 回测失败: {e}")
            import traceback
            traceback.print_exc()
    
    async def run_signal_tracking(self):
        """
        技术信号追踪任务（交易日15:35执行）
        
        两件事：
        1. 记录今日的技术信号机会股
        2. 评估7天前的信号是否命中
        """
        import sys
        today = date.today()
        
        if not self.is_trading_day(today):
            print(f"[SKIP] 今天 {today} 不是交易日，跳过信号追踪")
            return
        
        print(f"\n[SIGNAL] 开始信号追踪 - {datetime.now().strftime('%H:%M:%S')}", flush=True)
        sys.stdout.flush()
        
        signal_tracker = get_signal_tracker()
        
        try:
            # Step 1: 记录今日技术信号
            print("[SIGNAL] Step 1: 记录今日技术信号...")
            from .market_data_service import get_market_data_service
            
            market_service = get_market_data_service()
            market_data = await market_service.get_market_overview(today)
            
            if market_data.tech_signal_stocks:
                await signal_tracker.record_today_signals(market_data.tech_signal_stocks)
            else:
                print("[SIGNAL] 今日无技术信号机会股")
            
        except Exception as e:
            print(f"[SIGNAL ERROR] 记录今日信号失败: {e}")
            import traceback
            traceback.print_exc()
        
        try:
            # Step 2: 评估7天前的信号
            print("[SIGNAL] Step 2: 评估7天前的信号...")
            await signal_tracker.evaluate_past_signals(days_back=7)
            
            # 打印当前胜率摘要
            win_rates = await signal_tracker.get_signal_win_rates()
            if win_rates:
                print("[SIGNAL] 📊 当前各信号胜率：")
                for signal_type, data in sorted(win_rates.items(), key=lambda x: x[1]["win_rate"], reverse=True):
                    print(f"   - {signal_type}: {data['win_rate']*100:.0f}% ({data['sample_size']}次)")
            
        except Exception as e:
            print(f"[SIGNAL ERROR] 评估历史信号失败: {e}")
            import traceback
            traceback.print_exc()
        
        print(f"[SIGNAL] ✅ 信号追踪完成")
    
    async def update_watchlist_data(self):
        """
        更新自选股数据
        - 获取所有自选股
        - 批量获取实时行情
        - 更新数据库中的价格和涨跌幅
        """
        print(f"[STOCK] 开始更新自选股数据 - {datetime.now().strftime('%H:%M:%S')}")
        
        if not self._session_maker:
            print("[WARN] 数据库未初始化，跳过自选股更新")
            return
        
        try:
            from sqlalchemy import select
            from ..models.database import StockModel
            
            async with self._session_maker() as session:
                # 1. 获取所有自选股
                query = select(StockModel)
                result = await session.execute(query)
                stocks = result.scalars().all()
                
                if not stocks:
                    print("[STOCK] 没有自选股，跳过更新")
                    return
                
                print(f"[STOCK] 开始更新 {len(stocks)} 只自选股")
                
                # 2. 批量获取实时行情
                import akshare as ak
                
                # 获取 A股实时行情（一次性获取所有）
                try:
                    a_share_df = ak.stock_zh_a_spot_em()
                except Exception as e:
                    print(f"[STOCK] 获取A股行情失败: {e}")
                    a_share_df = None
                
                # 获取港股实时行情
                try:
                    hk_df = ak.stock_hk_spot_em()
                except Exception as e:
                    print(f"[STOCK] 获取港股行情失败: {e}")
                    hk_df = None
                
                # 3. 更新每只股票
                updated_count = 0
                for stock in stocks:
                    try:
                        if stock.market == 'A' and a_share_df is not None:
                            row = a_share_df[a_share_df['代码'] == stock.code]
                            if not row.empty:
                                r = row.iloc[0]
                                stock.current_price = float(r['最新价']) if r['最新价'] else None
                                stock.change_percent = float(r['涨跌幅']) if r['涨跌幅'] else None
                                stock.last_updated = datetime.now()
                                updated_count += 1
                        elif stock.market == 'HK' and hk_df is not None:
                            code_padded = stock.code.zfill(5)
                            row = hk_df[hk_df['代码'] == code_padded]
                            if not row.empty:
                                r = row.iloc[0]
                                stock.current_price = float(r['最新价']) if r['最新价'] else None
                                stock.change_percent = float(r['涨跌幅']) if r['涨跌幅'] else None
                                stock.last_updated = datetime.now()
                                updated_count += 1
                    except Exception as e:
                        print(f"[STOCK] 更新 {stock.code} 失败: {e}")
                
                await session.commit()
                print(f"[STOCK] 自选股数据更新完成，更新了 {updated_count}/{len(stocks)} 只")
                
        except Exception as e:
            print(f"[ERROR] 更新自选股数据失败: {e}")
            import traceback
            traceback.print_exc()
    
    async def _save_report(self, report):
        """
        保存报告到数据库（同日同类型覆盖模式）
        
        逻辑：
        - 检查今天是否已有同类型（morning/evening）的报告
        - 如果有，覆盖更新内容（保留原记录ID，避免数据库膨胀）
        - 如果没有，新增一条记录
        - 早报和晚报互不干扰：早报多次生成只覆盖早报，不影响晚报
        """
        from ..models.database import ReportModel
        from sqlalchemy import select, and_
        
        if not self._session_maker:
            print("[WARN] 数据库未初始化")
            return
        
        report_type_str = report.report_type.value if hasattr(report, 'report_type') and report.report_type else "morning"
        
        async with self._session_maker() as session:
            # 检查同日同类型的旧报告
            existing_query = select(ReportModel).where(
                and_(
                    ReportModel.report_date == report.report_date,
                    ReportModel.report_type == report_type_str
                )
            ).order_by(ReportModel.created_at.desc()).limit(1)
            
            result = await session.execute(existing_query)
            existing_report = result.scalars().first()
            
            if existing_report:
                # 覆盖更新已有报告
                print(f"   [INFO] 发现同日{'早报' if report_type_str == 'morning' else '晚报'}，覆盖更新（旧ID: {existing_report.id}）")
                existing_report.title = report.title
                existing_report.summary = report.summary
                existing_report.content = report.content
                existing_report.core_opinions = report.core_opinions if hasattr(report, 'core_opinions') else []
                existing_report.highlights = [h.model_dump() for h in report.highlights]
                existing_report.cross_border_events = [e.model_dump() for e in report.cross_border_events] if hasattr(report, 'cross_border_events') else []
                existing_report.analysis = report.analysis.model_dump() if report.analysis else None
                existing_report.podcast_url = report.podcast_url
                existing_report.podcast_duration = report.podcast_duration
                existing_report.podcast_status = report.podcast_status
                existing_report.word_count = report.word_count
                existing_report.reading_time = report.reading_time
                existing_report.news_count = report.news_count
                existing_report.cross_border_count = report.cross_border_count if hasattr(report, 'cross_border_count') else 0
                existing_report.updated_at = datetime.now()
                # 更新 report 对象的 id 以匹配数据库记录（保持一致性）
                report.id = existing_report.id
            else:
                # 新增报告
                db_report = ReportModel(
                    id=report.id,
                    title=report.title,
                    summary=report.summary,
                    content=report.content,
                    report_date=report.report_date,
                    report_type=report_type_str,
                    core_opinions=report.core_opinions if hasattr(report, 'core_opinions') else [],
                    highlights=[h.model_dump() for h in report.highlights],
                    cross_border_events=[e.model_dump() for e in report.cross_border_events] if hasattr(report, 'cross_border_events') else [],
                    analysis=report.analysis.model_dump() if report.analysis else None,
                    podcast_url=report.podcast_url,
                    podcast_duration=report.podcast_duration,
                    podcast_status=report.podcast_status,
                    word_count=report.word_count,
                    reading_time=report.reading_time,
                    news_count=report.news_count,
                    cross_border_count=report.cross_border_count if hasattr(report, 'cross_border_count') else 0,
                    created_at=report.created_at
                )
                session.add(db_report)
            
            await session.commit()
    
    async def _get_report(self, report_id: str):
        """从数据库获取报告"""
        from sqlalchemy import select
        from ..models.database import ReportModel
        from ..models.report import Report, NewsHighlight, MarketAnalysis, ReportType
        
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
                report_type=ReportType(db_report.report_type) if db_report.report_type else ReportType.MORNING,
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

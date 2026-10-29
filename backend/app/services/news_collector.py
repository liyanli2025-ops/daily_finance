"""
新闻采集服务
支持多源 RSS 抓取、网页爬取、去重和聚类
增强版：
- 集成 FinBERT 深度情感分析
- 支持自选股个股新闻采集
- 支持自选股行业新闻采集
"""
import asyncio
import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
from .time_context import china_now, china_today
from dataclasses import dataclass
import uuid

import feedparser
import httpx
from bs4 import BeautifulSoup

from ..config import settings
from ..models.news import News, NewsCreate, SentimentType, NewsType, SentimentStrength
from .watchlist_service import get_watchlist_service, WatchlistStock
from .watchlist_repository import read_app_watchlist
from .news_selection import matches_watchlist, within_window
from .evidence import article_url


@dataclass
class RawNewsItem:
    """原始新闻条目"""
    title: str
    content: str
    source: str
    source_url: str
    published_at: datetime


class NewsCollectorService:
    """新闻采集服务"""
    
    def __init__(self,sentiment=True):
        self.client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )
        self._archive_enabled=True
        self._rss_coverage={}
        from pathlib import Path
        self._rss_state_root=Path(__file__).resolve().parents[2]/'data/radar/rss-state'
        
        # 仅保留本次生产验收可用的节点，移除域名解析失败的备用节点。
        self._rsshub_nodes = [
            "https://rsshub.rssforever.com",
        ]
        self._current_rsshub_node = self._rsshub_nodes[0]
        
        # RSS 源配置
        # url 中包含 {RSSHUB} 占位符的会自动替换为当前可用的 RSSHub 节点
        self.rss_feeds = [
            # ==========================================
            # 财经类新闻（国内 — 核心信源）
            # ==========================================
            {
                "url": "{RSSHUB}/jin10/flash",
                "name": "金十数据",
                "category": "快讯",
                "news_type": "finance"
            },
            {
                "url": "{RSSHUB}/eastmoney/report/strategyreport",
                "name": "东方财富研报",
                "category": "研报",
                "news_type": "finance"
            },
            {
                "url": "http://news.baidu.com/n?cmd=1&class=finannews&tn=rss&sub=0",
                "name": "百度财经焦点",
                "category": "综合财经",
                "news_type": "finance"
            },
            {
                "url": "http://news.baidu.com/n?cmd=1&class=stock&tn=rss&sub=0",
                "name": "百度股票焦点",
                "category": "股票",
                "news_type": "finance"
            },
            
            # ==========================================
            # 【新增】差异化财经信源（实测可用）
            # ==========================================
            {
                "url": "{RSSHUB}/gelonghui/live",
                "name": "格隆汇7x24快讯",
                "category": "全球快讯",
                "news_type": "finance"
            },
            
            # ==========================================
            # 国际财经新闻
            # ==========================================
            {
                "url": "{RSSHUB}/wallstreetcn/news/global",
                "name": "华尔街见闻-全球",
                "category": "国际财经",
                "news_type": "finance"
            },
            {
                "url": "{RSSHUB}/wallstreetcn/news/shares",
                "name": "华尔街见闻-股市",
                "category": "全球股市",
                "news_type": "finance"
            },
            {
                "url": "{RSSHUB}/finviz/news",
                "name": "Finviz美股新闻",
                "category": "美股",
                "news_type": "finance"
            },
            
            # ==========================================
            # 港股/日股
            # ==========================================
            {
                "url": "{RSSHUB}/hkej/index",
                "name": "信报财经新闻",
                "category": "港股",
                "news_type": "finance"
            },
            {
                "url": "{RSSHUB}/gelonghui/subject/3",
                "name": "格隆汇港股",
                "category": "港股",
                "news_type": "finance"
            },
            
            # ==========================================
            # 国际政治/地缘（跨界）
            # ==========================================
            {
                "url": "http://news.baidu.com/n?cmd=1&class=internews&tn=rss&sub=0",
                "name": "百度国际新闻",
                "category": "国际政治",
                "news_type": "geopolitical"
            },
            
            # ==========================================
            # 科技新闻（跨界）
            # ==========================================
            {
                "url": "{RSSHUB}/36kr/newsflashes",
                "name": "36氪快讯",
                "category": "科技突破",
                "news_type": "tech"
            },
            {
                "url": "http://news.baidu.com/n?cmd=1&class=internet&tn=rss&sub=0",
                "name": "百度科技焦点",
                "category": "科技突破",
                "news_type": "tech"
            },
            {
                "url": "{RSSHUB}/ithome/it",
                "name": "IT之家",
                "category": "科技突破",
                "news_type": "tech"
            },
            
            # ==========================================
            # 社会舆论（跨界）
            # ==========================================
            {
                "url": "http://news.baidu.com/n?cmd=1&class=socianews&tn=rss&sub=0",
                "name": "百度社会新闻",
                "category": "社会舆论",
                "news_type": "social"
            }
        ]
        # Acceptance found these feeds supplied headlines/empty bodies almost
        # exclusively. No body completion path exists for them in this project.
        disabled={name:'headline_only_without_body_reader' for name in
            ('Finviz美股新闻','百度财经焦点','百度股票焦点','百度国际新闻','百度科技焦点','百度社会新闻')}
        disabled['华尔街见闻-股市']='duplicate_of_global_rss_in_acceptance'
        from .source_health import PAUSED_FEEDS
        disabled.update(PAUSED_FEEDS)
        self._disabled_rss_feeds=[dict(feed,disabled_reason=disabled[feed['name']]) for feed in self.rss_feeds if feed['name'] in disabled]
        self.rss_feeds=[feed for feed in self.rss_feeds if feed['name'] not in disabled]
        self._rss_coverage={feed['name']:dict(status='disabled',reason=feed['disabled_reason'])
            for feed in self._disabled_rss_feeds}
        
        # 新闻去重缓存（基于标题哈希）
        self._seen_hashes: set = set()
        
        # 【盘中预采集缓存】
        # 交易日午间采集的新闻会暂存在这里，晚报生成时合并使用
        self._midday_news_cache: List[News] = []
        self._midday_cache_date: Optional[str] = None  # 缓存日期，避免跨日使用过期数据
        
        # 中国相关关键词
        self.china_keywords = [
            "中国", "人民币", "央行", "A股", "沪深", "港股",
            "中美", "贸易", "发改委", "工信部", "财政部",
            "北京", "上海", "深圳", "香港", "内地",
            "国企", "民企", "科创板", "创业板", "北交所"
        ]
        
        # 全球市场关键词（对A股有重大影响的国际市场信息）
        self.global_market_keywords = [
            # 大宗商品
            "原油", "油价", "黄金", "金价", "白银", "铜", "铁矿石",
            "大宗商品", "期货", "现货", "WTI", "布伦特", "OPEC",
            # 外盘指数
            "美股", "纳斯达克", "道琼斯", "标普", "恒指", "恒生",
            "日经", "欧股", "富时",
            # 宏观/央行
            "美联储", "降息", "加息", "利率", "通胀", "CPI",
            "美元", "汇率", "关税", "制裁",
            # 其他影响A股的关键词
            "MSCI", "北向资金", "外资", "离岸",
        ]
        
        # 检查 AKShare 是否可用
        self.akshare_available = False
        try:
            import akshare
            self.akshare_available = True
            print("[OK] NewsCollector: AKShare 可用，将作为补充新闻源")
        except ImportError:
            print("[WARN] NewsCollector: AKShare 不可用")
        
        # 初始化情感分析器
        self.sentiment_analyzer = None
        self.sentiment_analysis_enabled = bool(sentiment)
        if sentiment:
            try:
                from .sentiment_analyzer import get_sentiment_analyzer
                self.sentiment_analyzer = get_sentiment_analyzer()
                print("[OK] NewsCollector: 情感分析服务已启用")
            except Exception as e:
                print(f"[WARN] NewsCollector: 情感分析服务初始化失败: {e}")
    
    async def collect_all(self, hours: int = 24) -> List[News]:
        """
        采集所有来源的新闻
        
        公开新闻、原文雷达及短期历史；停用通道不重探
        
        Args:
            hours: 采集最近多少小时的新闻
            
        Returns:
            去重后的新闻列表
        """
        # 每次采集前清空去重缓存，避免跨次调用（如早报->晚报）时误过滤
        self._seen_hashes.clear()
        self._rss_coverage={feed['name']:dict(status='disabled',reason=feed['disabled_reason'])
            for feed in getattr(self,'_disabled_rss_feeds',[])}
        
        all_news = []
        
        # 1. 并行采集所有 RSS 源
        tasks = [
            self._collect_rss(feed) 
            for feed in self.rss_feeds
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        rss_success_count = 0
        for result in results:
            if isinstance(result, Exception):
                print(f"采集出错: {result}")
                continue
            all_news.extend(result)
            if result:
                rss_success_count += 1
        
        print(f"[RSS] {rss_success_count}/{len(self.rss_feeds)} 个源成功，获取 {len(all_news)} 条新闻")
        
        # 2. 使用 AKShare 采集补充新闻
        if self.akshare_available:
            try:
                akshare_news = await self._collect_akshare_news()
                all_news.extend(akshare_news)
                print(f"[AKShare] 补充 {len(akshare_news)} 条新闻")
            except Exception as e:
                print(f"[AKShare] 新闻采集失败: {e}")
        
        # The server's 20 THS rows all had homepage URLs and unverified times.
        # Do not fetch a known unusable adapter merely to discard every item.
        self._rss_coverage['同花顺快讯']=dict(status='disabled',
            reason='homepage_url_and_unverified_publication_no_automatic_retest')
        
        # 5. 【新增】采集自选股相关新闻（个股 + 行业）
        try:
            watchlist_news = await self._collect_watchlist_news(hours=hours)
            all_news.extend(watchlist_news)
            print(f"[自选股] 相关新闻补充 {len(watchlist_news)} 条")
        except Exception as e:
            print(f"[自选股] 新闻采集失败: {e}")

        # Global coverage must run even when the App watchlist is empty.
        all_news.extend(await self._collect_radar_news(hours))

        retrieved=list(all_news)
        history=[];history_status=dict(status='not_enabled',complete_window=False)
        if getattr(self,'_archive_enabled',False):
            from .material_lifecycle import prune_material_caches
            await asyncio.to_thread(prune_material_caches)
            from .news_archive import NewsArchive,identity
            archive=NewsArchive(getattr(self,'_archive_root',None))
            try:
                await asyncio.to_thread(archive.save,retrieved,dict(rss=self._rss_coverage,
                    media=getattr(self,'_radar_coverage',{})),'full_collection')
                retained,history_status=await asyncio.to_thread(archive.load,hours)
                current={identity(item) for item in retrieved}
                history=[item for item in retained if identity(item) not in current]
                all_news.extend(history)
            except Exception as error:
                history_status=dict(status='failed',error=type(error).__name__,complete_window=False)
                print('[新闻历史库] 失败：'+type(error).__name__+'；本次继续使用现采材料',flush=True)
        from .source_inventory import inventory
        self._source_inventory=inventory(retrieved,history,china_now(),hours,
            {**self._rss_coverage,**getattr(self,"_supplement_coverage",{})},history_status)
        print(f'[采集覆盖] 本次抓取={len(retrieved)}，历史补回={len(history)}；非完整历史，逐源质量已记录',flush=True)

        from .research_hub import ResearchHub, tag_industry_news
        current_stocks = get_watchlist_service().get_all_stocks()
        profiles = [item.get('profile') for item in ResearchHub().load(current_stocks)]
        tag_industry_news(all_news, profiles)

        # Filter before deduplication: an old high-score copy must not displace
        # a current report. Future-dated items cannot become current evidence.
        now = china_now()
        cutoff_time = now - timedelta(hours=hours)
        in_window = [n for n in all_news if within_window(n, now, hours)]
        for item in in_window:
            if item.published_at.tzinfo is not None:
                item.published_at = item.published_at.astimezone(
                    timezone(timedelta(hours=8))).replace(tzinfo=None)
        # The private acceptance snapshot retains the pre-dedup text too, so
        # counts and removed copies can be inspected without another collection.
        self._raw_news_snapshot=list(in_window)
        self._collection_funnel=dict(retrieved=len(retrieved),history_restored=len(history),in_window=len(in_window))
        unique_news = self._deduplicate(in_window)
        self._collection_funnel['after_dedup']=len(unique_news)
        filtered_news = unique_news
        try:
            from .event_observations import EventObservations
            EventObservations().observe(in_window,dict(
                scope='本次RSS及公开媒体采集，非全网',rss_with_items=rss_success_count,
                rss_requested=len(self.rss_feeds),empty_rss_status='unknown',
                media=getattr(self,'_radar_coverage',{})))
        except Exception as error:
            print(f'[事件历史] 写入失败：{type(error).__name__}，传播范围未知',flush=True)
        stocks = get_watchlist_service().get_all_stocks()
        for stock in stocks:
            raw_count = sum(matches_watchlist(n, [stock]) for n in all_news)
            window_count = sum(matches_watchlist(n, [stock]) for n in in_window)
            kept_count = sum(matches_watchlist(n, [stock]) for n in filtered_news)
            print(f"[自选股新闻漏斗] {stock.market}:{stock.code} 原始={raw_count} "
                  f"窗口内={window_count} 去重后={kept_count}")
        
        # 按重要性和时间排序
        filtered_news.sort(key=lambda x: (x.importance_score, x.published_at), reverse=True)
        
        print(f"[NEWS] 共采集到 {len(filtered_news)} 条新闻（原始 {len(all_news)} 条，去重后 {len(unique_news)} 条，时间窗口 {hours}h，cutoff {cutoff_time.strftime('%H:%M')}）")
        
        # 5. 【新增】深度情感分析
        if self.sentiment_analyzer and self.sentiment_analysis_enabled and filtered_news:
            print(f"[SENTIMENT] 开始对 {len(filtered_news)} 条新闻进行深度情感分析...")
            try:
                filtered_news = await self._analyze_sentiment_batch(filtered_news)
                print(f"[SENTIMENT] 情感分析完成")
            except Exception as e:
                print(f"[SENTIMENT] 情感分析失败: {e}")
        
        return filtered_news
    
    async def collect_midday_cache(self, hours: int = 3) -> List[News]:
        """
        盘中预采集（交易日午间调用）
        
        采集上午开盘到午休期间的新闻和雪球讨论，
        缓存在内存中，供晚报合并使用。
        
        Args:
            hours: 采集最近几小时的新闻（默认3小时，覆盖9:30-11:30）
            
        Returns:
            采集到的新闻列表（同时缓存在 _midday_news_cache 中）
        """
        from datetime import date as date_type
        
        today_str = china_today().strftime("%Y-%m-%d")
        
        print(f"\n[盘中预采集] 开始采集盘中新闻，时间窗口 {hours}h...")
        
        # 执行常规新闻采集
        all_news = await self.collect_all(hours=hours)
        
        # 更新缓存
        self._midday_news_cache = all_news
        self._midday_cache_date = today_str
        
        print(f"[盘中预采集] 完成，缓存 {len(all_news)} 条盘中新闻（日期: {today_str}）")
        
        return all_news
    
    def get_midday_cache(self) -> List[News]:
        """
        获取盘中预采集的缓存新闻
        
        只有当天的缓存才有效，过期数据会被清空。
        
        Returns:
            缓存的盘中新闻列表（可能为空）
        """
        from datetime import date as date_type
        
        today_str = china_today().strftime("%Y-%m-%d")
        
        if self._midday_cache_date != today_str:
            # 缓存不是今天的，清空
            if self._midday_news_cache:
                print(f"[盘中缓存] 缓存日期 {self._midday_cache_date} 非今日，清空")
            self._midday_news_cache = []
            self._midday_cache_date = None
            return []
        
        print(f"[盘中缓存] 返回今日 {len(self._midday_news_cache)} 条盘中缓存新闻")
        return self._midday_news_cache
    
    def merge_with_midday_cache(self, evening_news: List[News]) -> List[News]:
        """
        将盘后新闻与盘中预采集缓存合并去重
        
        盘中新闻 + 盘后新闻 → 去重后的完整新闻列表
        确保盘中的新闻不会因为被下午新闻冲掉而丢失。
        
        Args:
            evening_news: 盘后采集的新闻列表
            
        Returns:
            合并去重后的完整新闻列表
        """
        midday_news = self.get_midday_cache()
        
        if not midday_news:
            print("[新闻合并] 无盘中缓存，使用盘后新闻")
            return evening_news
        
        # 合并：盘后新闻优先（更新），盘中新闻补充
        combined = list(evening_news)  # 先放入盘后新闻
        
        # 构建已有标题的标准化列表（用于相似度比较）
        import hashlib
        existing_hashes = set()
        existing_norm_titles = []
        for news in combined:
            title_hash = hashlib.md5(news.title.encode()).hexdigest()
            existing_hashes.add(title_hash)
            existing_norm_titles.append(self._normalize_title(news.title))
        
        # 从盘中缓存中补充不重复的新闻（MD5 + 相似度双重检查）
        added_count = 0
        for news in midday_news:
            title_hash = hashlib.md5(news.title.encode()).hexdigest()
            if title_hash in existing_hashes:
                continue
            
            # 相似度检查
            norm_title = self._normalize_title(news.title)
            is_dup = False
            for existing_norm in existing_norm_titles:
                if self._title_similarity(norm_title, existing_norm) > 0.7:
                    is_dup = True
                    break
            
            if not is_dup:
                existing_hashes.add(title_hash)
                existing_norm_titles.append(norm_title)
                combined.append(news)
                added_count += 1
        
        # 按重要性和时间重新排序
        combined.sort(key=lambda x: (x.importance_score, x.published_at), reverse=True)
        
        print(f"[新闻合并] 盘后 {len(evening_news)} + 盘中补充 {added_count} = 合计 {len(combined)} 条")
        
        return combined

    
    
    
    async def _collect_10jqka_news(self) -> List[News]:
        """Retired: homepage links and fallback collection timestamps are not news evidence."""
        return []

    async def _collect_watchlist_news(self, hours: int = 24) -> List[News]:
        """
        采集自选股相关新闻
        
        1. 针对每只自选股搜索个股新闻
        2. 针对自选股所属行业搜索板块新闻（行业去重）
        """
        news_list = []
        
        # 获取自选股服务
        watchlist_service = get_watchlist_service()
        
        db_stocks = await self._load_db_watchlist()
        watchlist_service.load_from_config("")
        watchlist_service.load_from_database(db_stocks)

        all_stocks = watchlist_service.get_all_stocks()
        unique_sectors = watchlist_service.get_unique_sectors()
        
        if not all_stocks:
            print("  [自选股] 未设置自选股，跳过采集")
            return news_list

        print(f"  [自选股] 共 {len(all_stocks)} 只股票，涉及 {len(unique_sectors)} 个行业")
        
        # Issuer disclosures are independent of the general article search index.
        from .watchlist_sources import fetch_company_announcements, fetch_sina_stock_news
        semaphore = asyncio.Semaphore(3)
        async def collect_disclosures(stock):
            async with semaphore:
                try:
                    items, status = await asyncio.to_thread(fetch_company_announcements, stock, hours=hours)
                    print(f'[自选股公告] {stock.market}:{stock.code} {status}', flush=True)
                    return items
                except Exception as error:
                    print(f'[自选股公告] {stock.market}:{stock.code} 请求失败：{type(error).__name__}', flush=True)
                    return []
        for items in await asyncio.gather(*(collect_disclosures(stock) for stock in all_stocks)):
            news_list.extend(items)

        async def collect_sina(stock):
            async with semaphore:
                try:
                    items, status = await asyncio.to_thread(fetch_sina_stock_news, stock, hours=hours)
                    print(f'[自选股新闻-新浪] {stock.market}:{stock.code} {status}', flush=True)
                    return items
                except Exception as error:
                    print(f'[自选股新闻-新浪] {stock.market}:{stock.code} 请求失败：{type(error).__name__}', flush=True)
                    return []
        for items in await asyncio.gather(*(collect_sina(stock) for stock in all_stocks)):
            news_list.extend(items)

        # 1. 采集个股新闻（使用 AKShare）
        if self.akshare_available:
            covered = {code for item in news_list if within_window(item, china_now(), hours)
                       for code in item.related_stocks}
            uncovered = [stock for stock in all_stocks if stock.code not in covered]
            stock_news = await self._collect_individual_stock_news(uncovered) if uncovered else []
            print(f'[自选股搜索] 已有近期原文覆盖{len(all_stocks)-len(uncovered)}只，'
                  f'旧搜索接口仅补缺{len(uncovered)}只', flush=True)
            news_list.extend(stock_news)
            print(f"  [自选股] 个股新闻: {len(stock_news)} 条")
        
        # Current issuer news is fetched before slower background document work.
        # Refresh dynamic business profiles before expanding industry news queries.
        from .research_hub import ResearchHub
        try:
            research = await ResearchHub().collect(all_stocks, budget=110)
            profiles = {item['key']:item['profile'] for item in research['stocks'] if item.get('profile')}
            watchlist_service.apply_research_profiles(profiles)
            unique_sectors = watchlist_service.get_unique_sectors()
            for item in research['stocks']:
                print(f'[研究覆盖] {item["key"]} {item["coverage"]}', flush=True)
        except Exception as error:
            print(f'[研究覆盖] 采集失败：{type(error).__name__}；不能解释为没有资料', flush=True)

        # 2. 采集行业新闻（行业去重）
        if self.akshare_available and unique_sectors:
            sector_news = await self._collect_sector_news(unique_sectors)
            news_list.extend(sector_news)
            print(f"  [自选股] 行业新闻: {len(sector_news)} 条")
        
        return news_list
    
    async def _collect_radar_news(self,hours=24):
        from .media_sources import MediaCollector
        from .policy_sources import PolicyCollector
        from .technical_radar import TechnicalRadar
        from .research_hub import ResearchHub
        from .wechat_sources import WeChatCollector
        from .public_news_sources import PublicNewsCollector
        from .overseas_sources import OverseasCollector
        from .microstructure import MicrostructureRadar
        service=get_watchlist_service()
        try:
            rows=await self._load_db_watchlist()
            service.load_from_config('')
            service.load_from_database(rows)
            stocks=service.get_all_stocks()
        except Exception as error:
            stocks=[]
            print(f'[全市场雷达] App自选股读取失败：{type(error).__name__}；仅收集全市场',flush=True)
        profiles={item['key']:item['profile'] for item in ResearchHub().load(stocks) if item.get('profile')}
        media,technical,policy,wechat,direct,overseas,microstructure=await asyncio.gather(
            asyncio.to_thread(MediaCollector().collect,stocks,profiles,hours),
            asyncio.to_thread(TechnicalRadar().collect,stocks),
            asyncio.to_thread(PolicyCollector().collect,hours),
            asyncio.to_thread(WeChatCollector().collect,stocks,profiles,hours),
            asyncio.to_thread(PublicNewsCollector().collect,stocks,profiles,hours),
            asyncio.to_thread(OverseasCollector().collect,hours),
            asyncio.to_thread(MicrostructureRadar().collect,stocks),return_exceptions=True)
        self._microstructure_snapshot=(dict(status='failed',error=type(microstructure).__name__)
            if isinstance(microstructure,Exception) else microstructure)
        if isinstance(technical,Exception):
            self._technical_snapshot=dict(status='failed',error=type(technical).__name__)
            print(f'[日线雷达] 失败：{type(technical).__name__}；禁止补写技术数据',flush=True)
        else:
            self._technical_snapshot=technical
            print(f'[日线雷达] {technical["coverage"]}；行业ETF代理不是全市场宽度',flush=True)
        if isinstance(media,Exception):
            self._radar_coverage=dict(status='failed',error=type(media).__name__)
            print(f'[媒体原文] {self._radar_coverage}',flush=True)
            items=[]
        else:
            items,self._radar_coverage=media
        if isinstance(policy,Exception):
            self._radar_coverage.setdefault('sources',{})['policy']=dict(status='failed',read=0,errors=[dict(error=type(policy).__name__)])
        else:
            originals,policy_coverage=policy
            items.extend(originals)
            self._radar_coverage.setdefault('sources',{}).update(policy_coverage['sources'])
            self._radar_coverage['policy_articles']=len(originals)
        if isinstance(wechat,Exception):
            self._radar_coverage.setdefault('sources',{})['wechat']=dict(status='failed',read=0,
                errors=[dict(error=type(wechat).__name__)])
        else:
            originals,wechat_status=wechat
            items.extend(originals)
            self._radar_coverage.setdefault('sources',{})['wechat']=wechat_status
        if isinstance(direct,Exception):
            self._radar_coverage.setdefault('sources',{})['direct_publishers']=dict(status='failed',read=0,
                errors=[dict(error=type(direct).__name__)])
        else:
            originals,direct_status=direct
            items.extend(originals)
            self._radar_coverage.setdefault('sources',{}).update(direct_status['sources'])
            self._radar_coverage['direct_publishers']=direct_status
        if isinstance(overseas,Exception):
            self._radar_coverage.setdefault('sources',{})['overseas']=dict(status='failed',read=0,
                errors=[dict(error=type(overseas).__name__)])
        else:
            originals,overseas_status=overseas
            items.extend(originals)
            self._radar_coverage.setdefault('sources',{}).update({'overseas_'+key:value for key,value in overseas_status['sources'].items()})
            self._radar_coverage['overseas']=overseas_status
        self._radar_coverage['total_originals']=len(items)
        source_rows=list(self._radar_coverage.get('sources',{}).values())
        incomplete=any(row.get('status') in {'failed','partial','paused'} for row in source_rows) or isinstance(media,Exception)
        self._radar_coverage['status']='partial' if incomplete and items else 'failed' if incomplete else 'ok' if items else 'no_material'
        summary={name:dict(status=row.get('status'),read=row.get('read'),errors=len(row.get('errors',[])),
                          paused_routes=len(row.get('paused_routes',[])))
            for name,row in self._radar_coverage.get('sources',{}).items()}
        print(f'[媒体原文] 合计={len(items)}；逐源摘要={summary}；完整候选与错误保存在验收快照',flush=True)
        return sorted(items,key=lambda item:(item.importance_score,item.published_at),reverse=True)

    async def _load_db_watchlist(self) -> List[Dict]:
        """
        从数据库加载自选股列表
        
        Returns:
            [{"code": "xxx", "name": "xxx", "market": "A"}, ...]
        """
        return await read_app_watchlist()

    async def _collect_individual_stock_news(self, stocks: List[WatchlistStock]) -> List[News]:
        """
        采集个股新闻（走全局限流器）
        """
        import akshare as ak
        from .market_data_service import _akshare_rate_limiter
        
        news_list = []
        
        for stock in stocks[:10]:
            try:
                code = stock.code
                if stock.market == "A":
                    full_code = f"{code}"
                else:
                    full_code = code
                
                try:
                    await _akshare_rate_limiter.acquire()
                    loop = asyncio.get_event_loop()
                    df = await asyncio.wait_for(
                        loop.run_in_executor(None, lambda c=full_code: ak.stock_news_em(symbol=c)),
                        timeout=30
                    )
                    if df is not None and not df.empty:
                        print(f'[个股新闻索引] {stock.code} 返回{len(df)}条；'
                              f'最新发布时间={df["发布时间"].astype(str).max()}；当前窗口另行校验', flush=True)
                        # The provider's row order is not a freshness guarantee.
                        df = df.sort_values("发布时间", ascending=False)
                        for _, row in df.head(5).iterrows():
                            title = str(row.get('新闻标题', ''))
                            content = str(row.get('新闻内容', title))
                            
                            if not title:
                                continue
                            
                            # 解析时间
                            try:
                                time_str = str(row.get('发布时间', ''))
                                if time_str:
                                    published = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                                else:
                                    continue
                            except (ValueError, TypeError):
                                continue
                            
                            news_list.append(News(
                                id=str(uuid.uuid4()),
                                title=f"[{stock.name}] {title}",
                                content=content,
                                summary=content[:200] if len(content) > 200 else content,
                                source=f"东方财富-{stock.name}",
                                source_url=str(row.get('新闻链接', 'https://www.eastmoney.com')),
                                published_at=published,
                                news_type=NewsType.FINANCE,
                                sentiment=SentimentType.NEUTRAL,
                                importance_score=0.75,  # 自选股相关新闻权重较高
                                is_china_related=True,
                                category=f"自选股-{stock.name}",
                                related_stocks=[stock.code]
                            ))
                except Exception as e:
                    print(f"    [个股新闻] {stock.name}({stock.code}) 采集失败: {e}")
                
                # 避免请求过快
                await asyncio.sleep(0.5)
                
            except Exception as e:
                print(f"    [个股新闻] {stock.name} 异常: {e}")
        
        return news_list
    
    async def _collect_sector_news(self, sectors: List[str]) -> List[News]:
        # Sector quotes are market data, not news. Industry evidence now comes
        # from dated articles and industry research in ResearchHub.
        print('[行业新闻] 已停用板块涨跌幅拼接新闻；采用真实文章及行业研报', flush=True)
        return []

    @staticmethod
    def _get_xueqiu_symbol(stock) -> str:
        """构造雪球股票代码"""
        if stock.market == "A":
            return f"SH{stock.code}" if stock.code.startswith("6") else f"SZ{stock.code}"
        return stock.code
    
    
    async def _collect_akshare_news(self) -> List[News]:
        """Retired supplement adapters: no article URL or verified source time.

        The observed EM response contained 30 empty bodies. The old CCTV
        adapter also supplied a homepage URL and collection time as publication.
        Keep issuer filings and research adapters; these are separate paths.
        """
        self._supplement_coverage={
            '东方财富':dict(status='disabled',reason='empty_body_homepage_url_and_unverified_publication'),
            '央视新闻':dict(status='disabled',reason='homepage_url_and_unverified_publication')}
        print('[补充入口] 停用旧东方财富/央视适配器：缺少合格正文链接或来源时间；不发送请求',flush=True)
        return []

    def _resolve_rss_url(self, url: str, node: str = None) -> str:
        """将 {RSSHUB} 占位符替换为实际的 RSSHub 节点地址"""
        if "{RSSHUB}" in url:
            return url.replace("{RSSHUB}", node or self._current_rsshub_node)
        return url
    
    async def _collect_rss(self, feed_config: Dict[str, str]) -> List[News]:
        """
        采集单个 RSS 源
        
        对于 RSSHub 源，如果主节点失败，自动切换到备用节点
        """
        news_list = []
        url_template = feed_config["url"]
        last_error = None
        if not hasattr(self,'_rss_coverage'):self._rss_coverage={}
        status=dict(status='pending',feed_entries=0,parsed=0,invalid_entries=0,
            history_pagination=False,reading_scope='feed_excerpt',transport_host=None)
        self._rss_coverage[feed_config['name']]=status
        from .source_health import PAUSED_FEEDS
        if feed_config['name'] in PAUSED_FEEDS:
            status.update(status='disabled',reason=PAUSED_FEEDS[feed_config['name']],automatic_retest=False)
            return []
        state_root=getattr(self,'_rss_state_root',None)
        if state_root:
            from .source_health import ensure_active,RetiredSourceError
            try:ensure_active(state_root,url_template)
            except RetiredSourceError:
                status.update(status='disabled',reason='source_paused_no_automatic_retest',automatic_retest=False)
                return []
        state_path=state_root/(hashlib.sha256(url_template.encode()).hexdigest()+'.json') if state_root else None
        if state_path:
            import json
            try:
                saved=json.loads(state_path.read_text(encoding='utf-8'))
                if china_now()<datetime.fromisoformat(saved['until']):
                    status.update(status='cooldown',retry_after=saved['until'])
                    return []
            except (OSError,ValueError,KeyError,TypeError):pass
        
        # 确定要尝试的 URL 列表
        if "{RSSHUB}" in url_template:
            urls_to_try = [
                self._resolve_rss_url(url_template, node) 
                for node in self._rsshub_nodes
            ]
        else:
            urls_to_try = [url_template]
        
        for url in urls_to_try:
            try:
                response = await self.client.get(url, timeout=15.0)
                response.raise_for_status()
                from urllib.parse import urlsplit
                status['transport_host']=urlsplit(url).hostname
                
                # 解析 RSS
                feed = feedparser.parse(response.text)
                status['feed_entries']=len(feed.entries)
                
                if not feed.entries:
                    status['status']='empty' if feed.get('version') else 'invalid_feed'
                    continue
                
                for entry in feed.entries:
                    try:
                        news = self._parse_rss_entry(entry, feed_config)
                        if news:
                            news_list.append(news)
                        else:status['invalid_entries']+=1
                    except Exception as e:
                        status['invalid_entries']+=1
                        print(f"解析条目失败: {e}")
                        continue
                
                # 成功获取到数据，更新当前可用节点
                if "{RSSHUB}" in url_template:
                    node = url.split("/")[2]
                    if node != self._current_rsshub_node.split("//")[1]:
                        # 切换到成功的节点
                        for n in self._rsshub_nodes:
                            if node in n:
                                self._current_rsshub_node = n
                                break
                
                print(f"[OK] {feed_config['name']}: 获取 {len(news_list)} 条")
                status['parsed']=len(news_list)
                status['status']='partial' if status['invalid_entries'] else 'ok'
                return news_list  # 成功就返回
                
            except Exception as e:
                last_error = e
                status['status']='failed';status['error']=type(e).__name__
                if state_root:
                    from .source_health import record_failure
                    if record_failure(state_root,url_template,e):
                        status.update(status='disabled',reason='source_paused_no_automatic_retest',automatic_retest=False)
                        break
                continue
        
        # 所有节点都失败了
        print(f"[FAIL] {feed_config['name']} 采集失败: {last_error or '未知错误'}")
        if state_path and status['status'] in {'failed','invalid_feed'}:
            from .research_hub import save_json
            until=(china_now()+timedelta(hours=6)).isoformat()
            try:
                save_json(state_path,dict(until=until,error=status.get('error',status['status'])))
                status['retry_after']=until
            except OSError:pass
        
        return news_list
    
    def _parse_rss_entry(self, entry: Any, feed_config: Dict[str, str]) -> Optional[News]:
        """解析 RSS 条目为 News 对象"""
        # 提取标题
        title = entry.get("title", "").strip()
        if not title:
            return None
        
        # 提取内容
        content = ""
        candidates=[getattr(block,'value','') for block in (getattr(entry,'content',None) or [])]
        candidates.extend([getattr(entry,'summary','') or '',getattr(entry,'description','') or ''])
        for candidate in candidates:
            content=self._clean_html(candidate)
            if content:break

        # Keep short actual text (a complete notice can be short). Do not replace
        # it with a headline and later count that headline as supporting content.

        # feedparser parsed timestamps are UTC. Missing dates cannot be treated as today.
        parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
        if not parsed_time:
            return None
        try:
            published_at = datetime(*parsed_time[:6], tzinfo=timezone.utc).astimezone(
                timezone(timedelta(hours=8))).replace(tzinfo=None)
        except (TypeError, ValueError):
            return None

        # 提取链接
        source_url = entry.get("link", "")
        
        # 创建新闻对象
        news_id = str(uuid.uuid4())
        
        # 获取新闻类型
        news_type_str = feed_config.get("news_type", "finance")
        news_type = NewsType(news_type_str) if news_type_str in [e.value for e in NewsType] else NewsType.FINANCE
        
        # 计算重要性评分（跨界新闻可能有更高的权重如果对市场有重大影响）
        importance_score = self._calculate_importance(title, content, news_type)
        
        # 提取关键词
        keywords = self._extract_keywords(title + " " + content)
        
        # 提取关联股票
        related_stocks = self._extract_stock_codes(title + " " + content)
        
        # 识别受影响板块（仅跨界新闻）
        beneficiary_sectors, affected_sectors = [], []
        if news_type != NewsType.FINANCE:
            beneficiary_sectors, affected_sectors = self._analyze_sector_impact(title, content, news_type)
        
        return News(
            id=news_id,
            title=title,
            content=content,
            summary=content[:200] if len(content) > 200 else content,
            source=feed_config["name"],
            source_url=source_url,
            published_at=published_at,
            sentiment=SentimentType.NEUTRAL,  # 后续由 AI 分析
            importance_score=importance_score,
            keywords=keywords,
            related_stocks=related_stocks,
            news_type=news_type,
            category=feed_config.get("category"),
            beneficiary_sectors=beneficiary_sectors,
            affected_sectors=affected_sectors,
            created_at=china_now()
        )
    
    def _clean_html(self, text: str) -> str:
        """清理 HTML 标签"""
        if not text:
            return ""
        
        # 使用 BeautifulSoup 提取纯文本
        soup = BeautifulSoup(text, "lxml")
        text = soup.get_text(separator=" ")
        
        # 清理多余空白
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        return text
    
    def _calculate_importance(self, title: str, content: str, news_type: NewsType = NewsType.FINANCE) -> float:
        """计算新闻重要性评分"""
        score = 0.5  # 基础分
        
        combined_text = title + " " + content
        
        # 中国相关加分
        for keyword in self.china_keywords:
            if keyword in combined_text:
                score += 0.1
        
        # 重要信号词加分（财经类）
        important_words = ["重磅", "突发", "暴跌", "暴涨", "央行", "降息", "加息", "政策", "监管"]
        for word in important_words:
            if word in combined_text:
                score += 0.15
        
        # 🆕 大宗商品/外盘/宏观关键词加分
        commodity_words = [
            "油价", "原油", "黄金", "白银", "金价", "大宗商品", "期货",
            "OPEC", "WTI", "布伦特", "铁矿石", "铜价",
        ]
        for word in commodity_words:
            if word in combined_text:
                score += 0.15
        
        global_market_words = [
            "美股", "纳斯达克", "道琼斯", "标普", "恒生", "恒指",
            "美联储", "降息", "加息", "通胀", "CPI", "非农",
            "美元", "汇率", "关税", "制裁",
        ]
        for word in global_market_words:
            if word in combined_text:
                score += 0.12
        
        # 跨界新闻特殊加分
        if news_type == NewsType.GEOPOLITICAL:
            # 地缘政治关键词
            geo_keywords = ["战争", "制裁", "冲突", "外交", "关税", "禁令", "协议", "谈判", "紧张"]
            for word in geo_keywords:
                if word in combined_text:
                    score += 0.2
                    
        elif news_type == NewsType.TECH:
            # 科技突破关键词
            tech_keywords = ["突破", "首发", "发布", "AI", "芯片", "新能源", "ChatGPT", "量子", "自动驾驶"]
            for word in tech_keywords:
                if word in combined_text:
                    score += 0.15
                    
        elif news_type == NewsType.SOCIAL:
            # 社会舆论关键词（可能影响上市公司）
            social_keywords = ["代言", "翻车", "塌房", "丑闻", "道歉", "下架", "停播", "热搜", "暴雷"]
            for word in social_keywords:
                if word in combined_text:
                    score += 0.2
                    
        elif news_type == NewsType.DISASTER:
            # 自然灾害关键词
            disaster_keywords = ["地震", "台风", "洪水", "暴雨", "干旱", "极端天气", "停工", "供应链"]
            for word in disaster_keywords:
                if word in combined_text:
                    score += 0.2
        
        # 限制在 0-1 范围
        return min(1.0, max(0.0, score))
    
    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词"""
        # 简单实现：提取常见财经关键词
        finance_keywords = [
            "股市", "基金", "债券", "利率", "汇率", "通胀", "GDP",
            "科技", "新能源", "消费", "医药", "金融", "地产",
            "并购", "IPO", "减持", "增持", "回购", "分红"
        ]
        
        found = []
        for kw in finance_keywords:
            if kw in text:
                found.append(kw)
        
        return found[:10]  # 最多返回10个
    
    def _extract_stock_codes(self, text: str) -> List[str]:
        """提取股票代码"""
        codes = []
        
        # A股代码模式：6位数字
        a_share_pattern = r'\b(00[0-3]\d{3}|30[0-2]\d{3}|60[0-3]\d{3}|68[89]\d{3})\b'
        codes.extend(re.findall(a_share_pattern, text))
        
        # 港股代码模式：4-5位数字
        hk_pattern = r'\b(0[0-9]{4})\b'
        codes.extend(re.findall(hk_pattern, text))
        
        return list(set(codes))[:10]  # 去重，最多10个
    
    def _analyze_sector_impact(self, title: str, content: str, news_type: NewsType) -> tuple:
        """
        分析跨界新闻对板块的影响
        
        Returns:
            (受益板块列表, 受损板块列表)
        """
        combined_text = title + " " + content
        beneficiaries = []
        affected = []
        
        if news_type == NewsType.GEOPOLITICAL:
            # 地缘政治影响
            if any(w in combined_text for w in ["战争", "冲突", "紧张", "制裁"]):
                beneficiaries.extend(["军工", "黄金", "石油", "能源"])
                affected.extend(["航空", "旅游", "出口"])
            if any(w in combined_text for w in ["贸易", "关税", "禁令"]):
                if "中美" in combined_text:
                    beneficiaries.extend(["国产替代", "半导体", "软件"])
                    affected.extend(["出口", "跨国企业"])
                    
        elif news_type == NewsType.TECH:
            # 科技突破影响
            if any(w in combined_text for w in ["AI", "人工智能", "ChatGPT", "大模型"]):
                beneficiaries.extend(["AI算力", "芯片", "云计算", "软件"])
            if any(w in combined_text for w in ["新能源", "电动车", "光伏", "储能"]):
                beneficiaries.extend(["新能源", "锂电池", "光伏"])
            if any(w in combined_text for w in ["芯片", "半导体", "光刻机"]):
                beneficiaries.extend(["半导体", "芯片设备"])
                
        elif news_type == NewsType.SOCIAL:
            # 社会舆论影响（品牌危机）
            if any(w in combined_text for w in ["代言", "翻车", "塌房", "丑闻"]):
                # 这类新闻通常影响特定公司，而非整个板块
                affected.extend(["相关上市公司"])
            if any(w in combined_text for w in ["食品安全", "质量问题"]):
                affected.extend(["食品饮料", "消费"])
                
        elif news_type == NewsType.DISASTER:
            # 自然灾害影响
            if any(w in combined_text for w in ["地震", "台风", "洪水"]):
                beneficiaries.extend(["建材", "基建", "灾后重建"])
                affected.extend(["保险", "农业", "当地企业"])
            if any(w in combined_text for w in ["干旱", "极端天气"]):
                affected.extend(["农业", "水电"])
                beneficiaries.extend(["火电", "节水"])
            if any(w in combined_text for w in ["停工", "供应链", "停产"]):
                affected.extend(["制造业", "汽车"])
        
        return list(set(beneficiaries)), list(set(affected))
    
    @staticmethod
    def _normalize_title(title: str) -> str:
        """
        标准化标题：去除来源前缀、标点、空白，统一小写
        例如 "[张三] 标题..." -> "张三标题"
        """
        import re
        # 去掉 [...] 开头的来源前缀（如 [雪球用户] [公司名]）
        text = re.sub(r'^\[.*?\]\s*', '', title)
        # 去除所有标点符号和空白
        text = re.sub(r'[^\w\u4e00-\u9fff]', '', text)
        return text.lower()
    
    @staticmethod
    def _title_similarity(a: str, b: str) -> float:
        """
        计算两个标准化标题的 Jaccard 字符级相似度
        比编辑距离更快，适合大批量去重
        """
        if not a or not b:
            return 0.0
        # 使用字符 bigram（二元组）做 Jaccard 相似度
        def bigrams(s):
            return set(s[i:i+2] for i in range(len(s) - 1)) if len(s) > 1 else {s}
        set_a = bigrams(a)
        set_b = bigrams(b)
        if not set_a or not set_b:
            return 1.0 if a == b else 0.0
        intersection = set_a & set_b
        union = set_a | set_b
        return len(intersection) / len(union)
    
    def _deduplicate(self, news_list: List[News]) -> List[News]:
        """
        智能新闻去重（MD5 精确 + Jaccard 相似度双重去重）
        
        第一层：MD5 哈希精确匹配（零成本过滤完全相同标题）
        第二层：标准化后的 Jaccard bigram 相似度 > 0.7 视为重复
                保留重要性评分更高的那条
        """
        from .evidence_audit import copy_reason,retain_distinct_full_bodies
        unique = []
        # 用于相似度比较的标准化标题列表
        normalized_titles = []
        
        dup_exact = 0
        dup_similar = 0
        seen_hashes = set()
        stocks = get_watchlist_service().get_all_stocks()
        def priority(item):
            from .news_quality import priority as evidence_priority
            return (article_url(item.source_url),evidence_priority(item)[0],matches_watchlist(item, stocks),
                    item.importance_score, item.published_at)

        for news in sorted(news_list, key=priority, reverse=True):
            if any(copy_reason(news,existing) for existing in unique):
                dup_exact += 1
                continue
            # 第一层：MD5 精确去重
            title_hash = hashlib.md5(news.title.encode()).hexdigest()
            if title_hash in seen_hashes and not any(
                    existing.title==news.title and retain_distinct_full_bodies(news,existing)
                    for existing in unique):
                dup_exact += 1
                continue
            
            # 第二层：相似度去重
            norm_title = self._normalize_title(news.title)
            is_duplicate = False
            
            for i, existing_norm in enumerate(normalized_titles):
                sim = self._title_similarity(norm_title, existing_norm)
                if sim > 0.7:
                    if retain_distinct_full_bodies(news,unique[i]):
                        continue
                    # Similar headlines about different watched companies are
                    # separate evidence and must not be collapsed into one.
                    new_stocks = {s.code for s in stocks if matches_watchlist(news, [s])}
                    old_stocks = {s.code for s in stocks if matches_watchlist(unique[i], [s])}
                    if new_stocks and old_stocks and new_stocks.isdisjoint(old_stocks):
                        continue
                    # 相似度超过阈值，保留重要性更高的
                    if priority(news) > priority(unique[i]):
                        # 新的更重要，替换旧的
                        old_hash = hashlib.md5(unique[i].title.encode()).hexdigest()
                        seen_hashes.discard(old_hash)
                        seen_hashes.add(title_hash)
                        unique[i] = news
                        normalized_titles[i] = norm_title
                    is_duplicate = True
                    dup_similar += 1
                    break
            
            if not is_duplicate:
                seen_hashes.add(title_hash)
                unique.append(news)
                normalized_titles.append(norm_title)
        
        if dup_exact or dup_similar:
            print(f"[去重] 精确重复 {dup_exact} 条，相似重复 {dup_similar} 条，保留 {len(unique)} 条")
        
        return unique
    
    def filter_china_related(self, news_list: List[News], min_score: float = 0.3) -> List[News]:
        """
        筛选中国相关及对A股有影响的新闻
        
        v2 修复版：
        - 来自国内财经源的新闻直接放行（不做关键词过滤，避免误杀）
        - 其他来源的新闻仍需包含中国/全球市场关键词
        - 降低 min_score 默认值到 0.3（之前 0.5 太严格）
        - 扩大关键词覆盖面
        """
        # 国内财经源白名单——来自这些源的新闻一定是中国相关的，不需要关键词过滤
        domestic_sources = {
            "财联社电报", "财联社深度", "金十数据", "东方财富研报",
            "百度财经焦点", "百度股票焦点", "格隆汇7x24快讯",
            "东方财富", "同花顺快讯", "央视新闻",
            "华尔街见闻-股市", "格隆汇港股", "香港经济日报", "信报财经新闻",
        }
        # 自选股/雪球/行业板块来源也直接放行
        domestic_source_keywords = ["自选股", "雪球", "行业板块", "东方财富-"]
        
        # 扩展的关键词列表（补充更多常见财经用语）
        extended_china_keywords = self.china_keywords + [
            "涨停", "跌停", "板块", "龙头", "主力", "散户",
            "融资", "融券", "基金", "ETF", "公募", "私募",
            "IPO", "减持", "增持", "回购", "分红", "业绩",
            "营收", "净利润", "同比", "环比", "预告", "快报",
            "监管", "证监会", "银保监", "国务院", "两会",
            "光伏", "新能源", "半导体", "芯片", "AI", "人工智能",
            "白酒", "医药", "银行", "保险", "证券", "地产",
            "涨幅", "跌幅", "成交", "放量", "缩量",
            "沪指", "深成指", "创业板", "科创", "北证",
            "券商", "研报", "评级", "目标价",
        ]
        
        filtered_news = []
        bypass_count = 0
        keyword_match_count = 0
        
        for news in news_list:
            source = news.source or ""
            if ('全市场事件入口' in (news.market_impact or '') and article_url(news.source_url)
                    and news.importance_score>=min_score):
                filtered_news.append(news)
                bypass_count+=1
                continue
            
            # 规则1：国内财经源白名单直接放行
            is_domestic = source in domestic_sources
            if not is_domestic:
                is_domestic = any(kw in source for kw in domestic_source_keywords)
            
            if is_domestic and news.importance_score >= min_score:
                filtered_news.append(news)
                bypass_count += 1
                continue
            
            # 规则2：其他来源需要关键词匹配
            text = news.title + " " + news.content
            
            is_china_related = any(kw in text for kw in extended_china_keywords)
            is_global_market = any(kw in text for kw in self.global_market_keywords)
            
            if (is_china_related or is_global_market) and news.importance_score >= min_score:
                filtered_news.append(news)
                keyword_match_count += 1
        
        print(f"   [filter_china_related] 白名单放行 {bypass_count} + 关键词匹配 {keyword_match_count} = 共 {len(filtered_news)} 条（原始 {len(news_list)} 条）")
        
        return filtered_news
    
    def filter_cross_border_news(self, news_list: List[News], min_score: float = 0.6) -> List[News]:
        """
        筛选跨界新闻（非财经但对股市有影响）
        
        Args:
            news_list: 新闻列表
            min_score: 最低重要性评分阈值（跨界新闻门槛更高）
            
        Returns:
            筛选后的跨界新闻列表
        """
        cross_border_news = []
        stocks=get_watchlist_service().get_all_stocks()
        macro_events=('美联储','央行','关税','出口管制','制裁','原油','天然气','航运','海峡','战争','停产','供应链中断')
        
        for news in news_list:
            # 只选取非财经类新闻
            if news.news_type != NewsType.FINANCE and news.importance_score >= min_score:
                text=news.title+' '+(news.content or '')
                if (matches_watchlist(news,stocks) or '行业关联 ' in (news.market_impact or '')
                        or any(term in text for term in macro_events)):
                    cross_border_news.append(news)
        
        # 按类型分组，每类最多取5条
        result = []
        type_counts = {}
        
        for news in sorted(cross_border_news, key=lambda x: x.importance_score, reverse=True):
            type_key = news.news_type.value
            if type_counts.get(type_key, 0) < 5:
                result.append(news)
                type_counts[type_key] = type_counts.get(type_key, 0) + 1
        
        return result[:6]
    
    def get_news_by_type(self, news_list: List[News]) -> Dict[str, List[News]]:
        """
        按类型分组新闻
        
        Returns:
            {'finance': [...], 'geopolitical': [...], 'tech': [...], 'social': [...], 'disaster': [...]}
        """
        grouped = {
            'finance': [],
            'geopolitical': [],
            'tech': [],
            'social': [],
            'disaster': []
        }
        
        for news in news_list:
            type_key = news.news_type.value
            if type_key in grouped:
                grouped[type_key].append(news)
        
        return grouped
    
    async def close(self):
        """关闭 HTTP 客户端"""
        await self.client.aclose()
    
    async def _analyze_sentiment_batch(self, news_list: List[News]) -> List[News]:
        """
        批量进行深度情感分析
        
        使用 FinBERT 或规则引擎对新闻进行情感分析，
        并将结果更新到新闻对象中
        """
        if not self.sentiment_analyzer:
            return news_list
        
        # 批量分析
        analyzed = await self.sentiment_analyzer.analyze_batch(news_list)
        
        # 更新新闻对象
        updated_news = []
        sentiment_stats = {"positive": 0, "negative": 0, "neutral": 0}
        
        for news, result in analyzed:
            # 更新情感字段
            news.sentiment = result.sentiment
            news.sentiment_confidence = result.confidence
            news.sentiment_strength = SentimentStrength(result.strength.value)
            news.sentiment_scores = result.scores
            news.sentiment_keywords_positive = result.keywords_positive
            news.sentiment_keywords_negative = result.keywords_negative
            news.sentiment_analysis_method = result.analysis_method
            
            # 统计
            sentiment_stats[result.sentiment.value] += 1
            
            updated_news.append(news)
        
        # 打印统计信息
        total = len(updated_news)
        print(f"  [情感分析统计] 正面: {sentiment_stats['positive']} ({sentiment_stats['positive']/total*100:.1f}%) | "
              f"负面: {sentiment_stats['negative']} ({sentiment_stats['negative']/total*100:.1f}%) | "
              f"中性: {sentiment_stats['neutral']} ({sentiment_stats['neutral']/total*100:.1f}%)")
        
        return updated_news
    
    def get_market_sentiment_index(self, news_list: List[News]):
        """
        获取市场情绪指数
        
        Returns:
            MarketSentimentIndex 对象，包含整体市场情绪分析
        """
        if not self.sentiment_analyzer:
            return None
        
        # 构建 (news, result) 对
        analyzed_pairs = []
        for news in news_list:
            if news.sentiment_analysis_method != "pending":
                from .sentiment_analyzer import SentimentResult, SentimentStrength as SST
                result = SentimentResult(
                    sentiment=news.sentiment,
                    confidence=news.sentiment_confidence,
                    strength=SST(news.sentiment_strength.value),
                    scores=news.sentiment_scores or {},
                    keywords_positive=news.sentiment_keywords_positive,
                    keywords_negative=news.sentiment_keywords_negative,
                    analysis_method=news.sentiment_analysis_method
                )
                analyzed_pairs.append((news, result))
        
        if not analyzed_pairs:
            return None
        
        return self.sentiment_analyzer.calculate_market_sentiment_index(analyzed_pairs)
    


# 单例实例
_collector_instance: Optional[NewsCollectorService] = None


def get_news_collector() -> NewsCollectorService:
    """获取新闻采集服务实例"""
    global _collector_instance
    if _collector_instance is None:
        _collector_instance = NewsCollectorService()
    return _collector_instance

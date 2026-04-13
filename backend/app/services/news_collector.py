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
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
import uuid

import feedparser
import httpx
from bs4 import BeautifulSoup

from ..config import settings
from ..models.news import News, NewsCreate, SentimentType, NewsType, SentimentStrength
from .watchlist_service import get_watchlist_service, WatchlistStock


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
    
    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )
        
        # RSSHub 备用节点（主节点挂掉时自动切换）
        self._rsshub_nodes = [
            "https://rsshub.rssforever.com",
            "https://rsshub.pseudoyu.com",
        ]
        self._current_rsshub_node = self._rsshub_nodes[0]
        
        # RSS 源配置
        # url 中包含 {RSSHUB} 占位符的会自动替换为当前可用的 RSSHub 节点
        self.rss_feeds = [
            # ==========================================
            # 财经类新闻（国内 — 核心信源）
            # ==========================================
            {
                "url": "{RSSHUB}/cls/telegraph",
                "name": "财联社电报",
                "category": "快讯",
                "news_type": "finance"
            },
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
            {
                "url": "{RSSHUB}/cls/depth/1000",
                "name": "财联社深度",
                "category": "深度分析",
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
                "name": "香港经济日报",
                "category": "港股",
                "news_type": "finance"
            },
            {
                "url": "{RSSHUB}/gelonghui/subject/3",
                "name": "格隆汇港股",
                "category": "港股",
                "news_type": "finance"
            },
            {
                "url": "{RSSHUB}/nikkei/index",
                "name": "日经新闻",
                "category": "日股",
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
        self.sentiment_analysis_enabled = True
        try:
            from .sentiment_analyzer import get_sentiment_analyzer
            self.sentiment_analyzer = get_sentiment_analyzer()
            print("[OK] NewsCollector: 情感分析服务已启用")
        except Exception as e:
            print(f"[WARN] NewsCollector: 情感分析服务初始化失败: {e}")
    
    async def collect_all(self, hours: int = 24) -> List[News]:
        """
        采集所有来源的新闻
        
        增强版：RSS + AKShare + 雪球API 三数据源
        
        Args:
            hours: 采集最近多少小时的新闻
            
        Returns:
            去重后的新闻列表
        """
        # 每次采集前清空去重缓存，避免跨次调用（如早报->晚报）时误过滤
        self._seen_hashes.clear()
        
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
        
        # 3. 【新增】直接爬取雪球热帖（投资者观点/小道消息）
        try:
            xueqiu_news = await self._collect_xueqiu_hot()
            all_news.extend(xueqiu_news)
            print(f"[雪球] 热帖补充 {len(xueqiu_news)} 条")
        except Exception as e:
            print(f"[雪球] 热帖采集失败: {e}")
        
        # 4. 【新增】采集同花顺快讯
        try:
            ths_news = await self._collect_10jqka_news()
            all_news.extend(ths_news)
            print(f"[同花顺] 快讯补充 {len(ths_news)} 条")
        except Exception as e:
            print(f"[同花顺] 快讯采集失败: {e}")
        
        # 5. 【新增】采集自选股相关新闻（个股 + 行业）
        try:
            watchlist_news = await self._collect_watchlist_news()
            all_news.extend(watchlist_news)
            print(f"[自选股] 相关新闻补充 {len(watchlist_news)} 条")
        except Exception as e:
            print(f"[自选股] 新闻采集失败: {e}")
        
        # 去重
        unique_news = self._deduplicate(all_news)
        
        # 过滤时间范围
        cutoff_time = datetime.now() - timedelta(hours=hours)
        filtered_news = [
            n for n in unique_news 
            if n.published_at >= cutoff_time
        ]
        
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
        
        today_str = date_type.today().strftime("%Y-%m-%d")
        
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
        
        today_str = date_type.today().strftime("%Y-%m-%d")
        
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

    async def _collect_xueqiu_hot(self) -> List[News]:
        """
        采集雪球热帖（投资者观点/小道消息）
        
        策略：优先使用 RSSHub 雪球源（稳定），失败再回退直接 API
        """
        # 方案 A：通过 RSSHub 获取雪球热帖（推荐，不被 WAF 拦截）
        rsshub_urls = [
            "https://rsshub.rssforever.com/xueqiu/hots",
            "https://rsshub.pseudoyu.com/xueqiu/hots",
        ]
        
        for rsshub_url in rsshub_urls:
            try:
                news_list = await self._collect_xueqiu_via_rsshub(rsshub_url)
                if news_list:
                    print(f"  [雪球] RSSHub 获取热帖 {len(news_list)} 条（{rsshub_url}）")
                    return news_list
            except Exception as e:
                print(f"  [雪球] RSSHub 源失败 ({rsshub_url}): {e}")
        
        # 方案 B：直接 API（加强反爬）
        try:
            news_list = await self._collect_xueqiu_hot_direct()
            if news_list:
                print(f"  [雪球] 直接 API 获取热帖 {len(news_list)} 条")
                return news_list
        except Exception as e:
            print(f"  [雪球] 直接 API 失败: {e}")
        
        print("  [雪球] 所有方式均失败，跳过")
        return []
    
    async def _collect_xueqiu_via_rsshub(self, rsshub_url: str) -> List[News]:
        """通过 RSSHub 获取雪球热帖"""
        news_list = []
        
        feed_response = await self.client.get(rsshub_url, timeout=15.0)
        if feed_response.status_code != 200:
            return news_list
        
        feed = feedparser.parse(feed_response.text)
        
        for entry in feed.entries[:20]:
            title = entry.get("title", "")
            content = entry.get("summary", entry.get("description", ""))
            
            # 清理 HTML
            content = self._clean_html(content) if content else ""
            
            if not title:
                continue
            
            # 解析时间
            try:
                published = datetime(*entry.published_parsed[:6]) if hasattr(entry, 'published_parsed') and entry.published_parsed else datetime.now()
            except:
                published = datetime.now()
            
            news_list.append(News(
                id=str(uuid.uuid4()),
                title=title,
                content=content[:1000],
                summary=content[:200] if content else title,
                source="雪球热帖",
                source_url=entry.get("link", "https://xueqiu.com"),
                published_at=published,
                news_type=NewsType.FINANCE,
                sentiment=SentimentType.NEUTRAL,
                importance_score=0.7,
                is_china_related=True,
                category="投资者观点"
            ))
        
        return news_list
    
    async def _collect_xueqiu_hot_direct(self) -> List[News]:
        """
        直接爬取雪球热帖（备用方案，加强反爬）
        """
        news_list = []
        
        try:
            # 雪球热门话题 API（加强 headers 模拟真实浏览器）
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Referer": "https://xueqiu.com/",
                "Origin": "https://xueqiu.com",
                "X-Requested-With": "XMLHttpRequest",
            }
            
            # 先访问首页获取 cookie（关键！）
            try:
                home_resp = await self.client.get("https://xueqiu.com/", headers={
                    "User-Agent": headers["User-Agent"],
                    "Accept": "text/html,application/xhtml+xml",
                })
                # 小延迟模拟真人行为
                await asyncio.sleep(0.5)
            except:
                pass
            
            # 热门帖子 API
            hot_url = "https://xueqiu.com/statuses/hot/listV2.json?since_id=-1&max_id=-1&size=30"
            response = await self.client.get(hot_url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                items = data.get("data", {}).get("items", [])
                
                for item in items[:20]:
                    original = item.get("original_status", item)
                    title = original.get("title", "")
                    text = original.get("text", "")
                    
                    # 清理 HTML
                    text = self._clean_html(text)
                    
                    if not title:
                        title = text[:50] + "..." if len(text) > 50 else text
                    
                    # 用户信息
                    user = original.get("user", {})
                    author = user.get("screen_name", "雪球用户")
                    
                    news_list.append(News(
                        id=str(uuid.uuid4()),
                        title=f"[{author}] {title}",
                        content=text[:1000],
                        summary=text[:200],
                        source="雪球热帖",
                        source_url=f"https://xueqiu.com/{user.get('id', '')}/post/{original.get('id', '')}",
                        published_at=datetime.fromtimestamp(original.get("created_at", 0) / 1000) if original.get("created_at") else datetime.now(),
                        news_type=NewsType.FINANCE,
                        sentiment=SentimentType.NEUTRAL,
                        importance_score=0.7,  # 社区观点权重适中
                        is_china_related=True,
                        category="投资者观点"
                    ))
                
                print(f"  [雪球] 获取热帖 {len(news_list)} 条")
        except Exception as e:
            print(f"  [雪球] 热帖采集失败: {e}")
        
        return news_list
    
    async def _collect_10jqka_news(self) -> List[News]:
        """
        采集同花顺24小时滚动快讯
        
        同花顺是国内主流炒股软件，其快讯非常及时
        """
        news_list = []
        
        try:
            # 同花顺快讯页面
            url = "https://news.10jqka.com.cn/tapp/news/push/stock/"
            response = await self.client.get(url)
            
            if response.status_code == 200:
                data = response.json()
                items = data.get("data", {}).get("list", [])
                
                for item in items[:30]:
                    title = item.get("title", "")
                    digest = item.get("digest", "")
                    ctime = item.get("ctime", "")
                    
                    if not title:
                        continue
                    
                    # 解析时间
                    try:
                        published = datetime.strptime(ctime, "%Y-%m-%d %H:%M:%S")
                    except:
                        published = datetime.now()
                    
                    news_list.append(News(
                        id=str(uuid.uuid4()),
                        title=title,
                        content=digest or title,
                        summary=digest[:200] if digest else title,
                        source="同花顺快讯",
                        source_url=f"https://news.10jqka.com.cn/",
                        published_at=published,
                        news_type=NewsType.FINANCE,
                        sentiment=SentimentType.NEUTRAL,
                        importance_score=0.65,
                        is_china_related=True,
                        category="股票快讯"
                    ))
        except Exception as e:
            print(f"  [同花顺] 快讯采集失败: {e}")
        
        return news_list
    
    async def _collect_watchlist_news(self) -> List[News]:
        """
        采集自选股相关新闻
        
        1. 针对每只自选股搜索个股新闻
        2. 针对自选股所属行业搜索板块新闻（行业去重）
        """
        news_list = []
        
        # 获取自选股服务
        watchlist_service = get_watchlist_service()
        
        # 从配置加载自选股
        watchlist_service.load_from_config(settings.watchlist_stocks)
        
        # 尝试从数据库加载自选股
        try:
            db_stocks = await self._load_db_watchlist()
            if db_stocks:
                watchlist_service.load_from_database(db_stocks)
                print(f"  [自选股] 从数据库加载了 {len(db_stocks)} 只股票")
        except Exception as e:
            print(f"  [自选股] 数据库加载失败: {e}")
        
        all_stocks = watchlist_service.get_all_stocks()
        unique_sectors = watchlist_service.get_unique_sectors()
        
        if not all_stocks:
            print("  [自选股] 未设置自选股，跳过采集")
            return news_list
        
        print(f"  [自选股] 共 {len(all_stocks)} 只股票，涉及 {len(unique_sectors)} 个行业")
        
        # 1. 采集个股新闻（使用 AKShare）
        if self.akshare_available:
            stock_news = await self._collect_individual_stock_news(all_stocks)
            news_list.extend(stock_news)
            print(f"  [自选股] 个股新闻: {len(stock_news)} 条")
        
        # 2. 采集行业新闻（行业去重）
        if self.akshare_available and unique_sectors:
            sector_news = await self._collect_sector_news(unique_sectors)
            news_list.extend(sector_news)
            print(f"  [自选股] 行业新闻: {len(sector_news)} 条")
        
        # 3. 采集雪球个股讨论
        xueqiu_news = await self._collect_xueqiu_stock_discussion(all_stocks)
        news_list.extend(xueqiu_news)
        if xueqiu_news:
            print(f"  [自选股] 雪球讨论: {len(xueqiu_news)} 条")
        
        return news_list
    
    async def _load_db_watchlist(self) -> List[Dict]:
        """
        从数据库加载自选股列表
        
        Returns:
            [{"code": "xxx", "name": "xxx", "market": "A"}, ...]
        """
        db_stocks = []
        
        try:
            # 尝试直接读取 SQLite 数据库
            import aiosqlite
            from pathlib import Path
            
            db_path = Path(settings.database_url.replace("sqlite:///", ""))
            if not db_path.exists():
                return db_stocks
            
            async with aiosqlite.connect(str(db_path)) as db:
                async with db.execute("SELECT code, name, market FROM stocks") as cursor:
                    rows = await cursor.fetchall()
                    for row in rows:
                        db_stocks.append({
                            "code": row[0],
                            "name": row[1],
                            "market": row[2]
                        })
        except Exception as e:
            print(f"  [自选股] 读取数据库失败: {e}")
        
        return db_stocks
    
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
                        for _, row in df.head(5).iterrows():  # 每只股票最多5条
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
                                    published = datetime.now()
                            except:
                                published = datetime.now()
                            
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
        """
        采集行业板块新闻（走全局限流器）
        """
        import akshare as ak
        from .market_data_service import _akshare_rate_limiter
        
        news_list = []
        
        # 行业板块名称映射
        sector_name_map = {
            "白酒": "白酒",
            "新能源": "新能源汽车",
            "光伏": "光伏设备",
            "半导体": "半导体",
            "消费电子": "消费电子",
            "医药": "医药生物",
            "银行": "银行",
            "保险": "保险",
            "证券": "证券",
            "地产": "房地产",
            "互联网": "互联网服务",
            "汽车": "汽车整车",
            "家电": "家用电器",
            "食品饮料": "食品饮料",
            "军工": "国防军工",
            "煤炭": "煤炭开采",
            "钢铁": "钢铁行业",
            "石油化工": "石油行业",
            "电力": "电力行业",
            "AI软件": "软件开发",
        }
        
        # 一次性获取概念板块数据（走限流器），而不是每个行业调一次
        df = None
        try:
            await _akshare_rate_limiter.acquire()
            loop = asyncio.get_event_loop()
            df = await asyncio.wait_for(
                loop.run_in_executor(None, ak.stock_board_concept_name_em),
                timeout=30
            )
        except Exception as e:
            print(f"    [板块新闻] 获取概念板块失败: {e}")
            return news_list
        
        if df is None or df.empty:
            return news_list
        
        for sector in sectors:
            try:
                sector_name = sector_name_map.get(sector, sector)
                
                for _, row in df.iterrows():
                    board_name = str(row.get('板块名称', ''))
                    if sector in board_name or sector_name in board_name:
                        change = row.get('涨跌幅', 0)
                        leader_stock = str(row.get('领涨股票', ''))
                        
                        news_list.append(News(
                            id=str(uuid.uuid4()),
                            title=f"[{sector}板块] 今日涨跌幅 {change}%，领涨股 {leader_stock}",
                            content=f"{sector}板块今日涨跌幅为{change}%，领涨股票为{leader_stock}。板块整体表现{'强势' if float(change) > 1 else '弱势' if float(change) < -1 else '平稳'}。",
                            summary=f"{sector}板块涨跌幅{change}%",
                            source=f"东方财富-{sector}板块",
                            source_url="https://data.eastmoney.com/bkzj/BK0493.html",
                            published_at=datetime.now(),
                            news_type=NewsType.FINANCE,
                            sentiment=SentimentType.POSITIVE if float(change) > 0 else SentimentType.NEGATIVE if float(change) < 0 else SentimentType.NEUTRAL,
                            importance_score=0.7,
                            is_china_related=True,
                            category=f"行业板块-{sector}",
                            beneficiary_sectors=[sector] if float(change) > 0 else [],
                            affected_sectors=[sector] if float(change) < 0 else []
                        ))
                        break
                        
            except Exception as e:
                print(f"    [板块新闻] {sector} 异常: {e}")
        
        return news_list
    
    async def _collect_xueqiu_stock_discussion(self, stocks: List[WatchlistStock]) -> List[News]:
        """
        采集雪球个股讨论
        
        雪球是投资者社区，可以获取市场观点和小道消息。
        先尝试 RSSHub 源，失败回退直接 API。
        """
        news_list = []
        
        # 方案 A：通过 RSSHub 获取个股讨论
        for stock in stocks[:5]:
            xq_symbol = self._get_xueqiu_symbol(stock)
            rsshub_urls = [
                f"https://rsshub.rssforever.com/xueqiu/stock_comments/{xq_symbol}",
                f"https://rsshub.pseudoyu.com/xueqiu/stock_comments/{xq_symbol}",
            ]
            
            fetched = False
            for rsshub_url in rsshub_urls:
                try:
                    resp = await self.client.get(rsshub_url, timeout=10.0)
                    if resp.status_code == 200:
                        feed = feedparser.parse(resp.text)
                        for entry in feed.entries[:3]:
                            title = entry.get("title", "")
                            content = entry.get("summary", entry.get("description", ""))
                            content = self._clean_html(content) if content else ""
                            
                            if not title or len(title) < 10:
                                continue
                            
                            try:
                                published = datetime(*entry.published_parsed[:6]) if hasattr(entry, 'published_parsed') and entry.published_parsed else datetime.now()
                            except:
                                published = datetime.now()
                            
                            news_list.append(News(
                                id=str(uuid.uuid4()),
                                title=f"[{stock.name}] {title}",
                                content=content[:1000],
                                summary=content[:200] if content else title,
                                source=f"雪球-{stock.name}",
                                source_url=entry.get("link", f"https://xueqiu.com/S/{xq_symbol}"),
                                published_at=published,
                                news_type=NewsType.FINANCE,
                                sentiment=SentimentType.NEUTRAL,
                                importance_score=0.65,
                                is_china_related=True,
                                category=f"雪球讨论-{stock.name}",
                                related_stocks=[stock.code]
                            ))
                        fetched = True
                        break
                except Exception as e:
                    pass
            
            if not fetched:
                # 方案 B：直接 API 获取
                try:
                    direct_news = await self._collect_xueqiu_stock_direct(stock)
                    news_list.extend(direct_news)
                except:
                    pass
            
            await asyncio.sleep(0.3)
        
        if news_list:
            print(f"  [雪球] 个股讨论共 {len(news_list)} 条")
        return news_list
    
    @staticmethod
    def _get_xueqiu_symbol(stock) -> str:
        """构造雪球股票代码"""
        if stock.market == "A":
            return f"SH{stock.code}" if stock.code.startswith("6") else f"SZ{stock.code}"
        return stock.code
    
    async def _collect_xueqiu_stock_direct(self, stock) -> List[News]:
        """直接 API 获取单只股票的雪球讨论（备用）"""
        news_list = []
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://xueqiu.com/",
            "Origin": "https://xueqiu.com",
        }
        
        try:
            # 先获取 cookie
            await self.client.get("https://xueqiu.com/", headers={
                "User-Agent": headers["User-Agent"],
                "Accept": "text/html",
            })
            await asyncio.sleep(0.3)
            
            xq_symbol = self._get_xueqiu_symbol(stock)
            
            # 获取个股讨论
            url = f"https://xueqiu.com/query/v1/symbol/search/status.json?symbol={xq_symbol}&count=10&page=1"
            
            response = await self.client.get(url, headers=headers)
            if response.status_code == 200:
                # 防止返回 HTML 而非 JSON
                content_type = response.headers.get("content-type", "")
                if "json" not in content_type and "text/html" in content_type:
                    return news_list
                
                data = response.json()
                items = data.get("list", [])
                
                for item in items[:3]:
                    text = item.get("text", "")
                    text = self._clean_html(text)
                    
                    if len(text) < 20:
                        continue
                    
                    user = item.get("user", {})
                    author = user.get("screen_name", "雪球用户")
                    followers = user.get("followers_count", 0)
                    
                    importance = 0.65 if followers > 10000 else 0.55
                    title = text[:50] + "..." if len(text) > 50 else text
                    
                    news_list.append(News(
                        id=str(uuid.uuid4()),
                        title=f"[{stock.name}] {author}: {title}",
                        content=text[:1000],
                        summary=text[:200],
                        source=f"雪球-{stock.name}",
                        source_url=f"https://xueqiu.com/{user.get('id', '')}/post/{item.get('id', '')}",
                        published_at=datetime.fromtimestamp(item.get("created_at", 0) / 1000) if item.get("created_at") else datetime.now(),
                        news_type=NewsType.FINANCE,
                        sentiment=SentimentType.NEUTRAL,
                        importance_score=importance,
                        is_china_related=True,
                        category=f"雪球讨论-{stock.name}",
                        related_stocks=[stock.code]
                    ))
        except Exception as e:
            print(f"    [雪球] {stock.name} 直接API讨论采集失败: {e}")
        
        return news_list
    
    async def _collect_akshare_news(self) -> List[News]:
        """
        使用 AKShare 采集财经新闻
        
        AKShare 提供的新闻接口比 RSS 更稳定，可作为主要数据源的补充。
        所有调用走全局限流器，避免被东方财富封IP。
        """
        import akshare as ak
        from .market_data_service import _akshare_rate_limiter
        
        news_list = []
        
        try:
            # 1. 采集东方财富快讯（股票相关新闻）
            try:
                await _akshare_rate_limiter.acquire()
                loop = asyncio.get_event_loop()
                df = await asyncio.wait_for(
                    loop.run_in_executor(None, ak.stock_info_global_em),
                    timeout=30
                )
                if df is not None and not df.empty:
                    for _, row in df.head(30).iterrows():
                        news_list.append(News(
                            id=str(uuid.uuid4()),
                            title=str(row.get('标题', row.get('内容', '')[:50])),
                            content=str(row.get('内容', '')),
                            source="东方财富",
                            source_url="https://www.eastmoney.com",
                            published_at=datetime.now(),
                            news_type=NewsType.FINANCE,
                            sentiment=SentimentType.NEUTRAL,
                            importance_score=0.6,
                            is_china_related=True
                        ))
                    print(f"  [AKShare] 全球财经快讯: {len(news_list)} 条")
            except Exception as e:
                print(f"  [AKShare] 全球财经快讯采集失败: {e}")
            
            await asyncio.sleep(2)  # 接口间隔
            
            # 2. 采集 CCTV 新闻（央视财经相关）
            try:
                await _akshare_rate_limiter.acquire()
                loop = asyncio.get_event_loop()
                df_cctv = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: ak.news_cctv(date=datetime.now().strftime("%Y%m%d"))),
                    timeout=30
                )
                if df_cctv is not None and not df_cctv.empty:
                    finance_keywords = ["经济", "金融", "股市", "央行", "货币", "贸易", "GDP", "通胀", "利率"]
                    for _, row in df_cctv.iterrows():
                        title = str(row.get('title', ''))
                        if any(kw in title for kw in finance_keywords):
                            news_list.append(News(
                                id=str(uuid.uuid4()),
                                title=title,
                                content=str(row.get('content', title)),
                                source="央视新闻",
                                source_url="https://www.cctv.com",
                                published_at=datetime.now(),
                                news_type=NewsType.FINANCE,
                                sentiment=SentimentType.NEUTRAL,
                                importance_score=0.8,
                                is_china_related=True
                            ))
                    print(f"  [AKShare] 央视财经新闻: 筛选到 {sum(1 for n in news_list if n.source == '央视新闻')} 条")
            except Exception as e:
                print(f"  [AKShare] 央视新闻采集失败: {e}")
                
        except Exception as e:
            print(f"[AKShare] 新闻采集总体失败: {e}")
        
        return news_list
    
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
                
                # 解析 RSS
                feed = feedparser.parse(response.text)
                
                if not feed.entries:
                    continue
                
                for entry in feed.entries:
                    try:
                        news = self._parse_rss_entry(entry, feed_config)
                        if news:
                            news_list.append(news)
                    except Exception as e:
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
                return news_list  # 成功就返回
                
            except Exception as e:
                last_error = e
                continue
        
        # 所有节点都失败了
        print(f"[FAIL] {feed_config['name']} 采集失败: {last_error or '未知错误'}")
        
        return news_list
    
    def _parse_rss_entry(self, entry: Any, feed_config: Dict[str, str]) -> Optional[News]:
        """解析 RSS 条目为 News 对象"""
        # 提取标题
        title = entry.get("title", "").strip()
        if not title:
            return None
        
        # 提取内容
        content = ""
        if hasattr(entry, "content"):
            content = entry.content[0].value if entry.content else ""
        elif hasattr(entry, "summary"):
            content = entry.summary or ""
        elif hasattr(entry, "description"):
            content = entry.description or ""
        
        # 清理 HTML 标签
        content = self._clean_html(content)
        
        # 如果内容太短，用标题作为内容
        if len(content) < 50:
            content = title
        
        # 解析发布时间
        published_at = datetime.now()
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                published_at = datetime(*entry.published_parsed[:6])
            except:
                pass
        elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
            try:
                published_at = datetime(*entry.updated_parsed[:6])
            except:
                pass
        
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
            created_at=datetime.now()
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
        unique = []
        # 用于相似度比较的标准化标题列表
        normalized_titles = []
        
        dup_exact = 0
        dup_similar = 0
        
        for news in news_list:
            # 第一层：MD5 精确去重
            title_hash = hashlib.md5(news.title.encode()).hexdigest()
            if title_hash in self._seen_hashes:
                dup_exact += 1
                continue
            
            # 第二层：相似度去重
            norm_title = self._normalize_title(news.title)
            is_duplicate = False
            
            for i, existing_norm in enumerate(normalized_titles):
                sim = self._title_similarity(norm_title, existing_norm)
                if sim > 0.7:
                    # 相似度超过阈值，保留重要性更高的
                    if news.importance_score > unique[i].importance_score:
                        # 新的更重要，替换旧的
                        old_hash = hashlib.md5(unique[i].title.encode()).hexdigest()
                        self._seen_hashes.discard(old_hash)
                        self._seen_hashes.add(title_hash)
                        unique[i] = news
                        normalized_titles[i] = norm_title
                    is_duplicate = True
                    dup_similar += 1
                    break
            
            if not is_duplicate:
                self._seen_hashes.add(title_hash)
                unique.append(news)
                normalized_titles.append(norm_title)
        
        if dup_exact or dup_similar:
            print(f"[去重] 精确重复 {dup_exact} 条，相似重复 {dup_similar} 条，保留 {len(unique)} 条")
        
        return unique
    
    def filter_china_related(self, news_list: List[News], min_score: float = 0.5) -> List[News]:
        """
        筛选中国相关及对A股有影响的新闻
        
        扩展版：不仅筛选包含中国关键词的新闻，
        也包含大宗商品、外盘、宏观经济等对A股有重大影响的国际新闻
        """
        filtered_news = []
        
        for news in news_list:
            text = news.title + " " + news.content
            
            # 检查是否包含中国相关关键词
            is_china_related = any(kw in text for kw in self.china_keywords)
            
            # 检查是否包含全球市场关键词（对A股有影响）
            is_global_market = any(kw in text for kw in self.global_market_keywords)
            
            if (is_china_related or is_global_market) and news.importance_score >= min_score:
                filtered_news.append(news)
        
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
        
        for news in news_list:
            # 只选取非财经类新闻
            if news.news_type != NewsType.FINANCE and news.importance_score >= min_score:
                cross_border_news.append(news)
        
        # 按类型分组，每类最多取5条
        result = []
        type_counts = {}
        
        for news in sorted(cross_border_news, key=lambda x: x.importance_score, reverse=True):
            type_key = news.news_type.value
            if type_counts.get(type_key, 0) < 5:
                result.append(news)
                type_counts[type_key] = type_counts.get(type_key, 0) + 1
        
        return result
    
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

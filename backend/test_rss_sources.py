"""
测试所有RSS源的可用性
"""
import asyncio
import httpx
import feedparser
from datetime import datetime
import sys
import io

# 修复Windows编码
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# RSS源列表（从news_collector.py复制）
rss_feeds = [
    # 国内财经
    {"url": "http://rss.xinhuanet.com/rss/fortune.xml", "name": "新华网财经"},
    {"url": "https://rsshub.rssforever.com/cls/telegraph", "name": "财联社电报"},
    {"url": "https://rsshub.rssforever.com/jin10/flash", "name": "金十数据"},
    {"url": "https://rsshub.rssforever.com/eastmoney/report/strategyreport", "name": "东方财富研报"},
    {"url": "http://news.baidu.com/n?cmd=1&class=finannews&tn=rss&sub=0", "name": "百度财经焦点"},
    {"url": "http://news.baidu.com/n?cmd=1&class=stock&tn=rss&sub=0", "name": "百度股票焦点"},
    
    # 雪球
    {"url": "https://rsshub.rssforever.com/xueqiu/today", "name": "雪球今日话题"},
    {"url": "https://rsshub.rssforever.com/xueqiu/hots", "name": "雪球热帖"},
    {"url": "https://rsshub.app/xueqiu/today", "name": "雪球今日话题(备用)"},
    
    # 国际财经
    {"url": "https://rsshub.rssforever.com/wallstreetcn/news/global", "name": "华尔街见闻-全球"},
    {"url": "https://rsshub.rssforever.com/ft/chinese/hotstoryby7day", "name": "FT中文网热门"},
    {"url": "https://rsshub.rssforever.com/bloomberg", "name": "彭博社"},
    {"url": "https://rsshub.rssforever.com/reuters/category/business", "name": "路透社商业"},
    {"url": "https://rsshub.rssforever.com/wsj", "name": "华尔街日报"},
    {"url": "https://rsshub.rssforever.com/cnbc/rss", "name": "CNBC"},
    {"url": "https://rsshub.rssforever.com/economist", "name": "经济学人"},
    
    # 美股
    {"url": "https://rsshub.rssforever.com/finviz/news", "name": "Finviz美股新闻"},
    {"url": "https://rsshub.rssforever.com/investing/news/stock-market-news", "name": "Investing美股"},
    {"url": "https://rsshub.rssforever.com/federalreserve/newsevents", "name": "美联储动态"},
    
    # 港股
    {"url": "https://rsshub.rssforever.com/hkej/index", "name": "香港经济日报"},
    {"url": "https://rsshub.rssforever.com/aastocks/news", "name": "AASTOCKS港股"},
    
    # 日本
    {"url": "https://rsshub.rssforever.com/nikkei/index", "name": "日经新闻"},
    
    # 国际政治
    {"url": "http://rss.xinhuanet.com/rss/world.xml", "name": "新华网国际"},
    {"url": "http://news.baidu.com/n?cmd=1&class=internews&tn=rss&sub=0", "name": "百度国际新闻"},
    {"url": "https://rsshub.rssforever.com/reuters/world", "name": "路透社国际"},
    {"url": "https://rsshub.rssforever.com/bbc/world", "name": "BBC国际"},
    {"url": "https://rsshub.rssforever.com/cnn/world", "name": "CNN国际"},
    
    # 科技
    {"url": "http://rss.xinhuanet.com/rss/tech.xml", "name": "新华网科技"},
    {"url": "https://rsshub.rssforever.com/36kr/newsflashes", "name": "36氪快讯"},
    {"url": "http://news.baidu.com/n?cmd=1&class=internet&tn=rss&sub=0", "name": "百度科技焦点"},
    {"url": "https://rsshub.rssforever.com/ithome/it", "name": "IT之家"},
    {"url": "https://rsshub.rssforever.com/techcrunch", "name": "TechCrunch"},
    {"url": "https://rsshub.rssforever.com/theverge", "name": "The Verge"},
    
    # 社会舆论
    {"url": "https://rsshub.rssforever.com/weibo/hot", "name": "微博热搜"},
    {"url": "http://news.baidu.com/n?cmd=1&class=socianews&tn=rss&sub=0", "name": "百度社会新闻"},
    {"url": "https://rsshub.rssforever.com/zhihu/hot", "name": "知乎热榜"},
    {"url": "https://rsshub.rssforever.com/toutiao/hot", "name": "今日头条热榜"},
    
    # 灾害
    {"url": "https://rsshub.rssforever.com/cma/warning", "name": "气象预警"},
    {"url": "https://rsshub.rssforever.com/earthquake/latest", "name": "地震速报"},
]


async def test_single_feed(client, feed):
    """测试单个RSS源"""
    try:
        response = await client.get(feed["url"], timeout=15.0)
        if response.status_code == 200:
            parsed = feedparser.parse(response.text)
            count = len(parsed.entries)
            if count > 0:
                # 获取最新一条的标题
                latest_title = parsed.entries[0].get("title", "无标题")[:40]
                return {"status": "OK", "count": count, "latest": latest_title}
            else:
                return {"status": "EMPTY", "count": 0, "latest": ""}
        else:
            return {"status": f"HTTP {response.status_code}", "count": 0, "latest": ""}
    except Exception as e:
        return {"status": f"ERROR: {str(e)[:30]}", "count": 0, "latest": ""}


async def main():
    print(f"开始测试 {len(rss_feeds)} 个RSS源...")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    
    async with httpx.AsyncClient(
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    ) as client:
        # 并发测试所有源
        tasks = [test_single_feed(client, feed) for feed in rss_feeds]
        results = await asyncio.gather(*tasks)
    
    # 统计结果
    ok_count = 0
    empty_count = 0
    error_count = 0
    
    print(f"\n{'序号':<4} {'状态':<8} {'条数':<6} {'名称':<20} {'最新标题'}")
    print("-" * 80)
    
    for i, (feed, result) in enumerate(zip(rss_feeds, results), 1):
        status = result["status"]
        count = result["count"]
        latest = result["latest"]
        
        if status == "OK":
            ok_count += 1
            status_icon = "[OK]"
        elif status == "EMPTY":
            empty_count += 1
            status_icon = "[空]"
        else:
            error_count += 1
            status_icon = "[X]"
        
        print(f"{i:<4} {status_icon:<8} {count:<6} {feed['name']:<20} {latest}")
    
    print("=" * 80)
    print(f"\n统计结果:")
    print(f"  - 成功且有数据: {ok_count}")
    print(f"  - 成功但无数据: {empty_count}")
    print(f"  - 失败: {error_count}")
    print(f"  - 成功率: {ok_count}/{len(rss_feeds)} ({ok_count*100//len(rss_feeds)}%)")


if __name__ == "__main__":
    asyncio.run(main())

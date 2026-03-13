import sys
sys.path.insert(0, '.')

try:
    from app.services.news_collector import get_news_collector
    print("Import OK!")
    
    collector = get_news_collector()
    print(f"RSS源数量: {len(collector.rss_feeds)}")
    print(f"AKShare可用: {collector.akshare_available}")
    
    # 列出所有新闻源
    print("\n=== 新闻源列表 ===")
    for i, feed in enumerate(collector.rss_feeds, 1):
        print(f"{i}. [{feed['news_type']}] {feed['name']}")
        
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

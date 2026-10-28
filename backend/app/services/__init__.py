"""
业务服务模块
"""
from importlib import import_module

_EXPORTS = {
    'NewsCollectorService': 'news_collector',
    'AIAnalyzerService': 'ai_analyzer',
    'PodcastGeneratorService': 'podcast_generator',
    'StockDataService': 'stock_service',
    'SchedulerService': 'scheduler',
}


def __getattr__(name):
    """Pure diagnostics must not initialize audio/config/scheduling services."""
    if name not in _EXPORTS:
        raise AttributeError(name)
    value = getattr(import_module('.'+_EXPORTS[name], __name__), name)
    globals()[name] = value
    return value

__all__ = [
    "NewsCollectorService",
    "AIAnalyzerService", 
    "PodcastGeneratorService",
    "StockDataService",
    "SchedulerService",
]

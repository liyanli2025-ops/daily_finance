"""Read the same stocks table the App edits; never substitute a stale cache."""
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from ..config import settings
from ..models.database import StockModel, get_database_url
from .watchlist_service import get_watchlist_service


async def read_app_watchlist(database_url=None):
    url = database_url or settings.database_url
    parsed = make_url(url)
    if parsed.drivername.startswith("sqlite") and parsed.database != ":memory:":
        if not parsed.database or not Path(parsed.database).is_file():
            raise RuntimeError("App数据库不存在，不能确认当前自选股")
    engine = create_async_engine(get_database_url(url))
    try:
        async with engine.connect() as connection:
            result = await connection.execute(select(
                StockModel.code, StockModel.name, StockModel.market
            ).order_by(StockModel.market, StockModel.code))
            rows = [dict(row) for row in result.mappings()]
        for row in rows:
            if row["market"] not in {"A", "HK"}:
                raise ValueError("Unsupported App watchlist market")
        return rows
    except Exception:
        raise RuntimeError("App自选股读取失败，停止使用缓存标的") from None
    finally:
        await engine.dispose()


async def refresh_app_watchlist():
    rows = await read_app_watchlist()
    service = get_watchlist_service()
    # The App is authoritative, including when the user deletes the last stock.
    service.load_from_config("")
    service.load_from_database(rows)
    from .research_hub import ResearchHub
    contexts = ResearchHub().load(service.get_all_stocks())
    service.apply_research_profiles({item['key']:item['profile'] for item in contexts if item.get('profile')})
    return service

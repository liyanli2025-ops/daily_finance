"""
股票相关 API 路由
"""
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
import uuid

from ..models.stock import (
    Stock, StockCreate, StockPrediction, StockQuote, 
    KlineData, MarketType, PredictionType
)
from ..models.database import StockModel, StockPredictionModel
from ..services.watchlist_service import get_watchlist_service, WatchlistStock
from ..services.market_data_service import get_market_data_service
from ..config import settings

router = APIRouter()


async def get_db(request: Request) -> AsyncSession:
    """获取数据库会话"""
    async with request.app.state.session_maker() as session:
        yield session


@router.get("/watchlist", response_model=List[Stock])
async def get_watchlist(db: AsyncSession = Depends(get_db)):
    """
    获取自选股列表
    """
    query = select(StockModel).order_by(StockModel.added_at)
    result = await db.execute(query)
    stocks = result.scalars().all()
    
    return [
        Stock(
            id=s.id,
            code=s.code,
            name=s.name,
            market=MarketType(s.market),
            current_price=s.current_price,
            change_percent=s.change_percent,
            latest_prediction=PredictionType(s.latest_prediction) if s.latest_prediction else None,
            latest_confidence=s.latest_confidence,
            added_at=s.added_at,
            last_updated=s.last_updated
        )
        for s in stocks
    ]


@router.post("/watchlist", response_model=Stock)
async def add_to_watchlist(
    stock_data: StockCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    添加自选股
    """
    # 检查是否已存在
    existing_query = select(StockModel).where(
        StockModel.code == stock_data.code,
        StockModel.market == stock_data.market.value
    )
    existing = await db.execute(existing_query)
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该股票已在自选列表中")
    
    stock = StockModel(
        id=str(uuid.uuid4()),
        code=stock_data.code,
        name=stock_data.name,
        market=stock_data.market.value,
        added_at=datetime.now()
    )
    
    db.add(stock)
    await db.commit()
    await db.refresh(stock)
    
    return Stock(
        id=stock.id,
        code=stock.code,
        name=stock.name,
        market=MarketType(stock.market),
        current_price=stock.current_price,
        change_percent=stock.change_percent,
        latest_prediction=PredictionType(stock.latest_prediction) if stock.latest_prediction else None,
        latest_confidence=stock.latest_confidence,
        added_at=stock.added_at,
        last_updated=stock.last_updated
    )


@router.delete("/watchlist/{stock_id}")
async def remove_from_watchlist(
    stock_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    从自选列表移除股票
    """
    query = select(StockModel).where(StockModel.id == stock_id)
    result = await db.execute(query)
    stock = result.scalar_one_or_none()
    
    if not stock:
        raise HTTPException(status_code=404, detail="股票不在自选列表中")
    
    await db.delete(stock)
    await db.commit()
    
    return {"status": "success", "message": "已从自选列表移除"}


@router.get("/search")
async def search_stocks(
    keyword: str = Query(..., min_length=1, description="股票代码或名称"),
    market: Optional[str] = Query(None, description="市场类型: A 或 HK")
):
    """
    搜索股票
    TODO: 接入真实股票数据API
    """
    # 模拟搜索结果（实际应该调用股票数据服务）
    mock_results = [
        {"code": "600519", "name": "贵州茅台", "market": "A"},
        {"code": "000858", "name": "五粮液", "market": "A"},
        {"code": "00700", "name": "腾讯控股", "market": "HK"},
        {"code": "09988", "name": "阿里巴巴-SW", "market": "HK"},
    ]
    
    # 过滤匹配结果
    results = [
        s for s in mock_results 
        if keyword.lower() in s["code"].lower() or keyword.lower() in s["name"].lower()
    ]
    
    if market:
        results = [s for s in results if s["market"] == market]
    
    return results


@router.get("/market/indices")
async def get_market_indices():
    """
    获取主要市场指数实时行情（轻量级接口）
    
    返回上证指数、深证成指、创业板指、科创50、沪深300 的实时数据
    """
    import asyncio
    
    main_indices = {
        "000001": "上证指数",
        "399001": "深证成指",
        "399006": "创业板指",
        "000688": "科创50",
        "000300": "沪深300",
    }
    
    def _fetch():
        import akshare as ak
        df = ak.stock_zh_index_spot_em()
        results = []
        for code, name in main_indices.items():
            row = df[df['代码'] == code]
            if not row.empty:
                r = row.iloc[0]
                results.append({
                    "code": code,
                    "name": name,
                    "current": float(r['最新价']),
                    "change": float(r['涨跌额']),
                    "change_pct": float(r['涨跌幅']),
                    "volume": float(r.get('成交量', 0)),
                    "amount": float(r.get('成交额', 0)),
                    "high": float(r.get('最高', 0)),
                    "low": float(r.get('最低', 0)),
                    "open": float(r.get('今开', 0)),
                })
        return results
    
    try:
        loop = asyncio.get_event_loop()
        data = await asyncio.wait_for(
            loop.run_in_executor(None, _fetch),
            timeout=30
        )
        return {"status": "success", "data": data}
    except asyncio.TimeoutError:
        return {"status": "error", "message": "获取指数数据超时，请稍后重试", "data": []}
    except Exception as e:
        return {"status": "error", "message": f"获取指数数据失败: {str(e)}", "data": []}


@router.get("/{stock_code}/quote", response_model=StockQuote)
async def get_stock_quote(
    stock_code: str,
    market: str = Query("A", description="市场类型: A 或 HK")
):
    """
    获取股票实时行情
    TODO: 接入真实行情API
    """
    # 模拟行情数据
    return StockQuote(
        code=stock_code,
        name="测试股票",
        current_price=100.00,
        open_price=99.50,
        high_price=101.20,
        low_price=98.80,
        prev_close=99.00,
        change=1.00,
        change_percent=1.01,
        volume=123456.0,
        amount=12345678.0,
        update_time=datetime.now()
    )


@router.get("/{stock_code}/kline", response_model=List[KlineData])
async def get_stock_kline(
    stock_code: str,
    market: str = Query("A", description="市场类型"),
    period: str = Query("daily", description="周期: daily, weekly, monthly"),
    limit: int = Query(60, ge=1, le=250, description="返回数据条数")
):
    """
    获取K线数据
    TODO: 接入真实K线数据API
    """
    from datetime import date, timedelta
    
    # 模拟K线数据
    klines = []
    base_date = date.today()
    base_price = 100.0
    
    for i in range(limit):
        d = base_date - timedelta(days=i)
        open_p = base_price + (i % 5 - 2)
        close_p = open_p + (i % 3 - 1)
        high_p = max(open_p, close_p) + (i % 2)
        low_p = min(open_p, close_p) - (i % 2)
        
        klines.append(KlineData(
            date=d,
            open=round(open_p, 2),
            high=round(high_p, 2),
            low=round(low_p, 2),
            close=round(close_p, 2),
            volume=float(100000 + i * 1000)
        ))
    
    return list(reversed(klines))


@router.get("/{stock_code}/prediction", response_model=StockPrediction)
async def get_stock_prediction(
    stock_code: str,
    market: str = Query("A", description="市场类型"),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
):
    """
    获取股票投资预判
    """
    # 先查询是否有缓存的预测
    query = (
        select(StockPredictionModel)
        .where(StockPredictionModel.stock_code == stock_code)
        .order_by(desc(StockPredictionModel.generated_at))
        .limit(1)
    )
    result = await db.execute(query)
    prediction_record = result.scalar_one_or_none()
    
    if prediction_record:
        # 返回已有预测
        from ..models.stock import FundamentalData, TechnicalData, SentimentData
        
        return StockPrediction(
            code=prediction_record.stock_code,
            name=prediction_record.stock_name,
            market=MarketType(prediction_record.market),
            current_price=prediction_record.current_price,
            fundamentals=FundamentalData(**(prediction_record.fundamentals or {})),
            technicals=TechnicalData(**(prediction_record.technicals or {})),
            sentiment=SentimentData(**(prediction_record.sentiment or {})),
            prediction=PredictionType(prediction_record.prediction),
            confidence=prediction_record.confidence,
            target_price=prediction_record.target_price,
            stop_loss=prediction_record.stop_loss,
            reasoning=prediction_record.reasoning,
            fundamental_score=prediction_record.fundamental_score or 0.5,
            technical_score=prediction_record.technical_score or 0.5,
            sentiment_score=prediction_record.sentiment_score or 0.5,
            overall_score=prediction_record.overall_score or 0.5,
            generated_at=prediction_record.generated_at
        )
    
    # 如果没有预测记录，返回模拟数据（实际应该触发生成）
    from ..models.stock import FundamentalData, TechnicalData, SentimentData
    
    return StockPrediction(
        code=stock_code,
        name="待获取",
        market=MarketType(market),
        current_price=0.0,
        fundamentals=FundamentalData(),
        technicals=TechnicalData(),
        sentiment=SentimentData(),
        prediction=PredictionType.NEUTRAL,
        confidence=0.5,
        reasoning="暂无预测数据，请先触发分析",
        fundamental_score=0.5,
        technical_score=0.5,
        sentiment_score=0.5,
        overall_score=0.5,
        generated_at=datetime.now()
    )


@router.post("/{stock_code}/analyze")
async def trigger_stock_analysis(
    stock_code: str,
    market: str = Query("A", description="市场类型"),
    background_tasks: BackgroundTasks = None,
    request: Request = None
):
    """
    触发股票分析
    """
    # TODO: 在后台执行分析任务
    return {
        "status": "started",
        "message": f"已开始分析 {stock_code}",
        "stock_code": stock_code,
        "market": market
    }


@router.post("/watchlist/refresh")
async def refresh_watchlist(
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    刷新所有自选股数据
    """
    query = select(StockModel)
    result = await db.execute(query)
    stocks = result.scalars().all()
    
    # TODO: 在后台刷新所有股票数据
    
    return {
        "status": "started",
        "message": f"正在刷新 {len(stocks)} 只股票的数据"
    }


@router.get("/watchlist/merged")
async def get_merged_watchlist(db: AsyncSession = Depends(get_db)):
    """
    获取合并后的自选股列表（配置文件 + 数据库）
    
    返回去重后的完整自选股列表，包含所属行业信息
    """
    watchlist_service = get_watchlist_service()
    
    # 从配置加载
    watchlist_service.load_from_config(settings.watchlist_stocks)
    
    # 从数据库加载
    query = select(StockModel)
    result = await db.execute(query)
    db_stocks = result.scalars().all()
    
    if db_stocks:
        db_stock_list = [
            {"code": s.code, "name": s.name, "market": s.market}
            for s in db_stocks
        ]
        watchlist_service.load_from_database(db_stock_list)
    
    # 获取合并后的数据
    all_stocks = watchlist_service.get_all_stocks()
    unique_sectors = watchlist_service.get_unique_sectors()
    
    return {
        "stocks": [
            {
                "code": s.code,
                "name": s.name,
                "market": s.market,
                "sector": s.sector,
                "source": s.source
            }
            for s in all_stocks
        ],
        "sectors": unique_sectors,
        "total_count": len(all_stocks),
        "config_count": sum(1 for s in all_stocks if s.source == "config"),
        "database_count": sum(1 for s in all_stocks if s.source == "database")
    }


@router.delete("/watchlist/config/{stock_code}")
async def remove_from_config_watchlist(stock_code: str):
    """
    从配置文件中移除自选股
    
    修改 .env 文件中的 WATCHLIST_STOCKS 配置
    """
    import os
    from pathlib import Path
    
    # 找到 .env 文件
    env_path = Path(__file__).parent.parent.parent / ".env"
    
    if not env_path.exists():
        raise HTTPException(status_code=404, detail=".env 文件不存在")
    
    # 读取 .env 文件内容
    with open(env_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    # 找到并修改 WATCHLIST_STOCKS 行
    new_lines = []
    found = False
    for line in lines:
        if line.strip().startswith("WATCHLIST_STOCKS="):
            found = True
            # 解析现有的自选股
            _, value = line.split("=", 1)
            value = value.strip()
            
            stocks = []
            if value:
                for item in value.split(","):
                    item = item.strip()
                    if ":" in item:
                        parts = item.split(":")
                        code = parts[0].strip()
                        # 跳过要删除的股票
                        if code != stock_code:
                            stocks.append(item)
            
            # 重新构建配置行
            new_value = ",".join(stocks)
            new_lines.append(f"WATCHLIST_STOCKS={new_value}\n")
        else:
            new_lines.append(line)
    
    if not found:
        raise HTTPException(status_code=404, detail="配置文件中没有找到 WATCHLIST_STOCKS 配置")
    
    # 写回 .env 文件
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    
    # 重新加载配置（更新内存中的设置）
    from ..config import settings
    
    # 重新读取 .env 并更新 settings
    new_watchlist = ""
    for line in new_lines:
        if line.strip().startswith("WATCHLIST_STOCKS="):
            _, new_watchlist = line.split("=", 1)
            new_watchlist = new_watchlist.strip()
            break
    
    # 更新 settings 对象
    settings.watchlist_stocks = new_watchlist
    
    # 重置自选股服务缓存
    from ..services.watchlist_service import reset_watchlist_service
    reset_watchlist_service()
    
    return {"status": "success", "message": f"已从配置文件中移除 {stock_code}"}


@router.get("/watchlist/sectors")
async def get_watchlist_sectors(db: AsyncSession = Depends(get_db)):
    """
    获取自选股覆盖的行业列表
    
    用于展示用户关注的行业分布
    """
    watchlist_service = get_watchlist_service()
    
    # 从配置加载
    watchlist_service.load_from_config(settings.watchlist_stocks)
    
    # 从数据库加载
    query = select(StockModel)
    result = await db.execute(query)
    db_stocks = result.scalars().all()
    
    if db_stocks:
        db_stock_list = [
            {"code": s.code, "name": s.name, "market": s.market}
            for s in db_stocks
        ]
        watchlist_service.load_from_database(db_stock_list)
    
    unique_sectors = watchlist_service.get_unique_sectors()
    
    # 获取每个行业的股票
    sector_details = {}
    for sector in unique_sectors:
        stocks_in_sector = watchlist_service.get_stocks_by_sector(sector)
        sector_details[sector] = {
            "count": len(stocks_in_sector),
            "stocks": [{"code": s.code, "name": s.name} for s in stocks_in_sector],
            "keywords": watchlist_service.get_sector_keywords(sector)
        }
    
    return {
        "sectors": unique_sectors,
        "details": sector_details
    }

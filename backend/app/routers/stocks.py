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
    KlineData, MarketType, PredictionType, StockPreparation
)
from ..models.database import StockModel, StockPredictionModel
from ..services.watchlist_service import get_watchlist_service, WatchlistStock
from ..services.market_data_service import get_market_data_service
from ..config import settings

router = APIRouter()


def preparation_record(stock):
    return dict(id=stock.id,code=stock.code,name=stock.name,market=stock.market)


async def get_db(request: Request) -> AsyncSession:
    """获取数据库会话"""
    async with request.app.state.session_maker() as session:
        yield session


@router.get("/watchlist", response_model=List[Stock])
async def get_watchlist(db: AsyncSession = Depends(get_db)):
    """
    获取自选股列表（含实时行情）
    
    直接从腾讯财经 API 获取最新股价，失败时回退到数据库缓存
    """
    import asyncio
    import urllib.request
    import ssl
    
    query = select(StockModel).order_by(StockModel.added_at)
    result = await db.execute(query)
    stocks = result.scalars().all()
    
    if not stocks:
        return []
    
    from ..services.watchlist_sources import fetch_watchlist_quotes
    quotes = await asyncio.to_thread(fetch_watchlist_quotes, stocks)

    result_list = []
    from ..services.watchlist_preparation import get_preparation_service
    preparation=get_preparation_service()
    for s in stocks:
        quote = quotes.get(s.code)
        current_price = quote["price"] if quote and quote.get("price") is not None else s.current_price
        change_percent = quote["change_pct"] if quote and quote.get("change_pct") is not None else s.change_percent
        
        result_list.append(Stock(
            id=s.id,
            code=s.code,
            name=s.name,
            market=MarketType(s.market),
            current_price=current_price,
            change_percent=change_percent,
            latest_prediction=None,  # Legacy ratings have no evidence verification.
            latest_confidence=None,
            added_at=s.added_at,
            last_updated=datetime.fromisoformat(quote['as_of']) if quote else s.last_updated,
            preparation=preparation.status(preparation_record(s))
        ))
    
    return result_list


@router.post("/watchlist", response_model=Stock)
async def add_to_watchlist(
    stock_data: StockCreate,
    background_tasks: BackgroundTasks,
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
    from ..services.watchlist_preparation import get_preparation_service
    preparation=get_preparation_service();record=preparation_record(stock)
    status,attempt=preparation.queue(record)
    if attempt:background_tasks.add_task(preparation.run,record,attempt)
    
    return Stock(
        id=stock.id,
        code=stock.code,
        name=stock.name,
        market=MarketType(stock.market),
        current_price=stock.current_price,
        change_percent=stock.change_percent,
        latest_prediction=None,  # Legacy ratings have no evidence verification.
        latest_confidence=None,
        added_at=stock.added_at,
        last_updated=stock.last_updated,
        preparation=status
    )


@router.get('/watchlist/preparation',response_model=dict[str,StockPreparation])
async def watchlist_preparation_status(db: AsyncSession=Depends(get_db)):
    from ..services.watchlist_preparation import get_preparation_service
    preparation=get_preparation_service()
    stocks=(await db.execute(select(StockModel))).scalars().all()
    return {stock.id:preparation.status(preparation_record(stock)) for stock in stocks}


@router.post('/watchlist/{stock_id}/prepare',response_model=StockPreparation)
async def prepare_watchlist_stock(stock_id: str,background_tasks: BackgroundTasks,db: AsyncSession=Depends(get_db)):
    from ..services.watchlist_preparation import get_preparation_service
    stock=(await db.execute(select(StockModel).where(StockModel.id==stock_id))).scalar_one_or_none()
    if stock is None:raise HTTPException(status_code=404,detail='股票已不在自选列表')
    preparation=get_preparation_service();record=preparation_record(stock)
    status,attempt=preparation.queue(record)
    if attempt:background_tasks.add_task(preparation.run,record,attempt)
    return status


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


# 内置常见股票列表（作为 fallback）
_builtin_stocks = [
    # A股 - 大盘蓝筹
    {"code": "600519", "name": "贵州茅台", "market": "A"},
    {"code": "000858", "name": "五粮液", "market": "A"},
    {"code": "002594", "name": "比亚迪", "market": "A"},
    {"code": "600036", "name": "招商银行", "market": "A"},
    {"code": "002714", "name": "牧原股份", "market": "A"},
    {"code": "000333", "name": "美的集团", "market": "A"},
    {"code": "601318", "name": "中国平安", "market": "A"},
    {"code": "600276", "name": "恒瑞医药", "market": "A"},
    {"code": "000001", "name": "平安银行", "market": "A"},
    {"code": "600900", "name": "长江电力", "market": "A"},
    {"code": "601012", "name": "隆基绿能", "market": "A"},
    {"code": "300750", "name": "宁德时代", "market": "A"},
    {"code": "600030", "name": "中信证券", "market": "A"},
    {"code": "601398", "name": "工商银行", "market": "A"},
    {"code": "600887", "name": "伊利股份", "market": "A"},
    {"code": "000568", "name": "泸州老窖", "market": "A"},
    {"code": "002415", "name": "海康威视", "market": "A"},
    {"code": "600809", "name": "山西汾酒", "market": "A"},
    {"code": "601888", "name": "中国中免", "market": "A"},
    {"code": "000002", "name": "万科A", "market": "A"},
    {"code": "601166", "name": "兴业银行", "market": "A"},
    {"code": "002304", "name": "洋河股份", "market": "A"},
    {"code": "600048", "name": "保利发展", "market": "A"},
    {"code": "002352", "name": "顺丰控股", "market": "A"},
    {"code": "300059", "name": "东方财富", "market": "A"},
    {"code": "601899", "name": "紫金矿业", "market": "A"},
    {"code": "002230", "name": "科大讯飞", "market": "A"},
    {"code": "600585", "name": "海螺水泥", "market": "A"},
    {"code": "603259", "name": "药明康德", "market": "A"},
    {"code": "601668", "name": "中国建筑", "market": "A"},
    {"code": "600050", "name": "中国联通", "market": "A"},
    {"code": "601857", "name": "中国石油", "market": "A"},
    {"code": "600028", "name": "中国石化", "market": "A"},
    {"code": "000651", "name": "格力电器", "market": "A"},
    {"code": "000725", "name": "京东方A", "market": "A"},
    {"code": "600690", "name": "海尔智家", "market": "A"},
    {"code": "002475", "name": "立讯精密", "market": "A"},
    {"code": "300124", "name": "汇川技术", "market": "A"},
    {"code": "600031", "name": "三一重工", "market": "A"},
    {"code": "601919", "name": "中远海控", "market": "A"},
    # 热门港股
    {"code": "00700", "name": "腾讯控股", "market": "HK"},
    {"code": "09988", "name": "阿里巴巴-W", "market": "HK"},
    {"code": "09618", "name": "京东集团-SW", "market": "HK"},
    {"code": "03690", "name": "美团-W", "market": "HK"},
    {"code": "09888", "name": "百度集团-SW", "market": "HK"},
    {"code": "01810", "name": "小米集团-W", "market": "HK"},
    {"code": "09999", "name": "网易-S", "market": "HK"},
    {"code": "00388", "name": "香港交易所", "market": "HK"},
    {"code": "02318", "name": "中国平安", "market": "HK"},
    {"code": "00941", "name": "中国移动", "market": "HK"},
    {"code": "01211", "name": "比亚迪股份", "market": "HK"},
    {"code": "02020", "name": "安踏体育", "market": "HK"},
    {"code": "00005", "name": "汇丰控股", "market": "HK"},
    {"code": "01024", "name": "快手-W", "market": "HK"},
    {"code": "06618", "name": "京东健康", "market": "HK"},
    {"code": "09868", "name": "小鹏汽车-W", "market": "HK"},
    {"code": "09866", "name": "蔚来-SW", "market": "HK"},
    {"code": "02015", "name": "理想汽车-W", "market": "HK"},
    {"code": "00981", "name": "中芯国际", "market": "HK"},
    {"code": "09961", "name": "携程集团-S", "market": "HK"},
]


@router.get("/search")
async def search_stocks(
    keyword: str = Query(..., min_length=1, description="股票代码或名称"),
    market: Optional[str] = Query(None, description="市场类型: A 或 HK")
):
    """
    搜索股票 - 使用东方财富搜索API，实时搜索全市场（A股+港股）
    毫秒级响应，支持中文名称、股票代码、拼音首字母
    """
    import httpx
    
    async def _search_eastmoney(kw: str):
        """调用东方财富搜索API"""
        url = "https://searchapi.eastmoney.com/api/suggest/get"
        params = {
            "input": kw,
            "type": "14",
            "token": "D43BF722C8E33BDC906FB84D85E326E8",
            "count": "20",
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, params=params)
                data = resp.json()
                
                results = []
                items = data.get("QuotationCodeTable", {}).get("Data", []) or []
                for item in items:
                    classify = item.get("Classify", "")
                    code = item.get("Code", "")
                    name = item.get("Name", "")
                    
                    # A 股：主板+创业板(AStock) + 科创板(23) + 北交所(NEEQ)
                    if classify in ("AStock", "23", "NEEQ"):
                        results.append({"code": code, "name": name, "market": "A"})
                    elif classify == "HK":
                        # 过滤掉权证、牛熊证（名称通常包含"购"/"沽"/"牛"/"熊"）
                        if not any(x in name for x in ["购", "沽", "牛", "熊", "法兴", "中银", "瑞银", "高盛", "摩通"]):
                            results.append({"code": code, "name": name, "market": "HK"})
                
                return results
        except Exception as e:
            print(f"[ERROR] 东方财富搜索API失败: {e}")
            return None
    
    def _search_from_builtin(kw: str):
        """从内置列表搜索（降级方案）"""
        kw_lower = kw.lower()
        results = [
            s for s in _builtin_stocks
            if kw_lower in s["code"].lower() or kw_lower in s["name"].lower()
        ]
        return results
    
    # 1. 优先调用东方财富搜索API（毫秒级响应）
    results = await _search_eastmoney(keyword)
    
    if results is None:
        # 2. API 失败 → 降级到内置列表
        print(f"[WARN] 东方财富API不可用，使用内置列表搜索: {keyword}")
        results = _search_from_builtin(keyword)
    
    # 3. 按市场过滤
    if market:
        results = [s for s in results if s["market"] == market]
    
    return results[:20]


@router.get("/market/indices")
async def get_market_indices():
    """
    获取主要市场指数实时行情（轻量级接口）
    
    使用腾讯财经 API 作为数据源（国内最稳定）
    返回上证指数、深证成指、创业板指、科创50、沪深300 的实时数据
    """
    import asyncio
    import urllib.request
    import ssl
    
    # 腾讯财经指数代码映射
    # 格式: sh000001 (上证), sz399001 (深证)
    qq_indices = {
        "sh000001": {"code": "000001", "name": "上证指数"},
        "sz399001": {"code": "399001", "name": "深证成指"},
        "sz399006": {"code": "399006", "name": "创业板指"},
        "sh000688": {"code": "000688", "name": "科创50"},
        "sh000300": {"code": "000300", "name": "沪深300"},
    }
    
    def _fetch_from_qq():
        """从腾讯财经获取指数数据"""
        symbols = ",".join(qq_indices.keys())
        url = f"http://qt.gtimg.cn/q={symbols}"
        
        # 创建不验证SSL的context
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'Mozilla/5.0')
        
        with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
            content = response.read().decode('gbk')
        
        results = []
        for line in content.strip().split(';'):
            if '=' not in line or '~' not in line:
                continue
            
            var_name = line.split('=')[0].replace('v_', '').strip()
            data_str = line.split('"')[1] if '"' in line else ""
            
            if var_name in qq_indices and data_str:
                info = qq_indices[var_name]
                parts = data_str.split('~')
                
                # 腾讯格式（指数）: 0~名称~代码~当前价~涨跌~涨跌%~成交量~成交额~...~开盘价~最高~最低...
                # 注意：指数的字段位置可能与个股不同
                # parts[3] = 当前价
                # parts[4] = 涨跌额
                # parts[5] = 涨跌幅（百分比数值，不带%号）
                # parts[32] = 涨跌幅（另一个位置，更准确）
                if len(parts) >= 6:
                    try:
                        current_price = float(parts[3]) if parts[3] else 0
                        change = float(parts[4]) if parts[4] else 0
                        
                        # 尝试从多个位置获取涨跌幅
                        change_pct = 0
                        # 首先尝试 parts[32]（更准确的涨跌幅位置）
                        if len(parts) > 32 and parts[32]:
                            try:
                                change_pct = float(parts[32])
                            except:
                                pass
                        
                        # 如果 parts[32] 无效，使用 parts[5]
                        if change_pct == 0 and parts[5]:
                            try:
                                pct_val = float(parts[5])
                                # 如果值太大（超过100），说明不是百分比，需要计算
                                if abs(pct_val) > 100:
                                    # 从 parts[4]（涨跌额）和 parts[3]（当前价）计算
                                    if current_price > 0 and change != 0:
                                        prev_close = current_price - change
                                        if prev_close > 0:
                                            change_pct = (change / prev_close) * 100
                                else:
                                    change_pct = pct_val
                            except:
                                pass
                        
                        # 获取开盘价（尝试多个位置）
                        open_price = 0
                        for pos in [5, 30, 31]:  # 可能的开盘价位置
                            if len(parts) > pos and parts[pos]:
                                try:
                                    val = float(parts[pos])
                                    # 开盘价应该接近当前价，不会差太远
                                    if current_price > 0 and abs(val - current_price) / current_price < 0.1:
                                        open_price = val
                                        break
                                except:
                                    pass
                        
                        results.append({
                            "code": info["code"],
                            "name": info["name"],
                            "current": current_price,
                            "change": change,
                            "change_pct": round(change_pct, 2),
                            "volume": float(parts[6]) * 100 if len(parts) > 6 and parts[6] else 0,
                            "amount": float(parts[7]) * 10000 if len(parts) > 7 and parts[7] else 0,
                            "high": float(parts[33]) if len(parts) > 33 and parts[33] else 0,
                            "low": float(parts[34]) if len(parts) > 34 and parts[34] else 0,
                            "open": open_price,
                        })
                    except (ValueError, IndexError) as e:
                        print(f"解析 {var_name} 失败: {e}")
        
        return results
    
    try:
        loop = asyncio.get_event_loop()
        data = await asyncio.wait_for(
            loop.run_in_executor(None, _fetch_from_qq),
            timeout=15
        )
        if data:
            return {"status": "success", "data": data}
        else:
            return {"status": "error", "message": "未获取到指数数据", "data": []}
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
    获取股票实时行情（腾讯财经真实数据）
    """
    import asyncio
    import urllib.request
    import ssl
    
    def _fetch_single_quote(code: str, mkt: str):
        """从腾讯财经获取单只股票的详细行情"""
        if mkt == 'A':
            if code.startswith('6') or code.startswith('9'):
                symbol = f"sh{code}"
            else:
                symbol = f"sz{code}"
        elif mkt == 'HK':
            symbol = f"hk{code.zfill(5)}"
        else:
            return None
        
        url = f"http://qt.gtimg.cn/q={symbol}"
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'Mozilla/5.0')
        
        with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
            content = response.read().decode('gbk')
        
        for line in content.strip().split(';'):
            if '=' not in line or '~' not in line:
                continue
            data_str = line.split('"')[1] if '"' in line else ""
            if not data_str:
                continue
            
            parts = data_str.split('~')
            # 腾讯财经字段说明（A股/港股通用）：
            # parts[1]=名称, parts[2]=代码, parts[3]=当前价, parts[4]=昨收
            # parts[5]=开盘价, parts[6]=成交量(手), parts[7]=外盘, parts[8]=内盘
            # parts[9]=买一价 ... parts[19]=卖五量
            # parts[30]=涨跌额, parts[31]=涨跌幅%, parts[32]=最高价?, parts[33]=最低价?
            # 更准确的: parts[31]=涨跌额, parts[32]=涨跌幅%
            # parts[33]=最高价, parts[34]=最低价, parts[35]=价格/成交量/成交额
            # parts[44]=流通市值, parts[45]=总市值
            # parts[46]=PB, parts[39]=PE(动态)
            if len(parts) >= 35:
                try:
                    name = parts[1]
                    current_price = float(parts[3]) if parts[3] else 0
                    prev_close = float(parts[4]) if parts[4] else 0
                    open_price = float(parts[5]) if parts[5] else 0
                    volume = float(parts[6]) if parts[6] else 0  # 手
                    high_price = float(parts[33]) if parts[33] else 0
                    low_price = float(parts[34]) if parts[34] else 0
                    
                    # 涨跌额和涨跌幅
                    change = float(parts[31]) if len(parts) > 31 and parts[31] else 0
                    change_pct = float(parts[32]) if len(parts) > 32 and parts[32] else 0
                    
                    # 成交额（万元）
                    amount = float(parts[37]) if len(parts) > 37 and parts[37] else 0
                    
                    # PE、PB、总市值
                    pe_ratio = None
                    pb_ratio = None
                    market_cap = None
                    if len(parts) > 39 and parts[39]:
                        try:
                            pe_ratio = float(parts[39])
                        except:
                            pass
                    if len(parts) > 46 and parts[46]:
                        try:
                            pb_ratio = float(parts[46])
                        except:
                            pass
                    if len(parts) > 45 and parts[45]:
                        try:
                            market_cap = float(parts[45])  # 亿
                        except:
                            pass
                    
                    return {
                        "name": name,
                        "current_price": current_price,
                        "open_price": open_price,
                        "high_price": high_price,
                        "low_price": low_price,
                        "prev_close": prev_close,
                        "change": change,
                        "change_percent": change_pct,
                        "volume": volume,
                        "amount": amount,
                        "pe_ratio": pe_ratio,
                        "pb_ratio": pb_ratio,
                        "market_cap": market_cap,
                    }
                except (ValueError, IndexError) as e:
                    print(f"[QUOTE] 解析 {symbol} 失败: {e}")
                    return None
        return None
    
    try:
        loop = asyncio.get_event_loop()
        quote = await asyncio.wait_for(
            loop.run_in_executor(None, _fetch_single_quote, stock_code, market),
            timeout=10
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取行情失败: {str(e)}")
    
    if not quote:
        raise HTTPException(status_code=404, detail=f"未找到 {stock_code} 的行情数据")
    
    return StockQuote(
        code=stock_code,
        name=quote["name"],
        current_price=quote["current_price"],
        open_price=quote["open_price"],
        high_price=quote["high_price"],
        low_price=quote["low_price"],
        prev_close=quote["prev_close"],
        change=quote["change"],
        change_percent=quote["change_percent"],
        volume=quote["volume"],
        amount=quote["amount"],
        update_time=datetime.now(),
        pe_ratio=quote.get("pe_ratio"),
        pb_ratio=quote.get("pb_ratio"),
        market_cap=quote.get("market_cap"),
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
    
    数据源优先级：腾讯财经 → 东方财富 → 新浪财经
    """
    import asyncio
    import urllib.request
    import ssl
    import json
    from datetime import date as dt_date_local
    
    def _build_symbol(code: str, mkt: str):
        """构建股票代码"""
        if mkt == 'A':
            if code.startswith('6') or code.startswith('9'):
                return f"sh{code}", "1"  # 返回腾讯格式和东方财富市场代码
            else:
                return f"sz{code}", "0"
        elif mkt == 'HK':
            return f"hk{code.zfill(5)}", "116"
        return None, None
    
    def _fetch_kline_qq(code: str, mkt: str, prd: str, lmt: int):
        """数据源1：腾讯财经 K 线"""
        symbol, _ = _build_symbol(code, mkt)
        if not symbol:
            return []
        
        period_map = {"daily": "day", "weekly": "week", "monthly": "month"}
        qq_period = period_map.get(prd, "day")
        
        url = (
            f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
            f"param={symbol},{qq_period},,{lmt},qfq"
        )
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        
        with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
            content = response.read().decode('utf-8')
        
        data = json.loads(content)
        print(f"[KLINE-QQ] {symbol} 响应 keys: {list(data.get('data', {}).keys())}")
        
        klines = []
        stock_data = data.get("data", {})
        
        for key in stock_data:
            stock_info = stock_data[key]
            if not isinstance(stock_info, dict):
                continue
            
            kline_data = None
            for kline_key in [f"qfq{qq_period}", qq_period]:
                if kline_key in stock_info:
                    kline_data = stock_info[kline_key]
                    break
            
            if not kline_data:
                print(f"[KLINE-QQ] {symbol} 可用 keys: {list(stock_info.keys())}")
                continue
            
            for item in kline_data:
                if len(item) >= 6:
                    try:
                        trade_date = dt_date_local.fromisoformat(item[0])
                        klines.append({
                            "trade_date": trade_date,
                            "open_price": float(item[1]),
                            "close_price": float(item[2]),
                            "high_price": float(item[3]),
                            "low_price": float(item[4]),
                            "volume": float(item[5]),
                        })
                    except (ValueError, IndexError):
                        continue
        
        return klines
    
    def _fetch_kline_eastmoney(code: str, mkt: str, prd: str, lmt: int):
        """数据源2：东方财富 K 线"""
        _, secid_market = _build_symbol(code, mkt)
        if secid_market is None:
            return []
        
        # 东方财富周期映射
        period_map = {"daily": "101", "weekly": "102", "monthly": "103"}
        klt = period_map.get(prd, "101")
        
        secid = f"{secid_market}.{code}"
        
        url = (
            f"https://push2his.eastmoney.com/api/qt/stock/kline/get?"
            f"secid={secid}&fields1=f1,f2,f3,f4,f5,f6&"
            f"fields2=f51,f52,f53,f54,f55,f56,f57&"
            f"klt={klt}&fqt=1&end=20500101&lmt={lmt}"
        )
        
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        req.add_header('Referer', 'https://quote.eastmoney.com/')
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
            content = response.read().decode('utf-8')
        
        data = json.loads(content)
        kline_list = data.get("data", {}).get("klines", []) if data.get("data") else []
        
        print(f"[KLINE-EM] {secid} 获取到 {len(kline_list)} 条K线")
        
        klines = []
        for line in kline_list:
            # 格式: "2025-04-09,39.50,39.26,39.68,39.12,534978,2102563872.00"
            parts = line.split(",")
            if len(parts) >= 6:
                try:
                    trade_date = dt_date_local.fromisoformat(parts[0])
                    klines.append({
                        "trade_date": trade_date,
                        "open_price": float(parts[1]),
                        "close_price": float(parts[2]),
                        "high_price": float(parts[3]),
                        "low_price": float(parts[4]),
                        "volume": float(parts[5]),
                    })
                except (ValueError, IndexError):
                    continue
        
        return klines
    
    def _fetch_kline_with_fallback(code: str, mkt: str, prd: str, lmt: int):
        """按优先级尝试多个数据源"""
        # 数据源1：腾讯财经
        try:
            result = _fetch_kline_qq(code, mkt, prd, lmt)
            if result:
                print(f"[KLINE] ✅ 腾讯源成功: {code}, {len(result)}条")
                return result
            print(f"[KLINE] ⚠️ 腾讯源返回空数据: {code}")
        except Exception as e:
            print(f"[KLINE] ❌ 腾讯源失败: {code} - {e}")
        
        # 数据源2：东方财富
        try:
            result = _fetch_kline_eastmoney(code, mkt, prd, lmt)
            if result:
                print(f"[KLINE] ✅ 东方财富源成功: {code}, {len(result)}条")
                return result
            print(f"[KLINE] ⚠️ 东方财富源返回空数据: {code}")
        except Exception as e:
            print(f"[KLINE] ❌ 东方财富源失败: {code} - {e}")
        
        return []
    
    try:
        loop = asyncio.get_event_loop()
        kline_data = await asyncio.wait_for(
            loop.run_in_executor(None, _fetch_kline_with_fallback, stock_code, market, period, limit),
            timeout=20
        )
    except Exception as e:
        print(f"[KLINE] ❌ 所有数据源超时: {stock_code} - {e}")
        raise HTTPException(status_code=502, detail=f"获取K线数据失败: {str(e)}")
    
    if not kline_data:
        raise HTTPException(status_code=404, detail=f"未找到 {stock_code} 的K线数据")
    
    # 返回最近 limit 条
    kline_data = kline_data[-limit:]
    
    return [
        KlineData(
            trade_date=k["trade_date"],
            open_price=k["open_price"],
            high_price=k["high_price"],
            low_price=k["low_price"],
            close_price=k["close_price"],
            volume=k["volume"],
        )
        for k in kline_data
    ]


@router.get("/{stock_code}/prediction")
async def get_stock_prediction(
    stock_code: str,
    market: str = Query("A", description="市场类型"),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
):
    """Legacy records lack evidence verification; preserve storage but do not publish as current analysis."""
    raise HTTPException(status_code=404, detail="暂无通过证据核验的个股分析；历史默认评级和置信度不作为当前结果展示")


@router.post("/{stock_code}/analyze")
async def trigger_stock_analysis(
    stock_code: str,
    market: str = Query("A", description="市场类型"),
    background_tasks: BackgroundTasks = None,
    request: Request = None,
    db: AsyncSession = Depends(get_db)
):
    """Do not acknowledge a background task that cannot produce evidence-based analysis."""
    raise HTTPException(status_code=422, detail="资料不足：仅凭报价不能生成投资评级；请查看报告中的来源、反证与触发条件")


@router.post("/watchlist/refresh")
async def refresh_watchlist(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    刷新所有自选股数据（立即执行）
    使用腾讯财经 API 获取最新行情并更新数据库
    """
    import asyncio
    import urllib.request
    import ssl
    
    query = select(StockModel)
    result = await db.execute(query)
    stocks = result.scalars().all()
    
    if not stocks:
        return {"status": "success", "message": "没有自选股", "updated": 0}
    
    def _fetch_quotes_from_qq(stock_list):
        """从腾讯财经批量获取股票行情"""
        # 构建腾讯财经股票代码
        # A股: sh600519 或 sz000001
        # 港股: hk00700
        symbols = []
        for s in stock_list:
            if s.market == 'A':
                if s.code.startswith('6') or s.code.startswith('9'):
                    symbols.append(f"sh{s.code}")
                else:
                    symbols.append(f"sz{s.code}")
            elif s.market == 'HK':
                symbols.append(f"hk{s.code.zfill(5)}")
        
        if not symbols:
            return {}
        
        url = f"http://qt.gtimg.cn/q={','.join(symbols)}"
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'Mozilla/5.0')
        
        with urllib.request.urlopen(req, timeout=15, context=ctx) as response:
            content = response.read().decode('gbk')
        
        quotes = {}
        for line in content.strip().split(';'):
            if '=' not in line or '~' not in line:
                continue
            
            var_name = line.split('=')[0].replace('v_', '').strip()
            data_str = line.split('"')[1] if '"' in line else ""
            
            if not data_str:
                continue
            
            parts = data_str.split('~')
            
            # 提取代码
            # 腾讯格式: 
            # parts[1]=名称, parts[2]=代码, parts[3]=当前价, parts[4]=昨收
            # parts[31]=涨跌额, parts[32]=涨跌幅%
            if var_name.startswith('sh') or var_name.startswith('sz'):
                code = var_name[2:]
                if len(parts) >= 33:
                    try:
                        current_price = float(parts[3]) if parts[3] else None
                        change_pct = float(parts[32]) if parts[32] else None
                        quotes[code] = {
                            "price": current_price,
                            "change_pct": change_pct
                        }
                    except ValueError:
                        pass
            elif var_name.startswith('hk'):
                code = var_name[2:].lstrip('0')  # 去掉前导0
                if len(parts) >= 33:
                    try:
                        current_price = float(parts[3]) if parts[3] else None
                        change_pct = float(parts[32]) if parts[32] else None
                        quotes[code] = {
                            "price": current_price,
                            "change_pct": change_pct
                        }
                    except ValueError:
                        pass
        
        return quotes
    
    try:
        loop = asyncio.get_event_loop()
        quotes = await asyncio.wait_for(
            loop.run_in_executor(None, _fetch_quotes_from_qq, stocks),
            timeout=20
        )
    except asyncio.TimeoutError:
        return {"status": "error", "message": "获取行情超时，请稍后重试", "updated": 0}
    except Exception as e:
        return {"status": "error", "message": f"获取行情失败: {str(e)}", "updated": 0}
    
    # 更新每只股票
    updated_count = 0
    for stock in stocks:
        try:
            quote = quotes.get(stock.code)
            if quote:
                if quote["price"] is not None:
                    stock.current_price = quote["price"]
                if quote["change_pct"] is not None:
                    stock.change_percent = quote["change_pct"]
                stock.last_updated = datetime.now()
                updated_count += 1
        except Exception as e:
            print(f"更新 {stock.code} 失败: {e}")
    
    await db.commit()
    
    return {
        "status": "success",
        "message": f"已刷新 {updated_count}/{len(stocks)} 只股票的数据",
        "updated": updated_count,
        "total": len(stocks)
    }


@router.post("/watchlist/predict")
async def generate_watchlist_predictions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    background_tasks: BackgroundTasks = None
):
    """Do not acknowledge a background task that cannot produce evidence-based analysis."""
    raise HTTPException(status_code=422, detail="资料不足：仅凭报价不能生成投资评级；请查看报告中的来源、反证与触发条件")


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

"""
报告相关 API 路由

支持早报/晚报查询和过滤
"""
from datetime import date, datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, and_
import uuid

from ..models.report import Report, ReportListItem, ReportCreate, ReportType
from ..models.database import ReportModel, get_session_maker

router = APIRouter()


@router.get('/generation/preflight')
async def generation_preflight(report_type: str = 'morning'):
    """Local inspection only; never starts searches/models/TTS."""
    if report_type not in {'morning', 'evening'}:
        raise HTTPException(400, 'report_type must be morning or evening')
    from ..services.edition_pipeline import preflight
    return await preflight(report_type)


@router.get('/generation/runs')
async def generation_runs():
    from ..services.edition_pipeline import ROOT, load_state
    if not ROOT.exists(): return []
    result = []
    for directory in sorted(ROOT.glob('edition-*'), key=lambda p: p.name):
        if directory.is_symlink(): continue
        try:
            state = load_state(directory.name)
        except (OSError, ValueError): continue
        result.append({k: state.get(k) for k in ('id', 'status', 'cutoff', 'updated_at', 'missing', 'app_written')})
    return sorted(result, key=lambda r: r.get('updated_at') or '', reverse=True)[:30]


@router.get('/generation/runs/{identifier}')
async def generation_run(identifier: str):
    from ..services.edition_pipeline import load_state
    try:
        return load_state(identifier)
    except (OSError, ValueError):
        raise HTTPException(404, 'edition not found') from None


@router.get('/generation/runs/{identifier}/receipt')
async def generation_receipt(identifier: str):
    from fastapi.responses import PlainTextResponse
    from ..services.edition_pipeline import load_state, run_path
    try:
        load_state(identifier)
        path = run_path(identifier) / 'receipt.txt'
        if path.is_symlink(): raise ValueError('symlink')
        return PlainTextResponse(path.read_text(), headers={'Cache-Control': 'no-store'})
    except (OSError, ValueError):
        raise HTTPException(404, 'edition receipt not found') from None


async def get_db(request: Request) -> AsyncSession:
    """获取数据库会话"""
    async with request.app.state.session_maker() as session:
        yield session


@router.get("/", response_model=List[ReportListItem])
async def list_reports(
    skip: int = Query(0, ge=0, description="跳过记录数"),
    limit: int = Query(20, ge=1, le=100, description="返回记录数"),
    report_type: Optional[str] = Query(None, description="报告类型: morning/evening"),
    db: AsyncSession = Depends(get_db)
):
    """
    获取报告列表
    - 按创建时间倒序排列
    - 支持分页
    - 支持按报告类型（早报/晚报）过滤
    """
    query = select(ReportModel)
    
    # 按报告类型过滤
    if report_type:
        query = query.where(ReportModel.report_type == report_type)
    
    query = query.order_by(desc(ReportModel.created_at)).offset(skip).limit(limit)
    result = await db.execute(query)
    reports = result.scalars().all()
    
    return [
        ReportListItem(
            id=r.id,
            title=r.title,
            summary=r.summary,
            report_date=r.report_date,
            report_type=ReportType(r.report_type) if r.report_type else ReportType.MORNING,
            podcast_status=r.podcast_status,
            podcast_url=r.podcast_url,
            podcast_duration=r.podcast_duration,
            created_at=r.created_at
        )
        for r in reports
    ]


@router.get("/today", response_model=Optional[Report])
async def get_today_report(
    report_type: Optional[str] = Query(None, description="报告类型: morning/evening，不指定则返回最新的"),
    db: AsyncSession = Depends(get_db)
):
    """
    获取今日报告
    - 可选指定报告类型（早报/晚报）
    - 不指定则返回今日最新的报告
    """
    today = date.today()
    
    query = select(ReportModel).where(ReportModel.report_date == today)
    
    # 按报告类型过滤
    if report_type:
        query = query.where(ReportModel.report_type == report_type)
    
    query = query.order_by(desc(ReportModel.created_at)).limit(1)
    result = await db.execute(query)
    report = result.scalar_one_or_none()
    
    if not report:
        return None
    
    return Report(
        id=report.id,
        title=report.title,
        summary=report.summary,
        content=report.content,
        report_date=report.report_date,
        report_type=ReportType(report.report_type) if report.report_type else ReportType.MORNING,
        core_opinions=report.core_opinions or [],
        sections=[],
        highlights=report.highlights or [],
        cross_border_events=report.cross_border_events or [],
        analysis=report.analysis,
        podcast_url=report.podcast_url,
        podcast_duration=report.podcast_duration,
        podcast_status=report.podcast_status,
        word_count=report.word_count,
        reading_time=report.reading_time,
        news_count=report.news_count,
        cross_border_count=report.cross_border_count or 0,
        created_at=report.created_at,
        updated_at=report.updated_at
    )


@router.get("/today/all")
async def get_today_all_reports(db: AsyncSession = Depends(get_db)):
    """
    获取今日所有报告（早报+晚报）
    """
    today = date.today()
    
    query = select(ReportModel).where(
        ReportModel.report_date == today
    ).order_by(desc(ReportModel.created_at))
    
    result = await db.execute(query)
    reports = result.scalars().all()
    
    return {
        "date": str(today),
        "reports": [
            {
                "id": r.id,
                "title": r.title,
                "summary": r.summary,
                "report_type": r.report_type or "morning",
                "podcast_status": r.podcast_status,
                "podcast_url": r.podcast_url,
                "podcast_duration": r.podcast_duration,
                "created_at": r.created_at.isoformat() if r.created_at else None
            }
            for r in reports
        ],
        "morning_report": next((r.id for r in reports if r.report_type == "morning"), None),
        "evening_report": next((r.id for r in reports if r.report_type == "evening"), None)
    }


@router.get("/date/{report_date}", response_model=List[Report])
async def get_report_by_date(
    report_date: date,
    report_type: Optional[str] = Query(None, description="报告类型: morning/evening"),
    db: AsyncSession = Depends(get_db)
):
    """
    根据日期获取报告
    - 可选指定报告类型
    - 返回该日期的所有报告（早报+晚报）
    """
    query = select(ReportModel).where(ReportModel.report_date == report_date)
    
    if report_type:
        query = query.where(ReportModel.report_type == report_type)
    
    query = query.order_by(desc(ReportModel.created_at))
    result = await db.execute(query)
    reports = result.scalars().all()
    
    if not reports:
        raise HTTPException(status_code=404, detail=f"未找到 {report_date} 的报告")
    
    return [
        Report(
            id=report.id,
            title=report.title,
            summary=report.summary,
            content=report.content,
            report_date=report.report_date,
            report_type=ReportType(report.report_type) if report.report_type else ReportType.MORNING,
            core_opinions=report.core_opinions or [],
            sections=[],
            highlights=report.highlights or [],
            cross_border_events=report.cross_border_events or [],
            analysis=report.analysis,
            podcast_url=report.podcast_url,
            podcast_duration=report.podcast_duration,
            podcast_status=report.podcast_status,
            word_count=report.word_count,
            reading_time=report.reading_time,
            news_count=report.news_count,
            cross_border_count=report.cross_border_count or 0,
            created_at=report.created_at,
            updated_at=report.updated_at
        )
        for report in reports
    ]


@router.get("/{report_id}", response_model=Report)
async def get_report(
    report_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    根据ID获取报告详情
    """
    query = select(ReportModel).where(ReportModel.id == report_id)
    result = await db.execute(query)
    report = result.scalar_one_or_none()
    
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    
    return Report(
        id=report.id,
        title=report.title,
        summary=report.summary,
        content=report.content,
        report_date=report.report_date,
        report_type=ReportType(report.report_type) if report.report_type else ReportType.MORNING,
        core_opinions=report.core_opinions or [],
        sections=[],
        highlights=report.highlights or [],
        cross_border_events=report.cross_border_events or [],
        analysis=report.analysis,
        podcast_url=report.podcast_url,
        podcast_duration=report.podcast_duration,
        podcast_status=report.podcast_status,
        word_count=report.word_count,
        reading_time=report.reading_time,
        news_count=report.news_count,
        cross_border_count=report.cross_border_count or 0,
        created_at=report.created_at,
        updated_at=report.updated_at
    )


@router.post("/", response_model=Report)
async def create_report(
    report_data: ReportCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    创建新报告（主要用于测试和手动创建）
    """
    # 检查是否已存在同日期报告
    existing_query = select(ReportModel).where(ReportModel.report_date == report_data.report_date)
    existing = await db.execute(existing_query)
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"{report_data.report_date} 的报告已存在")
    
    # 计算统计信息
    word_count = len(report_data.content)
    reading_time = max(1, word_count // 400)  # 假设每分钟阅读400字
    
    report = ReportModel(
        id=str(uuid.uuid4()),
        title=report_data.title,
        summary=report_data.summary,
        content=report_data.content,
        report_date=report_data.report_date,
        highlights=[h.model_dump() for h in report_data.highlights] if report_data.highlights else [],
        analysis=report_data.analysis.model_dump() if report_data.analysis else None,
        word_count=word_count,
        reading_time=reading_time,
        news_count=len(report_data.highlights) if report_data.highlights else 0,
        created_at=datetime.now()
    )
    
    db.add(report)
    await db.commit()
    await db.refresh(report)
    
    return Report(
        id=report.id,
        title=report.title,
        summary=report.summary,
        content=report.content,
        report_date=report.report_date,
        core_opinions=[],
        sections=[],
        highlights=report.highlights or [],
        cross_border_events=[],
        analysis=report.analysis,
        podcast_url=report.podcast_url,
        podcast_duration=report.podcast_duration,
        podcast_status=report.podcast_status,
        word_count=report.word_count,
        reading_time=report.reading_time,
        news_count=report.news_count,
        cross_border_count=0,
        created_at=report.created_at,
        updated_at=report.updated_at
    )


@router.delete("/{report_id}")
async def delete_report(
    report_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    删除报告
    """
    query = select(ReportModel).where(ReportModel.id == report_id)
    result = await db.execute(query)
    report = result.scalar_one_or_none()
    
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    
    await db.delete(report)
    await db.commit()
    
    return {"status": "success", "message": "报告已删除"}

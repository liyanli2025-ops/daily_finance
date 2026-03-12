"""
报告相关 API 路由
"""
from datetime import date, datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
import uuid

from ..models.report import Report, ReportListItem, ReportCreate
from ..models.database import ReportModel, get_session_maker

router = APIRouter()


async def get_db(request: Request) -> AsyncSession:
    """获取数据库会话"""
    async with request.app.state.session_maker() as session:
        yield session


@router.get("/", response_model=List[ReportListItem])
async def list_reports(
    skip: int = Query(0, ge=0, description="跳过记录数"),
    limit: int = Query(20, ge=1, le=100, description="返回记录数"),
    db: AsyncSession = Depends(get_db)
):
    """
    获取报告列表
    - 按日期倒序排列
    - 支持分页
    """
    query = select(ReportModel).order_by(desc(ReportModel.report_date)).offset(skip).limit(limit)
    result = await db.execute(query)
    reports = result.scalars().all()
    
    return [
        ReportListItem(
            id=r.id,
            title=r.title,
            summary=r.summary,
            report_date=r.report_date,
            podcast_status=r.podcast_status,
            podcast_duration=r.podcast_duration,
            created_at=r.created_at
        )
        for r in reports
    ]


@router.get("/today", response_model=Optional[Report])
async def get_today_report(db: AsyncSession = Depends(get_db)):
    """
    获取今日报告
    """
    today = date.today()
    query = select(ReportModel).where(ReportModel.report_date == today)
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
        highlights=report.highlights or [],
        analysis=report.analysis,
        podcast_url=report.podcast_url,
        podcast_duration=report.podcast_duration,
        podcast_status=report.podcast_status,
        word_count=report.word_count,
        reading_time=report.reading_time,
        news_count=report.news_count,
        created_at=report.created_at,
        updated_at=report.updated_at
    )


@router.get("/date/{report_date}", response_model=Report)
async def get_report_by_date(
    report_date: date,
    db: AsyncSession = Depends(get_db)
):
    """
    根据日期获取报告
    """
    query = select(ReportModel).where(ReportModel.report_date == report_date)
    result = await db.execute(query)
    report = result.scalar_one_or_none()
    
    if not report:
        raise HTTPException(status_code=404, detail=f"未找到 {report_date} 的报告")
    
    return Report(
        id=report.id,
        title=report.title,
        summary=report.summary,
        content=report.content,
        report_date=report.report_date,
        highlights=report.highlights or [],
        analysis=report.analysis,
        podcast_url=report.podcast_url,
        podcast_duration=report.podcast_duration,
        podcast_status=report.podcast_status,
        word_count=report.word_count,
        reading_time=report.reading_time,
        news_count=report.news_count,
        created_at=report.created_at,
        updated_at=report.updated_at
    )


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
        highlights=report.highlights or [],
        analysis=report.analysis,
        podcast_url=report.podcast_url,
        podcast_duration=report.podcast_duration,
        podcast_status=report.podcast_status,
        word_count=report.word_count,
        reading_time=report.reading_time,
        news_count=report.news_count,
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
        highlights=report.highlights or [],
        analysis=report.analysis,
        podcast_url=report.podcast_url,
        podcast_duration=report.podcast_duration,
        podcast_status=report.podcast_status,
        word_count=report.word_count,
        reading_time=report.reading_time,
        news_count=report.news_count,
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

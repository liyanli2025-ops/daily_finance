"""
播客相关 API 路由
"""

from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pathlib import Path

from ..models.database import ReportModel
from ..config import settings

router = APIRouter()


async def get_db(request: Request) -> AsyncSession:
    """获取数据库会话"""
    async with request.app.state.session_maker() as session:
        yield session


def _get_actual_audio_duration(report_id: str) -> Optional[int]:
    """从实际音频文件获取时长"""
    try:
        # 使用 audio_mixer 模块中已配置好 ffmpeg 路径的 AudioSegment
        from ..services.audio_mixer import AudioSegment
        from pathlib import Path
        # podcasts.py 在 app/routers/ 下，需要向上3级到 backend
        backend_dir = Path(__file__).resolve().parent.parent.parent
        audio_path = backend_dir / "data" / "podcasts" / f"{report_id}.mp3"
        if audio_path.exists():
            audio = AudioSegment.from_mp3(str(audio_path))
            return len(audio) // 1000
    except Exception as e:
        print(f"[WARN] 无法读取音频时长: {e}")
    return None


@router.get("/today")
async def get_today_podcast(db: AsyncSession = Depends(get_db)):
    """
    获取今日播客信息
    """
    from sqlalchemy import desc
    today = date.today()
    query = select(ReportModel).where(ReportModel.report_date == today).order_by(desc(ReportModel.created_at)).limit(1)
    result = await db.execute(query)
    report = result.scalar_one_or_none()
    
    if not report:
        return {"status": "not_found", "message": "今日报告尚未生成"}
    
    # 尝试从实际音频文件获取时长
    actual_duration = _get_actual_audio_duration(report.id) if report.podcast_url else None
    duration = actual_duration if actual_duration else report.podcast_duration
    
    return {
        "report_id": report.id,
        "title": report.title,
        "date": str(report.report_date),
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "podcast_status": report.podcast_status,
        "podcast_url": report.podcast_url,
        "podcast_duration": duration
    }


@router.get("/history")
async def list_podcasts(
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db)
):
    """
    获取播客历史列表
    修复：改为查询有播客URL或正在生成中的报告，按创建时间倒序
    """
    from sqlalchemy import desc, or_
    
    query = (
        select(ReportModel)
        .where(
            or_(
                ReportModel.podcast_url != None,
                ReportModel.podcast_status == "generating",
                ReportModel.podcast_status == "ready"
            )
        )
        .order_by(desc(ReportModel.created_at))
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    reports = result.scalars().all()
    
    return [
        {
            "report_id": r.id,
            "title": r.title,
            "report_date": str(r.report_date),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "podcast_status": r.podcast_status,
            "podcast_url": r.podcast_url,
            "podcast_duration": _get_actual_audio_duration(r.id) if r.podcast_url else r.podcast_duration
        }
        for r in reports
    ]


@router.get("/{report_id}/status")
async def get_podcast_status(
    report_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    获取播客生成状态
    """
    query = select(ReportModel).where(ReportModel.id == report_id)
    result = await db.execute(query)
    report = result.scalar_one_or_none()
    
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    
    return {
        "report_id": report.id,
        "status": report.podcast_status,
        "url": report.podcast_url,
        "duration": report.podcast_duration
    }


@router.get("/{report_id}")
async def get_podcast_detail(
    report_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    获取播客详情（用于播放历史播客）
    """
    query = select(ReportModel).where(ReportModel.id == report_id)
    result = await db.execute(query)
    report = result.scalar_one_or_none()
    
    if not report:
        raise HTTPException(status_code=404, detail="播客不存在")
    
    # 尝试从实际音频文件获取时长（与 /today 和 /history 接口保持一致）
    actual_duration = _get_actual_audio_duration(report.id) if report.podcast_url else None
    duration = actual_duration if actual_duration else report.podcast_duration
    
    return {
        "report_id": report.id,
        "title": report.title,
        "report_date": str(report.report_date),
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "podcast_status": report.podcast_status,
        "podcast_url": report.podcast_url,
        "podcast_duration": duration  # 使用实际文件时长
    }


@router.get("/{report_id}/audio")
async def get_podcast_audio(
    report_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    获取播客音频文件
    """
    query = select(ReportModel).where(ReportModel.id == report_id)
    result = await db.execute(query)
    report = result.scalar_one_or_none()
    
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    
    if report.podcast_status != "ready":
        raise HTTPException(
            status_code=400, 
            detail=f"播客尚未就绪，当前状态: {report.podcast_status}"
        )
    
    # 构建音频文件路径
    audio_path = Path(settings.podcasts_dir) / f"{report_id}.mp3"
    
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="音频文件不存在")
    
    return FileResponse(
        path=str(audio_path),
        media_type="audio/mpeg",
        filename=f"财经日报_{report.report_date}.mp3"
    )


@router.post("/{report_id}/regenerate")
async def regenerate_podcast(
    report_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    重新生成播客
    """
    query = select(ReportModel).where(ReportModel.id == report_id)
    result = await db.execute(query)
    report = result.scalar_one_or_none()
    
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    
    # 更新状态为生成中
    report.podcast_status = "generating"
    await db.commit()
    
    # 在后台重新生成播客
    scheduler = request.app.state.scheduler
    if scheduler:
        background_tasks.add_task(
            scheduler.generate_podcast_for_report,
            report_id
        )
    
    return {
        "status": "started",
        "message": "播客重新生成已启动",
        "report_id": report_id
    }

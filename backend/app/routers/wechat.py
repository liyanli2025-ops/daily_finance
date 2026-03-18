"""
微信公众号订阅管理 API

路由：
- GET    /api/wechat/accounts          获取公众号列表
- POST   /api/wechat/accounts          添加公众号
- PUT    /api/wechat/accounts/{id}     更新公众号
- DELETE /api/wechat/accounts/{id}     删除公众号
- POST   /api/wechat/accounts/{id}/toggle   切换启用/禁用
- POST   /api/wechat/extract-biz       从链接提取 biz
- POST   /api/wechat/test-fetch/{id}   测试采集某个公众号
- GET    /api/wechat/presets            获取预置公众号列表
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.wechat import (
    WechatAccountCreate, WechatAccountUpdate, WechatAccountResponse
)
from ..services.wechat_service import get_wechat_service, PRESET_ACCOUNTS

router = APIRouter()


async def get_db(request: Request) -> AsyncSession:
    """获取数据库会话"""
    session_maker = request.app.state.session_maker
    async with session_maker() as session:
        yield session


@router.get("/accounts")
async def list_accounts(db: AsyncSession = Depends(get_db)):
    """获取所有公众号"""
    service = get_wechat_service()
    accounts = await service.get_all_accounts(db)
    
    results = []
    for acc in accounts:
        results.append({
            "id": acc.id,
            "name": acc.name,
            "biz": acc.biz,
            "description": acc.description,
            "category": acc.category,
            "is_preset": acc.is_preset,
            "enabled": acc.enabled,
            "last_fetched_at": acc.last_fetched_at.isoformat() if acc.last_fetched_at else None,
            "total_articles": acc.total_articles,
            "fetch_fail_count": acc.fetch_fail_count,
            "added_at": acc.added_at.isoformat() if acc.added_at else None,
            "rsshub_url": service._get_rsshub_url(acc.biz),
        })
    
    return results


@router.post("/accounts")
async def add_account(
    data: WechatAccountCreate,
    db: AsyncSession = Depends(get_db)
):
    """添加公众号"""
    service = get_wechat_service()
    
    try:
        account = await service.add_account(
            db,
            name=data.name,
            biz=data.biz,
            description=data.description,
            category=data.category,
        )
        return {
            "id": account.id,
            "name": account.name,
            "biz": account.biz,
            "description": account.description,
            "category": account.category,
            "enabled": account.enabled,
            "is_preset": account.is_preset,
            "message": f"公众号 {account.name} 添加成功"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/accounts/{account_id}")
async def update_account(
    account_id: str,
    data: WechatAccountUpdate,
    db: AsyncSession = Depends(get_db)
):
    """更新公众号"""
    service = get_wechat_service()
    
    update_data = data.model_dump(exclude_unset=True)
    account = await service.update_account(db, account_id, **update_data)
    
    if not account:
        raise HTTPException(status_code=404, detail="公众号不存在")
    
    return {
        "id": account.id,
        "name": account.name,
        "biz": account.biz,
        "enabled": account.enabled,
        "message": "更新成功"
    }


@router.delete("/accounts/{account_id}")
async def delete_account(
    account_id: str,
    db: AsyncSession = Depends(get_db)
):
    """删除公众号"""
    service = get_wechat_service()
    
    success = await service.delete_account(db, account_id)
    if not success:
        raise HTTPException(status_code=404, detail="公众号不存在")
    
    return {"message": "删除成功"}


@router.post("/accounts/{account_id}/toggle")
async def toggle_account(
    account_id: str,
    db: AsyncSession = Depends(get_db)
):
    """切换启用/禁用"""
    service = get_wechat_service()
    
    account = await service.toggle_account(db, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="公众号不存在")
    
    return {
        "id": account.id,
        "name": account.name,
        "enabled": account.enabled,
        "message": f"{'已启用' if account.enabled else '已禁用'} {account.name}"
    }


@router.post("/extract-biz")
async def extract_biz(url: str):
    """
    从微信文章链接中提取 __biz
    
    用户只需要粘贴文章链接，自动解析出 biz
    """
    service = get_wechat_service()
    biz = service.extract_biz_from_url(url)
    
    if not biz:
        raise HTTPException(
            status_code=400, 
            detail="无法从链接中提取 __biz 参数，请确认是有效的微信公众号文章链接"
        )
    
    return {
        "biz": biz,
        "rsshub_url": service._get_rsshub_url(biz),
        "message": f"提取成功: {biz}"
    }


@router.post("/test-fetch/{account_id}")
async def test_fetch(
    account_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    测试采集某个公众号
    
    返回最新文章（不存储，仅用于验证源是否可用）
    """
    from ..models.database import WechatAccountModel
    from sqlalchemy import select
    
    result = await db.execute(
        select(WechatAccountModel).where(WechatAccountModel.id == account_id)
    )
    account = result.scalar_one_or_none()
    
    if not account:
        raise HTTPException(status_code=404, detail="公众号不存在")
    
    service = get_wechat_service()
    articles = await service.fetch_articles(account.biz, account.name)
    
    return {
        "account_name": account.name,
        "biz": account.biz,
        "article_count": len(articles),
        "articles": [
            {
                "title": a.title,
                "summary": a.summary[:200] if a.summary else "",
                "source_url": a.source_url,
                "published_at": a.published_at.isoformat(),
            }
            for a in articles[:5]  # 只返回前5篇
        ],
        "status": "success" if articles else "no_articles",
        "message": f"获取到 {len(articles)} 篇文章" if articles else "未获取到文章，RSSHub源可能暂时不可用"
    }


@router.get("/presets")
async def list_presets():
    """获取预置公众号列表"""
    return [
        {
            "name": p["name"],
            "biz": p["biz"],
            "description": p["description"],
            "category": p["category"],
        }
        for p in PRESET_ACCOUNTS
    ]

"""Per-generation request cap and private usage ledger; no prompts, keys or responses."""
from contextvars import ContextVar
import asyncio
from functools import wraps
import json
import os
from pathlib import Path
import uuid

from .time_context import china_now

_run=ContextVar('finance_model_run',default=None)
ROOT=Path(__file__).resolve().parents[2]/'data/diagnostics'


def budgeted_generation(func):
    @wraps(func)
    async def wrapped(*args,**kwargs):
        if _run.get() is not None:
            return await func(*args,**kwargs)
        from ..config import settings
        owner=args[0]
        if not hasattr(owner,'_edition_guard'):
            owner._edition_guard=asyncio.Lock()
        if owner._edition_guard.locked():
            print('[SKIP] 已有早报或晚报正在生成，拒绝并发重复扣费',flush=True)
            return
        async with owner._edition_guard:
            token=_run.set(dict(id=uuid.uuid4().hex,calls=0,limit=settings.model_max_calls_per_report))
            try:
                return await func(*args,**kwargs)
            finally:
                _run.reset(token)
    return wrapped


def reserve_call():
    run=_run.get()
    if run is None:
        return
    if run['calls']>=run['limit']:
        raise RuntimeError('本期模型调用次数已达上限，停止额外扣费；保留诊断后人工检查')
    run['calls']+=1


def record_usage(task,route,max_tokens,response=None,error=None,elapsed=None,directory=None):
    def count(value):
        return value if type(value) is int and value>=0 else None
    payload={}
    if response is not None:
        try:
            value=response.json()
            if isinstance(value,dict):
                payload=value
        except (ValueError,TypeError):
            pass
    usage=payload.get('usage') or {}
    if not isinstance(usage,dict):
        usage={}
    run=_run.get()
    row=dict(at=china_now().isoformat(),run_id=run['id'] if run else None,
             task=task,provider=route.provider,model=route.model,max_output_tokens=max_tokens,
             http_status=response.status_code if response is not None else None,
             transport_error=type(error).__name__ if error else None,
             input_tokens=count(usage.get('input_tokens',usage.get('prompt_tokens'))),
             output_tokens=count(usage.get('output_tokens',usage.get('completion_tokens'))),
             cache_read_tokens=count(usage.get('cache_read_input_tokens')),
             cache_write_tokens=count(usage.get('cache_creation_input_tokens')),
             elapsed_seconds=round(elapsed,3) if elapsed is not None else None,
             billing_note='Token用量不等于账单；服务商实际扣费另行核对，未知用量保留null')
    root=Path(directory) if directory is not None else ROOT
    try:
        root.mkdir(parents=True,exist_ok=True,mode=0o700)
        root.chmod(0o700)
        target=root/('model-usage-'+china_now().date().isoformat()+'.jsonl')
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
        try:
            os.write(fd,(json.dumps(row,ensure_ascii=False)+'\n').encode('utf-8'))
        finally:
            os.close(fd)
    except OSError as failure:
        print('[模型用量] 记录失败：'+type(failure).__name__,flush=True)
    return row

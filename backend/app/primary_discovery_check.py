"""Zero-network preflight for model-led collection; no paid execution flag."""
import argparse
import asyncio
import hashlib
import json

from .config import settings
from .services.primary_discovery import Limits,prompt
from .services.time_context import china_now
from .services.watchlist_repository import read_app_watchlist
from .services.web_research import capabilities


async def main(show_prompt=False):
    limits=Limits(search_calls=min(4,settings.research_web_search_max_requests))
    stocks=await read_app_watchlist();now=china_now();value=prompt(stocks,now,limits)
    from .services.model_gateway import MODEL_PAUSE_FILE
    result=dict(mode='free_model_led_collection_preflight',checked_at=now.isoformat(),watchlist=stocks,
        search=capabilities(),model_maintenance_paused=MODEL_PAUSE_FILE.exists(),limits=limits.__dict__,
        prompt_characters=len(value),prompt_sha256=hashlib.sha256(value.encode()).hexdigest(),
        http_requests_performed=0,model_requests_performed=0,tts_requests_performed=0,
        next_stage='requires_reviewed_paid_runner_and_real_collection_quality_acceptance',
        limitation='只读App名单并检查共享提示词和工具协议；没有执行搜索、验证模型判断或恢复自动化。没有收费运行参数。')
    if show_prompt:result['prompt']=value
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--show-prompt',action='store_true')
    asyncio.run(main(parser.parse_args().show_prompt))

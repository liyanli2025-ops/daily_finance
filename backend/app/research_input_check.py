"""Read cached research and preview actual initial ranges; no fetch or model calls."""
import argparse
import asyncio
from collections import Counter
import json


def inspect(stocks,hub=None,details=False):
    from .services.research_hub import ResearchHub
    hub=hub or ResearchHub()
    contexts=hub.load(stocks)
    prompt,evidence=hub.prompt(stocks,max_characters=8000)
    materials={item.id:item for item in evidence}
    ledger=hub.prompt_reading
    result=dict(mode='cached_research_free_preview',http_requests_performed=0,model_requests_performed=0,
        watchlist=[dict(key=row['key'],name=row['name'],cached_materials=len(row.get('materials',[])),
            collection_status=row.get('coverage',{}).get('collection',{}).get('status','unknown')) for row in contexts],
        cached_materials=sum(len(row.get('materials',[])) for row in contexts),
        prepared_materials=len(evidence),prepared_unique_source_documents=len({item.source_id for item in evidence}),prompt_characters=len(prompt),prompt_character_budget=8000,
        prepared_original_characters=sum(row['selected_characters'] for row in ledger),
        reading_status_counts=dict(Counter(row['status'] for row in ledger)),
        prepared_kind_counts=dict(Counter(item.kind for item in evidence)),
        prepared_titles=[dict(id=item.id,source_id=item.source_id,title=item.title,kind=item.kind,scope=item.scope) for item in evidence][:12],
        additional_prepared_titles=max(0,len(evidence)-12),
        limitation='只回放当前有效研究缓存和正式8000字符初始底稿分配；不采集、不调用模型/TTS、不写App或恢复调度。'
        '缓存过期不自动补采；prepared表示已准备而非模型读过。存储文本可能本来只是摘要/前部/带页码节选，覆盖存储文本不等于读完原报告。')
    if details:
        result['initial_research_reading']=ledger
        result['range_previews']=[dict(id=row['id'],scope=row['scope'],
            text='\n'.join(materials[row['id']].body[a:b] for a,b in row['ranges'])[:180])
            for row in ledger if row['status']=='provided'][:12]
    return result


async def main(details=False):
    from .services.watchlist_repository import refresh_app_watchlist,watchlist_signature,assert_watchlist_current
    watchlist=await refresh_app_watchlist()
    stocks=watchlist.get_all_stocks();signature=watchlist_signature(stocks)
    result=inspect(stocks,details=details)
    await assert_watchlist_current(signature)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--details',action='store_true',help='显示研究范围台账和最多12段180字符预览；只是显示截短，不是入模截短')
    asyncio.run(main(parser.parse_args().details))

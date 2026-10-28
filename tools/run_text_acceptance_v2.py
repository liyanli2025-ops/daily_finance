"""Run from deployed backend: one capped text trial, with the whole saved pool.

No App report writes or audio. Default is free preflight; --run authorizes models.
"""
import argparse
import asyncio
from datetime import datetime,timedelta
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path.cwd()))

from app.config import settings
from app.selection_check import candidates
from app.services.ai_analyzer import AIAnalyzerService
from app.services.model_usage import budgeted_generation,_run
from app.services.research_hub import save_json
from app.services.time_context import china_now,china_today
from app.services.watchlist_repository import read_app_watchlist


def load(root,now):
    folder=root/'data/radar'
    raw=(folder/'news-acceptance.json').read_bytes()
    snapshot=json.loads(raw)
    age=now-datetime.fromisoformat(snapshot['collected_at'])
    if not timedelta()<=age<=timedelta(hours=2):
        raise RuntimeError('原采集快照超过2小时或时间异常，停止本次模型请求')
    replay=json.loads((folder/'selection-replay.json').read_text(encoding='utf-8'))
    digest=hashlib.sha256(raw).hexdigest()
    if replay['snapshot_sha256']!=digest:
        raise RuntimeError('重选结果与原始快照不匹配，停止模型请求')
    pool=candidates(snapshot)
    by_id={row.id:row for row in pool}
    selected=[row['id'] for row in replay['selection']['articles'] if row.get('selected')]
    if not selected or len(selected)!=len(set(selected)) or set(selected)-set(by_id):
        raise RuntimeError('重选清单为空、重复或缺少原始正文')
    if not replay.get('news_input','').strip():
        raise RuntimeError('缺少冻结的重选正文输入')
    technical=json.loads((folder/'technical.json').read_text(encoding='utf-8'))
    if not timedelta()<=now-datetime.fromisoformat(technical['collected_at'])<=timedelta(hours=2):
        raise RuntimeError('日线技术快照已过期，停止模型请求')
    return snapshot,replay,pool,[by_id[key] for key in selected],digest,technical


class SnapshotAnalyzer(AIAnalyzerService):
    def __init__(self,replay,selected,state,metadata):
        super().__init__()
        self.replay=replay;self.selected=selected;self.state=state
        self.metadata=metadata;self.calls=0;self.run_id=None;self.phase='preflight'

    def _prepare_news_summary_with_sentiment(self,news):
        self._selected_evidence_news=list(self.selected)
        return self.replay['news_input']

    async def _call_ai(self,prompt,max_tokens=4000,task='analysis'):
        self.phase=task
        save_json(self.state,dict(self.metadata,status='running',phase=task,
            http_requests_so_far=_run.get()['calls']))
        print('[文字验收] 当前阶段：'+task,flush=True)
        return await super()._call_ai(prompt,max_tokens,task)

    @budgeted_generation
    async def once(self,pool):
        try:
            # Only refresh current microstructure once; no broad news recollection.
            from app.services.microstructure import MicrostructureRadar
            from app.services.watchlist_repository import refresh_app_watchlist
            service=await refresh_app_watchlist()
            save_json(self.state,dict(self.metadata,status='running',phase='current_market_context'))
            await asyncio.to_thread(MicrostructureRadar().collect,service.get_all_stocks(),40)
            from app.services.scheduler import SchedulerService
            # Passing ALL candidates is essential: the episode decorator creates
            # its retrieval workspace before the frozen initial input is used.
            return await self.generate_daily_report(pool,
                is_trading_day=SchedulerService().is_trading_day(china_today()))
        finally:
            self.calls=_run.get()['calls']
            self.run_id=_run.get()['id']


async def main(root=None,run=False):
    root=Path(root) if root is not None else Path.cwd()
    snapshot,replay,pool,selected,key,technical=load(root,china_now())
    current=await read_app_watchlist()
    if {row['market']+':'+row['code'] for row in current}!=set(technical['watchlist']):
        raise RuntimeError('当前App自选股与技术快照不一致，停止模型请求')
    folder=root/'data/diagnostics';folder.mkdir(parents=True,exist_ok=True,mode=0o700);folder.chmod(0o700)
    base=folder/('text-acceptance-'+key[:20])
    state=base.with_suffix('.json');output=base.with_suffix('.md');marker=base.with_suffix('.started')
    latest=folder/'text-acceptance-latest.json'
    metadata=dict(snapshot_collected_at=snapshot['collected_at'],snapshot_sha256=key,
        candidate_count=len(pool),initial_articles=len(selected),max_http_requests=min(settings.model_max_calls_per_report,4),
        output=str(output),state=str(state),mode='文字验收，无TTS、无App报告写入')
    if marker.exists() or state.exists() or output.exists():
        print('该快照已有验收记录，禁止重复扣费。状态：'+str(state),flush=True)
        if state.exists():print(state.read_text(encoding='utf-8'),flush=True)
        return
    if not run:
        print(json.dumps(dict(metadata,status='preflight_ok',note='未调用模型；--run才开始最多4次HTTP请求（含重试）'),ensure_ascii=False,indent=2))
        return
    fd=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
    settings.model_max_calls_per_report=metadata['max_http_requests']
    save_json(state,dict(metadata,status='started'));save_json(latest,dict(metadata,status='started'))
    analyzer=SnapshotAnalyzer(replay,selected,state,metadata)
    print('开始文字验收：全部候选可检索，最多4次模型HTTP请求（含重试），不生成音频。',flush=True)
    try:
        report=await asyncio.wait_for(analyzer.once(pool),900)
        if report is None:raise RuntimeError('未返回报告')
        fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as stream:stream.write(report.content)
        result=dict(metadata,status='passed_model_review',http_requests=analyzer.calls,run_id=analyzer.run_id,
            limitation='模型审查通过不代表事实已独立核实、预测准确或用户听感验收通过')
    except Exception as error:
        reasons={'报告修复后复核仍未通过，停止发布':'repair_review_failed',
                 '本期模型调用次数已达上限，停止额外扣费；保留诊断后人工检查':'request_budget_exhausted'}
        reason=reasons.get(str(error),'see_saved_diagnostics')
        if str(error).startswith('模型输入字符数'):reason='input_character_guard'
        result=dict(metadata,status='failed',http_requests=analyzer.calls,run_id=analyzer.run_id,
            last_phase=analyzer.phase,error_type=type(error).__name__,failure_reason=reason,
            note='保留开始标记和生成/审查检查点；不要删除标记重新扣费。错误详情查看本次日志。')
        save_json(state,result);save_json(latest,result)
        raise
    save_json(state,result);save_json(latest,result)
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--run',action='store_true')
    args=parser.parse_args()
    asyncio.run(main(run=args.run))

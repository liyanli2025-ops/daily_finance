"""Bounded public-data preparation after an App addition. Never calls a model."""
import asyncio
from contextlib import contextmanager
from datetime import datetime,timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

from .research_hub import save_json
from .time_context import china_now
from .watchlist_repository import read_app_watchlist

DATA=Path(__file__).resolve().parents[2]/'data'


@contextmanager
def exclusive(path):
    """Nonblocking OS lock; the OS releases it if the process is interrupted."""
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    descriptor=os.open(path,os.O_RDWR|os.O_CREAT,0o600)
    acquired=False
    try:
        if sys.platform=='win32':
            import msvcrt
            if os.fstat(descriptor).st_size==0:os.write(descriptor,b'0')
            os.lseek(descriptor,0,os.SEEK_SET)
            try:msvcrt.locking(descriptor,msvcrt.LK_NBLCK,1);acquired=True
            except OSError:pass
        else:
            import fcntl
            try:fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB);acquired=True
            except BlockingIOError:pass
        yield acquired
    finally:
        if acquired:
            if sys.platform=='win32':
                os.lseek(descriptor,0,os.SEEK_SET);msvcrt.locking(descriptor,msvcrt.LK_UNLCK,1)
            else:fcntl.flock(descriptor,fcntl.LOCK_UN)
        os.close(descriptor)


async def prepare_resources(record,checkpoint):
    from .watchlist_service import WatchlistStock
    from .technical_radar import TechnicalRadar
    from .research_hub import ResearchHub
    from .media_sources import MediaCollector
    from .news_archive import NewsArchive
    from .news_quality import company_focus
    stock=WatchlistStock(record['code'],record['name'],record['market'],source='database')
    current=await checkpoint('正在补历史行情')
    stocks=[WatchlistStock(row['code'],row['name'],row['market'],source='database') for row in current]
    technical=await asyncio.to_thread(TechnicalRadar().collect,stocks,35)
    from .watchlist_sources import symbol_for
    daily=next((row for row in technical['instruments'] if row['symbol']==symbol_for(stock)),{})
    history=len(daily.get('bars',[])) if daily.get('status')=='ok' else 0
    await checkpoint('正在补公司业务、公告及财务资料')
    hub=ResearchHub()
    research=await asyncio.to_thread(hub.collect_stock,stock,75)
    await checkpoint('正在补公司与行业近期新闻')
    profiles={research['key']:research['profile']} if research.get('profile') else {}
    news,coverage=await asyncio.to_thread(MediaCollector().collect,[stock],profiles,72,25)
    await checkpoint('正在保存补采结果')
    # Public originals enter the same short-lived archive used by normal editions.
    await asyncio.to_thread(NewsArchive().save,news,coverage,'watchlist_preparation')
    company=sum(company_focus(item,stock) for item in news)
    return dict(history=dict(status='ok' if history>=60 else 'partial' if history else 'unavailable',
        observations=history,as_of=daily.get('metrics',{}).get('as_of')),
        profile=dict(status='ok' if research.get('profile') else 'unavailable'),
        news=dict(status='ok' if company else 'no_company_material',company_articles=company,
            total_articles=len(news),window_hours=72),
        research=dict(materials=len(research.get('materials',[])),coverage=research.get('coverage',{})))


class PreparationService:
    def __init__(self,base=None,reader=None,worker=None):
        self.base=Path(base) if base is not None else DATA
        self.root=self.base/'radar/watchlist-preparation'
        self.reader=reader or (lambda:read_app_watchlist(include_identity=True))
        self.worker=worker or prepare_resources
        self.semaphore=asyncio.Semaphore(1)

    def paused(self):return (self.base/'.automation-paused').exists()

    def path(self,record):
        key=hashlib.sha256(json.dumps({field:record[field] for field in ('id','code','market','name')},
            ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        return self.root/(key+'.json')

    def read(self,record):
        try:
            value=json.loads(self.path(record).read_text(encoding='utf-8'))
            if isinstance(value,dict) and value.get('owner')=='finance-watchlist-preparation-v1':return value
        except (OSError,ValueError,TypeError):pass
        return {}

    def status(self,record):
        if self.paused():return dict(status='paused',message='维护暂停中；股票已保存，资料补采未启动',coverage={})
        state=self.read(record)
        if not state:return dict(status='not_prepared',message='尚无单独补采记录；常规资料以本期采集为准',coverage={})
        if state.get('status')=='paused':
            return dict(status='not_prepared',message='维护已结束，补采尚未恢复；可手动准备资料',coverage=state.get('coverage',{}))
        try:
            age=china_now()-datetime.fromisoformat(state['updated_at'])
            if not timedelta()<=age<timedelta(hours=2):
                return dict(status='stale',message='补采记录已过期；需重新准备当前资料',coverage={})
            if state['status']=='collecting' and age>timedelta(minutes=3):
                return dict(status='interrupted',message='补采未及时结束；可点击补采检查或恢复',coverage={})
        except (KeyError,TypeError,ValueError):
            return dict(status='failed',message='补采记录不可读；未确认资料完整',coverage={})
        return {key:state[key] for key in ('status','message','updated_at','coverage') if key in state}

    def queue(self,record):
        if self.paused():return self.status(record),None
        path=self.path(record)
        try:
            with exclusive(path.with_suffix('.lock')) as locked:
                if not locked:return self.status(record),None
                state=self.read(record)
                if state.get('status')=='queued':return self.status(record),state['attempt']
                if state.get('status') in {'complete','partial','failed'}:
                    age=china_now()-datetime.fromisoformat(state['updated_at'])
                    if timedelta()<=age<timedelta(minutes=15):
                        status=self.status(record)
                        status['message']='15分钟内复用本次补采结果。'+status['message']
                        return status,None
                # A collecting record with a free OS lock was interrupted. A new
                # explicit add/retry can recover it, rather than retry on every GET.
                attempt=uuid.uuid4().hex
                save_json(path,dict(owner='finance-watchlist-preparation-v1',record=record,attempt=attempt,
                    status='queued',message='已加入资料补采队列',updated_at=china_now().isoformat(),coverage={}))
                return self.status(record),attempt
        except (OSError,ValueError,KeyError):
            return dict(status='failed',message='股票已保存，补采未能入队；请稍后检查',coverage={}),None

    async def run(self,record,attempt):
        async with self.semaphore:
            path=self.path(record)
            with exclusive(path.with_suffix('.lock')) as locked:
                state=self.read(record)
                if not locked or state.get('attempt')!=attempt or state.get('status')!='queued':return
                def update(status,message,coverage=None):
                    state.update(status=status,message=message,updated_at=china_now().isoformat())
                    if coverage is not None:state['coverage']=coverage
                    save_json(path,state)
                async def checkpoint(message):
                    if self.paused():raise PreparationPaused()
                    rows=await self.reader()
                    if not any(all(row.get(key)==record[key] for key in ('id','code','market','name')) for row in rows):
                        raise PreparationCancelled()
                    update('collecting',message)
                    return rows
                try:
                    await checkpoint('正在准备资料')
                    coverage=await asyncio.wait_for(self.worker(record,checkpoint),180)
                    await checkpoint('正在确认当前自选股')
                    complete=(all(coverage.get(field,{}).get('status')=='ok' for field in ('history','profile','news'))
                        and not any(item.get('status') in {'failed','deferred','unsupported','not_collected'}
                            for item in coverage.get('research',{}).get('coverage',{}).values()))
                    gaps=[]
                    if coverage.get('history',{}).get('status')!='ok':
                        gaps.append('可用日线仅'+str(coverage.get('history',{}).get('observations',0))+'期')
                    if coverage.get('profile',{}).get('status')!='ok':gaps.append('业务资料未取得')
                    if coverage.get('news',{}).get('status')!='ok':gaps.append('近72小时未取得公司专属新闻')
                    if not complete and not gaps:gaps.append('部分公司资料采集未完成')
                    update('complete' if complete else 'partial',
                        '本次补采完成；资料是否足够仍需分析核对' if complete else '补采完成：'+'；'.join(gaps),coverage)
                except PreparationPaused:update('paused','维护暂停，已停止后续补采阶段')
                except PreparationCancelled:update('cancelled','该股票已移除或资料标识改变，本次补采停止')
                except asyncio.CancelledError:
                    update('interrupted','补采进程中断；结果尚未确认');raise
                except Exception as error:
                    update('failed','补采未完成（'+type(error).__name__+'）；不据此判断没有相关新闻')


class PreparationPaused(RuntimeError):pass
class PreparationCancelled(RuntimeError):pass

_service=None


def get_preparation_service():
    global _service
    if _service is None:_service=PreparationService()
    return _service

"""Per-episode, short-lived evidence and explicit lexical retrieval. No model calls."""
from contextvars import ContextVar
from datetime import datetime,timedelta
from functools import wraps
import json
from pathlib import Path
import re
import shutil
import tempfile

from .news_quality import excluded_reason,reading_scope
from .research_hub import save_json,Material,recent_opinion
from .time_context import china_now

ROOT=Path(__file__).resolve().parents[2]/'data/episodes'
_current=ContextVar('episode_workspace',default=None)


def terms(query):
    result=set()
    for word in re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z0-9]+',query.casefold()):
        result.add(word)
        if re.fullmatch(r'[\u4e00-\u9fff]+',word):result.update(word[i:i+2] for i in range(len(word)-1))
    return result


def body(item):
    return item.body if isinstance(item,Material) else item.content


class EpisodeWorkspace:
    def __init__(self,news=(),root=None,now=None):
        self.root=Path(root) if root is not None else ROOT
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path=Path(tempfile.mkdtemp(prefix='episode-',dir=self.root))
        self.now=now or china_now();self.documents={};self.accessed={};self.journal=[]
        self.meta=dict(owner='finance-episode-v1',created_at=self.now.isoformat(),
            expires_at=(self.now+timedelta(hours=24)).isoformat(),status='working')
        save_json(self.path/'meta.json',self.meta)
        self.add(news)

    def add(self,news):
        for item in news:
            if isinstance(item,Material):
                from .news_quality import article_url
                if (not article_url(item.source_url) or len(item.body.strip())<80
                        or not recent_opinion(item.kind,item.published_at,self.now)
                        or (item.published_at and item.published_at>self.now)):continue
            else:
                if not all(hasattr(item,field) for field in ('content','title','source','source_url','published_at')):continue
                if excluded_reason(item):continue
            if item.id in self.documents and body(self.documents[item.id])!=body(item):
                raise ValueError('episode_evidence_id_collision')
            self.documents[item.id]=item
        save_json(self.path/'materials.json',[dict(**self.metadata(item),text=body(item)) for item in self.documents.values()])

    def metadata(self,item):
        from .evidence import publication_label
        return dict(id=item.id,title=item.title,source=item.source,url=item.source_url,
            published=(item.published_at.isoformat() if item.published_at else None) if isinstance(item,Material) else publication_label(item),
            reading_scope=item.reading_status if isinstance(item,Material) else reading_scope(item),
            kind=getattr(item,'kind','news'),scope=getattr(item,'scope',''),period=getattr(item,'period',''),
            characters=len(body(item)))

    def search(self,query,limit=5):
        tokens=terms(query)
        ranked=[]
        for item in self.documents.values():
            title=item.title.casefold();text=body(item).casefold()
            score=sum(4*(token in title)+(token in text) for token in tokens)
            if score:ranked.append((score,item))
        ranked.sort(key=lambda row:(row[0],row[1].published_at.isoformat() if row[1].published_at else ''),reverse=True)
        rows=[]
        for score,item in ranked[:limit]:
            text=body(item)
            positions=[text.casefold().find(token) for token in tokens if token in text.casefold()]
            offset=max(0,min(positions)-150) if positions else 0
            self.accessed[item.id]=item
            rows.append(dict(**self.metadata(item),score=score,offset=offset,
                excerpt=text[offset:offset+800],has_more=offset+800<len(text)))
        return dict(method='标题/正文词项匹配，非语义检索或事实核实',results=rows)

    def read(self,identifier,offset=0,characters=6000):
        if identifier not in self.documents:return dict(status='not_found',id=identifier)
        if type(offset) is not int or offset<0 or type(characters) is not int or not 1<=characters<=6000:
            raise ValueError('invalid_evidence_read_range')
        item=self.documents[identifier];self.accessed[identifier]=item
        return dict(status='ok',**self.metadata(item),offset=offset,
            text=body(item)[offset:offset+characters],has_more=offset+characters<len(body(item)))

    def record(self,request,result):
        self.journal.append(dict(request=request,result=result))
        # Journal contains evidence excerpts; it has the same short lifetime.
        save_json(self.path/'retrieval.json',self.journal)

    def finish(self,success):
        self.meta['status']='complete' if success else 'failed'
        if success:
            save_json(self.path/'sources.json',[self.metadata(item) for item in self.accessed.values()])
            for name in ('materials.json','retrieval.json'):
                (self.path/name).unlink(missing_ok=True)
        save_json(self.path/'meta.json',self.meta)

    @staticmethod
    def prune(root=None,now=None):
        root=(Path(root) if root is not None else ROOT).resolve();now=now or china_now()
        removed=0
        if not root.is_dir():return removed
        for folder in root.glob('episode-*'):
            # Verify the resolved absolute path before recursive removal.
            if folder.is_symlink() or folder.resolve().parent!=root:continue
            try:
                meta=json.loads((folder/'meta.json').read_text(encoding='utf-8'))
                if meta.get('owner')!='finance-episode-v1' or datetime.fromisoformat(meta['expires_at'])>now:continue
            except (OSError,ValueError,KeyError,TypeError):continue
            shutil.rmtree(folder.resolve());removed+=1
        return removed


def current_workspace():return _current.get()


def episode_generation(func):
    @wraps(func)
    async def wrapped(*args,**kwargs):
        if _current.get() is not None:return await func(*args,**kwargs)
        EpisodeWorkspace.prune()
        news=list(kwargs.get('news_list',args[1] if len(args)>1 else []) or [])
        cross=kwargs.get('cross_border_news',args[2] if len(args)>2 else [])
        if isinstance(cross,list):news+=cross
        workspace=EpisodeWorkspace(news);token=_current.set(workspace);success=False
        try:
            result=await func(*args,**kwargs);success=result is not None
            return result
        finally:
            try:workspace.finish(success)
            except OSError as error:
                # Retain the original generation result/error; expiry marker already exists.
                print('[当期资料] 收尾清理失败，等待下次过期清理：'+type(error).__name__,flush=True)
            finally:_current.reset(token)
    return wrapped

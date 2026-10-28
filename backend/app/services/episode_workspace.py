"""Per-episode, short-lived evidence and explicit lexical retrieval. No model calls."""
from contextvars import ContextVar
from datetime import datetime,timedelta
from functools import wraps
import json
from pathlib import Path
import re
import shutil
import tempfile
import hashlib

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
        self.document_hashes={};self.prepared={};self.confirmed={};self.completed_rounds=0
        self.cited_ids=set();self.claim_refs=[]
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
            fingerprint=hashlib.sha256(body(item).encode('utf-8')).hexdigest()
            if item.id in self.documents and self.document_hashes[item.id]!=fingerprint:
                raise ValueError('episode_evidence_id_collision')
            self.documents[item.id]=item
            self.document_hashes[item.id]=fingerprint
        save_json(self.path/'materials.json',[dict(**self.metadata(item),text=body(item)) for item in self.documents.values()])

    def metadata(self,item):
        from .evidence import publication_label
        return dict(id=item.id,title=item.title,source=item.source,url=item.source_url,
            published=(item.published_at.isoformat() if item.published_at else None) if isinstance(item,Material) else publication_label(item),
            reading_scope=item.reading_status if isinstance(item,Material) else reading_scope(item),
            kind=getattr(item,'kind','news'),scope=getattr(item,'scope',''),period=getattr(item,'period',''),
            characters=len(body(item)))

    def prepare_ranges(self,identifier,ranges,channel):
        """Record assembled/tool-returned text; this alone is NOT a model read."""
        if channel not in {'initial_news','initial_research','initial_cross','search_excerpt','read_excerpt'}:
            raise ValueError('unknown_exposure_channel')
        if identifier not in self.documents:raise ValueError('exposure_source_not_in_pool')
        text=body(self.documents[identifier])
        if hashlib.sha256(text.encode('utf-8')).hexdigest()!=self.document_hashes[identifier]:
            raise ValueError('exposure_source_changed')
        if not isinstance(ranges,(list,tuple)):raise ValueError('invalid_exposure_ranges')
        checked=[]
        for span in ranges:
            if not isinstance(span,(list,tuple)) or len(span)!=2:raise ValueError('invalid_exposure_range')
            start,end=span
            if type(start) is not int or type(end) is not int or not 0<=start<end<=len(text):
                raise ValueError('invalid_exposure_range')
            checked.append((start,end,channel))
        self.prepared.setdefault(identifier,set()).update(checked)

    def confirm_analysis_response(self):
        """Analysis returned complete text; not proof of attention or fact-checking."""
        for identifier,ranges in self.prepared.items():
            self.confirmed.setdefault(identifier,set()).update(ranges)
        self.completed_rounds+=1

    @staticmethod
    def merged_ranges(ranges):
        result=[]
        for start,end,*_ in sorted(ranges):
            if result and start<=result[-1][1]:result[-1][1]=max(end,result[-1][1])
            else:result.append([start,end])
        return result

    def usage(self,content=None,notes=None):
        if content is not None:self.cited_ids=set(re.findall(r'\[N:([^\]\s]+)\]',content))
        if notes is not None:
            self.claim_refs=[dict(claim=row.get('claim',''),horizon=row.get('horizon',''),
                support_ids=row.get('support_ids',[]),counterevidence_ids=row.get('counterevidence_ids',[])) for row in notes]
        claims={key for row in self.claim_refs for field in ('support_ids','counterevidence_ids') for key in row[field]}
        rows=[]
        for identifier in sorted(set(self.prepared)|self.cited_ids|claims):
            item=self.documents.get(identifier)
            if item is None:
                rows.append(dict(id=identifier,in_pool=False,cited=identifier in self.cited_ids,confirmed_ranges=[]))
                continue
            prepared=self.merged_ranges(self.prepared.get(identifier,[]))
            confirmed=self.merged_ranges(self.confirmed.get(identifier,[]))
            size=len(body(item));covered=sum(end-start for start,end in confirmed)
            rows.append(dict(**self.metadata(item),in_pool=True,stored_text_sha256=self.document_hashes[identifier],
                prepared_ranges=prepared,confirmed_ranges=confirmed,
                confirmed_stored_characters=covered,unprovided_stored_characters=size-covered,
                model_input_scope='all_stored_text' if size and covered==size else 'stored_fragment' if covered else 'not_confirmed',
                channels=sorted({channel for _,_,channel in self.prepared.get(identifier,[])}),cited=identifier in self.cited_ids))
        return dict(pool_count=len(self.documents),prepared_sources=sum(bool(r) for r in self.prepared.values()),
            confirmed_sources=sum(bool(r) for r in self.confirmed.values()),completed_analysis_rounds=self.completed_rounds,
            cited_sources=len(self.cited_ids),decision_sources=len(claims),decisions=self.claim_refs,sources=rows,
            cited_without_confirmed_text=sorted(key for key in self.cited_ids if not self.confirmed.get(key)),
            decision_sources_without_confirmed_text=sorted(key for key in claims if not self.confirmed.get(key)),
            limitation='prepared仅是已组装片段；confirmed表示对应分析请求返回完整回复，不能证明模型认真读过或事实正确。覆盖率只相对存储文本，摘要/节选100%也不是读完原文。未完成请求的接收情况未知。')

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
            self.prepare_ranges(item.id,[(offset,min(offset+800,len(text)))],'search_excerpt')
            rows.append(dict(**self.metadata(item),score=score,offset=offset,
                excerpt=text[offset:offset+800],has_more=offset+800<len(text),
                model_input_scope='tool_return_fragment' if offset or len(text)>800 else 'all_stored_text'))
        return dict(method='标题/正文词项匹配，非语义检索或事实核实',results=rows)

    def read(self,identifier,offset=0,characters=6000):
        if identifier not in self.documents:return dict(status='not_found',id=identifier)
        if type(offset) is not int or offset<0 or type(characters) is not int or not 1<=characters<=6000:
            raise ValueError('invalid_evidence_read_range')
        item=self.documents[identifier]
        if offset>=len(body(item)):return dict(status='out_of_range',id=identifier,characters=len(body(item)))
        self.accessed[identifier]=item
        end=min(offset+characters,len(body(item)))
        self.prepare_ranges(identifier,[(offset,end)],'read_excerpt')
        return dict(status='ok',**self.metadata(item),offset=offset,
            text=body(item)[offset:end],has_more=end<len(body(item)),
            model_input_scope='all_stored_text' if offset==0 and end==len(body(item)) else 'tool_return_fragment')

    def record(self,request,result):
        self.journal.append(dict(request=request,result=result))
        # Journal contains evidence excerpts; it has the same short lifetime.
        save_json(self.path/'retrieval.json',self.journal)

    def finish(self,success):
        self.meta['status']='complete' if success else 'failed'
        usage=self.usage()
        save_json(self.path/'usage.json',usage)
        if success:
            save_json(self.path/'sources.json',usage['sources'])
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

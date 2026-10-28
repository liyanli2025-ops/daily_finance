"""Reuse an already verified script only for exactly the same report facts and routing."""
import hashlib
import json
from pathlib import Path

from ..config import settings
from .research_hub import save_json
from .spoken_editing import tts_text,TTS_TEXT_VERSION
from .editorial_policy import SPOKEN_POLICY,EDITION_BRIEFS

ROOT=Path(__file__).resolve().parents[2]/'data/diagnostics/verified-scripts'


def signature(report,nickname):
    facts={name:getattr(report,name,None) for name in ['title','report_date','report_type','content','summary','core_opinions']}
    routing={name:getattr(settings,name,None) for name in ['ai_provider','ai_model','podcast_provider','podcast_model',
        'podcast_reasoning_effort','review_provider','review_model','review_reasoning_effort',
        'openai_base_url','backup_ai_model','backup_ai_base_url']}
    value=json.dumps(dict(policy=SPOKEN_POLICY,edition_briefs=EDITION_BRIEFS,tts_text_version=TTS_TEXT_VERSION,facts=facts,routing=routing,nickname=nickname),
                     ensure_ascii=False,sort_keys=True,default=str)
    return hashlib.sha256(value.encode()).hexdigest()


def load(report,nickname,directory=None):
    key=signature(report,nickname)
    path=(Path(directory) if directory is not None else ROOT)/(key+'.json')
    try:
        value=json.loads(path.read_text(encoding='utf-8'))
        script=value.get('script')
        if (value.get('verified') is True and value.get('signature')==key and isinstance(script,str)
                and script.replace('[SECTION_BREAK]','').strip() and len(script)<=4000
                and tts_text(script)==script
                and hashlib.sha256(script.encode()).hexdigest()==value.get('script_sha256')):
            return script
    except (OSError,ValueError,TypeError):
        pass
    return None


def save(report,nickname,script,directory=None):
    if tts_text(script)!=script or not script.replace('[SECTION_BREAK]','').strip():
        raise ValueError('不能缓存未经规范化核验的口播文本')
    key=signature(report,nickname)
    try:
        save_json((Path(directory) if directory is not None else ROOT)/(key+'.json'),
                  dict(signature=key,script=script,verified=True,script_sha256=hashlib.sha256(script.encode()).hexdigest()))
    except OSError as error:
        print('[口播缓存] 保存失败：'+type(error).__name__,flush=True)

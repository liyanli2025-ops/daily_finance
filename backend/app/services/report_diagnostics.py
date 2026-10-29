"""Private review artifacts for reproducing failures without another model call."""
import json
import os
from pathlib import Path
import tempfile
import uuid


def save_spoken_case(report,raw,script,audit,directory=None,editorial_plan=None):
    from .research_hub import save_json
    from .spoken_editing import TTS_TEXT_VERSION
    import hashlib
    from .time_context import china_now
    folder=Path(directory) if directory else Path(__file__).resolve().parents[2]/'data/diagnostics'
    target=folder/('spoken-'+uuid.uuid4().hex+'.json')
    try:
        save_json(target,dict(owner='finance-spoken-v1',at=china_now().isoformat(),
            status='not_approved',report_id=getattr(report,'id',None),
            report_content=report.content,raw_script=raw,script=script,reading_load=audit,editorial_plan=editorial_plan,
            tts_text_version=TTS_TEXT_VERSION,script_sha256=hashlib.sha256(script.encode('utf-8')).hexdigest(),
            limitation='生成/清洗检查点，不代表通过事实核验、音频合成或人工听感验收'))
    except OSError as error:
        raise RuntimeError('口播检查点保存失败，停止后续模型请求：'+type(error).__name__) from None
    print('[口播诊断] 已保存：'+str(target),flush=True)
    return target


def mark_spoken_case(path,status,error=None):
    from .research_hub import save_json
    if status not in {'format_rejected','review_failed','passed_model_review'}:raise ValueError('invalid_spoken_status')
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('owner')!='finance-spoken-v1':raise ValueError('unknown_spoken_case')
    data.update(status=status,error_type=error)
    save_json(Path(path),data)


def save_generation_stage(stage,response,directory=None):
    """Checkpoint completed text before parsing or another paid call; no headers/reasoning."""
    if stage not in {'draft_response','repair_response','review_response','spoken_review_response','spoken_response','watchlist_changed_response'} or not isinstance(response,str) or not response.strip():
        raise ValueError('invalid_generation_checkpoint')
    from .research_hub import save_json
    from .time_context import china_now
    folder=Path(directory) if directory else Path(__file__).resolve().parents[2]/'data/diagnostics'
    path=folder/('generation-'+stage+'-'+uuid.uuid4().hex+'.json')
    from .episode_workspace import current_workspace
    workspace=current_workspace()
    try:
        save_json(path,dict(stage=stage,at=china_now().isoformat(),response=response,
            evidence_usage=workspace.usage() if workspace is not None else None,
            status='unreviewed',limitation='完整模型回复，仅供恢复及核验；不代表已通过审查或可发布'))
    except OSError as error:
        # Do not spend more on review/repair if an already-paid result cannot be preserved.
        raise RuntimeError('模型回复检查点保存失败，停止后续模型请求：'+type(error).__name__) from None
    print('[诊断] 完整生成阶段已保存：'+str(path),flush=True)
    return path


def save_review_case(report, metadata, review, finance, cross, market, context,
                     repaired, directory=None):
    directory = Path(directory) if directory else Path(__file__).resolve().parents[2] / 'data' / 'diagnostics'
    temporary = None
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        # No environment, credentials, model request headers, or provider responses.
        case = dict(content=report.content, metadata=metadata, review=review,
                    finance_evidence=finance, cross_evidence=cross,
                    market_evidence=market, generation_context=context, repaired=repaired)
        target = directory / ('review-' + uuid.uuid4().hex + '.json')
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory,
                                         prefix='.review-', delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            json.dump(case, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, target)
        print(f'[诊断] 完整审查材料已保存：{target}', flush=True)
        return target
    except OSError as error:
        raise RuntimeError('审查材料保存失败，停止后续模型请求：'+type(error).__name__) from None
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()

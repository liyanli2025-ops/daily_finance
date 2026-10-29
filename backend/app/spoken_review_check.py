"""Replay a saved speech-review checkpoint locally, without model or audio calls."""
import argparse
import json
from pathlib import Path
from .services.spoken_fidelity import assess


def check(path):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('stage')!='spoken_review_response': raise ValueError('要求口播审查检查点')
    context=data.get('context')
    if not isinstance(context,dict) or any(not isinstance(context.get(k),str) for k in ('report_body','script')):
        raise ValueError('旧检查点缺少绑定的正文和口播；不能猜测或自动重跑模型')
    raw=data['response'].strip()
    if raw.startswith('```json') and raw.endswith('```'): raw=raw[7:-3].strip()
    elif raw.startswith('```') and raw.endswith('```'): raw=raw[3:-3].strip()
    try: result=json.loads(raw)
    except ValueError: return dict(mode='offline_saved_review',http_requests=0,model_requests=0,status='malformed_saved_response',publish_approved=False)
    anchors=assess(result,context['report_body'],context['script'])
    return dict(mode='offline_saved_review',http_requests=0,model_requests=0,
        model_passed=result.get('passed') if isinstance(result,dict) else None,
        anchor_check=anchors,publish_approved=False,
        checks=result.get('checks',[]) if isinstance(result,dict) else [],
        limitation='复核已有审查原句，不调用模型，不证明语义正确，不发布、不改缓存或暂停状态')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--case',type=Path,required=True)
    print(json.dumps(check(parser.parse_args().case),ensure_ascii=False,indent=2))

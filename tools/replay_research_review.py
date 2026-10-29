"""Replay a user-exported research archive locally. Never fetch or call a model."""
import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
from unittest.mock import patch
import zipfile

BASELINE='f46d6fe'


def replay(archive,output):
    repo=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(repo/'backend'))
    from app.services import research_hub as current
    from app.services.episode_workspace import EpisodeWorkspace
    from app.services.watchlist_service import WatchlistStock
    raw=Path(archive).read_bytes()
    with zipfile.ZipFile(archive) as source:
        data=json.loads(source.read('research-review.json'))
        original_prompt=source.read('initial-prompt.txt').decode('utf-8')
    now=datetime.fromisoformat(data['created_at']);contexts=data['contexts']
    stocks=[WatchlistStock(row['key'].split(':')[1],row['name'],row['key'].split(':')[0]) for row in contexts]
    # Execute only trusted historical local Git code, never archive text.
    name='app.services._research_review_baseline'
    baseline=types.ModuleType(name);baseline.__package__='app.services'
    baseline.__file__=str(repo/'backend/app/services/research_hub.py');sys.modules[name]=baseline
    code=subprocess.check_output(['git','-C',str(repo),'show',BASELINE+':backend/app/services/research_hub.py']).decode('utf-8')
    exec(compile(code,baseline.__file__,'exec'),baseline.__dict__)
    reports={};objects={}
    for label,module in [('before',baseline),('after',current)]:
        hub=module.ResearchHub()
        with patch.object(hub,'load',return_value=contexts),patch.object(module,'china_now',return_value=now):
            prompt,evidence=hub.prompt(stocks,max_characters=8000)
            pool=hub.evidence_pool(stocks)
        objects[label]=(evidence,pool)
        reports[label]=dict(prompt_characters=len(prompt),prepared_records=len(evidence),
            prepared_original_characters=sum(row['selected_characters'] for row in hub.prompt_reading),
            source_body_characters=sum(row.get('source_body_characters',0) for row in hub.prompt_reading) if any('source_body_characters' in row for row in hub.prompt_reading) else None,
            kinds=dict(Counter(item.kind for item in evidence)),reading=hub.prompt_reading,
            selected=[dict(id=item.id,title=item.title,kind=item.kind,scope=item.scope) for item in evidence])
        if label=='before':
            reports[label]['exact_prompt_match']=prompt==original_prompt
            assert prompt==original_prompt,'Historical reconstruction differs from the exported real input'
        else:
            reports[label]['prepared_source_documents']=len({item.source_id for item in evidence})
            reports[label]['prompt']=prompt
    collisions={}
    with tempfile.TemporaryDirectory(prefix='finance-real-research-replay-') as folder:
        for label,(evidence,pool) in objects.items():
            workspace=EpisodeWorkspace([],folder,now)
            try:
                # Historical dataclass objects are converted as data only, so
                # workspace membership uses the current material type.
                workspace.add([current.Material(**asdict(item)) for item in evidence])
                workspace.add([current.Material(**asdict(item)) for item in pool])
                collisions[label]=dict(status='ok',pool_views=len(workspace.documents))
            except ValueError as error:
                collisions[label]=dict(status='rejected',error=str(error))
            finally:workspace.finish(False)
    result=dict(mode='real_export_local_replay_no_models',archive_sha256=hashlib.sha256(raw).hexdigest(),
        exported_at=data['created_at'],cached_records=sum(len(row.get('materials',[])) for row in contexts),
        results=reports,workspace=collisions,
        limitation='Historical exported cache; exact old prompt reproduction verifies input assembly, not factual validity or investing quality. No collection, model, TTS, production or App writes.')
    Path(output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return {key:value for key,value in result.items() if key not in {'results'}}|{'results':{key:{k:v for k,v in value.items() if k not in {'reading','selected','prompt'}} for key,value in reports.items()}}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(replay(args.archive,args.output),ensure_ascii=False,indent=2))

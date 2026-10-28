"""Read-only market-model replay from a saved daily snapshot; no APIs or LLM."""
import argparse
import json
from pathlib import Path
from .services.market_model import build,compact


def inspect(path):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    result=build(data['instruments']);reduced=compact(result)
    return dict(mode='historical_model_replay_not_current_or_predictive',
        snapshot_collected_at=data.get('collected_at'),
        prompt_characters=len(json.dumps(reduced,ensure_ascii=False,separators=(',',':'))),
        full_diagnostics=result,prompt_context=reduced)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(inspect(args.case),ensure_ascii=False,indent=2))

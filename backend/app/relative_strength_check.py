"""Replay a saved daily snapshot; never refresh markets or call models."""
import argparse
import json
from pathlib import Path
from .services.relative_strength import build,compact


def inspect(path):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    context=build(data['instruments'])
    return dict(mode='saved_daily_replay_not_current',snapshot_collected_at=data.get('collected_at'),
        coverage=dict(requested=len(context['comparisons']),
            compared=sum(row['status']=='ok' for row in context['comparisons'])),
        **compact(context))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(inspect(args.case),ensure_ascii=False,indent=2))
